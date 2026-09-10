#!/usr/bin/env python3
"""Реестр слитого без внешнего взгляда: факт отсутствия, а не находка.

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ МЕХАНИЗМ, А НЕ ЕЩЁ ОДНА НАХОДКА. Находка говорит «вот
дефект»; здесь говорится «дефекта, может, и нет, но искать было некому».
Ревью объявлено совещательным намеренно (`.pipeline.yml`): красное у ревьюера
говорит о ревьюере, а не о работе, и обязательный канал из него сделал бы
простой на каждом сбое чужого действия
([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).

Обратная сторона у этого одна и до сих пор ничем не закрыта: **«взгляд был и
находок нет» и «взгляда не было вовсе» снаружи выглядят одинаково**. Изменение
сливается, код возврата умирает вместе с прогоном, и через неделю сказать,
смотрел ли кто-нибудь на слитое, нечем
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ДВА СОСТОЯНИЯ, А НЕ ОДНО, И ЭТО ГРАНИЦА, НАЗВАННАЯ ЗАРАНЕЕ. Повторный прогон
по слитому — НЕ то же ревью: он видит код после слияния, а не тот, что смотрел
бы до. Соседние изменения уже влились, конфликтов нет, история переписана
уплотнением. Для аудита общей ветки это законный предмет, но назвать такой
прогон «ревью изменения» значило бы записать, что взгляд состоялся, когда
состоялся другой
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

ПРИЧИНА НАЗЫВАЕТСЯ ТЕМ, ЧТО ВИДНО, А НЕ ДОГАДКОЙ. Задача просила четыре
причины — «вердикта не было · прогон упал · секрета нет · находки не закрыты», —
и артефакты дают из них не четыре, а полторы.

* **«секрета не было» и «прогон отработал и промолчал» снаружи одинаковы**: оба
  оставляют изменение без строки вердикта, и различить их можно только логом
  прогона, а лога у механизма нет — он читает то, что прогон пережило;
* **«прогон упал» состоянием записи проверки не читается**: шаг ревью объявлен
  `continue-on-error`, поэтому джоб зелен и когда действие свалилось. Видимая
  часть этой причины другая — ревьюер начал отвечать и не закончил: строки
  находок есть, итоговой нет. Она и записывается, под своим именем;
* **«находки не закрыты» здесь не записывается вовсе, и это не забывчивость**:
  у незакрытых находок уже есть адресат — живая задача механизма ревью, и она
  же считается долгом перед планом. Второй список того же разошёлся бы с первым
  молча
  ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

Названо это здесь, а не сглажено умолчанием
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).

ЗАПИСЬ СНИМАЕТСЯ ОПОЗДАВШИМ ВЕРДИКТОМ, А НЕ ЖИВЁТ ВЕЧНО. Вердикт бывает
позже слияния — у соседа замерено опоздание на 2,3 минуты. Поэтому открытые
состояния перечитываются каждым заходом: появился вердикт — запись уходит сама.
«Поздний взгляд» не перечитывается: его ставит человек, и вердикта на самом
изменении от этого не появится.

Исходы (правило 039): ``0`` слитого без взгляда нет · ``2`` шаг не отработал ·
``3`` запись есть, и она записана.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final

import findings
import ghrest
import report
import review_findings

MARKER: Final = "<!-- unlooked: не удаляйте, по этой строке задача находится снова -->"
TITLE: Final = "Слитое без внешнего взгляда"

#: Взгляда не было вовсе: ни строк находок, ни строки вердикта.
STATE_NONE: Final = "вердикта нет"
#: Ревьюер отвечал, но вердикта не поставил: строки находок есть, итоговой нет.
#: Это и есть видимая часть «прогон упал» — большего артефакты не говорят.
STATE_CUT: Final = "ответ оборван: находки есть, вердикта нет"
#: Был поздний взгляд — по общей ветке, после слияния. Другой предмет, и
#: называется он другим словом.
STATE_LATE: Final = "поздний взгляд по общей ветке"
STATES: Final = (STATE_NONE, STATE_CUT, STATE_LATE)
#: Состояния, которые заход перечитывает: вердикт бывает позже слияния.
#: «Поздний взгляд» сюда не входит — его ставит человек, и вердикта на самом
#: изменении от этого не появится.
OPEN_STATES: Final = (STATE_NONE, STATE_CUT)

#: Скрытая строка, которой поздний взгляд называет себя поздним. Его вердикт
#: тоже строка «ВЕРДИКТ: находок N», и без этой отметки он снял бы запись
#: «взгляда не было»: реестр сказал бы, что взгляд был вовремя, — ровно та
#: подмена, ради которой состояния и разведены (154).
LATE_MARKER: Final = "<!-- late-look: этот взгляд по общей ветке, а не по изменению -->"

#: Запись реестра читается СТРОКОЙ: номер, состояние, дата слияния.
ENTRY_RE: Final = re.compile(r"^- #(\d+) · ([^·]+) · (\S*)\s*$", re.M)
#: Отметка обхода: до какого номера реестр уже смотрел. Без неё каждый заход
#: перечитывал бы комментарии всего окна — тридцать запросов к площадке на
#: каждое событие очереди.
WATERMARK_RE: Final = re.compile(r"^Просмотрено до: #(\d+)\s*$", re.M)

EXIT_NOTHING: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RECORDED: Final = 3

#: Сколько последних слитых изменений видно за заход. Окно закрывает
#: пропущенное событие, а не заменяет обход истории: если между заходами слито
#: больше, отметка обхода перешагнёт неувиденное, и об этом будет сказано.
#: Значение общее с остальными механизмами окна: «недавно» у них одно.
WINDOW: Final = ghrest.MERGED_WINDOW


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «всё просмотрено»."""


