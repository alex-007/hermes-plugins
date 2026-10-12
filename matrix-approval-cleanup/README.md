# Matrix approval cleanup

Standalone native plugin for the default profile, tested on Hermes v0.21.7+179.g0e16173. Requires `plugins.isolation: in_process` (already configured here).

At `register(ctx)`, checks the owner-profile registry without forcing deferred loading. If Matrix is already concrete, patches its factory immediately. Otherwise subscribes a one-shot `PluginManager.on_plugin_loaded` callback: after discovery releases its lock, resolves the actual profile-scoped Matrix adapter factory through `gateway.platform_registry.platform_registry.get('matrix')`. No client is constructed or connected. The built-in platform is namespaced (`hermes_plugins.platforms__matrix.adapter`); patching the canonical import alone would not affect the real gateway. The callback unsubscribes itself before resolving; an unavailable platform logs a warning and retains stock behavior. No advisory manifest dependency is needed for a lazily registered platform.

Only `MatrixAdapter._redact_bot_approval_reactions` is replaced in memory. The existing initial delay is retained. Each event in `prompt.bot_reaction_events` gets at most three attempts; false returns are retried after 1 and 2 seconds, or the instance's existing `_reaction_redaction_retry_seconds` override. The background task is tracked in the adapter's existing task set. Cancellation and raised exceptions keep the previous local method's behavior. No choice resolver, approval handler, expiry policy, user reaction, or model-picker cleanup is modified.

Class signature/helper guards and instance-state guards warn and retain the captured stock method on incompatible API. Secondary-profile adapters and foreign profile runtime scopes use stock cleanup. Repeated registration is idempotent. No network I/O during registration. This is a deliberate narrow internal runtime patch, not a stable public Matrix extension API; check regression tests after upgrades.

Enable with `hermes plugins enable matrix-approval-cleanup` in default only. Restart the gateway separately to activate a coherent startup lifecycle; this task must not restart its own gateway. Disabling/unloading does not undo an already-installed class patch until process restart. New processes discover enabled plugins automatically.

Tests: `hermes --run-module unittest discover -s "$HERMES_HOME/plugins/matrix-approval-cleanup/tests" -v`. Doctor: `hermes plugins doctor "$HERMES_HOME/plugins/matrix-approval-cleanup" --ci`. Tests exercise real adapter code and the actual namespaced platform factory without making Matrix network calls. Socket connects are explicitly forbidden in the registration test. Doctor's temporary home is outside the owner profile, so its registration skips the patch; real default-profile registration is tested separately.

Original diff and full focused test backup: `/home/alex/hermes-artifacts/matrix-approval-cleanup-20261012-160018/`.
