# Docker 服务监控与 AI 定向修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在监控中心新增 Docker 服务检测，并让 AI 只能在保存的 Docker 目标作用域内安全诊断、修复和严格验证恢复。

**架构：** 扩展 Docker inspect 解析并新增目标作用域模块，将监控结果标准化为包含故障类别和结构化详情的 `DetectionResult`。Docker 监控触发的智能体使用专用工具而非任意 SSH，所有写操作由后端基于不可变作用域生成，并结合配置哈希、副本基线、冷却和熔断保护。

**技术栈：** Python 3 / Django 4.2、Redis、Paramiko、PydanticAI 2.37、React 16、MobX 5、Ant Design 4。

---

## 文件结构

- 修改 `spug_api/apps/docker/client.py`：解析健康检查、重启次数和配置哈希；生成配置哈希命令、限量日志命令和受限恢复命令。
- 修改 `spug_api/apps/docker/tests.py`：锁定 inspect 元数据和所有受限 Docker 命令的安全属性。
- 创建 `spug_api/apps/monitor/docker.py`：解析监控目标、实时校验作用域、判定状态、严格恢复验证。
- 创建 `spug_api/apps/monitor/tests.py`：覆盖 Docker 状态、基础设施错误、动态宽限期、副本基线和严格验证。
- 修改 `spug_api/apps/monitor/models.py`：新增监控类型并序列化 Docker 目标。
- 修改 `spug_api/apps/monitor/executors.py`：引入 `DetectionResult`、分流故障类别并调用 Docker 检测。
- 修改 `spug_api/apps/monitor/views.py`：保存时验证 Docker 目标并固定 AI 主机。
- 修改 `spug_api/apps/monitor/utils.py`：构造 Docker 上下文、跳过基础设施错误、执行冷却/熔断和会话互斥。
- 修改 `spug_api/apps/ai/models.py`：增加不可变 `target_scope` 字段。
- 创建 `spug_api/apps/ai/migrations/0007_agentsession_target_scope.py`：数据库迁移。
- 修改 `spug_api/apps/ai/engine.py`：为 Docker 会话注册专用工具、移除任意 SSH，并在写操作后严格复检。
- 修改 `spug_api/apps/ai/agent.py`：增加 Docker 目标提示词和操作边界。
- 修改 `spug_api/apps/ai/tests.py`：覆盖工具隔离、日志截断和 Docker 写操作作用域。
- 创建 `spug_web/src/pages/monitor/DockerTarget.js`：主机、Compose 服务和独立容器级联选择。
- 修改 `spug_web/src/pages/monitor/Step1.js`：接入新监控类型和目标组件。
- 修改 `spug_web/src/pages/monitor/Step2.js`：Docker 监控启用 AI 时固定排查主机。
- 修改 `spug_web/src/pages/monitor/store.js`：初始化和编辑 Docker 目标状态。

### 任务 1：Docker 元数据与受限命令

**文件：**
- 修改：`spug_api/apps/docker/client.py`
- 测试：`spug_api/apps/docker/tests.py`

- [ ] **步骤 1：编写 inspect 元数据失败测试**

在测试载荷加入 `State.Health.Status`、`StartedAt`、`RestartCount`、`Config.Healthcheck` 和 `com.docker.compose.config-hash`，断言容器字典包含：

```python
{
    'health': 'starting',
    'started_at': '2026-09-08T01:00:00Z',
    'restart_count': 2,
    'config_hash': 'abc123',
    'health_start_period_ns': 300_000_000_000,
    'health_interval_ns': 30_000_000_000,
    'health_retries': 3,
}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd spug_api && python manage.py test apps.docker.tests.DockerClientTests -v 2`
预期：FAIL，返回容器字典缺少新增字段。

- [ ] **步骤 3：实现元数据解析**

从 `item['State']`、`item['Config']['Healthcheck']` 和 Compose 标签读取字段；所有缺失值使用空字符串或 `0`，不改变现有分组规则。

- [ ] **步骤 4：编写受限命令失败测试**

新增断言：

```python
self.assertEqual(
    build_monitor_recover_command(project, 'api', 3),
    'cd /opt/apps/demo && docker compose -p demo -f /opt/apps/demo/compose.yaml '
    'up -d --no-deps --no-recreate --pull never --scale api=3 api')
self.assertEqual(build_monitor_restart_command('demo-api-2'),
                 'docker restart -- demo-api-2')
self.assertIn('--tail 200', build_monitor_logs_command('demo-api-2'))
```

