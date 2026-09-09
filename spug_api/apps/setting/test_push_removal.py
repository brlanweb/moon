# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist
from django.db.migrations.loader import MigrationLoader
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.account.models import User
from apps.account.views import SelfView, UserView, handle_user_info
from apps.alarm.models import Alarm, Contact
from apps.monitor.views import DetectionView
from apps.pipeline.models import Pipeline
from apps.pipeline.utils import NodeExecutor, PUSH_MODULES
from apps.pipeline.views import PipeView, DoView
from apps.setting.models import Setting, KEYS_DEFAULT
from apps.setting.utils import AppSetting
from apps.setting.views import SettingView
from apps.setting.urls import urlpatterns
from libs.spug import Notification
from libs.utils import AttrDict


class PushRemovalTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(id=1, is_supper=True, has_perms=lambda codes: True)

    def request(self, data=None, method='post'):
        request = getattr(self.factory, method)('/', json.dumps(data or {}), content_type='application/json')
        request.user = self.user
        return request

    def test_removed_fields_are_absent(self):
        for model in (User, Contact):
            with self.subTest(model=model), self.assertRaises(FieldDoesNotExist):
                model._meta.get_field('wx_token')

    def test_settings_hide_old_credentials_and_policy_before_migration(self):
        rows = [Setting(key=k, value=json.dumps(v)) for k, v in (
            ('spug_push_key', 'old-secret'), ('MFA', {'enable': True}),
            ('mail_service', {'server': 'smtp.example.test'}), ('verify_ip', False))]
        with patch.object(Setting.objects, 'all', return_value=rows):
            data = json.loads(SettingView().get(self.request()).content)['data']
        self.assertNotIn('spug_push_key', data)
        self.assertNotIn('MFA', data)
        self.assertEqual(data['mail_service']['server'], 'smtp.example.test')
        self.assertFalse(data['verify_ip'])

    def test_settings_reject_retired_keys_before_any_write(self):
        for key in ('spug_push_key', 'MFA'):
            with self.subTest(key=key), patch.object(AppSetting, 'set') as save:
                response = SettingView().post(self.request({'data': [
                    {'key': 'verify_ip', 'value': False}, {'key': key, 'value': 'legacy'}]}))
                self.assertTrue(json.loads(response.content)['error'])
                save.assert_not_called()
                self.assertNotIn(key, KEYS_DEFAULT)

    def test_setting_store_cannot_recreate_retired_keys(self):
        with patch.object(Setting.objects, 'update_or_create') as save:
            for key in ('MFA', 'spug_push_key'):
                with self.subTest(key=key), self.assertRaises(KeyError):
                    AppSetting.set(key, 'legacy')
            save.assert_not_called()

    def test_supported_settings_still_save(self):
        with patch.object(AppSetting, 'set') as save:
            response = SettingView().post(self.request({'data': [{'key': 'bind_ip', 'value': True}]}))
        self.assertFalse(json.loads(response.content)['error'])
        save.assert_called_once_with(key='bind_ip', value=True)

    def test_removed_endpoints_are_not_registered(self):
        routes = {str(x.pattern) for x in urlpatterns}
        self.assertFalse(routes.intersection({'push/bind/', 'push/balance/', 'push/contacts/', 'mfa/'}))
        self.assertTrue({'', 'user/', 'email_test/', 'about/'}.issubset(routes))

    def test_profile_exposes_nickname_only(self):
        request = self.request()
        request.user = User(nickname='operator')
        self.assertEqual(json.loads(SelfView().get(request).content)['data'], {'nickname': 'operator'})

    def test_old_profile_payload_does_not_restore_field(self):
        request = self.request({'nickname': 'new', 'wx_token': 'old'}, 'patch')
        request.user = User(nickname='old')
        with patch.object(User, 'save'):
            response = SelfView().patch(request)
        self.assertFalse(json.loads(response.content)['error'])
        self.assertEqual(request.user.nickname, 'new')
        self.assertFalse(hasattr(request.user, 'wx_token'))

    def test_account_creation_discards_retired_field(self):
        user = Mock()
        with patch.object(User.objects, 'filter') as query, patch.object(User.objects, 'create', return_value=user) as create:
            query.return_value.first.return_value = None
            response = UserView().post(self.request({'username': 'local', 'nickname': 'Local',
                'password': 'TestingPass123', 'wx_token': 'retired'}))
        self.assertFalse(json.loads(response.content)['error'])
        self.assertNotIn('wx_token', create.call_args.kwargs)

    def test_pipeline_save_rejects_retired_nodes(self):
        for method in ('post', 'patch'):
            with self.subTest(method=method), patch.object(Pipeline.objects, 'filter') as query, \
                    patch.object(Pipeline.objects, 'create') as create:
                response = getattr(PipeView(), method)(self.request({
                    'id': 1, 'name': 'old pipeline', 'nodes': [{'id': 'old', 'module': 'push_spug'}]}, method))
                self.assertIn('已移除', json.loads(response.content)['error'])
                query.assert_not_called()
                create.assert_not_called()

    def test_pipeline_execution_rejects_legacy_nodes_before_side_effects(self):
        pipe = SimpleNamespace(nodes=json.dumps([{'id': 'old', 'module': 'push_spug'}]))
        for method in ('post', 'patch'):
            with self.subTest(method=method), patch.object(Pipeline.objects, 'get', return_value=pipe), \
                    patch('apps.pipeline.views.PipeHistory.objects.create') as history, \
                    patch('apps.pipeline.views.get_redis_connection') as redis, \
                    patch('apps.pipeline.views.Thread') as thread:
                response = getattr(DoView(), method)(self.request({'id': 1, 'token': 'old', 'params': {}}, method))
                self.assertIn('已移除', json.loads(response.content)['error'])
                history.assert_not_called()
                redis.assert_not_called()
                thread.assert_not_called()

    def test_pipeline_can_be_repaired_with_supported_node(self):
        with patch.object(Pipeline.objects, 'filter') as query:
            response = PipeView().patch(self.request({'id': 1, 'nodes': [{'module': 'push_dd'}]}, 'patch'))
        self.assertFalse(json.loads(response.content)['error'])
        query.return_value.update.assert_called_once()

    def executor(self):
        executor = NodeExecutor.__new__(NodeExecutor)
        executor.helper = Mock()
        executor.helper.tc.side_effect = lambda value: value
        executor.env = {}
        executor.pipe_name = 'test'
        executor.run = Mock()
        return executor

    def test_legacy_worker_node_fails_and_propagates_error(self):
        executor = self.executor()
        node = AttrDict(id='old', module='push_spug')
        executor._dispatch(node)
        executor.helper.send_error.assert_called_once()
        executor.helper.send_success.assert_not_called()
        executor.run.assert_called_once_with(node, 'error')
        self.assertEqual(set(PUSH_MODULES), {'push_dd', 'push_fs', 'push_wx'})

    def test_direct_webhook_nodes_still_dispatch(self):
        for module in ('push_dd', 'push_fs', 'push_wx'):
            with self.subTest(module=module), patch('apps.pipeline.utils.webhook.' + module, return_value=None) as send:
                executor = self.executor()
                node = AttrDict(id='new', module=module, url='https://example.test/hook')
                executor._dispatch(node, 'error')
                send.assert_called_once()
                executor.helper.send_success.assert_called_once()
                executor.run.assert_called_once_with(node, 'success')

    def test_direct_webhook_failure_remains_a_failure(self):
        with patch('apps.pipeline.utils.webhook.push_dd', side_effect=RuntimeError('delivery failed')):
            executor = self.executor()
            node = AttrDict(id='new', module='push_dd', url='https://example.test/hook')
            executor._dispatch(node)
        executor.helper.send_error.assert_called_once()
        executor.helper.send_success.assert_not_called()
        executor.run.assert_called_once_with(node, 'error')

    def test_retired_push_send_never_falls_back_to_wecom(self):
        with patch('apps.pipeline.utils.webhook.push_wx') as send:
            error = self.executor()._push_send(AttrDict(id='old', module='push_spug'), None)
        self.assertIn('已移除', error)
        send.assert_not_called()

    def test_monitor_api_rejects_removed_channels(self):
        for mode in ('1', '2', '6', 'push_spug', 'unknown'):
            with self.subTest(mode=mode), patch('apps.monitor.views.Detection.objects.create') as create:
                response = DetectionView().post(self.request({'name': 'old', 'group': 'ops', 'type': '1',
                    'targets': ['https://example.test'], 'notify_grp': [1], 'notify_mode': [mode]}))
                self.assertIn('已下线', json.loads(response.content)['error'])
                create.assert_not_called()

    def test_legacy_monitor_cannot_be_enabled(self):
        with patch('apps.monitor.views.Detection.objects.filter') as query:
            query.return_value.first.return_value = SimpleNamespace(notify_mode='["1"]', type='1')
            response = DetectionView().patch(self.request({'id': 1, 'is_active': True}, 'patch'))
        self.assertIn('已下线', json.loads(response.content)['error'])
        query.return_value.update.assert_not_called()

    def test_legacy_monitor_generates_site_notification(self):
        with patch('libs.spug.Group.objects.filter', return_value=[]), \
                patch('libs.spug.Notify.make_monitor_notify') as notify:
            Notification([], '1', 'target', 'alarm', 'message', '').dispatch_monitor(['1', '2', '6'])
        self.assertEqual(notify.call_count, 3)
        self.assertIn('已下线', notify.call_args.args[1])
        self.assertEqual({x[0] for x in Alarm.MODES}, {'3', '4', '5', '7'})

    def test_supported_monitor_channels_still_dispatch(self):
        contact = SimpleNamespace(email='ops@example.test', qy_wx='https://example.test/wx')
        notification = Notification([], '1', 'target', 'alarm', 'message', '')
        with patch('libs.spug.Group.objects.filter', return_value=[]), \
                patch('libs.spug.Contact.objects.filter', return_value=[contact]), \
                patch.object(notification, '_webhook_targets', return_value=[('https://example.test/hook', None)]), \
                patch.object(notification, 'monitor_by_dd') as dd, \
                patch.object(notification, 'monitor_by_email') as mail, \
                patch.object(notification, 'monitor_by_qy_wx') as wx, \
                patch.object(notification, 'monitor_by_fs') as fs:
            notification.dispatch_monitor(['3', '4', '5', '7'])
        for sender in (dd, mail, wx, fs):
            sender.assert_called_once()

    def test_migration_state_drops_only_target_fields(self):
        loader = MigrationLoader(None)
        self.assertEqual(loader.detect_conflicts(), {})
        state = loader.project_state([
            ('account', '0003_remove_user_wx_token'), ('alarm', '0002_remove_contact_wx_token')])
        for model in (('account', 'user'), ('alarm', 'contact')):
            self.assertNotIn('wx_token', state.models[model].fields)
        self.assertIn('password_hash', state.models['account', 'user'].fields)
        for field in ('email', 'ding', 'feishu', 'qy_wx', 'phone'):
            self.assertIn(field, state.models['alarm', 'contact'].fields)

    def test_cleanup_removes_credentials_without_silently_disabling_mfa(self):
        migration = importlib.import_module('apps.setting.migrations.0003_remove_push_settings')
        apps, editor = Mock(), Mock()
        editor.connection.alias = 'test-only'
        migration.remove_push_settings(apps, editor)
        apps.get_model.assert_called_once_with('setting', 'Setting')
        manager = apps.get_model.return_value.objects
        manager.using.assert_called_once_with('test-only')
        manager.using.return_value.filter.assert_called_once_with(key__in=['spug_push_key'])
        manager.using.return_value.filter.return_value.delete.assert_called_once()
        self.assertFalse(migration.Migration.operations[0].reversible)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class RetiredMFAPolicyTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    def test_enabled_old_policy_fails_closed_without_issuing_session(self):
        user = User(username='local')
        record = Mock(return_value='blocked')
        with patch.object(AppSetting, 'get_default', return_value={'enable': True}), patch.object(User, 'save') as save:
            self.assertEqual(handle_user_info(record, RequestFactory().post('/'), user), 'blocked')
        self.assertIn('MFA已移除', record.call_args.kwargs['error'])
        save.assert_not_called()

    def test_cleared_policy_keeps_normal_login(self):
        user = User(username='local', nickname='Local', is_supper=True)
        with patch.object(AppSetting, 'get_default', side_effect=lambda key, default=None: default), patch.object(User, 'save'):
            response = handle_user_info(Mock(), RequestFactory().post('/'), user)
        data = json.loads(response.content)
        self.assertFalse(data['error'])
        self.assertEqual(len(data['data']['access_token']), 32)
        self.assertNotIn('required_mfa', data['data'])
