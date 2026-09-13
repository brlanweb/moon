import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest import skipUnless

from django.test import SimpleTestCase

from apps.database import executions


def execution_id():
    return f'{int(time.time() * 1000)}.{uuid4()}'


class ExecutionRegistryTests(SimpleTestCase):
    def setUp(self):
        self.user = int(uuid4().hex[:10], 16)
        self.registry = executions.Registry(self.user, 23, execution_id())

    def test_cancel_before_registration_prevents_execution(self):
        self.assertEqual(self.registry.cancel()['status'], 'cancelling')
        self.assertFalse(self.registry.begin())
        self.assertEqual(self.registry.status()['status'], 'cancelled')

    def test_completed_execution_cannot_be_cancelled_or_replayed(self):
        self.assertTrue(self.registry.begin())
        self.registry.finish('completed')
        self.assertEqual(self.registry.cancel()['status'], 'completed')
        with self.assertRaises(executions.ExecutionError):
            self.registry.begin()

    def test_only_one_concurrent_execution_on_same_user_connection(self):
        other = executions.Registry(self.user, 23, execution_id())
        self.registry.begin()
        with self.assertRaises(executions.ExecutionError):
            other.begin()
        self.registry.finish('completed')
        self.assertTrue(other.begin())
        other.finish('completed')

    def test_other_user_cannot_cancel_registered_execution(self):
        self.registry.begin()
        other = executions.Registry(self.user + 1, 23, self.registry.execution_id)
        other.cancel()
        self.assertFalse(self.registry.status()['cancel_requested'])
        self.registry.finish('completed')

    def test_duplicate_cancel_only_records_intent(self):
        self.registry.begin()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.registry.cancel(), range(8)))
        self.assertTrue(all(r['status'] == 'cancelling' for r in results))
        self.registry.finish('completed')
        self.assertEqual(self.registry.status()['status'], 'completed')

    def test_old_cancel_cannot_affect_next_execution(self):
        self.registry.begin()
        self.registry.finish('completed')
        other = executions.Registry(self.user, 23, execution_id())
        other.begin()
        self.registry.cancel()
        self.assertFalse(other.status()['cancel_requested'])
        other.finish('completed')

    def test_expired_execution_id_rejected(self):
        with self.assertRaises(executions.ExecutionError):
            executions.Registry(self.user, 23, f'1.{uuid4()}')


class NativeCancellationTests(SimpleTestCase):
    def test_redis_scripts_are_explicitly_unsupported(self):
        from apps.database.cancellation import redis_cancellable
        self.assertFalse(redis_cancellable('EVAL "return 1" 0'))
        self.assertFalse(redis_cancellable('FCALL f 0'))
        self.assertFalse(redis_cancellable('GET key'))
        self.assertTrue(redis_cancellable('BLPOP key 10'))
        self.assertTrue(redis_cancellable('XREAD BLOCK 10000 STREAMS key $'))

    def test_only_native_interruption_is_cancelled(self):
        from apps.database.cancellation import interrupted
        import pymysql
        self.assertTrue(interrupted('mysql', pymysql.err.OperationalError(1317, 'interrupted')))
        self.assertFalse(interrupted('mysql', pymysql.err.OperationalError(2013, 'lost connection')))
        self.assertFalse(interrupted('redis', RuntimeError('UNBLOCKED')))


class CancelApiTests(SimpleTestCase):
    def test_cancel_requires_both_permissions(self):
        import json
        from types import SimpleNamespace
        from django.test import RequestFactory
        from apps.database.views import cancel_command
        request = RequestFactory().post('/api/database/cancel/', data=json.dumps({
            'id': 23, 'execution_id': execution_id(),
        }), content_type='application/json')
        request.user = SimpleNamespace(id=1, has_perms=lambda p: p != ['database.connection.view'])
        self.assertEqual(json.loads(cancel_command(request).content)['error'], '权限拒绝')

    def test_postgresql_schema_is_separate_from_dbname(self):
        from types import SimpleNamespace
        from apps.database.views import _execution_database
        connection = SimpleNamespace(type='postgresql', database='app')
        self.assertEqual(_execution_database(connection, 'tenant'), 'app / tenant')


