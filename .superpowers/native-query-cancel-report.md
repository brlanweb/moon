# 原生查询取消交付报告

## 状态与提交

- 开发、测试与代码提交已完成；等待主代理独立核验。未部署新功能、未重启服务、未推送远端。
- 开始时工作区干净，基线：`e531468a6486968197c73ef12dfec038cdb50312`。
- 实现提交：`43025d93f5bef6d9a2064ec39e98814f8d8e1398`，`feat(database): add precise native query cancellation and target selection`。
- 本报告与完成后的计划另作文档提交；其 SHA 可由 `git log -1 -- .superpowers/native-query-cancel-report.md` 获取。
- 修改范围仅数据库后端、数据库控制台前端、对应测试、计划和本报告。没有模型/迁移改动、没有全局安装软件。

## 实现

### 注册、权限与竞态

- 浏览器使用 Web Crypto 生成随机 128 位标识，组成 `时间戳.随机标识` execution_id；一次生产确认沿用原 execution_id、SQL 和 database/schema 快照。
- 独立 `POST /api/database/cancel/` 记录取消意图；同一路径 GET 查询执行状态。均校验 `database.query.do` 和 `database.connection.view`，并校验连接存在。
- Redis key 按用户、连接、execution_id 隔离；原子 Lua 完成 begin/cancel/update/finish。每个用户的同一连接同时最多一个已登记执行。
- 先取消后登记产生 pending tombstone，后续 begin 直接确认 cancelled，完全不发送业务查询。完成记录拒绝重放，旧取消不影响新执行，其他用户的取消只会写入自己的命名空间。
- execution_id 启动有效期 1 小时，取消/状态有效期 2 小时；记录保留 2 小时，执行端 heartbeat 延长活动记录和连接锁，避免正常运行时租期过早释放。
- 取消接口不接受客户端提供的 pid/thread_id/query_id 等目标。真实目标由执行端获取后登记，状态接口不返回内部目标。
- 控制线程属于执行请求，在工作连接释放前 join。控制端发出请求仅代表 sent；只有工作端收到原生中断结果才报告 cancelled。查询正常结束仍为 completed。
- 取消控制失败报告 failed，查询保持运行；新的取消请求可触发重试。没有以 HTTP abort 代替数据库取消。
- 已发送查询遭遇网络丢失时报告 unknown，保留锁定和状态确认，不宣称已取消/已完成。连接准备失败则明确失败，避免无业务查询的错误被误认为正在运行。

### 各驱动

| 数据库 | 实现 | 验证范围 |
| --- | --- | --- |
| MySQL / MariaDB | 独立、预先建立且不重连的控制连接执行 KILL QUERY；工作连接只用于这一轮业务查询 | 本地 MariaDB 10.8 真实 SELECT SLEEP 中断；同用户权限控制、跨用户隔离、并行查询存活 |
| PostgreSQL | 登记 pid 与 backend_start；控制查询同时约束 pid、backend_start、当前数据库与当前用户，再调用 pg_cancel_backend | 驱动版本与安全 Identifier 引用验证；没有可用本地 PG 服务，未做真实服务中断验证 |
| ClickHouse | 预生成 UUID query_id，经实际驱动支持的 settings 参数传入；KILL QUERY 按 query_id 精确匹配，检查 kill_status；关闭工作查询重试；识别普通/流式 Code 394 | 真实安装驱动参数验证、流式异常回归；没有可用本地 CH 服务，未做真实服务中断验证 |
| Redis | single_connection_client 工作/控制连接，禁用自动重试，登记 client_id 后禁止连接重建；只对已知 blocking 命令 CLIENT UNBLOCK ... ERROR | 本地 Redis 真实 XREAD BLOCK 中断 |

Redis EVAL/FCALL/SCRIPT/FUNCTION 等不能精确取消的命令，返回 `cancel_status=unsupported`；不调用全局 SCRIPT KILL / FUNCTION KILL。普通非 blocking 命令也不伪报支持。

