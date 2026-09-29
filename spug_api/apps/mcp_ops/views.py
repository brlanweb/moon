from django.db.models import Q
from django.views.generic import View

from apps.account.utils import get_host_perms
from apps.mcp_ops.models import McpAuditLog, McpToken
from apps.mcp_ops.service import TOKEN_DAYS, create_token, delete_token, regenerate_token
from libs import Argument, JsonParser, auth, json_response

_DAYS_HELP = '有效期只能是 1、7、30 天、6 个月或 1 年'


def _valid_days(value):
    return type(value) is int and value in TOKEN_DAYS


def _token_query(user):
    query = McpToken.objects.select_related('user')
    return query if user.is_supper else query.filter(user=user)


class TokenView(View):
    @auth('system.mcp.view')
    def get(self, request):
        return json_response({'tokens': [item.to_view() for item in _token_query(request.user)]})

    @auth('system.mcp.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('name', help='请输入令牌名称'),
            Argument('days', filter=_valid_days, help=_DAYS_HELP),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        try:
            token, plaintext = create_token(request.user, form.name, form.days)
            data = token.to_view()
            data['token'] = plaintext
            return json_response(data)
        except Exception as exc:
            return json_response(error=str(exc))

    @auth('system.mcp.del')
    def delete(self, request):
        form, error = JsonParser(Argument('id', type=int)).parse(request.GET)
        if error:
            return json_response(error=error)
        token = _token_query(request.user).filter(pk=form.id).first()
        if not token:
            return json_response(error='令牌不存在')
        try:
            delete_token(token, request.user)
        except Exception as exc:
            return json_response(error=str(exc))
        return json_response()


class RegenerateView(View):
    @auth('system.mcp.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int),
            Argument('days', filter=_valid_days, help=_DAYS_HELP),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        token = _token_query(request.user).filter(pk=form.id).first()
        if not token:
            return json_response(error='令牌不存在')
        try:
            refreshed, plaintext = regenerate_token(token, request.user, form.days)
            data = refreshed.to_view()
            data['token'] = plaintext
            return json_response(data)
        except Exception as exc:
            return json_response(error=str(exc))


class AuditView(View):
    @auth('system.mcp.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('page', type=int, default=1, filter=lambda value: value > 0),
            Argument('page_size', type=int, default=20, filter=lambda value: 0 < value <= 100),
            Argument('status', required=False),
            Argument('operation', required=False),
            Argument('token_id', type=int, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = McpAuditLog.objects.select_related('operator', 'host')
        if not request.user.is_supper:
            query = query.filter(operator=request.user).filter(
                Q(host_id__in=get_host_perms(request.user)) |
                Q(host__isnull=True, script__isnull=True, output__isnull=True))
        if form.status:
            query = query.filter(status=form.status)
        if form.operation:
            query = query.filter(operation=form.operation)
        if form.token_id:
            query = query.filter(token_id=form.token_id)
        total = query.count()
        start = (form.page - 1) * form.page_size
        records = [item.to_view() for item in query[start:start + form.page_size]]
        return json_response({'records': records, 'total': total})
