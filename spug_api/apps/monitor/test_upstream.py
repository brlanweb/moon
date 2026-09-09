import configparser
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import get_commands
from django.test import RequestFactory, SimpleTestCase
from apps.host.models import HostExtend
from apps.monitor.models import Detection
from apps.monitor.views import get_overview
from libs.middleware import TranslateMiddleware
from libs.utils import json_response


class UpstreamCompatibilityTests(SimpleTestCase):
    def test_runserver_uses_daphne_for_websocket_support(self):
        self.assertEqual(get_commands()['runserver'], 'daphne')

    def test_supervisor_templates_have_matching_local_control_socket(self):
        root = Path(__file__).resolve().parents[3]
        for name in ('spug.ini', 'supervisor-host.conf'):
            with self.subTest(template=name):
                config = configparser.ConfigParser()
                config.read(root / 'docs' / 'docker' / name)
                self.assertEqual(config['unix_http_server']['chmod'], '0700')
                self.assertEqual(config['supervisorctl']['serverurl'],
                                 'unix://' + config['unix_http_server']['file'])
                self.assertEqual(config['rpcinterface:supervisor']['supervisor.rpcinterface_factory'],
                                 'supervisor.rpcinterface:make_main_rpcinterface')

    def english(self, response):
        request = RequestFactory().get('/', HTTP_X_LANGUAGE='en')
        return json.loads(TranslateMiddleware(lambda _request: response)
                          .process_response(request, response).content)['data']

    def test_host_billing_alias_is_translated(self):
        host = HostExtend(host_id=1, cpu=4, memory=8, disk='[]',
                          private_ip_address='[]', public_ip_address='[]',
                          internet_charge_type='PayByBandwidth', instance_charge_type='PrePaid')
        result = self.english(json_response(host.to_view()))
        self.assertEqual(result['internet_charge_type_alias'], 'Pay-by-bandwidth')

    def test_custom_monitor_types_remain_translatable(self):
        for kind, expected in (('6', 'Docker service check'), ('7', 'Resource monitoring')):
            with self.subTest(kind=kind):
                label = Detection(type=kind).get_type_display()
                self.assertEqual(self.english(json_response({'type_alias': label}))['type_alias'], expected)

    @patch('apps.monitor.views.get_redis_connection')
    @patch('apps.monitor.views.Detection.objects.all')
    def test_overview_has_a_translatable_type_alias(self, detections, _redis):
        detections.return_value = [Detection(id=1, name='test', type='1', targets='["https://example.com"]',
                                           is_active=False, notify_mode='[]', notify_grp='[]')]
        request = RequestFactory().get('/')
        request.user = SimpleNamespace(has_perms=lambda _codes: True)
        result = self.english(get_overview(request))[0]
        self.assertEqual(result['type_alias'], 'Site check')
        self.assertEqual(result['id'], '1_https://example.com')