取消控制配置使用请求内副本移除业务 read_only 初始化选项，仅用于内部登记目标；原始连接配置、SQL 只读策略和生产一次性 Redis token 均保留。

### 执行目标和界面

- MySQL/MariaDB 与 ClickHouse 选择数据库；PostgreSQL 选择 schema，并用 psycopg.sql.Identifier 安全构造 SET search_path，连接 dbname 保持配置值。PG 生产确认实际签名包含结构化 database/schema，显示中同时呈现二者。
- Redis 下拉只展示当前 DB，不支持切换。
- 元数据以数据库/schema 左连接表，空命名空间不生成 null 表项。仍保留 5000 项截断上限，并通过 truncated 提示目录不完整。
- 双击连接/数据库节点打开并展开；保留单击打开行为。下拉与树高亮同步；刷新目录保留用户选择，代次保护旧响应。
- 查询头部增加明显断开、执行数据库/模式下拉和运行时停止按钮；取消请求期间显示“正在中断”，失败展示明确反馈。
- 运行和生产确认期间禁止切换目标、清空、关闭标签和断开；断开按钮提示先停止/取消确认并等待结束。结束前不允许再次运行。
- 手动断开清理目录、目标、命令和会话状态；QueryPanel 带会话代次 key。idle 定时器继续保留，运行/确认期间不会自动断开。
- 请求响应丢失时轮询服务端执行状态；仅确认终态后解锁，旧取消响应不能污染新结果。
- 头部支持换行，避免新增控件在较窄窗口互相挤压。

## TDD 与测试证据

先加入缺失模块/行为测试并执行红灯，再实现注册表和取消；前端 execution_id/停止按钮、空数据库、PG schema 快照、网络未知结果、CH 流式取消均记录了红灯运行。旧测试中“运行中可断开并重连”和“刷新重置数据库”的预期随明确的新要求改为保护/保留选择，不删除安全回归目标。

最终验证：

1. 后端 **91 项通过**，包含真实 Redis 注册表原子/并发测试和 **5 项本地数据库集成测试**：
   ```sh
   docker exec -e NATIVE_CANCEL_INTEGRATION=1 -w /data/spug/spug_api spug4 python3 manage.py test apps.database.test_connections apps.database.test_policy apps.database.test_executions --noinput
   ```
   真实 MariaDB SELECT SLEEP、Redis XREAD BLOCK、独立 cancel API、提前取消/重放、取消一个用户后另一个物理查询正常完成均通过。仅使用既有本地容器，连接构造断言目标为本地 Compose db；没有用生产连接执行查询或写入。
2. 前端 **5 个套件 / 85 项通过**：
   ```sh
   cd spug_web
   CI=true npm test -- --watch=false --runInBand src/pages/database
   ```
   仍存在工具链已有 Node DEP0040 punycode 弃用提示，不影响通过。
3. 隔离生产构建 **Compiled successfully**：
   ```sh
   cd spug_web
   npm run build -- --config-overrides ../.superpowers/native-build-overrides.cjs
   ```
   覆盖脚本复用原 config-overrides，仅将 paths.appBuild 指向 `.superpowers/native-query-build`。脚本和构建产物为本地忽略文件；未放入交付代码。可复现的脚本内容：
   ```js
   const path = require('path');
   module.exports = {
     webpack: require('../spug_web/config-overrides'),
     paths: paths => ({...paths, appBuild: path.resolve(__dirname, 'native-query-build')}),
   };
   ```
4. `manage.py makemigrations --check --dry-run`：No changes detected。
5. `manage.py migrate --check`：退出 0。
6. `git diff --check`：退出 0。

实际本机虚拟环境和 spug4 容器版本一致：PyMySQL 1.2.0、psycopg 3.3.5、clickhouse-connect 0.15.1、redis-py 6.4.0、Django 4.2.30；Node 22.0.0。ClickHouse 没有使用不存在的 query(query_id=...) 参数，验证了安装版本的 valid_transport_settings/settings 实现。

## 构建过程异常及恢复

