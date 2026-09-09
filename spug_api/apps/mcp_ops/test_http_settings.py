"""File-backed isolated settings for the real HTTP MCP integration test."""
import os
from apps.mcp_ops.test_settings import *  # noqa: F401,F403

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': os.environ.get('MOON_MCP_TEST_DB', '/tmp/moon-mcp-http-test.sqlite3'),
}}
