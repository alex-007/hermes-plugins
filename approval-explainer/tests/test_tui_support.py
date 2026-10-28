"""Exercise the real gateway queue used by Ink TUI, without executing commands."""
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools import approval, approval_context, approval_gateway_wait

FILE = Path(__file__).resolve().parents[1] / 'tui_support.py'
if FILE.exists():
    spec = importlib.util.spec_from_file_location('tui_support_test', FILE)
    assert spec and spec.loader
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
else:
    support = SimpleNamespace(install_tui=lambda *a, **kw: False)


class TuiTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(approval_gateway_wait, '_await_gateway_decision',
                                      approval_gateway_wait._await_gateway_decision))
        self.enterContext(patch.object(approval, '_await_gateway_decision', approval._await_gateway_decision))
        self.surface = self.enterContext(patch('hermes_cli.plugin_session.session_surface', return_value='tui'))
        self.enterContext(patch.object(approval_context, '_fire_approval_hook'))
        self.explain = Mock(return_value='Выводит probe; файлов не меняет.')
        self.data = dict(command='echo probe', description='script execution', pattern_key='script',
                         pattern_keys=['script'], allow_session=False, allow_permanent=False, smart_denied=True)

    def check_prompt(self, choice, expected):
        seen = []
        errors = []
        def notify(payload):
            seen.append(payload)
            try:
                pending = approval.get_pending_gateway_approval('explainer-tui-test')
                assert pending is not None
                self.assertEqual(pending['description'], payload['description'])
                self.assertEqual(payload['description'], f'Пояснение: {expected}\nПричина запроса: script execution')
                for key, value in self.data.items():
                    if key != 'description':
                        self.assertEqual(payload[key], value)
            except AssertionError as exc:
                errors.append(exc)
            self.assertEqual(approval.resolve_gateway_approval(
                'explainer-tui-test', choice, request_id=payload['request_id']), 1)
        result = approval._await_gateway_decision('explainer-tui-test', notify, self.data)
        if errors:
            raise errors[0]
        self.assertEqual(len(seen), 1)
        self.assertTrue(result['resolved'])
        self.assertEqual(result['choice'], choice)
        self.assertEqual(self.data['description'], 'script execution')
        self.assertIsNone(approval.get_pending_gateway_approval('explainer-tui-test'))
        self.explain.assert_called_once_with('echo probe', 'script execution')

    def test_explanation_in_real_pending_prompt_once_and_deny(self):
        self.assertTrue(support.install_tui(self.explain))
        for choice in ('once', 'deny'):
            with self.subTest(choice=choice):
                self.explain.reset_mock()
                self.check_prompt(choice, 'Выводит probe; файлов не меняет.')

    def test_failure_fallback_keeps_deny(self):
        self.explain.side_effect = RuntimeError('offline')
        self.assertTrue(support.install_tui(self.explain))
        self.check_prompt('deny', support.FALLBACK)

    def test_blank_fallback_keeps_once(self):
        self.explain.return_value = ''
        self.assertTrue(support.install_tui(self.explain))
        self.check_prompt('once', support.FALLBACK)

    def test_other_surfaces_skip_explanation(self):
        self.assertTrue(support.install_tui(self.explain))
        for surface in ('cli', 'matrix', 'telegram', 'acp', 'desktop', ''):
            self.surface.return_value = surface
            def notify(data):
                self.assertEqual(data['description'], 'script execution')
                approval.resolve_gateway_approval('explainer-tui-test', 'deny', request_id=data['request_id'])
            result = approval._await_gateway_decision('explainer-tui-test', notify, self.data)
            self.assertEqual(result['choice'], 'deny')
        self.explain.assert_not_called()

    def test_other_profile_skipped(self):
        self.assertTrue(support.install_tui(self.explain, Path('/different/profile')))
        def notify(data):
            self.assertEqual(data['description'], 'script execution')
            approval.resolve_gateway_approval('explainer-tui-test', 'deny', request_id=data['request_id'])
        result = approval._await_gateway_decision('explainer-tui-test', notify, self.data)
        self.assertEqual(result['choice'], 'deny')
        self.explain.assert_not_called()

    def test_idempotent_install_does_not_generate_or_resolve(self):
        resolver = approval.resolve_gateway_approval
        with patch('socket.socket.connect', side_effect=AssertionError('network in register')):
            self.assertTrue(support.install_tui(self.explain))
            installed = approval._await_gateway_decision
            self.assertTrue(support.install_tui(self.explain))
        self.assertIs(approval._await_gateway_decision, installed)
        self.assertIs(approval_gateway_wait._await_gateway_decision, installed)
        self.assertIs(approval.resolve_gateway_approval, resolver)
        self.explain.assert_not_called()

    def test_incompatible_api_keeps_stock(self):
        def changed_api(session_key, notify_cb, approval_data, new_argument):
            pass
        with patch.object(approval_gateway_wait, '_await_gateway_decision', changed_api):
            with self.assertLogs('approval-explainer.tui', level='WARNING'):
                self.assertFalse(support.install_tui(self.explain))
            self.assertIs(approval_gateway_wait._await_gateway_decision, changed_api)
        self.explain.assert_not_called()

    def test_notification_failure_keeps_core_cleanup(self):
        self.assertTrue(support.install_tui(self.explain))
        def notify(data):
            raise RuntimeError('client disconnected')
        with self.assertLogs('tools.approval', level='WARNING'):
            result = approval._await_gateway_decision('explainer-tui-test', notify, self.data)
        self.assertEqual(result, dict(resolved=False, choice=None, notify_failed=True))
        self.assertIsNone(approval.get_pending_gateway_approval('explainer-tui-test'))


if __name__ == '__main__':
    unittest.main()