同时断言服务名、副本数和容器名中的 shell 元字符被拒绝。

- [ ] **步骤 5：实现命令构造和配置哈希读取**

新增：

```python
def build_service_hash_command(project, service): ...
def parse_service_hash(output, service): ...
def build_monitor_recover_command(project, service, replicas): ...
def build_monitor_restart_command(container): ...
def build_monitor_logs_command(container): ...
```

`build_monitor_recover_command` 固定带 `--no-deps --no-recreate --pull never --scale`；日志固定 `--tail 200`。

- [ ] **步骤 6：运行 Docker 测试并提交**

运行：`cd spug_api && python manage.py test apps.docker.tests -v 2`
预期：PASS。

提交：

```bash
git add spug_api/apps/docker/client.py spug_api/apps/docker/tests.py
git commit -m "feat: 扩展Docker监控元数据与受限命令"
```

### 任务 2：Docker 监控判定与严格验证

**文件：**
- 创建：`spug_api/apps/monitor/docker.py`
- 创建：`spug_api/apps/monitor/tests.py`
- 修改：`spug_api/apps/monitor/executors.py`

- [ ] **步骤 1：编写状态判定失败测试**

定义目标和容器工厂，覆盖以下断言：

```python
result = evaluate_target(scope, payload, now=fixed_now)
self.assertFalse(result.is_ok)
self.assertEqual(result.failure_kind, 'target')
self.assertIn('unhealthy', result.message)
```

分别覆盖：副本数不足、任一 exited/dead/restarting/unhealthy、starting 位于动态宽限期内、starting 超时、无 Healthcheck 的 running、独立容器不存在。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd spug_api && python manage.py test apps.monitor.tests -v 2`
预期：FAIL，模块或函数尚不存在。

- [ ] **步骤 3：实现标准结果和纯状态判定**

在 `apps.monitor.docker` 定义：

```python
@dataclass
class DetectionResult:
    is_ok: bool
    message: str
    failure_kind: str = ''
    details: dict = field(default_factory=dict)
```

实现 `parse_scope`、`startup_grace_seconds`、`evaluate_target`。时间解析失败时保守判为目标异常，不抛出到 worker。

- [ ] **步骤 4：实现实时检测适配**

实现：

```python
def check_target(host, raw_scope) -> DetectionResult:
    try:
        return evaluate_target(parse_scope(raw_scope), discover_all(host))
    except DockerClientError as exc:
        return DetectionResult(False, str(exc), 'infrastructure')
```

修改 `dispatch`，现有检测结果适配为 `DetectionResult`；worker、测试接口和 verifier 读取属性，不改变对外 JSON。

- [ ] **步骤 5：编写严格验证失败测试**

模拟状态序列 `starting -> healthy -> healthy`，断言前两次均不结束，连续第二次 healthy 才成功；模拟 `healthy -> unhealthy` 和超时，断言失败。

- [ ] **步骤 6：实现严格验证器**

实现 `verify_recovery(host, scope, sleep=time.sleep, monotonic=time.monotonic)`，每 10 秒采样；Healthcheck 目标要求连续两次 healthy，无 Healthcheck 要求连续两次 running。计算时间超过 30 分钟时返回需要人工处理，不进入自动修复。

- [ ] **步骤 7：运行监控测试并提交**

运行：`cd spug_api && python manage.py test apps.monitor.tests -v 2`
预期：PASS。

提交：

```bash
git add spug_api/apps/monitor/docker.py spug_api/apps/monitor/tests.py spug_api/apps/monitor/executors.py
git commit -m "feat: 增加Docker服务状态检测与严格验证"
```

### 任务 3：监控配置保存与目标发现

**文件：**
- 修改：`spug_api/apps/monitor/models.py`
- 修改：`spug_api/apps/monitor/views.py`
- 修改：`spug_api/apps/monitor/tests.py`

- [ ] **步骤 1：编写保存校验失败测试**

从视图入口覆盖：类型 `6` 必须只有一个主机；目标必须来自实时发现；Compose 服务保存 `expected_replicas` 和一致的 `config_hash`；伪造路径、服务和独立容器被拒绝；Docker 目标启用 AI 时 `ai_host_id` 被固定为目标主机。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd spug_api && python manage.py test apps.monitor.tests.DockerMonitorViewTests -v 2`
预期：FAIL，新类型和保存规范尚未实现。