class MetadataTests(SimpleTestCase):
    def test_empty_namespaces_have_no_null_table_item(self):
        from types import SimpleNamespace
        from unittest.mock import patch, MagicMock
        from apps.database.client import metadata
        worker = MagicMock()
        worker.cursor.return_value.__enter__.return_value.fetchmany.return_value = [('empty', None), ('app', 'orders')]
        with patch('apps.database.client._mysql', return_value=worker):
            result = metadata(SimpleNamespace(type='mysql'))
        self.assertEqual(result['groups'], [
            {'name': 'empty', 'items': []}, {'name': 'app', 'items': ['orders']}])


class LocalConnectionMixin:
    def connection(self, engine):
        from types import SimpleNamespace
        from django.conf import settings
        config = settings.DATABASES['default']
        self.assertEqual(config['HOST'], 'db', 'Integration must use the local Compose database')
        return SimpleNamespace(type=engine, host='db' if engine == 'mariadb' else '127.0.0.1',
                               port=3306 if engine == 'mariadb' else 6379,
                               username=config['USER'] if engine == 'mariadb' else '',
                               get_password=lambda: config['PASSWORD'] if engine == 'mariadb' else '',
                               database=config['NAME'] if engine == 'mariadb' else '0',
                               connect_timeout=3, query_timeout=15, use_ssl=False, read_only=True)



@skipUnless(os.environ.get('NATIVE_CANCEL_INTEGRATION') == '1', 'Local container integration is opt-in')
class LocalCancellationIntegrationTests(LocalConnectionMixin, SimpleTestCase):
    def cancel_query(self, engine, command):
        from apps.database.client import execute
        registry = executions.Registry(int(uuid4().hex[:10], 16), 23, execution_id())
        self.assertTrue(registry.begin())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute, self.connection(engine), command, registry=registry)
            deadline = time.monotonic() + 5
            while not registry.status().get('target') and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(registry.status().get('target'))
            self.assertEqual(registry.cancel()['status'], 'cancelling')
            result = future.result(timeout=6)
        self.assertEqual(result['status'], 'cancelled')
        registry.finish('cancelled')
        self.assertEqual(registry.cancel()['status'], 'cancelled')
        return registry

    def test_mariadb_sleep_native_cancel_on_readonly_connection(self):
        from apps.database.client import execute
        old = self.cancel_query('mariadb', 'SELECT SLEEP(10)')
        old.cancel()
        self.assertEqual(execute(self.connection('mariadb'), 'SELECT 42')['rows'], [[42]])

    def test_redis_unblock_fixed_physical_connection(self):
        self.cancel_query('redis', f'XREAD BLOCK 10000 STREAMS native-cancel-{uuid4().hex} $')


class TransportFailureTests(SimpleTestCase):
    def test_network_loss_is_not_a_terminal_server_result(self):
        from apps.database.cancellation import uncertain_failure
        import pymysql
        import redis
        self.assertTrue(uncertain_failure('mysql', pymysql.err.OperationalError(2013, 'lost')))
        self.assertFalse(uncertain_failure('mysql', pymysql.err.ProgrammingError(1064, 'syntax')))
        self.assertTrue(uncertain_failure('redis', redis.exceptions.ConnectionError('lost')))
        self.assertFalse(uncertain_failure('redis', redis.exceptions.ResponseError('WRONGTYPE')))


class DriverContractTests(SimpleTestCase):
    def test_clickhouse_installed_driver_accepts_query_id_as_settings(self):
        from clickhouse_connect.driver.httpclient import HttpClient
        # This is the actual installed driver's validation, not a guessed query_id kwarg.
        client = object.__new__(HttpClient)
        self.assertEqual(client._validate_settings({'query_id': 'native-contract'}),
                         {'query_id': 'native-contract'})

    def test_postgres_identifier_quotes_embedded_quotes(self):
        from psycopg import sql
        schema = 'tenant"; DROP SCHEMA public; --'
        statement = sql.SQL('SET search_path TO {}').format(sql.Identifier(schema))
        self.assertEqual(statement.as_string(), 'SET search_path TO "tenant""; DROP SCHEMA public; --"')

    def test_redis_pinned_connection_cannot_reconnect(self):
        from types import SimpleNamespace
        from apps.database.cancellation import pin_redis
        import redis
        client = SimpleNamespace(connection=SimpleNamespace(_sock=None))
        pin_redis(client)
        with self.assertRaises(redis.exceptions.ConnectionError):
            client.connection.connect()


