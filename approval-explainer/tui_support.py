"""Decorate Ink TUI approval notifications; the core owns queueing and decisions."""
import functools
import inspect
import logging
from pathlib import Path

LOG = logging.getLogger('approval-explainer.tui')
FALLBACK = 'Содержание команды не удалось надёжно разобрать. Проверьте команду ниже; выполнение ещё не разрешено.'


def install_tui(explain, owner_home=None):
    from tools import approval, approval_gateway_wait

    original = approval_gateway_wait._await_gateway_decision
    if getattr(original, '_approval_explainer_tui', False):
        return True
    try:
        compatible = tuple(inspect.signature(original).parameters) == (
            'session_key', 'notify_cb', 'approval_data', 'surface')
        compatible = compatible and approval._await_gateway_decision is original
    except (TypeError, ValueError, AttributeError):
        compatible = False
    if not compatible:
        LOG.warning('approval-explainer: incompatible gateway wait API; keeping stock TUI prompt')
        return False

    @functools.wraps(original)
    def wait(session_key, notify_cb, approval_data, *, surface='gateway'):
        from hermes_cli.plugin_session import session_surface
        from hermes_constants import get_hermes_home

        if (session_surface() != 'tui' or surface not in ('gateway', 'tui')
                or (owner_home is not None and Path(get_hermes_home()).resolve() != owner_home)):
            return original(session_key, notify_cb, approval_data, surface=surface)

        def notify(data):
            # Called only for a real, newly published human prompt (not coalesced
            # followers or smart auto-approvals), on the agent thread, not the UI loop.
            command, reason = data.get('command', ''), data.get('description', '')
            try:
                text = explain(command, reason)
                if not isinstance(text, str) or not text.strip():
                    text = FALLBACK
            except Exception:
                text = FALLBACK
            decorated = dict(data, description=f'Пояснение: {text}\nПричина запроса: {reason}')
            # Preserve the explanation on reconnect as well as first delivery.
            # Touch only presentation text on this exact request; never choices,
            # commands, flags, IDs, timeout, events or resolution callbacks.
            with approval._lock:
                for entry in approval._gateway_queues.get(session_key, []):
                    if entry.data.get('request_id') == data.get('request_id'):
                        entry.data['description'] = decorated['description']
                        break
            return notify_cb(decorated)

        return original(session_key, notify, approval_data, surface=surface)

    setattr(wait, '_approval_explainer_tui', True)
    approval_gateway_wait._await_gateway_decision = wait
    approval._await_gateway_decision = wait  # core imports an alias at module load
    return True


def register_tui(ctx, explain):
    try:
        from hermes_constants import get_hermes_home
        install_tui(explain, Path(get_hermes_home()).resolve())
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        LOG.warning('approval-explainer: TUI integration unavailable (%s); keeping stock prompt', type(exc).__name__)
