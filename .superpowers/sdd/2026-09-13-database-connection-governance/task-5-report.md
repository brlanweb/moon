# 任务 5：生产确认交互与完整验证报告

## 状态

已完成任务 5 的前端实现、TDD 测试、范围内验证和提交前审查。

## 实现内容

### QueryPanel 生产危险操作确认

- 新增生产环境危险操作确认 Modal。
- 首次执行返回 `requires_confirmation: true` 时，不把挑战响应写入查询结果。
- Modal 展示：
  - 连接名称；
  - 实际执行数据库；
  - 后端返回的 statement types；
  - 完整 SQL，使用可滚动的 `pre` 区域展示。
- 取消确认只关闭 Modal，不发送第二次请求。
- 确认后使用首次请求的相同 `id`、`command`、`database`，仅追加 `confirmation_token` 后重试。
- 确认请求成功后关闭 Modal 并按原有结果组件渲染结果。
- 使用同步请求锁和按钮 loading 状态阻止重复点击；确认 Modal 存在时，普通运行入口不会自动或手动重复首次执行。
- QueryPanel 头部对 production 连接展示红色“生产”标签，对 read-only 连接展示“只读”标签；normal 且非只读连接不展示治理标签。

### 前端 HTTP timeout 适配

- 查询执行 timeout：`max(45000, query_timeout * 1000 + 5000)`。
- 连接测试 timeout：`max(45000, connect_timeout * 1000 + 5000)`。
- metadata 请求 timeout：`max(45000, connect_timeout * 1000 + 5000)`。
- 旧连接缺少 timeout 字段时仍保持至少 45000 ms。

## TDD 记录

### 红灯

新增 `QueryPanel.test.js`，并扩展 `ConnectionForm.test.js`、`DatabaseConsole.test.js` 后，首次运行：

```bash
CI=true npm test -- --watchAll=false \
  src/pages/database/QueryPanel.test.js \
  src/pages/database/ConnectionForm.test.js \
  src/pages/database/DatabaseConsole.test.js
```

结果：3 个 suite 失败，6 个测试按预期失败。失败原因分别为：

- 查询请求仍使用固定 45000 ms；
- 尚未展示危险确认 Modal；
- 尚未展示生产/只读标签；
- 连接测试未传自适应 timeout；
- metadata 请求未传自适应 timeout。

### 绿灯

完成最小实现并修正测试对 Ant Design Modal 动画隐藏状态和 Tag 范围的断言后，同一命令结果：

- 3 个 suite 全部通过；
- 38 个测试全部通过。

## 最终验证

### 数据库前端全部测试

```bash
cd spug_web
CI=true npm test -- --watchAll=false src/pages/database/*.test.js
```

结果：

- 5 个 test suites 通过；
- 68 个 tests 通过；
- 0 个失败；
- 存在 Node.js `punycode` 弃用警告，属于现有依赖警告。

### 数据库后端测试与迁移检查

未设置 Django 测试环境的首次命令在启动前失败：

```text
RuntimeError: SPUG_SECRET_KEY is required when SPUG_DEBUG is disabled
```

按照本项目既有数据库治理验证方式，显式设置测试环境后重新运行：

```bash
cd spug_api
SPUG_DEBUG=true ./venv/bin/python manage.py test \
  apps.database.test_policy apps.database.test_connections -v 2
SPUG_DEBUG=true ./venv/bin/python manage.py makemigrations --check
```

结果：

- 58 个后端测试通过；
- Django system check 无问题；
- `makemigrations --check` 返回 `No changes detected`；
- Paramiko/Cryptography 输出既有 TripleDES 弃用警告。

### 前端生产构建

```bash
cd spug_web
npm run build
```

结果：构建成功。保留一个既有警告：`DatabaseConsole` 的 idle timer effect 缺少 `disconnectConnection` hook dependency；本任务未扩大范围修改该既有结构。

### 差异检查

```bash
git diff --check
```

结果：退出码 0，无空白错误。

## 代码审查

当前执行上下文不提供可调用的子代理接口，因此无法派发独立 reviewer。已按任务简报进行提交前人工审查，重点检查：

- 挑战响应不会进入查询结果；
- 确认重试只追加 token，不重新读取编辑器或数据库选择；
- 取消不会触发重试；
- running 同步锁覆盖按钮和编辑器快捷键入口；
- 低 timeout 保持 45000 ms 下限，高 timeout 增加 5000 ms 前端余量；
- 暂存清单仅包含任务 5 数据库文件和本报告。

未发现 Critical 或 Important 问题。

