from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.database.policy import (
    PolicyViolation,
    classify_command,
    enforce_command_policy,
)


class FakeConfirmationRedis:
    def __init__(self):
        self.values = {}
        self.lock = Lock()

    def set(self, key, value, ex=None, nx=False):
        with self.lock:
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

    def getdel(self, key):
        with self.lock:
            return self.values.pop(key, None)

    def eval(self, script, numkeys, key):
        return self.getdel(key)


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

    def test_only_copy_to_stdout_is_read_only(self):
        for command in (
                'COPY users TO STDOUT',
                'COPY (SELECT * FROM users) TO STDOUT'):
            with self.subTest(command=command):
                result = classify_command('postgresql', command)

                self.assertIs(result.read_only, True)
                self.assertIs(result.has_data_change, False)

    def test_copy_with_server_side_effect_is_data_change(self):
        for command in (
                'COPY users FROM STDIN',
                "COPY users TO '/tmp/users.csv'",
                "COPY users TO PROGRAM 'gzip > /tmp/users.gz'"):
            with self.subTest(command=command):
                result = classify_command('postgresql', command)

                self.assertIs(result.read_only, False)
                self.assertIs(result.has_data_change, True)

    def test_select_into_forms_are_data_changes(self):
        for database_type, command in (
                ('postgresql', 'SELECT * INTO archived_users FROM users'),
                ('mysql', "SELECT * FROM users INTO OUTFILE '/tmp/users.csv'"),
                ('mysql', "SELECT * FROM users INTO DUMPFILE '/tmp/users.bin'")):
            with self.subTest(database_type=database_type, command=command):
                result = classify_command(database_type, command)

                self.assertIs(result.read_only, False)
                self.assertIs(result.has_data_change, True)

    def test_mysql_executable_comment_is_conservatively_a_data_change(self):
        for database_type, command in (
                ('mysql', '/*!40101 DELETE FROM users */'),
                ('mysql', 'SELECT 1; /*!50000 DROP TABLE users */'),
                ('mariadb', '/*!40101 DELETE FROM users */'),
                ('mariadb', '/*M!100100 DELETE FROM users */')):
            with self.subTest(database_type=database_type, command=command):
                result = classify_command(database_type, command)

                self.assertIs(result.read_only, False)
                self.assertIs(result.has_data_change, True)
                self.assertIs(result.known, False)


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
    def setUp(self):
        self.redis = FakeConfirmationRedis()
        redis_patch = patch(
            'apps.database.policy.get_redis_connection',
            return_value=self.redis,
            create=True,
        )
        redis_patch.start()
        self.addCleanup(redis_patch.stop)

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

    def test_normal_connection_allows_unknown_sql_and_redis_commands(self):
        commands = (
            (self.connection(), 'FUTURE COMMAND'),
            (self.connection(type='redis'), 'JSON.FUTURE key value'),
        )

        for connection, command in commands:
            with self.subTest(database_type=connection.type, command=command):
                decision = enforce_command_policy(connection, 7, command)

                self.assertIs(decision.requires_confirmation, False)

    def test_production_unknown_command_requires_confirmation(self):
        commands = (
            (self.connection(environment='production'), 'FUTURE COMMAND'),
            (self.connection(type='redis', environment='production'), 'JSON.FUTURE key value'),
        )

        for connection, command in commands:
            with self.subTest(database_type=connection.type, command=command):
                decision = enforce_command_policy(connection, 7, command)

                self.assertIs(decision.requires_confirmation, True)
                self.assertTrue(decision.confirmation_token)

    def test_production_potentially_mutating_redis_commands_require_confirmation(self):
        connection = self.connection(type='redis', environment='production')

        for command in (
                'EVAL "return redis.call(\'SET\', KEYS[1], ARGV[1])" 1 key value',
                'EVALSHA abcdef 1 key',
                'FCALL library.function 1 key',
                'JSON.SET profile $ {}'):
            with self.subTest(command=command):
                decision = enforce_command_policy(connection, 7, command)

                self.assertIs(decision.requires_confirmation, True)

    def test_read_only_connection_rejects_potentially_mutating_redis_commands(self):
        connection = self.connection(type='redis', read_only=True)

        for command in (
                'EVAL "return 1" 0',
                'EVALSHA abcdef 0',
                'FCALL library.function 0',
                'JSON.SET profile $ {}'):
            with self.subTest(command=command):
                with self.assertRaisesRegex(PolicyViolation, '只读连接'):
                    enforce_command_policy(connection, 7, command)

    def test_copy_to_program_is_rejected_in_every_environment(self):
        command = "COPY users TO PROGRAM 'gzip > /tmp/users.gz'"

        for environment in ('normal', 'production'):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(PolicyViolation, 'COPY TO PROGRAM'):
                    enforce_command_policy(
                        self.connection(type='postgresql', environment=environment),
                        7,
                        command,
                    )

    def test_production_copy_to_file_requires_confirmation(self):
        decision = enforce_command_policy(
            self.connection(type='postgresql', environment='production'),
            7,
            "COPY users TO '/tmp/users.csv'",
        )

        self.assertIs(decision.requires_confirmation, True)

    def test_production_read_does_not_require_confirmation(self):
        decision = enforce_command_policy(
            self.connection(environment='production'), 7, 'SELECT * FROM users')

        self.assertIs(decision.requires_confirmation, False)
        self.assertIsNone(decision.confirmation_token)

    def test_production_known_ddl_does_not_require_confirmation(self):
        connection = self.connection(environment='production')

        for command in (
                'CREATE TABLE audit_log (id INT)',
                'ALTER TABLE audit_log ADD COLUMN message TEXT',
                'DROP TABLE audit_log',
                'TRUNCATE TABLE audit_log'):
            with self.subTest(command=command):
                decision = enforce_command_policy(connection, 7, command)

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

    def test_confirmation_token_cannot_be_replayed(self):
        connection = self.connection(environment='production')
        command = 'UPDATE users SET active = 1'
        first = enforce_command_policy(connection, 7, command)

        enforce_command_policy(
            connection, 7, command, confirmation_token=first.confirmation_token)

        with self.assertRaisesRegex(PolicyViolation, '确认令牌无效或已过期'):
            enforce_command_policy(
                connection, 7, command,
                confirmation_token=first.confirmation_token,
            )

    def test_confirmation_token_is_consumed_atomically(self):
        connection = self.connection(environment='production')
        command = 'DELETE FROM users WHERE id = 3'
        first = enforce_command_policy(connection, 7, command)

        def consume():
            try:
                enforce_command_policy(
                    connection, 7, command,
                    confirmation_token=first.confirmation_token,
                )
                return True
            except PolicyViolation:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: consume(), range(2)))

        self.assertEqual(sorted(outcomes), [False, True])

    def test_confirmation_token_is_bound_to_effective_database(self):
        connection = self.connection(environment='production')
        command = 'UPDATE users SET active = 1'
        first = enforce_command_policy(connection, 7, command, database='analytics')

        with self.assertRaisesRegex(PolicyViolation, '确认令牌无效或已过期'):
            enforce_command_policy(
                connection,
                7,
                command,
                confirmation_token=first.confirmation_token,
                database='archive',
            )

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
