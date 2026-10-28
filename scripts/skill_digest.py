#!/usr/bin/env python3
"""Недельная сводка применения навыков по сырым записям — свои и соседей (#1694).

ЧТО СВОДИТСЯ. Сырые записи `skills.json` с ветки `badges` (их дописывает
`skill_record.py` на каждом слитом изменении): по неделе слияния и по навыку —
сколько изменений навык ждали, сколько из них несут строку `Навык:` с ним и
сколько назвали навык без ожидания по признакам. РЯД С РАЗМЕРОМ ВЫБОРКИ, А НЕ
ПРОЦЕНТ (#1694): «ждали 2, вызван 1» и «ждали 40, вызван 20» — разное знание, и
процент их уравнял бы.

СЕМЬЯ — ТЕМ ЖЕ ОБХОДОМ, ЧТО ФАКТЫ СОСЕДЕЙ (слово владельца 26.10.2026, #1694):
список семьи — из сводки каталога (`family_uptake.family`), файл соседа — тем
же читателем ветки `badges` (`badges_read.by_api`). Сосед без файла записей —
«записей нет», сосед, чей файл не прочитан, — назван поимённо: незнание не
ноль (039, 045).

ЖИВАЯ ЗАДАЧА-АНАЛИТИКА. Механизм переписывает ТОЛЬКО блок между метками
`BLOCK_START` и `BLOCK_END`; ниже блока — вопросы и решения человека, и
«почему не применён» разбирается там по номерам изменений. Метки блока нет —
блок встаёт в начало тела, а прежний текст сохраняется ниже целиком.

ГРАНИЦЫ НАЗВАНЫ. `invoked` — самоотчёт окна (поле `source` каждой записи),
`expected` — след в слитом, а не намерение (`skill_signals`): сводка говорит,
что навык ждали и назвали, а не что его применили верно.

Исходы (правило 039): ``0`` сводка записана, уже описывает состояние или
сухой заход · ``2`` не отработал — нет токена, свои записи не прочитаны,
площадка молчит.
"""

import argparse
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import badges_read
import family_uptake
import findings
import ghrest
import main_guard
import report

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Имя файла записей на ветке `badges` — тот, что пишет `skill_record`.
NAME: Final = "skills.json"
#: Метка живой задачи-аналитики.
MARKER: Final = findings.marker("skills-digest")
#: Заголовок задачи.
TITLE: Final = "Применение навыков: ждали — вызван, по неделям и по семье"
#: Блок, который механизм переписывает; вне его — текст человека.
#: Метки блока — не метка задачи: её пишет одна константа `MARKER` (209).
BLOCK_START: Final = "<!-- блок сводки: начало -->"
BLOCK_END: Final = "<!-- блок сводки: конец -->"
#: Сколько последних недель показывать: ряд, а не вся история (она в записях).
WEEKS: Final = 8
#: Неделя записи, чей день не разобран.
UNKNOWN_WEEK: Final = "?"
#: Сколько соседей обходит сводка за заход: на столько рассчитана оценка
#: вызовов площадки в `.rules/schedules.json` (два вызова на соседа). Сосед
#: за пределом — «не прочитан» поимённо, а не молча (поздний взгляд на #1715).
FAMILY_AT_MOST: Final = 10
#: Поле записи с проектом, из чьего файла она прочитана (`mine`).
REPO: Final = "repo"
#: Строка дня сборки: сверка «то же состояние» её не читает.
DATED: Final = "Собрано:"


class NotRun(RuntimeError):
    """Сводка не собрана: третий исход, а не пустой ряд."""


def records_of(store: Any) -> list[dict[str, Any]]:
    """Записи из прочитанного файла; форма не та — `NotRun`."""
    if not isinstance(store, dict) or not isinstance(store.get("records"), list):
        raise NotRun(f"{NAME}: форма не та — ждётся словарь с records")
    return [one for one in store["records"] if isinstance(one, dict)]


def week_of(day: str) -> str:
    """Неделя слияния ISO: `2026-W44`; день не разобран — `?`, а не текущая неделя."""
    try:
        year, week, _ = date.fromisoformat(day).isocalendar()
    except TypeError, ValueError:
        return UNKNOWN_WEEK
    return f"{year}-W{week:02d}"


def tally(records: list[dict[str, Any]]) -> dict[str, dict[tuple[str, str], list[int]]]:
    """Неделя → (проект, навык) → [ждали, из них вызван, вызван без ожидания].

    ПРОЕКТ — В КЛЮЧЕ (поздний взгляд на #1715): записи соседей и свои
    складывались в одну строку навыка, и «по семье» нельзя было прочесть, чей
    ряд. Проект ставит `gather` по файлу, из которого запись прочитана.
    """
    table: dict[str, dict[tuple[str, str], list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0, 0])
    )
    for one in records:
        week = week_of(str(one.get("merged_at") or ""))
        whose = str(one.get(REPO) or "?")
        wanted = {str(name) for name in one.get("expected") or []}
        said = {str(name) for name in one.get("invoked") or []}
        for name in wanted:
            table[week][(whose, name)][0] += 1
            table[week][(whose, name)][1] += name in said
        for name in said - wanted:
            table[week][(whose, name)][2] += 1
    return table


