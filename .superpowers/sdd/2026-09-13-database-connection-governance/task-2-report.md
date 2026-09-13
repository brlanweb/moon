# 数据库连接治理任务 2 实现报告

## 结论

已完成只读策略和生产数据变更确认后端实现，并严格按红灯、绿灯、重构流程完成策略层和 API 层测试。未修改、回退或暂存工作区中既有的 Docker 前端改动。

## 实现内容

### SQL 与 Redis 策略

- 新增 `spug_api/apps/database/policy.py`，使用 `sqlparse` 解析 SQL 注释、空白、多语句和 CTE。
- SQL 只读分类允许查询、解释和元数据读取；写操作、DDL、DCL、调用及未知语句在只读连接上拒绝。
- 检测 CTE 内的数据变更，避免外层 `SELECT` 掩盖 `INSERT`、`UPDATE` 或 `DELETE`。
- 区分 PostgreSQL `COPY ... TO` 与 `COPY ... FROM`。
- Redis 使用明确只读命令集合；写命令、未知命令及非只读子命令不会被当作只读命令。
- 普通连接不增加确认流程；生产环境仅已识别的数据变更触发确认。

### 生产确认令牌

- 使用 `django.core.signing.dumps/loads` 的时间戳签名。
- 令牌绑定用户 ID、数据库连接 ID 和完整命令的 SHA-256 摘要。
- 有效期为 60 秒。
- 令牌不依赖全局一次性存储。
- 篡改、过期以及用户、连接或命令错配统一拒绝。

### API 行为

- `run_command` 接受可选字段 `confirmation_token`。
- 生产数据变更第一次请求返回：
  - `requires_confirmation: true`
  - `confirmation_token`
  - `statement_types`
- 第一次请求不调用数据库执行函数。
- 有效且匹配的确认令牌允许执行。
- 只读违规或令牌错配在执行前返回错误。

### 依赖

- `spug_api/requirements.txt` 显式加入 `sqlparse >= 0.5.3, < 0.7.0`。
- 当前虚拟环境为 Python 3.12.13、sqlparse 0.6.0，位于声明范围内。

## TDD 证据

1. 新建策略测试后运行 `apps.database.test_policy`，因 `apps.database.policy` 不存在而失败。
2. 实现策略后，策略测试转绿。
3. 新增 API 测试后运行 `RunCommandPolicyTests`，因确认挑战缺失且命令被直接执行而失败。
4. 修改 `run_command` 后，API 测试转绿。
5. Redis `MEMORY PURGE`、`TOUCH` 以及 `COPY (SELECT ... FROM ...) TO` 边界测试均先失败，随后通过最小分类修正转绿。

## 最终验证

- `SPUG_DEBUG=true ./venv/bin/python manage.py test apps.database.test_policy -v 2`：17 项通过。
- `SPUG_DEBUG=true ./venv/bin/python manage.py test apps.database.test_connections -v 2`：22 项通过。
- `./venv/bin/python -m pip check`：未发现损坏的依赖关系。
- `git diff --check`：通过。

## 变更文件

- `spug_api/apps/database/policy.py`
- `spug_api/apps/database/test_policy.py`
- `spug_api/apps/database/views.py`
- `spug_api/apps/database/test_connections.py`
- `spug_api/requirements.txt`
- `.superpowers/sdd/2026-09-13-database-connection-governance/task-2-report.md`

## 疑虑

- 测试启动时 Paramiko 会输出上游 `TripleDES` 弃用警告，不影响本任务测试结果。
- 本地未配置生产模式所需的 `SPUG_SECRET_KEY`，因此测试使用 `SPUG_DEBUG=true` 启动；签名测试仍使用 Django 测试配置中的 `SECRET_KEY` 完成真实签名与过期校验。
