# Moon MCP 操作服务

Moon 提供独立的 Streamable HTTP MCP 端点，用于列出已授权服务器、检查 SSH 连接以及执行受限脚本。服务只接受后台创建的限时 Bearer 令牌，不能传入任意地址、用户名、私钥或密码。

## 客户端连接

MCP 地址为 Moon 站点根路径下的 `/mcp/`：

```text
https://moon.example.com/mcp/
```

请求头（手动配置 Bearer；本功能不提供 OAuth 动态注册或自动登录流程）：

```text
Authorization: Bearer moon_xxx
```

令牌明文只在创建或重新生成成功后展示一次。数据库只保存 SHA-256 摘要和短前缀，无法找回明文。有效期仅支持 1、7、30 天，采用固定绝对到期时间，不会因调用而延期；到期后需要重新生成，重新生成会立即撤销旧令牌。

提供三个工具：

- `list_servers`：列出令牌已授权且操作者当前仍有权限的登记主机。
- `check_connection`：对指定登记主机执行 SSH 连通性检查。
- `execute_script`：执行受限脚本，超时 1-300 秒，输出最多 64 KiB。

每次调用都会重新检查令牌到期/撤销状态、操作者启用状态、`system.mcp.use` 权限和当前主机分组权限。危险命令复用 Moon 智能体风险规则并直接拒绝；动态变量/命令展开、间接解释器执行和无法解析的脚本需要改用交互式终端人工确认。MCP 风险检查不是 Shell 沙箱，不应向不可信用户授予脚本执行权限。

默认单进程的 SSH 操作并发上限为 4，连接检查共享额度；不要通过增加 Uvicorn workers 绕过该限制。脚本、输出和失败信息会脱敏后写入 MCP 专用审计日志。超时会关闭 SSH 通道和连接，但不能保证远端已自行脱离会话的后台进程被终止。

## 后台权限

角色可分配以下权限：

```text
system.mcp.view  查看令牌和审计日志
system.mcp.add   创建令牌
system.mcp.edit  重新生成令牌
system.mcp.del   撤销令牌
system.mcp.use   通过令牌调用 MCP 工具
```

普通用户仅能查看、重新生成、撤销自己持有的令牌；日志内容同时受当前主机权限约束。超级管理员可全局管理，重新生成不会把管理员身份授权给普通用户。

后台路径为 `/system/mcp`。批量执行页也提供“MCP 操作日志”入口。

## 部署

安装项目依赖并应用迁移：

```bash
cd /data/spug/spug_api
./venv/bin/pip install -r requirements.txt
./venv/bin/python manage.py migrate
```

MCP 必须由支持 ASGI lifespan 的 Uvicorn 独立运行，不能挂在现有 Daphne `ProtocolTypeRouter` 中：

```bash
MOON_MCP_RESOURCE_URL=https://moon.example.com/mcp \
MOON_MCP_ISSUER_URL=https://moon.example.com \
sh tools/start-mcp.sh
```

Supervisor 配置启动 `spug-mcp`（本机 `127.0.0.1:9003`），Nginx 的 `/mcp` 将请求代理到该进程，并覆盖 `X-Moon-Client-IP` 为实际代理对端地址。生产环境必须设置上面的公开 HTTPS URL，且反向代理只应信任自身写入的客户端 IP 头。

## 验证

后端隔离测试使用内存 SQLite、LocMemCache、内存 Channel Layer：

```bash
SPUG_DEBUG=true DJANGO_SETTINGS_MODULE=apps.mcp_ops.test_settings \
  ./venv/bin/python manage.py test apps.mcp_ops.tests -v 2
```

真实 HTTP 联调会创建临时 SQLite 数据库、启动临时 Uvicorn，使用官方 `mcp.Client` 完成初始化、`tools/list` 和 `tools/call`；不连接真实 SSH 主机：

```bash
SPUG_DEBUG=true ./venv/bin/python -m apps.mcp_ops.test_http_integration
```
