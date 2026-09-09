import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.monitor.docker import DetectionResult
from apps.monitor.executors import dispatch, monitor_worker_handler
from apps.monitor.models import Detection
from apps.monitor.resource import check_target, parse_config, validate_payload
from apps.monitor.utils import _build_trigger_message, handle_ai_post_task
from apps.monitor.views import DetectionView, get_overview, prepare_resource_form, run_test
from libs import AttrDict


CONFIG = {'metric': 'cpu', 'operator': 'gte', 'value': 85, 'mount': ''}
PROBE = '''cpu 100 0 0 100 0 0 0 0
MemTotal: 1000 kB
MemAvailable: 150 kB
SPUG_PROBE_NET
SPUG_PROBE_STAT2
cpu 190 0 0 110 0 0 0 0
SPUG_PROBE_NET
SPUG_PROBE_DISK
/dev/sda 1000 100 900 10% /
/dev/sdb 1000 900 100 90% /data
SPUG_PROBE_TEMP
package|65000
board|70000
SPUG_PROBE_GPU
10, 100, 1000, 75
'''


def make_host(output=PROBE, exit_code=0):
    host = MagicMock(id=7, is_verified=True, hostname='10.0.0.7')
    host.name = 'resource-host'
    ssh = host.get_ssh.return_value.__enter__.return_value
    ssh.exec_command_raw.return_value = exit_code, output
    return host


def make_detection(**kwargs):
    fields = dict(id=9, name='resource monitor', group='ops', type='7', targets='[7]',
                  extra=json.dumps(CONFIG), notify_grp='[]', notify_mode='[]')
    fields.update(kwargs)
    return Detection(**fields)


class ResourceConfigTests(SimpleTestCase):
    def test_object_and_json_string_have_same_normalized_schema(self):
        self.assertEqual(parse_config(CONFIG), CONFIG)
        self.assertEqual(parse_config(json.dumps(CONFIG)), CONFIG)
        self.assertEqual(parse_config({k: v for k, v in CONFIG.items() if k != 'mount'}), CONFIG)

    def test_bad_schema_operator_and_values_are_rejected(self):
        invalid = [None, [], True, 123, 'bad json', '{}', '[]',
                   {**CONFIG, 'metric': 'swap'}, {**CONFIG, 'metric': []},
                   {**CONFIG, 'operator': 'gt'}, {**CONFIG, 'operator': None},
                   {**CONFIG, 'unknown': 1}]
        invalid += [{**CONFIG, 'value': value} for value in
                    (None, True, False, '85', [], {}, -1, 100.1, float('nan'),
                     float('inf'), float('-inf'), 10 ** 400)]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_config(value)

    def test_temperature_and_percentage_range_boundaries(self):
        for metric, maximum in [('cpu', 100), ('memory', 100), ('disk', 100), ('temperature', 250)]:
            for value in (0, maximum):
                with self.subTest(metric=metric, value=value):
                    self.assertEqual(parse_config({**CONFIG, 'metric': metric, 'value': value})['value'], value)
            with self.assertRaises(ValueError):
                parse_config({**CONFIG, 'metric': metric, 'value': maximum + 1})

    def test_mount_requires_absolute_path_and_disk_metric(self):
        for mount in (None, [], True, 'data', '/data\n', '/data\x00'):
            with self.subTest(mount=mount), self.assertRaises(ValueError):
                parse_config({**CONFIG, 'metric': 'disk', 'mount': mount})
        with self.assertRaises(ValueError):
            parse_config({**CONFIG, 'mount': '/'})
        self.assertEqual(parse_config({**CONFIG, 'metric': 'disk', 'mount': '/data'})['mount'], '/data')

    def test_targets_are_strict_distinct_positive_integer_ids(self):
        for targets in (None, [], {}, '[7]', ['7'], [True], [7.0], [-1], [0], [7, 7], [2 ** 40]):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                validate_payload({'targets': targets, 'extra': CONFIG})
        validate_payload({'targets': [7, 8], 'extra': CONFIG})

    def test_schedule_defaults_and_existing_ui_options_are_supported(self):
        for rate in (1, 5, 15, 30, 60):
            for threshold in (1, 2, 3, 4, 5):
                validate_payload({'targets': [7], 'extra': CONFIG, 'rate': rate,
                                  'threshold': threshold, 'quiet': 1440})
        validate_payload({'targets': [7], 'extra': CONFIG, 'quiet': 0})
        for field in ('rate', 'threshold', 'quiet'):
            for value in (True, 1.5, '5', -1, None, 2 ** 40):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_payload({'targets': [7], 'extra': CONFIG, field: value})
        for field in ('rate', 'threshold'):
            with self.assertRaises(ValueError):
                validate_payload({'targets': [7], 'extra': CONFIG, field: 0})


