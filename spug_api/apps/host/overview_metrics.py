"""On-demand host charts: 5s freshness, 60s idle retention, 5min history."""
import json
import math
import time
from uuid import uuid4
from threading import Timer

from django_redis import get_redis_connection
from libs import Argument, JsonParser, auth, json_response
from apps.account.utils import get_host_perms
from apps.host.models import Host

INTERVAL = 5
CACHE_TTL = 60
HISTORY_WINDOW = 300
MAX_POINTS = 61
# Longer than connection (3 x 5s) plus hard channel budget (12s).
LOCK_TTL = 60
COMMAND = r'''
head -1 /proc/stat
 grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
echo SPUG_GPU
_NS=""
for _P in nvidia-smi /usr/bin/nvidia-smi /usr/local/bin/nvidia-smi /usr/local/nvidia/bin/nvidia-smi /opt/bin/nvidia-smi; do
  if command -v "$_P" >/dev/null 2>&1; then _NS="$_P"; break; fi
done
if [ -z "$_NS" ]; then
  echo absent
elif command -v timeout >/dev/null 2>&1; then
  timeout -s KILL 2 "$_NS" --query-gpu=index,utilization.gpu --format=csv,noheader,nounits 2>/dev/null || echo unavailable
else
  echo unavailable
fi
'''


def parse_sample(output, previous=None):
    point = {'cpu': None, 'memory': None, 'gpu': [], 'gpu_status': 'unavailable'}
    head, marker, gpu = output.partition('SPUG_GPU')
    stat, memory = None, {}
    for line in head.splitlines():
        fields = line.split()
        try:
            if fields and fields[0] == 'cpu' and len(fields) >= 5:
                # guest/guest_nice are already included in user/nice.
                counts = [int(value) for value in fields[1:9]]
                if min(counts) >= 0:
                    stat = [sum(counts), counts[3] + (counts[4] if len(counts) > 4 else 0)]
            elif fields and fields[0] in ('MemTotal:', 'MemAvailable:'):
                memory[fields[0]] = int(fields[1])
        except (ValueError, IndexError):
            continue
    if stat and previous:
        total, idle = stat[0] - previous[0], stat[1] - previous[1]
        if total > 0 and 0 <= idle <= total:
            point['cpu'] = round(100 * (total - idle) / total, 1)
    total, available = memory.get('MemTotal:', 0), memory.get('MemAvailable:')
    if total > 0 and available is not None and 0 <= available <= total:
        point['memory'] = round(100 * (total - available) / total, 1)
    if marker:
        if gpu.strip() == 'absent':
            point['gpu_status'] = 'absent'
        elif 'unavailable' not in gpu:
            for line in gpu.splitlines():
                try:
                    index, value = line.split(',')
                    value = float(value)
                    if int(index) >= 0 and math.isfinite(value) and 0 <= value <= 100:
                        point['gpu'].append({'id': int(index), 'value': value})
                except (ValueError, TypeError):
                    continue
            if point['gpu']:
                point['gpu_status'] = 'available'
    return point, stat


def probe(host):
    ssh = host.get_ssh()
    ssh.arguments.update(timeout=5, banner_timeout=5, auth_timeout=5)
    watchdog = None
    try:
        client = ssh.get_client()
        # Paramiko exec_command waits for acknowledgement without honoring
        # Channel.settimeout. Close the transport to bound that wait too.
        watchdog = Timer(12, client.close)
        watchdog.daemon = True
        watchdog.start()
        channel = client.get_transport().open_session(timeout=5)
        try:
            channel.settimeout(6)
            channel.exec_command(COMMAND)
            deadline, output = time.monotonic() + 6, bytearray()
            while time.monotonic() < deadline:
                if channel.recv_ready():
                    output.extend(channel.recv(4096))
                    if len(output) > 65536:
                        raise ValueError('probe output limit')
                elif channel.exit_status_ready():
                    return output.decode('utf-8', errors='replace')
                else:
                    time.sleep(0.02)
            raise TimeoutError('probe timeout')
        finally:
            channel.close()
    finally:
        if watchdog:
            watchdog.cancel()
        if ssh.client:
            ssh.client.close()


def collect(host, rds):
    key = f'spug:host:chart:v1:{host.id}'
    lock_key, token = key + ':lock', uuid4().hex
    now = time.time()
    raw = rds.get(key)
    state = json.loads(raw) if raw else {}
    if now - state.get('attempted_at', 0) < INTERVAL:
        return state
    if not rds.set(lock_key, token, nx=True, ex=LOCK_TTL):
        return dict(state, collecting=True)
    try:
        # A winner may have published between our first read and acquiring the lock.
        raw = rds.get(key)
        state = json.loads(raw) if raw else {}
        if time.time() - state.get('attempted_at', 0) < INTERVAL:
            return state
        history = [p for p in state.get('history', []) if now - p['ts'] <= HISTORY_WINDOW]
        try:
            output = probe(host)
            previous = state.get('stat') if now - state.get('sampled_at', 0) <= CACHE_TTL else None
            point, stat = parse_sample(output, previous)
            if stat is None and point['memory'] is None:
                raise ValueError('host metrics unavailable')
            sampled_at = time.time()
            history.append(dict(point, ts=sampled_at))
            state = {'history': history[-MAX_POINTS:], 'stat': stat, 'sampled_at': sampled_at}
        except Exception:
            # Never return SSH exception text or remote output to the browser.
            state = dict(state, history=history[-MAX_POINTS:], error='主机指标暂不可用')
        state['attempted_at'] = time.time()
        rds.setex(key, CACHE_TTL, json.dumps(state))
        return state
    finally:
        rds.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end", 1, lock_key, token)


@auth('host.host.view')
def overview_metrics(request):
    form, error = JsonParser(Argument('id', type=int, help='参数错误')).parse(request.GET)
    if error is not None:
        return json_response(error=error)
    if not request.user.is_supper and form.id not in get_host_perms(request.user):
        return json_response(error='无权访问该主机')
    host = Host.objects.filter(pk=form.id).first()
    if not host:
        return json_response(error='未找到指定主机')
    if not host.is_verified:
        return json_response({'host_id': host.id, 'error': '主机未验证', 'history': []})
    try:
        state = collect(host, get_redis_connection())
    except Exception:
        # Fail closed: no uncoordinated SSH fallback when Redis is unavailable.
        state = {'error': '指标缓存暂不可用', 'history': []}
    return json_response({
        'host_id': host.id, 'history': state.get('history', []),
        'sampled_at': state.get('sampled_at'), 'error': state.get('error'),
        'collecting': state.get('collecting', False), 'server_time': time.time(),
    })
