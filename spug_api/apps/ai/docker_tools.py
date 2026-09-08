import json
from types import SimpleNamespace

from apps.docker.client import (
    DockerClientError,
    build_monitor_logs_command,
    build_monitor_recover_command,
    build_monitor_restart_command,
    discover_all,
    find_name_conflicts,
    read_service_hash,
)
from apps.monitor.docker import evaluate_target, parse_scope


OUTPUT_LIMIT = 20 * 1024
HOST_DIAGNOSTICS = {
    'disk': 'df -h',
    'inode': 'df -i',
    'memory': 'free -m',
    'load': 'uptime',
}


def limit_output(value, limit=OUTPUT_LIMIT):
    raw = str(value or '').encode('utf-8')
    if len(raw) <= limit:
        return raw.decode('utf-8', 'replace')
    return raw[:limit].decode('utf-8', 'ignore') + '\n...（输出已截断）'


def _exec(host, command):
    try:
        with host.get_ssh() as ssh:
            return ssh.exec_command_raw(command)
    except Exception as exc:
        return -1, f'命令执行异常：{exc}'


def _project(scope, payload):
    expected_files = tuple(scope.get('config_files') or [])
    for project in payload.get('projects') or []:
        files = tuple(project.get('config_files') or [project.get('config_file')])
        if (project.get('name') == scope.get('project')
                and project.get('workdir') == scope.get('workdir')
                and files == expected_files):
            return project
    return None


class DockerTargetOperator:
    """Docker 智能体唯一可用的操作面，目标全部来自持久化作用域。"""

    def __init__(self, host, raw_scope):
        self.host = host
        self.scope = parse_scope(raw_scope)
        self.did_write = False

    def _discover(self):
        return discover_all(self.host)

    def _containers(self, payload):
        if self.scope['kind'] == 'standalone_container':
            return [item for item in payload.get('standalone') or []
                    if item.get('name') == self.scope['container']]
        project = _project(self.scope, payload)
        return [item for item in (project or {}).get('containers', [])
                if item.get('service') == self.scope['service']]

    def status(self):
        result = evaluate_target(self.scope, self._discover())
        return limit_output(json.dumps({
            'is_ok': result.is_ok,
            'message': result.message,
            'details': result.details,
        }, ensure_ascii=False, default=str))

    def logs(self):
        containers = self._containers(self._discover())
        if not containers:
            return '目标容器不存在，无法读取日志。'
        chunks = []
        for item in containers:
            command = build_monitor_logs_command(item['name'])
            code, output = _exec(self.host, command)
            chunks.append(f"[{item['name']}] exit={code}\n{output or ''}")
        return limit_output('\n\n'.join(chunks))

    def restart(self):
        payload = self._discover()
        result = evaluate_target(self.scope, payload)
        abnormal_names = {item['name'] for item in result.details.get('abnormal') or []}
        containers = self._containers(payload)
        targets = [item for item in containers if item.get('name') in abnormal_names]
        if not targets:
            return '没有可安全重启的异常目标容器；若副本缺失，请使用目标服务恢复工具。'
        outputs = []
        for item in targets:
            command = build_monitor_restart_command(item['name'])
            self.did_write = True
            code, output = _exec(self.host, command)
            outputs.append(f"{item['name']}: exit={code} {output or ''}".strip())
            if code:
                break
        return limit_output('\n'.join(outputs))

    def recover(self):
        if self.scope['kind'] != 'compose_service':
            return '独立容器缺失后没有可靠启动参数，禁止自动重建。'
        if not self.scope.get('can_recover_missing') or not self.scope.get('config_hash'):
            return '目标未建立可信配置哈希基线，禁止自动恢复缺失副本。'
        payload = self._discover()
        project = _project(self.scope, payload)
        if not project:
            files = self.scope.get('config_files') or []
            if not files:
                return 'Compose配置路径缺失，禁止自动恢复。'
            project = {
                'name': self.scope['project'],
                'workdir': self.scope['workdir'],
                'config_file': files[0],
                'config_files': files,
                'containers': [],
            }
        if find_name_conflicts(
                payload.get('projects') or [], project['name'], project['config_file']):
            return '检测到同名Compose项目冲突，禁止自动恢复。'
        containers = self._containers(payload)
        expected = int(self.scope['expected_replicas'])
        if len(containers) >= expected:
            return '目标服务副本未缺失，无需执行恢复命令。'
        hashes = {item.get('config_hash') for item in containers if item.get('config_hash')}
        if hashes and hashes != {self.scope['config_hash']}:
            return '运行中副本配置哈希与监控基线不一致，禁止自动恢复。'
        try:
            current = read_service_hash(
                self.host, SimpleNamespace(**project), self.scope['service'])
        except DockerClientError as exc:
            return f'无法校验当前配置哈希，禁止自动恢复：{exc}'
        if current != self.scope['config_hash']:
            return '当前Compose配置哈希与监控基线不一致，禁止自动恢复。'
        command = build_monitor_recover_command(
            SimpleNamespace(**project), self.scope['service'], expected)
        self.did_write = True
        code, output = _exec(self.host, command)
        return limit_output(f'exit={code}\n{output or ""}')

    def host_diagnostics(self, kind):
        command = HOST_DIAGNOSTICS.get(kind)
        if not command:
            return '不支持的宿主机诊断项，仅支持 disk、inode、memory、load。'
        code, output = _exec(self.host, command)
        return limit_output(f'exit={code}\n{output or ""}')
