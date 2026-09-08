# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""命令风险规则与 Docker 作用域工具的回归测试。

修复模式允许变更服务器，但服务器上通常还跑着其他项目，
一旦让模型自行执行批量/跨项目的破坏性命令，损失不可恢复。
这里锁定「必须拦截」与「不得误伤」两类样本。
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from apps.ai.risk import check_command
from apps.ai.engine import build_agent, _make_docker_tools
from apps.ai.docker_tools import DockerTargetOperator, limit_output
from apps.ai.models import AgentSession


class DockerAgentSessionModelTests(SimpleTestCase):
    def test_target_scope_is_an_optional_persisted_field(self):
        field = AgentSession._meta.get_field('target_scope')

        self.assertTrue(field.null)


class DockerAgentToolIsolationTests(SimpleTestCase):
    @patch('apps.ai.engine._PydanticAgent')
    @patch('apps.ai.engine._build_model', return_value=(object(), []))
    @patch('apps.ai.engine._make_mcp_tools')
    @patch('apps.ai.engine._make_skill_tool')
    @patch('apps.ai.engine._make_ssh_tool')
    @patch('apps.ai.engine._make_docker_tools')
    def test_docker_session_registers_only_scoped_tools(
            self, docker_tools, ssh_tool, skill_tool, mcp_tools, _model, agent):
        scoped = object()
        docker_tools.return_value = [scoped]
        runner = SimpleNamespace(session=SimpleNamespace(target_scope='{"version": 1}'))

        build_agent(runner, 'instructions')

        self.assertEqual(agent.call_args.kwargs['tools'], [scoped])
        ssh_tool.assert_not_called()
        skill_tool.assert_not_called()
        mcp_tools.assert_not_called()

    def test_diagnose_docker_session_has_no_write_tools(self):
        runner = SimpleNamespace(
            session=SimpleNamespace(mode='diagnose', target_scope='{"version": 1}'))

        names = [tool.name for tool in _make_docker_tools(runner)]

        self.assertIn('docker_target_status', names)
        self.assertIn('docker_target_logs', names)
        self.assertNotIn('docker_target_restart', names)
        self.assertNotIn('docker_target_recover', names)

    @patch('apps.ai.engine._PydanticAgent')
    @patch('apps.ai.engine._build_model', return_value=(object(), []))
    @patch('apps.ai.engine._skill_hint', return_value='')
    @patch('apps.ai.engine._make_mcp_tools', return_value=[])
    @patch('apps.ai.engine._make_skill_tool', return_value=object())
    @patch('apps.ai.engine._make_ssh_tool', return_value=object())
    def test_regular_session_keeps_existing_tools(
            self, ssh_tool, skill_tool, _mcp, _hint, _model, agent):
        runner = SimpleNamespace(session=SimpleNamespace(target_scope=None))

        build_agent(runner, 'instructions')

        self.assertEqual(len(agent.call_args.kwargs['tools']), 2)
        ssh_tool.assert_called_once()
        skill_tool.assert_called_once()


class DockerTargetOperatorTests(SimpleTestCase):
    SCOPE = {
        'version': 1, 'kind': 'compose_service', 'project': 'demo',
        'workdir': '/opt/demo', 'config_files': ['/opt/demo/compose.yml'],
        'service': 'api', 'expected_replicas': 2,
        'config_hash': 'hash-1', 'can_recover_missing': True,
    }

    def test_log_output_is_limited_to_20_kib(self):
        output = 'x' * (25 * 1024)

        result = limit_output(output)

        self.assertLessEqual(len(result.encode('utf-8')), 20 * 1024 + 64)
        self.assertIn('已截断', result)

    @patch('apps.ai.docker_tools._exec', return_value=(0, 'restarted'))
    @patch('apps.ai.docker_tools.discover_all')
    def test_restart_only_operates_abnormal_scoped_container(self, discover, execute):
        discover.return_value = {
            'projects': [{
                'name': 'demo', 'workdir': '/opt/demo',
                'config_file': '/opt/demo/compose.yml',
                'config_files': ['/opt/demo/compose.yml'],
                'containers': [
                    {'name': 'demo-api-1', 'service': 'api', 'state': 'running',
                     'health': 'healthy', 'config_hash': 'hash-1'},
                    {'name': 'demo-api-2', 'service': 'api', 'state': 'running',
                     'health': 'unhealthy', 'config_hash': 'hash-1'},
                ],
            }],
            'standalone': [{'name': 'other', 'state': 'exited'}],
        }
        operator = DockerTargetOperator(object(), self.SCOPE)

        result = operator.restart()

        self.assertIn('demo-api-2', result)
        self.assertNotIn('demo-api-1', execute.call_args.args[1])
        self.assertEqual(execute.call_count, 1)

    @patch('apps.ai.docker_tools._exec')
    @patch('apps.ai.docker_tools.read_service_hash', return_value='changed')
    @patch('apps.ai.docker_tools.discover_all')
    def test_recover_rejects_compose_config_drift(self, discover, _hash, execute):
        discover.return_value = {
            'projects': [{
                'name': 'demo', 'workdir': '/opt/demo',
                'config_file': '/opt/demo/compose.yml',
                'config_files': ['/opt/demo/compose.yml'], 'containers': [],
            }],
            'standalone': [],
        }
        operator = DockerTargetOperator(object(), self.SCOPE)

        result = operator.recover()

        self.assertIn('配置哈希', result)
        execute.assert_not_called()


class CheckCommandTests(SimpleTestCase):
    # 会波及告警对象之外的服务或数据，修复模式必须拦下
    CROSS_SERVICE = [
        'docker system prune -af',
        'docker volume rm app_data',
        'docker rm -f $(docker ps -aq)',
        'docker compose -p new-api -f a.yml down --remove-orphans',
        'docker compose -f a.yml down -v',
        'mysql -e "drop database orders"',
        'mysql -e "truncate table users"',
        'find /data -name "*.log" -delete',
        'ls /data | xargs rm -rf',
        'rm -rf /var/lib/mysql',
        'apt-get purge nginx',
        'killall nginx',
    ]
    # 限定在单个目标上的常规修复操作，不应被误伤
    SCOPED_REPAIR = [
        'systemctl restart nginx',
        'docker restart new-api',
        'docker compose -p new-api -f /opt/new-api/compose.yaml up -d',
        'rm -f /tmp/new-api.lock',
        'journalctl -u nginx -n 100',
        'df -h',
    ]

    def test_repair_blocks_cross_service_commands(self):
        for command in self.CROSS_SERVICE:
            with self.subTest(command=command):
                self.assertIsNotNone(
                    check_command(command, 'repair'),
                    f'跨服务破坏性命令未被拦截: {command}')

    def test_repair_allows_scoped_commands(self):
        for command in self.SCOPED_REPAIR:
            with self.subTest(command=command):
                self.assertIsNone(
                    check_command(command, 'repair'),
                    f'常规修复命令被误伤: {command}')

    def test_chat_mode_also_blocks_cross_service(self):
        # 对话模式有人值守，拦截后转为人工确认，同样不能让模型自行决定
        self.assertIsNotNone(check_command('docker system prune -af', 'agent'))

    def test_diagnose_blocks_write_commands(self):
        self.assertIsNotNone(check_command('systemctl restart nginx', 'diagnose'))
        self.assertIsNone(check_command('systemctl status nginx', 'diagnose'))

    def test_dangerous_commands_blocked_in_all_modes(self):
        for mode in ('repair', 'diagnose', 'agent'):
            with self.subTest(mode=mode):
                self.assertIsNotNone(check_command('reboot', mode))