第一次尝试通过 node -e 在内存中修改 CRA 路径，未能可靠隔离 fork 子进程，导致本地 `spug_web/build` 被触碰且构建报 EEXIST/ENOENT。已终止该构建进程树，随后改用 react-app-rewired 正式 --config-overrides 路径覆盖机制，新功能构建只生成到隔离目录。

为恢复本地静态目录，从任务起点 `e531468a6486968197c73ef12dfec038cdb50312` 的前端源码独立构建成功，替换恢复 `spug_web/build`；出错的目录保留在 `.superpowers/native-dist-interrupted`。恢复的是任务前源码基线的产物，**没有宣称它与任务前未知的旧编译文件逐字节一致**。新功能未拷入运行静态目录，服务未重启。主代理应知悉这一构建副作用，并按需要检查本地页面。基线 main bundle 为 `main.aa7eeb5d.chunk.js`。

## 限制与主代理核验重点

- PostgreSQL、ClickHouse 没有本地运行实例；已实现适配并校验驱动契约，但真实数据库端权限、版本和中断行为仍需在非生产测试环境验收。MariaDB 实测不能代替 Oracle MySQL 的服务端验收。
- 安全取消依赖目标账号的相应权限；拒绝控制操作时显示失败并保留运行状态。Redis 非 blocking、脚本/函数不支持精确取消属于设计限制。
- 网络丢失、执行进程异常终止无法可靠证明服务端已结束，系统保守锁定。活动锁的异常退出过期上限为 2 小时；应由管理员检查数据库侧执行状态后处理，不能据“锁过期”宣称查询已取消。客户端超出 execution_id 时间窗口后需人工核实，不自动解除不确定状态。
- Redis 注册表是强依赖，必须供所有 HTTP worker 共享；不能切回进程内字典/LocMemCache。
- 没有额外启动 PostgreSQL/ClickHouse 容器，没有下载或全局安装依赖。没有 UI 真浏览器验收，界面验证为 React DOM 行为测试及生产构建。
- 已自审目标绑定、控制线程 join、连接复用、生产确认与 idle 回归；没有宣称完成独立代理审查。请主代理进行最终核验。

## 部署所需步骤（未执行）

1. 主代理复核实现 SHA、报告及上述限制，补做非生产 PostgreSQL/ClickHouse/Oracle MySQL 验收。
2. 确认目标部署的四类驱动与实测契约相容，所有服务 worker 使用同一个可用 Redis；HTTP 服务允许至少两个请求并行，避免执行请求占满 worker 后 cancel API 排队。
3. 核对数据库用户的取消权限；保持原始连接只读和生产确认设置。部署本次后端源码与重新生成的前端生产产物，不能只替换前端。
4. 无新增数据库迁移，但按现有部署规范再次执行迁移检查。仅在主代理授权部署流程中进行服务 reload/restart。
5. 非生产验收停止/失败/unsupported、双击展开、下拉同步、PG schema、生产确认锁定、断开清理及 idle。生产环境不以慢查询做验收。
6. 如需回滚，回到基线或回滚实现提交，并同步恢复前后端；进行中的执行先等待或安全取消，避免把仍在运行的请求当作已结束。


## 2026-09-13：两项 Important 审查修复

### 提交与范围

- 本轮起点：`57a184517029f7c28934a2eaac721143b48fba2c`；起始工作区干净。
- 修复及回归测试提交：`2a6fd37eeea3550578c069185f889344accaaab6`，`fix(database): keep cancellation reachable and distinguish preflight rejection`。
- 本节作为后续报告提交追加；最终报告提交 SHA 由 `git log -1 -- .superpowers/native-query-cancel-report.md` 查询。
- 先阅读 QueryPanel、views、executions、公共 HTTP 封装、原报告及现有测试，再补红灯测试；实现仅改 QueryPanel、数据库 views 和公共 HTTP 的显式 opt-in 分支。未修改全局认证装饰器、其他页面生产代码、模型或迁移。
- 已提交；未推送、未部署、未重启服务。临时浏览器验收服务器已停止，已调用浏览器关闭工具。

