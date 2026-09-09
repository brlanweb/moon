"""No external delivery: all transports and site notifications are mocked."""
from types import SimpleNamespace
from unittest.mock import patch
import json

from django.test import SimpleTestCase

from libs.spug import Notification
from apps.schedule.utils import send_task_notify


class NotificationTransportTests(SimpleTestCase):
    def setUp(self):
        post = patch('libs.spug.requests.post')
        self.post = post.start()
        self.addCleanup(post.stop)
        notify = patch('libs.spug.Notify.make_system_notify')
        self.notify = notify.start()
        self.addCleanup(notify.stop)
        self.response = self.post.return_value
        self.response.status_code = 200
        self.response.url = 'https://example.test/hook'

    def test_generic_webhook_accepts_non_json_http_success(self):
        self.response.json.side_effect = ValueError('not JSON')
        Notification.handle_request('https://example.test/hook', {'message': 'test'})
        self.post.assert_called_once_with('https://example.test/hook', json={'message': 'test'}, timeout=15)
        self.response.json.assert_not_called()
        self.notify.assert_not_called()

    def test_supported_vendor_success(self):
        for mode, payload in [('dd', {'errcode': 0}), ('wx', {'errcode': 0}), ('fs', {'StatusCode': 0})]:
            with self.subTest(mode=mode):
                self.response.json.return_value = payload
                Notification.handle_request('https://example.test/hook', {}, mode)
        self.assertEqual(self.post.call_count, 3)
        self.notify.assert_not_called()

    def test_retired_or_unknown_transport_never_sends(self):
        for mode in ('push_spug', '1', '2', '6', 'unknown'):
            with self.subTest(mode=mode):
                Notification.handle_request('https://example.test/hook', {}, mode)
        self.post.assert_not_called()
        self.assertEqual(self.notify.call_count, 5)

    def test_vendor_non_json_becomes_site_notification(self):
        self.response.json.side_effect = ValueError('not JSON')
        Notification.handle_request('https://example.test/hook', {}, 'dd')
        self.notify.assert_called_once()

    def test_unexpected_json_shape_or_vendor_failure_becomes_site_notification(self):
        for payload in (None, [], 'ok', {}, {'errcode': 42}):
            with self.subTest(payload=payload):
                self.response.json.return_value = payload
                Notification.handle_request('https://example.test/hook', {}, 'wx')
        self.assertEqual(self.notify.call_count, 5)

    def test_http_failure_becomes_site_notification(self):
        self.response.status_code = 500
        Notification.handle_request('https://example.test/hook', {}, 'fs')
        self.notify.assert_called_once()
        self.response.json.assert_not_called()

    def test_network_failure_becomes_site_notification(self):
        self.post.side_effect = RuntimeError('connection unavailable')
        Notification.handle_request('https://example.test/hook', {}, 'dd')
        self.notify.assert_called_once()


class TaskChannelContractTests(SimpleTestCase):
    def task(self, mode):
        return SimpleNamespace(id=7, name='test-task', type='test',
                               rst_notify=json.dumps({'mode': mode, 'value': 'https://example.test/hook'}))

    def test_task_modes_keep_their_own_mapping(self):
        for task_mode, transport in [('1', 'dd'), ('2', None), ('3', 'wx'), ('4', 'fs')]:
            with self.subTest(mode=task_mode), patch.object(Notification, 'handle_request') as send:
                send_task_notify(self.task(task_mode), False, 'test-message')
                send.assert_called_once()
                args = send.call_args.args
                self.assertEqual(args[2] if len(args) > 2 else None, transport)

    def test_task_generic_webhook_reaches_transport_without_vendor_contract(self):
        with patch('libs.spug.requests.post') as post, patch('libs.spug.Notify.make_system_notify') as notify:
            post.return_value.status_code = 200
            post.return_value.json.side_effect = ValueError('not JSON')
            send_task_notify(self.task('2'), False, 'test-message')
        post.assert_called_once()
        post.return_value.json.assert_not_called()
        notify.assert_not_called()

    def test_disabled_task_notification_does_not_send(self):
        with patch.object(Notification, 'handle_request') as send, patch('apps.schedule.utils.Mail') as mail:
            send_task_notify(self.task('0'), False, 'test-message')
        send.assert_not_called()
        mail.assert_not_called()

    def test_task_smtp_mode_is_five_not_monitor_mode_four(self):
        task = self.task('5')
        task.rst_notify = json.dumps({'mode': '5', 'value': 'ops@example.test'})
        with patch('apps.schedule.utils.AppSetting.get_default', return_value={'server': 'smtp.example.test'}), \
                patch('apps.schedule.utils.Mail') as mail, patch.object(Notification, 'handle_request') as webhook:
            send_task_notify(task, False, 'test-message')
        mail.return_value.send_text_mail.assert_called_once()
        self.assertEqual(mail.return_value.send_text_mail.call_args.args[0], ['ops@example.test'])
        webhook.assert_not_called()
