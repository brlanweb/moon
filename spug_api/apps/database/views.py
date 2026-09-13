from django.db import transaction
from django.views.generic import View

from libs import Argument, JsonParser, auth, json_response
from apps.database.client import DatabaseClientError, execute, metadata, test_connection
from apps.database.models import DatabaseConnection
from apps.database.policy import PolicyViolation, enforce_command_policy


_DEFAULT_DATABASES = {
    'postgresql': 'postgres',
    'clickhouse': 'default',
    'redis': '0',
}


def _execution_database(connection, request_database=None):
    if request_database is not None:
        return request_database
    return connection.database or _DEFAULT_DATABASES.get(connection.type, '')


class _StrictInteger(int):
    def __new__(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError
        return super().__new__(cls, value)


def _connection_form(body, partial=False):
    return JsonParser(
        Argument('id', type=int, required=False),
        Argument('name', help='请输入连接名称'),
        Argument('type', filter=lambda x: x in dict(DatabaseConnection.TYPES), help='请选择数据库类型'),
        Argument('host', help='请输入主机地址'),
        Argument('port', type=int, filter=lambda x: 0 < x < 65536, help='请输入有效端口'),
        Argument('username', required=False, default=''),
        Argument('password', required=False, default=''),
        Argument('database', required=False, default=''),
        Argument('use_ssl', type=bool, default=False),
        Argument('connect_timeout', type=_StrictInteger, default=10,
                 filter=lambda x: 1 <= x <= 120, help='连接超时必须在 1～120 秒之间'),
        Argument('query_timeout', type=_StrictInteger, default=30,
                 filter=lambda x: 1 <= x <= 3600, help='查询超时必须在 1～3600 秒之间'),
        Argument('idle_timeout', type=_StrictInteger, default=30,
                 filter=lambda x: 0 <= x <= 1440, help='空闲断开必须在 0～1440 分钟之间'),
        Argument('environment', default='normal',
                 filter=lambda x: x in dict(DatabaseConnection.ENVIRONMENTS),
                 help='连接环境必须是 normal 或 production'),
        Argument('read_only', type=bool, default=False),
    ).parse(body, partial)


def _temporary_connection(form):
    item = DatabaseConnection(
        name=form.get('name') or 'temp', type=form.type, host=form.host,
        port=form.port, username=form.get('username') or '',
        database=form.get('database') or '', use_ssl=form.get('use_ssl') or False,
        connect_timeout=form.connect_timeout, query_timeout=form.query_timeout,
        idle_timeout=form.idle_timeout, environment=form.environment,
        read_only=form.read_only,
    )
    item.set_password(form.get('password') or '')
    return item


class ConnectionView(View):
    @auth('database.connection.view')
    def get(self, request):
        return json_response([item.to_view() for item in DatabaseConnection.objects.all()])

    @auth('database.connection.add|database.connection.edit')
    def post(self, request):
        form, error = _connection_form(request.body)
        if error:
            return json_response(error=error)
        required_perm = 'database.connection.edit' if form.id else 'database.connection.add'
        if not request.user.has_perms([required_perm]):
            return json_response(error='权限拒绝')
        other = DatabaseConnection.objects.filter(name=form.name).exclude(pk=form.id or 0).first()
        if other:
            return json_response(error=f'已存在的连接名称【{form.name}】')
        with transaction.atomic():
            if form.id:
                item = DatabaseConnection.objects.filter(pk=form.id).first()
                if not item:
                    return json_response(error='数据库连接不存在')
                password = form.pop('password')
                form.pop('id')
                for key, value in form.items():
                    setattr(item, key, value)
                if password:
                    item.set_password(password)
                item.save()
            else:
                password = form.pop('password')
                form.pop('id')
                item = DatabaseConnection(created_by=request.user, **form)
                item.set_password(password)
                item.save()
        return json_response(item.to_view())

    @auth('database.connection.del')
    def delete(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请指定操作对象')
        ).parse(request.GET)
        if error is None:
            DatabaseConnection.objects.filter(pk=form.id).delete()
        return json_response(error=error)


@auth('database.connection.add|database.connection.edit')
def check_connection(request):
    form, error = _connection_form(request.body)
    if error:
        return json_response(error=error)
    required_perm = 'database.connection.edit' if form.id else 'database.connection.add'
    if not request.user.has_perms([required_perm]):
        return json_response(error='权限拒绝')
    if form.id and not form.password:
        item = DatabaseConnection.objects.filter(pk=form.id).first()
        if not item:
            return json_response(error='数据库连接不存在')
        for key in ('name', 'type', 'host', 'port', 'username', 'database', 'use_ssl',
                    'connect_timeout', 'query_timeout', 'idle_timeout', 'environment',
                    'read_only'):
            setattr(item, key, form.get(key))
    else:
        item = _temporary_connection(form)
    try:
        elapsed = test_connection(item)
    except DatabaseClientError as exc:
        return json_response(error=f'连接失败: {exc}')
    return json_response({'elapsed': elapsed})


@auth('database.connection.view')
def get_metadata(request):
    form, error = JsonParser(
        Argument('id', type=int, help='请指定数据库连接')
    ).parse(request.GET)
    if error:
        return json_response(error=error)
    item = DatabaseConnection.objects.filter(pk=form.id).first()
    if not item:
        return json_response(error='数据库连接不存在')
    try:
        return json_response(metadata(item))
    except DatabaseClientError as exc:
        return json_response(error=f'连接失败: {exc}')


@auth('database.query.do')
def run_command(request):
    if not request.user.has_perms(['database.connection.view']):
        return json_response(error='权限拒绝')
    form, error = JsonParser(
        Argument('id', type=int, help='请指定数据库连接'),
        Argument('command', help='请输入要执行的命令'),
        Argument('database', required=False),
        Argument('confirmation_token', required=False),
    ).parse(request.body)
    if error:
        return json_response(error=error)
    item = DatabaseConnection.objects.filter(pk=form.id).first()
    if not item:
        return json_response(error='数据库连接不存在')
    request_database = None
    if item.type in ('mysql', 'mariadb') and form.database is not None:
        if not isinstance(form.database, str) or not 0 < len(form.database.strip()) <= 128:
            return json_response(error='数据库名称必须为 1～128 个非空白字符')
        request_database = form.database.strip()
    execution_database = _execution_database(item, request_database)
    try:
        decision = enforce_command_policy(
            item,
            request.user.id,
            form.command,
            confirmation_token=form.confirmation_token,
            database=execution_database,
        )
        if decision.requires_confirmation:
            return json_response({
                'requires_confirmation': True,
                'confirmation_token': decision.confirmation_token,
                'statement_types': list(decision.statement_types),
                'execution_database': execution_database,
            })
        return json_response(execute(
            item, form.command, database=request_database,
        ))
    except PolicyViolation as exc:
        return json_response(error=str(exc))
    except DatabaseClientError as exc:
        return json_response(error=f'执行失败: {exc}')
