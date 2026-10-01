import fs from 'fs';
import path from 'path';
import vm from 'vm';
import {execFileSync} from 'child_process';
import postcss from 'postcss';

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(__dirname, 'index.less'), 'utf8');
const sandbox = {
  module: {exports: {}},
  require: () => ({
    override: (...options) => options[1],
    addDecoratorsLegacy: () => null,
    addLessLoader: options => options,
  }),
};
vm.runInNewContext(fs.readFileSync(path.join(root, 'config-overrides.js'), 'utf8'), sandbox);
const vars = sandbox.module.exports.lessOptions.modifyVars;
let css;

beforeAll(() => {
  // Use Node resolution, as the legacy Jest resolver selects browser-only Less dependencies.
  const compiled = execFileSync(process.execPath, ['-e', `
    const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
    require('less').render(input.source, input.options).then(
      result => process.stdout.write(result.css),
      error => { console.error(error); process.exit(1); }
    );
  `], {
    cwd: root,
    encoding: 'utf8',
    timeout: 60000,
    maxBuffer: 8 * 1024 * 1024,
    input: JSON.stringify({
      source: source.replace('~antd/', 'antd/'),
      options: {
        filename: path.join(__dirname, 'index.less'),
        paths: [path.join(root, 'node_modules')],
        javascriptEnabled: true,
        modifyVars: vars,
      },
    }),
  });
  css = postcss.parse(compiled);
}, 60000);

function declarations(selector) {
  const result = {};
  css.walkRules(rule => {
    if (rule.selectors.includes(selector)) {
      rule.walkDecls(decl => { result[decl.prop] = decl.value; });
    }
  });
  return result;
}

function luminance(hex) {
  const rgb = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

test('uses neutral surfaces, a teal primary and distinct semantic status colors', () => {
  expect(vars['@layout-sider-background']).toBe('#272b30');
  expect(vars['@layout-body-background']).toBe('#f3f4f5');
  expect(vars['@primary-color']).toBe('#28786f');
  expect(new Set(['primary', 'success', 'warning', 'error', 'info'].map(name => vars[`@${name}-color`])).size).toBe(5);
  expect(contrast(vars['@menu-dark-selected-item-text-color'], vars['@menu-dark-item-active-bg'])).toBeGreaterThanOrEqual(4.5);
});

test.each(['@primary-color', '@primary-5', '@primary-7', '@error-color'])('%s is legible against white', token => {
  expect(contrast(vars[token], '#ffffff')).toBeGreaterThanOrEqual(4.5);
});

test('does not introduce gradient backgrounds or geometry animations on buttons', () => {
  expect(source).not.toMatch(/linear-gradient|transform\s*:/);
  expect(declarations('.ant-btn').transition).not.toMatch(/transform|\ball\b/);
  expect(declarations('.ant-btn-primary')['box-shadow']).toBe('none');
});

test.each(['.ant-btn-primary', '.ant-btn-dangerous.ant-btn-primary', '.ant-btn-link'])('%s preserves Antd disabled states', selector => {
  const disabled = declarations(`${selector}[disabled]`);
  expect(disabled.color).toBe(vars['@disabled-color']);
  expect(declarations(`${selector}[disabled]:hover`).color).toBe(disabled.color);
  expect(declarations(`${selector}[disabled]:active`).color).toBe(disabled.color);
});

test('solid-button hover overrides exclude disabled and ghost buttons and keep danger red', () => {
  const selector = '.ant-layout .ant-btn-primary:not([disabled]):not(.ant-btn-background-ghost)';
  expect(declarations(`${selector}:hover`).background).toBe(vars['@primary-5']);
  expect(declarations(`${selector}:active`).background).toBe(vars['@primary-7']);
  const danger = declarations(`${selector}.ant-btn-dangerous:hover`).background;
  expect(danger).toBe('#b94040');
  expect(contrast(danger, '#ffffff')).toBeGreaterThanOrEqual(4.5);
  expect(declarations('.ant-btn:focus-visible')['outline-offset']).toBe('2px');
});

test('sidebar sizing follows viewport changes without changing navigation handlers', () => {
  const sider = fs.readFileSync(path.join(__dirname, 'layout/Sider.js'), 'utf8');
  expect(sider).not.toContain('document.body.clientHeight');
  expect(sider).toContain('className={styles.menuScroll}');
  expect(sider).toContain('onSelect={menu => history.push(menu.key)}');
  expect(sider).toContain('if (item.auth && !hasPermission(item.auth)) return');
});
