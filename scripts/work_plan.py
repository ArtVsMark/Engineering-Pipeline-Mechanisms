#!/usr/bin/env python3
"""План работ: зеркало источников 0–6 в одной живой задаче.

ЗАЧЕМ ОН, ЕСЛИ ИСТОЧНИКИ И ТАК ЕСТЬ. Источников работы семь
([091](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/091-work-sources-are-ordered-first-non-empty-wins.md)),
и каждый живёт в своём месте: краснота — в задаче шага 9, находки — в реестре
адресата, числа правил — во «входящих» каталога, своё открытое — у площадки.
Складывало их до сих пор ОКНО, в голове и заново на каждом заходе. Порядок,
который держится памятью, держится до конца окна
([134](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/134-a-window-reopens-only-after-the-rulebook-exists.md)).

ЗЕРКАЛО, А НЕ ВТОРОЕ МЕСТО ПРАВДЫ. Числа и строки здесь не СЧИТАЮТСЯ, а
читаются у тех, кто их ведёт, — теми же функциями, которыми их читает шаг
долга. Второй счёт того же разошёлся бы с первым молча, и разошёлся бы
незаметно: оба числа выглядят одинаково правдоподобно
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

ЧТО СБОРЩИК ПИШЕТ, А ЧТО НЕТ. Разделы 0–3 и 5 он собирает целиком: их предмет
знает механизм. Разделы 4 и 6 — указание владельца и его план — механизм не
знает и не сочиняет; их текст переносится дословно. Единственное, что сборщик
делает с ними, — СНИМАЕТ строку, чей адрес закрыт: это чтение источника, а не
сочинение.

СДЕЛАННОЕ ИСЧЕЗАЕТ, А НЕ ЛЕЖИТ ЗАЧЁРКНУТЫМ — тем же приёмом, что у реестра
находок. Галочка копит историю там, где нужен ОСТАТОК: план из двадцати строк,
где восемнадцать зачёркнуты, перестаёт отвечать на вопрос «чем заняться». След
при этом не теряется — он остался в источнике и в слитом изменении.

У СТРОКИ ВСЕГДА ЕСТЬ АДРЕС, и это условие работоспособности, а не оформление.
Снимает строку закрытая задача или ушедшая находка, а снять безадресную прозу
нечем: `- переделать бы доки` осталось бы в плане навсегда
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
Поэтому строка без адреса — отказ сборки, а не строка.

ИСТОЧНИК НЕ ПРОЧИТАН — ЭТО НЕ «ПУСТО». Раздел, чей источник не ответил,
говорит об этом вслух: пустота и молчание снаружи неотличимы, а значат разное
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ПРОГОНА У НЕГО НЕТ, И ЭТО ВЫБОР, А НЕ ПРОБЕЛ. Расписание сделало бы план
лентой событий: он обязан держаться, пока его не попросили обновить. Значит
единственный путь — вызов рукой, и требование «у события всегда есть ручная
кнопка»
([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md))
исполнено тем, что ручной путь здесь ЕДИНСТВЕННЫЙ. Появится нужда собирать по
событию — кнопка понадобится вместе с ним, а не раньше.

Исходы (правило 039): ``0`` план собран · ``2`` не отработало · ``3`` часть
источников не прочитана — сказано, а не выдано за пустоту.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

import debt
import findings
import ghrest
from report import announce

#: По этой строке план находится снова. Тем же приёмом, что у прочих живых
#: задач: номер задачи в коде не живёт, он меняется вместе с репозиторием.
MARKER: Final = "<!-- work-plan: не удаляйте, по этой строке план находится снова -->"

#: Заголовок раздела: номер источника и его имя. Имена — из договора
#: (`docs/behaviour.md`, контур 1), а не свои: два словаря на один предмет
#: разъезжаются молча (022).
HEADS: Final[dict[int, str]] = {
    0: "0 · Краснота общей ветки",
    1: "1 · Конфликт слияния на своём открытом изменении",
    2: "2 · Красное и находки на своём открытом изменении",
    3: "3 · Долг по уже слитому",
    4: "4 · Прямое указание владельца",
    5: "5 · Незакрытая работа по правилам каталога и дрейф",
    6: "6 · План автора",
}

#: Разделы, которые собирает механизм, и разделы, которые он только читает.
#: Список разрешительный (068): раздел, не названный здесь, сборщик не пишет.
BUILT: Final = (0, 1, 2, 3, 5)
HELD: Final = (4, 6)

#: Адрес строки: номер задачи либо отпечаток находки. Берётся ПЕРВЫЙ — предмет
#: строки, а не упомянутые рядом соседи: строка «#547 — это то, что #642
#: описывает» говорит о 547, и снимать её должно закрытие 547.
ISSUE_RE: Final = re.compile(r"#(\d+)")
MARK_RE: Final = re.compile(r"`([0-9a-f]{7})`")

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_PARTIAL: Final = 3


class NotRun(RuntimeError):
    """Сборщик не отработал: третий исход, а не «план пуст»."""


@dataclass(frozen=True)
class Source:
    """Один источник: строки работы и, если часть его молчит, — причина.

    МОЛЧАНИЕ И СТРОКИ УЖИВАЮТСЯ В ОДНОМ РАЗДЕЛЕ, и поле поэтому не «либо-либо».
    Источник 3 складывается из ДВУХ каналов — реестра находок и задачи о
    красноте, — и отказ одного не делает пустым другой. Пока молчание было
    альтернативой строкам, прочитанная половина вытесняла непрочитанную: раздел
    показывал строки и выглядел полным
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд на #651.
    """

    rows: list[str] = field(default_factory=list)
    note: str = ""
    unread: str = ""


def address_of(line: str) -> str:
    """Адрес строки плана: `#N`, отпечаток или пустая строка, если его нет."""
    said = MARK_RE.search(line)
    if said is not None:
        return said.group(1)
    found = ISSUE_RE.search(line)
    return f"#{found.group(1)}" if found is not None else ""


#: Черта, которой кончается последний раздел. Без неё подвал плана читался бы
#: строками раздела 6 и переезжал бы в него — то есть механизм сохранял бы
#: дословно собственную прошлую подпись, включая «механизма сборки ещё нет».
RULE: Final = "---"


def rows_of(body: str, head: str) -> list[str]:
    """Строки одного раздела: от его заголовка до следующего или до черты."""
    found: list[str] = []
    inside = False
    for line in body.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip() == head
            continue
        if inside and line.strip() == RULE:
            break
        if inside:
            found.append(line)
    while found and not found[0].strip():
        found.pop(0)
    while found and not found[-1].strip():
        found.pop()
    return found


def sources(repo: str, token: str) -> tuple[dict[int, Source], list[str], set[str]]:
    """Источники 0–3 и 5, прочитанные у тех, кто их ведёт.

    Отказ ОДНОГО источника не роняет весь план: остальные разделы собираются, а
    непрочитанный называет себя. План, исчезнувший целиком из-за молчания
    одного канала, хуже плана с названной дырой
    ([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
    """
    built: dict[int, Source] = {}
    broken: list[str] = []

    # ОТКАЗ ЭТОГО КАНАЛА КАСАЕТСЯ ДВУХ ИСТОЧНИКОВ, а не одного: задача о
    # красноте несёт и держащее слияние (0), и совещательное, пережившее его
    # (3). Пока отказ доходил только до нулевого, третий получал пустой список
    # и выглядел полным (045).
    lagging_silent = ""
    try:
        holding, lagging = debt.branch_debt(repo, token)
        built[0] = Source(rows=[f"**{one}** — держит слияние" for one in holding])
    except ghrest.TransportError as exc:
        built[0] = Source(unread=f"задача о красноте не прочитана: {exc}")
        broken.append("0")
        lagging = []
        lagging_silent = f"совещательное красное не спрошено: {exc}"

    try:
        conflicting, unknown, red = debt.stuck_changes(repo, token)
        built[1] = Source(
            rows=[f"{one} — база устарела" for one in conflicting],
            note=(
                "площадка ещё считает состояние слияния: " + ", ".join(unknown) if unknown else ""
            ),
        )
        built[2] = Source(rows=[f"{one} — красное на своей голове" for one in red])
    except ghrest.TransportError as exc:
        built[1] = built[2] = Source(unread=f"свои открытые изменения не спрошены: {exc}")
        broken += ["1", "2"]

    # РЕЕСТР ЧИТАЕТСЯ ОДИН РАЗ НА ЗАХОД. Отпечатки нужны и разделу 3, и снятию
    # строк ручных разделов; второе чтение того же стоило бы вызова из общей
    # квоты и разошлось бы с первым молча, изменись реестр между ними
    # ([058](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/058-when-the-quota-is-out-stop.md),
    # [022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    # Нашёл внешний взгляд на #651.
    marks: set[str] = set()
    # СТРОКИ СОСЕДНЕГО КАНАЛА СОБИРАЮТСЯ ОДИН РАЗ И НА ОБА ИСХОДА. Прежде
    # ветка отказа заводила раздел заново и выбрасывала уже прочитанное —
    # тот же дефект, что чинился здесь же, но в обратную сторону: сперва
    # непрочитанное выдавалось за пустоту, теперь непрочитанное вытесняло
    # прочитанное. Симметрию нашёл внешний взгляд на #652.
    stayed = [f"**{one}** — совещательное красное пережило слияние" for one in lagging]
    try:
        left = debt.findings_debt(repo, token)
        marks = {mark for mark, _, _ in left}
        rows = [f"`{mark}` · #{pr} — {said}" for mark, pr, said in left]
        built[3] = Source(rows=rows + stayed, unread=lagging_silent)
        if lagging_silent:
            broken.append("3")
    except ghrest.TransportError as exc:
        built[3] = Source(rows=stayed, unread=f"реестр находок не прочитан: {exc}")
        broken.append("3")

    try:
        closed = debt.closed_issues(repo, token)
        inbox, inbox_note, seen = debt.inbox_body(repo, token, closed)
        numbers = debt.rules_debt(inbox)
        note = debt.contract_note(inbox)
        if numbers is None:
            built[5] = Source(unread="числа каталога не найдены во «входящих»")
            broken.append("5")
        else:
            tasks, queue, unheld = numbers
            rows = []
            if queue:
                rows.append(f"правил без ответа: **{queue}**")
            if unheld:
                rows.append(f"правил «действует, но не держится ничем»: **{unheld}**")
            if note:
                rows.append(f"контракт разошёлся: {note}")
            said = debt.said_age(debt.age_of(seen))
            built[5] = Source(
                rows=rows,
                note=f"задач по правилам заведено {tasks}; числа {said}"
                + (f"; {inbox_note}" if inbox_note else ""),
            )
    except ghrest.TransportError as exc:
        built[5] = Source(unread=f"«входящие» каталога не прочитаны: {exc}")
        broken.append("5")

    return built, broken, marks


def render(number: int, source: Source, when: str = "") -> list[str]:
    """Раздел плана строками: работа, названная пустота или названное молчание.

    ПУСТОТА НЕСЁТ ДЕНЬ ОБХОДА. Тело плана переписывается поверх прежнего, и
    внешнего следа у прошлого захода не остаётся: без дня «нашёл и ничего нет»
    неотличимо от «не заходили с июля» — причём тем дольше, чем спокойнее
    выглядит пустой раздел, у застывшего механизма он ровно такой же
    ([027](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/027-empty-state-is-a-state.md)).
    """
    lines = [f"## {HEADS[number]}", ""]
    if source.rows:
        lines += [f"- {one}" for one in source.rows]
    elif not source.unread:
        lines.append(f"**Пусто** на {when or datetime.now(UTC).strftime('%d.%m.%Y')}.")
    lines.append("")
    if source.unread:
        lines += [f"⚠️ **Не спрошено:** {source.unread}", ""]
        lines += ["Это НЕ «пусто»: пустота и молчание снаружи неотличимы (045).", ""]
    if source.note:
        lines += [f"ℹ️ {source.note}", ""]
    return lines


def still_open(address: str, repo: str, token: str, marks: set[str]) -> bool:
    """Жив ли адрес строки: задача не закрыта либо находка ещё в реестре.

    ЗАКРЫТИЕ СПРАШИВАЕТСЯ У ПЛОЩАДКИ, А НЕ У ТЕЛА ПЛАНА. Тело плана пишет тот
    же механизм, и спрашивать его о судьбе работы значило бы спрашивать себя
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    """
    if not address.startswith("#"):
        return address in marks
    found = ghrest.request("GET", f"repos/{repo}/issues/{address[1:]}", token) or {}
    return str(found.get("state") or "open") != "closed"


def held_rows(body: str, number: int, repo: str, token: str, marks: set[str]) -> list[str]:
    """Строки ручного раздела: дословно, минус те, чей адрес закрыт."""
    kept: list[str] = []
    for line in rows_of(body, HEADS[number]):
        if not line.startswith("- "):
            kept.append(line)
            continue
        address = address_of(line)
        if not address:
            raise NotRun(
                f"строка раздела {number} без адреса — её нечем будет снять (154): {line.strip()}"
            )
        if still_open(address, repo, token, marks):
            kept.append(line)
    return kept


def assemble(body: str, built: dict[int, Source], held: dict[int, list[str]], when: str) -> str:
    """Тело плана: шапка прежняя, разделы — свои собранные и чужие сохранённые."""
    head = body.split("\n## ", 1)[0].rstrip()
    lines = [head, ""]
    for number in sorted(HEADS):
        if number in built:
            lines += render(number, built[number], when)
            continue
        lines += [f"## {HEADS[number]}", ""]
        lines += held.get(number, [])
        lines.append("")
    lines += [RULE, "", f"**Собрано:** {when} механизмом `scripts/work_plan.py` (#640)."]
    return "\n".join(one.rstrip() for one in lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает план и кладёт его в живую задачу."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="записать; без него — показать")
    args = parser.parse_args(argv)

    announce(not args.apply)
    token = ghrest.token_from_env()
    if not token or not args.repo:
        print("план не собран: нет токена или репозитория (045).", file=sys.stderr)
        return EXIT_PARTIAL

    try:
        number, body = findings.live_issue(args.repo, token, MARKER)
        if number is None:
            raise NotRun("живой задачи плана нет — заводить её механизм не берётся (154)")
        built, broken, marks = sources(args.repo, token)
        held: dict[int, list[str]] = {
            one: held_rows(body, one, args.repo, token, marks) for one in HELD
        }
        when = datetime.now(UTC).strftime("%d.%m.%Y")
        said = assemble(body, built, held, when)
    except (NotRun, ghrest.TransportError) as exc:
        print(f"сборщик не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    gone = sum(
        1
        for one in HELD
        for line in rows_of(body, HEADS[one])
        if line.startswith("- ") and line not in held[one]
    )
    if args.apply:
        ghrest.request("PATCH", f"repos/{args.repo}/issues/{number}", token, {"body": said})
        print(f"план #{number} собран" + (f"; снято сделанных строк: {gone}" if gone else ""))
    else:
        print(said)
    if broken:
        print(
            f"источники не прочитаны: {', '.join(broken)} — разделы названы молчащими, "
            "а не пустыми (045)",
            file=sys.stderr,
        )
        return EXIT_PARTIAL
    return EXIT_OK


def _run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    _run()
