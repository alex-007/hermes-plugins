# Hermes plugins

Общие исходники плагинов для hyperion и deathworld (default-профили).

- `approval-explainer/`: пояснения команд при ручном подтверждении в classic CLI и Matrix; полный постраничный просмотр в CLI.
- `matrix-approval-cleanup/`: ограниченные повторные попытки удаления служебных approval reactions в Matrix.

Forgejo: https://git.alex-007.duckdns.org/alex/hermes-plugins
SSH в домашней сети: ssh://git@pulsar:4222/alex/hermes-plugins.git

## Установка

Нужен SSH-ключ, зарегистрированный в Forgejo. Каждый плагин устанавливается из своего подкаталога:

    hermes plugins install 'ssh://git@pulsar:4222/alex/hermes-plugins.git#approval-explainer' --enable
    hermes plugins install 'ssh://git@pulsar:4222/alex/hermes-plugins.git#matrix-approval-cleanup' --enable

Для перехода с существующей локальной установки используйте `--force`. Источник и ревизию сохраняет штатный менеджер Hermes, не сам плагин. `--ref <commit SHA>` устанавливает фиксированный commit; для обычного обновления без смены pin не задавайте `--ref`.

## Обновление

Сначала коммит и push исходников в репозиторий, затем на каждом компьютере:

    hermes plugins update approval-explainer
    hermes plugins update matrix-approval-cleanup

Проверка:

    hermes --run-module unittest discover -s "$HOME/.hermes/plugins/approval-explainer/tests" -v
    hermes --run-module unittest discover -s "$HOME/.hermes/plugins/matrix-approval-cleanup/tests" -v
    hermes plugins doctor approval-explainer --ci
    hermes plugins doctor matrix-approval-cleanup --ci

CLI требует нового процесса; gateway — штатного `hermes gateway restart`, выполняемого извне, а не из его собственной задачи. Другие профили не обновляются автоматически. Не используйте symlink на checkout: профильные Matrix-патчи проверяют установленный путь.

Внутренние UI/Matrix методы Hermes не являются стабильным plugin API: после обновления Hermes проверяйте тесты и загрузку. Подробности и ограничения — в README каждого плагина. В репозитории нет credentials, пользовательской конфигурации или логов.
