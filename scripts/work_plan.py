#!/usr/bin/env python3
"""План работ: зеркало источников 0–6 в одной живой задаче.

ЗАЧЕМ ОН, ЕСЛИ ИСТОЧНИКИ И ТАК ЕСТЬ. Источников работы семь
([091](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/091-work-sources-are-ordered-first-non-empty-wins.md)),
и каждый живёт в своём месте: краснота — в задаче шага 9, находки — в реестре
адресата, числа правил — во «входящих» каталога, дрейф — в своей живой
задаче, своё открытое — у площадки.
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
знает и не сочиняет; их текст переносится дословно. Со строками этих разделов
сборщик делает две вещи, и обе — чтение источника, а не сочинение: СНИМАЕТ
строку, чей адрес закрыт, и ДОБАВЛЯЕТ в конец раздела 4 открытую задачу,
рождённую работой по строке раздела 4 или 6 (`born_rows`, #747).

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

ЗАХОД ИДЁТ ПО ПРОГОНУ КОНВЕЙЕРА, А НЕ ПО РАСПИСАНИЮ. Здесь стояло «прогона у
него нет, и это выбор, а не пробел», и довод был неверен. Расписание он
отвергал справедливо — план не лента событий, — но выводил из этого
единственный путь рукой, а «по запросу» держится на том, что кто-то вспомнит:
правило без механизма
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЗАМЕР, КОТОРЫЙ ЭТО ОТМЕНИЛ: 23.09.2026 за смену слилось СЕМЬ изменений, и всё
это время план оставался вчерашним — строка закрытой задачи висела, раздел 3
показывал находки, снятые трейлерами. Заметил владелец, а не механизм.

ПРОГОН КОНВЕЙЕРА — НЕ РАСПИСАНИЕ: это момент, в который источники МЕНЯЮТСЯ, и
моментов таких три. Слияние меняет источники 3 и 5: задача закрывается,
находка снимается трейлером, общая ветка меняет цвет. Проверка на голове
ИЗМЕНЕНИЯ меняет источники 1 и 2 — конфликт и красное на своём открытом; они
живут и гаснут между слияниями, и заход только по слиянию их бы не видел.
Поэтому будит сборщик завершение `ci` на любой голове, а не только на общей.
Третий момент — ночной заход дрейфа: он переписывает задачу дрейфа, а это
половина источника 5 (#665).

Ручная кнопка остаётся рядом и нужна отдельно
([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md)):
находка бывает и без прогона — поздний взгляд на уже слитое кладёт запись в
реестр, а прогона за ней не идёт.

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
from pathlib import Path
from typing import Any, Final

import changerefs
import debt
import drift
import finding_kinds
import findings
import ghrest
import paths
from report import announce

#: По этой строке план находится снова. Тем же приёмом, что у прочих живых
#: задач: номер задачи в коде не живёт, он меняется вместе с репозиторием.
MARKER: Final = findings.PLAN_MARKER

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

    # ИСТОЧНИК 5 СКЛАДЫВАЕТСЯ ИЗ ДВУХ КАНАЛОВ, как и источник 3: «входящие»
    # каталога и задача дрейфа. Договор называет дрейф частью источника 5
    # (`docs/behaviour.md`, контур 1), а сборщик его не читал — раздел
    # выглядел полным, когда дрейф назвал бы работу (#665). Каналы читаются
    # порознь: отказ одного не стирает прочитанное у другого — тот же урок,
    # что у источника 3 (#651).
    rules = rules_part(repo, token)
    moved = drift_part(repo, token)
    born = birth_part()
    parts = (rules, moved, born)
    built[5] = Source(
        rows=[row for part in parts for row in part.rows],
        note="; ".join(part.note for part in parts if part.note),
        unread="; ".join(part.unread for part in parts if part.unread),
    )
    if built[5].unread:
        broken.append("5")

    return built, broken, marks


def rules_part(repo: str, token: str) -> Source:
    """Половина источника 5 о правилах каталога — из «входящих»."""
    try:
        closed = debt.closed_issues(repo, token)
        inbox, inbox_note, seen = debt.inbox_body(repo, token, closed)
    except ghrest.TransportError as exc:
        return Source(unread=f"«входящие» каталога не прочитаны: {exc}")
    numbers = debt.rules_debt(inbox)
    if numbers is None:
        return Source(unread="числа каталога не найдены во «входящих»")
    tasks, queue, unheld = numbers
    rows = []
    if queue:
        rows.append(f"правил без ответа: **{queue}**")
    if unheld:
        rows.append(f"правил «действует, но не держится ничем»: **{unheld}**")
    note = debt.contract_note(inbox)
    if note:
        rows.append(f"контракт разошёлся: {note}")
    said = debt.said_age(debt.age_of(seen))
    return Source(
        rows=rows,
        note=f"задач по правилам заведено {tasks}; числа {said}"
        + (f"; {inbox_note}" if inbox_note else ""),
    )


def birth_part(where: Path | None = None) -> Source:
    """Третья часть источника 5 — поводы для правила из инцидентов (#650).

    Род находки, встреченный не реже порога и без ответа каталогу, — это
    незакрытая работа по правилам: либо предложение, либо «своё», либо «правило
    есть». Новый род такой ответ несёт с момента, когда дошёл до порога (гейт
    `check_rule_birth`); прежние, дошедшие раньше, называет здесь план.

    СЛОВАРЯ НЕТ — ЭТО НАЗВАННОЕ МОЛЧАНИЕ, А НЕ ПУСТОТА. Пути в проекте
    относительно корня, как у всех механизмов; запуск не из корня прежде давал
    пустой раздел, неотличимый от «поводов нет» (`13f3a9d`). У плана словарь
    есть всегда, и его отсутствие — поломка захода. То же с очередью
    предложений: без неё ответ «предложено» не сверить, и это молчание, а не
    «без ответа» у каждого такого рода (`dd1da87`).
    """
    declared = where or paths.FINDING_KINDS
    queue_path = declared.parent / paths.PROPOSALS.name
    try:
        kinds = finding_kinds.read(declared)
        left = finding_kinds.unanswered(kinds, finding_kinds.queued(queue_path))
    except finding_kinds.NotRun as exc:
        return Source(unread=f"роды находок не прочитаны: {exc}")
    return Source(
        rows=[
            f"род находок у порога без ответа каталогу: «{name}» — встреч {times}"
            for name, times in left
        ]
    )


#: Что сказать о задаче дрейфа, которую давно не переписывали. Срок у ночных
#: заходов один (`debt.STALE_AFTER`), а пропущенный заход — свой.
DRIFT_LATE: Final = "ночной заход дрейфа, похоже, пропущен"


def drift_part(repo: str, token: str) -> Source:
    """Половина источника 5 о дрейфе — записи живой задачи дрейфа.

    Строка плана несёт номер задачи дрейфа: он и есть адрес — снимается запись
    там, а не здесь, когда расхождения больше нет.

    ЗАДАЧИ ДРЕЙФА НЕТ — ЭТО «ПУСТО», А НЕ ОТКАЗ. Дрейф не заводит пустую задачу
    (`drift.save`), и её отсутствие значит «записей не было ни разу». А вот
    источники, которые дрейф не спросил, называются: без них пустой список
    читался бы как «всё сошлось» (045).
    """
    try:
        number, body, seen = findings.live_issue_seen(repo, token, drift.MARKER)
    except ghrest.TransportError as exc:
        return Source(unread=f"задача дрейфа не прочитана: {exc}")
    if number is None:
        return Source()
    found, silent = drift.read_back(body)
    notes = [f"обход дрейфа {debt.said_age(debt.age_of(seen), DRIFT_LATE)}"]
    if silent:
        notes.append("дрейф не спросил: " + ", ".join(silent))
    return Source(
        rows=[f"#{number} · `{one.source}` — {one.said}" for one in found],
        note="; ".join(notes),
    )


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

    МОЛЧАНИЕ ПЛОЩАДКИ СТРОКУ НЕ СНИМАЕТ — умолчание «открыта» здесь намеренно.
    Это обратная сторона `may_be_born`, где молчание строку НЕ добавляет: в
    обоих случаях без явного ответа план не меняется. Снять строку по пустому
    ответу значило бы потерять указание владельца молча (045); лишняя строка
    уйдёт следующей сборкой, потерянную не вернёт никто (взгляд на #758).
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


#: Раздел, в который встаёт задача, рождённая работой по ручным разделам.
BORN_INTO: Final = 4
#: Хвост строки рождённой задачи: чья работа её родила.
BORN_TAIL: Final = "родилась в работе по"


def may_be_born(issue: dict[str, Any], repo: str, taken: frozenset[int] | set[int]) -> bool:
    """Может ли задача встать рождённой строкой — ОДНА проверка на оба пути.

    Путь по связи в теле и путь по подзадаче раньше отсекали разное: живая
    задача механизма со связью в теле отсекалась, та же задача подзадачей —
    нет (взгляд на #754). Условия собраны здесь, и обоим путям других нет:
    открытая задача, а не изменение; не стоит в плане; не живая задача
    механизма (план, реестры); своего хранилища.

    ХРАНИЛИЩЕ СВЕРЯЕТСЯ БЕЗ УЧЁТА РЕГИСТРА: имена владельца и хранилища у
    площадки регистронезависимы, и `--repo` в другом регистре уводил все свои
    подзадачи в чужие молча. Чужое хранилище называется вслух (045).
    """
    number = int(issue.get("number") or 0)
    text = str(issue.get("body") or "")
    if not number or "pull_request" in issue or number in taken:
        return False
    # Состояние — ТОЛЬКО явное: ответ без поля не делает задачу открытой
    # молча (взгляд на #756).
    if issue.get("state") != "open":
        return False
    if findings.is_plan(text) or findings.is_kept_by_a_mechanism(text):
        return False
    home = str(issue.get("repository_url") or "")
    if home and not home.lower().endswith(f"/repos/{repo}".lower()):
        print(f"#{number} из другого хранилища ({home}) — в план не встаёт")
        return False
    return True


def born_rows(
    repo: str, token: str, held: dict[int, list[str]], taken: frozenset[int] = frozenset()
) -> list[str]:
    """Строки раздела 4 для задач, рождённых работой по строкам разделов 4 и 6.

    РЕШЕНИЕ ВЛАДЕЛЬЦА 24.09.2026 (#747): задача, заведённая по ходу работы над
    строкой ручного раздела, встаёт в раздел 4 сама. Иначе её не видит
    порядок работ (091), пока владелец не внесёт её рукой.

    РОДИЛАСЬ — ЗНАЧИТ СВЯЗАНА СО СТРОКОЙ: связью (`Refs`/`Closes`/`Part of
    #X` в теле — тем же разбором, что у изменений) или подзадачей X, где X —
    адрес строки раздела 4 или 6. Ссылка на живые задачи-адресаты (план,
    реестры) рождением не считается: их в этих разделах нет, а `Refs #639`
    несёт почти каждая задача. Задача, уже стоящая в разделе 4 или 6, второй
    раз не добавляется; добавленная становится обычной строкой — дальше её
    сохраняет и снимает тот же порядок, что руку, а её дети встают следом.

    Порядок внутри раздела ставит владелец: механизм добавляет в конец.

    ЧТО РОЖДЕНИЕМ НЕ СЧИТАЕТСЯ (взгляд на #750). Живая задача механизма —
    план и реестры — не рождена работой, даже если её тело несёт `refs #X`
    (`d21a0b9`). Подзадача из ДРУГОГО хранилища не встаёт строкой `**#N**`:
    адрес строки читается как задача этого проекта (`446c2fe`). Задача, уже
    стоящая в ЛЮБОМ разделе плана (`taken`: и собранные 0–3 и 5), второй раз
    не добавляется (`365d40a`).

    УДАЛЁННАЯ РУКОЙ РОЖДЁННАЯ СТРОКА ВЕРНЁТСЯ, пока задача открыта и связана
    (`1bff680`, `729e813`): памяти о прошлых заходах у сборщика нет, и
    отличить «удалил, потому что не в план» от «ещё не добавлял» нечем. Отказ
    выражается тем, что сборщик читает: строку переносят в раздел 6 (повтор
    отсекается и там), закрывают задачу либо снимают связь в её теле.
    """
    parents = {
        int(address[1:])
        for one in HELD
        for line in held.get(one, [])
        if line.startswith("- ") and (address := address_of(line)).startswith("#")
    }
    if not parents:
        return []
    found: dict[int, tuple[str, int]] = {}
    for issue in ghrest.paginate(f"repos/{repo}/issues?state=open", token):
        if not may_be_born(issue, repo, parents | taken):
            continue
        links = changerefs.links_in(str(issue.get("body") or ""))
        linked = [link.number for link in links if link.number in parents]
        if linked:
            found.setdefault(int(issue["number"]), (str(issue.get("title") or ""), linked[0]))
    for parent in sorted(parents):
        for issue in ghrest.paginate(f"repos/{repo}/issues/{parent}/sub_issues", token):
            if may_be_born(issue, repo, parents | taken):
                found.setdefault(int(issue["number"]), (str(issue.get("title") or ""), parent))
    return [
        f"- **#{number}** — {title} *({BORN_TAIL} #{parent})*"
        for number, (title, parent) in sorted(found.items())
    ]


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


#: Сколько раз сборка повторяется, если рука правит план во время захода.
#: Правка человека занимает секунды, заход между чтением и записью — тоже; три
#: подряд совпадения означали бы, что план правят непрерывно, и тогда писать
#: поверх — хуже, чем отказаться и сказать об этом.
TRIES: Final = 3


def hand_part(body: str) -> list[str]:
    """То, что в плане пишет рука: шапка и строки ручных разделов."""
    return [
        body.split("\n## ", 1)[0],
        *(line for one in HELD for line in rows_of(body, HEADS[one])),
    ]


def fresh_build(
    repo: str, token: str, built: dict[int, Source], marks: set[str], when: str, apply: bool
) -> tuple[int, str, dict[int, list[str]], str]:
    """Собирает план по свежему телу и перед записью сверяет, не правила ли его рука.

    ПОТЕРЯННАЯ ПРАВКА ЧЕЛОВЕКА ХУЖЕ ОТКАЗА СБОРКИ. Сборщик переписывает тело
    целиком, а разделы 4 и 6 и шапку ведёт владелец: всё, что он поменял между
    чтением тела и записью, затиралось бы без следа. Поэтому перед записью тело
    перечитывается, и если рука успела поправить шапку или ручные разделы,
    сборка повторяется на свежем теле. Разделы механизма сверять не нужно:
    параллельных заходов сборщика нет — у прогона одна группа.

    ГРАНИЦА. Окно между перечитыванием и записью остаётся — площадка не даёт
    записи «если тело не менялось». Оно сужено с минуты опроса источников до
    одного запроса.

    СОСЕДИ ПО ПРИЗНАКУ «ПЕРЕПИСЫВАЕТ ТЕЛО ЗАДАЧИ ПОСЛЕ ДОЛГОЙ РАБОТЫ» НАЗВАНЫ
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    Тело задачи через PATCH пишут восемь механизмов. Шесть — `drift`,
    `review_findings`, `unlooked`, `stuck`, `schedules_seen`, `main_red` —
    ведут тело целиком сами, ручной части в нём нет, и потерять правку
    человека им нечем. Седьмой — `items.follow` — пишет в тела ЭПИКОВ, которые
    ведёт человек, и между чтением и записью спрашивает состояния задач: тот
    же дефект, и он починен тем же приёмом — чтение до пересчёта и ещё раз
    перед записью. `items.mark` читает задачу и пишет
    её сразу, без работы между — окно в один запрос, как здесь. Нашёл внешний
    взгляд на #684 (`55d530e`).
    """
    for _ in range(TRIES):
        number, body = findings.live_issue(repo, token, MARKER)
        if number is None:
            raise NotRun("живой задачи плана нет — заводить её механизм не берётся (154)")
        held = {one: held_rows(body, one, repo, token, marks) for one in HELD}
        taken = frozenset(
            int(address[1:])
            for source in built.values()
            for row in source.rows
            if (address := address_of(row)).startswith("#")
        )
        held[BORN_INTO] = held[BORN_INTO] + born_rows(repo, token, held, taken)
        said = assemble(body, built, held, when)
        if not apply:
            return number, body, held, said
        _, current = findings.live_issue(repo, token, MARKER)
        if hand_part(current) == hand_part(body):
            return number, body, held, said
        print("рука правила план во время захода — собираю заново по свежему телу")
    raise NotRun(
        f"план правили во время каждого из {TRIES} заходов — писать поверх правки "
        "человека сборщик не берётся"
    )


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
        # ИСТОЧНИКИ СПРАШИВАЮТСЯ ДО ТЕЛА, а не после: опрос идёт минуту, и
        # тело, прочитанное в начале, к записи устаревает. Замер 23.09.2026:
        # владелец поставил #673 первым в раздел 4, а заход, прочитавший тело
        # до правки, записал его после — и указание владельца пропало молча.
        built, broken, marks = sources(args.repo, token)
        when = datetime.now(UTC).strftime("%d.%m.%Y")
        number, body, held, said = fresh_build(args.repo, token, built, marks, when, args.apply)
    except (NotRun, ghrest.TransportError) as exc:
        print(f"сборщик не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    gone = sum(
        1
        for one in HELD
        for line in rows_of(body, HEADS[one])
        if line.startswith("- ") and line not in held[one]
    )
    born = [line for line in held[BORN_INTO] if BORN_TAIL in line and line not in body]
    if args.apply:
        ghrest.request("PATCH", f"repos/{args.repo}/issues/{number}", token, {"body": said})
        print(f"план #{number} собран" + (f"; снято сделанных строк: {gone}" if gone else ""))
        if born:
            print(f"в раздел {BORN_INTO} встало рождённых работой задач: {len(born)}")
    else:
        # НОМЕР ПЛАНА ПЕЧАТАЕТСЯ И СУХИМ ЗАХОДОМ: навык `work-the-plan` не
        # прибивает номер живой задачи и отсылает за ним сюда, а в самом теле
        # номера нет. Нашёл внешний взгляд на #689 (`5a0aac6`).
        print(f"план #{number} — собрал бы так:")
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
