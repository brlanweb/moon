# Docker 概览服务器实时指标交付报告

日期：2026-09-14。开发基线：`eb6c740`，开始时 `git status --short` 为空。源码及上层目录未发现适用的 AGENTS.md；依赖目录和历史验证副本没有作为实现目标。此次工作已获用户开发、验证和提交授权。

## 实现与复用判断

项目实际使用 Django / Paramiko / django-redis，以及 React 16、Ant Design 4、BizCharts 3；没有引入 Vue、其他图表库或新依赖。

检查了 Docker `OverviewPanel`、现有主机 `metrics.py`、Host.get_ssh、SSH.exec_command_raw、Docker localStorage 缓存、仪表盘 AlarmTrend 的 BizCharts 用法和现有 Docker 测试。

旧主机指标 API 的结果缓存是 15 秒，快照 300 秒，没有采集互斥锁；同时采集磁盘、温度、网络，首次远端 sleep，且找不到 timeout 时直接执行 nvidia-smi。原始 SSH exec_command_raw 没有读取期限。旧 Docker 缓存没有 TTL。这些行为不适合直接用于本次 5 秒图表轮询。因此新增独立、轻量的主机图表 API，复用 Host、权限体系、SSH 凭据获取、Redis 连接和已有图表库，保留旧主机列表行为。

- 新增 `GET /api/host/metrics/overview/?id=<host_id>`。任何 Redis 读取和 SSH 前，先校验 `host.host.view`、get_host_perms、主机存在和 verified 状态。采集目标只来自所选 Host，没有应用本机或 Docker 容器回退。
- CPU 使用相邻 /proc/stat 累计计数差值；guest/guest_nice 不重复计入总量。初始基线、计数回绕、异常差值均返回 null，不构造 0。
- 内存使用 `(MemTotal - MemAvailable) / MemTotal`。缺失或异常 available 不猜测、不使用 free 替代。
- NVIDIA GPU 使用现有 nvidia-smi，每卡独立曲线；顶部最新值标为“最高”。缺少工具显示“未检测到 GPU”。驱动失败、N/A、缺少 timeout 则 GPU 不可用，不影响 CPU/内存。
- 单次远端只读命令读取 proc 和可选 GPU，无磁盘扫描、远程文件写入、安装、采样 sleep 或常驻远程进程。GPU 使用 `timeout -s KILL 2`；没有 timeout 时跳过 GPU。
- SSH 建连/banner/auth 分别限制 5 秒；打开 channel 限制 5 秒，读取总期限 6 秒、输出上限 64 KiB。另有 12 秒 channel 看门狗，关闭 transport 解除 Paramiko exec_command 等待 acknowledgement 不遵守 settimeout 的问题。看门狗在 finally 取消，channel 和连接均清理。原始错误和远端输出不会返回浏览器。
- 概览顶部三个图表横向铺满，600px 以下堆叠。HostMetrics 与容器 Engine 请求独立，即使 Docker 查询未返回也能显示服务器曲线。缺失点保持 null，曲线断开；移动端限制时间刻度，避免文字被裁切。

## 缓存精确语义与成本

