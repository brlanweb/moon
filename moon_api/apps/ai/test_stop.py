import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, RequestFactory
from apps.ai.engine import AgentRunner, ChatStopped, _drive, _stop_chat
from apps.ai.views import session_stop


class StopEndpointTests(SimpleTestCase):
    def request(self, turn=3, allowed=True):
        request = RequestFactory().post('/api/ai/session/stop/',
                                        {'id': 7, 'turn': turn}, content_type='application/json')
        request.user = SimpleNamespace(has_perms=lambda _codes: allowed)
        return request

    @patch('apps.ai.views.ai_stream.request_stop')
    @patch('apps.ai.views.AgentSession.objects.filter')
    def test_stop_is_scoped_to_current_turn_without_premature_idle(self, sessions, stop):
        session = SimpleNamespace(id=7, turn=3, source='manual', status='running')
        sessions.return_value.first.return_value = session
        result = json.loads(session_stop(self.request()).content)
        self.assertTrue(result['data']['stopping'])
        stop.assert_called_once_with(7, 3)
        self.assertEqual(session.status, 'running')

    @patch('apps.ai.views.ai_stream.request_stop')
    @patch('apps.ai.views.AgentSession.objects.filter')
    def test_late_stop_never_cancels_next_turn(self, sessions, stop):
        sessions.return_value.first.return_value = SimpleNamespace(
            id=7, turn=4, source='manual', status='running')
        result = json.loads(session_stop(self.request()).content)
        self.assertFalse(result['data']['stopping'])
        stop.assert_not_called()

    @patch('apps.ai.views.ai_stream.request_stop')
    @patch('apps.ai.views.AgentSession.objects.filter')
    def test_monitor_task_is_not_cancelled(self, sessions, stop):
        sessions.return_value.first.return_value = SimpleNamespace(
            id=7, turn=3, source='monitor', status='running')
        self.assertTrue(json.loads(session_stop(self.request()).content)['error'])
        stop.assert_not_called()

    @patch('apps.ai.views.ai_stream.request_stop')
    def test_permission_required(self, stop):
        self.assertTrue(json.loads(session_stop(self.request(allowed=False)).content)['error'])
        stop.assert_not_called()


class StopEngineTests(SimpleTestCase):
    @patch('apps.ai.stream.stop_requested', return_value=True)
    def test_stop_prevents_ssh_dispatch(self, _stop):
        runner = AgentRunner(SimpleNamespace(id=7, turn=3))
        ssh = Mock()
        with self.assertRaises(ChatStopped):
            runner.exec_command(ssh, 'echo test')
        ssh.exec_command_raw.assert_not_called()

    def test_can_cancel_while_waiting_for_first_token(self):
        runner = Mock(unattended=False)
        runner.check_stop.side_effect = [None, None, ChatStopped()]
        cleaned = []

        async def waiting(*_args):
            try:
                await asyncio.sleep(60)
            finally:
                cleaned.append(True)

        async def exercise():
            with patch('apps.ai.engine._drive_run', side_effect=waiting):
                with self.assertRaises(ChatStopped):
                    await asyncio.wait_for(_drive(None, runner, None, '', None, None, 1), 2)
        asyncio.run(exercise())
        self.assertEqual(cleaned, [True])

    def test_normal_answer_does_not_get_cancelled(self):
        runner = Mock(unattended=False)
        async def completed(*_args):
            return 'result', False
        with patch('apps.ai.engine._drive_run', side_effect=completed):
            self.assertEqual(asyncio.run(_drive(None, runner, None, '', None, None, 1)), ('result', False))

    def test_stop_retains_partial_answer_and_releases_session_after_settling(self):
        session = Mock(id=7, turn=3, mode='chat')
        session.records.filter.return_value.order_by.return_value = [
            SimpleNamespace(kind='question', content='hello')]
        runner = AgentRunner(session)
        runner.partial_text = 'partial answer'
        runner.load_history = Mock(return_value=[])
        runner.save_history = Mock()
        runner.record = Mock()
        runner.emit = Mock()
        _stop_chat(runner)
        self.assertEqual(session.status, 'idle')
        self.assertIsNone(session.pending)
        self.assertIn('partial answer', runner.record.call_args.args[1])
        self.assertTrue(runner.record.call_args.kwargs['extra']['stopped'])
        self.assertEqual(len(runner.save_history.call_args.args[0]), 2)
        runner.emit.assert_called_once_with('done', status='idle', stopped=True)
