"""Profile-local retry of the bot's seeded approval reaction cleanup only."""
import asyncio
import functools
import inspect
import logging
from collections.abc import Mapping
from pathlib import Path

LOG = logging.getLogger('matrix-approval-cleanup')
METHOD = '_redact_bot_approval_reactions'


def install(adapter_cls, owner_home=None):
    original = getattr(adapter_cls, METHOD, None)
    if getattr(original, '_matrix_approval_cleanup_v1', False):
        return True
    try:
        compatible = (inspect.iscoroutinefunction(original)
                      and tuple(inspect.signature(original).parameters) == ('self', 'room_id', 'prompt')
                      and inspect.iscoroutinefunction(getattr(adapter_cls, '_redact_reaction', None))
                      and tuple(inspect.signature(adapter_cls._redact_reaction).parameters)
                      == ('self', 'room_id', 'reaction_event_id', 'reason')
                      and callable(getattr(adapter_cls, '_schedule_reaction_redaction', None)))
    except (AttributeError, TypeError, ValueError):
        compatible = False
    if not compatible:
        LOG.warning('matrix-approval-cleanup: incompatible Matrix API; keeping stock cleanup')
        return False

    @functools.wraps(original)
    async def cleanup(self, room_id, prompt):
        # A host gateway shares this class across profiles. Never change secondary adapters.
        if getattr(self, '_hermes_profile_name', 'default') not in ('', 'default', None):
            return await original(self, room_id, prompt)
        if owner_home is not None:
            from hermes_constants import get_hermes_home
            if Path(get_hermes_home()).resolve() != owner_home:
                return await original(self, room_id, prompt)
        reactions_map = getattr(prompt, 'bot_reaction_events', None)
        tasks = getattr(self, '_reaction_redaction_tasks', None)
        delay = getattr(self, '_reaction_redaction_delay_seconds', None)
        retry_delay = getattr(self, '_reaction_redaction_retry_seconds', 1.0)
        if not (isinstance(reactions_map, Mapping) and isinstance(tasks, set)
                and isinstance(delay, (int, float)) and delay >= 0
                and isinstance(retry_delay, (int, float)) and retry_delay >= 0):
            LOG.warning('matrix-approval-cleanup: incompatible instance API; keeping stock cleanup')
            return await original(self, room_id, prompt)
        reactions = tuple(reactions_map.items())

        async def redact_all():
            if delay:
                await asyncio.sleep(delay)
            for emoji, event_id in reactions:
                for attempt in range(3):
                    if await self._redact_reaction(room_id, event_id, 'approval resolved'):
                        LOG.debug('Matrix: redacted approval reaction %s (%s)', emoji, event_id)
                        break
                    if attempt < 2 and retry_delay:
                        await asyncio.sleep(retry_delay * (attempt + 1))
                else:
                    LOG.warning('Matrix: failed to redact approval reaction %s after 3 attempts', event_id)

        task = asyncio.create_task(redact_all())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    cleanup._matrix_approval_cleanup_v1 = True
    setattr(adapter_cls, METHOD, cleanup)
    LOG.info('matrix-approval-cleanup: installed MatrixAdapter.%s (3 attempts; default profile)', METHOD)
    return True


def register(ctx):
    # Resolve the actual profile-scoped factory. Directory platforms are loaded
    # as hermes_plugins.platforms__matrix.adapter, NOT the canonical import path.
    # Materializing the deferred registration defines the class; it does not connect.
    try:
        owner_home = Path(__file__).resolve().parents[2]
        from hermes_constants import get_hermes_home
        if Path(get_hermes_home()).resolve() != owner_home:
            LOG.warning('matrix-approval-cleanup: registration outside owner profile; keeping stock cleanup')
            return
        from gateway.platform_registry import platform_registry
        from hermes_cli.plugins import get_plugin_manager

        def apply_patch():
            entry = platform_registry.get('matrix')
            adapter_cls = getattr(entry, 'adapter_factory', None)
            if not inspect.isclass(adapter_cls):
                LOG.warning('matrix-approval-cleanup: Matrix factory unavailable; keeping stock cleanup')
                return
            install(adapter_cls, owner_home=owner_home)

        # Never force a deferred plugin load while register runs under the discovery
        # lock in a deadline worker. Only patch an already concrete factory here.
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
                    LOG.warning('matrix-approval-cleanup: unsupported startup API (%s); keeping stock cleanup', type(exc).__name__)
            unsubscribe = get_plugin_manager().on_plugin_loaded(after_discovery)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        LOG.warning('matrix-approval-cleanup: unsupported Matrix API (%s); keeping stock cleanup', type(exc).__name__)
