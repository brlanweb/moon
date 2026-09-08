# Docker 服务监控与 AI 定向修复设计

## 背景

监控中心当前支持站点、端口、进程、自定义脚本和 Ping 检测，并可在达到连续失败阈值后触发 AI 诊断或修复。Docker 管理模块已经能够通过 SSH 发现 Compose 项目、服务和独立容器，也能对明确目标执行启停、重启、日志和 Compose 单服务操作。

本功能把这两条已有链路连接起来：用户在新建监控时直接选择 Docker 主机和服务，系统检查容器运行状态与 Docker Healthcheck；发生故障时由 AI 在严格限定的目标范围内排查和修复，不能影响同一主机上的其他服务。

## 目标

- 在“新建监控”的“监控类型”中增加“Docker 服务检测”。
- 选择已验证主机后，实时选择 Compose 项目中的服务或独立容器。
- 通过运行状态与 Docker Healthcheck 判断服务是否正常。
- Compose 服务任一副本异常即判定本轮检测失败。
- 达到现有连续失败阈值后先告警，再触发 AI 诊断或修复，并在处理后通知结论。
- AI 修复操作必须限定在选中的 Compose 服务或独立容器上。
- 复用现有监控调度、Docker 发现、通知、智能体会话及执行审计能力。

## 非目标

- 首版不部署主机侧 Agent，也不监听 Docker Events，仍采用现有分钟级轮询。
- 不增加容器端口或 HTTP 应用层探测；应用层可用性继续由站点和端口监控负责。
- 不自动修改或静默应用 Compose 配置、环境变量、镜像、网络或数据卷。
- 不允许 `up` 隐式启动 `depends_on` 服务或拉取镜像。
- 不自动删除容器、镜像、网络或数据卷。
- 不自动修复已经被删除的独立容器，因为系统没有可靠的原始启动参数。
- 不允许整个 Compose 项目级的启停、重启、重建或销毁操作。
- Docker 无人值守会话不提供任意 SSH 命令执行能力。

## 用户流程

监控表单仍使用现有两步流程。

第一步：

1. 用户选择“Docker 服务检测”。
2. 用户选择一台已验证且当前用户有权访问的主机。
3. 前端调用 Docker 发现接口获取实时数据，不用长效缓存作为最终选择依据。
4. 用户选择目标类型：Compose 服务或独立容器。
5. Compose 目标按“项目 / 服务”展示；独立容器直接按容器名展示。
6. 用户可执行一次检测测试，返回每个副本的状态和整体判断。

第二步沿用现有监控频率、失败阈值、通知、沉默期、AI 模式和最大轮次配置。启用 AI 时，排查主机自动固定为第一步选择的 Docker 主机，不再允许另选主机，避免检测目标与修复目标不一致。

编辑已有监控时重新获取实时 Docker 列表。已保存目标已经不存在时仍显示原始标识和“目标当前不可用”，用户可以保存其他字段或重新选择目标。

## 目标数据

新增监控类型 `6`，显示名为“Docker 服务检测”。该类型一次只监控一台主机上的一个逻辑服务，不支持在一个监控项中混选多个主机或多个服务。

沿用 `Detection.targets` 保存单个主机 ID，沿用 `Detection.extra` 保存版本化 JSON 文本，避免为仅适用于一种监控类型的字段扩展通用表结构。

Compose 服务目标示例：

```json
{
  "version": 1,
  "kind": "compose_service",
  "project": "orders",
  "workdir": "/opt/orders",
  "config_files": ["/opt/orders/compose.yml"],
  "service": "api",
  "expected_replicas": 3,
  "config_hash": "f6c9a42fd12005ab4fdb2dc66b8fd5d0c6b9bc1066ee3d1c8163702b4bcbe723"
}
```

独立容器目标示例：

```json
{
  "version": 1,
  "kind": "standalone_container",
  "container": "legacy-worker"
}
```