- [ ] **步骤 3：实现目标标准化**

在 Docker 监控模块新增：

```python
def validate_and_normalize_scope(host, raw_scope):
    # 实时 discover，服务哈希与所有副本标签一致才保存 config_hash
    # 保存服务当前副本数，独立容器只保存容器名
```

配置哈希能力不可用时保存空哈希和 `can_recover_missing=False`，而不是阻止监控。

- [ ] **步骤 4：接入模型和视图**

`Detection.TYPES` 增加 `('6', 'Docker服务检测')`。POST 中类型 `6` 校验单主机、序列化规范化 scope，并强制 `ai_host_id=targets[0]`；`to_view` 仅对类型 `6` 把 extra 解码为对象。

- [ ] **步骤 5：运行视图与原监控回归并提交**

运行：`cd spug_api && python manage.py test apps.monitor.tests -v 2`
预期：PASS。

提交：

```bash
git add spug_api/apps/monitor/models.py spug_api/apps/monitor/views.py spug_api/apps/monitor/tests.py
git commit -m "feat: 支持保存Docker服务监控目标"
```

### 任务 4：AI Docker 作用域和专用工具

**文件：**
- 修改：`spug_api/apps/ai/models.py`
- 创建：`spug_api/apps/ai/migrations/0007_agentsession_target_scope.py`
- 修改：`spug_api/apps/ai/engine.py`
- 修改：`spug_api/apps/ai/agent.py`
- 修改：`spug_api/apps/ai/tests.py`

- [ ] **步骤 1：编写工具隔离失败测试**

覆盖 Docker 作用域会话构建出的工具名不含 `ssh_exec`，包含 `docker_target_status`、`docker_target_logs`、`docker_target_restart`、`docker_target_recover` 和固定枚举 `host_diagnostics`；普通会话仍保留现有工具集合。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd spug_api && python manage.py test apps.ai.tests -v 2`
预期：FAIL，`target_scope` 和专用工具尚不存在。

- [ ] **步骤 3：增加会话作用域持久化**

模型新增：

```python
target_scope = models.TextField(null=True)
```

迁移只增加可空字段，`to_view` 不返回原始作用域中的敏感 inspect 内容。

- [ ] **步骤 4：实现目标限定工具**

工具不接收目标标识，只从 `ctx.deps.session.target_scope` 读取。每次操作实时校验容器标签或 Compose 项目，日志结果截到 20 KiB。`docker_target_restart` 仅逐个重启异常容器；`docker_target_recover` 先比对基准哈希，再执行受限恢复命令。

- [ ] **步骤 5：修改智能体组装和复检触发**

`build_agent` 根据 `target_scope` 选择工具：Docker 会话不注册 SSH、Skill 或任意 MCP 工具，只注册专用工具。工具写操作返回统一标记，使 `_drive` 在写操作后调用严格 verifier；只读工具不触发复检。

- [ ] **步骤 6：更新 Docker 提示词**

提示词说明只能调用目标工具；配置漂移、独立容器缺失、基础设施错误、熔断或工具拒绝时直接总结并转人工，不能尝试绕过。

- [ ] **步骤 7：运行 AI 测试与迁移检查并提交**

运行：

```bash
cd spug_api
python manage.py test apps.ai.tests -v 2
python manage.py makemigrations --check --dry-run
```

预期：测试 PASS，迁移检查显示无未生成变更。

提交：

```bash
git add spug_api/apps/ai
git commit -m "feat: 限定Docker智能体修复作用域"
```

### 任务 5：告警分流、互斥、冷却和熔断

**文件：**
- 修改：`spug_api/apps/monitor/utils.py`
- 修改：`spug_api/apps/monitor/executors.py`
- 修改：`spug_api/apps/monitor/tests.py`

- [ ] **步骤 1：编写策略失败测试**

使用 mock Redis 覆盖：`infrastructure` 不创建 AI 会话；运行中会话不重复创建；写操作后 30 分钟冷却；滚动 6 小时最多 3 次；10 分钟 restart_count 增加 3 次或连续两次 restarting 时熔断；停用再启用清除策略键。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd spug_api && python manage.py test apps.monitor.tests.DockerRepairPolicyTests -v 2`
预期：FAIL，策略函数尚不存在。

