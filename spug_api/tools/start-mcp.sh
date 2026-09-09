#!/bin/sh
# Start the standalone Streamable HTTP MCP service under an ASGI server that
# supports lifespan. Daphne remains dedicated to the existing WebSocket app.
set -e
cd "$(dirname "$(dirname "$0")")"
if [ -f ./venv/bin/activate ]; then
  . ./venv/bin/activate
fi
exec uvicorn spug.mcp_asgi:application \
  --host 127.0.0.1 --port "${MOON_MCP_PORT:-9003}" \
  --lifespan on --no-access-log --proxy-headers --forwarded-allow-ips=127.0.0.1
