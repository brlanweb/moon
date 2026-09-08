from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.monitor.docker import (
    DetectionResult,
    check_target,
    evaluate_target,
    may_start_repair,
    record_repair_started,
    record_repair_write,
    repair_target_key,
    startup_grace_seconds,
    validate_and_normalize_scope,
    verify_recovery,
)
from apps.monitor.executors import dispatch, monitor_worker_handler
from apps.monitor.models import Detection
from apps.monitor.views import prepare_docker_form
from apps.monitor.utils import handle_ai_post_task
from libs import AttrDict


class DockerMonitorEvaluationTests(SimpleTestCase):
    NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)
    SCOPE = {
        'version': 1,
        'kind': 'compose_service',
        'project': 'demo',
        'workdir': '/opt/demo',
        'config_files': ['/opt/demo/compose.yml'],
        'service': 'api',
        'expected_replicas': 2,
        'config_hash': 'hash-1',
    }

    @staticmethod
    def container(name, state='running', health='healthy', started_at='2026-09-08T01:00:00Z',
                  start_period=0, interval=30_000_000_000, retries=3, restart_count=0):
        return {
            'name': name,
            'service': 'api',
            'state': state,
            'health': health,
            'started_at': started_at,
            'restart_count': restart_count,
            'config_hash': 'hash-1',
            'health_start_period_ns': start_period,
            'health_interval_ns': interval,
            'health_retries': retries,
            'image': 'demo:latest',
            'ports': [],
        }

    def payload(self, containers):
        return {
            'projects': [{
                'name': 'demo',
                'workdir': '/opt/demo',
                'config_file': '/opt/demo/compose.yml',
                'config_files': ['/opt/demo/compose.yml'],
                'containers': containers,
            }],
            'standalone': [],
        }

    def test_compose_fails_when_replica_count_is_below_saved_baseline(self):
        result = evaluate_target(self.SCOPE, self.payload([self.container('demo-api-1')]), self.NOW)

        self.assertFalse(result.is_ok)
        self.assertEqual(result.failure_kind, 'target')
        self.assertIn('副本缺失', result.message)

    def test_compose_fails_when_any_replica_is_unhealthy(self):
        result = evaluate_target(self.SCOPE, self.payload([
            self.container('demo-api-1'),
            self.container('demo-api-2', health='unhealthy'),
        ]), self.NOW)

        self.assertFalse(result.is_ok)
        self.assertEqual(result.details['abnormal'][0]['name'], 'demo-api-2')
        self.assertIn('unhealthy', result.message)

    def test_starting_uses_healthcheck_start_period_as_grace(self):
        item = self.container(
            'demo-api-1', health='starting', started_at='2026-09-08T01:56:00Z',
            start_period=300_000_000_000)
        payload = self.payload([item, self.container('demo-api-2')])

        result = evaluate_target(self.SCOPE, payload, self.NOW)

        self.assertTrue(result.is_ok)
        self.assertEqual(startup_grace_seconds(item), 300)

    def test_starting_after_dynamic_grace_is_failure(self):
        item = self.container(
            'demo-api-1', health='starting', started_at='2026-09-08T01:54:00Z',
            start_period=300_000_000_000)

        result = evaluate_target(
            self.SCOPE, self.payload([item, self.container('demo-api-2')]), self.NOW)

        self.assertFalse(result.is_ok)
        self.assertIn('starting超时', result.message)

    def test_running_without_healthcheck_is_healthy(self):
        scope = {'version': 1, 'kind': 'standalone_container', 'container': 'worker'}
        item = self.container('worker', health='', interval=0, retries=0)
        item['service'] = ''

        result = evaluate_target(scope, {'projects': [], 'standalone': [item]}, self.NOW)

        self.assertTrue(result.is_ok)

    def test_unknown_standalone_container_is_failure(self):
        scope = {'version': 1, 'kind': 'standalone_container', 'container': 'missing'}

        result = evaluate_target(scope, {'projects': [], 'standalone': []}, self.NOW)

        self.assertFalse(result.is_ok)
        self.assertTrue(result.details['missing'])

    @patch('apps.monitor.docker.discover_all', side_effect=Exception('ssh down'))
    def test_discovery_error_is_classified_as_infrastructure(self, _discover):
        result = check_target(object(), self.SCOPE)

        self.assertFalse(result.is_ok)
        self.assertEqual(result.failure_kind, 'infrastructure')
        self.assertIn('ssh down', result.message)


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, _ttl, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class DockerAiDispatchTests(SimpleTestCase):
    def detection(self):
        return SimpleNamespace(
            id=9, ai_mode='repair', ai_host_id=7, ai_max_loops=3, type='6',
            extra=json.dumps({
                'version': 1, 'kind': 'standalone_container', 'container': 'worker'}),
            name='worker monitor', rate=5, notify_grp='[]', notify_mode='[]',
            get_type_display=lambda: 'Docker服务检测')

    @patch('apps.monitor.utils.Detection.objects.filter')
    def test_infrastructure_failure_does_not_start_ai(self, detections):
        detections.return_value.first.return_value = self.detection()

        outcome = handle_ai_post_task(
            9, 'docker-1', 'SSH连接失败', 3, lambda: None,
            DetectionResult(False, 'SSH连接失败', 'infrastructure'))

        self.assertIsNone(outcome)

    @patch('libs.spug.Notification.dispatch_monitor')
    @patch('apps.ai.agent.run_session')
    @patch('apps.ai.models.AgentSession.objects.create')
    @patch('apps.ai.models.AgentSession.objects.filter')
    @patch('apps.monitor.utils.get_redis_connection', return_value=FakeRedis())
    @patch('apps.monitor.utils.Detection.objects.get')
    @patch('apps.monitor.utils.Detection.objects.filter')
    def test_target_failure_persists_scope_on_ai_session(
            self, detections, get_detection, _redis, sessions, create, run, _notify):
        detection = self.detection()
        detections.return_value.first.return_value = detection
        get_detection.return_value = detection
        sessions.return_value.exists.return_value = False
        session = SimpleNamespace(
            id=12, status='failed', summary='未恢复', used_loops=1, max_loops=3,
            get_status_display=lambda: '未解决')
        create.return_value = session
        run.return_value = session
        result = DetectionResult(False, 'worker=exited', 'target', {
            'containers': [{'name': 'worker', 'state': 'exited', 'restart_count': 1}],
            'verification_timeout': 120,
        })

        handle_ai_post_task(9, 'docker-1', result.message, 3, lambda: None, result)

        kwargs = create.call_args.kwargs
        self.assertEqual(json.loads(kwargs['target_scope'])['container'], 'worker')
        self.assertEqual(kwargs['host_id'], 7)