后端保存前必须从该主机的实时 `docker inspect` 结果重新确认目标归属，不能信任前端提交的项目、配置文件、工作目录或容器类型。Compose 目标保存当前副本数作为 `expected_replicas`，只有用户重新保存监控项才更新该基线。后端还要通过 `docker compose config --hash <service>` 计算当前服务配置哈希，确认它与所有现存副本的 `com.docker.compose.config-hash` 标签一致后，把该值保存为基准哈希。基准哈希只在用户重新保存监控项时更新，正常轮询和 AI 不得自动接受配置漂移。若当前 Compose 版本不支持 `config --hash`，仍可监控和定向重启，但禁用自动 `up`，副本缺失时转人工。读取旧记录或非法 JSON 时返回可理解的配置错误，不能让监控工作线程异常退出。

## Docker 发现扩展

现有 `parse_inspect` 返回的容器信息增加以下只读字段：

- `health`：`healthy`、`unhealthy`、`starting` 或空字符串。
- `started_at`：Docker State 中的启动时间，用于判断启动宽限期。
- `restart_count`：辅助识别短时间内的重启循环。
- `config_hash`：容器的 `com.docker.compose.config-hash` 标签。
- `health_start_period_ns`、`health_interval_ns` 和 `health_retries`：来自
  `Config.Healthcheck`，用于计算检测宽限期和修复验证截止时间。

现有 Docker 管理页面可以忽略新增字段，不改变其行为。监控表单复用现有发现接口，但后端监控执行器直接调用 Docker 客户端模块，避免通过 HTTP 回调自身。

## 状态判定

### Compose 服务

每轮从实时发现结果中按项目名、配置文件集合和服务名解析当前全部副本。

- 当前副本数低于保存的 `expected_replicas`：失败，原因是服务副本缺失；高于基线时不自动缩容，但提示用户重新保存监控项以更新基线。
- 任一副本状态为 `exited` 或 `dead`：失败。
- 任一副本状态为 `restarting`：失败。
- 任一运行中副本 Healthcheck 为 `unhealthy`：失败。
- Healthcheck 为 `starting` 且尚在启动宽限期：常规检测本轮正常。
- Healthcheck 为 `starting` 且超过启动宽限期：失败。
- 状态为 `running` 且 Healthcheck 为 `healthy`：正常。
- 状态为 `running` 且镜像未配置 Healthcheck：正常。
- 出现未识别状态时按失败处理，并在信息中保留原始状态。

Compose 服务采用“任一副本异常即失败”，检测结果列出异常副本及各自状态。每个副本的常规检测启动宽限期取 `max(120 秒, Config.Healthcheck.StartPeriod)`；没有 Healthcheck 时使用 120 秒。Docker inspect 中时长以纳秒表示，后端统一转换为秒并对负值或异常值回退到 120 秒，首版不增加新的用户配置项。

### 独立容器

按保存的容器名解析目标，状态与 Healthcheck 判定规则和单个 Compose 副本一致。容器不存在时判定失败，并标记为不可自动重建。

### 基础设施错误

SSH 连接失败、Docker 命令不可用、权限不足或 inspect 输出无法解析时，本轮检测失败并保留具体错误，但错误分类为 `infrastructure`。基础设施错误照常参与告警计数和通知，不创建 AI 会话，因为智能体使用同一条 SSH/Docker 链路，继续调用只会重复失败。恢复正常连接后的下一次检测沿用现有恢复通知逻辑。

容器不存在、容器状态异常或 Healthcheck 异常分类为 `target`，只有该类别达到阈值时才允许触发 AI。

## 调度、告警与恢复

现有 Scheduler 继续按监控频率把任务写入监控工作队列。内部 `dispatch` 统一返回 `DetectionResult(is_ok, message, failure_kind, details)`；现有五种检测通过适配器保持原行为，Docker 检测使用 `failure_kind` 区分 `target` 与 `infrastructure`，并在 `details` 保存副本状态。HTTP 测试接口仍只暴露兼容的成功状态与消息。Redis 中的连续失败计数、报警阈值和沉默期保持不变。

达到阈值后的顺序保持不变：

