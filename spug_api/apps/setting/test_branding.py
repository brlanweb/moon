import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.deploy.helper import NotifyMixin
from apps.schedule.utils import send_fail_notify
from libs.locale import translate_console
from libs.spug import Notification


class MoonBrandTests(SimpleTestCase):
    @patch('libs.spug.requests.post')
    def test_monitor_notifications_brand_only_generated_content(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'errcode': 0, 'StatusCode': 0}
        notify = Notification(None, '1', 'https://spug.cc', 'Spug user title', 'Spug user output', None)
        for method, users in (
            (notify.monitor_by_dd, [('https://example.com/dd', None)]),
            (notify.monitor_by_fs, [('https://example.com/fs', None)]),
            (notify.monitor_by_qy_wx, ['https://example.com/wx']),
        ):
            with self.subTest(channel=method.__name__):
                method(users)
                payload = json.dumps(post.call_args.kwargs['json'], ensure_ascii=False)
                self.assertIn('来自 Moon运维平台', payload)
                self.assertIn('Spug user title', payload)
                self.assertIn('Spug user output', payload)
                self.assertIn('https://spug.cc', payload)

    @patch('libs.spug.requests.post')
    def test_deploy_notifications_use_moon_for_every_action(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'errcode': 0}
        user = SimpleNamespace(nickname='Spug operator')
        req = SimpleNamespace(
            name='Spug deployment', deploy=SimpleNamespace(
                app=SimpleNamespace(name='Spug app'), env=SimpleNamespace(name='test')),
            created_by=user, approve_by=user, do_by=user, status='3',
            reason='approved', approve_at=None, type='1',
        )
        for method in (NotifyMixin._make_dd_notify, NotifyMixin._make_wx_notify):
            for action in ('approve_req', 'approve_rst', 'deploy_rst'):
                with self.subTest(channel=method.__name__, action=action):
                    method('https://example.com/hook', action, req, '1.0', 'host')
                    markdown = post.call_args.kwargs['json']['markdown']
                    payload = json.dumps(markdown, ensure_ascii=False)
                    self.assertIn('来自 Moon运维平台', payload)
                    self.assertIn('Spug deployment', payload)
                    if 'title' in markdown:
                        self.assertEqual(markdown['title'], 'Moon 发布消息通知')

    @patch('libs.spug.requests.post')
    def test_schedule_notifications_preserve_user_output(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'errcode': 0}
        for mode in ('1', '3'):
            with self.subTest(mode=mode):
                task = SimpleNamespace(name='Spug task', type='shell', rst_notify=json.dumps({
                    'mode': mode, 'value': 'https://example.com/hook',
                }))
                send_fail_notify(task, 'Spug command output')
                payload = json.dumps(post.call_args.kwargs['json'], ensure_ascii=False)
                self.assertIn('来自 Moon运维平台', payload)
                self.assertIn('Spug command output', payload)

    def test_console_translation_matches_new_brand_and_preserves_path(self):
        text = "\r\n检测到该主机的发布目录 '/data/spug' 已存在，为了数据安全请自行备份后删除该目录，Moon 将会创建并接管该目录。"
        self.assertEqual(translate_console(text, 'zh'), text)
        self.assertEqual(translate_console(text, 'en'),
                         "\r\nThe deploy directory '/data/spug' already exists on this host, please back it up and remove it yourself for data safety, Moon will create and take over this directory.")
        self.assertEqual(translate_console('Spug EOF 2108111926 0', 'en'), 'Spug EOF 2108111926 0')
