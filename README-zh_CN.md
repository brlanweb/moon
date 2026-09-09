# Moon

简体中文 | [English](./README.md)

![Moon](./spug_web/public/logo.png)

Moon 是面向已登记服务器的运维控制台，在 OpenSpug 基础上扩展了智能体运维、容器管理和资源监控，并统一使用 Moon 品牌与界面风格。

## 功能

- 主机资产、分组、SSH 终端、文件管理及批量脚本执行。
- 独立的容器项目、镜像、网络和存储管理页面。
- 智能问答、服务器任务、危险命令审批、执行过程和停止生成。
- 服务监控，以及 CPU、内存、磁盘、温度阈值告警。
- 应用发布、流水线、计划任务、配置管理和数据库控制台。
- 本地账户登录、角色权限管理、中英双语界面。
- 站内通知，以及直连邮件、钉钉、飞书、企业微信通知。

LDAP 和外部推送助手集成已下线。原依赖推送助手的 MFA 验证码通道不再可用；若旧 MFA 策略仍启用，需要管理员明确处理，不能静默绕过。

## 本地运行

使用 Node.js 22、项目 Python 环境（已在 Python 3.10/3.12 验证）及 Docker Compose。内部包名、数据库标识和兼容配置保留，避免破坏现有安装。

```sh
git clone https://github.com/brlanweb/moon.git
cd moon
cd spug_web
npm ci
npm run build
cd ..
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml exec spug python3 /data/spug/spug_api/manage.py migrate
```

访问 http://127.0.0.1:8000。本地 Compose 使用仅供开发的默认配置，不可直接作为公网生产部署；生产环境必须单独配置凭据、访问限制及备份。

执行功能下线迁移前必须备份数据库。被移除的凭据内容无法仅靠反向结构迁移恢复。源码及前端构建产物已挂载至本地应用容器：Python 修改需重载应用进程，前端修改需重新执行 `npm run build`。

## MCP 操作

通过官方 SDK 实现的 Streamable HTTP 端点为 `/mcp/`。在“系统管理 / MCP 操作”创建、重新生成或撤销令牌；专用操作日志也可从批量执行页进入。

有效期固定为 1 天、7 天或 30 天，最长 30 天，调用不会续期；到期后必须重新生成，新令牌生成时旧令牌立即撤销。明文只展示一次，数据库仅保存不可逆摘要。普通用户仅管理自己的令牌，日志访问遵循当前主机权限。仅可操作已登记且当前有权访问的服务器；危险或动态展开的脚本会被拒绝。详见 [MCP 配置与安全边界](./docs/mcp.md)。

## 源码与许可

- Moon 仓库：https://github.com/brlanweb/moon
- 上游项目：https://github.com/openspug/spug
- 许可证：GNU Affero General Public License v3.0，详见仓库保留的许可证文件。

保留 OpenSpug 及其他上游贡献者的版权声明。Moon 为独立维护的衍生项目，不代表 OpenSpug 官方发行版。Git 历史以及现有安装所需的技术标识均予以保留。
