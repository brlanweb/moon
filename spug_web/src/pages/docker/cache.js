const CACHE_PREFIX = 'spug:docker:view:v1:';

function key(hostId, scope) {
  return `${CACHE_PREFIX}${hostId}:${scope}`;
}

export function readDockerCache(hostId, scope) {
  if (hostId === undefined || hostId === null) return null;
  try {
    const value = JSON.parse(localStorage.getItem(key(hostId, scope)));
    return value && typeof value === 'object' ? value : null;
  } catch (error) {
    return null;
  }
}

export function clearDockerCache(hostId, ...scopes) {
  if (hostId === undefined || hostId === null) return;
  try {
    for (const scope of scopes) localStorage.removeItem(key(hostId, scope));
  } catch (error) {
    // Cache cleanup failure must not block a completed Docker operation.
  }
}

export function writeDockerCache(hostId, scope, value) {
  if (hostId === undefined || hostId === null) return;
  try {
    localStorage.setItem(key(hostId, scope), JSON.stringify(value));
  } catch (error) {
    // Cache is an optimization; quota failures must not block Docker management.
  }
}
