#!/usr/bin/env python3
"""Заход по расписанию случился — или не случился, и это видно.

ПЛОЩАДКА НЕ ОБЕЩАЕТ `schedule`. Заход может не произойти вовсе: под нагрузкой
расписания откладывают и теряют, и снаружи потерянный запуск неотличим от
ненаступившего часа — нигде не краснеет, потому что краснеть нечему
([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md),
[169](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/169-cron-is-a-hint-not-a-cadence.md)).
Замер соседа-профиля: один пропуск за девять дней. У нас числа не было вовсе.

ВТОРОЕ СОСТОЯНИЕ — УПАВШИЙ ЗАХОД. Он краснеет, но краснеет на вкладке
прогонов, а вкладка адресатом не является: её никто не открывает, пока не
заподозрит. Оба состояния получают одного адресата — живую задачу, которую
ведёт этот же механизм.

ОЖИДАЕМОЕ ЧИСЛО СЧИТАЕТСЯ ИЗ ОБЪЯВЛЕННОГО РАСПИСАНИЯ, а не из наблюдений:
`.rules/schedules.json` — то же объявление, по которому держится цена захода, и
второй список того же разошёлся бы с первым на первой же правке (022).

САМ СЕБЯ ЭТОТ ЗАХОД НЕ СТОРОЖИТ, и это названо, а не умолчано: он идёт по
событию, а не по расписанию, и в объявлении расписаний его нет. Сторожить
сторожа можно было бы только вторым сторожем, а второй счёт того же
расходится с первым молча.

Исходы (правило 039): ``0`` все заходы на месте · ``1`` есть пропуски или
падения · ``2`` заход не отработал.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import findings
import ghrest
import paths
import report

#: Объявление расписаний — то же, по которому держится цена захода (022).
DECLARED: Final = paths.SCHEDULES

EXIT_OK: Final = 0
EXIT_MISSED: Final = 1
EXIT_BROKEN: Final = 2

TITLE: Final = "Расписания: пропущенные и упавшие заходы"
MARKER: Final = findings.marker("schedules-seen")

#: Окно обхода: за сколько суток считаются пропуски. Неделя, а не сутки:
#: один пропуск в сутки — это шум площадки, а ряд за неделю уже мера
#: надёжности канала (169).
WINDOW_DAYS: Final = 7

#: Сколько пропусков подряд терпимо. Ноль означал бы красное на первой же
#: задержке площадки, а задержка — не потеря
#: ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
#: Это ГИПОТЕЗА: ряда у нас пока нет, и первый же ряд её пересматривает.
TOLERATED: Final = 1

#: Исходы прогона, считающиеся состоявшимся заходом. Отменённый заходом не
#: считается: он не сделал работы, ради которой заведён.
HAPPENED: Final = frozenset({"success", "failure", "neutral", "timed_out", "action_required"})
#: Исходы, означающие упавший заход.
FELL: Final = frozenset({"failure", "timed_out", "action_required"})


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не «пропусков нет» (039)."""


@dataclass(frozen=True, slots=True)
class Seen:
    """Что известно про один прогон по расписанию за окно обхода."""

    name: str
    cron: str
    expected: int
    happened: int
    fell: int

    @property
    def missed(self) -> int:
        """Сколько заходов не случилось. Лишние заходы в минус не уводят.

        Прогон могли запустить кнопкой или чужим событием, и вычитать это из
        пропусков значило бы прятать потерю за ручным заходом.
        """
        return max(0, self.expected - self.happened)

    @property
    def loud(self) -> bool:
        """Есть ли о чём говорить: пропусков сверх терпимого или падения."""
        return self.missed > TOLERATED or self.fell > 0

    def said(self) -> str:
        """Строка реестра: что за прогон и что с ним."""
        about = f"ожидалось {self.expected}, случилось {self.happened}"
        if self.missed:
            about += f", пропущено {self.missed}"
        if self.fell:
            about += f", упало {self.fell}"
        return f"- `{self.name}` (`{self.cron}`) — {about}"