| 项目 | 精确定义 |
| --- | --- |
| 采样新鲜度 | 5 秒。最近一次尝试完成后 5 秒内直接返回缓存；失败也缓存，防止连续失败引起 SSH 风暴。 |
| 浏览器轮询 | 立即请求，此后每次请求完成后等待 5 秒再请求。实际采样间隔是请求耗时加 5 秒，慢请求不重叠。 |
| Redis 数据 TTL | 固定 60 秒，从最近一次采集尝试写入开始计算。缓存命中的 GET 不续期。无观察者时不再采集，最后写入后最多 60 秒键自动失效。 |
| Redis 共享范围 | `spug:host:chart:v1:<id>`，同一主机跨用户、标签页、worker 共享结果、CPU 基线和历史。 |
| 锁 | 同主机 `:lock`，SET NX EX 60；失败者只读历史/返回 collecting。获锁后再次读取缓存消除竞态。Lua 校验 owner token 后释放；进程崩溃时锁最多保留 60 秒。 |
| 历史窗口 | 最近 300 秒，最多 61 点。只在持续观察时通过更新同一 Redis 键累积；它不是 300 秒缓存 TTL。键过期后历史和 CPU 基线一起清除。 |
| 浏览器缓存 TTL | 内存 Map，按 hostId 隔离，从响应收到起 60 秒。不使用原来无 TTL 的 localStorage。最多 50 主机，每主机最多 61 点；读写时清除过期项，挂载时每秒清理和推进状态。卸载后不留定时器，残留 Map 数据在下次访问懒清理且不可命中过期项。 |
| 立即回显 | 切回主机时 useState 同步读取有效缓存，立即渲染，同时后台更新；旧主机请求完成后因 disposed 标识被丢弃，不能写缓存或更新新主机。 |
| 过期显示 | 使用 server_time/sample time 差值加客户端经过时间计算年龄。超过 5 秒标记“数据已过期 · 更新中”；样本年龄超过 60 秒不再画旧曲线或旧最新值。后台更新不把旧样本年龄清零。 |
| 停止与降级 | 离开概览/卸载清理 timeout、interval、visibility listener；隐藏标签页停止发起轮询，返回后立即更新。进行中的单个请求自然结束并受超时限制。Redis 故障直接返回不可用，不执行绕过共享锁的 SSH。 |

正常持续观察时每主机最多约 12 次探针/分钟（实际受 SSH 耗时影响更少），每次最多一次 SSH 握手、一次 exec 和一次有上限的 nvidia-smi。多用户新增的是轻量 HTTP/Redis 读取，不按人数倍增本接口的远端探针。缓存均固定 60 秒，未提供可越过 30 分钟的配置入口。

## 自动验证结果

### 后端：65 项通过

本机默认 Redis 6379 未运行。首次直接执行旧 Docker 测试时，3 个已有 create/remove 项目用例因缓存失效操作连接 Redis 失败。没有启动或更改已有容器；改用测试进程内 LocMemCache 隔离这些既有缓存操作，新图表测试使用受控 Redis mock 验证 NX、重复读取、写 TTL 和 owner release 调用。

可复现命令（仓库根目录执行）：

```sh
cd spug_api
SPUG_DEBUG=1 DJANGO_SETTINGS_MODULE=spug.settings venv/bin/python - <<'PY'
import django
from django.conf import settings
settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
django.setup()
from django.test.runner import DiscoverRunner
raise SystemExit(bool(DiscoverRunner(verbosity=1).run_tests([
    'apps.docker.tests', 'apps.host.test_overview_metrics', 'apps.host.tests'
])))
PY
```

结果：`Ran 65 tests ... OK`，Django system check 无问题。新增 10 项覆盖 CPU 差值/guest/首次缺失、内存 available、GPU 异常独立处理、缓存命中避免重复采集、锁竞争/获锁后二次检查、失败缓存不泄漏异常、历史限点及陈旧基线、权限先于缓存、真实授权 host 传递、Redis 故障不触发 SSH、采集超时连接清理。

初次使用 `apps.docker` 包路径还遇到项目 namespace package 的测试发现错误；最终明确使用 `apps.docker.tests`，没有修改业务代码来绕过测试加载问题。

### 前端：45 项通过，生产构建通过

```sh
cd spug_web
CI=true npm test -- --watch=false --runInBand --testPathPattern=pages/docker
npm run build
```

结果：`Test Suites: 2 passed`，`Tests: 45 passed`，`Compiled successfully`。Node.js 22.0.0；保留项目现有 openssl legacy build 参数。

