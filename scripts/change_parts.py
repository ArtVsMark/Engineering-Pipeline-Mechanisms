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

ПРЕДУПРЕЖДЕНИЕ В КОНВЕЙЕРЕ — СТУПЕНЬ 051, КОТОРУЮ ГЕЙТ ПЕРЕСКОЧИЛ БЫ (#860).
Отказались от красного, а не от сигнала: с ключом `--warn` счёт идёт джобом
`parts` на каждом изменении и печатает `::warning::`, когда частей больше
одной. Слияние он не держит; предупреждение называет решение 008, чтобы
законное смешение отличалось от слепленного по счёту находок.

ЗАМЕР 18.09.2026, РАДИ КОТОРОГО МЕХАНИЗМ И НАПИСАН: окно закрыло восемь находок
одним изменением, и дифф распался бы на ЧЕТЫРЕ компоненты. Навык, велящий резать
по пересечению, лежал в дереве и говорил ровно это — но словами, которые надо
помнить, а не числом, которое видно
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ПУСТОЙ КОММИТ — СОСТОЯНИЕ, А НЕ ОТКАЗ, и разница стоила красного на
обязательной проверке. Коммит с `--allow-empty` законен: им отмечают пункт
задачи трейлером, не трогая файлов. Прежде такой коммит давал «считать
нечего» вторым исходом, и проверка живого дерева краснела по причине, к
работе отношения не имеющей — то есть механизм краснел на законном
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Нашёл внешний взгляд на #562.

ОТКАЗ ПРИ ЭТОМ ОСТАЁТСЯ ОТКАЗОМ: коммитов нет вовсе — вход не найден, и
«ноль частей» звучало бы вердиктом о работе, которой не видно (045, 075).
Разница именно в этом: пустой вход и пустой РЕЗУЛЬТАТ — разные ответы.

Исходы (правило 039): ``0`` части названы · ``2`` не отработал ·
``3`` изменение не тронуло файлов: считать нечего, и это сказано.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from typing import Final

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
#: Файлов не тронуто ни одного. Своё имя, а не «не отработал»: предмета нет
#: по законной причине, и выход из этого другой (039).
EXIT_NOTHING: Final = 3


class NotRun(RuntimeError):
    """Механизм не отработал: третий исход, а не «изменение цельное»."""


def _git(*args: str) -> str:
    """Запуск git; отказ — третий исход, а не пустой ответ (075)."""
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def files_of(sha: str) -> list[str]:
    """Файлы одного коммита — ПРОТИВ ПЕРВОГО РОДИТЕЛЯ, а не комбинированно.

    У merge-коммита `git show --name-only` печатает КОМБИНИРОВАННЫЙ дифф: только
    файлы, отличные от ОБОИХ родителей. Совпавшее с одним из них выпадает молча,
    и счёт частей на таком списке отвечает правдоподобным числом
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Замер 18.09.2026 по трём слияниям дерева: комбинированный дал НОЛЬ файлов
    там, где против первого родителя их четыре и два. Нашёл внешний взгляд.

    ПУТИ ЧИТАЮТСЯ ПО NUL: без `-z` git экранирует имена с не-ASCII, и файл молча
    выпадает из счёта
    ([165](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/165-git-file-list-needs-nul.md)).
    В дереве такие имена — норма: механизмы названы по-русски.
    """
    # КОММИТ БЕЗ РОДИТЕЛЯ ЧИТАЕТСЯ, А НЕ ОТВЕРГАЕТСЯ. `sha^` у него не
    # разрешается вовсе, и git отвечает «unknown revision» — то есть отказом
    # входа там, где предмет есть и читается. Такой коммит бывает не только
    # корнем дерева: в МЕЛКОМ клоне граничный коммит выглядит так же, а мелким
    # клонирует облачное окно и чужой прогон.
    parents = _git("rev-list", "--parents", "-n", "1", sha).split()[1:]
    if parents:
        said = _git("diff", "--name-only", "-z", f"{sha}^", sha)
    else:
        said = _git("diff-tree", "-r", "--no-commit-id", "--name-only", "-z", "--root", sha)
    return [name for name in said.split("\0") if name]


def touched(base: str) -> list[list[str]]:
    """Файлы каждого коммита ветки: внутри списка они связаны одним коммитом.

    СЛИЯНИЯ ИЗ СПИСКА ИСКЛЮЧЕНЫ. Дифф merge-коммита против первого родителя
    есть ровно ЧУЖАЯ работа — всё, что принесла слитая общая ветка, — и граница
    изменения на таком списке считается по чужим файлам
    ([133](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/133-file-overlap-sets-the-boundary.md)).

    ЗАМЕР 19.09.2026, на живом изменении: после слияния общей ветки счёт назвал
    шесть файлов, из которых два автор не трогал вовсе. Нашёл внешний взгляд
    (`5954abc`), а подтвердилось это в тот же день своей работой.

    БАЗА ОБЯЗАНА БЫТЬ СВЕЖЕЙ, и это условие, а не пожелание: коммиты общей
    ветки отсекаются тем, что достижимы из неё. Отстала база — её коммиты,
    слитые в ветку, снова попадут в счёт. Флагом это не чинится:
    `--first-parent` отсекал бы их, но на голове изменения у площадки стоит
    merge-коммит, чей ПЕРВЫЙ родитель — общая ветка, и проход по первой линии
    уводит мимо всей работы автора. Замер того же дня: с ним список пуст, без
    него — верен.
    """
    shas = _git("log", "--format=%H", "--no-merges", f"{base}..HEAD").split()
    if not shas:
        raise NotRun(f"между {base} и HEAD своих коммитов нет — предмет счёта не найден (075)")
    return [files_of(sha) for sha in shas]


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
    if not commits:
        raise NotRun("коммитов на входе нет — считать нечего (075)")
    grouped: dict[str, list[str]] = defaultdict(list)
    for name in parent:
        grouped[root(name)].append(name)
    # Пустой СПИСОК — не отказ: коммиты были, файлов не тронули. Отвечает за
    # разницу зовущий, а здесь она просто не стирается.
    return sorted((sorted(names) for names in grouped.values()), key=lambda one: (-len(one), one))


#: Решение, разрешающее везти хвост мелких правок одним изменением.
DECISION_008: Final = "docs/decisions/008-a-batch-of-corrections-is-one-subject.md"


def warning(count: int) -> str:
    """Аннотация площадки: изменение распалось, и чем законное отличается от ошибки."""
    return (
        f"::warning title=изменение из {count} частей (133)::"
        f"дифф распался на {count} несвязанных частей (файлы связаны, если тронуты одним "
        "коммитом). Законно, если это хвост мелких правок (решение 008, "
        f"{DECISION_008}) или неделимая широкая тема (132) — тогда назовите это в записи; "
        "иначе разрежьте изменение по пересечению файлов. Слияние это не держит."
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает части изменения и что с ними делать."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="с чем сравнивать")
    parser.add_argument(
        "--warn", action="store_true", help="частей больше одной — аннотация ::warning:: (#860)"
    )
    args = parser.parse_args(argv)
    try:
        found = parts(touched(args.base))
    except NotRun as refusal:
        print(f"части не сосчитаны: {refusal}", file=sys.stderr)
        return EXIT_BROKEN

    if not found:
        print(
            "изменение не тронуло файлов: считать нечего. Так выглядит пустой коммит —"
            " например, отмечающий пункт задачи трейлером, — и это состояние, а не отказ"
        )
        return EXIT_NOTHING

    print(f"файлов {sum(len(one) for one in found)}, частей {len(found)}")
    for number, names in enumerate(found, 1):
        print(f"  {number}. {', '.join(names)}")
    if len(found) == 1:
        print("\nодна часть — граница по пересечению файлов соблюдена (133)")
        return EXIT_OK
    if args.warn:
        print(warning(len(found)))
    print(
        "\nчастей больше одной. Либо разрежьте изменение, либо НАЗОВИТЕ В ЗАПИСИ,"
        " почему везёте одним:\nрешение 008 разрешает хвост мелких правок, правило 132 —"
        " широкую тему, которая неделима.\nМолча везти нельзя: снаружи «одна широкая тема» и"
        " «слепил по счёту находок» неотличимы."
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — точка входа процессом
    raise SystemExit(main())
