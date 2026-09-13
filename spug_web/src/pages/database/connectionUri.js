const DATABASE_TYPES = {
  mysql: {type: 'mysql', port: 3306},
  mariadb: {type: 'mariadb', port: 3306},
  postgres: {type: 'postgresql', port: 5432},
  postgresql: {type: 'postgresql', port: 5432},
  clickhouse: {type: 'clickhouse', port: 8123},
  clickhouses: {type: 'clickhouse', port: 8123, ssl: true},
  redis: {type: 'redis', port: 6379},
  rediss: {type: 'redis', port: 6379, ssl: true},
};

function authorityParts(uri, prefixLength) {
  const authority = uri.slice(prefixLength).split(/[/?#]/, 1)[0];
  const endpoint = authority.slice(authority.lastIndexOf('@') + 1);

  if (endpoint.startsWith('[')) {
    const closingBracket = endpoint.indexOf(']');
    if (closingBracket === -1) return {host: endpoint};
    const suffix = endpoint.slice(closingBracket + 1);
    return {
      host: endpoint.slice(1, closingBracket),
      port: suffix.startsWith(':') ? suffix.slice(1) : undefined,
    };
  }

  const separator = endpoint.lastIndexOf(':');
  if (separator === -1) return {host: endpoint};
  return {host: endpoint.slice(0, separator), port: endpoint.slice(separator + 1)};
}

function decode(value) {
  try {
    return decodeURIComponent(value);
  } catch (error) {
    throw new Error('连接 URI 编码无效');
  }
}

function validatePercentEscapes(uri) {
  if (/%(?![0-9a-f]{2})/i.test(uri)) {
    throw new Error('连接 URI 编码无效');
  }
}

export function parseConnectionUri(value) {
  const uri = String(value || '').trim();
  const schemeMatch = uri.match(/^([a-z][a-z0-9+.-]*):\/\//i);
  if (!schemeMatch) throw new Error('连接 URI 缺少协议');

  const scheme = schemeMatch[1].toLowerCase();
  const config = DATABASE_TYPES[scheme];
  if (!config) throw new Error(`不支持的数据库协议：${scheme}`);
  validatePercentEscapes(uri);

  const endpoint = authorityParts(uri, schemeMatch[0].length);
  if (!endpoint.host) throw new Error('连接 URI 缺少主机地址');
  if (endpoint.port !== undefined && !/^\d+$/.test(endpoint.port)) {
    throw new Error('连接 URI 端口无效');
  }
  const explicitPort = endpoint.port === undefined ? undefined : Number(endpoint.port);
  if (explicitPort !== undefined && (explicitPort < 1 || explicitPort > 65535)) {
    throw new Error('连接 URI 端口无效');
  }

  let parsed;
  try {
    parsed = new URL(uri);
  } catch (error) {
    throw new Error('连接 URI 格式无效');
  }

  const ssl = (parsed.searchParams.get('ssl') || '').toLowerCase();
  const sslmode = (parsed.searchParams.get('sslmode') || '').toLowerCase();
  const secure = (parsed.searchParams.get('secure') || '').toLowerCase();
  let useSsl = Boolean(config.ssl) || ['true', '1', 'require'].includes(ssl);
  if (config.type === 'postgresql') {
    if (sslmode === 'disable') useSsl = false;
    if (['require', 'verify-ca', 'verify-full'].includes(sslmode)) useSsl = true;
  }
  if (config.type === 'clickhouse' && ['true', '1'].includes(secure)) useSsl = true;

  return {
    type: config.type,
    host: parsed.hostname.replace(/^\[|\]$/g, ''),
    port: explicitPort === undefined ? config.port : explicitPort,
    username: decode(parsed.username),
    password: decode(parsed.password),
    database: decode(parsed.pathname.replace(/^\//, '')),
    use_ssl: useSsl,
  };
}