def declared(where: Path = DECLARED) -> dict[str, str]:
    """Объявленные расписания: файл прогона → выражение cron."""
    try:
        document: dict[str, Any] = json.loads(where.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotRun(f"объявление расписаний не прочитано: {report.cut(str(exc))}") from exc
    runs = document.get("runs")
    if not isinstance(runs, dict) or not runs:
        raise NotRun("в объявлении нет ни одного расписания — предмет обхода не найден (075)")
    return {str(name): str((one or {}).get("cron") or "") for name, one in runs.items()}


def expected_between(cron: str, since: datetime, until: datetime) -> int:
    """Сколько раз расписание обязано было сработать в окне.

    РАЗБИРАЮТСЯ НЕ ВСЕ ФОРМЫ CRON, И НЕРАЗОБРАННАЯ — ЭТО ОТКАЗ, А НЕ НОЛЬ.
    Приблизительный ответ, выданный за точный, здесь хуже отсутствующего: он
    объявил бы «пропусков нет» там, где их не считали
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Разбираются ровно те формы, что у нас есть: «минута час * * *» (ежедневно)
    и «минута * * * *» (ежечасно).
    """
    fields = cron.split()
    if len(fields) != 5:
        raise NotRun(f"расписание «{cron}» не вида из пяти полей — считать нечем")
    minute, hour, day, month, weekday = fields
    if (day, month, weekday) != ("*", "*", "*"):
        raise NotRun(f"расписание «{cron}»: разбор дней не сделан — форма не поддержана (045)")
    if not minute.isdigit():
        raise NotRun(f"расписание «{cron}»: минута не числом — форма не поддержана (045)")
    step = timedelta(days=1) if hour.isdigit() else timedelta(hours=1)
    if not hour.isdigit() and hour != "*":
        raise NotRun(f"расписание «{cron}»: час не числом и не «*» — форма не поддержана (045)")

    at = since.replace(minute=int(minute), second=0, microsecond=0)
    if step == timedelta(days=1):
        at = at.replace(hour=int(hour))
    while at < since:
        at += step
    count = 0
    while at <= until:
        count += 1
        at += step
    return count


def born(repo: str, name: str, token: str) -> datetime | None:
    """Когда прогон появился у площадки; ``None`` — если спросить не удалось.

    ОЖИДАНИЕ НАЧИНАЕТСЯ НЕ РАНЬШЕ, ЧЕМ ПРОГОН ПОЯВИЛСЯ. Без этого окно обхода
    требует заходов от расписания, которого в те дни не существовало: замер
    12.09.2026 объявил `hail.yml` 163 пропуска за неделю, хотя прогон был
    заведён накануне. Число, полученное так, не мера надёжности канала, а мера
    возраста файла
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    try:
        got = ghrest.request("GET", f"repos/{repo}/actions/workflows/{name}", token) or {}
    except ghrest.TransportError:
        return None
    said = str(got.get("created_at") or "")
    if not said:
        return None
    return datetime.fromisoformat(said.replace("Z", "+00:00"))


def fired(repo: str, name: str, token: str, since: datetime) -> tuple[int, int]:
    """Сколько заходов по расписанию случилось и сколько из них упало.

    Спрашиваются прогоны СОБЫТИЯ `schedule`: ручная кнопка и чужое событие
    заходом по расписанию не являются, и складывать их значило бы прятать
    пропуск за ручным запуском.
    """
    # СПИСОК ИДЁТ СТРАНИЦАМИ, И ЭТО НЕ ЗАПАС НА БУДУЩЕЕ. Ежечасное расписание
    # за неделю даёт 168 заходов — больше страницы, — и обход, читающий одну,
    # объявил бы пропуском всё, что за её краем: чем ИСПРАВНЕЕ канал, тем
    # больше он «пропускает». Нашёл внешний взгляд на #269.
    try:
        found = list(
            ghrest.paginate(
                f"repos/{repo}/actions/workflows/{name}/runs?event=schedule",
                token,
                key="workflow_runs",
            )
        )
    except ghrest.NotFound:
        # Прогона с таким именем у площадки нет: объявление разошлось с
        # деревом. Это отказ входа, а не «заходов не было» (075).
        raise NotRun(
            f"прогон «{name}» площадке неизвестен — объявление разошлось с деревом"
        ) from None
    happened = 0
    fell = 0
    for run in found:
        started = str(run.get("created_at") or "")
        if not started:
            continue
        when = datetime.fromisoformat(started.replace("Z", "+00:00"))
        if when < since:
            continue
        outcome = str(run.get("conclusion") or "")
        if outcome in HAPPENED:
            happened += 1
        if outcome in FELL:
            fell += 1
    return happened, fell


def sweep(repo: str, token: str, now: datetime, days: int = WINDOW_DAYS) -> list[Seen]:
    """Обход всех объявленных расписаний: по каждому — ожидание и случившееся."""
    window = now - timedelta(days=days)
    seen: list[Seen] = []
    for name, cron in sorted(declared().items()):
        # НЕПРОЧИТАННЫЙ ВОЗРАСТ НЕ ДАЁТ ПОБЛАЖКИ: считаем от начала окна, как
        # считали бы всегда. Поблажка из незнания скрыла бы пропуски у прогона,
        # про который не удалось спросить (045).
        appeared = born(repo, name, token)
        since = max(window, appeared) if appeared else window
        happened, fell = fired(repo, name, token, since)
        seen.append(Seen(name, cron, expected_between(cron, since, now), happened, fell))
    return seen


def render_body(seen: list[Seen], now: datetime, days: int) -> str:
    """Тело реестра: пересобирается заходом целиком, а не дописывается."""
    lines = [
        MARKER,
        "",
        "> **Читатель:** владелец и окно. Здесь заходы по расписанию, которые",
        "> **не случились** или **упали**.",
        "",
        "Площадка не обещает `schedule`: заход может не произойти вовсе, и",
        "потерянный запуск снаружи неотличим от ненаступившего часа — краснеть",
        "нечему. Упавший заход краснеет, но на вкладке прогонов, а вкладка",
        "адресатом не является.",
        "",
        f"Обход: {now.strftime('%Y-%m-%d %H:%M')} UTC, окно {days} сут.",
        "",
        "## Требуют взгляда",
        "",
    ]
    loud = [item for item in seen if item.loud]
    if not loud:
        lines.append("Пусто — все объявленные заходы на месте.")
    else:
        lines.extend(item.said() for item in loud)
    lines += ["", "## Весь ряд", ""]
    lines.extend(item.said() for item in seen)
    return "\n".join(lines) + "\n"


def save(repo: str, token: str, seen: list[Seen], now: datetime, days: int, *, apply: bool) -> None:
    """Записывает реестр: обновляет по месту или заводит одну задачу."""
    number, _ = findings.live_issue(repo, token, MARKER)
    body = render_body(seen, now, days)
    if not apply:
        print(f"записал бы {len(seen)} строк в " + (f"#{number}" if number else "новую задачу"))
        return
    if number is None:
        created = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"реестр заведён: #{(created or {}).get('number')}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"реестр обновлён: #{number}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: считает пропуски и падения, объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--days", type=int, default=WINDOW_DAYS, help="окно обхода, суток")
    parser.add_argument("--apply", action="store_true", help="записать реестр, а не показать")
    args = parser.parse_args(argv)

    try:
        if not args.repo:
            raise NotRun("репозиторий не назван — обходить нечего (075)")
        token = ghrest.token_from_env()
        now = datetime.now(UTC)
        seen = sweep(args.repo, token, now, args.days)
        for item in seen:
            print(item.said())
        # ЗАПИСЬ РЕЕСТРА — ВНУТРИ РАЗБОРА ОТКАЗОВ. Отказ площадки на записи
        # (права, квота, сеть) выходил отсюда необработанным и становился
        # кодом 1, а единица по договору значит «есть пропуски»: читатель
        # получал бы «канал осекается» там, где осеклась сама запись, — то
        # есть третий исход подменялся первым (039). Нашёл внешний взгляд
        # на #269.
        save(args.repo, token, seen, now, args.days, apply=args.apply)
    except (NotRun, ghrest.TransportError) as exc:
        print(f"обход не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN

    loud = [item for item in seen if item.loud]
    if not loud:
        print(f"все объявленные заходы на месте: расписаний {len(seen)}, окно {args.days} сут.")
        return EXIT_OK
    print(f"требуют взгляда: {len(loud)} из {len(seen)}")
    return EXIT_MISSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
