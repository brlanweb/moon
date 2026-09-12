# Docker 统一管理台实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 删除 Docker 模块的侧边子菜单，将现有项目、容器、镜像、网络和存储卷能力整合为截图风格的单页管理台。

**架构：** `/docker` 作为唯一导航入口，页面顶层持有服务器和当前页签状态。概览聚合现有发现接口与资源接口，容器/Compose 复用当前项目控制台，镜像、网络和卷继续复用 `Resources`，旧 URL 兼容跳转并映射到对应页签。

**技术栈：** React 16、React Router 5、Ant Design 4、Jest、CSS Modules/Less。

---

### 任务 1：统一路由与工作台页签

**文件：**
- 修改：`spug_web/src/routes.js`
- 修改：`spug_web/src/pages/docker/index.js`
- 修改：`spug_web/src/pages/docker/index.test.js`

- [ ] 编写失败测试：断言 `/docker` 是唯一菜单入口，旧路径仍可解析到对应页签，页面展示统一 Docker 头部和六个页签。
- [ ] 运行 `CI=true npm test -- --runInBand src/pages/docker/index.test.js`，确认因统一工作台尚未实现而失败。
- [ ] 实现顶层工作台、共享主机选择和页签切换，保留旧路径兼容。
- [ ] 再次运行前端测试并确认通过。

### 任务 2：概览与容器汇总

**文件：**
- 修改：`spug_web/src/pages/docker/index.js`
- 修改：`spug_web/src/pages/docker/index.module.less`
- 修改：`spug_web/src/pages/docker/index.test.js`

- [ ] 编写失败测试：选择服务器后概览显示运行、停止、容器总数和镜像数；容器页展示 Compose 与独立容器。
- [ ] 运行目标测试并确认缺少概览行为导致失败。
- [ ] 使用 `/api/docker/discover/` 与资源列表接口聚合概览，容器页复用当前可操作表格。
- [ ] 运行目标测试并确认通过。

### 任务 3：样式与全量回归

**文件：**
- 修改：`spug_web/src/pages/docker/index.module.less`
- 修改：`spug_web/src/layout/PageTitle.test.js`

- [ ] 编写或更新失败测试，锁定统一入口的页面标题和旧地址兼容行为。
- [ ] 实现截图风格的紧凑头部、页签、统计卡片及响应式布局。
- [ ] 运行 Docker 页面测试、页面标题测试和前端构建。
- [ ] 使用浏览器在桌面与移动视口检查无重叠、页签可切换、资源表格可滚动。
