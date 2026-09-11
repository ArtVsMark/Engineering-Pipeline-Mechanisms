#!/usr/bin/env python3
"""Свой прогон перед толчком: красное чинится здесь, а не по логам площадки.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ СТРОКА В СВОДЕ. Правило без механизма — пожелание
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
Строка «прогоните проверки перед толчком» держится памятью окна, а память —
первое, что теряется к концу смены. Цена красного толчка названа прямо: цикл
площадки и доверие ревьюера; один проверенный толчок дешевле трёх пробных.

ЧТО ЗАПУСКАЕТСЯ, БЕРЁТСЯ ИЗ ДЕРЕВА, А НЕ ПЕРЕЧИСЛЯЕТСЯ ЗДЕСЬ ЗАНОВО. Команды
читаются из шагов `ci.yml`: второй список тех же команд разошёлся бы с первым
молча, и разошёлся бы незаметно — обе стороны выглядели бы правдоподобно
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Поэтому добавленный в прогон гейт появляется здесь сам, а не через полгода.

ГРАНИЦА НАЗВАНА, А НЕ СГЛАЖЕНА. Часть проверок без площадки невыполнима:
атрибуция считается по истории относительно базы, разметка изменения читается у
площадки, внешний взгляд идёт чужим прогоном. Объявить их «пройденными
локально» значило бы завести тихий запасной путь
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Невыполнимое здесь называется НЕВЫПОЛНЕННЫМ и печатается списком — это не
«пропущено», а «проверит площадка».

Исходы (правило 039): ``0`` всё зелено · ``2`` шаг не отработал ·
``3`` есть красное, толкать рано.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import paths
import yaml

CI: Final = paths.WORKFLOWS / "ci.yml"

#: Команда шага прогона: строка, начинающаяся с зовомого инструмента. Читается
#: список РАЗРЕШЁННОГО (068): что не узнано, то не запускается, а называется.
RUNNABLE: Final = ("ruff ", "mypy ", "pytest", "python scripts/")
#: Подстановка площадки. Блок с ней локально не раскрывается, и запускать его
#: значит проверять не ту команду.
PLATFORM_MARK: Final = "${{"
#: Шаги, отложенные разбором с названной причиной. Заполняется КАЖДЫМ чтением
#: заново и печатается вместе с прочим невыполнимым: пропуск без имени
#: неотличим от «шага не было» (046).
#:
#: Прежде словарь копился между вызовами в одном процессе и требовал ручной
#: очистки в тесте — то есть механизм отвечал не про то дерево, которое у него
#: спросили, а про все, что он видел за жизнь процесса. Нашёл внешний взгляд
#: на #101.
UNRUNNABLE: Final[dict[str, str]] = {}
#: Шаги, которым нужна площадка: их команды сюда не берутся, а перечисляются
#: как невыполнимые. Ключ — начало команды, значение — почему.
NEEDS_PLATFORM: Final = {
    "python scripts/check_pr_meta.py": "разметку изменения читает площадка",
    "python scripts/debt.py": "долг читается из задач площадки",
    "python scripts/ci_complete.py": "опрашивает записи проверок на голове у площадки",
    # ФЕТЧ ДЕЛАЕТ СОСЕДНЯЯ СТРОКА ШАГА, А НЕ САМ СКРИПТ, и разница не
    # придирка: блок шага несёт `git fetch` с записью в
    # `refs/remotes/origin/<база>`, и запускать локально надо не скрипт, а
    # блок — то есть правку чужого дерева. Сам гейт поверхности прогоняется
    # руками (`python scripts/check_contract.py`) и базу берёт ту, что уже
    # есть. Прежняя запись приписывала фетч скрипту; нашёл внешний взгляд
    # на #123, а разбор самого шага — на #108.
    "python scripts/check_contract.py": "фетч базы делает соседняя строка шага, а не скрипт",
    # Локально канон берётся у `origin`, а он хранит написание клонировавшего:
    # регистр там не сверить, и половина гейта была бы вхолостую.
    "python scripts/check_own_name.py": "каноничное имя знает только площадка",
    # Имена правил читаются из выгрузки каталога по сети: локально её может не
    # быть, и падение говорило бы о канале, а не о ссылках.
    "python scripts/check_rule_links.py": "имена правил берутся из выгрузки каталога",
    # Нарисован ли артефакт на своей ветке, знает только площадка: в дереве его
    # нет и быть не должно — ровно в этом предмет правила 196.
    "python scripts/check_derived_refs.py": "нарисовано ли производное, знает площадка",
}


@dataclass(frozen=True, slots=True)
class Step:
    """Одна команда прогона: чем названа и что запускает."""

    name: str
    command: str


#: Проверки ПЕРЕД ТОЛЧКОМ, которых нет шагом прогона ни у кого. Это не второй
#: список тех же команд (022): в `ci.yml` их нет вовсе, потому что предмет у
#: них — ветка до открытия изменения. Приставка ветки и связь с задачей видны
#: на дереве целиком, а ловились до сих пор отказом `agent-pr` — то есть уже
#: после толчка. Замер 10.09.2026: три ветки подряд ушли без связи, и каждая
#: вернулась ни с чем: изменение не открылось, красного тоже не было.
BEFORE_PUSH: Final = (Step("ветка откроет изменение", "python scripts/agent_pr.py --dry-run"),)

#: Проверки прогона, у которых здесь нет команды вовсе: они живут не шагом с
#: командой, а действием площадки или чужим прогоном.
ELSEWHERE: Final = {
    "attribution": "считается по истории относительно базы изменения",
    "ci-complete": "опрашивает записи проверок на голове у площадки",
    "review": "идёт отдельным прогоном и чужим исполнителем",
    "automerge": "это само слияние, а не проверка перед ним",
}

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RED: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «всё зелено»."""