1. 立即发送原始故障告警并记录报警事件。
2. 仅当错误类别为 `target` 且未触发冷却或熔断时，创建来源为 monitor 的智能体会话。
3. AI 排查或修复目标。
4. 修复模式每次写操作后进入严格恢复验证，不复用常规检测对 `starting` 的宽限判定。
5. 严格验证通过后发送恢复通知并清除故障计数；否则发送未修复结论。

触发消息包含结构化目标摘要、异常副本、运行状态、健康状态和检测错误，使 AI 第一轮直接查看目标日志和退出原因，不扫描无关服务。

### 修复后严格验证

常规轮询为了避免慢启动误报，可以在启动宽限期内把 `starting` 视为正常；修复后的验证不能使用这个规则。每次写操作后按 10 秒间隔轮询目标：

- 配置 Healthcheck 时，全部副本必须连续 2 次为 `running + healthy`。
- 未配置 Healthcheck 时，全部副本必须连续 2 次为 `running`。
- `starting` 只表示继续等待，不能判定恢复。
- 验证截止时间为 `启动宽限期 + max(60 秒, Healthcheck.Interval × Healthcheck.Retries)`；没有 Healthcheck 时为 120 秒。
- 计算结果超过 30 分钟时不启动自动修复，直接转人工，避免长期占用监控工作线程。
- 截止前未满足连续稳定条件，或任一副本再次退出、dead、restarting、unhealthy，均判定本次修复未恢复。

只有严格验证通过才能发送恢复通知。验证期间由现有会话互斥锁阻止并发修复，常规监控任务可以记录状态但不重复创建会话。

## AI 执行边界

### 会话作用域

监控触发的 Docker 智能体会话保存不可变的 Docker 作用域快照，至少包括主机 ID、目标类型、项目、配置文件集合、工作目录、服务名或独立容器名。`AgentSession` 新增可空的 `target_scope` 文本字段保存版本化 JSON；非 Docker 会话保持为空。完整作用域写入会话记录，供执行校验和审计使用。

### 专用工具

Docker 自动修复不依赖模型拼接任意写命令。智能体获得以下后端工具：

- 获取目标当前状态与 inspect 摘要。
- 获取目标最近 200 行日志，工具输出最多 20 KiB，超出部分截断并明确标记。
- 重启目标。
- 对 Compose 目标执行受限的单服务恢复。
- 对独立容器执行 `start` 或 `restart`。

每次工具调用都从会话作用域读取目标，不接受模型传入主机 ID、项目名、服务名、配置路径或容器名。执行前重新实时发现目标，确认项目和配置没有变化，并复用 Docker 模块现有的名称校验、项目校验、同名项目冲突检查和操作锁。

Compose 单服务恢复仅用于目标服务副本数低于保存基线的情况。工具先执行 `docker compose config --hash <service>`，结果必须等于监控创建时保存的基准哈希；任一现存副本的 config-hash 与基准不一致也立即转人工。通过后只能生成：

```text
docker compose -p <project> -f <file...> up -d --no-deps --no-recreate --pull never --scale <service>=<expected_replicas> <service>
```

`--no-deps` 防止启动 `depends_on` 服务，`--no-recreate` 防止改动现存副本，`--pull never` 防止隐式拉取镜像，`--scale` 只把目标服务恢复到人工保存的副本基线。当前配置哈希无法计算或与基准不一致时，不执行 `up`，避免把尚未发布的配置漂移静默应用到生产环境。

### 无任意 SSH 命令

Docker 监控触发的无人值守会话不注册通用 `ssh_exec` 工具，避免 `sh -c`、脚本解释器、编码载荷、heredoc 或 Docker Socket 等方式绕过字符串黑名单。容器状态、日志和写操作全部经过目标限定专用工具。

如排查确实需要宿主机信息，只提供参数为固定枚举的只读诊断工具，例如磁盘空间、inode、内存和系统负载。命令模板由后端生成，不接收模型提供的 shell、路径、管道、重定向或附加参数。首版不要求用户创建新的受限 SSH 账号；现有高权限凭据只能由这些后端工具内部使用。

现有高危与跨服务命令规则继续保护其他智能体会话，但不作为 Docker 无人值守修复的主要隔离机制。提示词仅用于引导排查，不能替代工具权限和执行前校验。

