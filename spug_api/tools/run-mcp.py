"""Development entry point using the same ASGI app as the deployed service."""
import os
import sys
from pathlib import Path

import uvicorn

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
    uvicorn.run(
        'spug.mcp_asgi:application',
        host=os.environ.get('MOON_MCP_HOST', '127.0.0.1'),
        port=int(os.environ.get('MOON_MCP_PORT', '9003')),
        lifespan='on', access_log=False,
    )
