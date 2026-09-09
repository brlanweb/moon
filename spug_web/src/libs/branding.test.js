const copy = [
  ['Moon API版本', 'Moon API Version'],
  ['Moon Web版本', 'Moon Web Version'],
  ['上游项目', 'Upstream Project'],
  ['上游更新日志', 'Upstream Changelog'],
  ['发现上游新版本 {}', 'New upstream version {} available'],
  ['上游升级说明', 'Upstream upgrade guide'],
  ['上游版本已是最新', 'Upstream version is up to date'],
  ['请输入本地（部署Moon的容器或主机）路径', 'Enter a local path on the host or container running Moon'],
  ['该容器不由 Compose 管理，Moon 没有它的启动参数，删除后无法在此页面重建。', 'This container is not managed by Compose. Moon does not have its startup parameters and cannot recreate it here after deletion.'],
  ['这些容器不由 Docker Compose 管理（docker run 启动，或 Compose 标签残缺）。Moon 没有它们的启动参数，删除后无法在此页面重建。', 'These containers are not managed by Docker Compose (started with docker run or missing Compose labels). Moon does not have their startup parameters and cannot recreate them here after deletion.'],
  ['本机即Moon服务运行所在的容器或主机。', 'Localhost is the container or host where the Moon service runs.'],
  ['Moon使用密钥认证连接服务器，导入或输入的密码仅作首次验证使用，不会存储。', 'Moon connects to servers with SSH key authentication. Imported or entered passwords are only used for first-time verification and are never stored.'],
];

afterEach(() => localStorage.removeItem('spug:language'));

test.each(['zh', 'en'])('non-login branding translates in %s', language => {
  localStorage.setItem('spug:language', language);
  jest.resetModules();
  const {t} = require('./i18n');
  copy.forEach(([zh, en]) => expect(t(zh)).toBe(language === 'en' ? en : zh));
});

test('deployment translation changes the product name but preserves shell variables', () => {
  localStorage.setItem('spug:language', 'en');
  jest.resetModules();
  const {t} = require('./i18n');
  const output = t('应用最终在主机上的部署路径，为了数据安全请确保该目录不存在，Moon 将会自动创建并接管该目录，可使用全局变量，例如：/www/$SPUG_APP_KEY');
  expect(output).toContain('Moon will create and take over this directory');
  expect(output).toContain('/www/$SPUG_APP_KEY');
  expect(t('例如：cn=admin,dc=spug,dc=cc')).toBe('e.g. cn=admin,dc=spug,dc=cc');
});
