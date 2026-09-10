#!/usr/bin/env python3
"""Окружение окна сверяется с требованиями дерева ДО работ, а не по ошибке.

ЗАМЕР 09.09.2026, из-за которого механизм и написан. В облачном окне
`python3` — 3.11.15, а проект требует `>=3.12` и прогон ставит 3.12;
`pytest`, `ruff`, `mypy` стояли для 3.11, а установка для 3.12 отказывала по
PEP 668. Окно почти прогнало проверки НЕ НА ТОЙ версии и узнало об этом
случайно — по ошибке импорта в тесте. Обратный случай тише и хуже: проверки
зеленеют в окне и краснеют на площадке, потому что версии разные
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ТРЕБОВАНИЯ ЧИТАЮТСЯ ИЗ ДЕРЕВА, А НЕ ОБЪЯВЛЯЮТСЯ ВТОРЫМ СПИСКОМ. Интерпретатор
берётся из `pyproject.toml` (`requires-python`), инструменты — из строк
установки в прогонах. Второй список тех же версий разошёлся бы с первым молча,
и оба выглядели бы правдоподобно
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

ИСХОД НАЗЫВАЕТ, ЧТО ДЕЛАТЬ. «Версия не та» без продолжения оставляет окно там
же, где застало: в окружении, где установка запрещена, а нужного
интерпретатора нет. Поэтому расхождение печатается вместе с действием
([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md)).

ЧЕГО МЕХАНИЗМ НЕ ДЕЛАЕТ: он не чинит окружение. Установка пакетов из шага,
который проверяет окружение, превратила бы проверку в действие, и «сверено» и
«подправлено на ходу» стали бы неотличимы.

Исходы (правило 039): ``0`` окружение годится · ``2`` шаг не отработал ·
``3`` расхождение названо.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Final

import paths

#: Строка установки в прогоне: `pip install "ruff>=0.6,<1" "mypy>=1.11,<2"`.
INSTALL_RE: Final = re.compile(r"pip install[^\n]*")
#: Одно требование внутри такой строки: имя и границы версий.
NEED_RE: Final = re.compile(r'"([A-Za-z][\w.-]*)((?:[<>=!~]=?[\d.]+,?)*)"')
#: Нижняя граница требования к интерпретатору: `>=3.12`.
PYTHON_RE: Final = re.compile(r">=\s*(\d+)\.(\d+)")

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_MISMATCH: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «окружение годится»."""


@dataclass(frozen=True, slots=True)
class Need:
    """Одно требование дерева: имя инструмента и объявленные границы."""

    name: str
    bounds: str
    where: str


def python_floor(root: Path = Path()) -> tuple[int, int]:
    """Нижняя граница интерпретатора из `pyproject.toml`."""
    path = root / "pyproject.toml"
    if not path.is_file():
        raise NotRun(f"нет {path}: требование к интерпретатору взять неоткуда (075)")
    declared = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
    raw = str(declared.get("requires-python") or "")
    found = PYTHON_RE.search(raw)
    if found is None:
        raise NotRun(f"{path}: в requires-python «{raw}» нет нижней границы вида >=X.Y")
    return int(found.group(1)), int(found.group(2))


def needs(root: Path = Path()) -> dict[str, Need]:
    """Инструменты и их границы — из строк установки в прогонах.

    Одно имя, объявленное в двух прогонах с разными границами, — расхождение
    дерева, а не выбор механизма: обе строки правдоподобны, и брать любую
    значило бы решать за проект молча.
    """
    directory = root / paths.WORKFLOWS
    if not directory.is_dir():
        raise NotRun(f"нет описания прогонов: {directory} — предмет сверки не найден (075)")

    found: dict[str, Need] = {}
    for path in sorted(directory.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        for line in INSTALL_RE.findall(text):
            for name, bounds in NEED_RE.findall(line):
                seen = found.get(name)
                if seen and seen.bounds != bounds:
                    raise NotRun(
                        f"«{name}» объявлен по-разному: {seen.bounds or '—'} в {seen.where} и "
                        f"{bounds or '—'} в {path.name} — дерево спорит само с собой (022)"
                    )
                found[name] = Need(name, bounds, path.name)
    if not found:
        raise NotRun("в прогонах нет ни одной строки установки — предмет сверки не найден (075)")
    return found


def installed(name: str) -> str | None:
    """Версия установленного инструмента; ``None`` — его нет."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def parts(version: str) -> tuple[int, ...]:
    """Числовые части версии — для сравнения границ."""
    return tuple(int(piece) for piece in re.findall(r"\d+", version)[:3])


def fits(version: str, bounds: str) -> bool:
    """Попадает ли версия в объявленные границы.

    Разбираются только те виды границ, которые в дереве действительно есть:
    `>=` и `<`. Встретив незнакомый вид, механизм НЕ отвечает «подходит» — он
    отвечает отказом входа, потому что молчаливое «наверное, годится» здесь
    неотличимо от проверки (068).
    """
    for piece in filter(None, bounds.split(",")):
        found = re.fullmatch(r"([<>=!~]=?)([\d.]+)", piece.strip())
        if found is None:
            raise NotRun(f"граница «{piece}» не разбирается — такой вид ещё не читается")
        mark, limit = found.group(1), parts(found.group(2))
        current = parts(version)[: len(limit)]
        if mark == ">=" and current < limit:
            return False
        if mark == "<" and current >= limit:
            return False
        if mark not in (">=", "<"):
            raise NotRun(f"граница «{piece}» не разбирается — такой вид ещё не читается")
    return True


def advise(floor: tuple[int, int], gaps: list[str]) -> None:
    """Печатает, ЧТО ДЕЛАТЬ, а не только чего не хватает."""
    print("\nчто делать:")
    print(f"  1. взять интерпретатор {floor[0]}.{floor[1]} или новее — тот же, что ставит прогон;")
    print("  2. поднять своё окружение, если установка в системный запрещена (PEP 668):")
    print(f"     python{floor[0]}.{floor[1]} -m venv .venv && . .venv/bin/activate")
    print("  3. поставить недостающее ровно с теми границами, что объявлены в прогонах:")
    print(f"     python -m pip install {' '.join(gaps)}" if gaps else "     (всё на месте)")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет окружение с деревом и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    try:
        floor = python_floor(args.root)
        declared = needs(args.root)
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    running = sys.version_info[:2]
    problems: list[str] = []
    gaps: list[str] = []

    print(f"интерпретатор: {running[0]}.{running[1]}, дерево требует >={floor[0]}.{floor[1]}")
    if running < floor:
        problems.append(
            f"интерпретатор {running[0]}.{running[1]} старше требуемого — проверки пойдут "
            "не на той версии, на которой их гоняет площадка"
        )

    for need in declared.values():
        version = installed(need.name)
        try:
            good = version is not None and fits(version, need.bounds)
        except NotRun as exc:
            print(f"шаг не отработал: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        print(f"  {need.name}: {version or 'нет'}, дерево требует {need.bounds or 'любую'}")
        if not good:
            problems.append(f"{need.name}: {version or 'не установлен'}, нужно {need.bounds}")
            gaps.append(f'"{need.name}{need.bounds}"')

    if not problems:
        print("\nокружение годится: версии совпадают с тем, что ставит прогон")
        return EXIT_OK

    print("\nокружение расходится с деревом:")
    for problem in problems:
        print(f"  {problem}")
    advise(floor, gaps)
    return EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
