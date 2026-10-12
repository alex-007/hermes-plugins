import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('panel_plugin', Path(__file__).resolve().parents[1] / '__init__.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

class PanelTests(unittest.TestCase):
    def test_full_explanation_choice_reveals_complete_text_without_approving(self):
        import cli
        from hermes_cli.cli_modal_mixin import CLIModalMixin
        from hermes_cli.cli_tui_mixin import CLITuiMixin
        long = 'ПОЛНЫЙ ТЕКСТ ' + ('подробное объяснение. ' * 100)
        class Harness(CLIModalMixin, CLITuiMixin):
            def _ring_bell(self, **kwargs): pass
            def _paint_now(self): pass
            def _persist_prompt_summary(self, *args): pass
            def _poll_modal_queue(self, *args, **kwargs):
                self.rendered = ''.join(text for _, text in self._get_approval_display_fragments())
                if 'explanation' in self._approval_state['choices']:
                    self._approval_state['selected'] = self._approval_state['choices'].index('explanation')
                    self._handle_approval_selection()
                    pages = []
                    while True:
                        pages.append(''.join(text for _, text in self._get_approval_display_fragments()))
                        self.assert_unresolved = self._approval_state['response_queue'].empty()
                        if not self.assert_unresolved:
                            raise AssertionError('Viewing must not approve')
                        if not self._approval_state.get('explanation_has_next'):
                            break
                        self._approval_state['selected'] = self._approval_state['choices'].index('explanation_next')
                        self._handle_approval_selection()
                    self.rendered = ''.join(pages)
                    self._approval_state['selected'] = self._approval_state['choices'].index('explanation_back')
                    self._handle_approval_selection()
                    if self._approval_state.get('show_full_explanation'):
                        raise AssertionError('Must return to approval')
                    if 'once' not in self._approval_state['choices']:
                        raise AssertionError('Original choices must be restored')
                return self.choice
        import threading
        obj = Harness()
        obj._approval_lock = threading.Lock()
        obj._approval_state = None
        plugin.install_panel()
        with patch.object(plugin, 'explain', return_value=long):
            obj.choice = 'deny'
            self.assertEqual(obj._approval_callback('echo ' + ('x' * 80), 'shell command'), 'deny')
        self.assertIn('Полное пояснение', obj.rendered)
        self.assertIn('ПОЛНЫЙ ТЕКСТ', obj.rendered)
        self.assertGreaterEqual(obj.rendered.count('подробное'), 100)
        self.assertNotIn('Пояснение усечено', obj.rendered)

    def test_explanation_in_real_panel_before_choices_and_choice_preserved(self):
        import cli
        from hermes_cli.cli_modal_mixin import CLIModalMixin
        from hermes_cli.cli_tui_mixin import CLITuiMixin
        class Harness(CLIModalMixin, CLITuiMixin):
            def _ring_bell(self, **kwargs): pass
            def _paint_now(self): pass
            def _persist_prompt_summary(self, *args): pass
            def _poll_modal_queue(self, *args, **kwargs):
                self.rendered = ''.join(text for _, text in self._get_approval_display_fragments())
                return self.choice
        import threading
        obj = Harness()
        obj._approval_lock = threading.Lock()
        obj._approval_state = None
        with patch.object(plugin, 'explain', return_value='Проверяет статус задания; ничего не изменяет.') as gen:
            plugin.install_panel()
            for choice in ['deny', 'once']:
                obj.choice = choice
                self.assertEqual(obj._approval_callback('echo probe', 'shell command'), choice)
                self.assertIn('Проверяет статус задания', obj.rendered)
                self.assertLess(obj.rendered.index('Проверяет статус задания'), obj.rendered.index('1.'))
                self.assertIn('shell command', obj.rendered)
                self.assertIn('echo probe', obj.rendered)
            self.assertEqual(gen.call_count, 2)

if __name__ == '__main__': unittest.main()
