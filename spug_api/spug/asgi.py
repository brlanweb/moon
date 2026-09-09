# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
"""ASGI config for Django HTTP and existing Channels WebSockets.

Moon MCP runs as a dedicated Uvicorn process via spug.mcp_asgi so its lifespan
is always started; Daphne remains responsible for this application.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter  # noqa: E402
from consumer import routing  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': routing.ws_router,
})
