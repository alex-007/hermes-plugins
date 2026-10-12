import json
from hermes_cli.plugins import discover_plugins
from tools import approval

discover_plugins()
import inspect
kwargs = {'warnings': []} if 'warnings' in inspect.signature(approval._human_decision).parameters else {}
result = approval._human_decision(
    approval._COMMAND_GATE, command="python -c \"print('Approval test: OK')\"",
    description="script execution via -c flag", pattern_key="approval-explainer-smoke",
    pattern_keys=["approval-explainer-smoke"], session_key="approval-explainer-smoke",
    approval_callback=None, is_cli=True, is_gateway=False, is_ask=False, smart=False, **kwargs,
)
print('SMOKE_RESULT=' + json.dumps(result, ensure_ascii=False))
