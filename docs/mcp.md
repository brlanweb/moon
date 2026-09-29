# Moon MCP 操作服务

Moon 提供独立的 Streamable HTTP MCP 端点，用于列出服务器、检查 SSH 连接、执行受限脚本以及上传/下载文件。服务只接受后台创建的限时 Bearer 令牌，不能传入任意地址、用户名、私钥或密码。

## 客户端连接

MCP 地址为 Moon 站点根路径下的 `/mcp/`：

```text
https://moon.example.com/mcp/
```

请求头（手动配置 Bearer；本功能不提供 OAuth 动态注册或自动登录流程）：

```text
Authorization: Bearer moon_xxx
```

令牌明文只在创建或刷新成功后展示一次。数据库只保存 SHA-256 摘要和短前缀，无法找回明文。有效期支持 1、7、30 天、6 个月（180 天）和 1 年（365 天），采用固定绝对到期时间，不会因调用而延期。

令牌不再绑定服务器：只要令牌有效，即可访问 Moon 中全部已登记服务器（含之后新增的）。令牌管理只有两个动作：

- **刷新**：原地更换密钥（令牌 ID 与审计记录保留），旧密钥立即失效，可重新选择有效期。
- **删除**：永久删除令牌记录，立即失效；历史审计日志保留但不再关联令牌。

提供以下工具：

- `list_servers`：列出全部已登记主机。
- `check_connection`：对指定登记主机执行 SSH 连通性检查。
- `execute_script`：执行受限脚本，超时 1-300 秒，输出最多 64 KiB。
- `create_upload_link`：为指定主机的远程文件路径生成一次性上传链接。
- `create_download_link`：为指定主机的远程文件生成一次性下载链接。

每次调用都会重新检查令牌到期状态、操作者启用状态和 `system.mcp.use` 权限。危险命令复用 Moon 智能体风险规则并直接拒绝；动态变量/命令展开、间接解释器执行和无法解析的脚本需要改用交互式终端人工确认。MCP 风险检查不是 Shell 沙箱，不应向不可信用户授予脚本执行权限。

默认单进程的 SSH 操作并发上限为 4，连接检查共享额度；不要通过增加 Uvicorn workers 绕过该限制。脚本、输出和失败信息会脱敏后写入 MCP 专用审计日志。超时会关闭 SSH 通道和连接，但不能保证远端已自行脱离会话的后台进程被终止。

## 文件传输

MCP 协议本身不适合传输大文件，因此由工具生成一次性 HTTP 链接，客户端直接用 curl 传输：

```bash
# 上传：create_upload_link(host_id=1, remote_path="/tmp/app.tar.gz") 返回的 url
curl -fsS -T ./app.tar.gz "https://moon.example.com/mcp/files/mft_xxx"
# 下载：create_download_link(host_id=1, remote_path="/tmp/app.log") 返回的 url
curl -fsS -o ./app.log "https://moon.example.com/mcp/files/mft_xxx"
```

规则：

- 链接一次性使用，30 分钟过期；链接本身即凭据，不需要再带 Bearer，请勿泄露。`HEAD` 请求不会消耗链接。
- 单文件上限 1 GiB；上传请以原始请求体发送（`curl -T` 或 `--data-binary @file`），不支持 multipart 表单。
- 远程路径必须是绝对路径、不能含 `..`，且必须位于白名单目录内；传输时会在远端解析符号链接后再次校验，目标为符号链接时拒绝上传。
- 上传写入同目录的临时文件，完成后原子替换目标文件；上级目录必须已存在。响应返回文件大小与 SHA-256。
- 使用链接时会重新检查令牌有效性与操作者权限；令牌被删除或过期后，未使用的链接也随之失效。
- 进程内同时最多 2 个文件传输。创建链接、上传、下载都会写入 MCP 审计日志（`create_upload_link`、`create_download_link`、`upload_file`、`download_file`）。

白名单目录由环境变量 `MOON_MCP_FILE_DIRS` 配置（逗号或冒号分隔），默认：

```text
/tmp,/opt,/srv,/data,/home,/root
```

## 后台权限

角色可分配以下权限：

```text
system.mcp.view  查看令牌和审计日志
system.mcp.add   创建令牌
system.mcp.edit  刷新令牌
system.mcp.del   删除令牌
system.mcp.use   通过令牌调用 MCP 工具
```

普通用户仅能查看、刷新、删除自己持有的令牌；日志内容同时受当前主机权限约束。超级管理员可全局管理，刷新不会改变令牌所属操作者。

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

Supervisor 配置启动 `spug-mcp`（本机 `127.0.0.1:9003`），Nginx 的 `/mcp` 将请求代理到该进程，并覆盖 `X-Moon-Client-IP` 为实际代理对端地址。`/mcp/files/` 需关闭请求缓冲（`proxy_request_buffering off`）并放开请求体大小（`client_max_body_size 0`），示例配置见 `docs/docker/nginx.conf`。生产环境必须设置上面的公开 HTTPS URL，且反向代理只应信任自身写入的客户端 IP 头。

## 验证

后端隔离测试使用内存 SQLite、LocMemCache、内存 Channel Layer：

```bash
SPUG_DEBUG=true DJANGO_SETTINGS_MODULE=apps.mcp_ops.test_settings \
  ./venv/bin/python manage.py test apps.mcp_ops.tests apps.mcp_ops.test_security_contract apps.mcp_ops.test_files -v 2
```

真实 HTTP 联调会创建临时 SQLite 数据库、启动临时 Uvicorn，使用官方 `mcp.Client` 完成初始化、`tools/list` 和 `tools/call`；不连接真实 SSH 主机：

```bash
SPUG_DEBUG=true ./venv/bin/python -m apps.mcp_ops.test_http_integration
```
