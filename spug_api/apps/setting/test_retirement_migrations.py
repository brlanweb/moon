"""Run real migration SQL only in an explicitly isolated child process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest import TestCase
from unittest.mock import Mock, patch

from django.test import SimpleTestCase


ISOLATED_SETTINGS = 'apps.setting.test_retirement_settings'
RETIREMENTS = {
    ('account', '0003_remove_user_wx_token'),
    ('alarm', '0002_remove_contact_wx_token'),
    ('setting', '0002_remove_ldap_service'),
    ('setting', '0003_remove_push_settings'),
}


class RetirementMigrationTests(SimpleTestCase):
    def probe(self, scenario):
        script = '''
import django
from unittest.mock import patch
with patch('socket.socket.connect', side_effect=AssertionError('Network is forbidden')):
    django.setup()
    from apps.setting.test_retirement_migrations import run_probe
    run_probe(%r)
''' % scenario
        result = subprocess.run(
            [sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, 'DJANGO_SETTINGS_MODULE': ISOLATED_SETTINGS, 'SPUG_DEBUG': '1'},
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(report['database'], 'sqlite-memory')
        self.assertEqual(report['pending_migrations'], 0)
        print('Migration evidence: ' + json.dumps(report, sort_keys=True))
        return report

    def test_empty_database_migrates_to_all_current_leaves(self):
        report = self.probe('fresh')
        self.assertGreater(report['applied_migrations'], len(RETIREMENTS))
        self.assertTrue(report['local_login'])

    def test_historical_upgrade_preserves_every_non_retired_value(self):
        report = self.probe('upgrade')
        self.assertEqual(report['upgrade_migrations'], 4)
        self.assertEqual(report['removed_settings'], ['ldap_service', 'spug_push_key'])
        self.assertTrue(report['mfa_preserved_and_login_blocked'])
        self.assertTrue(report['external_login_and_sessions_blocked'])
        self.assertGreater(report['unchanged_tables'], 0)


def _rows(connection):
    result = {}
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names(cursor):
            if table == 'django_migrations':
                continue
            cursor.execute('SELECT * FROM ' + connection.ops.quote_name(table))
            columns = [item[0] for item in cursor.description]
            result[table] = sorted(
                [dict(zip(columns, row)) for row in cursor.fetchall()], key=lambda row: row.get('id', 0))
    return result


def _login(username, login_type='default'):
    from apps.account.views import login
    from django.test import RequestFactory
    request = RequestFactory().post('/account/login/', data=json.dumps({
        'username': username, 'password': 'TestingPass123', 'type': login_type,
    }), content_type='application/json', HTTP_USER_AGENT='isolated-migration-test')
    return json.loads(login(request).content)


def _seed_history(apps):
    from apps.account.models import User as CurrentUser
    user_model = apps.get_model('account', 'User')
    password = CurrentUser.make_password('TestingPass123')
    users = []
    for name, kind, token in (('local', 'default', 'a'), ('external', 'ldap', 'b')):
        users.append(user_model.objects.create(
            username=name, nickname=name, type=kind, password_hash=password,
            is_supper=True, access_token=token * 32, token_expired=int(time.time()) + 3600,
            last_login='', last_ip='', wx_token='synthetic-old-id-' + name))
    local, external = users
    role = apps.get_model('account', 'Role').objects.create(
        name='preserved', created_by=local, page_perms={'host': {'host': ['view']}},
        deploy_perms={'apps': [1]}, group_perms=[1])
    for user in users:
        user.roles.add(role)
    apps.get_model('account', 'History').objects.create(
        username='external', type='ldap', ip='', agent='historical-audit', is_success=True)
    contact = apps.get_model('alarm', 'Contact').objects.create(
        name='preserved-contact', phone='00000000000', email='ops@example.test',
        ding='https://example.test/dd', qy_wx='https://example.test/wx',
        feishu='https://example.test/fs', secret='{"ding":"synthetic-signing-value"}',
        created_by=external, wx_token='synthetic-old-contact-id')
    group = apps.get_model('alarm', 'Group').objects.create(
        name='preserved-group', contacts=json.dumps([contact.id]), created_by=local)
    apps.get_model('alarm', 'Alarm').objects.create(
        name='historical-alarm', type='HTTP', target='https://example.test',
        notify_mode='["1", "3", "4", "5", "7"]',
        notify_grp=json.dumps([group.id]), status='1', duration='')
    values = {
        'ldap_service': {'enable': True, 'bind_password': 'synthetic-directory-value'},
        'spug_push_key': 'synthetic-push-value',
        'MFA': {'enable': True, 'other': 'preserve-verbatim'},
        'mail_service': {'server': 'smtp.example.test', 'password': 'synthetic-smtp-value'},
        'verify_ip': False, 'bind_ip': False,
        'private_key': 'synthetic-private-value', 'public_key': 'synthetic-public-value',
        'api_key': 'synthetic-api-value', 'custom_setting': {'preserve': [1, 2, 3]},
    }
    for key, value in values.items():
        apps.get_model('setting', 'Setting').objects.create(
            key=key, value=json.dumps(value), desc='preserved-description')
    apps.get_model('setting', 'UserSetting').objects.create(
        user=external, key='test-layout', value='{"preserve":true}')
    apps.get_model('notify', 'Notify').objects.create(
        source='schedule', type='1', title='preserved-site-notification', content='preserved-content')


def run_probe(scenario):
    from django.conf import settings
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.recorder import MigrationRecorder
    from apps.account.models import User
    from apps.setting.models import Setting
    from django.test import RequestFactory
    from libs.middleware import AuthenticationMiddleware
    from consumer.utils import BaseConsumer

    check = TestCase()
    # Check configuration before the first database connection can be opened.
    check.assertEqual(settings.SETTINGS_MODULE, ISOLATED_SETTINGS)
    check.assertEqual(connection.settings_dict['ENGINE'], 'django.db.backends.sqlite3')
    check.assertEqual(connection.settings_dict['NAME'], ':memory:')
    check.assertEqual(settings.CACHES['default']['BACKEND'], 'django.core.cache.backends.locmem.LocMemCache')
    executor = MigrationExecutor(connection)
    check.assertEqual(executor.loader.detect_conflicts(), {})
    leaves = executor.loader.graph.leaf_nodes()
    report = {'scenario': scenario, 'database': 'sqlite-memory'}
    if scenario == 'upgrade':
        # MCP was introduced after retirement and depends on its account schema.
        retirement_targets = [node for node in leaves if node[0] != 'mcp_ops']
        before_targets = [node for node in retirement_targets if node[0] not in ('account', 'alarm', 'setting')]
        before_targets += [('account', '0002_role_created_by'),
                           ('alarm', '0001_initial'), ('setting', '0001_initial')]
        executor.migrate(before_targets)
        old_apps = executor.loader.project_state(before_targets).apps
        _seed_history(old_apps)
        before = _rows(connection)
        check.assertIn('wx_token', before['users'][0])
        check.assertIn('wx_token', before['alarm_contacts'][0])
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(retirement_targets)
        check.assertEqual({(migration.app_label, migration.name) for migration, _ in plan}, RETIREMENTS)
        check.assertTrue(all(not backwards for _, backwards in plan))
        report['upgrade_migrations'] = len(plan)
        executor.migrate(retirement_targets)
        after = _rows(connection)
        expected = {table: [dict(row) for row in rows] for table, rows in before.items()}
        for table in ('users', 'alarm_contacts'):
            for row in expected[table]:
                del row['wx_token']
        expected['settings'] = [row for row in expected['settings']
                                if row['key'] not in ('ldap_service', 'spug_push_key')]
        check.assertEqual(after, expected)
        report['removed_settings'] = sorted({row['key'] for row in before['settings']}
                                            - {row['key'] for row in after['settings']})
        report['preserved_settings'] = sorted(row['key'] for row in after['settings'])
        report['unchanged_tables'] = sum(after[table] == rows for table, rows in before.items())
        report['preserved_users'] = User.objects.count()
        report['removed_columns'] = ['users.wx_token', 'alarm_contacts.wx_token']
        token_before = list(User.objects.order_by('id').values_list('access_token', 'token_expired'))
        local_result = _login('local')
        check.assertIn('set mfa disable', local_result['error'])
        check.assertNotIn('access_token', local_result.get('data') or {})
        check.assertTrue(Setting.objects.get(key='MFA').real_val['enable'])
        report['mfa_preserved_and_login_blocked'] = True
        for login_type in ('default', 'ldap'):
            data = _login('external', login_type)
            check.assertTrue(data['error'])
            check.assertNotIn('access_token', data.get('data') or {})
        external = User.objects.get(username='external')
        request = RequestFactory().get('/account/self/', HTTP_X_TOKEN=external.access_token)
        response = AuthenticationMiddleware(lambda r: None).process_request(request)
        check.assertEqual(response.status_code, 401)
        consumer = BaseConsumer()
        consumer.scope = {'query_string': ('x-token=' + external.access_token).encode(), 'headers': []}
        consumer.accept, consumer.close_with_message = Mock(), Mock()
        with patch('consumer.utils.close_old_connections'):
            consumer.connect()
        check.assertIsNone(consumer.user)
        consumer.close_with_message.assert_called_once()
        check.assertEqual(list(User.objects.order_by('id').values_list('access_token', 'token_expired')), token_before)
        report['external_login_and_sessions_blocked'] = True
        MigrationExecutor(connection).migrate(leaves)
    else:
        check.assertEqual(scenario, 'fresh')
        executor.migrate(leaves)
        check.assertFalse(Setting.objects.filter(key__in=['MFA', 'ldap_service', 'spug_push_key']).exists())
        User.objects.create(username='local', nickname='local', is_supper=True,
                            password_hash=User.make_password('TestingPass123'))
        result = _login('local')
        check.assertFalse(result['error'])
        check.assertEqual(len(result['data']['access_token']), 32)
        report['local_login'] = True
    with connection.cursor() as cursor:
        for table in ('users', 'alarm_contacts'):
            columns = {column.name for column in connection.introspection.get_table_description(cursor, table)}
            check.assertNotIn('wx_token', columns)
    connection.check_constraints()
    executor = MigrationExecutor(connection)
    report['pending_migrations'] = len(executor.migration_plan(leaves))
    check.assertEqual(report['pending_migrations'], 0)
    executor.migrate(leaves)
    report['applied_migrations'] = len(MigrationRecorder(connection).applied_migrations())
    for node in [('setting', '0002_remove_ldap_service'), ('setting', '0003_remove_push_settings')]:
        check.assertFalse(executor.loader.get_migration(*node).operations[0].reversible)
    connection.close()
    print(json.dumps(report, sort_keys=True))
