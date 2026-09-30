// HTTPS credentials retain the existing backend URL format.
export function parseRepoUrl(url = '') {
  if (/^(git@|ssh:\/\/)/.test(url)) return {type: 'key', url};
  try {
    const parsed = new URL(url);
    const username = decodeURIComponent(parsed.username);
    const password = decodeURIComponent(parsed.password);
    parsed.username = '';
    parsed.password = '';
    if (username || password) {
      return username === 'x-access-token'
        ? {type: 'token', url: parsed.href, token: password}
        : {type: 'password', url: parsed.href, username, password};
    }
  } catch (_) { /* Keep incomplete URLs editable. */ }
  return {type: 'token', url};
}

export function buildRepoUrl(data) {
  const url = (data.url || '').trim();
  if (!url) throw new Error('请输入仓库地址');
  if (data.type === 'key') {
    if (!/^(git@[^\s:]+:.+|ssh:\/\/[^\s]+)$/.test(url)) throw new Error('SSH认证请使用git@或ssh://仓库地址');
    return url;
  }
  let parsed;
  try { parsed = new URL(url); } catch (_) { throw new Error('请输入有效的HTTP或HTTPS仓库地址'); }
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('请输入有效的HTTP或HTTPS仓库地址');
  let username = data.username;
  let password = data.password;
  if (data.type === 'token') {
    if (parsed.protocol !== 'https:') throw new Error('Token认证必须使用HTTPS仓库地址');
    username = 'x-access-token';
    password = (data.token || '').trim();
    if (!password) throw new Error('请输入访问令牌');
    if (/\s/.test(password) || password.startsWith('-----BEGIN')) throw new Error('请填写PAT访问令牌，不是SSH公钥或私钥');
  } else {
    if (!username) throw new Error('请输入账户');
    if (!password) throw new Error('请输入密码');
  }
  parsed.username = encodeURIComponent(username);
  parsed.password = encodeURIComponent(password);
  return parsed.href;
}