class ResourceProbeTests(SimpleTestCase):
    def check(self, metric='cpu', output=PROBE, **config):
        return check_target(make_host(output), {**CONFIG, 'metric': metric, **config})

    def test_cpu_uses_delta_percent_and_equality_triggers_alarm(self):
        for limit, expected in ((89.9, False), (90, False), (90.1, True)):
            result = self.check(value=limit)
            self.assertEqual(result.is_ok, expected)
            self.assertEqual(result.details['value'], 90)
            self.assertEqual(result.failure_kind, '' if expected else 'target')

    def test_memory_uses_percentage_not_gigabytes(self):
        result = self.check('memory')
        self.assertFalse(result.is_ok)
        self.assertEqual(result.details['value'], 85)
        self.assertEqual(result.details['unit'], '%')

    def test_disk_defaults_to_highest_or_uses_exact_mount(self):
        result = self.check('disk')
        self.assertFalse(result.is_ok)
        self.assertEqual(result.details['mount'], '/data')
        result = self.check('disk', mount='/')
        self.assertTrue(result.is_ok)
        self.assertEqual(result.details['value'], 10)
        self.assertEqual(self.check('disk', mount='/missing').failure_kind, 'infrastructure')

    def test_disk_mount_names_with_spaces_remain_exact(self):
        result = self.check('disk', output=PROBE.replace('/data', '/data files'), mount='/data files')
        self.assertFalse(result.is_ok)
        self.assertEqual(result.details['mount'], '/data files')
        self.assertEqual(result.details['value'], 90)

    def test_malformed_disk_row_cannot_hide_behind_a_healthy_disk(self):
        output = PROBE.replace('/dev/sdb 1000 900', '/dev/sdb invalid 900')
        result = self.check('disk', output=output)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.failure_kind, 'infrastructure')

    def test_temperature_takes_highest_sysfs_and_gpu_in_celsius(self):
        result = self.check('temperature', value=75)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.details['value'], 75)
        self.assertEqual(result.details['unit'], 'C')
        result = self.check('temperature', output=PROBE.replace('board|70000', 'board|95000'))
        self.assertEqual(result.details['value'], 95)

    def test_gpu_temperature_survives_unsupported_other_fields(self):
        output = PROBE.replace('10, 100, 1000, 75', '[N/A], [N/A], [N/A], 92')
        result = self.check('temperature', output=output)
        self.assertFalse(result.is_ok)
        self.assertEqual(result.details['value'], 92)

    def test_gpu_only_and_sysfs_only_temperatures_are_usable(self):
        gpu_only = PROBE.replace('package|65000\nboard|70000\n', '')
        self.assertEqual(self.check('temperature', output=gpu_only).details['value'], 75)
        sysfs_only = PROBE.replace('10, 100, 1000, 75', '[N/A], [N/A], [N/A], [N/A]')
        self.assertEqual(self.check('temperature', output=sysfs_only).details['value'], 70)

    def test_no_sensors_and_invalid_gpu_values_are_infrastructure(self):
        output = PROBE.replace('package|65000\nboard|70000\n', '')
        for reading in ('[N/A]', 'NaN', 'inf', '-1', '251'):
            result = self.check('temperature', output=output.replace('10, 100, 1000, 75',
                                                                     f'N/A, N/A, N/A, {reading}'))
            self.assertFalse(result.is_ok)
            self.assertEqual(result.failure_kind, 'infrastructure')
            self.assertIn('no readable', result.message)

    def test_true_zero_readings_remain_valid(self):
        output = PROBE.replace('MemAvailable: 150', 'MemAvailable: 1000')
        result = self.check('memory', output=output)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.details['value'], 0)

    def test_empty_malformed_missing_or_impossible_data_never_recovers(self):
        cases = [('cpu', ''), ('cpu', 'bad output'), ('cpu', PROBE.replace('cpu 190', 'cpu bad')),
                 ('cpu', PROBE.replace('cpu 190 0 0 110', 'cpu 100 0 0 100')),
                 ('memory', PROBE.replace('MemAvailable: 150 kB\n', '')),
                 ('memory', PROBE.replace('MemAvailable: 150', 'MemAvailable: 2000')),
                 ('disk', PROBE.replace('/dev/sda 1000 100 900 10% /\n', '')
                  .replace('/dev/sdb 1000 900 100 90% /data\n', ''))]
        for metric, output in cases:
            with self.subTest(metric=metric, output=output):
                result = self.check(metric, output=output)
                self.assertFalse(result.is_ok)
                self.assertEqual(result.failure_kind, 'infrastructure')

    def test_nonzero_exit_ssh_error_missing_and_unverified_hosts(self):
        hosts = [None, make_host(exit_code=1), make_host(), make_host()]
        hosts[2].is_verified = False
        hosts[3].get_ssh.side_effect = OSError('ssh down')
        for host in hosts:
            result = check_target(host, CONFIG)
            self.assertFalse(result.is_ok)
            self.assertEqual(result.failure_kind, 'infrastructure')

    def test_untrusted_mount_never_enters_command(self):
        from apps.host.metrics import PROBE_COMMAND_FULL
        host = make_host()
        result = check_target(host, {**CONFIG, 'metric': 'disk', 'mount': '/$(touch /tmp/unwanted)'})
        self.assertEqual(result.failure_kind, 'infrastructure')
        host.get_ssh.return_value.__enter__.return_value.exec_command_raw.assert_called_once_with(PROBE_COMMAND_FULL)

    @patch('apps.monitor.executors.Host.objects.filter')
    def test_dispatch_routes_type_seven_and_missing_hosts(self, hosts):
        hosts.return_value.first.return_value = make_host()
        self.assertEqual(dispatch('7', 7, CONFIG).details['metric'], 'cpu')
        hosts.return_value.first.return_value = None
        self.assertEqual(dispatch('7', 7, CONFIG).failure_kind, 'infrastructure')


class ResourceApiTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(has_perms=lambda codes: True)
        self.factory = RequestFactory()
        self.hosts = self.enterContext(patch('apps.monitor.views.Host.objects.filter', return_value=[make_host()]))
        self.permission = self.enterContext(patch('apps.monitor.views.has_host_perm', return_value=True))
        self.create = self.enterContext(patch('apps.monitor.views.Detection.objects.create', return_value=SimpleNamespace(id=9)))
        self.redis = self.enterContext(patch('apps.monitor.views.get_redis_connection'))
        self.dispatch = self.enterContext(patch('apps.monitor.views.dispatch', return_value=DetectionResult(False, 'missing', 'infrastructure')))

    def payload(self, **kwargs):
        return dict(type='7', name='resource', group='ops', targets=[7], extra=CONFIG,
                    notify_grp=[1], notify_mode=['4'], **kwargs)

    def request(self, payload, method='post'):
        request = getattr(self.factory, method)('/monitor/', json.dumps(payload), content_type='application/json')
        request.user = self.user
        return request

    def test_save_serializes_config_and_reuses_scheduler_queue(self):
        response = DetectionView().post(self.request(self.payload()))
        self.assertFalse(json.loads(response.content)['error'])
        saved = self.create.call_args.kwargs
        self.assertEqual(json.loads(saved['extra']), CONFIG)
        self.assertEqual(json.loads(saved['targets']), [7])
        self.assertEqual((saved['rate'], saved['threshold'], saved['quiet']), (5, 3, 1440))
        queued = json.loads(self.redis.return_value.lpush.call_args.args[1])
        self.assertEqual((queued['type'], queued['action']), ('7', 'add'))
        self.dispatch.assert_not_called()

    def test_update_serializes_resource_config_and_modifies_active_job(self):
        with patch('apps.monitor.views.Detection.objects.filter') as detections:
            detections.return_value.first.return_value = make_detection()
            response = DetectionView().post(self.request(self.payload(id=9)))
            self.assertFalse(json.loads(response.content)['error'])
            self.assertEqual(json.loads(detections.return_value.update.call_args.kwargs['extra']), CONFIG)
        queued = json.loads(self.redis.return_value.lpush.call_args.args[1])
        self.assertEqual(queued['action'], 'modify')
        self.create.assert_not_called()

    def test_save_and_test_reject_bad_schema_before_database_or_probe(self):
        for replacement in ({'extra': []}, {'extra': {**CONFIG, 'value': float('nan')}},
                            {'rate': 1.5}, {'threshold': True}, {'targets': '[7]'},
                            {'targets': [True]}, {'targets': [7, 7]}):
            payload = {**self.payload(), **replacement}
            for view in (DetectionView().post, run_test):
                with self.subTest(replacement=replacement, view=view):
                    response = view(self.request(payload))
                    self.assertTrue(json.loads(response.content)['error'])
        self.create.assert_not_called()
        self.dispatch.assert_not_called()
        self.hosts.assert_not_called()
        self.redis.assert_not_called()

    def test_save_and_test_check_all_host_permissions(self):
        self.permission.return_value = False
        payload = {**self.payload(), 'targets': [7, 8]}
        for view in (DetectionView().post, run_test):
            response = view(self.request(payload))
            self.assertTrue(json.loads(response.content)['error'])
        self.permission.assert_called_with(self.user, [7, 8])
        self.hosts.assert_not_called()
        self.create.assert_not_called()
        self.dispatch.assert_not_called()

    def test_missing_and_unverified_hosts_rejected_without_probe(self):
        for hosts in ([], [SimpleNamespace(is_verified=False)]):
            self.hosts.return_value = hosts
            response = run_test(self.request(self.payload()))
            self.assertTrue(json.loads(response.content)['error'])
        self.dispatch.assert_not_called()

    def test_test_returns_failure_kind_and_only_probes_first_authorized_target(self):
        self.hosts.return_value = [make_host(), make_host()]
        payload = {**self.payload(), 'targets': [7, 8]}
        response = run_test(self.request(payload))
        data = json.loads(response.content)['data']
        self.assertFalse(data['is_success'])
        self.assertEqual(data['failure_kind'], 'infrastructure')
        self.dispatch.assert_called_once_with('7', 7, json.dumps(CONFIG))
        self.permission.assert_called_with(self.user, [7, 8])

    def test_ai_is_bound_to_single_selected_host(self):
        form = AttrDict(type='7', targets=[7], extra=CONFIG, ai_mode='repair', ai_host_id=99)
        self.assertIsNone(prepare_resource_form(self.user, form))
        self.assertEqual(form.ai_host_id, 7)
        self.hosts.return_value = [make_host(), make_host()]
        form = AttrDict(type='7', targets=[7, 8], extra=CONFIG, ai_mode='repair')
        self.assertIsNotNone(prepare_resource_form(self.user, form))

    def test_reenable_requires_host_permission_before_update(self):
        self.permission.return_value = False
        with patch('apps.monitor.views.Detection.objects.filter') as detections:
            detections.return_value.first.return_value = make_detection()
            response = DetectionView().patch(self.request({'id': 9, 'is_active': True}, 'patch'))
            self.assertTrue(json.loads(response.content)['error'])
            detections.return_value.update.assert_not_called()
        self.redis.assert_not_called()

    def test_model_decodes_extra_and_preserves_host_ids(self):
        data = make_detection().to_view()
        self.assertEqual(data['extra'], CONFIG)
        self.assertEqual(data['targets'], [7])
        self.assertEqual(data['type_alias'], '\u8d44\u6e90\u76d1\u63a7')

    def test_list_adds_host_name_map_without_changing_targets(self):
        query = MagicMock()
        query.__iter__.side_effect = lambda: iter([make_detection()])
        query.order_by.return_value.values.return_value.distinct.return_value = [{'group': 'ops'}]
        with patch('apps.monitor.views.Detection.objects.all', return_value=query):
            response = DetectionView().get(self.request({}))
        row = json.loads(response.content)['data']['detections'][0]
        self.assertEqual(row['targets'], [7])
        self.assertEqual(row['target_names'], {'7': 'resource-host(10.0.0.7)'})

    def test_overview_resolves_host_names_and_keeps_redis_status(self):
        self.redis.return_value.hgetall.return_value = {b'c_7': b'3', b't_7': b'1000'}
        with patch('apps.monitor.views.Detection.objects.all', return_value=[make_detection(latest_run_time='2026-09-09 01:00:00')]):
            response = get_overview(self.request({}))
        row = json.loads(response.content)['data'][0]
        self.assertEqual(row['target'], 'resource-host(10.0.0.7)')
        self.assertEqual((row['id'], row['status'], row['count']), ('9_7', '3', 3))

    def test_overview_handles_deleted_host(self):
        self.hosts.return_value = []
        with patch('apps.monitor.views.Detection.objects.all', return_value=[make_detection(is_active=False)]):
            response = get_overview(self.request({}))
        row = json.loads(response.content)['data'][0]
        self.assertIn('id=7', row['target'])
        self.assertEqual(row['status'], '0')


