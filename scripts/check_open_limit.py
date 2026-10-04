#!/usr/bin/env python3
"""Гейт: окно не открывает новое изменение, пока у него три открытых.

РЕШЕНИЕ ВЛАДЕЛЬЦА 03.10.2026 (#1085). Своя очередь — находки, конфликт,
красное на своих изменениях — идёт раньше новой строки плана (091). Окно,
у которого открыто три изменения, сначала доводит их, а не открывает
четвёртое.

ЗАМЕР, РАДИ КОТОРОГО ГЕЙТ ЗАВЕДЁН. За 03.10.2026 открыто 17 изменений, слито
10; с 10:40 до 16:10 — ни одного слияния. Первый заход взгляда нашёл находки
у 11 из 12, автослияние законно ждало починки, а окно в это время открывало
новые. По всей истории площадки — замер 04.10.2026 командой
`python scripts/check_open_limit.py --measure`, окно — по трейлеру
`Claude-Session` в теле уплотнения: из 908 изменений окно известно у 880, и 97
из них открыты, когда у того же окна уже было три открытых и больше.

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

import re
import sys
from pathlib import Path
from typing import Any, Final

import check_branch_revival
import ghrest
import gitcall
import trunk_log

EXIT_OK: Final = 0
EXIT_OVER: Final = 1
EXIT_BROKEN: Final = 2
EXIT_UNASKED: Final = 3

#: Сколько открытых изменений окна держит предел: четвёртое не открывается.
LIMIT: Final = 3
#: Трейлер, по которому изменение узнаётся своим, и его строка целиком.
TRAILER: Final = "Claude-Session"
TRAILER_RE: Final = re.compile(rf"^{TRAILER}:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
#: Режим замера по истории: печатает число превышений, гейтом не служит.
MEASURE: Final = "--measure"


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def trailers_in(message: str) -> set[str]:
    """Значения трейлера `Claude-Session` в тексте коммита — строкой целиком, а не вхождением.

    Адрес окна, процитированный в теле (оклик, разбор), трейлером не
    становится: своё узнаётся разбором строки, а не подстрокой (взгляд на
    #1087, 141).
    """
    return set(TRAILER_RE.findall(message))


def session_of(root: Path, base: str = trunk_log.TRUNK_REF) -> str:
    """Окно ветки — трейлер самого нового СВОЕГО коммита `base..HEAD`; нет — пусто.

    СВОИ КОММИТЫ, А НЕ ГОЛОВА (взгляд на #1087). Головой бывает слияние
    общей ветки, и трейлера у него нет: гейт по голове отвечал «не про неё»
    ровно на ветке, которую подтягивали к базе. Слияния не читаются вовсе — их
    тело пишет git, а не окно.
    """
    log = gitcall.output(
        ["log", "--no-merges", "--format=%B%x00", f"{base}..HEAD"],
        NotRun,
        cwd=str(root) if root else None,
    )
    for body in log.split(trunk_log.RECORD):
        said = sorted(trailers_in(body))
        if said:
            return said[-1]
    return ""


def own_open(repo: str, token: str, session: str) -> list[dict[str, Any]]:
    """Открытые изменения, чьи коммиты несут трейлер этого окна."""
    found = []
    for change in ghrest.paginate(f"repos/{repo}/pulls?state=open", token):
        commits = ghrest.paginate(f"repos/{repo}/pulls/{change['number']}/commits", token)
        if any(
            session in trailers_in(str(one.get("commit", {}).get("message", ""))) for one in commits
        ):
            found.append(change)
    return found


def overlaps(rows: list[tuple[int, str, str | None, str]], limit: int = LIMIT) -> list[int]:
    """Изменения, открытые, когда у того же окна уже было `limit` открытых.

    Строка — (номер, открыто, закрыто или ``None``, окно); время — ISO 8601
    одной зоны, и строки сравниваются как время. Окно пусто — строка не
    считается: чьё изменение, неизвестно.
    """
    found = []
    for number, opened, _, session in rows:
        if not session:
            continue
        busy = sum(
            1
            for other, since, until, whose in rows
            if whose == session
            and other != number
            and since < opened
            and (until is None or until > opened)
        )
        if busy >= limit:
            found.append(number)
    return found


def measure(root: Path) -> int:
    """Замер по истории площадки: сколько изменений открыто сверх предела (#1085).

    Окно изменения — трейлер в теле его уплотнения в общей ветке; время —
    открытие и закрытие по списку площадки. Неслитые без окна не считаются,
    и их число печатается (045).
    """
    token = ghrest.token_from_env()
    if not token:
        print("замер не сделан: токена площадки нет (045)", file=sys.stderr)
        return EXIT_UNASKED
    try:
        repo = check_branch_revival.repo_of(root)
        # Мелкий клон — отказ, как у счёта встреч: окна слитых изменений
        # недосчитались бы, а число печаталось бы полным (045, взгляд на #1087).
        trunk_log.whole(root)
        log = trunk_log.git_log(root)
    except (check_branch_revival.NotRun, trunk_log.NotRun) as exc:
        print(f"замер не сделан: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    whose = {
        number: sorted(trailers_in(body))[-1]
        for number, body in trunk_log.merged_messages(log)
        if trailers_in(body)
    }
    rows = [
        (
            int(one["number"]),
            str(one["created_at"]),
            one.get("closed_at"),
            whose.get(int(one["number"]), ""),
        )
        for one in ghrest.paginate(f"repos/{repo}/pulls?state=all", token)
    ]
    known = sum(1 for row in rows if row[3])
    over = overlaps(rows)
    print(
        f"изменений {len(rows)}, с известным окном {known}; открыто при {LIMIT} и более "
        f"открытых у того же окна — {len(over)}"
    )
    return EXIT_OK


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
        return EXIT_OK, f"свои коммиты ветки не несут трейлера {TRAILER} — предел окна не про неё"
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
    """Точка входа: одна ветка против числа открытых изменений окна; `--measure` — замер."""
    said = list(sys.argv[1:] if argv is None else argv)
    if said == [MEASURE]:
        return measure(Path())
    return check_branch_revival.cli(look, __doc__, NotRun, said)


if __name__ == "__main__":
    raise SystemExit(main())
