"""Standalone ASGI entry point for the Moon MCP Streamable HTTP service."""
import os
from contextlib import asynccontextmanager

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django  # noqa: E402

django.setup()

from starlette.applications import Starlette  # noqa: E402
from starlette.routing import Mount  # noqa: E402
from apps.mcp_ops.mcp_server import http_app, server, RESOURCE_URL, ISSUER_URL  # noqa: E402
from mcp.server.auth.routes import create_protected_resource_routes  # noqa: E402
from pydantic import AnyHttpUrl  # noqa: E402


@asynccontextmanager
async def lifespan(app):
    async with server.session_manager.run():
        yield


application = Starlette(
    routes=create_protected_resource_routes(
        resource_url=AnyHttpUrl(RESOURCE_URL), authorization_servers=[AnyHttpUrl(ISSUER_URL)],
        scopes_supported=['mcp:operate'], resource_name='Moon Operations',
    ) + [Mount('/mcp', app=http_app)],
    lifespan=lifespan,
)