class WorkerRedis:
    def hmget(self, *_args):
        return None, None

    def hincrby(self, *_args):
        return 1

    def hset(self, *_args):
        return None

    def hdel(self, *_args):
        return None


class DockerMonitorWorkerTests(SimpleTestCase):
    @patch('apps.monitor.executors.handle_ai_post_task')
    @patch('apps.monitor.executors.handle_notify')
    @patch('apps.monitor.executors.handle_trigger_event')
    @patch('apps.monitor.executors.get_redis_connection', return_value=WorkerRedis())
    @patch('apps.monitor.executors.Host.objects.filter')
    @patch('apps.monitor.executors.dispatch')
    def test_worker_routes_docker_result_to_ai_policy(
            self, dispatch_check, hosts, _redis, _trigger, notify, ai_post):
        host = SimpleNamespace(name='docker-1', hostname='10.0.0.7')
        hosts.return_value.first.return_value = host
        result = DetectionResult(False, 'SSH连接失败', 'infrastructure')
        dispatch_check.return_value = result

        monitor_worker_handler(json.dumps([9, '6', 7, '{"version": 1}', 1, 60]))

        notify.assert_called_once()
        self.assertIs(ai_post.call_args.args[-1], result)


class DockerMonitorFormTests(SimpleTestCase):
    def test_detection_view_decodes_docker_scope(self):
        scope = {'version': 1, 'kind': 'standalone_container', 'container': 'worker'}
        detection = Detection(type='6', targets='[7]', extra=json.dumps(scope),
                              notify_mode='[]', notify_grp='[]')

        self.assertEqual(detection.to_view()['extra'], scope)
        self.assertEqual(detection.get_type_display(), 'Docker服务检测')

    @patch('apps.monitor.views.validate_and_normalize_scope')
    @patch('apps.monitor.views.Host.objects.filter')
    @patch('apps.monitor.views.has_host_perm', return_value=True)
    def test_prepare_docker_form_fixes_ai_host_and_serializes_live_scope(
            self, _has_perm, hosts, validate):
        user = type('User', (), {'has_perms': lambda self, perms: True})()
        host = object()
        hosts.return_value.first.return_value = host
        validate.return_value = {
            'version': 1, 'kind': 'standalone_container', 'container': 'worker'}
        form = AttrDict(type='6', targets=[7], extra={'version': 1},
                        ai_mode='repair', ai_host_id=99)

        error = prepare_docker_form(user, form)

        self.assertIsNone(error)
        self.assertEqual(form.ai_host_id, 7)
        self.assertEqual(json.loads(form.extra)['container'], 'worker')
        validate.assert_called_once_with(host, {'version': 1})

    def test_prepare_docker_form_requires_one_host(self):
        user = type('User', (), {'has_perms': lambda self, perms: True})()
        form = AttrDict(type='6', targets=[1, 2], extra={}, ai_mode='')

        self.assertIn('一台', prepare_docker_form(user, form))


