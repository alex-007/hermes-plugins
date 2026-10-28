"""Source-path smoke: real auxiliary model + gateway prompt, always denies; no execution."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_cli.plugins import discover_plugins
from tools import approval

# Bootstrap configured providers/platforms before loading the candidate source.
discover_plugins()
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('approval_explainer_candidate', root / '__init__.py',
                                             submodule_search_locations=[str(root)])
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
plugin.register(SimpleNamespace(register_hook=lambda *args: None))

seen = []
def notify(data):
    seen.append(data)
    print('TUI_APPROVAL=' + json.dumps(data, ensure_ascii=False), flush=True)
    assert 'Пояснение: ' in data['description']
    assert plugin.FALLBACK not in data['description'], 'Real model generation failed'
    pending = approval.get_pending_gateway_approval('explainer-source-smoke')
    assert pending is not None and pending['description'] == data['description']
    approval.resolve_gateway_approval('explainer-source-smoke', 'deny', request_id=data['request_id'])

with patch('hermes_cli.plugin_session.session_surface', return_value='tui'):
    result = approval._await_gateway_decision('explainer-source-smoke', notify, dict(
        command="python -c \"print('Approval test: OK')\"", description='script execution via -c flag',
        pattern_key='explainer-source-smoke', pattern_keys=['explainer-source-smoke']))
assert len(seen) == 1 and result['choice'] == 'deny' and result['resolved']
print('SMOKE_RESULT=' + json.dumps(result, ensure_ascii=False))
print('No shell command executed; no permissions persisted.')