### 允许和禁止的写操作

Compose 服务只允许：

- 对目标服务中状态异常的现存副本逐个执行 `docker restart -- <container>`；工具执行前按容器标签重新确认它仍属于目标项目和服务，不重启同服务内的健康副本。
- 目标服务副本数低于保存基线且配置哈希校验通过时，执行带 `--no-deps --no-recreate --pull never --scale <service>=<expected_replicas>` 的定向 `up -d <service>`。

独立容器只允许：

- 目标仍存在时执行 `start` 或 `restart`。

明确禁止：

- 不带服务名的 Compose `up`、`restart`、`start` 或 `stop`。
- `down`、`rm`、`--remove-orphans`、`-v`、`--volumes`。
- `--build`、`--force-recreate`、`pull` 及镜像构建或更新。
- 修改 Compose 文件、环境文件或目标服务配置。
- 操作其他服务、独立容器、网络、镜像和数据卷。
- 主机重启、Docker daemon 重启或其他整机级操作。

如果必须越过这些边界才能恢复，AI 立即停止自动修复并通知人工。

## 修复策略

AI 先读取状态、退出信息和目标日志，再决定是否执行写操作。推荐顺序为：

1. 确认异常发生在目标服务或目标独立容器。
2. 查看目标日志、State Error、OOMKilled、ExitCode 和健康检查输出。
3. Compose 目标存在异常容器时只逐个重启异常副本，不影响同服务的健康副本；目标副本数低于保存基线时，配置哈希校验通过后才允许执行受限的定向 `up -d --scale`。
4. 独立容器存在时执行 start 或 restart；已删除则停止并通知人工。
5. 每次写操作后进入严格恢复验证；连续稳定后结束，不继续操作。

### 冷却、限流与重启循环

除会话互斥外，系统在 Redis 中按“主机 + 目标类型 + 项目/服务或容器名”记录修复状态：

- 任一次自动写操作后进入 30 分钟冷却期；冷却期内继续检测和告警，但不创建新的 AI 修复会话。
- 同一目标在滚动 6 小时内最多启动 3 次自动修复会话；超过后熔断并转人工，计数窗口到期后自动解除。
- 每次检测保存 `restart_count` 样本；10 分钟内增加 3 次及以上，或连续 2 个检测样本处于 `restarting`，判定为重启循环，直接熔断，不再通过重启尝试修复。
- 人工停用再启用监控时清除该目标的冷却和熔断状态，作为显式人工复位。

相同监控目标的 AI 修复会话必须互斥。已有会话仍在运行时，新一轮检测只保留告警状态，不再启动第二个并发修复会话。

## 权限与接口

- 新建或编辑 Docker 服务监控继续要求监控新增或编辑权限。
- Docker 目标发现同时要求当前用户拥有目标主机访问权限和 Docker 查看权限。
- 保存时由后端再次校验主机权限及目标归属。
- 后台监控和 AI 修复使用监控记录中已经验证的目标，不继承创建者后来可能失效的浏览器会话；管理员停用监控即可立即停止后续自动修复。
- 不向前端返回 SSH 凭据或 Docker 原始 inspect 全量内容。

## 错误处理

- 目标在保存前变化：拒绝保存并提示刷新 Docker 服务列表。
- 目标在运行期变化：本轮失败，AI 只允许在重新确认作用域后操作。
- Compose 配置路径变化、配置哈希漂移、无法计算哈希或同名项目冲突：禁止 `up` 并通知人工；现存容器仍可执行不应用配置变化的定向 restart。
- 独立容器已经删除：禁止重建并通知人工。
- 目标日志或状态读取失败：记录工具错误，不继续执行写操作。
- SSH、Docker 命令、权限或 inspect 解析等基础设施错误：告警但不创建 AI 会话。
- 命中冷却、次数上限或重启循环熔断：跳过 AI 修复并在告警中说明原因和解除条件。
- 达到最大轮次仍未恢复：会话标记为未解决并发送结论通知。
- AI 模型、SSH 或 Docker 调用异常：会话标记为执行异常，不吞掉原始告警。

