#!/usr/bin/env python3
"""Собирает `CHANGELOG.md` из фрагментов.

Правило 030: журнал собирается из фрагментов, а не правится общим файлом. Два
файла с разными именами не конфликтуют никогда, а на конфликтном изменении
площадка не создаёт проверок вовсе.

Правило 125: генератор читает **источники, а не свой вывод**. Поэтому выпущенные
фрагменты не исчезают в собранный файл, а переезжают в
``changelog.d/released/<версия>/`` и остаются источником. `CHANGELOG.md`
производный целиком: его можно удалить и собрать заново, ничего не потеряв.

Исходы (правило 039): ``0`` собрано · ``1`` собранное расходится с файлом на
диске при ``--check`` · ``2`` собрать не удалось.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

FRAGMENTS: Final = Path("changelog.d")
RELEASED: Final = FRAGMENTS / "released"
OUTPUT: Final = Path("CHANGELOG.md")
VERSION_FILE: Final = Path("CONTRACT_VERSION")
VERSION_RE: Final = re.compile(r"^\d+\.\d+\.\d+$")
FRAGMENT_RE: Final = re.compile(r"^(?P<task>[\w.-]+)\.(?P<kind>contract|feat|fix|docs|internal)\.md$")

KINDS: Final = {
    "contract": "Несовместимое: поверхность контракта",
    "feat": "Добавлено",
    "fix": "Исправлено",
    "docs": "Документы",
    "internal": "Внутреннее",
}

EXIT_OK: Final = 0
EXIT_DIFFERS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Сборка не отработала: третий исход, а не пустой журнал."""


@dataclass(frozen=True, slots=True)
class Fragment:
    """Один фрагмент журнала: род, задача, текст."""

    kind: str
    task: str
    body: str


def read_fragments(directory: Path) -> list[Fragment]:
    """Читает фрагменты каталога, отвергая файлы с неразбираемым именем."""
    if not directory.is_dir():
        return []

    fragments: list[Fragment] = []
    unnamed: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        match = FRAGMENT_RE.match(path.name)
        if match is None:
            unnamed.append(path.name)
            continue
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            unnamed.append(f"{path.name} (пустой)")
            continue
        fragments.append(Fragment(match["kind"], match["task"], body))

    if unnamed:
        raise NotRun(
            "фрагменты с неразбираемым именем или пустые:\n  "
            + "\n  ".join(unnamed)
            + "\n\nИмя: <задача>.<род>.md, род — " + " · ".join(KINDS)
        )
    return fragments


def render_section(title: str, fragments: list[Fragment]) -> str:
    """Собирает один раздел журнала, группируя фрагменты по роду."""
    lines = [f"## {title}", ""]
    if not fragments:
        lines += ["Пусто.", ""]
        return "\n".join(lines)

    for kind, heading in KINDS.items():
        chosen = [f for f in fragments if f.kind == kind]
        if not chosen:
            continue
        lines += [f"### {heading}", ""]
        for fragment in chosen:
            lines += [fragment.body, ""]
    return "\n".join(lines)


def render(version: str) -> str:
    """Собирает журнал целиком: не выпущенное, затем выпуски от новых к старым."""
    parts = [
        "# Журнал изменений",
        "",
        "> Файл производный: собирается `scripts/build_changelog.py` из фрагментов",
        "> в `changelog.d/`. Руками не правится — правка потеряется при следующей",
        "> сборке (правило 125).",
        "",
        f"Версия контракта — `{version}`, источник `CONTRACT_VERSION`. Что означают",
        "разряды и что делает потребитель — [`docs/release.md`](docs/release.md).",
        "",
        render_section("Не выпущено", read_fragments(FRAGMENTS)),
    ]

    if RELEASED.is_dir():
        released = sorted(
            (p for p in RELEASED.iterdir() if p.is_dir()),
            key=lambda p: [int(x) for x in p.name.split(".")] if VERSION_RE.match(p.name) else [0],
            reverse=True,
        )
        for directory in released:
            parts.append(render_section(directory.name, read_fragments(directory)))

    return "\n".join(parts).rstrip() + "\n"


def read_version() -> str:
    """Читает версию контракта из единственного источника."""
    if not VERSION_FILE.is_file():
        raise NotRun(f"нет источника версии: {VERSION_FILE}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not VERSION_RE.match(version):
        raise NotRun(f"версия «{version}» не вида МАЖОР.МИНОР.ПАТЧ")
    return version


def do_release(version: str) -> None:
    """Переносит текущие фрагменты в каталог выпуска, оставляя их источником."""
    if not VERSION_RE.match(version):
        raise NotRun(f"версия выпуска «{version}» не вида МАЖОР.МИНОР.ПАТЧ")
    target = RELEASED / version
    if target.exists():
        raise NotRun(f"выпуск {version} уже собран: {target}")

    moving = [p for p in FRAGMENTS.glob("*.md") if p.name != "README.md"]
    if not moving:
        raise NotRun("выпускать нечего: ни одного фрагмента — это ошибка входа, а не пустой выпуск")

    target.mkdir(parents=True)
    for path in moving:
        shutil.move(str(path), str(target / path.name))
    print(f"в выпуск {version} перенесено фрагментов: {len(moving)}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает журнал, сверяет его или закрывает выпуск."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="сверить, не записывая")
    parser.add_argument("--release", metavar="ВЕРСИЯ", help="закрыть выпуск: перенести фрагменты")
    args = parser.parse_args(argv)

    try:
        if args.release:
            do_release(args.release)
        version = read_version()
        assembled = render(version)

        if args.check:
            current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
            if current != assembled:
                print(
                    f"{OUTPUT} расходится со сборкой из фрагментов.\n"
                    "Соберите заново: python scripts/build_changelog.py",
                    file=sys.stderr,
                )
                return EXIT_DIFFERS
            print(f"{OUTPUT} совпадает со сборкой")
            return EXIT_OK

        OUTPUT.write_text(assembled, encoding="utf-8")
        print(f"{OUTPUT} собран, версия контракта {version}")
        return EXIT_OK
    except NotRun as exc:
        print(f"сборка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
