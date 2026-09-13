# MySQL 默认数据库 1046 修复报告

日期：2026-09-13

## 结论

数据库终端现已为每个 MySQL/MariaDB 连接维护请求级活动数据库，并将其从元数据树传递到 QueryPanel、execute API、命令策略和 PyMySQL 连接参数。执行未限定表名的 SQL 时，请求级新连接可使用界面当前显示的数据库，且不会修改持久化连接记录。

## 根因确认

- ConnectionForm 允许 MySQL/MariaDB 的默认数据库为空。
- 原 `_mysql()` 仅读取连接记录的 `connection.database`，空配置会传 `database=None`。
- 元数据树展示 schema，但 group 点击不更新任何执行上下文。
- QueryPanel 原 execute payload 仅包含 `id` 与 `command`。
- execute API 每次新建驱动连接，无法继承前端元数据树中看到的 schema，导致未限定表名 SQL 报 MySQL 1046。

## 修改

### 前端

- DatabaseConsole 新增按连接 ID 保存的活动数据库状态。
- MySQL/MariaDB 元数据加载后，连接配置的 database 优先；配置为空时选择第一个 metadata group。
- 点击 database group 或其 table 时更新活动数据库。
- 普通关闭 tab 保留活动数据库；显式或空闲断开连接时清除。
- QueryPanel 接收 `activeDatabase`，在 endpoint 显示，并随 execute payload 发送 `database`。

### 后端

- execute API 新增可选 `database` 参数，规范化后长度限制为 1～128；拒绝空字符串、纯空白和超长覆盖。
- 仅 MySQL/MariaDB 使用请求覆盖；未传时由客户端工厂回退到连接记录配置；其他数据库类型忽略请求覆盖。
- `execute()` 与 `_mysql()` 通过驱动参数传递数据库名，不拼接 SQL，不修改连接模型。
- 生产确认令牌加入有效执行数据库字段，令牌不能在切换 database 后重放同一 SQL。

### Redis 检查

`spug_api/apps/database/client.py` 首行仍为 `import json`，`_redis_execute` 的 JSON 序列化路径不存在确定性 NameError，因此未添加无必要的修复或回归测试。

## TDD 证据

### 红灯

1. 前端首次运行：
   - 命令：`CI=true npm test -- --runInBand src/pages/database/DatabaseConsole.test.js`
   - 结果：16 项中 4 项失败。
   - 正确失败点：execute payload 缺少 `database`；点击 group/table 后 endpoint 未显示活动数据库。
2. 前端刷新优先级补充红灯：
   - 同一命令运行 17 项，1 项失败。
   - 正确失败点：刷新 metadata 后仍保留手动选择的 `analytics`，未恢复配置记录的 `operations`。
3. 后端聚焦红灯：
   - 命令：`SPUG_DEBUG=true ./venv/bin/python manage.py test apps.database.test_connections.DriverTimeoutTests.test_mysql_receives_request_database_override apps.database.test_connections.DriverTimeoutTests.test_mysql_execute_without_override_uses_configured_database apps.database.test_connections.RunCommandPolicyTests.test_mysql_request_database_overrides_without_mutating_connection apps.database.test_connections.RunCommandPolicyTests.test_non_mysql_request_database_does_not_override_connection apps.database.test_connections.RunCommandPolicyTests.test_request_database_rejects_blank_and_overlong_values apps.database.test_connections.RunCommandPolicyTests.test_confirmation_token_cannot_be_replayed_for_another_database apps.database.test_policy.CommandPolicyTests.test_confirmation_token_is_bound_to_effective_database -v 2`
   - 结果：7 项未通过。
   - 正确失败点：`_mysql`/policy 尚不接受 database；API 未校验或转发覆盖；确认令牌未绑定数据库。

### 绿灯

- `CI=true npm test -- --runInBand src/pages/database/DatabaseConsole.test.js src/pages/database/index.test.js src/pages/database/ConnectionForm.test.js src/pages/database/connectionUri.test.js`
  - 4 个套件、56 项测试通过。
