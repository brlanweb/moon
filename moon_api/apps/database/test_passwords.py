from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.database.client import DatabaseClientError, test_connection as check_connection
from apps.database.models import DatabaseConnection


@override_settings(SECRET_KEY='password-regression-test-key')
class StoredPasswordTests(SimpleTestCase):
    def test_reopening_connection_preserves_encrypted_password(self):
        connection = DatabaseConnection(type='mysql')
        connection.set_password('example-test-password')
        reopened = DatabaseConnection(type='mysql', password=connection.password)
        self.assertEqual(reopened.get_password(), 'example-test-password')
        self.assertNotIn('password', reopened.to_view())

    def test_wrong_key_never_falls_back_to_ciphertext(self):
        connection = DatabaseConnection(type='mysql')
        connection.set_password('example-test-password')
        with override_settings(SECRET_KEY='different-test-key'):
            with self.assertRaisesMessage(ValueError, '重新输入密码并保存'):
                connection.get_password()

    @patch('pymysql.connect')
    def test_undecryptable_password_is_rejected_before_database_login(self, connect):
        connection = DatabaseConnection(type='mysql')
        connection.set_password('example-test-password')
        with override_settings(SECRET_KEY='different-test-key'):
            with self.assertRaisesMessage(DatabaseClientError, '无法解密'):
                check_connection(connection)
        connect.assert_not_called()

    def test_reentering_password_repairs_connection_under_current_key(self):
        connection = DatabaseConnection(type='mysql')
        with override_settings(SECRET_KEY='previous-test-key'):
            connection.set_password('example-test-password')
        connection.set_password('replacement-test-password')
        reopened = DatabaseConnection(password=connection.password)
        self.assertEqual(reopened.get_password(), 'replacement-test-password')

    def test_legacy_plaintext_and_empty_password_remain_supported(self):
        self.assertEqual(DatabaseConnection(password='legacy-test').get_password(), 'legacy-test')
        connection = DatabaseConnection()
        connection.set_password('')
        self.assertEqual(connection.get_password(), '')
