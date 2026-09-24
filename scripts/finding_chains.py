#!/usr/bin/env python3
"""Цепочки находок по одному месту: замер рода «каскад», повторяемый командой.

ЗАЧЕМ. Род «каскад по одному месту» (`.rules/finding-kinds.json`, #746) и
предложение каталогу `a-second-finding-on-one-place-stops-the-patching`
опираются на числа: сколько мест получили находки на двух, трёх, четырёх
изменениях. Первый раз они были сняты разовым сценарием окна — и повторить их
было нечем, кроме памяти этого окна
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
Теперь число — команда:

    python scripts/finding_chains.py --repo <владелец/имя> --last 100

АРХИВ ДЛЯ ЭТОГО НЕ НУЖЕН. Находки уходят из реестра #23 после разбора, но
остаются в лентах изменений — в комментариях взгляда. Замер читает их там тем
же разбором, что и сборщик реестра (`review_findings.findings_of`,
`review_findings.fingerprint`): второй разбор той же строки разошёлся бы с
первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

МЕСТО — ПУТЬ ДО ДВОЕТОЧИЯ. Взгляд называет место одним способом —
`путь/от/корня.py:12` (так требует его подсказка), и путь берётся из начала
заголовка находки. Находка без пути в месте не считается и названа числом.
Одна находка, пересказанная дважды, считается по отпечатку один раз.

ГРАНИЦА. «Цепочка» здесь — место с находками на нескольких изменениях, а не
«одна цепочка форм»: считать ли их одним предикатом, решает чтение поимённо,
и замер его не заменяет — он печатает места, чтобы было что читать.

Исходы (правило 039): ``0`` замер снят · ``2`` не снят (нет токена, площадка
не ответила). Третьего — «снят с находками» — нет: это счёт, а не гейт, и
судить по нему не о чем
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Final

import ghrest
import review_findings

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Сколько последних закрытых изменений читать, если не сказано иначе.
LAST: Final = 100

#: Место в начале заголовка находки: путь с расширением, затем двоеточие.
PLACE_RE: Final = re.compile(r"^\s*`?(?P<path>[\w./-]+\.\w+)`?:\d")


@dataclass(frozen=True, slots=True)
class Chains:
    """Замер: сколько находок, мест и как далеко места дошли по изменениям."""

    findings: int
    changes: int
    unplaced: int
    #: место → номера изменений, на которых по нему были находки.
    places: dict[str, list[int]] = field(default_factory=dict)

    def reached(self, depth: int) -> list[str]:
        """Места с находками не меньше чем на `depth` изменениях."""
        return sorted(path for path, prs in self.places.items() if len(prs) >= depth)


def place_of(title: str) -> str:
    """Путь, с которого начинается заголовок находки; пусто — места нет."""
    found = PLACE_RE.match(title)
    return found.group("path") if found else ""


def chains(said: list[tuple[int, str]]) -> Chains:
    """Цепочки по парам «изменение, заголовок находки» — повтор по отпечатку снят."""
    seen: set[str] = set()
    places: dict[str, set[int]] = defaultdict(set)
    changes: set[int] = set()
    unplaced = 0
    for number, title in said:
        mark = review_findings.fingerprint(title)
        if mark in seen:
            continue
        seen.add(mark)
        changes.add(number)
        path = place_of(title)
        if not path:
            unplaced += 1
            continue
        places[path].add(number)
    return Chains(
        findings=len(seen),
        changes=len(changes),
        unplaced=unplaced,
        places={path: sorted(prs) for path, prs in places.items()},
    )


def read(repo: str, token: str, last: int) -> list[tuple[int, str]]:
    """Находки взгляда из лент последних `last` закрытых изменений."""
    said: list[tuple[int, str]] = []
    pulls = ghrest.paginate(f"repos/{repo}/pulls?state=closed&sort=created&direction=desc", token)
    for count, pull in enumerate(pulls):
        if count >= last:
            break
        number = int(pull["number"])
        comments = list(ghrest.paginate(f"repos/{repo}/issues/{number}/comments", token))
        said += [(number, found[1]) for found in review_findings.findings_of(comments)]
    return said


def report(measured: Chains) -> list[str]:
    """Строки отчёта: числа замера и места, дошедшие до третьего изменения."""
    lines = [
        f"уникальных находок: {measured.findings} на {measured.changes} изменениях"
        f" (без места: {measured.unplaced})",
        f"мест с находками: {len(measured.places)}",
    ]
    lines += [
        f"  на {depth} и более изменениях: {len(measured.reached(depth))}" for depth in (2, 3, 4)
    ]
    lines.append("места на трёх и более изменениях — читать поимённо:")
    lines += [
        f"  {path}: {', '.join(f'#{pr}' for pr in measured.places[path])}"
        for path in measured.reached(3)
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Точка входа: читает ленты изменений и печатает замер цепочек."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--last", type=int, default=LAST, help="сколько закрытых изменений читать")
    args = parser.parse_args(argv)
    token = ghrest.token_from_env()
    if not token or not args.repo:
        print("замер не снят: нет токена или репозитория (045)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        said = read(args.repo, token, args.last)
    except ghrest.TransportError as exc:
        print(f"замер не снят: площадка не ответила — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print("\n".join(report(chains(said))))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
