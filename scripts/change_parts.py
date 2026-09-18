#!/usr/bin/env python3
"""На сколько частей распадается изменение: считает, а не напоминает.

Граница изменения задаётся ПЕРЕСЕЧЕНИЕМ ФАЙЛОВ, а не числом находок или задач:
число находок одного захода — свойство ревьюера, а не работы
([133](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/133-file-overlap-sets-the-boundary.md)).

ПОЧЕМУ ЭТО СЧЁТ, А НЕ ГЕЙТ, И ПОЧЕМУ ГЕЙТА НЕ БУДЕТ. Признак замерен и ОТВЕРГНУТ
как гейт: решение 008 разрешает везти хвост мелких правок одним изменением, а
правило 132 — широкую тему, которая неделима. Сигнал срабатывал бы на каждом
четвёртом заходе, большинство из которых законны, и проверка, краснеющая на
законном, приучает себя обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Поэтому здесь ЧИСЛО, которое видно, а решение остаётся за автором.

ЗАМЕР 18.09.2026, РАДИ КОТОРОГО МЕХАНИЗМ И НАПИСАН: окно закрыло восемь находок
одним изменением, и дифф распался бы на ЧЕТЫРЕ компоненты. Навык, велящий резать
по пересечению, лежал в дереве и говорил ровно это — но словами, которые надо
помнить, а не числом, которое видно
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

Исходы (правило 039): ``0`` части названы · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from typing import Final

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Механизм не отработал: третий исход, а не «изменение цельное»."""


def _git(*args: str) -> str:
    """Запуск git; отказ — третий исход, а не пустой ответ (075)."""
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def touched(base: str) -> list[list[str]]:
    """Файлы каждого коммита ветки: внутри списка они связаны одним коммитом.

    ПУТИ ЧИТАЮТСЯ ПО NUL, А НЕ ПО ПЕРЕВОДУ СТРОКИ. Без `-z` git экранирует имена
    с пробелами и не-ASCII, построенный путь не разрешается, и файл молча
    выпадает из счёта — а счёт частей на неполном списке даёт правдоподобное
    число
    ([165](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/165-git-file-list-needs-nul.md)).
    В дереве таких имён полно: сами механизмы названы по-русски.
    """
    shas = _git("log", "--format=%H", f"{base}..HEAD").split()
    if not shas:
        raise NotRun(f"между {base} и HEAD коммитов нет — предмет счёта не найден (075)")
    return [
        [name for name in _git("show", "--name-only", "--format=", "-z", sha).split("\0") if name]
        for sha in shas
    ]


def parts(commits: list[list[str]]) -> list[list[str]]:
    """Компоненты связности: файлы, связанные через общие коммиты."""
    parent: dict[str, str] = {}

    def root(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for files in commits:
        # КАЖДЫЙ ФАЙЛ РЕГИСТРИРУЕТСЯ, А НЕ ТОЛЬКО СВЯЗАННЫЙ. Первая редакция
        # шла по `files[1:]` и трогала `parent` лишь при двух файлах в коммите:
        # коммит с ОДНИМ файлом исчезал целиком, и изменение из таких коммитов
        # отвечало «считать нечего» вместо честного числа частей (075).
        for name in files:
            root(name)
        for name in files[1:]:
            parent[root(files[0])] = root(name)
    grouped: dict[str, list[str]] = defaultdict(list)
    for name in parent:
        grouped[root(name)].append(name)
    if not grouped:
        raise NotRun("ни один коммит ветки не тронул файлов — считать нечего (075)")
    return sorted((sorted(names) for names in grouped.values()), key=lambda one: (-len(one), one))


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает части изменения и что с ними делать."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="с чем сравнивать")
    args = parser.parse_args(argv)
    try:
        found = parts(touched(args.base))
    except NotRun as refusal:
        print(f"части не сосчитаны: {refusal}", file=sys.stderr)
        return EXIT_BROKEN

    print(f"файлов {sum(len(one) for one in found)}, частей {len(found)}")
    for number, names in enumerate(found, 1):
        print(f"  {number}. {', '.join(names)}")
    if len(found) == 1:
        print("\nодна часть — граница по пересечению файлов соблюдена (133)")
        return EXIT_OK
    print(
        "\nчастей больше одной. Либо разрежьте изменение, либо НАЗОВИТЕ В ЗАПИСИ,"
        " почему везёте одним:\nрешение 008 разрешает хвост мелких правок, правило 132 —"
        " широкую тему, которая неделима.\nМолча везти нельзя: снаружи «одна широкая тема» и"
        " «слепил по счёту находок» неотличимы."
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — точка входа процессом
    raise SystemExit(main())
