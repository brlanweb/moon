import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.account.models import History, User
from apps.account.views import SelfView, UserView, login
from consumer.utils import BaseConsumer
from libs.middleware import AuthenticationMiddleware


@override_settings(CACHES={'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'retired-login-tests',
}})
class RetiredLoginTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.user = User(id=987, username='operator', type='default', is_supper=True,
                         password_hash=User.make_password('TestingPass123'),
                         access_token='a' * 32, token_expired=int(time.time()) + 3600, last_ip='')

    def request(self, payload):
        return self.factory.post('/account/login/', data=json.dumps({
            'username': self.user.username, 'password': 'TestingPass123', **payload,
        }), content_type='application/json', HTTP_USER_AGENT='retirement-test')

    def test_old_login_requests_never_reach_password_authentication(self):
        for login_type in ('ldap', 'LDAP', ' ldap ', 'other', [], {}, True, 1):
            with self.subTest(login_type=login_type), \
                    patch.object(User.objects, 'filter') as users, \
                    patch.object(User.objects, 'create') as create, \
                    patch.object(User, 'verify_password', return_value=True) as verify, \
                    patch('apps.account.views.handle_user_info') as session:
                users.return_value.first.return_value = self.user
                data = json.loads(login(self.request({'type': login_type})).content)
            self.assertTrue(data['error'])
            users.assert_not_called()
            verify.assert_not_called()
            session.assert_not_called()
            create.assert_not_called()
            self.assertIsNone(cache.get(self.user.username))

    def test_local_login_default_compatibility_and_audit(self):
        for payload in ({}, {'type': 'default'}, {'type': None}, {'type': ''}):
            with self.subTest(payload=payload), \
                    patch.object(User.objects, 'filter') as users, \
                    patch.object(User, 'save'), \
                    patch.object(History.objects, 'create') as audit, \
                    patch('apps.account.views.AppSetting.get_default', side_effect=lambda k, d=None: d):
                users.return_value.first.return_value = self.user
                data = json.loads(login(self.request(payload)).content)
            self.assertFalse(data['error'])
            self.assertEqual(data['data']['access_token'], 'a' * 32)
            users.assert_called_once_with(username='operator', type='default', is_deleted=False)
            self.assertEqual(audit.call_args.kwargs['type'], 'default')
            self.assertTrue(audit.call_args.kwargs['is_success'])

    def test_legacy_only_username_is_not_selected_for_local_login(self):
        with patch.object(User.objects, 'filter') as users, \
                patch.object(History.objects, 'create') as audit, \
                patch.object(User, 'verify_password') as verify:
            users.return_value.first.return_value = None
            data = json.loads(login(self.request({})).content)
        self.assertTrue(data['error'])
        users.assert_called_once_with(username='operator', type='default', is_deleted=False)
        verify.assert_not_called()
        self.assertFalse(audit.call_args.kwargs['is_success'])

    def test_local_login_does_not_bypass_enabled_mfa(self):
        with patch.object(User.objects, 'filter') as users, \
                patch.object(User, 'save') as save, \
                patch.object(History.objects, 'create'), \
                patch('apps.account.views.AppSetting.get_default', return_value={'enable': True}):
            users.return_value.first.return_value = self.user
            data = json.loads(login(self.request({})).content)
        self.assertIn('set mfa disable', data['error'])
        self.assertNotIn('required_mfa', data.get('data') or {})
        self.assertNotIn('access_token', data.get('data') or {})
        save.assert_not_called()

    def test_http_session_accepts_only_local_accounts(self):
        for user_type in ('default', 'ldap'):
            self.user.type = user_type
            request = self.factory.get('/account/self/', HTTP_X_TOKEN='a' * 32)
            with self.subTest(user_type=user_type), patch.object(User.objects, 'filter') as users, \
                    patch.object(User, 'save') as save:
                users.return_value.first.return_value = self.user
                response = AuthenticationMiddleware(lambda r: None).process_request(request)
            if user_type == 'default':
                self.assertIsNone(response)
                self.assertIs(request.user, self.user)
                save.assert_called_once()
            else:
                self.assertEqual(response.status_code, 401)
                self.assertFalse(hasattr(request, 'user'))
                save.assert_not_called()

    def test_websocket_session_accepts_only_local_accounts(self):
        for user_type in ('default', 'ldap'):
            self.user.type = user_type
            consumer = BaseConsumer()
            consumer.scope = {'query_string': b'x-token=' + b'a' * 32, 'headers': []}
            consumer.accept = Mock()
            consumer.close_with_message = Mock()
            with self.subTest(user_type=user_type), \
                    patch('consumer.utils.close_old_connections'), \
                    patch.object(User.objects, 'filter') as users:
                users.return_value.first.return_value = self.user
                consumer.connect()
            if user_type == 'default':
                self.assertIs(consumer.user, self.user)
                consumer.close_with_message.assert_not_called()
            else:
                self.assertIsNone(consumer.user)
                consumer.close_with_message.assert_called_once()

    def test_historical_account_cannot_be_reset_or_deleted(self):
        self.user.type = 'ldap'
        with patch.object(User.objects, 'get', return_value=self.user), \
                patch.object(User.objects, 'filter') as users, patch.object(User, 'save') as save:
            users.return_value.first.return_value = self.user
            reset = self.factory.patch('/account/user/', data=json.dumps({
                'id': self.user.id, 'password': 'NewPassword123',
            }), content_type='application/json')
            self.assertTrue(json.loads(UserView().patch(reset).content)['error'])
            delete = self.factory.delete('/account/user/?id=987')
            delete.user = User(id=1)
            self.assertTrue(json.loads(UserView().delete(delete).content)['error'])
            change = self.factory.patch('/account/self/', data=json.dumps({
                'old_password': 'TestingPass123', 'new_password': 'NewPassword123',
            }), content_type='application/json')
            change.user = self.user
            self.assertTrue(json.loads(SelfView().patch(change).content)['error'])
        save.assert_not_called()
        self.assertEqual(self.user.type, 'ldap')
        self.assertFalse(self.user.is_deleted)

    def test_project_startup_never_imports_retired_libraries(self):
        script = '''
import builtins
original_import = builtins.__import__
def checked_import(name, *args, **kwargs):
    if name == 'ldap' or name.startswith('ldap.') or name in ('libs.ldap', 'libs.push'):
        raise AssertionError('Retired dependency imported: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked_import
import django
django.setup()
from django.core.management import call_command
call_command('check')
import spug.wsgi
import spug.asgi
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(__file__).resolve().parents[2],
                                env={**os.environ, 'SPUG_DEBUG': '1',
                                     'DJANGO_SETTINGS_MODULE': 'apps.setting.test_retirement_settings'},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
