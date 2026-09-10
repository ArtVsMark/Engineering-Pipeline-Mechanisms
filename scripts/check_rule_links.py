#!/usr/bin/env python3
"""Гейт: ссылка на правило каталога ведёт туда, куда обещает.

ПОЧЕМУ ЭТО ВАЖНЕЕ, ЧЕМ ВЫГЛЯДИТ. Ссылками на правила этот проект обосновывает
решения: почти каждый механизм называет правило, из которого вырос. Ссылка,
ведущая в никуда, обесценивает обоснование дважды — читатель не может проверить
довод и не может отличить «правило есть, адрес переврали» от «правила нет».

Замер 10.09.2026, из-за которого гейт и появился: битых ссылок в дереве
оказалось **семнадцать**. Имя файла правила писалось по памяти — номер верный,
а название придумано близко к смыслу: `046-a-red-must-name-its-cause.md` вместо
`046-name-the-gaps-do-not-level-them.md`. На площадке такая ссылка отдаёт 404, и
ни один прогон об этом не говорил. Нашёл первую из них внешний взгляд на #130.

ИМЯ СВЕРЯЕТСЯ С ВЫГРУЗКОЙ КАТАЛОГА, А НЕ С ПАМЯТЬЮ. Каталог публикует `id` и
`slug` каждого правила; второй список того же разошёлся бы с первым молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ВЫГРУЗКА НЕ ПРИШЛА — ЭТО ТРЕТИЙ ИСХОД. «Не спросили» и «всё сошлось» снаружи
одинаковы, и молчаливое «чисто» здесь было бы тихим запасным ответом
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import ghrest

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

EXPORT_URL: Final = (
    "https://raw.githubusercontent.com/ArtVsMark/Engineering-Incidents-Playbook"
    "/main/export/rules.json"
)
#: Ссылка на файл правила: `rules/ru/<номер>-<имя>.md`. Ловится и в прозе, и в
#: докстроке — форма одна, и разбирать её по видам файлов незачем.
LINK_RE: Final = re.compile(r"rules/ru/(?P<number>\d{3})-(?P<slug>[a-z0-9-]+)\.md")
SUFFIXES: Final = frozenset({".py", ".md", ".yml", ".yaml", ".json"})


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def known() -> dict[str, str]:
    """Номер → имя файла правила, как их публикует каталог."""
    try:
        export = ghrest.raw_json(EXPORT_URL)
    except ghrest.TransportError as exc:
        raise NotRun(f"выгрузка каталога не прочитана: {exc}") from exc
    found: dict[str, str] = {}
    for rule in export.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        number, slug = str(rule.get("id") or ""), str(rule.get("slug") or "")
        if number and slug:
            found[number] = slug
    if not found:
        raise NotRun("в выгрузке каталога нет ни одного правила — сверять не с чем (075)")
    return found


def links(root: Path) -> list[tuple[Path, int, str, str]]:
    """Ссылки на правила в отслеживаемых файлах: где, на какой номер и имя."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if listed.returncode != 0:
        raise NotRun(f"список файлов не получен: {listed.stderr.strip()}")
    found: list[tuple[Path, int, str, str]] = []
    for name in listed.stdout.split("\0"):
        if not name:
            continue
        path = root / name
        if path.suffix not in SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in LINK_RE.finditer(line):
                found.append((Path(name), line_number, match["number"], match["slug"]))
    return found


def broken(found: list[tuple[Path, int, str, str]], real: dict[str, str]) -> list[str]:
    """Ссылки, которые не ведут туда, куда обещают.

    Разводятся два случая: номера нет в каталоге вовсе и имя не то. Первое
    значит «правила не существует», второе — «правило есть, адрес переврали», и
    чинятся они по-разному (154).
    """
    problems: list[str] = []
    for path, line, number, slug in found:
        if number not in real:
            problems.append(f"{path}:{line} — правила {number} в каталоге нет")
        elif real[number] != slug:
            problems.append(f"{path}:{line} — {number} зовётся «{real[number]}», а не «{slug}»")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет ссылки дерева с выгрузкой каталога."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    try:
        real = known()
        found = links(args.root)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not found:
        print("гейт не отработал: ссылок на правила в дереве нет (075)", file=sys.stderr)
        return EXIT_BROKEN

    problems = broken(found, real)
    if not problems:
        print(f"чисто: все ссылки на правила разрешаются; проверено {len(found)}")
        return EXIT_OK
    print(f"ссылок, ведущих не туда: {len(problems)} из {len(found)}")
    for said in problems:
        print(f"  {said}")
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
