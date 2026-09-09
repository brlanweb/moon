import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve

from apps.setting.models import KEYS_DEFAULT, Setting
from apps.setting.utils import AppSetting
from apps.setting.views import SettingView


class RetiredDirectorySettingTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_retired_config_is_not_a_default(self):
        self.assertNotIn('ldap_service', KEYS_DEFAULT)

    def test_read_hides_retired_config_even_if_value_is_corrupt(self):
        for value in ('not-json', json.dumps({'admin_password': 'test-only-password'})):
            with self.subTest(value=value), patch.object(Setting.objects, 'all', return_value=[
                    Setting(key='ldap_service', value=value),
                    Setting(key='verify_ip', value='false')]):
                data = json.loads(SettingView().get(self.factory.get('/setting/')).content)
            self.assertNotIn('ldap_service', data['data'])
            self.assertFalse(data['data']['verify_ip'])
            self.assertNotIn('test-only-password', json.dumps(data))

    def test_setting_read_hides_retired_push_secret(self):
        rows = [Setting(key='spug_push_key', value=json.dumps('test-only-key'))]
        with patch.object(Setting.objects, 'all', return_value=rows):
            data = json.loads(SettingView().get(self.factory.get('/setting/')).content)
        self.assertNotIn('spug_push_key', data['data'])

    def test_batch_with_retired_config_is_rejected_before_any_write(self):
        request = self.factory.post('/setting/', data=json.dumps({'data': [
            {'key': 'verify_ip', 'value': False},
            {'key': 'ldap_service', 'value': {}},
        ]}), content_type='application/json')
        with patch.object(AppSetting, 'set') as save:
            data = json.loads(SettingView().post(request).content)
        self.assertTrue(data['error'])
        save.assert_not_called()

    def test_ordinary_setting_can_still_be_saved(self):
        request = self.factory.post('/setting/', data=json.dumps({'data': [
            {'key': 'verify_ip', 'value': False},
        ]}), content_type='application/json')
        with patch.object(AppSetting, 'set') as save:
            data = json.loads(SettingView().post(request).content)
        self.assertFalse(data['error'])
        save.assert_called_once_with(key='verify_ip', value=False)

    def test_internal_setting_writer_also_rejects_retired_key(self):
        with patch.object(Setting.objects, 'update_or_create') as save:
            with self.assertRaises(KeyError):
                AppSetting.set('ldap_service', {})
        save.assert_not_called()

    def test_retired_endpoints_no_longer_resolve(self):
        for path in ('ldap/', 'ldap_test/', 'ldap_import/'):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve('/' + path, urlconf='apps.setting.urls')

    def test_cleanup_migration_only_deletes_retired_setting_on_selected_database(self):
        module = importlib.import_module('apps.setting.migrations.0002_remove_ldap_service')
        apps = Mock()
        editor = SimpleNamespace(connection=SimpleNamespace(alias='test-database'))
        module.remove_retired_directory_config(apps, editor)
        apps.get_model.assert_called_once_with('setting', 'Setting')
        manager = apps.get_model.return_value.objects
        manager.using.assert_called_once_with('test-database')
        manager.using.return_value.filter.assert_called_once_with(key='ldap_service')
        manager.using.return_value.filter.return_value.delete.assert_called_once_with()
        self.assertFalse(module.Migration.operations[0].reversible)
