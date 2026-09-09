#!/usr/bin/env python3
"""Сверяет ответ проекта по проверкам с тем, что выдаёт дерево.

Класс проверки объявляется данными (`.pipeline.yml`), а сами проверки живут в
файлах прогонов. Две стороны расходятся молча: добавили джоб — он молча стал бы
обязательным или молча никем не читаемым; убрали джоб — ответ по нему остался
бы висеть, и сводный гейт ждал бы записи, которой никто не выдаёт.

Что проверяется:

* **полнота**: по каждой проверке дерева есть ответ, пусть и `unreviewed` —
  сверяется состав, а не наличие файла
  ([128](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/128-a-required-field-is-checked-for-completeness.md));
* **обратное**: у каждого ответа есть проверка, которая его выдаёт;
* **матрица**: обязательным объявлено имя джоба, а не ячейки — матричный джоб
  выдаёт записи вида `test (3.12)`, и имени `test` на голове не появляется
  вовсе;
* **сводный не отвечает сам за себя**: его класс задан построением;
* **предмет опроса не пуст**: без единой обязательной проверки сводный гейт
  зелен всегда (075).

Неотвеченные проверки печатаются остатком очереди и красным **не** считаются:
`unreviewed` — объявленное состояние, а не дефект. Красное здесь — это
расхождение состава, а не незаконченный разбор.

Исходы (правило 039): ``0`` совпадает · ``2`` не отработало · ``3`` находки.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

import pipeline_checks as policy

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
#: Единицу отдаёт сам Python при необработанном сбое, поэтому объявленным
#: состоянием она быть не может: иначе сломанный механизм читается как
#: работающий. Объявленные исходы — 0, 2 и 3; всё прочее отказ (068).
EXIT_FINDINGS: Final = 3


def findings(
    checks: dict[str, policy.Check], jobs: dict[str, policy.Job], summary: str
) -> list[str]:
    """Собирает все расхождения состава, а не первое найденное."""
    found: list[str] = []

    for name in jobs:
        if name not in checks:
            found.append(
                f"{name}: проверка есть в дереве, ответа нет. Новая проверка не становится "
                f"обязательной молча — назовите класс, хотя бы «{policy.UNREVIEWED}»"
            )

    for name, check in checks.items():
        if name == summary:
            found.append(
                f"{name}: сводный гейт не отвечает сам за себя — его класс задан построением"
            )
            continue
        if name not in jobs:
            found.append(
                f"{name}: ответ есть, а проверки в дереве нет. Сводный гейт ждал бы записи, "
                "которую никто не выдаёт"
            )
            continue
        if check.holds_merge and jobs[name].matrix:
            found.append(
                f"{name}: обязательной объявлена матрица. На голове появятся имена ячеек "
                f"(«{name} (…)»), а имени «{name}» не будет ни одного"
            )

    if not any(check.holds_merge for check in checks.values()):
        found.append(
            "ни одной обязательной проверки: сводный гейт был бы зелёным всегда — "
            "это ошибка входа, а не «нечего держать» (075)"
        )
    return found


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет ответ с деревом и печатает вердикт."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=str(policy.DEFAULT_PATH), help="ответ по проверкам")
    parser.add_argument("--workflows", default=str(policy.WORKFLOWS), help="каталог прогонов")
    parser.add_argument("--self-name", default="ci-complete", help="имя сводного гейта")
    args = parser.parse_args(argv)

    try:
        checks = policy.load(Path(args.policy))
        jobs = policy.declared_jobs(Path(args.workflows), skip=args.self_name)
    except policy.BadPolicy as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    problems = findings(checks, jobs, args.self_name)
    if problems:
        print(f"находки ({len(problems)}):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return EXIT_FINDINGS

    queue = policy.names_of(checks, policy.UNREVIEWED)
    required = policy.names_of(checks, policy.REQUIRED)
    advisory = policy.names_of(checks, policy.ADVISORY)
    disabled = policy.names_of(checks, policy.OFF)
    print(
        f"совпадает: {len(jobs)} проверок дерева, ответ дан по каждой.\n"
        f"  держат слияние: {', '.join(required)}\n"
        f"  совещательные:  {', '.join(advisory) or '—'}\n"
        f"  выключены:      {', '.join(disabled) or '—'}\n"
        f"  в очереди разбора: {', '.join(queue) or '—'}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
