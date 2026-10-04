#!/usr/bin/env python3
"""Верификатор по плану: висящие находки по слитому идут на проверку премисы (#1005).

РЕШЕНИЕ ВЛАДЕЛЬЦА 04.10.2026 (#1005, вариант 3). Верификатор (`verify` в
`review.yml`) берёт ОДНУ находку и пытается опровергнуть её премису. Звали его
только кнопкой, и за всю историю он отработал дважды: поле `checked` пусто у
всех 1904 записей архива, и гейт правила 044 мерить не на чем. Звать его на
каждую находку — заход агента на каждую из десятков в день. Здесь он зовётся
ровно туда, ради чего заведён: на находки по УЖЕ СЛИТОМУ, которые висят дольше
`STALE_DAYS` и рискуют оказаться починенными (случай `1fd43a4`).

ПОТОЛОК — ЗАПУСКИ ЗА СУТКИ, СЧИТАННЫЕ У ПЛОЩАДКИ (049). Своего счётчика у
захода нет: он короткий, и память разошлась бы с площадкой. Запуск верификатора
несёт имя прогона `verify <отпечаток>` (`run-name` в `review.yml`), и заход
считает такие прогоны за текущие сутки по UTC. Потолок — `DAILY_CAP`.

ПОДСТАНОВКА ОТПЕЧАТКА — ВХОД ПРОГОНА, И ОН УЗКИЙ (085). Отпечаток берётся из
разбора реестра (`findings.parse_entries`) и обязан быть семью шестнадцатерич-
ными знаками (`changerefs.MARK_RE`): иное в `inputs.mark` не уходит.

ГРАНИЦА НАЗВАНА (195). Возраст находки — со дня слияния её изменения: даты
записи реестр не хранит. Находку позднего взгляда, пришедшую через неделю
после слияния, заход сочтёт старой сразу. Это сдвиг к ранней проверке, а не к
пропуску, и предел суток держит его цену.

Исходы (правило 039): ``0`` позвано или звать некого — что именно, названо ·
``2`` заход не отработал · ``3`` токен не задан — спросить не у кого.
"""

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import changerefs
import findings
import ghrest
import report

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_UNSET: Final = 3

#: С какого возраста находка по слитому считается висящей, дней.
STALE_DAYS: Final = 3
#: Сколько запусков верификатора за сутки (UTC), считая уже ушедшие.
DAILY_CAP: Final = 3
#: Прогон верификатора и приставка имени его запуска (`run-name`).
REVIEW_FLOW: Final = "review.yml"
RUN_PREFIX: Final = "verify "


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не «звать некого»."""


#: Дата слияния изменения, которое старше окна слитых: заведомо давнее срока.
LONG_AGO: Final = ""


def candidates(
    entries: dict[str, findings.Entry], merged: dict[int, str], now: datetime
) -> list[str]:
    """Отпечатки к проверке: по слитому, без отметки верификатора, старше срока; старые — первыми.

    `merged` — дата слияния по номеру; `LONG_AGO` — слито раньше окна
    чтения, и такая находка идёт первой.
    """
    edge = (now - timedelta(days=STALE_DAYS)).isoformat()
    ready = [
        (merged[entry.pr], mark)
        for mark, entry in entries.items()
        if changerefs.MARK_RE.fullmatch(mark)
        and not entry.checked
        and entry.pr in merged
        and merged[entry.pr] <= edge
    ]
    return [mark for _, mark in sorted(ready)]


def launched_today(runs: list[dict[str, Any]], now: datetime) -> int:
    """Сколько запусков верификатора уже ушло за текущие сутки UTC — по имени прогона."""
    day = now.astimezone(UTC).date().isoformat()
    return sum(
        1
        for run in runs
        if str(run.get("display_title") or "").startswith(RUN_PREFIX)
        and str(run.get("created_at") or "").startswith(day)
    )


#: Сколько последних закрытых изменений читается одним запросом.
WINDOW: Final = 100


def merged_dates(numbers: set[int], window: list[dict[str, Any]], live: set[int]) -> dict[int, str]:
    """Дата слияния каждого названного изменения — ДВУМЯ чтениями на весь реестр (#1065).

    `window` — последние закрытые (`ghrest.merged_page`), `live` — номера
    открытых. Номер из окна берёт свою дату; номер старше окна и не открытый
    слит давно (`LONG_AGO`). Закрытое без слияния, неоткрытое и открытое в
    ответ не входят: проверять по нему нечего.
    """
    found = {int(one["number"]): str(one["merged_at"]) for one in window if one.get("merged_at")}
    oldest = min((int(one["number"]) for one in window), default=0)
    return {
        number: found.get(number, LONG_AGO)
        for number in numbers
        if number in found or (number < oldest and number not in live)
    }


def main(argv: list[str] | None = None) -> int:
    """Точка входа: один заход — не больше остатка суточного потолка запусков."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--dry-run", action="store_true", help="назвать, не запуская")
    args = parser.parse_args(argv)
    token = ghrest.token_from_env()
    if not token:
        print("звать некому: токена площадки нет (045)", file=sys.stderr)
        return EXIT_UNSET
    now = datetime.now(UTC)
    try:
        if not args.repo:
            raise NotRun("репозиторий не назван")
        _, body = findings.live_issue(args.repo, token)
        entries = findings.parse_entries(body)
        _, window = ghrest.merged_page(args.repo, token, WINDOW)
        live = {
            int(one["number"])
            for one in ghrest.paginate(f"repos/{args.repo}/pulls?state=open", token)
        }
        merged = merged_dates({entry.pr for entry in entries.values()}, window, live)
        runs = list(
            ghrest.paginate(
                f"repos/{args.repo}/actions/workflows/{REVIEW_FLOW}/runs"
                f"?event=workflow_dispatch&created=>={now.date().isoformat()}",
                token,
                key="workflow_runs",
            )
        )
    except (NotRun, ghrest.TransportError) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    queue = candidates(entries, merged, now)
    room = max(DAILY_CAP - launched_today(runs, now), 0)
    print(
        f"висящих находок по слитому (старше {STALE_DAYS} дн., без проверки): {len(queue)}; "
        f"запусков за сутки осталось {room} из {DAILY_CAP}"
    )
    for mark in queue[:room]:
        if args.dry_run:
            print(f"  {report.DRY} позвал бы верификатор на {mark}")
            continue
        try:
            ghrest.request(
                "POST",
                f"repos/{args.repo}/actions/workflows/{REVIEW_FLOW}/dispatches",
                token,
                {"ref": "main", "inputs": {"mark": mark}},
            )
        except ghrest.TransportError as exc:
            print(f"заход не отработал: верификатор на {mark} не позван: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        print(f"  верификатор позван на {mark}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
