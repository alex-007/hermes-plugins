import asyncio
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from plugins.platforms.matrix.adapter import MatrixAdapter
from gateway.platforms.base import ExecApprovalPrompt, SendResult

FILE = Path(__file__).resolve().parents[1] / 'matrix_support.py'
if FILE.exists():
    spec = importlib.util.spec_from_file_location('matrix_support_test', FILE)
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
else:
    support = SimpleNamespace(install_matrix=lambda cls, explain: False)


class MatrixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original = MatrixAdapter._send_exec_approval_prompt
        self.adapter = object.__new__(MatrixAdapter)
        self.adapter._client = object()
        self.adapter._approval_prompt_by_session = {}
        self.adapter._approval_prompts_by_event = {}
        self.sent = []
        async def sender(chat, text, metadata, make, registry, reactions, label):
            self.sent.append((text, tuple(reactions), metadata, label))
            registry['$prompt'] = make('$prompt', '@alex:private', 123)
            return SendResult(success=True, message_id='$prompt')
        self.adapter._send_reaction_prompt = sender
        self.prompt = ExecApprovalPrompt(
            chat_id='!stub', session_key='stub', text='RAW COMMAND: echo harmless\nTRIGGER: script execution',
            actions=[('Once', 'once', 'primary'), ('Deny', 'deny', 'danger')],
            command='echo harmless', description='script execution', smart_denied=True,
            metadata={'requester_user_id': '@alex:private'})

    def tearDown(self):
        MatrixAdapter._send_exec_approval_prompt = self.original

    async def test_same_message_command_reason_choices_and_decisions(self):
        from tools.approval import resolve_gateway_approval
        decisions = MatrixAdapter._handle_approval_reaction
        explain_calls = []
        def explain(command, description):
            explain_calls.append((command, description))
            return 'Только вывод, изменений нет.'
        support.install_matrix(MatrixAdapter, explain)
        before = dict(vars(self.prompt))
        result = await self.adapter._send_exec_approval_prompt(self.prompt)
        text, reactions, metadata, label = self.sent[0]
        self.assertIn('Только вывод, изменений нет.', text)
        self.assertIn(self.prompt.text, text)
        self.assertEqual(reactions, ('✅', '❌'))
        self.assertEqual(explain_calls, [('echo harmless', 'script execution')])
        self.assertEqual(vars(self.prompt), before)
        self.assertEqual(label, 'approval')
        self.assertIs(metadata, self.prompt.metadata)
        self.assertTrue(result.success)
        self.assertFalse(self.adapter._approval_prompts_by_event['$prompt'].resolved)
        self.assertIs(MatrixAdapter._handle_approval_reaction, decisions)
        from tools import approval
        self.assertIs(approval.resolve_gateway_approval, resolve_gateway_approval)


    async def test_failure_fallback_and_standard_choices(self):
        def broken(command, description):
            raise RuntimeError('offline')
        support.install_matrix(MatrixAdapter, broken)
        await self.adapter._send_exec_approval_prompt(self.prompt)
        self.assertIn(support.FALLBACK, self.sent[0][0])
        self.assertIn(self.prompt.text, self.sent[0][0])
        self.assertEqual(self.sent[0][1], ('✅', '❌'))

    async def test_async_generation_does_not_block_loop(self):
        import threading
        started, release = threading.Event(), threading.Event()
        thread_ids = []
        def slow(command, description):
            thread_ids.append(threading.get_ident())
            started.set()
            release.wait(1)
            return 'ASYNC EXPLANATION'
        support.install_matrix(MatrixAdapter, slow)
        task = asyncio.create_task(self.adapter._send_exec_approval_prompt(self.prompt))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.001)
        try:
            self.assertTrue(started.is_set())
            self.assertFalse(task.done(), 'generation must not block the event loop')
            self.assertNotEqual(thread_ids[0], threading.get_ident())
            self.assertEqual(self.sent, [])
        finally:
            release.set()
            await task
        self.assertIn('ASYNC EXPLANATION', self.sent[0][0])

    async def test_other_profile_excluded(self):
        called = []
        def explain(command, description):
            called.append(command)
            return 'SHOULD NOT APPEAR'
        support.install_matrix(MatrixAdapter, explain)
        self.adapter._hermes_profile_name = 'planner'
        await self.adapter._send_exec_approval_prompt(self.prompt)
        self.assertEqual(called, [])
        self.assertNotIn('SHOULD NOT APPEAR', self.sent[0][0])

    async def test_incompatible_api_skipped(self):
        class Different:
            async def _send_exec_approval_prompt(self, prompt, changed):
                return None
        original = Different._send_exec_approval_prompt
        error = None
        try:
            with self.assertLogs('approval-explainer.matrix', level='WARNING'):
                installed = support.install_matrix(Different, lambda *_: '')
        except Exception as exc:
            error = exc
        self.assertIsNone(error, f'incompatible API must gracefully skip: {error}')
        self.assertFalse(installed)
        self.assertIs(Different._send_exec_approval_prompt, original)

    async def test_registered_factory_no_network_idempotent(self):
        self.assertTrue(callable(getattr(support, 'register_matrix', None)), 'Matrix lifecycle missing')
        from hermes_cli.plugins import discover_plugins
        from gateway.platform_registry import platform_registry
        from unittest.mock import patch
        from hermes_cli.cli_modal_mixin import CLIModalMixin
        from hermes_cli.cli_tui_mixin import CLITuiMixin
        cli_callback = CLIModalMixin._approval_callback
        cli_renderer = CLITuiMixin._get_approval_display_fragments
        discover_plugins()
        actual = platform_registry.get('matrix').adapter_factory
        original = actual._send_exec_approval_prompt
        picker = actual.send_model_picker
        try:
            with patch('socket.socket.connect', side_effect=AssertionError('network in register')):
                support.register_matrix(SimpleNamespace(), lambda *_: 'EXPLANATION')
                installed = actual._send_exec_approval_prompt
                self.assertTrue(getattr(installed, '_approval_explainer_matrix', False))
                support.register_matrix(SimpleNamespace(), lambda *_: 'EXPLANATION')
                self.assertIs(actual._send_exec_approval_prompt, installed)
                self.assertIs(actual.send_model_picker, picker)
        finally:
            actual._send_exec_approval_prompt = original
            CLIModalMixin._approval_callback = cli_callback
            CLITuiMixin._get_approval_display_fragments = cli_renderer


if __name__ == '__main__':
    unittest.main()