class DockerScopeValidationTests(SimpleTestCase):
    PROJECT = {
        'name': 'demo', 'workdir': '/opt/demo',
        'config_file': '/opt/demo/compose.yml',
        'config_files': ['/opt/demo/compose.yml'],
        'containers': [
            {**DockerMonitorEvaluationTests.container('demo-api-1'), 'config_hash': 'hash-1'},
            {**DockerMonitorEvaluationTests.container('demo-api-2'), 'config_hash': 'hash-1'},
        ],
    }

    @patch('apps.monitor.docker.read_service_hash', return_value='hash-1')
    @patch('apps.monitor.docker.discover_all')
    def test_compose_scope_is_rebuilt_from_live_discovery(self, discover, _read_hash):
        discover.return_value = {'projects': [self.PROJECT], 'standalone': []}
        submitted = {
            'version': 1, 'kind': 'compose_service', 'project': 'demo',
            'workdir': '/opt/demo', 'config_files': ['/opt/demo/compose.yml'],
            'service': 'api', 'expected_replicas': 99, 'config_hash': 'forged',
        }

        scope = validate_and_normalize_scope(object(), submitted)

        self.assertEqual(scope['expected_replicas'], 2)
        self.assertEqual(scope['config_hash'], 'hash-1')
        self.assertTrue(scope['can_recover_missing'])

    @patch('apps.monitor.docker.read_service_hash', return_value='changed')
    @patch('apps.monitor.docker.discover_all')
    def test_compose_scope_rejects_config_hash_drift(self, discover, _read_hash):
        discover.return_value = {'projects': [self.PROJECT], 'standalone': []}
        submitted = {
            'version': 1, 'kind': 'compose_service', 'project': 'demo',
            'workdir': '/opt/demo', 'config_files': ['/opt/demo/compose.yml'],
            'service': 'api',
        }

        with self.assertRaisesRegex(Exception, '配置.*不一致'):
            validate_and_normalize_scope(object(), submitted)

    @patch('apps.monitor.docker.read_service_hash', side_effect=Exception('unsupported'))
    @patch('apps.monitor.docker.discover_all')
    def test_hash_capability_failure_disables_missing_replica_recovery(self, discover, _read_hash):
        discover.return_value = {'projects': [self.PROJECT], 'standalone': []}
        submitted = {
            'version': 1, 'kind': 'compose_service', 'project': 'demo',
            'workdir': '/opt/demo', 'config_files': ['/opt/demo/compose.yml'],
            'service': 'api',
        }

        scope = validate_and_normalize_scope(object(), submitted)

        self.assertFalse(scope['can_recover_missing'])
        self.assertEqual(scope['config_hash'], '')

    @patch('apps.monitor.docker.discover_all')
    def test_standalone_scope_rejects_unknown_container(self, discover):
        discover.return_value = {'projects': [], 'standalone': []}

        with self.assertRaisesRegex(Exception, '不存在'):
            validate_and_normalize_scope(object(), {
                'version': 1, 'kind': 'standalone_container', 'container': 'forged'})