def mine(repo: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Записи с проектом, из чьего файла они прочитаны: источник — файл, а не запись."""
    return [{**one, REPO: repo} for one in records]


def gather(
    repo: str, token: str, family: list[str]
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Записи свои и соседей; соседи без файла и непрочитанные — двумя списками.

    Свои не прочитаны — `NotRun`: сводка о семье без себя выдавала бы чужой ряд
    за общий. Сосед без файла — законно: шага записи у него может не быть.
    """
    try:
        records = mine(repo, records_of(badges_read.by_api(repo, NAME, token)))
    except ghrest.NotFound:
        records = []
    except ghrest.TransportError as exc:
        raise NotRun(f"свои записи не прочитаны: {exc}") from exc
    empty: list[str] = []
    unread: list[str] = []
    for one in family[FAMILY_AT_MOST:]:
        print(f"::warning::{one}: записи навыков не прочитаны — за пределом обхода семьи")
        unread.append(one)
    for one in family[:FAMILY_AT_MOST]:
        try:
            records += mine(one, records_of(badges_read.by_api(one, NAME, token)))
        except ghrest.NotFound:
            empty.append(one)
        except (ghrest.TransportError, NotRun) as exc:
            print(f"::warning::{one}: записи навыков не прочитаны — {report.cut(str(exc))}")
            unread.append(one)
    return records, empty, unread


def block(records: list[dict[str, Any]], empty: list[str], unread: list[str], today: date) -> str:
    """Блок сводки между метками: неделями сверху вниз, навыки по имени."""
    table = tally(records)
    lines = [
        BLOCK_START,
        f"{DATED} {today.strftime('%d.%m.%Y')}. Записей: {len(records)}.",
        "",
        "Ряд — число изменений, а не процент: «ждали» — по признакам в шапке навыка,",
        "«вызван» — по строке `Навык:` тела слитого коммита (самоотчёт окна).",
    ]
    if empty:
        lines += ["", f"Записей нет у соседей: {', '.join(sorted(empty))}."]
    if unread:
        lines += ["", f"**Не прочитаны:** {', '.join(sorted(unread))} — это незнание, а не ноль."]
    # Неделя «?» — день не разобран — идёт последней и место в ряду недель не
    # занимает: при обратной сортировке строкой она вставала выше всех
    # настоящих недель (поздний взгляд на #1715).
    weeks = sorted((one for one in table if one != UNKNOWN_WEEK), reverse=True)[:WEEKS]
    for week in [*weeks, *([UNKNOWN_WEEK] if UNKNOWN_WEEK in table else [])]:
        rows = table[week]
        lines += [
            "",
            f"### Неделя {week}",
            "",
            "| проект | навык | ждали | из них вызван | вызван без ожидания |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {whose} | `{name}` | {said[0]} | {said[1]} | {said[2]} |"
            for (whose, name), said in sorted(rows.items())
        ]
    if not table:
        lines += ["", "Записей ещё нет: ряд начнётся с первого слитого изменения."]
    return "\n".join([*lines, BLOCK_END])


def body_with(current: str, fresh: str) -> str:
    """Тело задачи с новым блоком; текст человека вне блока сохраняется целиком."""
    if not current:
        return (
            f"{MARKER}\n\n"
            "> **Читатель:** владелец и окно, разбирающие, почему навык ждали, а не\n"
            "> позвали. Блок ниже переписывает механизм (`skill_digest.py`, раз в\n"
            "> неделю); ниже блока — вопросы и решения человека, их он не трогает.\n\n"
            f"{fresh}\n\n## Вопросы и решения\n"
        )
    start, end = current.find(BLOCK_START), current.find(BLOCK_END)
    if start == -1 or end < start:
        head, _, rest = current.partition("\n")
        return f"{head}\n\n{fresh}\n{rest}" if head.startswith("<!--") else f"{fresh}\n\n{current}"
    return current[:start] + fresh + current[end + len(BLOCK_END) :]


def stable(body: str) -> str:
    """Тело без строки дня сборки: с ней сверка «то же состояние» держалась бы сутки."""
    return findings.undated(body, (DATED,))


def save(repo: str, token: str, fresh: str, *, apply: bool) -> None:
    """Переписывает блок живой задачи или заводит её; `TransportError` — наверх."""
    number, current = findings.live_issue(repo, token, MARKER)
    body = body_with(current, fresh)
    if number is not None and stable(current) == stable(body):
        print(f"задача-аналитика #{number} уже описывает это состояние")
        return
    if not apply:
        print(f"{report.DRY} {'обновил бы' if number else 'завёл бы'} задачу-аналитику навыков")
        return
    if number is None:
        fresh_issue = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"заведена задача-аналитика навыков #{(fresh_issue or {}).get('number')}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"задача-аналитика навыков #{number} обновлена")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: записи свои и семьи — в блок живой задачи-аналитики."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=family_uptake.OURS, help="наш репозиторий")
    parser.add_argument("--summary", type=Path, help="сводка семьи where.json; нет — без соседей")
    parser.add_argument("--apply", action="store_true", help="записать, а не показать")
    args = parser.parse_args(argv)
    token = ghrest.token_from_env()
    if not token:
        print("сводка навыков не собрана: нет токена площадки", file=sys.stderr)
        return EXIT_BROKEN
    try:
        family: list[str] = []
        if args.summary is not None:
            try:
                family = family_uptake.family(local=args.summary)
            except family_uptake.NotRun as exc:
                print(f"::warning::семья не прочитана — сводка только своя: {exc}")
        records, empty, unread = gather(args.repo, token, family)
        print(
            f"записей навыков: {len(records)}; соседей без записей {len(empty)}, "
            f"не прочитано {len(unread)}"
        )
        save(
            args.repo,
            token,
            block(records, empty, unread, datetime.now(UTC).date()),
            apply=args.apply,
        )
    except (NotRun, ghrest.TransportError) as exc:
        print(f"сводка навыков не собрана: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
