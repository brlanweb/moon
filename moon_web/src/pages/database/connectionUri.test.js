import {parseConnectionUri} from './connectionUri';

describe('parseConnectionUri', () => {
  test.each([
    ['mysql://db.example.com/app', 'mysql', 3306],
    ['mariadb://db.example.com/app', 'mariadb', 3306],
    ['postgres://db.example.com/app', 'postgresql', 5432],
    ['postgresql://db.example.com/app', 'postgresql', 5432],
    ['clickhouse://db.example.com/app', 'clickhouse', 8123],
    ['clickhouses://db.example.com/app', 'clickhouse', 8123],
    ['redis://db.example.com/0', 'redis', 6379],
    ['rediss://db.example.com/0', 'redis', 6379],
  ])('parses %s with its normalized type and default port', (uri, type, port) => {
    expect(parseConnectionUri(uri)).toMatchObject({type, port});
  });

  test('decodes credentials and database without changing the IPv6 host', () => {
    expect(parseConnectionUri('postgresql://report%40user:p%2Fa%3Ass@[2001:db8::5]:5544/sales%2Farchive')).toEqual({
      type: 'postgresql',
      host: '2001:db8::5',
      port: 5544,
      username: 'report@user',
      password: 'p/a:ss',
      database: 'sales/archive',
      use_ssl: false,
    });
  });

  test.each([
    'rediss://cache.example.com/0',
    'clickhouses://analytics.example.com/default',
    'mysql://db.example.com/app?ssl=true',
    'mysql://db.example.com/app?ssl=1',
    'postgres://db.example.com/app?ssl=require',
  ])('enables SSL for %s', uri => {
    expect(parseConnectionUri(uri).use_ssl).toBe(true);
  });

  test.each([
    'require',
    'verify-ca',
    'verify-full',
  ])('enables PostgreSQL SSL for sslmode=%s', sslmode => {
    expect(parseConnectionUri(`postgresql://db.example.com/app?sslmode=${sslmode}`).use_ssl).toBe(true);
  });

  test('disables PostgreSQL SSL for sslmode=disable', () => {
    expect(parseConnectionUri('postgresql://db.example.com/app?sslmode=disable').use_ssl).toBe(false);
  });

  test.each(['true', '1'])('enables ClickHouse SSL for secure=%s', secure => {
    expect(parseConnectionUri(`clickhouse://db.example.com/app?secure=${secure}`).use_ssl).toBe(true);
  });

  test('keeps SSL disabled for an unrelated query value', () => {
    expect(parseConnectionUri('mysql://db.example.com/app?ssl=false').use_ssl).toBe(false);
  });

  test.each([
    ['oracle://db.example.com/app', '不支持的数据库协议：oracle'],
    ['db.example.com/app', '连接 URI 缺少协议'],
    ['mysql://db.example.com:70000/app', '连接 URI 端口无效'],
    ['mysql:///app', '连接 URI 缺少主机地址'],
  ])('rejects %s with a displayable error', (uri, error) => {
    expect(() => parseConnectionUri(uri)).toThrow(error);
  });

  test.each([
    'mysql://user%ZZ:password@db.example.com/app',
    'mysql://user:password%2@db.example.com/app',
    'mysql://db.example.com/app%',
    'mysql://db.example.com/app?label=%GG',
  ])('rejects invalid percent escapes in %s', uri => {
    expect(() => parseConnectionUri(uri)).toThrow('连接 URI 编码无效');
  });
});
