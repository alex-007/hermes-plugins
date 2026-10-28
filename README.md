# Hermes plugins

Plugins for Hermes Agent: command explanations before approval and cleanup of Matrix approval reactions. Matrix functionality is intended for the default profile.

- `approval-explainer/`: command explanations for manual approvals in classic CLI, Ink TUI, and Matrix; full paginated explanations in classic CLI.
- `matrix-approval-cleanup/`: bounded retries for removing Matrix approval reactions added by the bot.

Repository: https://github.com/alex-007/hermes-plugins

## Installation

Install each plugin from its own subdirectory. No GitHub account or SSH key is required:

    hermes plugins install 'https://github.com/alex-007/hermes-plugins.git#approval-explainer' --enable
    hermes plugins install 'https://github.com/alex-007/hermes-plugins.git#matrix-approval-cleanup' --enable

The plugins require `plugins.isolation: in_process`. Explanations use the `approval` auxiliary model and are generated in Russian. See each plugin's README for detailed requirements and limitations.

Use `--force` to replace an existing local installation. The native Hermes plugin manager records the source and revision; the plugins themselves do not. `--ref <commit SHA>` pins the installation to a specific commit. Omit `--ref` for normal tracking updates rather than a pinned revision.

## Updating

Commit and push the source changes to the repository first, then run the following on each machine:

    hermes plugins update approval-explainer
    hermes plugins update matrix-approval-cleanup

Validation:

    hermes --run-module unittest discover -s "$HOME/.hermes/plugins/approval-explainer/tests" -v
    hermes --run-module unittest discover -s "$HOME/.hermes/plugins/matrix-approval-cleanup/tests" -v
    hermes plugins doctor approval-explainer --ci
    hermes plugins doctor matrix-approval-cleanup --ci

Classic CLI changes require a new CLI process. Gateway changes, including the plugin integration serving Ink TUI, require a normal `hermes gateway restart`, run externally rather than from the gateway's own task. Other profiles are not updated automatically. Do not symlink the installation to a checkout: profile-scoped Matrix patches validate the installed path.

Hermes internal UI and Matrix methods are not a stable plugin API. After updating Hermes, verify that the plugins load and their tests pass. See each plugin's README for details and limitations. This repository contains no credentials, user configuration, or logs.

## License

MIT — see [LICENSE](LICENSE).
