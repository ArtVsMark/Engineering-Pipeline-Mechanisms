#!/usr/bin/env python3
"""Гейт: толчок в ветку, чьё изменение уже слито, воскрешает её — и отвергается.

ВЕТКУ, УДАЛЁННУЮ ПЛОЩАДКОЙ ПРИ СЛИЯНИИ, ВОСКРЕШАЕТ ЛЮБОЙ СЛЕДУЮЩИЙ ТОЛЧОК —
вместе со всеми коммитами, которых нет в общей ветке. Толчок об этом не
говорит: он выглядит ровно как обычный успешный
([202](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/202-a-merged-branch-is-recreated-by-any-push.md)).

ИНЦИДЕНТ 19.09.2026, РАДИ КОТОРОГО ГЕЙТ И ЗАВЕДЁН. В 08:38 изменение #509 слито
уплотнением, ветка удалена площадкой. Через несколько минут окно толкнуло в неё
же — толчок снёс merge-коммит мувера и воскресил ветку. Конвейер законно открыл
по ней изменение #513, и его дифф против общей ветки **удалял чужую работу**:
тест на 104 строки и фрагмент журнала целиком, всё из #512. На #513 стояла метка
`automerge`; держал его только конфликт. Разбирал это человек.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ СТОРОЖА ПЕРЕД GIT. `.claude/hooks/push_guard.py` ловит тот
же случай **локальными** ссылками: слежение за одноимённой веткой при
исчезнувшей `origin/<имя>`. Признак верен, но устаревает до первого `git fetch`,
и предел там назван прямо. В тот день он не сработал именно поэтому: окно
слияния не видело. Здесь вопрос задаётся **площадке**, и она отвечает о
настоящем, а не о том, что окно успело узнать
([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).

ПРИЗНАК — СЛИТОЕ ИЗМЕНЕНИЕ ПО ЭТОЙ ЖЕ ГОЛОВЕ, а не отсутствие ветки. Ветка
после воскрешения СУЩЕСТВУЕТ, и спрашивать о её существовании бесполезно:
воскрешённая и живая выглядят одинаково. Слияние же — событие, которое площадка
помнит навсегда.

ЗАМЕР 19.09.2026 ПО ВСЕМ ВЕТКАМ ПЛОЩАДКИ: их пять, и ровно одна несёт слитое
изменение — `agent/an-empty-parametrisation-must-redden`, изменение #509. Это и
есть воскрешённая ветка из инцидента; она на площадке до сих пор.

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: толчок с чужой машины мимо
предполётной, и ветку, чьё изменение закрыли БЕЗ слияния, — по ней продолжать
работу законно. Без токена вопрос не задаётся вовсе, и тогда гейт говорит
«не спросили», а не «чисто»
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md),
[046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).

Исходы (правило 039): ``0`` чисто · ``1`` ветка воскреснет · ``2`` не отработал ·
``3`` не спросить: токена нет.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Final

import ghrest

EXIT_OK: Final = 0
EXIT_REVIVED: Final = 1
EXIT_BROKEN: Final = 2
EXIT_UNASKED: Final = 3

#: Ветки, о которых вопрос не имеет смысла: общая и оторванная голова.
NOT_A_BRANCH: Final = frozenset({"", "HEAD"})


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def repo_of(root: Path) -> str:
    """Имя репозитория `владелец/имя` — из адреса `origin`, а не из памяти."""
    said = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root or None,
    )
    if said.returncode != 0:
        raise NotRun("адрес origin не прочитан — спрашивать площадку не у кого")
    url = said.stdout.strip().removesuffix(".git")
    parts = url.replace(":", "/").split("/")
    if len(parts) < 2 or not parts[-1] or not parts[-2]:
        raise NotRun(f"адрес origin не разбирается: {url}")
    return f"{parts[-2]}/{parts[-1]}"


def merged_changes_of(repo: str, branch: str, token: str) -> list[int]:
    """Номера СЛИТЫХ изменений, открытых по этой ветке; пусто — ветка свежая.

    Спрашивается голова (`head`), а не база: предмет — та самая ветка, в которую
    пойдёт толчок. Закрытые без слияния сюда не попадают намеренно — по ним
    работу продолжают законно, и отказ был бы запретом верного (051).
    """
    owner = repo.split("/")[0]
    found = ghrest.request(
        "GET",
        f"repos/{repo}/pulls?head={owner}:{branch}&state=all&per_page=100",
        token,
    )
    if not isinstance(found, list):
        raise NotRun(f"площадка ответила не списком изменений: {type(found).__name__}")
    return [int(one["number"]) for one in found if one.get("merged_at")]


def refusal(repo: str, branch: str, merged: list[int]) -> str:
    """Отказ называет, ЧТО делать вместо толчка, а не только что не так (104)."""
    which = ", ".join(f"#{number}" for number in sorted(merged))
    return (
        f"толчок отвергнут: по ветке «{branch}» уже слито изменение {which} — площадка "
        f"удалила её при слиянии, и толчок воскресит её вместе с коммитами, которых нет "
        f"в общей ветке (202). Продолжение идёт с НОВОЙ ветки:\n"
        f"  git fetch origin main && git checkout -b <новая> origin/main\n"
        f"  (воскрешённая ветка остаётся на площадке — её удаляют руками: {repo})"
    )


def look(root: Path, branch: str) -> tuple[int, str]:
    """Вердикт по одной ветке: исход и что сказать."""
    if branch in NOT_A_BRANCH:
        raise NotRun(f"имя ветки не годится в предмет: «{branch}»")
    token = ghrest.token_from_env()
    if not token:
        return EXIT_UNASKED, (
            f"воскрешение ветки «{branch}» НЕ ПРОВЕРЕНО: токена площадки нет, а признак "
            "живёт только у неё. Это не «чисто» — это не спросили (045)"
        )
    repo = repo_of(root)
    merged = merged_changes_of(repo, branch, token)
    if merged:
        return EXIT_REVIVED, refusal(repo, branch, merged)
    return EXIT_OK, f"ветка «{branch}» слитых изменений не несёт — толчок её не воскресит"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: одна ветка против памяти площадки о слияниях."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True, help="ветка, в которую пойдёт толчок")
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    try:
        code, said = look(args.root, args.branch)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except ghrest.TransportError as exc:
        print(f"гейт не отработал: площадка не ответила — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print(said, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
