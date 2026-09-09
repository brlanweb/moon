# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
import django
from django.conf import settings
from libs import JsonParser, Argument, json_response, auth
from libs.mail import Mail
from libs.mixins import AdminView
from apps.setting.utils import AppSetting
from apps.setting.models import Setting, KEYS_DEFAULT
from copy import deepcopy
import platform


class SettingView(AdminView):

    def get(self, request):
        response = deepcopy(KEYS_DEFAULT)
        for item in Setting.objects.all():
            if item.key == 'ldap_service':
                continue
            if item.key in ('spug_push_key', 'MFA'):
                continue
            response[item.key] = item.real_val
        return json_response(response)

    def post(self, request):
        form, error = JsonParser(
            Argument('data', type=list, help='缺少必要的参数')
        ).parse(request.body)
        if error is None:
            if any(isinstance(item, dict) and item.get('key') == 'ldap_service' for item in form.data):
                return json_response(error='该设置已下线')
            if any(isinstance(item, dict) and item.get('key') in ('spug_push_key', 'MFA') for item in form.data):
                return json_response(error='外部推送服务及其MFA设置已移除')
            for item in form.data:
                AppSetting.set(**item)
        return json_response(error=error)


@auth('admin')
def email_test(request):
    form, error = JsonParser(
        Argument('server', help='请输入邮件服务地址'),
        Argument('port', type=int, help='请输入邮件服务端口号'),
        Argument('username', help='请输入邮箱账号'),
        Argument('password', help='请输入密码/授权码'),
        Argument('nickname', required=False),
    ).parse(request.body)
    if error is None:
        try:
            mail = Mail(**form)
            mail.send_text_mail(
                [form.username],
                'Moon 邮件服务测试',
                '这是一封来自 Moon 的测试邮件，收到此邮件表示邮件服务配置正常。',
            )
            return json_response()
        except Exception as e:
            error = f'{e}'
    return json_response(error=error)


@auth('admin')
def get_about(request):
    return json_response({
        'python_version': platform.python_version(),
        'system_version': platform.platform(),
        'spug_version': settings.SPUG_VERSION,
        'django_version': django.get_version()
    })