## 兼容与迁移

- `Detection.type` 的长度足以容纳新值，仅需新增 choices，无需修改字段结构。
- `extra` 的 JSON 仅在类型 `6` 下解析，其他五种监控类型保持原有字符串语义。
- Scheduler 和队列消息结构不变，仍传递 `type`、`targets` 和 `extra`。
- Docker 发现响应只增加字段，不删除或改名，现有 Docker 管理页面保持兼容。
- 新增一次数据库迁移，为 `AgentSession.target_scope` 增加可空文本字段；现有会话无需回填。
- 现有监控记录无需数据迁移。

## 测试

后端单元测试覆盖：

- inspect 解析健康状态、Healthcheck 时序、启动时间、重启次数和配置哈希。
- Compose 无副本、任一副本退出、反复重启、unhealthy、动态 starting 宽限期及全部健康的判断。
- 未配置 Healthcheck 的运行容器判定正常。
- 独立容器正常、异常和已删除的判断。
- Docker/SSH/JSON 基础设施错误转换为检测失败和告警，且不创建 AI 会话。
- 保存接口拒绝伪造的项目、配置路径、服务名、独立容器和无权限主机。
- AI 会话作用域生成正确，修复后执行严格验证，`starting` 不会误报恢复，并要求连续 2 次稳定。
- 专用工具只操作作用域中的目标，并拒绝变化、冲突和越界目标。
- Compose 恢复命令固定包含 `--no-deps --no-recreate --pull never`、保存的副本基线和明确服务名。
- 配置哈希一致时允许受限 `up`，配置漂移、哈希不可用或副本哈希不一致时拒绝。
- Docker 自动修复会话不注册通用 `ssh_exec`，固定枚举诊断工具不接受 shell 参数。
- 日志工具固定读取 200 行并在 20 KiB 截断。
- 同一监控目标不会并发启动两个自动修复会话。
- 30 分钟冷却、6 小时 3 次上限和 10 分钟 restart_count 增长熔断生效。

前端测试或可复现检查覆盖：

- 选择主机后加载 Compose 服务和独立容器。
- 切换监控类型或主机时清空旧目标。
- 编辑时回显有效目标，并提示已经失效的目标。
- Docker 监控启用 AI 时排查主机固定为目标主机。
- 未完成主机和服务选择时不能进入下一步或执行测试。

回归验证覆盖现有五种监控类型、Docker 管理页面发现与操作、AI 诊断/修复以及告警和恢复通知，确保新增分支不改变原有行为。

## 验收标准

- 用户能从监控中心创建 Compose 服务或独立容器监控。
- Compose 任一副本异常及容器 unhealthy 能按连续失败阈值触发告警。
- AI 能读取目标状态和日志，并在允许范围内恢复目标。
- Compose 服务副本缺失时，仅在配置哈希未漂移的前提下，通过带 `--no-deps --no-recreate --pull never` 和保存副本基线的定向 `up -d --scale <service>=<expected_replicas> <service>` 恢复。
- 修复后必须通过严格连续稳定验证，不能把启动宽限期内的 `starting` 当成恢复。
- 冷却、次数上限和重启循环熔断能够阻止反复自动重启和重复 AI 消耗。
- 基础设施错误只告警，不创建必然失败的 AI 会话。
- 独立容器被删除时不尝试重建，而是给出明确人工处理结论。
- 测试能够证明 AI 没有任意 SSH 执行入口，且无法操作同主机上的其他服务或执行项目级、整机级破坏操作。
- 日志输入固定限量，所有 AI 工具调用、命令、结果和最终结论可在智能体会话中审计。

## 参考资料

- Docker Compose `up` 参数：<https://docs.docker.com/reference/cli/docker/compose/up/>
- Compose `depends_on` 与 Healthcheck：<https://docs.docker.com/reference/compose-file/services/#depends_on>
- Docker Compose `config --hash` 实现：<https://github.com/docker/compose/blob/main/cmd/compose/config.go>
- Docker 容器日志参数：<https://docs.docker.com/reference/cli/docker/container/logs/>
