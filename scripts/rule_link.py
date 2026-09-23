#!/usr/bin/env python3
"""Ссылка на правило каталога — СПРАШИВАЕТСЯ, а не вспоминается.

ЗАЧЕМ ЭТО ЕСТЬ. Номер правила окно помнит верно, а имя файла — нет: за смену
20–21.09.2026 гейт `check_rule_links` отверг ДЕВЯТЬ выдуманных слагов, среди
них `155-an-unused-stub-drifts` вместо `a-template-you-dont-use-drifts` и
полностью несуществующее `104-a-refusal-names-the-way-out`. Девятый нашёлся
внутри докстроки ЭТОГО шага — он же его и починил.

ЦЕНА НЕ В ПРОПУЩЕННОЙ ОШИБКЕ, А В ЦИКЛЕ. Гейт ловит каждый случай — механизм
исправен. Но ссылка пишется в фрагмент журнала или в пояснение, гейт зовётся
предполётной В КОНЦЕ, и один промах стоит полного повторного захода: набор,
формат, типы, восемнадцать проверок дерева. За смену это девять лишних циклов
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

СООТВЕТСТВИЕ БЕРЁТСЯ У ГЕЙТА, А НЕ ПИШЕТСЯ ЗАНОВО. `check_rule_links.known()`
уже читает «номер → слаг» из выгрузки каталога, и сверяется гейт именно с ним.
Второй источник того же разошёлся бы с первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ЧЕГО ЭТОТ ШАГ НЕ ДЕЛАЕТ: не проверяет, уместна ли ссылка. Цитата проверяется
применимостью, и это суждение
([204](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/204-a-citation-is-checked-by-applicability.md)).
Здесь убирается цена промаха в ИМЕНИ, а не привычка ссылаться по памяти.

Исходы (правило 039): ``0`` ссылка напечатана · ``1`` такого правила в каталоге
нет · ``2`` шаг не отработал · ``4`` каталог молчит.
"""

from __future__ import annotations

import argparse
import sys
from typing import Final

import catalogue
import check_rule_links

EXIT_OK: Final = 0
EXIT_UNKNOWN: Final = 1
EXIT_BROKEN: Final = 2
#: Каталог не ответил — свой исход, как у гейта: молчание канала говорит о
#: сети, а не о нашем дереве, и выдавать его за «правила нет» значило бы
#: отправить автора искать несуществующую ошибку (045, решение 027).
EXIT_SILENT: Final = 4

#: Человекочитаемый адрес файла правила. Сырой адрес выгрузки для ссылки не
#: годится: её читает человек, а не механизм.
BLOB: Final = f"https://github.com/{catalogue.REPO}/blob/main/rules/ru"


def link(number: str, slugs: dict[str, str]) -> str:
    """Готовая markdown-ссылка на правило — ровно в том виде, какой ждёт гейт.

    Номер приводится к трём знакам: автор пишет «5», «05» и «005» одинаково
    охотно, а в каталоге он всегда трёхзначный.
    """
    said = number.strip().lstrip("#").zfill(3)
    slug = slugs.get(said)
    if not slug:
        raise LookupError(said)
    return f"[{said}]({BLOB}/{said}-{slug}.md)"


def main(argv: list[str] | None = None) -> int:
    """Печатает ссылку на правило по его номеру."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("number", nargs="+", help="номер правила, можно несколько")
    args = parser.parse_args(argv)

    try:
        slugs = check_rule_links.known()
    except catalogue.Silent as exc:
        # Молчание канала НЕ превращается в «правила нет»: у него свой исход.
        print(f"каталог молчит: {exc}", file=sys.stderr)
        return EXIT_SILENT
    except check_rule_links.NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    missing: list[str] = []
    for one in args.number:
        try:
            print(link(one, slugs))
        except LookupError as exc:
            missing.append(str(exc))
    if missing:
        # ОТКАЗ НАЗЫВАЕТ ПРЕДМЕТ, а не отдаёт правдоподобную выдумку: номер,
        # которого в каталоге нет, — это либо опечатка, либо правило, которого
        # ещё не предложили (154).
        print(
            "в выгрузке каталога нет правил: " + ", ".join(missing),
            file=sys.stderr,
        )
        return EXIT_UNKNOWN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
