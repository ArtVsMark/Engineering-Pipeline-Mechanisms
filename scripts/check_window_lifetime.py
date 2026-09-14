#!/usr/bin/env python3
"""Срок жизни окна, открывшего изменение, — величина, а не память человека.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ СТРОКА СВОДА. Правило
[006](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/006-window-lifetime.md)
держалось у нас документом, и причиной отказа стоял замер, утверждавший, что
следа окна в дереве нет вовсе. Дерево этого не подтверждает: трейлер
``Claude-Session`` несёт номер окна в 309 коммитах из 340, и срок жизни окна из
него читается — замер 14.09.2026 дал у трёх окон 2 часа, 7 часов и 4 суток
13 часов. Ответ «механизма нет и быть не может» стоял на непроверенной премисе
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md),
[146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md));
нашёл это внешний взгляд находкой `51a6454` на #335, а разбор показал, что
причина названа неверно — механизму здесь есть на чём стоять.

ГЕЙТ НЕ РЕШАЕТ ЗА ЧЕЛОВЕКА, КОГДА ПЕРЕЗАПУСКАТЬ ОКНО. Свод говорит прямо: срок
держится строкой и решает его человек. Поэтому шаг НАЗЫВАЕТ величину и называет
превышение — он не объявляет работу негодной и не отменяет её. Класс проверки
поэтому и не обязательный: красное, которое правкой изменения не чинится,
загоняло бы окно в починку неисправимого — своё красное идёт источником 2, и
окно чинило бы его до предела попыток
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

ПРЕДМЕТ ЕСТЬ ТОЛЬКО ТАМ, ГДЕ РАБОТАЛО ОКНО. Изменение без соавтора-окна правилу
006 не подчиняется: у руки человека срока жизни сессии нет. Это состояние
названо словом и даёт чистый исход, а не третий — отсутствие предмета здесь
законно, в отличие от гейта, которому предмет обязан найтись
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

А ВОТ ОКНО БЕЗ СЛЕДА — ТРЕТИЙ ИСХОД, И ИМЕННО ЭТИМ ТРЕЙЛЕР СТАНОВИТСЯ
ОБЯЗАТЕЛЬНЫМ. Гейт `attribution` подключён действием каталога и требует
соавторства, а трейлер сессии не требует никто: он стоит потому, что его
подставляет среда. Механизм на привычке среды — это механизм без договора, и
здесь он объявляет нехватку входа вслух, вместо того чтобы зеленеть на ней
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Переписывать сюда чужой гейт атрибуции ради одной строки нельзя — копия
разъехалась бы с оригиналом
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ОБРЕЗАННАЯ ИСТОРИЯ НЕ СЧИТАЕТСЯ МОЛОДЫМ ОКНОМ. В мелком клоне начало окна не
видно, и срок вышел бы короче настоящего — то есть гейт зеленел бы тем охотнее,
чем меньше знает. Разбор этого — в ``scripts/window.py``.

Исходы (правило 039): ``0`` окно в пределах срока или предмета нет ·
``1`` окно пережило предел · ``2`` не отработал: нет входа или истории.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

import window

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2


def main(argv: list[str] | None = None) -> int:
    """Точка входа: срок жизни окон, стоящих за этим изменением."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="база изменения")
    parser.add_argument("--head", default="HEAD", help="голова изменения")
    parser.add_argument(
        "--history",
        default="origin/main",
        help="что считать историей: в ней ищется начало окна",
    )
    parser.add_argument("--root", type=Path, default=None, help="корень дерева")
    args = parser.parse_args(argv)
    cwd = str(args.root) if args.root else None

    try:
        mine = window.commits(f"{args.base}..{args.head}", cwd=cwd)
    except window.NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not mine:
        print(
            f"шаг не отработал: между {args.base} и {args.head} коммитов нет — "
            "предмета проверки не нашлось (075)",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    by_window = [commit for commit in mine if window.made_by_window(commit.message)]
    if not by_window:
        print(
            f"предмета нет: ни один из {len(mine)} коммитов не подписан окном — "
            "правило 006 не о нём"
        )
        return EXIT_OK

    trackless = [commit for commit in by_window if commit.session is None]
    if trackless:
        print(
            f"шаг не отработал: окно подписало {len(by_window)} коммитов, "
            f"а трейлера Claude-Session нет у {len(trackless)} из них "
            f"(первый — {trackless[0].sha[:7]}). Срок жизни окна считать не из чего (045)",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    head = by_window[-1]
    sessions = sorted({commit.session for commit in by_window if commit.session})
    try:
        ages = [window.lifetime(name, args.history, head, cwd=cwd) for name in sessions]
    except window.NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    cut = [age for age in ages if not age.whole]
    if cut:
        print(
            "шаг не отработал: история обрезана, и начало окна "
            f"{cut[0].session} в ней не видно — срок вышел бы короче настоящего (045)",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    over = [age for age in ages if age.over_limit]
    for age in ages:
        note = ""
        if age.over_limit:
            note = f" — ПЕРЕЖИЛО предел {window.LIMIT_DAYS} сут"
        elif age.near_limit:
            note = f" — подходит к пределу {window.LIMIT_DAYS} сут"
        print(f"{age.session}: {window.said_age(age.age)}{note} (с {age.first.sha[:7]})")

    if over:
        print(
            f"окон за пределом срока: {len(over)}. Правило 006 просит перезапуска, "
            "и решает его человек: шаг называет величину, а не отменяет работу."
        )
        return EXIT_FOUND

    print(f"в пределах срока: окон {len(ages)}, предел {window.LIMIT_DAYS} сут")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
