"""Read-only resource detection using the shared host probe."""
import json
import math

from apps.host.metrics import PROBE_COMMAND_FULL, _parse_output
from apps.monitor.docker import DetectionResult


METRICS = ('cpu', 'memory', 'disk', 'temperature')
MAX_INTEGER = 2_147_483_647


def _finite_number(value, maximum):
    return (type(value) in (int, float) and 0 <= value <= maximum
            and math.isfinite(value))


def parse_config(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid resource monitor JSON') from exc
    if not isinstance(raw, dict):
        raise ValueError('Resource extra must be a JSON object')
    if set(raw) - {'metric', 'operator', 'value', 'mount'}:
        raise ValueError('Unknown resource monitor configuration field')
    metric = raw.get('metric')
    if metric not in METRICS:
        raise ValueError('metric must be cpu, memory, disk or temperature')
    if raw.get('operator') != 'gte':
        raise ValueError('operator must be gte')
    maximum = 250 if metric == 'temperature' else 100
    value = raw.get('value')
    if not _finite_number(value, maximum):
        raise ValueError(f'value must be a finite number between 0 and {maximum}')
    mount = raw.get('mount', '')
    if (not isinstance(mount, str) or len(mount) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in mount)
            or (mount and (metric != 'disk' or not mount.startswith('/')))):
        raise ValueError('mount must be empty or an absolute disk mount point')
    return {'metric': metric, 'operator': 'gte', 'value': value, 'mount': mount}


def validate_payload(payload):
    """Validate before JsonParser can coerce floats/bools into integers."""
    targets = payload.get('targets')
    if (not isinstance(targets, list) or not targets
            or any(type(item) is not int or not 1 <= item <= MAX_INTEGER for item in targets)
            or len(set(targets)) != len(targets)):
        raise ValueError('targets must be a non-empty list of distinct positive host IDs')
    for name, default, minimum in (('rate', 5, 1), ('threshold', 3, 1), ('quiet', 1440, 0)):
        value = payload.get(name, default)
        if type(value) is not int or not minimum <= value <= MAX_INTEGER:
            raise ValueError(f'{name} must be an integer between {minimum} and {MAX_INTEGER}')
    parse_config(payload.get('extra'))


def _temperature_values(metrics, output):
    temperature = metrics.get('temperature') or {}
    values = [temperature.get('max')]
    values.extend(item.get('temperature') for item in metrics.get('gpu') or [])
    # The host parser drops GPU rows when utilization or memory is N/A.
    # Temperature is independent: retain a valid fourth CSV column.
    _, marker, gpu_output = output.partition('SPUG_PROBE_GPU')
    if marker:
        for line in gpu_output.splitlines():
            fields = line.split(',')
            if len(fields) == 4:
                try:
                    values.append(float(fields[3].strip()))
                except ValueError:
                    pass
    return [value for value in values if _finite_number(value, 250)]


def _disk_readings(metrics, output):
    disks = metrics.get('disk') or []
    if not output:
        return disks
    disk_output = output.split('SPUG_PROBE_DISK', 1)[1].split('SPUG_PROBE_TEMP', 1)[0]
    rows = [line.split(None, 5) for line in disk_output.strip().splitlines()]
    # Do not let the shared parser's skipped rows hide an unreadable disk.
    if len(rows) != len(disks) or any(len(row) != 6 or not row[5].startswith('/') for row in rows):
        raise ValueError('Disk probe contains missing or invalid measurements')
    # Preserve full mount names, including spaces, without changing the host parser.
    return [{**disk, 'mount': row[5]} for disk, row in zip(disks, rows)]


def evaluate(config, metrics, output=''):
    metric = config['metric']
    selected_mount = ''
    if metric == 'cpu':
        value = metrics.get('cpu')
    elif metric == 'memory':
        value = (metrics.get('memory') or {}).get('percent')
    elif metric == 'disk':
        disks = _disk_readings(metrics, output)
        if config['mount']:
            disks = [item for item in disks if item.get('mount') == config['mount']]
        if not disks or any(not _finite_number(item.get('percent'), 100) for item in disks):
            raise ValueError(f'Disk usage unavailable for {config["mount"] or "all mounts"}')
        selected = max(disks, key=lambda item: item['percent'])
        value, selected_mount = selected['percent'], selected['mount']
    else:
        temperatures = _temperature_values(metrics, output)
        if not temperatures:
            raise ValueError('Temperature unavailable: no readable sysfs or GPU sensors')
        value = max(temperatures)
    maximum = 250 if metric == 'temperature' else 100
    if not _finite_number(value, maximum):
        raise ValueError(f'{metric} measurement is missing or invalid')
    unit = 'C' if metric == 'temperature' else '%'
    is_ok = value < config['value']
    location = f' ({selected_mount})' if selected_mount else ''
    comparison = '<' if is_ok else '>='
    message = f'{metric}{location}: {value:g}{unit} {comparison} {config["value"]:g}{unit}'
    return DetectionResult(is_ok, message, '' if is_ok else 'target', {
        'metric': metric, 'value': value, 'unit': unit, 'mount': selected_mount,
        'operator': config['operator'], 'limit': config['value'],
    })


def check_target(host, raw_config):
    try:
        config = parse_config(raw_config)
        if not host or not host.is_verified:
            raise ValueError('Host does not exist or is not verified')
        with host.get_ssh() as ssh:
            # Configuration, including mount names, never enters the shell command.
            exit_code, output = ssh.exec_command_raw(PROBE_COMMAND_FULL)
        if exit_code != 0:
            raise ValueError(f'Probe exited with status {exit_code}: {output[:200]}')
        metrics, _, _ = _parse_output(output)
        return evaluate(config, metrics, output)
    except Exception as exc:
        return DetectionResult(False, f'Resource collection failed: {exc}', 'infrastructure')