- [ ] **步骤 3：实现策略模块边界**

在 `apps.monitor.docker` 增加纯策略键和 Redis 操作函数：

```python
def repair_target_key(host_id, scope): ...
def may_start_repair(redis, key, details, now): ...
def record_repair_started(redis, key, now): ...
def record_repair_write(redis, key, now): ...
def clear_repair_policy(redis, key): ...
```

所有键设置 TTL；拒绝结果包含具体原因和解除时间。

- [ ] **步骤 4：接入告警链路**

worker 把 `failure_kind/details` 传给 `handle_ai_post_task`。基础设施错误只告警；Docker 修复创建 `AgentSession.target_scope` 并传严格 verifier；已有 running 会话、冷却或熔断时记录跳过原因。

- [ ] **步骤 5：运行监控与 AI 集成测试并提交**

运行：`cd spug_api && python manage.py test apps.monitor.tests apps.ai.tests -v 2`
预期：PASS。

提交：

```bash
git add spug_api/apps/monitor spug_api/apps/ai
git commit -m "feat: 增加Docker自动修复冷却与熔断"
```

### 任务 6：监控表单 Docker 目标选择

**文件：**
- 创建：`spug_web/src/pages/monitor/DockerTarget.js`
- 修改：`spug_web/src/pages/monitor/Step1.js`
- 修改：`spug_web/src/pages/monitor/Step2.js`
- 修改：`spug_web/src/pages/monitor/store.js`

- [ ] **步骤 1：实现 DockerTarget 组件**

组件使用 Ant Design `Select`：先选择单台已验证主机，再调用 `/api/docker/discover/` 实时获取 `projects` 和 `standalone`。Compose 选项值保存项目、工作目录、配置文件和服务，独立容器保存名称；加载、空状态、请求失败和已失效编辑目标都有明确状态。

- [ ] **步骤 2：接入 Step1**

增加选项：

```jsx
<Select.Option value="6">{t('Docker服务检测')}</Select.Option>
```

类型 `6` 显示 `DockerTarget`，切换类型或主机时清空旧 scope。`canNext` 只在主机和目标都有效时放行；执行测试提交标准 `{type, targets, extra}`。

- [ ] **步骤 3：固定 Step2 的 AI 主机**

Docker 类型启用 AI 时，把 `ai_host_id` 设置为 `targets[0]`，用只读文本显示目标主机，不允许选择其他主机；其他监控类型保持原主机选择器。

- [ ] **步骤 4：执行前端构建验证并提交**

运行：`cd spug_web && npm run build`
预期：构建成功，无 ESLint 或编译错误。

提交：

```bash
git add spug_web/src/pages/monitor
git commit -m "feat: 增加Docker服务监控配置界面"
```

### 任务 7：完整回归与文档收尾

**文件：**
- 修改：`docs/superpowers/specs/2026-09-08-docker-service-monitor-ai-repair-design.md`（仅在实现与规格存在已验证差异时）
- 修改：`docs/superpowers/plans/2026-09-08-docker-service-monitor-ai-repair.md`（勾选执行状态）

- [ ] **步骤 1：运行后端完整测试**

运行：`cd spug_api && python manage.py test apps.docker.tests apps.monitor.tests apps.ai.tests -v 2`
预期：全部 PASS。

- [ ] **步骤 2：运行 Django 系统与迁移检查**

运行：

```bash
cd spug_api
python manage.py check
python manage.py makemigrations --check --dry-run
```

预期：系统检查无错误，无遗漏迁移。

- [ ] **步骤 3：运行前端生产构建**

运行：`cd spug_web && npm run build`
预期：构建成功。

- [ ] **步骤 4：检查变更范围和安全关键字**

运行：

```bash
git diff --check
git status --short
grep -RInE "docker compose.*up" spug_api/apps/monitor spug_api/apps/ai
```

预期：无空白错误；监控/AI 中所有 Compose 恢复命令都包含明确服务、`--no-deps`、`--no-recreate`、`--pull never` 和副本基线。

- [ ] **步骤 5：最终提交**

```bash
git add docs/superpowers/plans/2026-09-08-docker-service-monitor-ai-repair.md
git commit -m "docs: 完成Docker服务监控实现计划"
```
