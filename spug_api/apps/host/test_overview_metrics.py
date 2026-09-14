import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.test import SimpleTestCase, RequestFactory
from apps.host.overview_metrics import collect, parse_sample, overview_metrics, probe, COMMAND


def output(cpu='100 0 100 800 0 0 0 0 20 0', gpu='absent'):
    return f'cpu {cpu}\nMemTotal: 1000 kB\nMemAvailable: 600 kB\nSPUG_GPU\n{gpu}\n'


class ChartMetricsTests(SimpleTestCase):
    def test_cpu_delta_excludes_guest_and_first_point_is_missing(self):
        point, stat = parse_sample(output())
        self.assertIsNone(point['cpu'])
        self.assertEqual(stat, [1000, 800])
        point, _ = parse_sample(output('150 0 100 850 0 0 0 0 50 0'), stat)
        self.assertEqual(point['cpu'], 50)
        self.assertEqual(point['memory'], 40)
        self.assertEqual(point['gpu_status'], 'absent')

    def test_reset_missing_memory_and_gpu_failure_are_independent(self):
        point, _ = parse_sample(output(gpu='unavailable').replace('MemAvailable: 600 kB', ''), [2000, 1900])
        self.assertIsNone(point['cpu'])
        self.assertIsNone(point['memory'])
        self.assertEqual(point['gpu'], [])
        point, _ = parse_sample(output(gpu='0, 42\n1, N/A\n2, nan'))
        self.assertEqual(point['gpu'], [{'id': 0, 'value': 42}])
        self.assertIn('timeout -s KILL 2', COMMAND)
        self.assertNotIn('sleep', COMMAND)

    def redis(self):
        values = {}
        rds = Mock()
        rds.get.side_effect = values.get
        def set_value(key, value, **kwargs):
            if key in values: return False
            values[key] = value
            return True
        rds.set.side_effect = set_value
        rds.setex.side_effect = lambda key, ttl, value: values.update({key: value})
        rds.eval.side_effect = lambda script, n, key, token: values.pop(key, None)
        return rds, values

    def test_shared_cache_and_lock_avoid_duplicate_probe(self):
        rds, values = self.redis()
        host = SimpleNamespace(id=1)
        with patch('apps.host.overview_metrics.probe', return_value=output()) as probe:
            first = collect(host, rds)
            self.assertEqual(collect(host, rds), first)
            probe.assert_called_once_with(host)
            self.assertEqual(rds.setex.call_args.args[1], 60)
            values['spug:host:chart:v1:2:lock'] = 'other-owner'
            self.assertTrue(collect(SimpleNamespace(id=2), rds)['collecting'])
            probe.assert_called_once()

    def test_lock_winner_rechecks_cache_before_ssh(self):
        rds = Mock()
        state = {'attempted_at': 1000, 'history': []}
        rds.get.side_effect = [None, json.dumps(state)]
        rds.set.return_value = True
        with patch('apps.host.overview_metrics.time.time', return_value=1001), \
                patch('apps.host.overview_metrics.probe') as collect_probe:
            self.assertEqual(collect(SimpleNamespace(id=1), rds), state)
        collect_probe.assert_not_called()
        rds.eval.assert_called_once()
        self.assertEqual(rds.eval.call_args.args[-1], rds.set.call_args.args[1])

    def test_probe_timeout_closes_channel_and_connection(self):
        host = Mock()
        ssh = host.get_ssh.return_value
        ssh.arguments = {}
        channel = ssh.get_client.return_value.get_transport.return_value.open_session.return_value
        with patch('apps.host.overview_metrics.time.monotonic', side_effect=[0, 7]):
            with self.assertRaises(TimeoutError):
                probe(host)
        channel.close.assert_called_once()
        ssh.client.close.assert_called_once()
        self.assertEqual(ssh.arguments['auth_timeout'], 5)

    def test_api_returns_authorized_host_without_internal_snapshot(self):
        request = RequestFactory().get('/host/metrics/overview/?id=12')
        request.user = Mock(is_supper=False)
        rds, _ = self.redis()
        with patch('apps.host.overview_metrics.Host.objects') as hosts, \
                patch('apps.host.overview_metrics.get_host_perms', return_value=[12]), \
                patch('apps.host.overview_metrics.get_redis_connection', return_value=rds), \
                patch('apps.host.overview_metrics.probe', return_value=output()) as collect_probe:
            host = SimpleNamespace(id=12, is_verified=True)
            hosts.filter.return_value.first.return_value = host
            first = json.loads(overview_metrics(request).content)['data']
            second = json.loads(overview_metrics(request).content)['data']
        self.assertEqual(first['host_id'], 12)
        self.assertEqual(first['history'], second['history'])
        self.assertNotIn('stat', first)
        collect_probe.assert_called_once_with(host)

    def test_failure_is_cached_and_does_not_leak_exception(self):
        rds, _ = self.redis()
        with patch('apps.host.overview_metrics.probe', side_effect=RuntimeError('private-key secret')) as probe:
            self.assertNotIn('secret', json.dumps(collect(SimpleNamespace(id=1), rds)))
            collect(SimpleNamespace(id=1), rds)
            probe.assert_called_once()

    def test_history_bounded_and_stale_snapshot_not_used(self):
        rds, values = self.redis()
        values['spug:host:chart:v1:1'] = json.dumps({'sampled_at': 1, 'stat': [100, 50],
            'history': [{'ts': n} for n in range(1000)]})
        with patch('apps.host.overview_metrics.time.time', return_value=1000), \
                patch('apps.host.overview_metrics.probe', return_value=output()):
            result = collect(SimpleNamespace(id=1), rds)
        self.assertEqual(len(result['history']), 61)
        self.assertIsNone(result['history'][-1]['cpu'])
        self.assertTrue(all(p['ts'] >= 700 for p in result['history']))

    def test_permissions_checked_before_cache(self):
        request = RequestFactory().get('/host/metrics/overview/?id=1')
        request.user = Mock(is_supper=False)
        request.user.has_perms.return_value = True
        with patch('apps.host.overview_metrics.get_host_perms', return_value=[]), \
                patch('apps.host.overview_metrics.get_redis_connection') as redis:
            result = json.loads(overview_metrics(request).content)
        self.assertTrue(result['error'])
        redis.assert_not_called()

    def test_redis_outage_never_falls_back_to_ssh(self):
        request = RequestFactory().get('/host/metrics/overview/?id=1')
        request.user = Mock(is_supper=True)
        with patch('apps.host.overview_metrics.Host.objects') as hosts, \
                patch('apps.host.overview_metrics.get_redis_connection', side_effect=RuntimeError), \
                patch('apps.host.overview_metrics.probe') as probe:
            hosts.filter.return_value.first.return_value = SimpleNamespace(id=1, is_verified=True)
            result = json.loads(overview_metrics(request).content)
        self.assertTrue(result['data']['error'])
        probe.assert_not_called()
