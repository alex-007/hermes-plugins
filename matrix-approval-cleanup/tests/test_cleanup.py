import asyncio
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '__init__.py').exists():
    spec = importlib.util.spec_from_file_location('matrix_cleanup_test', ROOT / '__init__.py')
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
else:
    plugin = SimpleNamespace(install=lambda cls: False)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_retries_success(self):
        class Adapter:
            def __init__(self):
                self._reaction_redaction_delay_seconds = 0
                self._reaction_redaction_retry_seconds = 0
                self._reaction_redaction_tasks = set()
                self.calls = {}

            async def _redact_reaction(self, room_id, reaction_event_id, reason=''):
                self.calls[reaction_event_id] = self.calls.get(reaction_event_id, 0) + 1
                return reaction_event_id != '$allow' or self.calls[reaction_event_id] >= 2

            def _schedule_reaction_redaction(self, room_id, reaction_event_id, reason=''):
                task = asyncio.create_task(self._redact_reaction(room_id, reaction_event_id, reason))
                self._reaction_redaction_tasks.add(task)
                task.add_done_callback(self._reaction_redaction_tasks.discard)

            async def _redact_bot_approval_reactions(self, room_id, prompt):
                for event_id in prompt.bot_reaction_events.values():
                    self._schedule_reaction_redaction(room_id, event_id, 'approval resolved')

        plugin.install(Adapter)
        adapter = Adapter()
        prompt = SimpleNamespace(bot_reaction_events={'allow': '$allow', 'deny': '$deny'}, resolved=True)
        await adapter._redact_bot_approval_reactions('!room', prompt)
        await asyncio.gather(*adapter._reaction_redaction_tasks)
        self.assertEqual(adapter.calls, {'$allow': 2, '$deny': 1})
        self.assertTrue(prompt.resolved)


    async def test_incompatible_api_gracefully_skipped(self):
        class Incompatible:
            async def _redact_bot_approval_reactions(self, room_id):
                return 'stock'
        original = Incompatible._redact_bot_approval_reactions
        error = None
        try:
            with self.assertLogs('matrix-approval-cleanup', level='WARNING'):
                installed = plugin.install(Incompatible)
        except Exception as exc:
            error = exc
        self.assertIsNone(error, f'incompatible API must not raise: {error}')
        self.assertFalse(installed)
        self.assertIs(Incompatible._redact_bot_approval_reactions, original)

    async def test_real_adapter_bounded_and_decisions_unchanged(self):
        from plugins.platforms.matrix.adapter import MatrixAdapter
        original = MatrixAdapter._redact_bot_approval_reactions
        decisions = MatrixAdapter._handle_approval_reaction
        from tools.approval import resolve_gateway_approval
        try:
            self.assertTrue(plugin.install(MatrixAdapter))
            adapter = object.__new__(MatrixAdapter)
            adapter._reaction_redaction_delay_seconds = 0.01
            adapter._reaction_redaction_retry_seconds = 0
            adapter._reaction_redaction_tasks = set()
            calls = []
            async def redact(room_id, reaction_event_id, reason=''):
                calls.append((room_id, reaction_event_id, reason))
                return False
            adapter._redact_reaction = redact
            prompt = SimpleNamespace(bot_reaction_events={'allow': '$allow', 'deny': '$deny'}, resolved=True, choices={'allow': 'once', 'deny': 'deny'})
            before = dict(vars(prompt))
            await adapter._redact_bot_approval_reactions('!room', prompt)
            self.assertEqual(calls, [])
            with self.assertLogs('matrix-approval-cleanup', level='WARNING'):
                await asyncio.gather(*adapter._reaction_redaction_tasks)
            await asyncio.sleep(0)
            self.assertEqual([c[1] for c in calls], ['$allow'] * 3 + ['$deny'] * 3)
            self.assertTrue(all(c[0] == '!room' and c[2] == 'approval resolved' for c in calls))
            self.assertFalse(adapter._reaction_redaction_tasks)
            self.assertEqual(vars(prompt), before)
            self.assertIs(MatrixAdapter._handle_approval_reaction, decisions)
            from tools import approval
            self.assertIs(approval.resolve_gateway_approval, resolve_gateway_approval)
        finally:
            MatrixAdapter._redact_bot_approval_reactions = original


    async def test_other_profile_uses_stock_cleanup(self):
        class Adapter:
            _hermes_profile_name = 'planner'
            async def _redact_reaction(self, room_id, reaction_event_id, reason=''):
                return True
            def _schedule_reaction_redaction(self, room_id, reaction_event_id, reason=''):
                pass
            async def _redact_bot_approval_reactions(self, room_id, prompt):
                return 'stock-planner'
        plugin.install(Adapter)
        error = None
        try:
            value = await Adapter()._redact_bot_approval_reactions('!room', SimpleNamespace())
        except Exception as exc:
            error = exc
        self.assertIsNone(error, f'foreign profile must use stock cleanup: {error}')
        self.assertEqual(value, 'stock-planner')

    async def test_incompatible_instance_uses_stock_cleanup(self):
        class Adapter:
            async def _redact_reaction(self, room_id, reaction_event_id, reason=''):
                return True
            def _schedule_reaction_redaction(self, room_id, reaction_event_id, reason=''):
                pass
            async def _redact_bot_approval_reactions(self, room_id, prompt):
                return 'stock-instance'
        plugin.install(Adapter)
        error = None
        try:
            with self.assertLogs('matrix-approval-cleanup', level='WARNING'):
                value = await Adapter()._redact_bot_approval_reactions('!room', SimpleNamespace())
        except Exception as exc:
            error = exc
        self.assertIsNone(error, f'changed instance API must keep stock cleanup: {error}')
        self.assertEqual(value, 'stock-instance')

    async def test_register_without_network_and_idempotent(self):
        self.assertTrue(callable(getattr(plugin, 'register', None)), 'register lifecycle is missing')
        from hermes_cli.plugins import discover_plugins
        from gateway.platform_registry import platform_registry
        discover_plugins()
        MatrixAdapter = platform_registry.get('matrix').adapter_factory
        from unittest.mock import patch
        original = MatrixAdapter._redact_bot_approval_reactions
        try:
            with patch('socket.socket.connect', side_effect=AssertionError('network during register')):
                plugin.register(SimpleNamespace())
                installed = MatrixAdapter._redact_bot_approval_reactions
                self.assertTrue(getattr(installed, '_matrix_approval_cleanup_v1', False))
                plugin.register(SimpleNamespace())
                self.assertIs(MatrixAdapter._redact_bot_approval_reactions, installed)
        finally:
            MatrixAdapter._redact_bot_approval_reactions = original


if __name__ == '__main__':
    unittest.main()
