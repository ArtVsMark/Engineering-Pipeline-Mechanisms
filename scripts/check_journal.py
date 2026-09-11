#!/usr/bin/env python3
"""Гейт: изменение несёт фрагмент журнала.

Правило 030: журнал собирается из фрагментов, и фрагмент едет **вместе с
изменением**, а не пишется после выпуска по памяти. Гейт держит именно это:
изменение, тронувшее что-либо кроме журнала и производных файлов, обязано
принести фрагмент.

Правило 154: ответ «журналу это безразлично» — состояние, а не молчание.
Выражается фрагментом рода ``internal``, ПЕРВАЯ строка которого называет
причину в заданной форме: ``> **Потребителю безразлично:** …``. Форму держит
разбор фрагментов (``scripts/build_changelog.py``), один на обоих читателей.

Гейт судит по **коммитам**, а не по рабочему дереву: в прогоне на изменении
всё уже зафиксировано, и рабочего дерева там нет вовсе. Локально это значит,
что фрагмент надо закоммитить, а не только положить рядом.

Исходы (правило 039): ``0`` фрагмент есть · ``1`` изменение отвергнуто ·
``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import sys
from typing import Final

import journal

FRAGMENT_RE: Final = journal.PATH_RE
# Тронув только это, изменение журналу ничего не сообщает.
EXEMPT_PREFIXES: Final = ("changelog.d/",)
EXEMPT_FILES: Final = frozenset({"CHANGELOG.md"})
#: Где живут механизмы: правка здесь меняет поведение, а не текст.
CODE_PREFIXES: Final = ("scripts/", ".github/workflows/")
#: Где живут проверки.
TESTS_PREFIX: Final = "tests/"
#: Род записи, означающий починку дефекта.
FIXED: Final = "fixed"

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2


#: Отказ чтения дифа приходит из общего модуля: у гейта он остаётся третьим
#: исходом, а разбор его — один на всех читателей.
NotRun = journal.NotRun


def numbered(path: str) -> bool:
    """Назван ли фрагмент номером задачи, а не смыслом записи."""
    match = journal.NAME_RE.match(path.rsplit("/", 1)[-1])
    return bool(match and journal.DIGITS_ONLY_RE.match(match.group("slug")))


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    # Площадка отдаёт базу коротким именем («main»), а в дереве прогона она
    # существует как `origin/main`, поэтому приставка нужна. Но ставится она
    # ТОЛЬКО к умолчанию из окружения: переданное ключом имя — это то, что
    # имел в виду зовущий, и молча переписывать его нельзя. Ровно на этом гейт
    # и упал в первом же прогоне на площадке — локально переменной нет, и
    # расхождение не воспроизводилось.
    parser.add_argument("--base", default=journal.base_from_env(), help="ветка сравнения")
    args = parser.parse_args(argv)

    try:
        files = journal.changed_files(args.base)
    except NotRun as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # Охват называется до вердикта: проверка, читающая список путей, без числа
    # неотличима от чистого результата (165).
    exempt = [name for name in files if name in EXEMPT_FILES or name.startswith(EXEMPT_PREFIXES)]
    print(f"тронутых путей прочитано: {len(files)}, из них журнальных: {len(exempt)}")

    # ФРАГМЕНТОМ СЧИТАЕТСЯ ТОЛЬКО ВЫЖИВШИЙ ПУТЬ. Удалённого файла в голове нет:
    # засчитывать его за принесённую запись значит зеленеть на изменении,
    # которое запись УНЕСЛО, а своей не оставило. Ровно так уборка старого
    # фрагмента пронесла бы мимо гейта любую правку кода.
    try:
        alive = set(journal.changed_files(args.base, alive_only=True))
    except journal.NotRun as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    fragments = [name for name in alive if FRAGMENT_RE.match(name)]

    # ИМЯ ФРАГМЕНТА ГОВОРИТ, ЧТО ИЗМЕНИЛОСЬ, А НЕ КАКАЯ ЗАДАЧА. Одна задача
    # живёт дольше одного изменения, и два захода целятся в одно имя: конфликта
    # это не даёт — побеждает последний, и первая запись исчезает без следа и
    # без выпуска. Так была потеряна запись об исправлении атрибуции (#12).
    # Судится тот же выживший список: у удалённого имени спрашивать нечего.
    by_number = [name for name in fragments if numbered(name)]
    if by_number:
        print(
            "отвергнуто: фрагмент назван номером задачи, а не смыслом: "
            f"{', '.join(by_number)}\n\n"
            "Одна задача живёт дольше одного изменения, и второй заход перезапишет\n"
            "первый молча — конфликта тут не бывает. Имя берётся от того, ЧТО\n"
            "изменилось: changelog.d/README.md.",
            file=sys.stderr,
        )
        return EXIT_REJECTED

    # ПОЧИНКА ПРИНОСИТ ПРОВЕРКУ, ИНАЧЕ ОНА УБИРАЕТ ПОВЕДЕНИЕ, А НЕ ДЕФЕКТ.
    # Правило 014 требует: сначала замер на входе, где гейт зелен, а быть
    # должен красным, потом починка. Доказать дереву САМ замер нечем — гейт
    # видит зелёный набор и не видит, краснел ли он до правки, — и это названо
    # пробелом, а не выровнено (046). Проверяется половина, которая проверяема:
    # починка механизма без единой тронутой проверки не проходит.
    #
    # Замер 09.09.2026 по сорока последним коммитам общей ветки: починок,
    # тронувших механизм, — 15, и все пятнадцать принесли проверку. Гейт
    # закрепляет то, что уже соблюдается, а не вводит новое требование.
    fixing = [name for name in fragments if name.endswith(f".{FIXED}.md")]
    touches_code = [name for name in alive if name.startswith(CODE_PREFIXES)]
    touches_tests = any(name.startswith(TESTS_PREFIX) for name in alive)
    if fixing and touches_code and not touches_tests:
        print(
            "отвергнуто: починка не принесла ни одной проверки.\n\n"
            f"Род записи — «{FIXED}», тронуты механизмы: "
            f"{', '.join(touches_code[:5])}\n\n"
            "Починка доказывается входом, на котором гейт краснел до неё (014): без\n"
            "проверки убирается поведение, а не дефект, и вернуться он может молча.\n"
            "Если проверять нечем — род записи другой, и причина называется в ней.",
            file=sys.stderr,
        )
        return EXIT_REJECTED

    if fragments:
        print(f"фрагмент журнала есть: {', '.join(fragments)}")
        return EXIT_OK

    substantive = [
        name for name in files if name not in EXEMPT_FILES and not name.startswith(EXEMPT_PREFIXES)
    ]
    if not substantive:
        print("изменение тронуло только журнал и производные файлы — фрагмент не нужен")
        return EXIT_OK

    print(
        "отвергнуто: изменение не несёт фрагмента журнала.\n\n"
        "Тронуто файлов вне журнала: "
        f"{len(substantive)}, первые — {', '.join(substantive[:5])}\n\n"
        "Положите changelog.d/<что-изменилось>.<род>.md. Если потребителю это\n"
        "безразлично — род `internal`, и ПЕРВОЙ строкой идёт причина в форме\n"
        "«> **Потребителю безразлично:** …»: молчание состоянием не является\n"
        "(154). Формат — changelog.d/README.md.",
        file=sys.stderr,
    )
    return EXIT_REJECTED


if __name__ == "__main__":
    raise SystemExit(main())
