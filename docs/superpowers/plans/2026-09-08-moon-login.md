# Moon 登录与品牌实现计划

目标：将确认的 A 视觉落实为可用登录页，并将系统自有用户可见品牌统一为 Moon。
架构：复用 React 16/Ant Design 4，新增小型 MoonBrand 组件和本地图形资产。保留认证协议；仅补充表单可访问性、必要校验与提交/计时生命周期。
技术栈：React 16, Ant Design 4, CSS Modules, Less, Jest, ReactDOM test-utils。

## 任务 1：登录页与品牌素材

文件：spug_web/src/pages/login/index.js、login.module.css、index.test.js；components/MoonBrand.js 与 moon-brand.module.css；public/moon-mark.svg、moon-art.svg、favicon.ico、logo.png、manifest.json、index.html。

- [ ] 使用真实 Ant Design 表单渲染登录页，仅替代路由和网络外部依赖。断言 Moon 身份、输入标签、空白必填错误、提交后的成功跳转/会话存储、MFA 保持/重发、错误恢复。先执行 `CI=true npm test -- --watchAll=false --runInBand --runTestsByPath src/pages/login/index.test.js` 观察未实现测试失败。
- [ ] 创建月牙轨道品牌图和深色主视觉，登录页改为响应式结构；显式 label、autocomplete、submit、状态重置和清理计时。接口仍为 `/api/account/login/`，type 仍为 default/ldap。
- [ ] 生成浏览器 PNG/ICO 图标；更新公共 manifest/title/theme。检查两种语言。
- [ ] 重跑相同测试。

## 任务 2：全站品牌

- [ ] 侧边栏使用 MoonBrand，收起只显示图标；全局页脚显示 Moon 并保留上游源代码入口。
- [ ] 独立子任务审计设置/终端/部署/主机/国际化/后端通知；只改品牌文案。保留 `_SPUG_*`、`spug_version`、EOF 等协议、URL 和源码版权。
- [ ] 终端及数据库也使用共享品牌组件；设置上游链接不伪称 Moon 官网。运行对应测试和 Python 编译校验。

## 任务 3：验证

- [ ] `CI=true npm test -- --watchAll=false --runInBand` 和 `npm run build`。
- [ ] 可用端口启动开发服务，使用 Playwright 验证 1440x900、390x844、320x568 与低矮桌面。检查溢出、图片加载、英文、键盘、MFA、LDAP 和错误状态。
- [ ] 独立审查变更，修复问题后重新验证。保留用户原有未提交内容，不提交或部署。
