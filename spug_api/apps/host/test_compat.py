import json
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.account.models import Role, User
from apps.host.group import GroupView


class GroupPermissionCompatibilityTests(SimpleTestCase):
    def delete_group(self, perms):
        request = RequestFactory().delete('/host/group/?id=12')
        request.user = User(id=1, is_supper=True)
        group = Mock(id=12)
        group.hosts.exists.return_value = False
        with patch('apps.host.group.Group.objects') as groups, \
                patch('apps.host.group.Role.objects') as roles:
            groups.filter.return_value.first.return_value = group
            groups.filter.return_value.exists.return_value = False
            groups.exclude.return_value.exists.return_value = True
            roles.all.return_value = [Role(name='ops', group_perms=perms)]
            roles.filter.return_value.first.return_value = None
            response = GroupView().delete(request)
            roles.filter.assert_not_called()
        return json.loads(response.content), group

    def test_referenced_groups_cannot_be_deleted_without_json_regexp(self):
        for perms in ([12], ['12'], json.dumps([12]), json.dumps(json.dumps([12]))):
            with self.subTest(perms=perms):
                data, group = self.delete_group(perms)
                self.assertTrue(data['error'])
                self.assertIn('ops', data['error'])
                group.delete.assert_not_called()

    def test_other_ids_and_corrupt_values_do_not_match(self):
        for perms in ([112], [2], [], None, 'broken', {'12': True}, [True, {}, []]):
            with self.subTest(perms=perms):
                data, group = self.delete_group(perms)
                self.assertFalse(data['error'])
                group.delete.assert_called_once_with()
