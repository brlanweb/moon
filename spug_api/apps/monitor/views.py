# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.views.generic import View
from django.conf import settings
from django_redis import get_redis_connection
from libs import json_response, JsonParser, Argument, human_datetime, auth
from apps.monitor.models import Detection, AI_LOOP_LIMITS
from apps.monitor.executors import dispatch
from apps.monitor.docker import (
    clear_repair_policy, repair_target_key, validate_and_normalize_scope)
from apps.host.models import Host
from apps.account.utils import has_host_perm
from apps.docker.client import DockerClientError
from datetime import datetime
import json


def prepare_docker_form(user, form):
    if len(form.targets) != 1:
        return 'Docker服务检测必须且只能选择一台主机'
    host_id = form.targets[0]
    if not user.has_perms(['docker.project.view']):
        return '缺少Docker查看权限'
    if not has_host_perm(user, host_id):
        return '无权访问所选Docker主机'
    host = Host.objects.filter(pk=host_id).first()
    if not host:
        return '所选Docker主机不存在'
    try:
        scope = validate_and_normalize_scope(host, form.extra)
    except DockerClientError as exc:
        return str(exc)
    form.extra = json.dumps(scope, ensure_ascii=False)
    if form.ai_mode:
        form.ai_host_id = host_id
    return None


class DetectionView(View):
    @auth('dashboard.dashboard.view|monitor.monitor.view')
    def get(self, request):
        detections = Detection.objects.all()
        groups = [x['group'] for x in detections.order_by('group').values('group').distinct()]
        return json_response({'groups': groups, 'detections': [x.to_view() for x in detections]})

    @auth('monitor.monitor.add|monitor.monitor.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', help='请输入任务名称'),
            Argument('group', help='请选择任务分组'),
            Argument('targets', type=list, filter=lambda x: len(x), help='请输入监控地址'),
            Argument('type', filter=lambda x: x in dict(Detection.TYPES), help='请选择监控类型'),
            Argument('extra', required=False),
            Argument('desc', required=False),
            Argument('rate', type=int, default=5),
            Argument('threshold', type=int, default=3),
            Argument('quiet', type=int, default=24 * 60),
            Argument('notify_grp', type=list, help='请选择报警联系组'),
            Argument('notify_mode', type=list, help='请选择报警方式'),
            Argument('ai_mode', default='', filter=lambda x: x in ('', 'diagnose', 'repair'),
                     help='请选择正确的AI前置任务类型'),
            Argument('ai_host_id', type=int, required=False),
            Argument('ai_max_loops', type=int, required=False),
        ).parse(request.body)
        if error is None and form.type == '6':
            error = prepare_docker_form(request.user, form)
        if error is None:
            # 报警方式不做任何前置拦截：渠道未配置时由 libs/spug.py 在实际发送阶段
            # 给出站内通知，配置保存本身不再被阻断。
            if form.ai_mode:
                if not form.ai_host_id:
                    return json_response(error='启用AI前置任务时必须选择用于排查的主机')
                # 诊断是只读排查，定位到原因就该收尾，给太多轮次只会让模型发散，上限 10；
                # 修复要多轮「执行→复检」试错，上限 20。前端已限幅，这里兜底防绕过。
                ceiling, fallback = AI_LOOP_LIMITS[form.ai_mode]
                form.ai_max_loops = max(1, min(form.ai_max_loops or fallback, ceiling))
            else:
                form.ai_host_id = None
                # 未启用时仍要给个合法值，字段本身不允许为空
                form.ai_max_loops = form.ai_max_loops or 15

            form.targets = json.dumps(form.targets)
            form.notify_grp = json.dumps(form.notify_grp)
            form.notify_mode = json.dumps(form.notify_mode)
            if form.id:
                Detection.objects.filter(pk=form.id).update(
                    updated_at=human_datetime(),
                    updated_by=request.user,
                    **form)
                task = Detection.objects.filter(pk=form.id).first()
                if task and task.is_active:
                    form.action = 'modify'
                    rds_cli = get_redis_connection()
                    rds_cli.lpush(settings.MONITOR_KEY, json.dumps(form))
            else:
                dtt = Detection.objects.create(created_by=request.user, **form)
                form.action = 'add'
                form.id = dtt.id
                rds_cli = get_redis_connection()
                rds_cli.lpush(settings.MONITOR_KEY, json.dumps(form))
        return json_response(error=error)

    @auth('monitor.monitor.edit')
    def patch(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象'),
            Argument('is_active', type=bool, required=False)
        ).parse(request.body, True)
        if error is None:
            task = Detection.objects.filter(pk=form.id).first()
            Detection.objects.filter(pk=form.id).update(**form)
            if form.get('is_active') is not None:
                rds_cli = get_redis_connection()
                if task and task.type == '6':
                    try:
                        host_id = json.loads(task.targets)[0]
                        clear_repair_policy(
                            rds_cli, repair_target_key(host_id, task.extra))
                    except Exception:
                        pass
                if form.is_active:
                    task = Detection.objects.filter(pk=form.id).first()
                    message = {'id': form.id, 'action': 'add'}
                    message.update(task.to_dict(selects=('targets', 'extra', 'rate', 'type', 'threshold', 'quiet')))
                else:
                    message = {'id': form.id, 'action': 'remove'}
                rds_cli.lpush(settings.MONITOR_KEY, json.dumps(message))
        return json_response(error=error)

    @auth('monitor.monitor.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            task = Detection.objects.filter(pk=form.id).first()
            if task:
                if task.is_active:
                    return json_response(error='该监控项正在运行中，请先停止后再尝试删除')
                task.delete()
        return json_response(error=error)


@auth('monitor.monitor.add|monitor.monitor.edit')
def run_test(request):
    form, error = JsonParser(
        Argument('type', help='请选择监控类型'),
        Argument('targets', type=list, filter=lambda x: len(x), help='请输入监控地址'),
        Argument('extra', required=False)
    ).parse(request.body)
    if error is None and form.type == '6':
        form.ai_mode = ''
        error = prepare_docker_form(request.user, form)
    if error is None:
        is_success, message = dispatch(form.type, form.targets[0], form.extra)
        return json_response({'is_success': is_success, 'message': message})
    return json_response(error=error)


@auth('monitor.monitor.view')
def get_overview(request):
    response = []
    rds = get_redis_connection()
    for item in Detection.objects.all():
        data = {}
        for key in json.loads(item.targets):
            key = str(key)
            data[key] = {
                'id': f'{item.id}_{key}',
                'group': item.group,
                'name': item.name,
                'type': item.get_type_display(),
                'target': key,
                'desc': item.desc,
                'status': '0',
                'latest_run_time': item.latest_run_time,
            }
            if item.is_active:
                if item.latest_run_time:
                    data[key]['status'] = '1'
                else:
                    data[key]['status'] = '10'
        if item.is_active:
            for key, val in rds.hgetall(f'spug:det:{item.id}').items():
                prefix, key = key.decode().split('_', 1)
                if key in data:
                    val = int(val)
                    if prefix == 'c':
                        if data[key]['status'] == '1':
                            data[key]['status'] = '2'
                        data[key]['count'] = val
                    elif prefix == 't':
                        date = datetime.fromtimestamp(val).strftime('%Y-%m-%d %H:%M:%S')
                        data[key].update(status='3', notified_at=date)
        response.extend(list(data.values()))
    return json_response(response)
