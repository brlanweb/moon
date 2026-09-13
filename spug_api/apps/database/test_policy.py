from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.database.policy import (
    PolicyViolation,
    classify_command,
    enforce_command_policy,
)


class SqlClassificationTests(SimpleTestCase):
    def test_ignores_comments_and_classifies_every_statement(self):
        result = classify_command(
            'mysql',
            '-- inspect first\nSELECT * FROM users; /* then change */ UPDATE users SET active = 1;',
        )

        self.assertEqual(result.statement_types, ('SELECT', 'UPDATE'))
        self.assertIs(result.read_only, False)
        self.assertIs(result.has_data_change, True)

    def test_classifies_read_only_cte_by_its_outer_statement(self):
        result = classify_command(
            'postgresql',
            'WITH recent AS (SELECT * FROM audit_log) SELECT * FROM recent',
        )

        self.assertEqual(result.statement_types, ('SELECT',))
        self.assertIs(result.read_only, True)
        self.assertIs(result.has_data_change, False)

    def test_detects_data_change_inside_cte(self):
        result = classify_command(
            'postgresql',
            'WITH removed AS (DELETE FROM sessions RETURNING *) SELECT * FROM removed',
        )

        self.assertEqual(result.statement_types, ('SELECT',))
        self.assertIs(result.read_only, False)
        self.assertIs(result.has_data_change, True)

    def test_copy_direction_distinguishes_read_from_write(self):
        reads = (
            classify_command('postgresql', 'COPY users TO STDOUT'),
            classify_command(
                'postgresql', 'COPY (SELECT * FROM users) TO STDOUT'),
        )
        write = classify_command('postgresql', 'COPY users FROM STDIN')

        for read in reads:
            self.assertIs(read.read_only, True)
            self.assertIs(read.has_data_change, False)
        self.assertIs(write.read_only, False)
        self.assertIs(write.has_data_change, True)


class RedisClassificationTests(SimpleTestCase):
    def test_explicit_read_command_is_read_only(self):
        result = classify_command('redis', 'GET session:1')

        self.assertEqual(result.statement_types, ('GET',))
        self.assertIs(result.read_only, True)
        self.assertIs(result.known, True)

    def test_write_command_is_not_read_only(self):
        for command in ('SET session:1 value', 'TOUCH session:1'):
            with self.subTest(command=command):
                result = classify_command('redis', command)

                self.assertIs(result.read_only, False)
                self.assertIs(result.has_data_change, True)
                self.assertIs(result.known, True)

    def test_unknown_command_is_not_treated_as_read_only(self):
        result = classify_command('redis', 'FUTURE.READ key')

        self.assertEqual(result.statement_types, ('FUTURE.READ',))
        self.assertIs(result.read_only, False)
        self.assertIs(result.known, False)

    def test_read_only_subcommand_allowlist_does_not_allow_memory_purge(self):
        usage = classify_command('redis', 'MEMORY USAGE session:1')
        purge = classify_command('redis', 'MEMORY PURGE')

        self.assertIs(usage.read_only, True)
        self.assertIs(usage.known, True)
        self.assertIs(purge.read_only, False)
        self.assertIs(purge.has_data_change, True)


class CommandPolicyTests(SimpleTestCase):
    def connection(self, **changes):
        values = {
            'id': 23,
            'type': 'mysql',
            'read_only': False,
            'environment': 'normal',
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_read_only_connection_rejects_sql_write(self):
        with self.assertRaisesRegex(PolicyViolation, '只读连接'):
            enforce_command_policy(
                self.connection(read_only=True), 7, 'UPDATE users SET active = 1')

    def test_read_only_connection_rejects_unknown_redis_command(self):
        with self.assertRaisesRegex(PolicyViolation, '只读连接'):
            enforce_command_policy(
                self.connection(type='redis', read_only=True), 7, 'FUTURE.READ key')

    def test_normal_connection_allows_unknown_command(self):
        decision = enforce_command_policy(self.connection(), 7, 'VACUUM users')

        self.assertIs(decision.requires_confirmation, False)

    def test_production_read_does_not_require_confirmation(self):
        decision = enforce_command_policy(
            self.connection(environment='production'), 7, 'SELECT * FROM users')

        self.assertIs(decision.requires_confirmation, False)
        self.assertIsNone(decision.confirmation_token)

    def test_production_data_change_returns_bound_confirmation_token(self):
        decision = enforce_command_policy(
            self.connection(environment='production'), 7, 'UPDATE users SET active = 1')

        self.assertIs(decision.requires_confirmation, True)
        self.assertTrue(decision.confirmation_token)
        self.assertEqual(decision.statement_types, ('UPDATE',))

    def test_valid_confirmation_token_allows_matching_command(self):
        connection = self.connection(environment='production')
        command = 'UPDATE users SET active = 1'
        first = enforce_command_policy(connection, 7, command)

        confirmed = enforce_command_policy(
            connection, 7, command, confirmation_token=first.confirmation_token)

        self.assertIs(confirmed.requires_confirmation, False)

    def test_tampered_confirmation_token_is_rejected(self):
        connection = self.connection(environment='production')
        command = 'DELETE FROM users WHERE id = 3'
        first = enforce_command_policy(connection, 7, command)

        with self.assertRaisesRegex(PolicyViolation, '确认令牌无效或已过期'):
            enforce_command_policy(
                connection, 7, command,
                confirmation_token=f'{first.confirmation_token}tampered',
            )

    def test_confirmation_token_is_rejected_after_sixty_seconds(self):
        connection = self.connection(environment='production')
        command = "INSERT INTO audit_log(message) VALUES ('changed')"
        with patch('django.core.signing.time.time', return_value=1000):
            first = enforce_command_policy(connection, 7, command)

        with patch('django.core.signing.time.time', return_value=1061):
            with self.assertRaisesRegex(PolicyViolation, '确认令牌无效或已过期'):
                enforce_command_policy(
                    connection, 7, command,
                    confirmation_token=first.confirmation_token,
                )

    def test_confirmation_token_rejects_user_connection_and_command_mismatch(self):
        connection = self.connection(environment='production')
        command = 'UPDATE users SET active = 1'
        first = enforce_command_policy(connection, 7, command)
        mismatches = (
            (connection, 8, command),
            (self.connection(id=24, environment='production'), 7, command),
            (connection, 7, 'UPDATE users SET active = 0'),
        )

        for mismatched_connection, user_id, mismatched_command in mismatches:
            with self.subTest(user_id=user_id, connection_id=mismatched_connection.id,
                              command=mismatched_command):
                with self.assertRaisesRegex(PolicyViolation, '确认令牌无效或已过期'):
                    enforce_command_policy(
                        mismatched_connection, user_id, mismatched_command,
                        confirmation_token=first.confirmation_token,
                    )
