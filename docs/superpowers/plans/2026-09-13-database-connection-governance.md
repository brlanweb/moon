# 数据库连接治理与生产安全实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在现有请求级数据库连接架构上实现可配置超时、逻辑断开、空闲自动断开、只读保护、生产数据变更确认和标准连接 URI 导入。

**架构：** 数据库配置仍由 `Connection` 持久化，每次 API 请求独立建立并关闭驱动连接。独立 `policy.py` 负责命令分类与确认令牌，前端连接表单负责 URI 解析和高级字段，工作台负责逻辑连接生命周期。

**技术栈：** Django 4.2、Python 3、sqlparse、React 16、Ant Design 4、Jest。

---

## 文件结构

- 创建 `spug_api/apps/database/policy.py`：SQL/Redis 命令分类、只读策略和生产确认令牌。
- 创建 `spug_api/apps/database/test_policy.py`：安全策略和令牌单元测试。
- 创建 `spug_api/apps/database/test_connections.py`：模型字段、表单校验、驱动参数与 API 行为测试。
- 创建 `spug_api/apps/database/migrations/0002_connection_governance.py`：新增连接治理字段。
- 修改 `spug_api/apps/database/models.py`：连接超时、查询超时、空闲超时、只读和环境字段。
- 修改 `spug_api/apps/database/client.py`：按连接配置向各数据库驱动传递超时。
- 修改 `spug_api/apps/database/views.py`：保存高级配置并执行安全策略和生产确认挑战。
- 修改 `spug_api/requirements.txt`：显式声明 `sqlparse` 依赖。
- 创建 `spug_web/src/pages/database/connectionUri.js`：标准数据库 URI 解析。
- 创建 `spug_web/src/pages/database/connectionUri.test.js`：URI 解析单元测试。
- 创建 `spug_web/src/pages/database/ConnectionForm.test.js`：高级设置交互测试。
- 创建 `spug_web/src/pages/database/DatabaseConsole.test.js`：手动及空闲断开测试。
- 创建 `spug_web/src/pages/database/QueryPanel.test.js`：生产变更确认测试。
- 修改 `spug_web/src/pages/database/ConnectionForm.js`：URI 导入和折叠高级设置。
- 修改 `spug_web/src/pages/database/index.js`：连接状态、手动断开和空闲回收。
- 修改 `spug_web/src/pages/database/QueryPanel.js`：只读/生产标签与确认重试。
- 修改 `spug_web/src/pages/database/index.module.less`：新增紧凑表单、状态标签和确认内容样式。

### 任务 1：连接级超时和环境配置

- [ ] 编写后端失败测试，断言新字段默认值、范围校验及各驱动收到连接级超时。
- [ ] 运行 `./venv/bin/python manage.py test apps.database.test_connections -v 2`，确认因字段缺失失败。
- [ ] 新增模型字段、迁移和表单解析参数，将客户端常量替换为连接字段。
- [ ] 重新运行定向测试，确认通过。
- [ ] 运行 migration 检查，确保没有额外未生成迁移。

### 任务 2：只读策略和生产数据变更确认

- [ ] 编写失败测试，覆盖注释、多语句、CTE、SQL 写操作、Redis 读写命令和签名令牌篡改/过期。
- [ ] 运行 `./venv/bin/python manage.py test apps.database.test_policy -v 2`，确认模块缺失导致失败。
- [ ] 实现 `policy.py`，普通连接放行，只读连接拒绝非只读命令，生产数据变更返回短时签名挑战。
- [ ] 编写 API 失败测试，断言首次请求不执行、有效确认令牌执行、错配令牌拒绝。
- [ ] 修改 `run_command`，返回结构化确认响应并在执行前强制安全策略。
- [ ] 运行两个数据库后端测试模块，确认通过。

### 任务 3：URI 导入和高级连接表单

- [ ] 编写 URI 解析失败测试，覆盖支持协议、URL 编码、IPv6、SSL、默认端口和非法 URI。
- [ ] 运行 `npm test -- --watchAll=false --runInBand src/pages/database/connectionUri.test.js`，确认模块缺失失败。
- [ ] 实现纯函数 URI 解析器。
- [ ] 编写连接表单失败测试，断言导入填充和高级字段随保存请求提交。
- [ ] 修改连接表单，增加 URI 输入弹窗/区域及折叠高级设置。
- [ ] 运行 URI 与表单测试，确认通过。

### 任务 4：手动断开和空闲自动断开

- [ ] 编写工作台失败测试，断言手动断开关闭标签并清缓存，重新点击会重新获取元数据。
- [ ] 编写定时器失败测试，断言超过 `idle_timeout` 自动断开，`0` 永不自动断开。
- [ ] 修改工作台状态模型，集中实现 `disconnectConnection` 和活动时间刷新。
- [ ] 在连接菜单增加断开命令，并对自动断开显示明确提示。
- [ ] 运行工作台测试，确认通过且定时器均被清理。

### 任务 5：生产确认交互与完整验证

- [ ] 编写 QueryPanel 失败测试，断言结构化挑战弹窗确认后携带令牌重试，取消时不重试。
- [ ] 修改 QueryPanel，展示环境/只读标签并处理确认挑战。
- [ ] 运行数据库前端全部测试，确认通过。
- [ ] 运行数据库后端全部测试和迁移检查。
- [ ] 运行前端生产构建与 `git diff --check`。
- [ ] 请求代码审查，修复 Critical/Important 问题后重新验证。