- `SPUG_DEBUG=true ./venv/bin/python manage.py test apps.database.test_policy apps.database.test_connections -v 2`
  - 56 项测试通过。
- `./venv/bin/python -m py_compile apps/database/client.py apps/database/views.py apps/database/policy.py apps/database/test_connections.py apps/database/test_policy.py`
  - 通过。

## 覆盖清单

- 空配置自动选择首个 schema 并进入 execute payload：已覆盖。
- 配置 database 优先及 metadata 刷新后恢复：已覆盖。
- 点击 group 切换并执行：已覆盖。
- 点击 table 切换：已覆盖。
- 普通关闭 tab 保留、断开连接清除：已覆盖。
- 后端 MySQL 请求覆盖且不修改记录：已覆盖。
- 非 MySQL 请求覆盖被忽略：已覆盖。
- 未传覆盖时回退连接配置：已覆盖。
- 空白和超过 128 字符覆盖被拒绝：已覆盖。
- 生产确认令牌 database 错配拒绝：policy 与 API 两层已覆盖。

## 自审

- 变更限定在数据库终端前端、数据库 API/client/policy 及对应测试。
- database 作为 PyMySQL 驱动参数传递，没有 SQL 标识符拼接。
- 请求覆盖没有赋值给 `DatabaseConnection`，不存在持久化副作用。
- policy 默认参数保持原调用兼容，并在调用方传入实际执行数据库。
- 已检查调用点，QueryPanel、execute 与 enforce_command_policy 没有遗漏的生产调用。
- Docker 日志前端既有未提交改动未修改、未回退、未暂存。

## 已知提示

- 前端测试输出包含 Node `punycode` deprecation warning。
- 后端测试输出包含 Paramiko/Cryptography TripleDES deprecation warning。
- 两类提示均为既有依赖告警，不影响本次测试结果。

## 审查问题修复追加

### 修复内容

- QueryPanel 仅在 MySQL/MariaDB 且存在活动数据库时附加 `database`；PostgreSQL、ClickHouse、Redis 不再发送空数据库覆盖。
- execute API 先解析连接标识并加载连接，再仅对 MySQL/MariaDB 的请求级数据库覆盖执行非空字符串与 128 字符上限校验；非 MySQL 请求中的 `database` 字段被忽略。
- metadata 请求开始时记录每连接的选择版本；用户随后选择 group 或 table 会推进版本，旧请求响应仍可刷新目录，但不会覆盖较新的活动数据库。没有新选择时仍按配置数据库或首个 metadata group 自动初始化。
- 增加 Redis 非标量返回值经 `json.dumps(..., default=str)` 序列化的回归覆盖。
- 增加 production 确认令牌在同一 `analytics` 数据库下二次请求成功，并验证调用 `execute(item, command, database='analytics')`。

### TDD 证据

红灯：

- 前端新增测试首次运行共 21 项，4 项按预期失败：PG/ClickHouse 请求仍携带 `database: ''`；在途刷新响应覆盖了较新的 group/table 选择。
- 后端聚焦运行 3 项，其中 PG/ClickHouse 的 `database: ''` 两个子测试按预期因全局 override 校验失败；Redis JSON 分支和同库确认令牌正向行为已由现有实现满足，新增测试首次即通过，未为其修改生产代码。

绿灯：

- `SPUG_DEBUG=true ./venv/bin/python manage.py test apps.database.test_policy apps.database.test_connections -v 2`：58 项通过。
- `CI=true npm test -- --runInBand src/pages/database/DatabaseConsole.test.js src/pages/database/index.test.js src/pages/database/ConnectionForm.test.js src/pages/database/connectionUri.test.js`：4 个套件、60 项通过。
- `git diff --check`：通过。

### 范围与约束

- 请求级数据库覆盖继续只传给 `_mysql`，未写回连接记录。
- confirmation token 继续绑定用户、连接、命令与实际执行数据库；同库可确认执行，跨库重放仍拒绝。
- 本次仅修改数据库 bugfix 文件及本报告；Docker 页面既有未提交改动未修改、未暂存。
