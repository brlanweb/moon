from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import time

from apps.docker.client import DockerClientError, discover_all, read_service_hash


@dataclass
class DetectionResult:
    is_ok: bool
    message: str
    failure_kind: str = ''
    details: dict = field(default_factory=dict)

    def __iter__(self):
        # Keep existing call sites that unpack ``is_ok, message`` compatible.
        yield self.is_ok
        yield self.message


def validate_and_normalize_scope(host, raw_scope):
    """只用实时发现结果重建可持久化目标，忽略前端提交的基线字段。"""
    if isinstance(raw_scope, str):
        try:
            raw_scope = json.loads(raw_scope)
        except (TypeError, ValueError) as exc:
            raise DockerClientError('Docker监控目标配置格式无效') from exc
    if not isinstance(raw_scope, dict) or raw_scope.get('version') != 1:
        raise DockerClientError('Docker监控目标配置版本无效')

    payload = discover_all(host)
    kind = raw_scope.get('kind')
    if kind == 'standalone_container':
        name = raw_scope.get('container')
        known = {item.get('name') for item in payload.get('standalone') or []}
        if not name or name not in known:
            raise DockerClientError('独立容器不存在，请刷新后重试')
        return {'version': 1, 'kind': kind, 'container': name}
    if kind != 'compose_service':
        raise DockerClientError('Docker监控目标类型无效')

    lookup_scope = {
        'project': raw_scope.get('project'),
        'workdir': raw_scope.get('workdir'),
        'config_files': raw_scope.get('config_files') or [],
    }
    project = _project(lookup_scope, payload)
    if not project:
        raise DockerClientError('Compose项目不存在或配置路径已变化，请刷新后重试')
    service = raw_scope.get('service')
    containers = [item for item in project.get('containers') or []
                  if item.get('service') == service]
    if not service or not containers:
        raise DockerClientError('Compose服务不存在，请刷新后重试')

    hashes = {item.get('config_hash') for item in containers if item.get('config_hash')}
    config_hash = ''
    can_recover = False
    if len(hashes) > 1:
        raise DockerClientError('目标服务各副本配置哈希不一致，请人工确认')
    try:
        current_hash = read_service_hash(host, SimpleNamespace(**project), service)
    except Exception:
        current_hash = ''
    if current_hash and hashes:
        if current_hash not in hashes:
            raise DockerClientError('当前Compose配置与运行容器配置不一致，请先人工发布')
        config_hash = current_hash
        can_recover = True

    return {
        'version': 1,
        'kind': kind,
        'project': project['name'],
        'workdir': project['workdir'],
        'config_files': project.get('config_files') or [project['config_file']],
        'service': service,
        'expected_replicas': len(containers),
        'config_hash': config_hash,
        'can_recover_missing': can_recover,
    }


def parse_scope(raw_scope):
    if isinstance(raw_scope, str):
        try:
            raw_scope = json.loads(raw_scope)
        except (TypeError, ValueError) as exc:
            raise DockerClientError('Docker监控目标配置格式无效') from exc
    if not isinstance(raw_scope, dict) or raw_scope.get('version') != 1:
        raise DockerClientError('Docker监控目标配置版本无效')
    kind = raw_scope.get('kind')
    if kind == 'compose_service':
        required = ('project', 'workdir', 'config_files', 'service', 'expected_replicas')
        if any(not raw_scope.get(key) for key in required):
            raise DockerClientError('Compose监控目标配置不完整')
    elif kind == 'standalone_container':
        if not raw_scope.get('container'):
            raise DockerClientError('独立容器监控目标配置不完整')
    else:
        raise DockerClientError('Docker监控目标类型无效')
    return raw_scope


def startup_grace_seconds(container):
    try:
        start_period = int(container.get('health_start_period_ns') or 0) / 1_000_000_000
    except (TypeError, ValueError):
        start_period = 0
    return max(120, int(start_period))


