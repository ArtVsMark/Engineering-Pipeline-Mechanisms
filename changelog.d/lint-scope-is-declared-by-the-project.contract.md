### `step-lint` не называет путей: состав линта — в настройках проекта

`step-lint` зовёт `ruff check`, `ruff format --check` и `mypy` без путей.
Раньше шаг передавал им `scripts/ tests/ packages/` — раскладку этого
проекта, чужую потребителю. Теперь состав объявляет потребитель в своём
`pyproject.toml`: `[tool.ruff] include` и `[tool.mypy] files`. Без
`files` шаг «типы» краснеет: mypy без целей не запускается.

#992
