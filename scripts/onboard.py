#!/usr/bin/env python3
"""Команда подключения: собирает потребителю заготовку вызова, а не инструкцию.

ОТДАЁТСЯ НАРУЖУ: этим заходом проект подключают к себе.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ АБЗАЦ В README. Порядок подключения, живущий прозой,
исполняется по-разному каждым, кто его прочёл: один забудет объявить класс
проверки, другой напишет имя записи голым, третий прибьётся к подвижной метке
вместо версии. Ровно так и разошлись пять конвейеров семьи — замер 09.09.2026:
десять повторяющихся имён прогонов, и **ни одна пара копий не совпала**
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

СОСТАВ ВЫВОДИТСЯ ИЗ ДЕРЕВА, А НЕ ПЕРЕЧИСЛЯЕТСЯ ЗДЕСЬ. Шаги берутся те, что
помечены маркером «отдаётся наружу» (`scripts/check_shipped.py`), прибивка —
тег ВЫПУСКА из истории (`pin_of` ниже говорит, почему не `CONTRACT_VERSION`).
Второй список тех же имён отстал бы на первом же вынесенном
шаге, и отстал бы молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

ИМЯ ЗАПИСИ ПРОВЕРКИ СОСТАВНОЕ, И ЗАГОТОВКА НАЗЫВАЕТ ЕГО ПРАВИЛЬНО. Площадка
зовёт запись вызванного джоба `<имя вызывающего> / <имя вызванного>` — замер
прогоном на живой площадке. Потребитель, написавший в своём ответе голое имя,
получил бы сводный гейт, ждущий записи, которой никто не выдаст
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЗАГОТОВКА НЕ РЕШАЕТ ЗА ПОТРЕБИТЕЛЯ, КАКОЙ КЛАСС У ПРОВЕРКИ. Класс — свойство
потребителя, а не механизма: объём документа обязателен там, где документ
выпускается наружу, и совещателен там, где он внутренний
(174).
Поэтому все шаги выходят с классом «в очереди разбора» — объявленным
состоянием, а не молчанием, — и потребитель отвечает по каждому сам.

ЗАГОТОВКА НЕ ПЕЧАТАЕТСЯ, ПОКА ПРИБИВКА ЕЁ НЕ НЕСЁТ. Вызов по адресу с
версией работает ровно тогда, когда названный тег этот файл содержит, и это
НЕ следует из того, что файл лежит у нас: работа слита, выпуск не нарезан —
самый обычный день. Замер 20.09.2026: помечено наружу одиннадцать файлов, в
выпуске `v1.1.0` их ноль, то есть заготовка была нерабочей целиком, и узнал
бы об этом потребитель на СВОЁМ красном
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Третий исход называет предмет: нарезать выпуск
([158](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/158-the-third-outcome-names-its-subject.md)).

ЧЕГО ЗАХОД НЕ ДЕЛАЕТ: не пишет в чужое дерево и не трогает защиту ветки.
Первое — чужая работа, второе живёт вне дерева вовсе. Заход печатает, а
потребитель кладёт; иначе «подключено» и «подправлено на ходу» стали бы
неотличимы.

Исходы (правило 039): ``0`` заготовка собрана · ``2`` не отработал ·
``3`` отдавать нечего: ни один шаг не помечен · ``4`` прибивка не несёт
помеченного: выпуск отстал от дерева.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

import check_shipped
import paths
import pipeline_checks as policy
import version

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_NOTHING: Final = 3
#: Прибивка есть, а помеченного в ней нет. Отдельный исход, а не «нечего
#: отдавать»: предмет тот же, причина и выход РАЗНЫЕ (039, 104).
EXIT_UNREACHABLE: Final = 4

#: Приставка вынесенного шага. Помеченным бывает и не шаг — пакет, действие, —
#: а заготовку вызова собирают только из прогонов, которые ЗОВУТ.
STEP_PREFIX: Final = "step-"
#: Что читается ответом «выпусков ещё не было». Пустота тут законна и обязана
#: быть названа, а не выдана за версию (154).
NO_RELEASE: Final = "выпусков ещё не было"


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не пустая заготовка."""


def steps(root: Path) -> list[str]:
    """Имена вынесенных шагов — из пометок дерева, а не списком.

    Имя шага — это имя его файла без приставки и расширения, и оно же имя
    джоба внутри: составное имя записи собирается из них двоих.
    """
    found = [
        Path(said).stem[len(STEP_PREFIX) :]
        for said in check_shipped.shipped(root)
        if Path(said).name.startswith(STEP_PREFIX) and Path(said).suffix in {".yml", ".yaml"}
    ]
    return sorted(found)


