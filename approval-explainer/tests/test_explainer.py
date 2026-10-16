import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('approval_explainer_test', HERE / '__init__.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class Tests(unittest.TestCase):
    def test_smart_and_gateway_do_not_spend_tokens(self):
        with patch.object(plugin, 'explain') as gen, patch.object(plugin, 'emit') as emit:
            for surface in ['smart', 'gateway', '', 'transport:other']:
                plugin.on_approval(command='echo test', surface=surface)
            gen.assert_not_called()
            emit.assert_not_called()

    def test_cli_explains(self):
        with patch.object(plugin, 'explain', return_value='Только вывод.') as gen, patch.object(plugin, 'emit') as emit:
            plugin.on_approval(command='echo test', description='test', surface='cli')
            gen.assert_called_once_with('echo test', 'test')
            emit.assert_called_once_with('Только вывод.')

    def test_failure_does_not_block(self):
        with patch.object(plugin, 'generate', side_effect=RuntimeError('offline')):
            self.assertEqual(plugin.explain('echo test', ''), plugin.FALLBACK)

    def test_timeout_is_bounded(self):
        import time
        with patch.object(plugin, 'TIMEOUT', 0.01), patch.object(plugin, 'generate', side_effect=lambda *a: (time.sleep(.05), 'late')[1]):
            with patch.object(plugin, 'emit') as emit:
                self.assertEqual(plugin.explain('echo test', ''), plugin.FALLBACK)
                time.sleep(.07)
                emit.assert_not_called()

    def test_script_read_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'test.sh'
            p.write_text('echo EXAMPLE\n')
            self.assertIn('echo EXAMPLE', plugin.script_context(f'bash {p}'))
            link = Path(tmp) / 'link.sh'; link.symlink_to(p)
            self.assertNotIn('echo EXAMPLE', plugin.script_context(f'bash {link}'))
            self.assertIn('не читалось', plugin.script_context('bash relative.sh'))

    def test_real_approval_flow_keeps_choice(self):
        from tools import approval, approval_context
        args = dict(command='python -c "print(123)"', description='script', pattern_key='python',
                    pattern_keys=['python'], session_key='plugin-test', is_cli=True,
                    is_gateway=False, is_ask=False, smart=True)
        import inspect
        if 'warnings' in inspect.signature(approval._human_decision).parameters:
            args['warnings'] = []
        events = []
        def fire(name, **kw):
            if name == 'pre_approval_request':
                plugin.on_approval(**kw)
        with patch.object(approval, '_smart_gate', return_value=({'approved': True}, False)), \
             patch.object(plugin, 'explain') as explain:
            result = approval._human_decision(approval._COMMAND_GATE, approval_callback=None, **args)
            self.assertTrue(result['approved']); explain.assert_not_called()
        with patch.object(approval, '_smart_gate', return_value=(None, False)), \
             patch.object(approval, '_present_with_selected_transport', return_value={'selected': False}), \
             patch.object(approval_context, '_fire_approval_hook', side_effect=fire), \
             patch.object(plugin, 'explain', return_value='Только вывод.'), \
             patch.object(plugin, 'emit', side_effect=lambda t: events.append('explanation')), \
             patch.object(approval, 'prompt_dangerous_approval', side_effect=lambda *a, **k: (events.append('prompt'), 'deny')[1]):
            result = approval._human_decision(approval._COMMAND_GATE, approval_callback=None, **args)
            self.assertFalse(result['approved'])
            self.assertEqual(events, ['explanation', 'prompt'])

if __name__ == '__main__':
    unittest.main()
