#!/usr/bin/env python3
"""Гейт: изменение не приносит чужое действие с версией старше той, что уже в дереве.

НАХОДКА, РАДИ КОТОРОЙ ГЕЙТ (`8bb4854`, взгляд на #1688; решение владельца
28.10.2026, #639). Расхождение версий одного действия держит дрейф
(`drift.actions_disagree`), и довод его — «чинится переездом, а не правкой
изменения». Для расхождения, которое в дереве уже живёт, довод верен. Но #1674
вернул `actions/setup-python` прежнего мажора НОВОЙ строкой уже после подъёма
в #1671 — и это чинилось правкой самого изменения: строку достаточно было
написать с той версией, что уже стоит рядом. Дрейф назвал бы это через сутки,
когда изменение уже слито.

ЗАМЕР 28.10.2026 по истории общей ветки до 42387b9e: каждое слитое изменение,
тронувшее прогоны (`git log --first-parent -- .github/workflows`, 337), против
своего родителя. Предикат назвал 11, и все одного вида — новая строка с
прежним мажором при поднятом рядом: десять раз `actions/checkout@v4` при
`v7.0.1`, начиная с #31, и #1674 с `setup-python` `v7.0.0` при `v7.1.0`.
Строк без порядка — ноль.

ПРЕДМЕТ — ПРИРОСТ, А НЕ ДЕРЕВО. Судится только вхождение `uses:`, которое
изменение ДОБАВИЛО: строк с этим действием и этой версией в диффе прибыло
больше, чем ушло. Переставленная или переписанная вокруг строка — не прирост,
и прежнее расхождение, которое изменение не трогает, остаётся дрейфу: его
правкой изменения не погасить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

КРАСНЕЕТ «СТАРШЕ», А НЕ «ИНАЧЕ». Новая строка с версией МЛАДШЕ старшей в базе —
отказ: рядом уже стоит поднятая, и написать её значит ничего не решать заново.
Новая строка с версией СТАРШЕ — это начало подъёма, а подъём — решение о
переезде, и его держит дрейф (`drift.actions_disagree`), а не этот гейт.

ВЕРСИЯ ЧИТАЕТСЯ, КАК ЕЁ ЧИТАЕТ ДРЕЙФ: один разбор строки `uses:`
(`drift.ACTION_USE`) и одна граница своего (`drift.own_prefixes`) — второй
разбор разошёлся бы с первым молча (214). Версия — пометка у хеша либо тег.
Хеш без пометки порядка не несёт: такая строка не судится и называется
строкой, а не пропускается молча (045).

СПЕРВА СПРОСИЛИ СЕМЬЮ (162), выкачки 28.10.2026. Ни у кого нет гейта на
порядок версий между строками одного дерева: у каталога (a0874b9)
`scripts/check_workflows.py` судит форму пина — полный SHA у чужого действия
(`unpinned_actions`), а не то, что новая строка младше соседней; у
Glossary-Python, Stepik-Python-Grader и ArtVsMark версии поднимает
`dependabot.yml`, и новую строку со старым пином не отвергает ничто; у
Usage-Token нет ни того, ни другого. Строим своё.

СОСЕДИ НАЗВАНЫ (195): действия семьи судит гейт заготовки (155,
`tests/test_family_pinning.py`); локальные `./…` и образы `docker://` формой
`ACTION_USE` не являются.

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

import argparse
import os
import re
import sys
from collections import Counter
from typing import Final

import drift
import gitcall
import main_guard
import paths

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Порядок версии: числа тега через точку, `v4` ниже `v7.0.1`.
RANK_RE: Final = re.compile(r"v?(\d+(?:\.\d+)*)")

#: Пара действия: чьё оно и какую версию называет строка.
Pin = tuple[str, str]


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def base_ref() -> str:
    """Общая ветка, относительно которой смотрится изменение."""
    return f"origin/{os.environ.get('GITHUB_BASE_REF') or paths.TRUNK}"


def rank(said: str) -> tuple[int, ...] | None:
    """Порядок версии для сравнения; хеш без пометки — `None`, порядка у него нет."""
    found = RANK_RE.fullmatch(said)
    if not found:
        return None
    parts = [int(one) for one in found[1].split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def pins_in(lines: list[str], own: tuple[str, ...]) -> Counter[Pin]:
    """Чужие пины в строках: (действие, версия) → сколько раз."""
    found: Counter[Pin] = Counter()
    for line in lines:
        for match in drift.ACTION_USE.finditer(line):
            if not match["repo"].startswith(own):
                found[(match["repo"], match["said"] or match["ref"])] += 1
    return found


def added(diff: str, own: tuple[str, ...]) -> Counter[Pin]:
    """Прирост пинов по диффу `-U0`: прибывших строк больше, чем ушедших."""
    plus = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    minus = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    return pins_in(plus, own) - pins_in(minus, own)


def findings(base_pins: Counter[Pin], grown: Counter[Pin]) -> tuple[list[str], list[str]]:
    """Отказы и строки без порядка: новая версия ниже старшей в базе — отказ."""
    problems: list[str] = []
    unranked: list[str] = []
    for (repo, said), count in sorted(grown.items()):
        known = [rank(version) for (name, version) in base_pins if name == repo]
        ranked = [one for one in known if one is not None]
        mine = rank(said)
        if not ranked:
            continue
        if mine is None:
            unranked.append(f"{repo}@{said} — версия не читается: хеш без пометки `# vX.Y.Z`")
            continue
        top = max(ranked)
        if mine < top:
            newest = next(
                version for (name, version) in base_pins if name == repo and rank(version) == top
            )
            problems.append(
                f"{repo}@{said} добавлено {count} раз(а), а в базе уже {newest} — "
                f"напишите строку с {newest}"
            )
    return problems, unranked


def look(base: str) -> tuple[list[str], list[str]]:
    """Прирост изменения против базы: отказы и строки, которые не судятся."""
    workflows = paths.WORKFLOWS.as_posix()
    try:
        spot = gitcall.output(["merge-base", base, "HEAD"], NotRun).strip()
    except NotRun as exc:
        raise NotRun(f"общая точка с {base} не найдена: {exc}") from exc
    diff = gitcall.output(["diff", "-U0", spot, "HEAD", "--", workflows], NotRun)
    own = drift.own_prefixes()
    grown = added(diff, own)
    if not grown:
        return [], []
    # `-z` обязателен: без него git экранирует имена с не-ASCII, и такой путь
    # не прочитался бы `git show` (165).
    names = gitcall.output(["ls-tree", "-r", "-z", "--name-only", spot, "--", workflows], NotRun)
    runs = [name for name in names.split("\0") if name.endswith((".yml", ".yaml"))]
    # Один вызов на все файлы: `git show` отдаёт блобы подряд.
    listed = gitcall.output(["show", *(f"{spot}:{name}" for name in runs)], NotRun) if runs else ""
    return findings(pins_in(listed.splitlines(), own), grown)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет добавленные пины действий с их версиями в базе."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="точка сравнения; по умолчанию общая ветка")
    args = parser.parse_args(argv)
    base = args.base or base_ref()
    try:
        problems, unranked = look(base)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    for said in unranked:
        print(f"::warning::не судится: {said}")
    if not problems:
        print("чисто: изменение не приносит действие версией ниже уже стоящей в дереве")
        return EXIT_OK
    print(f"действие добавлено версией ниже той, что уже в дереве: {len(problems)}")
    for said in problems:
        print(f"  {said}")
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
