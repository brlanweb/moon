import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.account.models import Role, User
from apps.account.views import RoleView, login


@override_settings(CACHES={'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'account-compat-tests',
}})
class PermissionCompatibilityTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User(id=987, username='compat-user')
        self.roles = self.enterContext(patch.object(User, 'roles'))
        self.apps = self.enterContext(patch.object(User, 'app_set'))
        self.apps.all.return_value = [SimpleNamespace(id=9)]

    def test_native_and_legacy_permissions(self):
        for encode in (lambda x: x, json.dumps, lambda x: json.dumps(json.dumps(x))):
            with self.subTest(encode=encode):
                cache.clear()
                self.roles.all.return_value = [Role(
                    page_perms=encode({'host': {'host': ['view', 'edit']}}),
                    deploy_perms=encode({'apps': [1, 2], 'envs': [3]}),
                    group_perms=encode([4, 5]),
                )]
                self.assertEqual(self.user.page_perms, {'host.host.view', 'host.host.edit'})
                self.assertEqual(self.user.deploy_perms, {'apps': {1, 2, 9}, 'envs': {3}})
                self.assertEqual(set(self.user.group_perms), {4, 5})
                self.assertFalse(self.user.has_perms(['account.role.edit']))

    def test_malformed_top_level_permissions_fail_closed(self):
        for value in (None, '', 'not json', 'null', 'true', 42, True, b'\xff', '"not json"'):
            with self.subTest(value=value):
                cache.clear()
                self.roles.all.return_value = [Role(
                    page_perms=value, deploy_perms=value, group_perms=value)]
                self.assertEqual(self.user.page_perms, set())
                self.assertEqual(self.user.deploy_perms, {'apps': {9}, 'envs': set()})
                self.assertEqual(self.user.group_perms, [])

    def test_nested_invalid_values_do_not_grant_permissions(self):
        self.roles.all.return_value = [Role(
            page_perms={'bad': [], 'host': {'bad': 'view', 'none': None,
                                          'host': ['view', {}, True, ['edit']]},
                        'other': {'bad': {'view': True}}},
            deploy_perms={'apps': [1, True, 2.0, {}, [], None], 'envs': '123'},
            group_perms=[4, True, 5.0, {}, [], None],
        )]
        self.assertEqual(self.user.page_perms, {'host.host.view'})
        self.assertEqual(self.user.deploy_perms, {'apps': {1, 9}, 'envs': set()})
        self.assertEqual(self.user.group_perms, [4])

    def test_wrong_container_types_fail_closed(self):
        self.roles.all.return_value = [Role(page_perms=[], deploy_perms=[], group_perms={'1': True})]
        self.assertEqual(self.user.page_perms, set())
        self.assertEqual(self.user.deploy_perms, {'apps': {9}, 'envs': set()})
        self.assertEqual(self.user.group_perms, [])

    def test_role_serialization_normalizes_legacy_values_and_keeps_audit(self):
        role = Role(id=2, created_by=self.user, page_perms=json.dumps({'host': {'host': ['view']}}),
                    deploy_perms=json.dumps({'apps': [1]}), group_perms=json.dumps([4]))
        with patch.object(Role, 'user_set') as users:
            users.filter.return_value.count.return_value = 1
            data = role.to_dict()
            self.assertEqual(data['page_perms'], {'host': {'host': ['view']}})
            self.assertEqual(data['deploy_perms'], {'apps': [1]})
            self.assertEqual(data['group_perms'], [4])
            self.assertEqual(data['created_by_id'], self.user.id)
            self.assertEqual(data['used'], 1)
            self.assertNotIn('group_perms', role.to_dict(selects=('name',)))
            self.assertNotIn('page_perms', role.to_dict(excludes=('page_perms',)))

    def test_add_deploy_permission_handles_legacy_and_corrupt_lists(self):
        for source in (json.dumps(json.dumps({'apps': [1], 'envs': [2]})),
                       {'apps': [1], 'envs': None}):
            with self.subTest(source=source), patch.object(Role, 'save') as save:
                role = Role(deploy_perms=source)
                role.add_deploy_perm('apps', 3)
                role.add_deploy_perm('envs', 4)
                self.assertEqual(role.deploy_perms['apps'], [1, 3])
                self.assertIn(4, role.deploy_perms['envs'])
                self.assertEqual(save.call_count, 2)

    def test_role_creation_retains_local_created_by(self):
        request = RequestFactory().post('/account/role/', data=json.dumps({'name': 'ops'}),
                                        content_type='application/json')
        request.user = self.user
        with patch.object(Role.objects, 'create', return_value=Role()) as create:
            response = RoleView().post(request)
        self.assertFalse(json.loads(response.content)['error'])
        self.assertIs(create.call_args.kwargs['created_by'], self.user)

    def test_multiple_roles_union_and_cache_revocation(self):
        first = Role(page_perms={'host': {'host': ['view']}}, deploy_perms={'apps': [1]}, group_perms=[4])
        second = Role(page_perms=json.dumps({'host': {'host': ['edit']}}),
                      deploy_perms=json.dumps({'envs': [2]}), group_perms=json.dumps([5]))
        self.roles.all.return_value = [first, second]
        self.assertEqual(self.user.page_perms, {'host.host.view', 'host.host.edit'})
        self.assertEqual(self.user.deploy_perms, {'apps': {1, 9}, 'envs': {2}})
        self.assertEqual(set(self.user.group_perms), {4, 5})
        first.page_perms = {}
        second.page_perms = {}
        with patch.object(Role, 'user_set') as users:
            users.all.return_value = [self.user]
            first.clear_perms_cache()
        self.assertEqual(self.user.page_perms, set())

    def test_valid_bytes_and_numeric_string_ids_remain_compatible(self):
        self.roles.all.return_value = [Role(
            page_perms=b'{"host": {"host": ["view"]}}',
            deploy_perms=bytearray(b'{"apps": ["12"]}'), group_perms=b'["4"]',
        )]
        self.assertEqual(self.user.page_perms, {'host.host.view'})
        self.assertEqual(self.user.deploy_perms, {'apps': {'12', 9}, 'envs': set()})
        self.assertEqual(self.user.group_perms, ['4'])

    def test_non_admin_cannot_create_role_via_dispatch(self):
        request = RequestFactory().post('/account/role/', data=json.dumps({'name': 'ops'}),
                                        content_type='application/json')
        request.user = self.user
        with patch.object(Role.objects, 'create') as create:
            response = RoleView.as_view()(request)
        self.assertTrue(json.loads(response.content)['error'])
        create.assert_not_called()

    def test_non_admin_login_returns_role_permissions(self):
        self.user.password_hash = User.make_password('TestingPass123')
        self.roles.all.return_value = [Role(page_perms={'host': {'host': ['view']}})]
        request = RequestFactory().post('/account/login/', data=json.dumps({
            'username': self.user.username, 'password': 'TestingPass123',
        }), content_type='application/json', HTTP_USER_AGENT='compat-test')
        with patch.object(User.objects, 'filter') as users, \
                patch.object(User, 'save'), \
                patch('apps.account.views.History.objects.create'), \
                patch('apps.account.views.AppSetting.get_default', side_effect=lambda k, d=None: d):
            users.return_value.first.return_value = self.user
            data = json.loads(login(request).content)
        self.assertFalse(data['error'])
        self.assertEqual(data['data']['permissions'], ['host.host.view'])
        self.assertFalse(data['data']['is_supper'])