class ResourceWorkerTests(SimpleTestCase):
    def setUp(self):
        self.redis = self.enterContext(patch('apps.monitor.executors.get_redis_connection')).return_value
        self.redis.hmget.return_value = (None, None)
        self.redis.hincrby.return_value = 1
        self.hosts = self.enterContext(patch('apps.monitor.executors.Host.objects.filter'))
        self.hosts.return_value.first.return_value = make_host()
        self.dispatch = self.enterContext(patch('apps.monitor.executors.dispatch'))
        self.dispatch.return_value = DetectionResult(False, 'cpu >= 85%', 'target')
        self.notify = self.enterContext(patch('apps.monitor.executors.handle_notify'))
        self.trigger = self.enterContext(patch('apps.monitor.executors.handle_trigger_event'))
        self.ai = self.enterContext(patch('apps.monitor.executors.handle_ai_post_task'))

    def run_worker(self, threshold=3, quiet=60):
        monitor_worker_handler(json.dumps([9, '7', 7, CONFIG, threshold, quiet]))

    def test_below_failure_threshold_does_not_notify(self):
        self.run_worker()
        self.notify.assert_not_called()
        self.trigger.assert_not_called()
        self.ai.assert_not_called()

    def test_threshold_alarm_uses_host_name_and_existing_trigger(self):
        self.redis.hincrby.return_value = 3
        self.run_worker()
        self.trigger.assert_called_once_with(9, 7)
        self.notify.assert_called_once_with(9, 'resource-host(10.0.0.7)', False, 'cpu >= 85%', 3)
        self.assertIs(self.ai.call_args.args[-1], self.dispatch.return_value)

    def test_infrastructure_failure_still_uses_alarm_channel(self):
        self.dispatch.return_value = DetectionResult(False, 'no sensors', 'infrastructure')
        self.run_worker(threshold=1)
        self.notify.assert_called_once_with(9, 'resource-host(10.0.0.7)', False, 'no sensors', 1)

    @patch('apps.monitor.executors.time.time', return_value=1100)
    def test_quiet_period_suppresses_repeat_alarm(self, _time):
        self.redis.hmget.return_value = (b'3', b'1000')
        self.redis.hincrby.return_value = 4
        self.run_worker()
        self.notify.assert_not_called()
        self.ai.assert_not_called()

    @patch('apps.monitor.executors.time.time', return_value=5000)
    def test_quiet_expiry_repeats_alarm(self, _time):
        self.redis.hmget.return_value = (b'3', b'1000')
        self.redis.hincrby.return_value = 4
        self.run_worker()
        self.notify.assert_called_once()

    def test_recovery_clears_counts_and_sends_recovery_notification(self):
        self.redis.hmget.return_value = (b'3', b'1000')
        self.dispatch.return_value = DetectionResult(True, 'cpu < 85%')
        self.run_worker()
        self.redis.hdel.assert_called_once_with('spug:det:9', 'c_7', 't_7')
        self.notify.assert_called_once_with(9, 'resource-host(10.0.0.7)', True, 'cpu < 85%', 4)
        self.ai.assert_not_called()

    @patch('apps.ai.agent.run_session')
    @patch('apps.ai.models.AgentSession.objects.create')
    @patch('apps.monitor.utils.Detection.objects.filter')
    def test_infrastructure_cannot_start_ai_repair_or_diagnosis(self, detections, create, run):
        for mode in ('repair', 'diagnose'):
            detections.return_value.first.return_value = make_detection(ai_mode=mode, ai_host_id=7)
            result = handle_ai_post_task(9, 'resource-host', 'no sensors', 3, result=DetectionResult(False, 'no sensors', 'infrastructure'))
            self.assertIsNone(result)
        create.assert_not_called()
        run.assert_not_called()

    def test_ai_prompt_includes_resource_metric_limit_and_mount(self):
        config = {**CONFIG, 'metric': 'disk', 'mount': '/data'}
        message = _build_trigger_message(make_detection(extra=json.dumps(config)), 'resource-host', 'usage high')
        for text in ('resource-host', 'disk', '85%', '/data'):
            self.assertIn(text, message)


