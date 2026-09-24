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
    python scripts/finding_chains.py --repo <владелец/имя> \
        --from 616 --to 743 --at 2026-09-24T19:00:00Z

Отрезок `--from/--to` — номера изменений включительно, и задаются они ОБА: одна
граница без другой читала бы всю историю молча. Отрезок повторяет ИЗМЕНЕНИЯ, но
не числа: поздний взгляд дописывает находки в ленты уже закрытых изменений, и
тот же отрезок завтра даст больше. Числа повторяет `--at`: в счёт идут только
комментарии, написанные до этого момента (взгляд на #769). Отрезок без
изменений — не нулевой замер, а отказ: пустое и измеренное неотличимы (045).

АРХИВ ДЛЯ ЭТОГО НЕ НУЖЕН. Находки уходят из реестра #23 после разбора, но
остаются в лентах изменений — в комментариях взгляда. Замер читает их там тем
же разбором, что и сборщик реестра (`review_findings.findings_of`,
`review_findings.fingerprint`): второй разбор той же строки разошёлся бы с
первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

МЕСТО — ПУТЬ ДО ДВОЕТОЧИЯ. Взгляд называет место одним способом —
`путь/от/корня.py:12` (так требует его подсказка), и путь берётся из начала
заголовка находки. Формы пути перечислены разом, а не по одной (195): с
расширением (`scripts/x.py:12`), без него (`Makefile:3`, `.github/CODEOWNERS:1`)
и с точкой в начале (`.gitignore:3`). Путь пишется латиницей: слово кириллицей
перед двоеточием — проза, а не место. Находка без пути в месте не считается и
названа числом.

ПЕРЕСКАЗ СНИМАЕТСЯ В ПРЕДЕЛАХ ИЗМЕНЕНИЯ, А НЕ ПОПЕРЁК. Одна находка, повторённая
на том же изменении, считается один раз. Та же находка на ДРУГОМ изменении —
это новое звено цепочки: место снова получило находку, и снять её значило бы
занизить глубину и потерять изменение, где находка родилась. В счёте
уникальных находок отпечаток по-прежнему один.

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

#: Место в начале заголовка находки: путь латиницей, затем двоеточие и номер
#: строки. Формы — в докстроке модуля: с расширением, без него, с точкой в начале.
PLACE_RE: Final = re.compile(
    r"^\s*`?(?P<path>(?:[A-Za-z0-9_.-]+/)*\.?[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)`?:\d"
)


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
    """Цепочки по парам «изменение, заголовок находки».

    Повтор снимается в пределах изменения; на другом изменении та же находка —
    новое звено цепочки места (докстрока модуля).
    """
    seen: set[str] = set()
    counted: set[tuple[int, str]] = set()
    places: dict[str, set[int]] = defaultdict(set)
    changes: set[int] = set()
    unplaced: set[str] = set()
    for number, title in said:
        mark = review_findings.fingerprint(title)
        if (number, mark) in counted:
            continue
        counted.add((number, mark))
        seen.add(mark)
        changes.add(number)
        path = place_of(title)
        if not path:
            unplaced.add(mark)
            continue
        places[path].add(number)
    return Chains(
        findings=len(seen),
        changes=len(changes),
        unplaced=len(unplaced),
        places={path: sorted(prs) for path, prs in places.items()},
    )


def read(
    repo: str, token: str, last: int, first: int = 0, final: int = 0, at: str = ""
) -> list[tuple[int, str]]:
    """Находки взгляда из лент закрытых изменений — без счёта прочитанного."""
    return read_counted(repo, token, last, first, final, at)[0]


def read_counted(
    repo: str, token: str, last: int, first: int = 0, final: int = 0, at: str = ""
) -> tuple[list[tuple[int, str]], int]:
    """Находки взгляда из лент закрытых изменений и число прочитанных изменений.

    Отрезок `first..final` (номера включительно) выбирает изменения; без него
    читаются последние `last`. Ленты идут от новых к старым, поэтому за нижней
    границей отрезка чтение останавливается, а не листает историю до конца.
    `at` отсекает комментарии, написанные позже: так числа повторяются, хотя
    поздний взгляд дописывает ленты задним числом.
    """
    said: list[tuple[int, str]] = []
    pulls = ghrest.paginate(f"repos/{repo}/pulls?state=closed&sort=created&direction=desc", token)
    taken = 0
    for pull in pulls:
        number = int(pull["number"])
        if first or final:
            if final and number > final:
                continue
            if number < first:
                break
        elif taken >= last:
            break
        taken += 1
        comments = [
            one
            for one in ghrest.paginate(f"repos/{repo}/issues/{number}/comments", token)
            if not at or str(one.get("created_at") or "") <= at
        ]
        said += [(number, found[1]) for found in review_findings.findings_of(comments)]
    return said, taken


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
    parser.add_argument("--from", dest="first", type=int, default=0, help="первый номер отрезка")
    parser.add_argument("--to", dest="final", type=int, default=0, help="последний номер отрезка")
    parser.add_argument("--at", default="", help="момент ISO: комментарии позже него не считаются")
    args = parser.parse_args(argv)
    if bool(args.first) != bool(args.final) or (args.first and args.first > args.final):
        print(
            "замер не снят: отрезок задаётся обеими границами, и первая не больше последней "
            f"(--from {args.first or '—'}, --to {args.final or '—'})",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    token = ghrest.token_from_env()
    if not token or not args.repo:
        print("замер не снят: нет токена или репозитория (045)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        said, seen = read_counted(args.repo, token, args.last, args.first, args.final, args.at)
    except ghrest.TransportError as exc:
        print(f"замер не снят: площадка не ответила — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not seen:
        print("замер не снят: в отрезке нет ни одного закрытого изменения (045)", file=sys.stderr)
        return EXIT_BROKEN
    print("\n".join(report(chains(said))))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