## 范围与疑虑

- Docker 日志前端的 3 个未提交文件始终保留在工作树中，未修改、未回退，也不会加入任务 5 提交。
- 前端构建和测试中的弃用/Hook dependency 警告均为既有问题，不属于任务 5 直接引入的问题。

## 审查修复

独立审查发现生产确认弹窗使用前端推测数据库，无法准确展示 PostgreSQL、ClickHouse 和 Redis 的驱动默认数据库；同时指出挑战 fixture 与真实只读策略不一致、低超时兼容测试不足。

TDD 红灯确认：

- `QueryPanel.test.js` 因弹窗仍显示前端 `tenant_42` 而非后端 `execution_database` 失败。
- `RunCommandPolicyTests` 新增四项断言因挑战响应缺少 `execution_database` 失败。

修复内容：

- 后端统一解析实际执行数据库：PostgreSQL `postgres`、ClickHouse `default`、Redis `0`，MySQL/MariaDB 使用请求覆盖或连接配置。
- 挑战响应返回 `execution_database`，并继续以同一值绑定确认令牌。
- 前端确认弹窗只展示后端返回的实际执行数据库。
- 生产写确认测试改用可写连接，只读标签改为独立 fixture。
- 查询、连接测试和 metadata 均补充低值与缺失配置时 `45000 ms` 下限测试。

验证结果：

- 前端定向测试 3 个 suites、44 项全部通过。
- 前端数据库全量测试 5 个 suites、74 项全部通过。
- 后端 `test_policy` 与 `test_connections` 共 59 项全部通过。
- `makemigrations --check` 返回 `No changes detected`。
- 前端生产构建成功；仅保留报告前文记录的既有 Hook dependency 警告。

## 最终审查问题修复

已按 `final-review-fixes.md` 完成全部 Critical 和 Important 项：

- 生产确认令牌加入随机 nonce，并在共享 Redis 中按 60 秒 TTL 保存；令牌继续绑定用户、连接、SQL SHA-256 与实际执行数据库，确认时通过 Redis Lua 原子读取并删除，保证一次性消费。
- 增加令牌重复使用和双线程并发消费回归测试，只有一个并发请求可以通过。
- MySQL/MariaDB 只读连接通过 `SET SESSION TRANSACTION READ ONLY` 设置会话默认只读；PostgreSQL 使用 `default_transaction_read_only=on`；ClickHouse 使用 `readonly=1`。词法策略继续作为前置拒绝层。
- MySQL 与 MariaDB 均保守识别 `/*!`，MariaDB 额外识别 `/*M!` 可执行注释。
- 生产确认范围收敛为数据变更和未知命令；已知 DDL 直接执行，但只读连接仍会在词法层与数据库会话层阻止写入。
- 查询、metadata 和连接测试的前端 HTTP timeout 统一为 `max(45000, (connect_timeout + query_timeout) * 1000 + 5000)`，覆盖高低组合。
- 保存已打开的编辑连接时，先递增 metadata 请求代次并完整断开旧标签、命令、活动数据库和目录状态，再刷新连接列表；过期 metadata 响应不会恢复旧状态。
- 控制台按连接记录进行中的查询数；空闲清理跳过运行中查询，并在查询完成后重新开始空闲计时。连接已断开时，迟到的查询完成回调不会恢复活动状态。
- `Dockerfile.local` 与 `spug_api/requirements.txt` 的 sqlparse 约束统一为 `>=0.5.3,<0.7.0`。

### TDD 记录

后端新增 8 项回归测试后先运行，67 项中出现 11 个预期失败和 3 个预期错误，分别覆盖令牌重放/并发消费、DDL、MariaDB 可执行注释及三类 SQL 驱动会话只读参数。完成最小实现后，同一命令 67 项全部通过。

前端新增或调整回归测试后先运行，3 个 suites 中 6 项按预期失败，分别覆盖三处组合 timeout、编辑保存状态清理和长查询空闲保护。完成最小实现后，3 个 suites、46 项全部通过。

### 最终验证

- 数据库后端：67 项通过，0 失败；Django system check 无问题。
- 数据库前端：5 个 suites、76 项通过，0 失败。
- 迁移检查：`No changes detected`。
- 前端生产构建：成功；保留既有 `disconnectConnection` Hook dependency 警告。
- sqlparse 约束语义检查：两处均为 `>=0.5.3,<0.7.0`。
- `git diff --check`：通过。
- Docker 日志前端的 3 个既有未提交文件未修改，且不纳入本次暂存或提交。