### Important 1：确认弹窗遮挡停止

根因：确认执行仅追加 token 后调用 execute，confirmation 状态一直保留到成功结果。运行中不能取消弹窗，网络丢失/unknown 又不会关闭弹窗，导致下面的停止按钮虽然存在，却被 Modal 遮罩拦截真实指针事件。

修复：点击“确认执行”时先保存原 payload 与 token，再关闭确认展示；execute 保存冻结的请求副本。execution_id、SQL、database/schema、token 均保持本轮快照，后续父组件更新不能改写已确认的请求。查询进入 unknown 或网络恢复时重置停止按钮的等待状态，保留运行锁，允许再次停止。服务端未知结果继续记录可重试的取消失败反馈；注册表故障不能把 unknown 变成 failed/not_started。

可达性证据不是只调用 DOM `.click()`：使用真实 Chromium、真实 QueryPanel/Ant Design/CSS/公共 HTTP，隔离测试页仅替换编辑器、权限入口和 HTTP 网络端点。

- 基线 `57a1845`：确认执行后 dialog 仍显示；`elementFromPoint` 表明停止按钮被覆盖；Playwright `click(trial=true)` 超时并报告遮罩 `intercepts pointer events`。`stopCovered=true, realClickBlockedByOverlay=true`。
- 修复版分别验证服务端 `unknown` 与真实浏览器 `route.abort('failed')` 网络失败：确认后 dialog 隐藏，停止按钮命中测试通过；每个场景实际点击停止 **2 次**（第一次控制失败，第二次重试），最终 `cancelled`；两次执行请求的 execution_id/命令/database/token 快照校验通过。
- 点击均由 Playwright 正常交互完成，没有 force 点击、没有移除遮罩、没有用 JavaScript 直接触发按钮事件替代真实点击。

### Important 2：明确执行前拒绝被错误恢复轮询

根因：权限/连接/参数等分支返回 `{data:'', error:'...'}`，公共 HTTP 将其拒绝为字符串；QueryPanel 将全部 rejection 当成可能已执行，开始查询尚未登记的 execution_id，状态返回空对象后永久重试。

新协议与边界：

| 情况 | 服务端/HTTP 识别 | 前端行为 |
| --- | --- | --- |
| execute 的明确前置拒绝 | 保留旧 error 信封，增加 `execution_status=not_started` | 显示错误、解锁、零状态轮询 |
| 成功信封中的 `data.status=not_started` | 同样作为确定未启动 | 错误展示、解锁、不轮询 |
| 认证/网关明确拒绝 | execute 的 HTTP 400/401/403/404/405/413/415/422/429 | 解锁、不轮询；保留既有 401 登录跳转 |
| 真实传输结果未知 | opt-in HTTP 的 `networkUncertain`，或服务端 `status=unknown` | 保守锁定并恢复状态轮询；仅确认 completed/cancelled/failed 后释放 |
| cancel/status 被明确拒绝 | `execution_status=unavailable` 或确定 HTTP 错误 | 终止自动查询、保留未知执行锁、允许手动停止重试/管理员核实 |
| 畸形响应/未分类服务端异常 | 不标记为网络异常或 not_started | 停止自动恢复、保持锁定，不能宣称已结束 |

数据库专用装饰器统一覆盖权限装饰器拒绝、连接查看权限、非法 JSON 顶层/语法、参数校验、连接不存在、执行 ID、只读/确认策略、注册失败等明确错误。前置检查与 execute 调用分开，确认 token 存储故障也能确定业务命令未发送；dispatch 之后的注册表/连接故障不会误标 not_started。

公共 HTTP 仅对 `executionProtocol: true` 请求提供结构化 rejection；普通页面继续得到原有字符串错误、原有成功数据和登录跳转。没有用错误文案或语言翻译猜测是否执行。旧客户端不带 execution_id 时，执行失败继续返回 error 信封，标记 failed 而非 not_started。

### TDD 与最终验证