新增覆盖缓存立即回显/60 秒失效、旧 host 响应丢弃、请求不重叠、卸载无定时器、后台标签暂停恢复、无 GPU、缺失值不转 0、过期标记，以及容器概览请求挂起时主机指标仍能展示。原有 Resources 的两条 act 警告和依赖 punycode/TripleDES 弃用警告保留，不影响通过。

### 迁移与差异

```sh
cd spug_api
SPUG_DEBUG=1 venv/bin/python manage.py makemigrations --check --dry-run
# 仓库根目录
 git diff --check
```

结果：`No changes detected`，diff check 无输出。没有新 model，不需要迁移。没有执行 migrate、部署或重启。

## 视觉证据

使用 agent-browser，在仅绑定 127.0.0.1 的隔离页面运行真实 HostMetrics、原样 LESS 和真实 BizCharts。HTTP 数据为模拟值，不访问任何服务器。下方统计卡片是验收页占位内容，不代表整页 Docker 端到端登录验收。

- [桌面 1440×900](docker-metrics-desktop.png)：三个 Canvas 并排，CPU 缺失点断线、GPU 两卡曲线，更新时间和最新值可见。
- [移动端 390px 完整页面](docker-metrics-mobile.png)：CPU/内存/GPU 垂直堆叠，时间刻度可读。
- [无 GPU](docker-metrics-no-gpu.png)：CPU/内存继续画图，GPU 显示“未检测到 GPU”。
- 浏览器检查：桌面 3 个 Canvas；移动端 `overflow=false`，Canvas Y 坐标 `[232,473,710]`；浏览器 errors 无输出。
- [隔离验收生成脚本](docker-metrics-visual.cjs)：运行 `NODE_OPTIONS=--openssl-legacy-provider node .superpowers/docker-metrics-visual.cjs`，再用 Python http.server 仅绑定本机提供生成目录。无需安装依赖。
- 本次启动的浏览器会话和两个临时 HTTP server 已关闭。

## 局限及交接

1. 本次后端验证使用 mock SSH/Redis，没有生产负载实验、真实 GPU 驱动测试或真实 Redis 多进程压力验证。没有把模拟图表截图声称为真实服务器监控。
2. 只支持有 /proc/stat、/proc/meminfo 的 Linux 主机和已有 NVIDIA 工具；其他 GPU 暂不探测。没有 MemAvailable 的旧系统显示内存不可用。无 timeout 时 GPU 安全跳过。
3. 首次 CPU 需要下一次采样才能显示；无人观察超过 60 秒后需要重建基线，这是刻意的低开销语义。页面刷新会丢失内存缓存，但首次 API 返回仍可恢复有效 Redis 历史。
4. 旧主机列表 metrics API 保持原有行为，使用独立缓存；同时打开旧列表和 Docker 概览时，两类接口仍可能分别采集。同一新图表 API 的多用户/多标签采集已通过共享锁合并。本次没有顺带改动旧主机监控语义。
5. SSH 建连仍有每轮握手成本；没有常驻 SSH 连接池或远程 agent。极端 DNS/操作系统不可中断等待不属于本次模拟验证范围。
6. 仅执行 `docker ps --format '{{.Names}}\t{{.Status}}'`：现有 `spug4`、`spug4-db` 均运行，数据库 healthy。未进入容器修改数据，未部署、重启或访问生产主机。

## 部署步骤（交由主代理核验后执行）

1. 核验提交 diff、上述测试和报告。按现有发布流程构建后端镜像与前端静态文件，确保全部后端 worker 使用同一 Redis。
2. 发布含新 host 路由的后端及匹配前端。没有数据库迁移和远程软件安装步骤；本报告不代表已经发布。
3. 在授权的测试主机验证首次 CPU 采集中、第二点出现、无 GPU 降级、5 秒新鲜度、60 秒切回缓存、无权限拒绝；多标签验证同主机探针不倍增。不要在生产主机做负载实验。
4. 回滚时恢复前一版前后端发布产物；新 Redis 数据和锁键会在最长 60 秒内自行过期，无需删表或批量清理 Redis。
