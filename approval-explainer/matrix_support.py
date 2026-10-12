"""Matrix explanation in the existing exec-approval message; decisions stay core-owned."""
import asyncio
import functools
import inspect
import logging
from dataclasses import replace
from pathlib import Path

LOG = logging.getLogger('approval-explainer.matrix')
METHOD = '_send_exec_approval_prompt'
FALLBACK = 'Содержание команды не удалось надёжно разобрать. Проверьте команду ниже; выполнение ещё не разрешено.'


def install_matrix(adapter_cls, explain, owner_home=None):
    original = getattr(adapter_cls, METHOD, None)
    if getattr(original, '_approval_explainer_matrix', False):
        return True
    try:
        compatible = (inspect.iscoroutinefunction(original)
                      and tuple(inspect.signature(original).parameters) == ('self', 'prompt'))
    except (TypeError, ValueError):
        compatible = False
    if not compatible:
        LOG.warning('approval-explainer: incompatible Matrix prompt API; keeping stock prompt')
        return False

    @functools.wraps(original)
    async def send(self, prompt):
        if getattr(self, '_hermes_profile_name', 'default') not in ('', 'default', None):
            return await original(self, prompt)
        if owner_home is not None:
            from hermes_constants import get_hermes_home
            if Path(get_hermes_home()).resolve() != owner_home:
                return await original(self, prompt)
        if not getattr(self, '_client', None):
            return await original(self, prompt)
        from gateway.platforms.base import ExecApprovalPrompt
        if not (isinstance(prompt, ExecApprovalPrompt)
                and all(isinstance(getattr(prompt, field, None), str)
                        for field in ('command', 'description', 'text'))):
            LOG.warning('approval-explainer: incompatible Matrix prompt type; keeping stock prompt')
            return await original(self, prompt)
        try:
            # Existing explain bounds generation with its shared slot and timeout.
            # Its synchronous wait and model call must never run on the gateway loop.
            text = await asyncio.to_thread(explain, prompt.command, prompt.description)
            if not isinstance(text, str) or not text.strip():
                text = FALLBACK
        except Exception:
            text = FALLBACK
        # Copy only the rendered text. Preserve raw command, trigger description,
        # actions, smart_denied, metadata, authentication and the original renderer.
        decorated = replace(prompt, text=f'Пояснение: {text}\n\n{prompt.text}')
        return await original(self, decorated)

    send._approval_explainer_matrix = True
    setattr(adapter_cls, METHOD, send)
    LOG.info('approval-explainer: installed MatrixAdapter.%s (default profile)', METHOD)
    return True


def register_matrix(ctx, explain):
    try:
        owner_home = Path(__file__).resolve().parents[2]
        from hermes_constants import get_hermes_home
        if Path(get_hermes_home()).resolve() != owner_home:
            LOG.warning('approval-explainer: Matrix registration outside owner profile; skipped')
            return
        from gateway.platform_registry import platform_registry
        from hermes_cli.plugins import get_plugin_manager

        def apply_patch():
            entry = platform_registry.get('matrix')
            adapter_cls = getattr(entry, 'adapter_factory', None)
            if not inspect.isclass(adapter_cls):
                LOG.warning('approval-explainer: Matrix factory unavailable; keeping stock prompt')
                return
            install_matrix(adapter_cls, explain, owner_home)

        # Same lifecycle as matrix-approval-cleanup: no deferred import under the
        # register deadline-worker/discovery lock, and no client/network in register.
        entry, _loader = platform_registry.snapshot_registration('matrix', scope=str(owner_home))
        if entry is not None:
            apply_patch()
        else:
            unsubscribe = None
            def after_discovery(summaries):
                nonlocal unsubscribe
                if unsubscribe is not None:
                    unsubscribe()
                try:
                    apply_patch()
                except (ImportError, AttributeError, TypeError, ValueError) as exc:
                    LOG.warning('approval-explainer: incompatible Matrix lifecycle (%s); keeping stock prompt', type(exc).__name__)
            unsubscribe = get_plugin_manager().on_plugin_loaded(after_discovery)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        LOG.warning('approval-explainer: incompatible Matrix lifecycle (%s); keeping stock prompt', type(exc).__name__)
