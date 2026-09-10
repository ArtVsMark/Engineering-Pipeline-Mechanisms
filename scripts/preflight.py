#!/usr/bin/env python3
"""Свой прогон перед толчком: красное чинится здесь, а не по логам площадки.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ СТРОКА В СВОДЕ. Правило без механизма — пожелание
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-a-rule-without-a-mechanism-is-a-wish.md)).
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
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import paths

CI: Final = paths.WORKFLOWS / "ci.yml"

#: Команда шага прогона: строка, начинающаяся с зовомого инструмента. Читается
#: список РАЗРЕШЁННОГО (068): что не узнано, то не запускается, а называется.
RUNNABLE: Final = ("ruff ", "mypy ", "pytest", "python scripts/")
#: Шаги, которым нужна площадка: их команды сюда не берутся, а перечисляются
#: как невыполнимые. Ключ — начало команды, значение — почему.
NEEDS_PLATFORM: Final = {
    "python scripts/check_pr_meta.py": "разметку изменения читает площадка",
    "python scripts/debt.py": "долг читается из задач площадки",
    "python scripts/check_journal.py": "сверяется с базой изменения",
    "python scripts/build_changelog.py --fragments": "разбирает принесённое изменением",
    "python scripts/ci_complete.py": "опрашивает записи проверок на голове у площадки",
}
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


@dataclass(frozen=True, slots=True)
class Step:
    """Одна команда прогона: чем названа и что запускает."""

    name: str
    command: str


def steps(path: Path = CI) -> list[Step]:
    """Команды прогона, выполнимые без площадки, — в порядке объявления.

    Разбор текстовый, а не по YAML, намеренно: команда живёт в блоке `run:`
    вместе с оболочечной обвязкой, и восстанавливать её из разобранного дерева
    пришлось бы тем же перечислением, от которого механизм и уходит.
    """
    if not path.is_file():
        raise NotRun(f"нет {path}: список проверок взять неоткуда (075)")

    found: list[Step] = []
    name = ""
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        named = re.match(r"\s*-?\s*name:\s*(\S.*?)\s*$", line)
        if named:
            name = named.group(1)
            continue
        # `- run: …` и `run: …` — одна и та же форма записи шага; читаются обе,
        # иначе часть команд дерева не увидели бы молча.
        command = line.strip().removeprefix("- ").removeprefix("run: ").strip()
        if not command.startswith(RUNNABLE) or command in seen:
            continue
        if any(command.startswith(prefix) for prefix in NEEDS_PLATFORM):
            continue
        if command.endswith("\\"):
            # Команда продолжается на следующей строке, а разбор построчный.
            # Запустить её обрезанной значило бы проверить не то, что проверяет
            # площадка, и промолчать об этом (045).
            raise NotRun(
                f"команда шага «{name}» многострочная — разбор её не читает целиком: {command}"
            )
        seen.add(command)
        found.append(Step(name or command, command))

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
        found = steps(args.root / CI)
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