def steps(path: Path = CI) -> list[Step]:
    """Команды прогона, выполнимые без площадки, — в порядке объявления.

    Разбор идёт по ДЕРЕВУ, а не по строкам, и это не вкус. Команда шага живёт в
    блоке `run:` вместе с оболочечной обвязкой — `set -euo pipefail`,
    подготовкой базы, `git fetch`, — и строка, выдернутая из середины такого
    блока, запускается без неё. Итог выглядит как проверка, а проверяет другое:
    зелёное там, где площадка краснеет, и наоборот
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Замер — находка ревью по #94.

    Поэтому берётся ВЕСЬ блок шага, и берётся он целиком либо не берётся вовсе.
    """
    if not path.is_file():
        raise NotRun(f"нет {path}: список проверок взять неоткуда (075)")

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc
    if not isinstance(document, dict):
        raise NotRun(f"{path}: ожидалось отображение, пришло {type(document).__name__}")

    # Чтение начинается с чистого листа: отложенное относится к ЭТОМУ дереву.
    UNRUNNABLE.clear()
    found: list[Step] = []
    seen: set[str] = set()
    for job in (document.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            command = str((step or {}).get("run") or "").strip()
            name = str((step or {}).get("name") or "").strip()
            if not command or command in seen:
                continue
            if not any(line.strip().startswith(RUNNABLE) for line in command.splitlines()):
                continue
            # Площадка нужна блоку целиком, если её требует ХОТЯ БЫ одна его
            # строка: запустить остальное без неё значит проверить половину и
            # назвать это проверкой.
            if any(
                line.strip().startswith(prefix)
                for line in command.splitlines()
                for prefix in NEEDS_PLATFORM
            ):
                continue
            if PLATFORM_MARK in command:
                # Подстановка площадки локально не раскрывается: запустить блок
                # с ней значит проверить не ту команду. Названо, а не выкинуто
                # молча (046) — такие шаги перечисляет `report_gaps`.
                UNRUNNABLE[name or command] = "в команде подстановка площадки"
                continue
            seen.add(command)
            found.append(Step(name or command.splitlines()[0], command))

    if not found:
        raise NotRun(f"{path}: ни одной выполнимой команды не нашлось — предмет не найден (075)")
    return found


def environment() -> dict[str, str]:
    """Окружение прогона: инструменты берутся оттуда же, откуда запущен механизм.

    Иначе `pytest` и `ruff` придут из системного пути — то есть с ДРУГИМ
    интерпретатором, чем тот, на котором окно собиралось их гонять. Ровно этот
    разрыв и ловит `check_env.py`, и повторять его внутри своего же прогона
    значило бы проверять не то окружение (022).
    """
    where = str(Path(sys.executable).parent)
    room = dict(os.environ)
    room["PATH"] = where + os.pathsep + room.get("PATH", "")
    return room


def run(step: Step, root: Path) -> tuple[int, str]:
    """Запускает команду шага и отдаёт код с выводом."""
    done = subprocess.run(
        step.command,
        shell=True,
        # ОБОЛОЧКА ТА ЖЕ, ЧТО У ПЛОЩАДКИ. Умолчание `shell=True` — `/bin/sh`, а
        # площадка запускает шаги в bash: `set -o pipefail` в sh не понят, и
        # здоровый шаг краснел здесь с «Illegal option». Прогон, идущий другой
        # оболочкой, проверяет не то, что проверит площадка (022).
        executable="/bin/bash",
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment(),
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def report_gaps() -> None:
    """Называет то, что здесь проверить нечем, — списком, а не молчанием."""
    print("\nчего этот прогон не проверяет (проверит площадка):")
    for name, why in UNRUNNABLE.items():
        print(f"  {name} — {why}")
    for command, why in NEEDS_PLATFORM.items():
        print(f"  {command} — {why}")
    for check, why in ELSEWHERE.items():
        print(f"  {check} — {why}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: прогоняет проверки дерева и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--list", action="store_true", help="только показать, что будет запущено")
    args = parser.parse_args(argv)

    try:
        # Проверки ветки идут ПЕРВЫМИ: их предмет — то, откроется ли изменение
        # вообще, и красное здесь делает остальное бессмысленным.
        found = [*BEFORE_PUSH, *steps(args.root / CI)]
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if args.list:
        for step in found:
            print(f"{step.name}: {step.command}")
        report_gaps()
        return EXIT_OK

    red: list[Step] = []
    for step in found:
        code, output = run(step, args.root)
        print(f"{'✓' if code == 0 else '✗'} {step.name}: {step.command}")
        if code != 0:
            red.append(step)
            print(output.rstrip())

    report_gaps()
    if red:
        print(f"\nкрасных проверок: {len(red)} — толкать рано, чинится здесь:")
        for step in red:
            print(f"  {step.name}: {step.command}")
        return EXIT_RED
    print(f"\nзелено: {len(found)} проверок дерева прошли")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