红灯记录（本机忽略的日志保留）：

- `native-review-frontend-red.log`：真实 Axios/公共响应拦截链下 **10 项失败、2 项通过**；覆盖未解锁、弹窗仍遮挡、状态拒绝后多发查询。最初测试导入路径错误已先修正，再取得这些行为红灯。
- `native-review-backend-red.log`：前置分支缺失协议标识，并暴露非对象 JSON、非字符串/空白命令等异常分支。
- `native-review-retry-red.log`：停止中的执行变成 network/unknown 后不能重试停止，**2 项失败**。
- `native-review-preflight-red.log`：前置确认存储故障缺少 not_started、未知执行缺少可重试取消反馈，**2 项断言失败**。
- `native-review-malformed-red.log`：畸形 execute/status 响应被当成网络未知，**3 项失败**。
- `native-review-http-red.log` 和 `native-review-legacy-backend-red.log`：公共 HTTP 网络错误字符串契约及旧客户端错误信封兼容性红灯；均在提交前修复并回归。

最终结果：

1. **数据库后端 104 项通过，0 跳过**，包括 **5 项本地原生取消集成**：MariaDB SLEEP、Redis XREAD BLOCK、独立 cancel API 用户隔离、提前取消与重放拒绝、取消一个物理查询不影响另一用户查询。
   ```sh
   docker exec -e NATIVE_CANCEL_INTEGRATION=1 -w /data/spug/spug_api spug4 python3 manage.py test apps.database.test_connections apps.database.test_policy apps.database.test_executions apps.database.test_execution_protocol --noinput
   ```
   输出 `Found 104 test(s)` / `Ran 104 tests` / `OK`。仍使用既有本地 Compose 数据库，集成构造器断言数据库 HOST 为 db；未访问生产数据库。
2. **数据库前端 6 套件 / 117 项通过**：
   ```sh
   cd spug_web
   CI=true npm test -- --watch=false --runInBand src/pages/database
   ```
3. 公共 HTTP 改动额外跑 **全部前端 25 套件 / 258 项，全部通过**：
   ```sh
   cd spug_web
   CI=true npm test -- --watch=false --runInBand
   ```
   新协议测试使用真实 Axios、真实公共拦截器和真实 React/Modal，仅在 HTTP adapter 边界提供完整响应/网络故障。保留全套运行中既有的 Node 弃用及其他页面 React act 警告，不将其描述成无警告运行。
4. **真实浏览器**补验：上述两个 unknown/network 场景正常停止与重试；首次 execute 被 not_started 拒绝时 `executeRequests=1,statusRequests=0,unlocked=true`；生产确认后被拒绝时 `executeRequests=2,statusRequests=0,unlocked=true`。状态明确拒绝场景仅 **1 次 GET**，等待超过两个轮询间隔后不再自动发请求，同时 `unknownExecutionLocked=true`。
5. **隔离生产构建成功**，输出到 `.superpowers/native-review-build`，main bundle 为 `main.eec862f8.chunk.js`：
   ```sh
   cd spug_web
   npm run build -- --config-overrides ../.superpowers/native-review-build-overrides.cjs
   ```
   覆盖脚本复用原 config-overrides，仅设置 paths.appBuild。构建前后运行静态目录 **26 个文件**的文件集合和 SHA-256 全部一致；没有把新构建产物复制到服务目录。
6. `git diff --check`、暂存区 `git diff --cached --check` 均通过。

浏览器隔离夹具、基线构建和本机日志位于 `.superpowers/native-review-browser` 与 `.superpowers/native-review-*.log`，属于本机忽略的验收产物；可持续回归的前后端测试已随修复提交。浏览器测试的网络端点为受控响应，与上述真实 MariaDB/Redis 集成分开验证，不冒称全链路生产环境测试。PostgreSQL/ClickHouse 的真实实例验收限制沿用原报告。本轮完成修复者自审与上述自动化/浏览器核验；当前子代理环境不支持再派遣独立审查代理，没有声称完成独立复审。