def pin_of(root: Path) -> str:
    """Тег ВЫПУСКА, к которому прибивается потребитель, — из истории.

    НЕ `CONTRACT_VERSION`, И РАЗНИЦА СТОИЛА БЫ НЕРАБОЧЕЙ ЗАГОТОВКИ. Там лежит
    версия ПОВЕРХНОСТИ, а выпуски помечены своими тегами, и это РАЗНЫЕ числа:
    прибивка к первой указала бы на тег, которого нет, и вызов
    отказал бы у потребителя, а не у нас
    ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).

    Тег читается ТЕМ ЖЕ разбором, что у механизма версии: второй разбор той же
    формы — это второе её понимание, и расходятся они молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    tag = version.release_tag(root or None)
    if tag is None:
        raise NotRun(
            f"{NO_RELEASE}: прибиваться потребителю не к чему. Заготовка с подвижной"
            " меткой вместо версии меняла бы у него исполняемый код без его ведома (152)"
        )
    return tag


def caller(name: str, repo: str, pin: str) -> str:
    """Джоб вызывающего для одного шага — то, что потребитель кладёт к себе."""
    return (
        f"  {name}:\n"
        f"    name: {name}\n"
        f"    uses: {repo}/.github/workflows/{STEP_PREFIX}{name}.yml@{pin}\n"
        f"    permissions:\n"
        f"      contents: read\n"
        f"      checks: read\n"
        f"      pull-requests: read\n"
        f"      issues: read\n"
    )


def check_name(name: str) -> str:
    """Имя записи проверки, которое выдаст площадка, — составное."""
    return f"{name}{policy.COMPOSED}{name}"


def answer(names: list[str]) -> str:
    """Заготовка ответа потребителя: по строке на проверку, класс — не решён.

    `unreviewed` здесь не заглушка, а объявленная очередь разбора: молча
    обязательной проверка не становится, и молча совещательной тоже.
    """
    rows = "\n".join(f'  "{check_name(one)}": {policy.UNREVIEWED}' for one in names)
    return f"checks:\n{rows}\n"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает заготовку вызова и заготовку ответа."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень ЭТОГО дерева")
    parser.add_argument(
        "--repo",
        default="ArtVsMark/Engineering-Pipeline-Mechanisms",
        help="откуда потребитель зовёт шаги",
    )
    args = parser.parse_args(argv)

    try:
        names = steps(args.root)
        pin = pin_of(args.root)
    except (NotRun, check_shipped.NotRun) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not names:
        print(
            "отдавать нечего: ни один шаг не помечен как отдаваемый наружу — "
            "подключать не к чему, и это состояние, а не заготовка (075)",
            file=sys.stderr,
        )
        return EXIT_NOTHING

    # СВЕРКА ИДЁТ ДО ПЕЧАТИ, А НЕ ПОСЛЕ. Напечатанную заготовку забирают
    # целиком; предупреждение под ней читают не все, а вызов по адресу,
    # которого по названному тегу нет, отказывает у потребителя.
    try:
        missing = check_shipped.unreleased(pin, args.root)
    except (NotRun, check_shipped.NotRun) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if missing:
        print(
            f"прибивка «{pin}» не несёт помеченного наружу: {len(missing)} из "
            f"{len(check_shipped.shipped(args.root))} — {', '.join(missing)}.\n"
            "Заготовка с такой прибивкой отказала бы у потребителя, а не у нас (045).\n"
            f"Выход: нарезать выпуск, содержащий эти файлы, и позвать заход заново (158).",
            file=sys.stderr,
        )
        return EXIT_UNREACHABLE

    print(f"# шагов к подключению: {len(names)} · прибивка: {pin}\n")
    print(f"# 1. В свой `{paths.WORKFLOWS}/ci.yml` — джобы вызова:\n")
    print("jobs:")
    print("\n".join(caller(one, args.repo, pin) for one in names))
    print(f"# 2. В свой `{paths.PIPELINE}` — ответ по каждой проверке.")
    print("#    Класс — СВОЙ выбор: `required`, `advisory` или `off` с причиной.")
    print(f"#    Здесь все выходят «{policy.UNREVIEWED}»: это очередь разбора, а не умолчание.\n")
    print(answer(names))
    print("# 3. В защиту ветки — ОДНО имя: имя своего сводного гейта.")
    print("#    Перечислять здесь шаги нельзя: список ломается добавлением версии")
    print("#    в матрицу, и защита начинает ждать имя, которого никто не выдаёт (168).")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
