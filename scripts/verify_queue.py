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

ДАТА СЛИЯНИЯ СПРАШИВАЕТСЯ, А НЕ ВЫВОДИТСЯ (взгляд на #1115). Окно закрытых
площадка упорядочивает по созданию, а не по закрытию: давнее изменение,
слитое вчера, в окно не попадает. Поэтому номер вне окна и не открытый
спрашивается у площадки отдельно, и закрытое без слияния слитым не
считается. Спрашиваются только номера непроверенных находок, и только когда
в сутках осталось место.

ПОТОЛОК ДЕРЖИТСЯ И БЕЗ ИМЕНИ ЗАПУСКА (взгляд на #1115). В потолок идёт
КАЖДЫЙ ручной запуск `review.yml` за сутки, с именем `verify <отпечаток>` или
без: копия `review.yml` у потребителя может быть старше `run-name`, и тогда
запуски звались бы «review» и не считались. Лишний счёт ручных нажатий —
безопасная сторона. Имя запуска нужно другому: находка, на которую
верификатор уже звался за `RECALL_DAYS`, повторно не зовётся — без отметки
`checked` (агент упал, токена нет) она иначе занимала бы место каждые сутки.

ВЕТКА ВЫЗОВА — ВЕТКА ПО УМОЛЧАНИЮ РЕПОЗИТОРИЯ, у площадки, а не буквой: у
потребителя общая ветка может зваться иначе.

Исходы (правило 039): ``0`` позвано или звать некого — что именно, названо ·
``2`` заход не отработал · ``3`` токен не задан — спросить не у кого.
"""

import argparse
import os
import random
import sys
from collections.abc import Callable
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
#: За сколько дней находка, на которую верификатор уже звался, не зовётся снова.
RECALL_DAYS: Final = 7
#: Сколько дат слияния вне окна спрашивается за заход. Заход идёт после каждой
#: пересборки плана, и без потолка давний реестр тратил бы квоту площадки
#: сотнями запросов (взгляд на #1121). Старт всегда с младших отдавал бы весь
#: потолок одним и тем же номерам — закрытым без слияния или ушедшим в 404 —
#: навсегда (взгляд на #1123).
#:
#: СЛУЧАЙНАЯ ВЫБОРКА, А НЕ КРУГ (210, взгляд на #1127). Круг со сдвигом по часу
#: держал обещание, только если заход идёт каждый час и набор между заходами не
#: меняется; заход же идёт по событию, а набор живёт. Каждая починка круга
#: рождала бы следующий обход. Выборка не зависит ни от расписания, ни от
#: позиций: в каждом заходе каждый номер вне окна спрашивается с вероятностью
#: `ASK_LIMIT / номеров`, и вечной немоты нет. СРОКА НЕТ, и это названо:
#: твёрдый срок требует памяти о спрошенном, а своей памяти у захода нет (049).
#:
#: ЦЕНА ВЫБОРКИ НАЗВАНА (поздний взгляд на #1129). Дата номера из окна известна
#: в каждом заходе, а номера вне окна — лишь когда он попал в выборку. Поэтому
#: при малом остатке суточного потолка очередь чаще заполняют недавние висящие
#: находки, а самые давние — ради которых верификатор и заведён — ждут без
#: верхней границы. Круг по часу ограничивал ожидание только при заходе каждый
#: час и неизменном наборе, то есть не ограничивал. Снимает это память о датах:
#: дата слияния не меняется, и спрошенную однажды можно хранить, — это новый
#: механизм: решение владельца 05.10.2026 — строить, место хранения — архив
#: находок (#1136).
ASK_LIMIT: Final = 20


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не «звать некого»."""


def candidates(
    entries: dict[str, findings.Entry],
    merged: dict[int, str],
    now: datetime,
    called: frozenset[str] = frozenset(),
) -> list[str]:
    """Отпечатки к проверке: по слитому, без отметки верификатора, старше срока; старые — первыми.

    `merged` — дата слияния по номеру; `called` — отпечатки, на которые
    верификатор уже звался в окне `RECALL_DAYS`. «Старые — первыми» — среди
    тех, чья дата известна в этот заход: из окна — всегда, вне окна — только
    попавшие в выборку `merged_dates`. Давняя находка вне выборки в очередь
    этого захода не попадает вовсе (цена названа у `ASK_LIMIT`).
    """
    edge = (now - timedelta(days=STALE_DAYS)).isoformat()
    ready = [
        (merged[entry.pr], mark)
        for mark, entry in entries.items()
        if changerefs.MARK_RE.fullmatch(mark)
        and not entry.checked
        and mark not in called
        and entry.pr in merged
        and merged[entry.pr] <= edge
    ]
    return [mark for _, mark in sorted(ready)]


def launched_today(runs: list[dict[str, Any]], now: datetime) -> int:
    """Сколько ручных запусков `review.yml` ушло за текущие сутки UTC — каждый, а не по имени."""
    day = now.astimezone(UTC).date().isoformat()
    return sum(1 for run in runs if str(run.get("created_at") or "").startswith(day))


def recently_called(runs: list[dict[str, Any]]) -> set[str]:
    """Отпечатки, на которые верификатор уже звался в окне чтения, — по имени запуска."""
    return {
        title.removeprefix(RUN_PREFIX)
        for run in runs
        if (title := str(run.get("display_title") or "")).startswith(RUN_PREFIX)
    }


#: Сколько последних закрытых изменений читается одним запросом.
WINDOW: Final = 100


def merged_dates(
    numbers: set[int],
    window: list[dict[str, Any]],
    live: set[int],
    ask: Callable[[int], str | None],
    limit: int = ASK_LIMIT,
    pick: Callable[[list[int], int], list[int]] = random.sample,
) -> tuple[dict[int, str], int]:
    """Дата слияния каждого названного изменения: из окна, а вне его — спросом.

    `window` — последние закрытые (`ghrest.merged_page`), `live` — номера
    открытых, `ask` — дата слияния одного номера у площадки (`None` — не
    слито). Номер из окна берёт свою дату; номер вне окна и не открытый
    спрашивается — окно упорядочено по созданию, и давнее, слитое вчера, в
    него не попадает. Открытое и закрытое без слияния в ответ не входят.

    Спросов не больше `limit`; номера вне окна берёт случайная выборка `pick`
    (`random.sample`; тест подставляет свою). Второе в ответе — сколько
    номеров осталось неспрошенными в этот заход.
    """
    seen = {int(one["number"]): one for one in window}
    said: dict[int, str] = {
        number: str(seen[number]["merged_at"])
        for number in numbers - live
        if number in seen and seen[number].get("merged_at")
    }
    outside = sorted(number for number in numbers - live if number not in seen)
    if not outside:
        return said, 0
    for number in pick(outside, min(limit, len(outside))):
        if merged_at := ask(number):
            said[number] = str(merged_at)
    return said, max(len(outside) - limit, 0)


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
        since = (now - timedelta(days=RECALL_DAYS)).date().isoformat()
        runs = list(
            ghrest.paginate(
                f"repos/{args.repo}/actions/workflows/{REVIEW_FLOW}/runs"
                f"?event=workflow_dispatch&created=>={since}",
                token,
                key="workflow_runs",
            )
        )
        room = max(DAILY_CAP - launched_today(runs, now), 0)
        if not room:
            print(
                f"запусков за сутки не осталось: потолок {DAILY_CAP} выбран — звать некого сегодня"
            )
            return EXIT_OK
        _, body = findings.live_issue(args.repo, token)
        # Отсев ДО спроса дат: проверенные и уже звавшиеся за `RECALL_DAYS` звать
        # не будут, и квота спросов на них не тратится (взгляд на #1123).
        called = frozenset(recently_called(runs))
        entries = {
            mark: entry
            for mark, entry in findings.parse_entries(body).items()
            if not entry.checked and mark not in called
        }
        _, window = ghrest.merged_page(args.repo, token, WINDOW)
        live = {
            int(one["number"])
            for one in ghrest.paginate(f"repos/{args.repo}/pulls?state=open", token)
        }

        def ask(number: int) -> str | None:
            # Номера нет у площадки (удалён, перенесён) — не слито, а не сбой
            # всего захода: одна такая запись иначе гасила бы вызовы на все
            # остальные (взгляд на #1121).
            try:
                said = ghrest.request("GET", f"repos/{args.repo}/pulls/{number}", token) or {}
            except ghrest.NotFound:
                return None
            return said.get("merged_at") if isinstance(said, dict) else None

        merged, unasked = merged_dates(
            {entry.pr for entry in entries.values()},
            window,
            live,
            ask,
        )
        trunk = str(
            (ghrest.request("GET", f"repos/{args.repo}", token) or {}).get("default_branch") or ""
        )
        if not trunk:
            raise NotRun("ветка по умолчанию репозитория не названа площадкой")
    except (NotRun, ghrest.TransportError) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    queue = candidates(entries, merged, now, called)
    print(
        f"висящих находок по слитому (старше {STALE_DAYS} дн., без проверки, не звались "
        f"{RECALL_DAYS} дн.): {len(queue)}; запусков за сутки осталось {room} из {DAILY_CAP}"
    )
    if unasked:
        print(
            f"  дат слияния не спрошено: {unasked} (потолок {ASK_LIMIT}) — их находок нет в "
            "очереди этого захода; следующие берут свою выборку, срока у номера нет"
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
                {"ref": trunk, "inputs": {"mark": mark}},
            )
        except ghrest.TransportError as exc:
            print(f"заход не отработал: верификатор на {mark} не позван: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        print(f"  верификатор позван на {mark}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