@dataclass(frozen=True, slots=True)
class Entry:
    """Одна запись реестра: что слито, в каком состоянии и когда."""

    number: int
    state: str
    merged: str


def parse_entries(body: str | None) -> dict[int, Entry]:
    """Разбирает реестр: номер изменения → запись."""
    return {
        int(number): Entry(int(number), state.strip(), merged)
        for number, state, merged in ENTRY_RE.findall(body or "")
    }


def parse_watermark(body: str | None) -> int:
    """Докуда реестр уже смотрел; ноль — не смотрел никуда."""
    found = WATERMARK_RE.findall(body or "")
    return int(found[-1]) if found else 0


merged_changes = ghrest.merged_changes


def look_of(comments: list[dict[str, Any]]) -> str | None:
    """Что видно о взгляде на изменение: ``None`` — вердикт был, иначе состояние.

    Читаются те же строки тем же разбором, что и у механизма находок: второе
    понимание одного формата разошлось бы с первым молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    if review_findings.verdict_of(comments) is not None:
        return None
    return STATE_CUT if review_findings.findings_of(comments) else STATE_NONE


def look_at(repo: str, number: int, token: str) -> str | None:
    """То же по живому изменению: спрашивает площадку и разбирает ответ.

    Комментарии позднего взгляда исключаются по его отметке: они говорят о
    коде в общей ветке, а вопрос здесь — смотрел ли кто-нибудь на изменение,
    пока оно было изменением.
    """
    comments = [
        comment
        for comment in ghrest.paginate(f"repos/{repo}/issues/{number}/comments", token)
        if LATE_MARKER not in (comment.get("body") or "")
    ]
    return look_of(comments)


def scan(
    merged: Iterable[dict[str, Any]],
    known: dict[int, Entry],
    watermark: int,
    look: Callable[[int], str | None],
) -> tuple[dict[int, Entry], int]:
    """Ведёт реестр по окну слитого: новое записывает, просмотренное снимает.

    Площадки здесь нет намеренно: она приходит одним `look`, и подделать её в
    проверке можно, не подделывая транспорт
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-proved-by-what-it-rejects.md)).
    """
    entries = dict(known)
    # Сначала перечитывается уже записанное: вердикт мог опоздать к слиянию, и
    # запись обязана уйти сама, а не ждать, пока её снимут рукой. Состояние при
    # этом тоже уточняется: оборванный ответ бывает дописан.
    for number, entry in list(entries.items()):
        if entry.state not in OPEN_STATES:
            continue
        state = look(number)
        if state is None:
            entries.pop(number)
        elif state != entry.state:
            entries[number] = Entry(number, state, entry.merged)
    mark = watermark
    for item in merged:
        number = int(item["number"])
        mark = max(mark, number)
        if number <= watermark or number in entries:
            continue
        state = look(number)
        if state is None:
            continue
        entries[number] = Entry(number, state, str(item.get("merged_at") or "")[:10])
    return entries, mark


def mark_late(entries: dict[int, Entry], number: int) -> dict[int, Entry]:
    """Переводит запись в «поздний взгляд»: он состоялся, но это другой взгляд.

    Записи о таком изменении может и не быть — тогда она заводится: поздний
    взгляд по слитому это событие само по себе, и терять его из-за того, что
    реестр этого номера не знал, значило бы отчитаться о меньшем, чем было.
    """
    entry = entries.get(number)
    return {**entries, number: Entry(number, STATE_LATE, entry.merged if entry else "")}


def render_body(entries: dict[int, Entry], watermark: int) -> str:
    """Собирает тело реестра: записи, а не счётчик."""
    lines = [
        MARKER,
        "",
        "> **Читатель:** окно и владелец. Здесь то, что уехало в общую ветку,",
        "> **не получив внешнего взгляда**, — факт отсутствия, а не находка.",
        "",
        "Ревью совещательное намеренно: красное у ревьюера говорит о ревьюере, а",
        "не о работе. Цена этого одна — «взгляд был и находок нет» и «взгляда не",
        "было вовсе» снаружи одинаковы. Реестр разводит их обратно.",
        "",
        "Состояния — то, что видно, а не догадка о причине:",
        "",
        f"* «{STATE_NONE}» — на изменении нет ни строк находок, ни итоговой.",
        "  Почему — не сказано: «секрета не было» и «прогон промолчал» снаружи",
        "  одинаковы, и различить их можно только логом прогона (046);",
        f"* «{STATE_CUT}» — ревьюер начал отвечать и не закончил. Это видимая",
        "  часть «прогон упал»: сам джоб зелен всегда, шаг ревью объявлен",
        "  `continue-on-error`, и краснеть ему нечем;",
        f"* «{STATE_LATE}» — НЕ то же ревью: поздний прогон видит код после",
        "  слияния, соседние изменения уже влились, история переписана",
        "  уплотнением. Законный аудит общей ветки, но не взгляд на изменение.",
        "",
        "Незакрытых находок здесь нет намеренно: у них свой адресат — живая",
        "задача механизма ревью, и она же считается долгом перед планом. Второй",
        "список того же разошёлся бы с первым молча (022).",
        "",
        "Запись снимается сама, если вердикт всё же появился: он бывает позже",
        "слияния. Задачу закрывает человек: механизм не знает, разобран остаток",
        "или просто надоел.",
        "",
        f"Просмотрено до: #{watermark}",
        "",
        "## Не просмотрено",
        "",
    ]
    if not entries:
        lines.append("Пусто — у всего слитого в окне обхода взгляд был.")
        return "\n".join(lines) + "\n"
    for number in sorted(entries, reverse=True):
        entry = entries[number]
        lines.append(f"- #{entry.number} · {entry.state} · {entry.merged}")
    return "\n".join(lines) + "\n"


def save(repo: str, token: str, entries: dict[int, Entry], watermark: int, apply: bool) -> None:
    """Записывает реестр: обновляет по месту или заводит одну задачу."""
    number, _ = findings.live_issue(repo, token, MARKER)
    body = render_body(entries, watermark)
    if not apply:
        print(f"записал бы {len(entries)} в " + (f"#{number}" if number else "новую задачу"))
        return
    if number is None:
        created = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"реестр заведён: #{(created or {}).get('number')}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"реестр обновлён: #{number}, записей {len(entries)}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: ведёт реестр и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--limit", type=int, default=WINDOW, help="окно обхода слитых изменений")
    parser.add_argument("--apply", action="store_true", help="записать, а не показать")
    parser.add_argument("--late", type=int, help="номер изменения, по которому был поздний взгляд")
    args = parser.parse_args(argv)

    entries: dict[int, Entry] = {}
    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")

        _, body = findings.live_issue(args.repo, token, MARKER)
        merged = merged_changes(args.repo, token, args.limit)
        entries, watermark = scan(
            merged,
            parse_entries(body),
            parse_watermark(body),
            lambda number: look_at(args.repo, number, token),
        )
        if args.late is not None:
            entries = mark_late(entries, args.late)

        if len(merged) >= args.limit:
            # Окно заполнено целиком — значит, за ним могло остаться слитое,
            # которого заход не увидел, а отметка обхода его перешагнула.
            print(
                f"::warning::окно обхода заполнено ({args.limit}) — за ним могло остаться "
                "слитое, которого этот заход не видел",
                file=sys.stderr,
            )

        without = [item for item in entries.values() if item.state in OPEN_STATES]
        print(
            f"слито без взгляда: {len(without)}, позже просмотрено: {len(entries) - len(without)}"
        )
        for entry in sorted(entries.values(), key=lambda item: -item.number):
            print(f"  #{entry.number} · {entry.state} · {entry.merged}")

        save(args.repo, token, entries, watermark, args.apply)
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except ghrest.TransportError as exc:
        print(f"шаг не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_RECORDED if entries else EXIT_NOTHING


if __name__ == "__main__":
    raise SystemExit(main())
