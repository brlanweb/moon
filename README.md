# Moon

[简体中文](./README-zh_CN.md) | English

![Moon](./moon_web/public/logo.png)

Moon is an operations console for managing registered servers, containers, deployments and monitoring. It provides AI-assisted operations, resource monitoring and a consistent Moon interface.

## Features

- Host inventory, groups, SSH terminals, file management and batch scripts.
- Separate container project, image, network and volume management pages.
- AI chat and server tasks, command approval, execution traces and generation cancellation.
- Service monitoring and CPU, memory, disk and temperature threshold alerts.
- Deployment pipelines, scheduled tasks, configuration management and database consoles.
- Role-based access control, local account login and Chinese/English interfaces.
- In-app notifications and direct email, DingTalk, Feishu and WeChat Work delivery.

LDAP and the external Push Assistant integration have been retired. The old push-based MFA transport is unavailable; an enabled legacy MFA policy must be explicitly retired by an administrator rather than silently bypassed.

## Local Development

Use Node.js 22, the project's Python environment (tested with Python 3.10/3.12), and Docker Compose.

```sh
git clone https://github.com/brlanweb/moon.git
cd moon
cd moon_web
npm ci
npm run build
cd ..
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml exec moon python3 /data/moon/moon_api/manage.py migrate
```

Open http://127.0.0.1:8000. The local Compose file contains development-only defaults and must not be exposed as a production deployment. Configure secrets, access restrictions and backups separately for production. Back up the database before applying retirement migrations; removed credentials cannot be recovered by reversing the schema alone.

The backend source and frontend build are mounted into the local application container. Python changes require an application process reload; frontend production changes require another `npm run build`.

## MCP Operations

The official-SDK Streamable HTTP endpoint is `/mcp/`. Manage tokens under **System / MCP Operations** and inspect dedicated operation logs there or from the batch execution page. Tokens expire after exactly 1, 7 or 30 days, never renew on use, and must be regenerated after expiry; regeneration revokes the old token immediately.

Only currently authorized registered hosts can be targeted. Token plaintext is shown once; stored tokens are irreversible digests. Non-administrators manage only their own tokens, and audit access follows current host permissions. Unsafe or dynamically expanded shell commands are refused. See [MCP setup and security boundaries](./docs/mcp.md).

## Source and License

- Moon source: https://github.com/brlanweb/moon
- License: GNU Affero General Public License v3.0, see [LICENSE](./LICENSE).