def _started_at(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _project(scope, payload):
    wanted_files = tuple(scope.get('config_files') or [])
    for project in payload.get('projects') or []:
        files = tuple(project.get('config_files') or [project.get('config_file')])
        if (project.get('name') == scope.get('project')
                and project.get('workdir') == scope.get('workdir')
                and files == wanted_files):
            return project
    return None


def _abnormal_reason(container, now, strict):
    state = container.get('state') or 'unknown'
    health = container.get('health') or ''
    if state != 'running':
        return state
    if health == 'unhealthy':
        return health
    if health == 'starting':
        if strict:
            return 'starting'
        started = _started_at(container.get('started_at'))
        if not started:
            return 'starting时间未知'
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = max(0, (now - started.astimezone(timezone.utc)).total_seconds())
        if elapsed > startup_grace_seconds(container):
            return 'starting超时'
    elif health not in ('', 'healthy'):
        return health
    return ''


def _verification_timeout(containers):
    maximum = 120
    for item in containers:
        grace = startup_grace_seconds(item)
        try:
            interval = int(item.get('health_interval_ns') or 0) / 1_000_000_000
            retries = max(1, int(item.get('health_retries') or 0))
        except (TypeError, ValueError):
            interval, retries = 0, 1
        maximum = max(maximum, int(grace + max(60, interval * retries)))
    return maximum


def evaluate_target(raw_scope, payload, now=None, strict=False):
    scope = parse_scope(raw_scope)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    missing = False
    if scope['kind'] == 'compose_service':
        project = _project(scope, payload)
        containers = [item for item in (project or {}).get('containers', [])
                      if item.get('service') == scope['service']]
        expected = int(scope['expected_replicas'])
        missing = len(containers) < expected
    else:
        containers = [item for item in payload.get('standalone') or []
                      if item.get('name') == scope['container']]
        expected = 1
        missing = not containers

    abnormal = []
    for item in containers:
        reason = _abnormal_reason(item, now, strict)
        if reason:
            abnormal.append({'name': item.get('name') or '-', 'reason': reason,
                             'state': item.get('state') or '',
                             'health': item.get('health') or '',
                             'restart_count': item.get('restart_count') or 0})

    details = {
        'containers': containers,
        'abnormal': abnormal,
        'missing': missing,
        'expected_replicas': expected,
        'actual_replicas': len(containers),
        'verification_timeout': _verification_timeout(containers),
    }
    if missing:
        return DetectionResult(
            False, f'Docker服务副本缺失：期望{expected}，当前{len(containers)}',
            'target', details)
    if abnormal:
        summary = '，'.join(f"{item['name']}={item['reason']}" for item in abnormal)
        if strict and all(item['reason'] == 'starting' for item in abnormal):
            details['strict_pending'] = True
        return DetectionResult(False, f'Docker服务状态异常：{summary}', 'target', details)

    names = '、'.join(item.get('name') or '-' for item in containers)
    details['strict_healthy'] = strict
    return DetectionResult(True, f'Docker服务状态正常：{names}', details=details)


def check_target(host, raw_scope, strict=False, now=None):
    try:
        payload = discover_all(host)
        return evaluate_target(raw_scope, payload, now=now, strict=strict)
    except Exception as exc:
        return DetectionResult(False, f'Docker检测失败：{exc}', 'infrastructure')


def verify_recovery(host, raw_scope, checker=check_target, sleep=time.sleep,
                    monotonic=time.monotonic, timeout_seconds=None):
    started = monotonic()
    stable = 0
    last = DetectionResult(False, '尚未执行恢复验证', 'target')
    while True:
        last = checker(host, raw_scope, strict=True)
        if last.is_ok and last.details.get('strict_healthy'):
            stable += 1
            if stable >= 2:
                return DetectionResult(True, f'目标已连续2次验证稳定：{last.message}', details=last.details)
        else:
            stable = 0
            if not last.details.get('strict_pending'):
                return last

        timeout = timeout_seconds or int(last.details.get('verification_timeout') or 120)
        if timeout > 1800:
            return DetectionResult(False, '恢复验证预计超过30分钟，已转人工处理', 'target', last.details)
        if monotonic() - started >= timeout:
            return DetectionResult(False, f'恢复验证超时：{last.message}', 'target', last.details)
        sleep(10)