class DockerDispatchTests(SimpleTestCase):
    @patch('apps.monitor.executors.check_docker_target')
    @patch('apps.monitor.executors.Host.objects.filter')
    def test_dispatch_routes_docker_monitor_to_structured_checker(self, hosts, checker):
        host = object()
        hosts.return_value.first.return_value = host
        checker.return_value = DetectionResult(False, 'unhealthy', 'target')

        result = dispatch('6', 7, '{"version": 1}')

        self.assertIsInstance(result, DetectionResult)
        self.assertEqual(result.failure_kind, 'target')
        checker.assert_called_once_with(host, '{"version": 1}')

    def test_legacy_dispatch_results_are_normalized(self):
        with patch('apps.monitor.executors.ping_check', return_value=(True, 'ok')):
            result = dispatch('5', '127.0.0.1', None)

        self.assertIsInstance(result, DetectionResult)
        self.assertTrue(result.is_ok)
        self.assertEqual(tuple(result), (True, 'ok'))


class DockerRepairPolicyTests(SimpleTestCase):
    SCOPE = {
        'version': 1, 'kind': 'standalone_container', 'container': 'worker'}

    def setUp(self):
        self.redis = FakeRedis()
        self.key = repair_target_key(7, self.SCOPE)

    def details(self, count=1, state='exited', timeout=120):
        return {
            'verification_timeout': timeout,
            'containers': [{
                'name': 'worker', 'restart_count': count, 'state': state,
            }],
        }

    def test_write_starts_thirty_minute_cooldown(self):
        record_repair_write(self.redis, self.key, now=1000)

        allowed, reason = may_start_repair(
            self.redis, self.key, self.details(), now=1200)

        self.assertFalse(allowed)
        self.assertIn('冷却', reason)
        self.assertTrue(may_start_repair(
            self.redis, self.key, self.details(), now=2801)[0])

    def test_three_sessions_in_six_hours_open_circuit(self):
        for now in (1000, 2000, 3000):
            record_repair_started(self.redis, self.key, now=now)

        allowed, reason = may_start_repair(
            self.redis, self.key, self.details(), now=3100)

        self.assertFalse(allowed)
        self.assertIn('3次', reason)
        self.assertTrue(may_start_repair(
            self.redis, self.key, self.details(), now=22601)[0])

    def test_fast_restart_count_growth_opens_circuit(self):
        self.assertTrue(may_start_repair(
            self.redis, self.key, self.details(count=1), now=1000)[0])

        allowed, reason = may_start_repair(
            self.redis, self.key, self.details(count=4), now=1100)

        self.assertFalse(allowed)
        self.assertIn('重启循环', reason)

    def test_two_consecutive_restarting_samples_open_circuit(self):
        self.assertTrue(may_start_repair(
            self.redis, self.key, self.details(state='restarting'), now=1000)[0])

        allowed, reason = may_start_repair(
            self.redis, self.key, self.details(state='restarting'), now=1100)

        self.assertFalse(allowed)
        self.assertIn('重启循环', reason)

    def test_verification_over_thirty_minutes_is_rejected(self):
        allowed, reason = may_start_repair(
            self.redis, self.key, self.details(timeout=1801), now=1000)

        self.assertFalse(allowed)
        self.assertIn('30分钟', reason)


class DockerRecoveryVerificationTests(SimpleTestCase):
    def test_recovery_requires_two_consecutive_strict_healthy_samples(self):
        samples = iter([
            DetectionResult(False, 'starting', 'target', {'strict_pending': True}),
            DetectionResult(True, 'healthy once', details={'strict_healthy': True}),
            DetectionResult(True, 'healthy twice', details={'strict_healthy': True}),
        ])
        calls = []

        result = verify_recovery(
            None, {}, checker=lambda *_args, **_kwargs: next(samples),
            sleep=lambda seconds: calls.append(seconds), timeout_seconds=60)

        self.assertTrue(result.is_ok)
        self.assertEqual(len(calls), 2)
        self.assertIn('连续2次', result.message)

    def test_starting_never_counts_as_recovered(self):
        samples = iter([
            DetectionResult(False, 'starting', 'target', {'strict_pending': True}),
            DetectionResult(False, 'unhealthy', 'target'),
        ])

        result = verify_recovery(
            None, {}, checker=lambda *_args, **_kwargs: next(samples),
            sleep=lambda _seconds: None, timeout_seconds=60)

        self.assertFalse(result.is_ok)
        self.assertIn('unhealthy', result.message)
