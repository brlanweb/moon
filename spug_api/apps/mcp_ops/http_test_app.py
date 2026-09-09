"""Isolated HTTP harness: real ASGI/auth/protocol, synthetic SSH boundary only."""
import os
import socket
from unittest.mock import Mock

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'apps.mcp_ops.test_http_settings')
import django

django.setup()
from django.conf import settings

if settings.SETTINGS_MODULE != 'apps.mcp_ops.test_http_settings':
    raise RuntimeError('HTTP harness requires isolated settings')
if settings.DATABASES['default']['NAME'] != os.environ.get('MOON_MCP_TEST_DB'):
    raise RuntimeError('HTTP harness requires an explicit temporary database')

from apps.host.models import Host
from apps.mcp_ops import service


def no_outbound_network(*args, **kwargs):
    raise AssertionError('Outbound network is forbidden in MCP HTTP tests')


socket.socket.connect = no_outbound_network
Host.get_ssh = Mock(return_value=Mock(ping=Mock(return_value=True)))
service._run_ssh = Mock(return_value=(0, 'mock SSH output'))

from spug.mcp_asgi import application  # noqa: E402,F401
