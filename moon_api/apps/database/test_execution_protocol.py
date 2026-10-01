"""Preflight failures must be distinguishable from a lost execution response."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory
from apps.database.views import run_command, cancel_command
from apps.database.executions import ExecutionError
from apps.database.policy import PolicyViolation
from apps.database.client import DatabaseClientError
from apps.database.test_executions import execution_id


class ExecutionProtocolTests(SimpleTestCase):
    def setUp(self):
        self.connection = SimpleNamespace(id=23, type='mysql', database='app',
                                          environment='normal', read_only=False)
        self.user = SimpleNamespace(id=7, has_perms=lambda _: True)

    def request(self, payload, method='post'):
        factory = RequestFactory()
        request = (factory.get('/api/database/cancel/', payload) if method == 'get' else
                   factory.post('/api/database/execute/', json.dumps(payload), content_type='application/json'))
        request.user = self.user
        return request

    def payload(self, **changes):
        return dict(id=23, command='SELECT 1', execution_id=execution_id(), **changes)

    def assert_rejected(self, response, status='not_started'):
        body = json.loads(response.content)
        self.assertTrue(body['error'])
        self.assertEqual(body.get('execution_status'), status)

    @patch('apps.database.views.execute')
    def test_both_permissions_are_structured_before_any_work(self, execute):
        for perm in ('database.query.do', 'database.connection.view'):
            with self.subTest(perm=perm):
                self.user.has_perms = lambda perms: perm not in perms
                self.assert_rejected(run_command(self.request(self.payload())))
        execute.assert_not_called()

    @patch('apps.database.views.execute')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_all_parameter_rejections_are_not_started(self, objects, execute):
        objects.return_value.first.return_value = self.connection
        cases = [None, [], ['id'], 1, 'text', {}, {'id': 'bad', 'command': 'SELECT 1'},
                 {'id': 23}, {'id': 23, 'command': ''}, {'id': 23, 'command': '   '},
                 {'id': 23, 'command': 42}, {'id': 23, 'command': ['SELECT 1']},
                 self.payload(database=' '), self.payload(database='x' * 129),
                 self.payload(database=[]), self.payload(confirmation_token=[])]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assert_rejected(run_command(self.request(payload)))
        execute.assert_not_called()

    @patch('apps.database.views.execute')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_missing_connection_is_not_started(self, objects, execute):
        objects.return_value.first.return_value = None
        self.assert_rejected(run_command(self.request(self.payload())))
        execute.assert_not_called()

    @patch('apps.database.views.execute')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_invalid_execution_ids_are_not_started(self, objects, execute):
        objects.return_value.first.return_value = self.connection
        for eid in ('invalid', '1.bad', [], 123):
            payload = self.payload()
            payload['execution_id'] = eid
            with self.subTest(eid=eid):
                self.assert_rejected(run_command(self.request(payload)))
        execute.assert_not_called()

    @patch('apps.database.views.execute')
    @patch('apps.database.views.enforce_command_policy')
    @patch('apps.database.views.Registry')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_policy_and_registration_refusal_never_execute(self, objects, registry, policy, execute):
        objects.return_value.first.return_value = self.connection
        policy.side_effect = PolicyViolation('只读拒绝')
        self.assert_rejected(run_command(self.request(self.payload())))
        policy.side_effect = None
        policy.return_value.requires_confirmation = False
        registry.return_value.begin.side_effect = ExecutionError('注册表不可用')
        self.assert_rejected(run_command(self.request(self.payload())))
        execute.assert_not_called()

    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_status_and_cancel_rejections_have_no_not_started_claim(self, objects):
        for method in ('get', 'post'):
            for case in ('permission', 'missing', 'invalid'):
                with self.subTest(method=method, case=case):
                    self.user.has_perms = lambda _: case != 'permission'
                    objects.return_value.exists.return_value = case != 'missing'
                    payload = self.payload()
                    if case == 'invalid':
                        payload['execution_id'] = 'invalid'
                    self.assert_rejected(cancel_command(self.request(payload, method)), 'unavailable')

    @patch('apps.database.views.execute')
    @patch('apps.database.views.enforce_command_policy')
    @patch('apps.database.views.Registry')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_work_transport_loss_stays_unknown_and_registered(self, objects, registry, policy, execute):
        objects.return_value.first.return_value = self.connection
        policy.return_value.requires_confirmation = False
        error = DatabaseClientError('lost')
        error.execution_uncertain = True
        execute.side_effect = error
        body = json.loads(run_command(self.request(self.payload())).content)
        self.assertEqual(body['data']['status'], 'unknown')
        registry.return_value.finish.assert_not_called()

    def test_authentication_middleware_rejects_before_execution(self):
        from libs.middleware import AuthenticationMiddleware
        request = RequestFactory().post('/api/database/execute/', '{}', content_type='application/json')
        response = AuthenticationMiddleware(lambda r: None).process_request(request)
        self.assertEqual(response.status_code, 401)


    @patch('apps.database.views.execute')
    @patch('apps.database.views.enforce_command_policy', side_effect=ConnectionError('confirmation store offline'))
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_confirmation_store_failure_is_known_not_started(self, objects, policy, execute):
        objects.return_value.first.return_value = self.connection
        request = self.request(self.payload())
        try:
            response = run_command(request)
        except Exception as error:
            from libs.middleware import HandleExceptionMiddleware
            response = HandleExceptionMiddleware(lambda r: None).process_exception(request, error)
        self.assert_rejected(response)
        execute.assert_not_called()

    @patch('apps.database.views.execute')
    @patch('apps.database.views.enforce_command_policy')
    @patch('apps.database.views.Registry')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_unknown_work_records_retryable_cancellation_failure(self, objects, registry, policy, execute):
        objects.return_value.first.return_value = self.connection
        policy.return_value.requires_confirmation = False
        error = DatabaseClientError('lost')
        error.execution_uncertain = True
        execute.side_effect = error
        body = json.loads(run_command(self.request(self.payload())).content)
        self.assertEqual(body['data']['status'], 'unknown')
        self.assertIsNotNone(registry.return_value.update.call_args)
        self.assertEqual(registry.return_value.update.call_args.kwargs['cancel_status'], 'failed')
        registry.return_value.finish.assert_not_called()

    @patch('apps.database.views.execute')
    @patch('apps.database.views.enforce_command_policy')
    @patch('apps.database.views.Registry')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_registry_failure_after_dispatch_never_claims_not_started(self, objects, registry, policy, execute):
        objects.return_value.first.return_value = self.connection
        policy.return_value.requires_confirmation = False
        execute.return_value = {'columns': [], 'rows': [], 'affected': 1}
        registry.return_value.finish.side_effect = ExecutionError('offline')
        registry.return_value.update.side_effect = ExecutionError('offline')
        body = json.loads(run_command(self.request(self.payload())).content)
        self.assertEqual(body['data']['status'], 'unknown')
        self.assertNotIn('execution_status', body)

    @patch('apps.database.views.execute')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_malformed_json_and_invalid_confirmation_are_preflight_rejections(self, objects, execute):
        objects.return_value.first.return_value = self.connection
        self.connection.environment = 'production'
        req = RequestFactory().post('/api/database/execute/', '{', content_type='application/json')
        req.user = self.user
        self.assert_rejected(run_command(req))
        payload = self.payload(confirmation_token='bad-token')
        payload['command'] = 'DELETE FROM orders'
        self.assert_rejected(run_command(self.request(payload)))
        execute.assert_not_called()


    @patch('apps.database.views.execute', side_effect=DatabaseClientError('query rejected'))
    @patch('apps.database.views.enforce_command_policy')
    @patch('apps.database.views.Registry')
    @patch('apps.database.views.DatabaseConnection.objects.filter')
    def test_legacy_execution_errors_keep_error_envelope_without_not_started_claim(self, objects, registry, policy, execute):
        objects.return_value.first.return_value = self.connection
        policy.return_value.requires_confirmation = False
        body = json.loads(run_command(self.request({'id': 23, 'command': 'SELECT 1'})).content)
        self.assertIn('query rejected', body['error'])
        self.assertEqual(body['execution_status'], 'failed')
        registry.return_value.finish.assert_called_once_with('failed')
