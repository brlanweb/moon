# 数据库目录滚动修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 `/db` 左侧数据库对象树在内容超过视口时独立滚动，并保持 Logo、连接标题和搜索框固定。

**架构：** 保留现有 React 和 Ant Design Tree 结构，仅收紧页面 Flex 高度约束。通过编译真实 Less 并解析生成 CSS 的 Jest 测试锁定滚动容器契约，再进行浏览器尺寸与滚动验证。

**技术栈：** React 16、Ant Design 4、Less 3、Jest、PostCSS

---

## 文件结构

- 创建：`spug_web/src/pages/database/index.test.js`，验证数据库工作台真实编译 CSS 的视口和滚动约束。
- 修改：`spug_web/src/pages/database/index.module.less`，约束页面与侧栏高度，让对象树成为独立滚动区域。

### 任务 1：修复数据库对象树滚动

**文件：**
- 创建：`spug_web/src/pages/database/index.test.js`
- 修改：`spug_web/src/pages/database/index.module.less:1-30`

- [ ] **步骤 1：编写失败的样式回归测试**

编译 `index.module.less`，使用 PostCSS 读取真实声明，并断言：

```javascript
expect(declarations('.container').height).toBe('100vh');
expect(declarations('.container').overflow).toBe('hidden');
expect(declarations('.sider').height).toBe('100%');
expect(declarations('.sider')['min-height']).toBe('0');
expect(declarations('.tree').flex).toBe('1');
expect(declarations('.tree')['min-height']).toBe('0');
expect(declarations('.tree').overflow).toBe('auto');
```

- [ ] **步骤 2：运行测试并确认失败原因**

运行：

```bash
cd spug_web
CI=true npm test -- --runInBand src/pages/database/index.test.js
```

预期：测试因 `.container` 缺少 `height: 100vh` 和 `overflow: hidden` 而失败。

- [ ] **步骤 3：实施最小 CSS 修复**

将外层和侧栏调整为：

```less
.container {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sider {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
```

保留 `.tree` 现有的 `flex: 1`、`min-height: 0` 和 `overflow: auto`。

- [ ] **步骤 4：运行测试与生产构建**

运行：

```bash
cd spug_web
CI=true npm test -- --runInBand src/pages/database/index.test.js
npm run build
```

预期：测试和构建均以退出码 0 完成。

- [ ] **步骤 5：浏览器验证**

启动开发服务器，通过浏览器加载 `/db`，构造超过侧栏高度的树节点并确认：

```javascript
const tree = document.querySelector('[class*="tree"]');
tree.scrollTop = tree.scrollHeight;
```

验证 `tree.scrollHeight > tree.clientHeight`，最后一个表节点可见，页面根节点高度不超过视口，固定区域没有随树滚动。

- [ ] **步骤 6：提交修复**

```bash
git add spug_web/src/pages/database/index.module.less \
  spug_web/src/pages/database/index.test.js
git commit -m "fix(数据库终端): 修复表目录无法滚动"
```
