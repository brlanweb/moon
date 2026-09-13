import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.database.client import (
    _clickhouse, _mysql, _postgresql, _redis, test_connection,
)
from apps.database.models import DatabaseConnection
from apps.database.views import _connection_form, _temporary_connection, check_connection


class ConnectionSettingsTests(SimpleTestCase):
    def setUp(self):
        self.payload = {
            'name': 'reporting',
            'type': 'mysql',
            'host': 'db.internal',
            'port': 3306,
        }

    def test_model_uses_connection_governance_defaults(self):
        connection = DatabaseConnection()

        self.assertEqual(connection.connect_timeout, 10)
        self.assertEqual(connection.query_timeout, 30)
        self.assertEqual(connection.idle_timeout, 30)
        self.assertEqual(connection.environment, 'normal')
        self.assertIs(connection.read_only, False)

    def test_form_uses_connection_governance_defaults_when_omitted(self):
        form, error = _connection_form(self.payload)

        self.assertIsNone(error)
        self.assertEqual(form.connect_timeout, 10)
        self.assertEqual(form.query_timeout, 30)
        self.assertEqual(form.idle_timeout, 30)
        self.assertEqual(form.environment, 'normal')
        self.assertIs(form.read_only, False)

    def test_form_accepts_timeout_boundaries(self):
        for connect_timeout, query_timeout in ((1, 1), (120, 3600)):
            with self.subTest(connect_timeout=connect_timeout, query_timeout=query_timeout):
                form, error = _connection_form({
                    **self.payload,
                    'connect_timeout': connect_timeout,
                    'query_timeout': query_timeout,
                })

                self.assertIsNone(error)
                self.assertEqual(form.connect_timeout, connect_timeout)
                self.assertEqual(form.query_timeout, query_timeout)

    def test_form_accepts_idle_timeout_boundaries(self):
        for idle_timeout in (0, 1440):
            with self.subTest(idle_timeout=idle_timeout):
                form, error = _connection_form({**self.payload, 'idle_timeout': idle_timeout})

                self.assertIsNone(error)
                self.assertEqual(form.idle_timeout, idle_timeout)

    def test_form_rejects_idle_timeout_outside_allowed_range(self):
        for idle_timeout in (-1, 1441):
            with self.subTest(idle_timeout=idle_timeout):
                _, error = _connection_form({**self.payload, 'idle_timeout': idle_timeout})

                self.assertEqual(error, '空闲断开必须在 0～1440 分钟之间')

    def test_form_accepts_supported_environments(self):
        for environment in ('normal', 'production'):
            with self.subTest(environment=environment):
                form, error = _connection_form({**self.payload, 'environment': environment})

                self.assertIsNone(error)
                self.assertEqual(form.environment, environment)

    def test_form_rejects_unsupported_environment(self):
        _, error = _connection_form({**self.payload, 'environment': 'staging'})

        self.assertEqual(error, '连接环境必须是 normal 或 production')

    def test_form_keeps_read_only_flag(self):
        form, error = _connection_form({**self.payload, 'read_only': True})

        self.assertIsNone(error)
        self.assertIs(form.read_only, True)

    def test_form_rejects_non_integer_connection_timeouts(self):
        for field, message in (
                ('connect_timeout', '连接超时必须在 1～120 秒之间'),
                ('query_timeout', '查询超时必须在 1～3600 秒之间')):
            for value in (True, 17.9):
                with self.subTest(field=field, value=value):
                    _, error = _connection_form({**self.payload, field: value})

                    self.assertEqual(error, message)

    def test_form_rejects_connect_timeout_outside_allowed_range(self):
        for value in (0, 121):
            with self.subTest(value=value):
                _, error = _connection_form({**self.payload, 'connect_timeout': value})

                self.assertEqual(error, '连接超时必须在 1～120 秒之间')

    def test_form_rejects_query_timeout_outside_allowed_range(self):
        for value in (0, 3601):
            with self.subTest(value=value):
                _, error = _connection_form({**self.payload, 'query_timeout': value})

                self.assertEqual(error, '查询超时必须在 1～3600 秒之间')

    def test_temporary_connection_keeps_requested_settings(self):
        form, error = _connection_form({
            **self.payload,
            'connect_timeout': 17,
            'query_timeout': 83,
            'idle_timeout': 41,
            'environment': 'production',
            'read_only': True,
        })

        self.assertIsNone(error)
        connection = _temporary_connection(form)
        self.assertEqual(connection.connect_timeout, 17)
        self.assertEqual(connection.query_timeout, 83)
        self.assertEqual(connection.idle_timeout, 41)
        self.assertEqual(connection.environment, 'production')
        self.assertIs(connection.read_only, True)

    @patch('apps.database.views.test_connection', return_value=12)
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_existing_connection_check_uses_requested_settings(self, connections, _test):
        item = SimpleNamespace(
            name='reporting', type='mysql', host='old.internal', port=3306,
            username='spug', database='operations', use_ssl=False,
            connect_timeout=10, query_timeout=30, idle_timeout=30,
            environment='normal', read_only=False,
        )
        connections.return_value.first.return_value = item
        payload = {
            **self.payload,
            'id': 7,
            'connect_timeout': 19,
            'query_timeout': 91,
            'idle_timeout': 47,
            'environment': 'production',
            'read_only': True,
        }
        request = RequestFactory().post(
            '/api/database/connection/check/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        request.user = SimpleNamespace(has_perms=lambda _perms: True)

        response = check_connection(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(item.connect_timeout, 19)
        self.assertEqual(item.query_timeout, 91)
        self.assertEqual(item.idle_timeout, 47)
        self.assertEqual(item.environment, 'production')
        self.assertIs(item.read_only, True)


class DriverTimeoutTests(SimpleTestCase):
    def connection(self, database_type):
        return SimpleNamespace(
            type=database_type,
            host='db.internal',
            port=5432,
            username='spug',
            database='operations',
            use_ssl=False,
            connect_timeout=17,
            query_timeout=83,
            get_password=lambda: 'secret',
        )

    @patch('pymysql.connect')
    def test_mysql_receives_connection_timeouts(self, connect):
        _mysql(self.connection('mysql'))

        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs['connect_timeout'], 17)
        self.assertEqual(kwargs['read_timeout'], 83)
        self.assertEqual(kwargs['write_timeout'], 83)

    @patch('psycopg.connect')
    def test_postgresql_receives_connection_timeouts(self, connect):
        _postgresql(self.connection('postgresql'))

        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs['connect_timeout'], 17)
        self.assertEqual(kwargs['options'], '-c statement_timeout=83000')

    @patch('clickhouse_connect.get_client')
    def test_clickhouse_receives_connection_timeouts(self, get_client):
        _clickhouse(self.connection('clickhouse'))

        kwargs = get_client.call_args.kwargs
        self.assertEqual(kwargs['connect_timeout'], 17)
        self.assertEqual(kwargs['send_receive_timeout'], 83)

    @patch('redis.Redis')
    def test_redis_receives_connection_timeouts(self, redis_client):
        connection = self.connection('redis')
        connection.database = '2'

        _redis(connection)

        kwargs = redis_client.call_args.kwargs
        self.assertEqual(kwargs['socket_connect_timeout'], 17)
        self.assertEqual(kwargs['socket_timeout'], 83)

    @patch('apps.database.client._mysql')
    def test_connection_closes_driver_connection_after_check(self, connect):
        client = MagicMock()
        connect.return_value = client

        test_connection(self.connection('mysql'))

        client.close.assert_called_once_with()
