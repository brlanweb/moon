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
