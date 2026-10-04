#!/usr/bin/env python3
"""Гейт: окно не открывает новое изменение, пока у него три открытых.

РЕШЕНИЕ ВЛАДЕЛЬЦА 03.10.2026 (#1085). Своя очередь — находки, конфликт,
красное на своих изменениях — идёт раньше новой строки плана (091). Окно,
у которого открыто три изменения, сначала доводит их, а не открывает
четвёртое.

ЗАМЕР, РАДИ КОТОРОГО ГЕЙТ ЗАВЕДЁН. За 03.10.2026 открыто 17 изменений, слито
10; с 10:40 до 16:10 — ни одного слияния. Первый заход взгляда нашёл находки
у 11 из 12, автослияние законно ждало починки, а окно в это время открывало
новые. По всей истории площадки (замер 04.10.2026, окно — по трейлеру
`Claude-Session` в теле уплотнения): из 884 изменений с известным окном 95
открыты, когда у того же окна уже было три открытых и больше; у четырёх окон
из семи одновременно открытых бывало больше трёх, наибольшее — девять.

ПРИЗНАК ДОСТОВЕРЕН, ПОЭТОМУ ОН ДЕРЖИТ ТОЛЧОК (051). Число открытых изменений
окна — ответ площадки, а не догадка. Держит его `preflight.py --push`: проверка
и толчок там одним заходом, и красное до толчка не доходит. Толчок в ветку, по
которой изменение уже открыто, предела не прибавляет — это починка своего, и
она как раз то, чего предел требует.

ЧЕЙ — ПО ТРЕЙЛЕРУ, А НЕ ПО АВТОРУ. Все изменения открывает одна учётная
запись (131), и автор окна не различает. Окно называет трейлер
`Claude-Session` в коммитах: изменение — окна, если его несёт хотя бы один
коммит изменения.

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо (046): толчок руками мимо предполётной и
вторую половину решения — «есть неразобранные находки или конфликт на своих».
Её число площадка не отдаёт одним ответом, и она держится чтением плана.
Без токена вопрос не задаётся, и гейт говорит «не спросили», а не «чисто»
(045).

Исходы (правило 039): ``0`` чисто · ``1`` предел достигнут · ``2`` не
отработал · ``3`` не спросить: токена нет.
"""

from pathlib import Path
from typing import Any, Final

import check_branch_revival
import ghrest
import gitcall

EXIT_OK: Final = 0
EXIT_OVER: Final = 1
EXIT_BROKEN: Final = 2
EXIT_UNASKED: Final = 3

#: Сколько открытых изменений окна держит предел: четвёртое не открывается.
LIMIT: Final = 3
#: Трейлер, по которому изменение узнаётся своим.
TRAILER: Final = "Claude-Session"


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def session_of(root: Path) -> str:
    """Окно головы — значение трейлера `Claude-Session` её коммита; нет — пусто."""
    said = gitcall.output(
        ["log", "-1", f"--format=%(trailers:key={TRAILER},valueonly)", "HEAD"],
        NotRun,
        cwd=str(root) if root else None,
    )
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def own_open(repo: str, token: str, session: str) -> list[dict[str, Any]]:
    """Открытые изменения, чьи коммиты несут трейлер этого окна."""
    found = []
    for change in ghrest.paginate(f"repos/{repo}/pulls?state=open", token):
        commits = ghrest.paginate(f"repos/{repo}/pulls/{change['number']}/commits", token)
        if any(session in str(one.get("commit", {}).get("message", "")) for one in commits):
            found.append(change)
    return found


def refusal(branch: str, mine: list[dict[str, Any]]) -> str:
    """Отказ называет, ЧТО делать вместо толчка (104)."""
    which = ", ".join(f"#{one['number']}" for one in sorted(mine, key=lambda one: one["number"]))
    return (
        f"толчок отвергнут: у окна открыто {len(mine)} изменений ({which}), предел — {LIMIT} "
        f"(#1085). Новая ветка «{branch}» открыла бы ещё одно. Сначала свои: находки, "
        "конфликт, красное — раньше новой строки плана (091). Работа ветки не пропадает: "
        "толкните её, когда одно из открытых сольётся."
    )


def look(root: Path, branch: str) -> tuple[int, str]:
    """Вердикт по одной ветке: исход и что сказать."""
    session = session_of(root)
    if not session:
        return EXIT_OK, f"голова не несёт трейлера {TRAILER} — предел окна не про неё"
    token = ghrest.token_from_env()
    if not token:
        return EXIT_UNASKED, (
            "предел открытых изменений НЕ ПРОВЕРЕН: токена площадки нет, а число "
            "открытых знает только она. Это не «чисто» — это не спросили (045)"
        )
    try:
        repo = check_branch_revival.repo_of(root)
    except check_branch_revival.NotRun as exc:
        raise NotRun(str(exc)) from exc
    owner = repo.split("/")[0]
    here = ghrest.request("GET", f"repos/{repo}/pulls?head={owner}:{branch}&state=open", token)
    if not isinstance(here, list):
        raise NotRun(f"площадка ответила не списком изменений: {type(here).__name__}")
    if here:
        return EXIT_OK, (
            f"по ветке «{branch}» изменение уже открыто (#{here[0]['number']}) — "
            "толчок чинит своё и предела не прибавляет"
        )
    mine = own_open(repo, token, session)
    if len(mine) >= LIMIT:
        return EXIT_OVER, refusal(branch, mine)
    return EXIT_OK, f"у окна открыто {len(mine)} изменений из {LIMIT} — новое можно"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: одна ветка против числа открытых изменений окна."""
    return check_branch_revival.cli(look, __doc__, NotRun, argv)


if __name__ == "__main__":
    raise SystemExit(main())