class ResourceIntegrationTests(SimpleTestCase):
    def test_migration_state_matches_model_without_database_connection(self):
        from django.db.migrations.loader import MigrationLoader
        loader = MigrationLoader(None)
        state = loader.project_state()
        field = state.models['monitor', 'detection'].fields['type']
        self.assertEqual(list(field.choices), list(Detection._meta.get_field('type').choices))
        self.assertIn(('monitor', '0004_resource_detection'), loader.graph.leaf_nodes())

    @patch('apps.monitor.scheduler.connections.close_all')
    @patch('apps.monitor.scheduler.get_redis_connection')
    @patch('apps.monitor.scheduler.Detection.objects.filter')
    def test_scheduler_dispatches_resource_job_for_each_host(self, detections, redis, _close):
        from apps.monitor.scheduler import Scheduler
        Scheduler._dispatch(None, 9, '7', '[7, 8]', json.dumps(CONFIG), 3, 1440)
        jobs = [json.loads(call.args[1]) for call in redis.return_value.rpush.call_args_list]
        self.assertEqual(jobs, [[9, '7', host, json.dumps(CONFIG), 3, 1440] for host in (7, 8)])
        detections.return_value.update.assert_called_once()

    def test_legacy_types_one_to_five_keep_dispatch_contract(self):
        cases = [('1', 'site_check', 'https://example.test', ''),
                 ('2', 'port_check', 'example.test', '80'),
                 ('3', 'host_executor', 7, 'nginx'),
                 ('4', 'host_executor', 7, 'exit 0'),
                 ('5', 'ping_check', 'example.test', '')]
        for kind, checker, target, extra in cases:
            with self.subTest(kind=kind), patch(f'apps.monitor.executors.{checker}', return_value=(True, 'ok')) as check, patch('apps.monitor.executors.Host.objects.filter'):
                result = dispatch(kind, target, extra)
                self.assertEqual(tuple(result), (True, 'ok'))
                self.assertEqual(result.failure_kind, '')
                check.assert_called_once()