@skipUnless(os.environ.get('NATIVE_CANCEL_INTEGRATION') == '1', 'Local container integration is opt-in')
class LocalApiCancellationIntegrationTests(LocalConnectionMixin, SimpleTestCase):
    def test_cancel_api_is_user_scoped_and_execute_reports_native_interruption(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from django.test import RequestFactory
        from apps.database.views import run_command, cancel_command
        connection = self.connection('mariadb')
        connection.id, connection.environment = 23, 'normal'
        owner = int(uuid4().hex[:10], 16)
        eid = execution_id()
        registry = executions.Registry(owner, 23, eid)

        def request(path, user, command=None):
            data = {'id': 23, 'execution_id': eid}
            if command:
                data['command'] = command
            req = RequestFactory().post(path, data=json.dumps(data), content_type='application/json')
            req.user = SimpleNamespace(id=user, has_perms=lambda _: True)
            return req

        with patch('apps.database.views.DatabaseConnection.objects.filter') as objects:
            objects.return_value.first.return_value = connection
            objects.return_value.exists.return_value = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(run_command, request('/execute/', owner, 'SELECT SLEEP(10)'))
                deadline = time.monotonic() + 5
                while not registry.status().get('target') and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(registry.status().get('target'))
                cancel_command(request('/cancel/', owner + 1))
                self.assertFalse(registry.status()['cancel_requested'])
                response = json.loads(cancel_command(request('/cancel/', owner)).content)
                self.assertEqual(response['data']['status'], 'cancelling')
                result = json.loads(future.result(timeout=6).content)
                self.assertEqual(result['data']['status'], 'cancelled')
                self.assertEqual(registry.status()['status'], 'cancelled')

    def test_early_cancel_api_prevents_work_and_replay(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from django.test import RequestFactory
        from apps.database.views import run_command, cancel_command
        connection = self.connection('mariadb')
        connection.id, connection.environment = 23, 'normal'
        payload = {'id': 23, 'execution_id': execution_id(), 'command': 'SELECT SLEEP(10)'}
        req = RequestFactory().post('/execute/', data=json.dumps(payload), content_type='application/json')
        req.user = SimpleNamespace(id=int(uuid4().hex[:10], 16), has_perms=lambda _: True)
        with patch('apps.database.views.DatabaseConnection.objects.filter') as objects:
            objects.return_value.first.return_value = connection
            objects.return_value.exists.return_value = True
            cancel_command(req)
            result = json.loads(run_command(req).content)['data']
            self.assertEqual(result['status'], 'cancelled')
            replay = json.loads(run_command(req).content)['data']
            self.assertEqual(replay['status'], 'failed')
            self.assertIn('已使用', replay['message'])


class ClickHouseInterruptionTests(SimpleTestCase):
    def test_native_stream_cancellation_is_recognized(self):
        from apps.database.cancellation import interrupted
        from clickhouse_connect.driver.exceptions import StreamFailureError
        self.assertTrue(interrupted('clickhouse', StreamFailureError('Code: 394. QUERY_WAS_CANCELLED')))
        self.assertFalse(interrupted('clickhouse', StreamFailureError('connection reset')))


@skipUnless(os.environ.get('NATIVE_CANCEL_INTEGRATION') == '1', 'Local container integration is opt-in')
class LocalConcurrentCancellationTests(LocalConnectionMixin, SimpleTestCase):
    def test_cancelling_one_user_leaves_another_physical_query_running(self):
        from apps.database.client import execute
        owner = int(uuid4().hex[:10], 16)
        first = executions.Registry(owner, 23, execution_id())
        other = executions.Registry(owner + 1, 23, execution_id())
        first.begin()
        other.begin()
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancelled = pool.submit(execute, self.connection('mariadb'), 'SELECT SLEEP(5)', registry=first)
            unaffected = pool.submit(execute, self.connection('mariadb'), 'SELECT SLEEP(0.5)', registry=other)
            deadline = time.monotonic() + 3
            while not (first.status().get('target') and other.status().get('target')) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertNotEqual(first.status()['target'], other.status()['target'])
            first.cancel()
            self.assertEqual(cancelled.result(timeout=3)['status'], 'cancelled')
            first.finish('cancelled')
            first.cancel()  # A repeated old stop cannot affect the still-running second query.
            self.assertEqual(unaffected.result(timeout=3)['rows'], [[0]])
            other.finish('completed')
