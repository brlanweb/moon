# 原生查询取消实现计划

**目标：** 完成所有数据库的安全原生取消、连接展开/断开和执行目标选择，保留请求级连接、生产一次性确认、只读与 idle 生命周期。

**架构：** Redis 按用户/连接/execution_id 登记单次执行与取消意图。执行端持有独占物理连接，监控取消意图并使用独立控制连接；控制线程结束后才释放工作连接，执行端异常才确认 cancelled。完成记录保留防止重放。前端锁定执行和确认快照，同步目录与 Select。

**技术栈：** Django 4.2、React 16 / Ant Design 4、PyMySQL 1.2、psycopg 3.3.5、clickhouse-connect 0.15.1、redis-py 6.4（本机及容器实测）。

- [x] 后端行为测试先失败：提前取消、重复/并发/跨用户取消、完成后取消及重放；取消状态不得伪报成功。
- [x] 实现共享 Redis 注册表、独立 cancel/status API 与执行端生命周期。MySQL KILL QUERY；PG pid/backend_start 身份校验；CH settings query_id + KILL 返回状态；Redis 固定单连接 CLIENT UNBLOCK，其他 unsupported。
- [x] 目标选择与空目录测试先失败；实现 MySQL/CH database、PG 安全引用 search_path、Redis 当前 DB；生产确认绑定完整目标。
- [x] 前端行为测试先失败；实现 execution_id、停止/正在中断/失败、运行及确认锁、双击展开、显式断开、Select/树同步与代次保护。
- [x] 运行后端和前端数据库套件、构建、迁移检查；已有本地容器 MariaDB SELECT SLEEP/Redis blocking 集成验证，不访问生产数据库。
- [x] 审查并提交相关文件；记录测试证据、限制和部署步骤到 .superpowers/native-query-cancel-report.md；不部署、不重启。
