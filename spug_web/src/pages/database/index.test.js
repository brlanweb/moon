const path = require('path');
const {execFileSync} = require('child_process');
const postcss = require('postcss');

function compileLess(lessPath) {
  const script = [
    "const fs = require('fs');",
    "const less = require('less');",
    "const file = process.argv[1];",
    "less.render(fs.readFileSync(file, 'utf8'), {filename: file})",
    "  .then(result => process.stdout.write(result.css))",
    "  .catch(error => { console.error(error); process.exit(1); });",
  ].join(' ');

  return execFileSync(process.execPath, ['-e', script, lessPath], {
    cwd: path.resolve(__dirname, '../../..'),
    encoding: 'utf8',
  });
}

async function getDeclarations(selector) {
  const lessPath = path.join(__dirname, 'index.module.less');
  const css = compileLess(lessPath);
  const declarations = {};

  postcss.parse(css).walkRules(rule => {
    if (rule.selector === selector) {
      rule.walkDecls(declaration => {
        declarations[declaration.prop] = declaration.value;
      });
    }
  });

  return declarations;
}

describe('database object tree layout', () => {
  test('constrains the sidebar and lets only the tree scroll', async () => {
    await expect(getDeclarations('.container')).resolves.toMatchObject({
      height: '100vh',
      overflow: 'hidden',
    });
    await expect(getDeclarations('.sider')).resolves.toMatchObject({
      height: '100%',
      'min-height': '0',
      overflow: 'hidden',
    });
    await expect(getDeclarations('.tree')).resolves.toMatchObject({
      flex: '1',
      'min-height': '0',
      overflow: 'auto',
    });
    await expect(getDeclarations('.tree :global(.ant-spin-container)')).resolves.toMatchObject({
      'min-height': '100%',
    });
  });
});
