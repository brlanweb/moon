"""Cross-process execution intent. Only the owning executor can publish a terminal state.

IDs contain their creation time: records outlive the acceptance window, so expiration
cannot turn a replay/late cancel into a new execution. No connection credentials live here.
"""
import json
import time
from uuid import UUID

from django_redis import get_redis_connection


class ExecutionError(Exception):
    pass


_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
local r = raw and cjson.decode(raw) or {status='pending', cancel_requested=false}
local op = ARGV[1]
if op == 'begin' then
    if r.status ~= 'pending' then return 'duplicate' end
    if r.cancel_requested then
        r.status = 'cancelled'
    else
        if redis.call('EXISTS', KEYS[2]) == 1 then return 'busy' end
        redis.call('SET', KEYS[2], KEYS[1], 'EX', 7200)
        r.status = 'running'
    end
elseif op == 'cancel' then
    if r.status == 'pending' or r.status == 'running' or r.status == 'cancelling' then
        r.cancel_requested = true
        r.cancel_attempt = (r.cancel_attempt or 0) + 1
        if r.status ~= 'pending' then r.status = 'cancelling' end
    end
elseif op == 'update' then
    if r.status == 'running' or r.status == 'cancelling' then
        local update = cjson.decode(ARGV[2])
        for k,v in pairs(update) do r[k] = v end
    end
elseif op == 'finish' then
    if r.status == 'running' or r.status == 'cancelling' then
        r.status = ARGV[2]
        if redis.call('GET', KEYS[2]) == KEYS[1] then redis.call('DEL', KEYS[2]) end
    end
elseif op == 'status' or op == 'heartbeat' then
    if not raw then return '{}' end
    if op == 'heartbeat' then
        redis.call('EXPIRE', KEYS[1], 7200)
        if redis.call('GET', KEYS[2]) == KEYS[1] then redis.call('EXPIRE', KEYS[2], 7200) end
    end
    return raw
end
redis.call('SET', KEYS[1], cjson.encode(r), 'EX', 7200)
return cjson.encode(r)
"""


class Registry:
    def __init__(self, user_id, connection_id, execution_id):
        try:
            stamp, nonce = execution_id.split('.')
            UUID(nonce)
            age = time.time() - int(stamp) / 1000
            if not -60 <= age <= 7200:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            raise ExecutionError('execution_id 无效或已过期') from None
        self.created_at = int(stamp) / 1000
        self.execution_id = execution_id
        self.key = f'moon:database:execution:{user_id}:{connection_id}:{execution_id}'
        self.active_key = f'moon:database:active:{user_id}:{connection_id}'

    def _call(self, operation, value=''):
        try:
            raw = get_redis_connection().eval(_SCRIPT, 2, self.key, self.active_key, operation, value)
            if isinstance(raw, bytes):
                raw = raw.decode()
            if raw in ('duplicate', 'busy'):
                raise ExecutionError('执行标识已使用' if raw == 'duplicate' else '该连接仍有执行未结束')
            return json.loads(raw)
        except ExecutionError:
            raise
        except Exception as exc:
            raise ExecutionError('执行注册表不可用，请稍后重试') from exc

    def begin(self):
        if time.time() - self.created_at > 3600:
            raise ExecutionError('execution_id 已过期，不能开始新执行')
        return self._call('begin')['status'] == 'running'

    def cancel(self):
        result = self._call('cancel')
        if result['status'] == 'pending':
            result['status'] = 'cancelling'
        return result

    def status(self):
        return self._call('status')

    def heartbeat(self):
        return self._call('heartbeat')

    def update(self, **fields):
        return self._call('update', json.dumps(fields))

    def finish(self, status):
        if status not in ('completed', 'cancelled', 'failed'):
            raise ValueError('Invalid terminal state')
        return self._call('finish', status)
