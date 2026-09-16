#!/usr/bin/env python3
"""Свод сменился, пока окно работало, — и окно об этом не знает.

ПРЕДМЕТ ПРАВИЛА
[047](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/047-rule-change-restarts-the-windows.md).
Свод (`AGENTS.md`, `CLAUDE.md`) читается окном ОДИН раз, при старте. Правка,
попавшая в общую ветку позже, живому окну не видна: оно продолжает работать по
прежним правилам и не знает об этом. Правило говорит — такие окна перезапускают,
а не рассылают им письма.

ПРЕДМЕТ ЗАМЕРЕН, А НЕ ПРЕДПОЛОЖЕН. Замер 16.09.2026 по 381 коммиту общей ветки:
правок свода 56, окон четыре, и **семь раз** свод правило ЧУЖОЕ окно, пока это
ещё работало, — шесть у одного окна и одно у другого, все 09.09.2026, когда два
окна шли вперемешку. С 09.09 случаев нет: окно с тех пор одно за раз. То есть
шаг не выдуман под пустоту и сегодня молчит по существу, а не по построению
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

ПОЧЕМУ НЕ ЧАСТЬ ШАГА `window-lifetime`. Тот мерит СРОК жизни окна (правило 006),
этот — смену правил под работающим окном (правило 047). Предметы разные, и
сложить их под одно имя значило бы выдать одну проверку за другую
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)):
класс шага `window-lifetime` ждёт ПЕРВОГО СВОЕГО красного (решение `020`), и
чужое красное под его именем это ожидание бы сорвало.

ПРАВКА СВОЕГО ЖЕ ОКНА НЕ СЧИТАЕТСЯ, И ЭТО НЕ ПОБЛАЖКА. Окно, само правившее
свод, эту правку знает — она прошла через его работу, а не мимо неё. Считать её
значило бы красить каждое окно, которое трогало `AGENTS.md`: у текущего окна
таких правок девять, и все девять были бы ложными. Граница названа, а не
подразумевается
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

ПЕРЕЗАПУСК ШАГ НЕ ОБЪЯВЛЯЕТ И РЕШАТЬ ЗА ЧЕЛОВЕКА НЕ БЕРЁТСЯ — ровно как сосед
по сроку жизни. Он НАЗЫВАЕТ правки поимённо и зовёт перечитать свод навыком
`.claude/skills/rulebook-reread`: навык читается в момент вызова, а не при
старте окна, и потому показывает свод ЖИВЫМ. Это и есть машинная половина,
которой у правила не было; выбор между перечитыванием и перезапуском остаётся
за человеком
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

ОБРЕЗАННАЯ ИСТОРИЯ НЕ СЧИТАЕТСЯ СВЕЖИМ СВОДОМ. В мелком клоне начало окна не
видно, и правки «после старта» вышли бы неполными — то есть шаг зеленел бы тем
охотнее, чем меньше знает
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Исходы (правило 039): ``0`` свод не менялся под окном или предмета нет ·
``1`` менялся, и правки названы · ``2`` шаг не отработал.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Final

import paths
import window

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Что считается сводом. Список объявлен здесь, а не выведен из дерева: свод —
#: это ровно два документа с объявленными читателями (021, 022), и «всякий .md в
#: корне» включил бы `README.md`, который окну правил не задаёт.
RULEBOOK: Final = ("AGENTS.md", "CLAUDE.md")

#: Навык, которым свод перечитывают без перезапуска окна.
SKILL: Final = "rulebook-reread"


def touching(history: str, files: tuple[str, ...], cwd: str | None = None) -> list[str]:
    """Коммиты истории, тронувшие названные файлы, от старых к новым."""
    try:
        done = subprocess.run(
            ["git", "log", "--reverse", "--format=%H", history, "--", *files],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise window.NotRun(f"история свода не прочитана: {exc}") from exc
    return done.stdout.split()


def changed_under(
    session: str, start: window.Commit, head: window.Commit, history: str, cwd: str | None = None
) -> list[window.Commit]:
    """Правки свода ЧУЖИМ окном между началом этого окна и данной головой.

    Границы обе: снизу — начало окна (раньше него правка попала в свод, который
    окно и прочитало), сверху — голова (позже неё правки этому изменению ещё не
    видны).
    """
    known = {commit.sha: commit for commit in window.commits(history, cwd=cwd)}
    found: list[window.Commit] = []
    for sha in touching(history, RULEBOOK, cwd=cwd):
        edit = known.get(sha)
        if edit is None or edit.session == session:
            continue
        if start.when < edit.when <= head.when:
            found.append(edit)
    return found


def said(session: str, edits: list[window.Commit]) -> list[str]:
    """Что сказать об окне, под которым сменился свод."""
    lines = [
        f"окно {session}: свод менялся под ним {len(edits)} раз — "
        f"эти правки оно при старте не читало (047):"
    ]
    lines += [f"  {edit.sha[:7]} {edit.message.splitlines()[0][:70]}" for edit in edits]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Точка входа: не сменился ли свод под окнами этого изменения."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="база изменения")
    parser.add_argument("--head", default="HEAD", help="голова изменения")
    parser.add_argument("--history", default="origin/main", help="что считать историей")
    parser.add_argument("--root", type=Path, default=None, help="корень дерева")
    args = parser.parse_args(argv)
    cwd = str(args.root) if args.root else None

    try:
        mine = window.commits(f"{args.base}..{args.head}", cwd=cwd)
    except window.NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not mine:
        print(
            f"шаг не отработал: между {args.base} и {args.head} коммитов нет — "
            "предмета проверки не нашлось (075)",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    last: dict[str, window.Commit] = {}
    for commit in mine:
        if window.made_by_window(commit.message) and commit.session:
            last[commit.session] = commit
    if not last:
        print(
            f"предмета нет: ни один из {len(mine)} коммитов не подписан окном — "
            "правило 047 не о нём"
        )
        return EXIT_OK

    try:
        lives = [window.lifetime(name, args.history, last[name], cwd=cwd) for name in sorted(last)]
    except window.NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    cut = [life for life in lives if not life.whole]
    if cut:
        print(
            "шаг не отработал: история обрезана, и начало окна "
            f"{cut[0].session} в ней не видно — правки свода вышли бы неполными (045)",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    told: list[str] = []
    for life in lives:
        try:
            edits = changed_under(life.session, life.first, life.last, args.history, cwd=cwd)
        except window.NotRun as exc:
            print(f"шаг не отработал: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        if edits:
            told += said(life.session, edits)
    if not told:
        print(f"свод под окнами изменения не менялся: {', '.join(sorted(last))}")
        return EXIT_OK
    print("\n".join(told))
    print(
        f"\nперечитать свод живым, не перезапуская окно: навык `{SKILL}` "
        f"({paths.SKILLS / SKILL}). Перезапускать или перечитать — решает человек: "
        "шаг называет величину и слияния не держит"
    )
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
