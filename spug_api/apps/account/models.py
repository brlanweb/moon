# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
from django.core.cache import cache
from libs import ModelMixin
from django.contrib.auth.hashers import make_password, check_password
import json


def load_json(value, default):
    """Accept JSONField values and up to two legacy JSON encoding layers."""
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode()
        except UnicodeDecodeError:
            return default
    for _ in range(2):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except ValueError:
            return default
    return value if isinstance(value, type(default)) else default


def permission_ids(value):
    # Reject booleans, floats and containers; never coerce corrupt values into IDs.
    if not isinstance(value, list):
        return []
    return [x for x in value if (type(x) is int and x > 0) or (
        isinstance(x, str) and x.isascii() and x.isdecimal() and x.strip('0'))]


class User(models.Model, ModelMixin):
    username = models.CharField(max_length=100)
    nickname = models.CharField(max_length=100)
    password_hash = models.CharField(max_length=100)  # hashed password
    type = models.CharField(max_length=20, default='default')
    is_supper = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    access_token = models.CharField(max_length=32)
    token_expired = models.IntegerField(null=True)
    last_login = models.CharField(max_length=20)
    last_ip = models.CharField(max_length=50)
    roles = models.ManyToManyField('Role', db_table='user_role_rel')
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def make_password(password):
        return make_password(password, hasher='pbkdf2_sha256')

    def verify_password(self, password):
        return check_password(password, self.password_hash)

    def get_perms_cache(self):
        return cache.get(f'perms_{self.id}', set())

    def set_perms_cache(self, value=None):
        cache.set(f'perms_{self.id}', value or set())

    @property
    def page_perms(self):
        data = self.get_perms_cache()
        if data:
            return data
        for item in self.roles.all():
            for m, v in item.get_page_perms().items():
                for p, d in v.items():
                    data.update(f'{m}.{p}.{x}' for x in d)
        self.set_perms_cache(data)
        return data

    @property
    def deploy_perms(self):
        data = {'apps': set(), 'envs': set()}
        for item in self.roles.all():
            perms = item.get_deploy_perms()
            data['apps'].update(perms.get('apps', []))
            data['envs'].update(perms.get('envs', []))
        data['apps'].update(x.id for x in self.app_set.all())
        return data

    @property
    def group_perms(self):
        data = set()
        for item in self.roles.all():
            data.update(item.get_group_perms())
        return list(data)

    def has_perms(self, codes):
        if self.is_supper:
            return True
        return self.page_perms.intersection(codes)

    def __repr__(self):
        return '<User %r>' % self.username

    class Meta:
        db_table = 'users'
        ordering = ('-id',)


class Role(models.Model, ModelMixin):
    name = models.CharField(max_length=50)
    desc = models.CharField(max_length=255, null=True)
    page_perms = models.JSONField(default=dict)
    deploy_perms = models.JSONField(default=dict)
    group_perms = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    # 与其他业务模型保持一致记录创建人；存量角色无此信息，故允许为空。
    created_by = models.ForeignKey(
        User, models.PROTECT, related_name='+', null=True, blank=True)

    def get_page_perms(self):
        perms = {}
        for module, pages in load_json(self.page_perms, {}).items():
            if not isinstance(module, str) or not isinstance(pages, dict):
                continue
            perms[module] = {
                page: [action for action in actions if isinstance(action, str) and action]
                for page, actions in pages.items()
                if isinstance(page, str) and isinstance(actions, list)
            }
        return perms

    def get_deploy_perms(self):
        perms = load_json(self.deploy_perms, {})
        return {key: permission_ids(perms[key]) for key in ('apps', 'envs') if key in perms}

    def get_group_perms(self):
        return permission_ids(load_json(self.group_perms, []))

    def to_dict(self, *args, **kwargs):
        tmp = super().to_dict(*args, **kwargs)
        for field in ('page_perms', 'deploy_perms', 'group_perms'):
            if field in tmp:
                tmp[field] = getattr(self, f'get_{field}')()
        tmp['used'] = self.user_set.filter(is_deleted=False).count()
        return tmp

    def add_deploy_perm(self, target, value):
        perms = {'apps': [], 'envs': []}
        perms.update(self.get_deploy_perms())
        perms[target].append(value)
        self.deploy_perms = perms
        self.save()

    def clear_perms_cache(self):
        for item in self.user_set.all():
            item.set_perms_cache()

    def __repr__(self):
        return '<Role name=%r>' % self.name

    class Meta:
        db_table = 'roles'
        ordering = ('-id',)


class History(models.Model, ModelMixin):
    username = models.CharField(max_length=100, null=True)
    type = models.CharField(max_length=20, default='default')
    ip = models.CharField(max_length=50)
    agent = models.CharField(max_length=255, null=True)
    message = models.CharField(max_length=255, null=True)
    is_success = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'login_histories'
        ordering = ('-id',)
