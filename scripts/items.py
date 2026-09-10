#!/usr/bin/env python3
"""Отметка пунктов задачи: один разбор на всех, кто её ставит.

Площадка умеет только полное закрытие: `Closes #N` закрывает задачу целиком, и
задача из нескольких этапов закрывается преждевременно вместе с несделанными.
`Refs #N` не отмечает ничего. Поэтому пункт называется строкой в теле работы, и
отметка едет ВМЕСТЕ с работой, а не отдельным жестом, который забудут
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ МОДУЛЬ. Ставят отметку двое: шаг слияния — по объявлению
АВТОРА, и разбор слитого — по выводу агента. Предмет у них разный, а работа
одна: найти пункт в теле задачи и отметить его, не испортив уже отмеченного.
Второе понимание того же разошлось бы с первым молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ПУНКТ УЗНАЁТСЯ ПО ТЕКСТУ, А НЕ ПО НОМЕРУ СТРОКИ: номер сдвигается от любой
правки тела задачи, и отметка уехала бы на соседний пункт молча.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import changerefs
import ghrest
import report

#: Незакрытый пункт чек-листа задачи. Отмечается ровно он: уже отмеченный
#: остаётся отмеченным, и повторный заход ничего не портит.
CHECKLIST_RE: Final = re.compile(r"^\s*[-*]\s*\[ \]\s*(?P<text>\S.*?)\s*$")
#: Уже отмеченный пункт. Нужен отдельно: «отметил» и «был отмечен» дают
#: одинаковое тело задачи, а значат разное, и без второго образца повтор
#: объявлялся бы ненайденным пунктом.
DONE_ITEM_RE: Final = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*(?P<text>\S.*?)\s*$")


@dataclass(frozen=True, slots=True)
class Outcome:
    """Чем кончилась отметка: что легло, что не записалось, чего нет нигде."""

    marked: list[str]
    unwritten: list[str]
    missing: list[str]


def marked(body: str, item: str) -> tuple[str, bool]:
    """Отмечает пункт сделанным; вторым отдаёт, НАШЁЛСЯ ли он вообще.

    Два ответа вместо одного, и разница не косметическая. «Пункт отмечен этим
    заходом» и «пункт был отмечен раньше» дают одинаковое тело задачи, а
    значат разное: первое — работа, второе — повтор. Пока их различало
    сравнение тел, уже отмеченный пункт объявлялся ненайденным — то есть
    механизм звал на помощь там, где всё было в порядке (045).
    """
    wanted = changerefs.normalise(item)
    lines = body.splitlines()
    for place, line in enumerate(lines):
        open_item = CHECKLIST_RE.match(line)
        if open_item and changerefs.normalise(open_item.group("text")) == wanted:
            lines[place] = line.replace("[ ]", "[x]", 1)
            return "\n".join(lines), True
        done_item = DONE_ITEM_RE.match(line)
        if done_item and changerefs.normalise(done_item.group("text")) == wanted:
            return body, True
    return body, False


def open_items(body: str) -> list[str]:
    """Незакрытые пункты задачи — как написаны, в порядке появления."""
    return [found.group("text") for found in map(CHECKLIST_RE.match, body.splitlines()) if found]


def done_items(body: str) -> list[str]:
    """Отмеченные пункты — симметрично незакрытым.

    Оба образца сверяются ПОСТРОЧНО: у них есть `^` и `$`, но нет флага
    построчного разбора, и поиск по телу целиком нашёл бы только пункт в самой
    первой строке. Симметричная функция здесь для того и заведена — чтобы
    читателю не пришлось помнить об этом (090).
    """
    return [found.group("text") for found in map(DONE_ITEM_RE.match, body.splitlines()) if found]


#: Окно догоняющего обхода — общее для всех, кто смотрит «что недавно слито».
#: Оно закрывает ПРОПУЩЕННОЕ событие и неудавшуюся запись, а не заменяет
#: историю: заход идёт по событию слияния, и обходить всё прошлое ему незачем.
WINDOW: Final = ghrest.MERGED_WINDOW
merged_changes = ghrest.merged_changes


#: Голая ссылка на задачу внутри пункта: `#27`. Глагола здесь нет и быть не
#: должно — пункт эпика НАЗЫВАЕТ задачу, а не объявляет связь изменения с ней,
#: и `changerefs.links_in` такой формы не читает намеренно.
TASK_REF_RE: Final = re.compile(r"(?<![\w/])#(?P<number>\d+)\b")

#: Метка задачи, чьи пункты следуют состоянию названных ими задач. Предмет
#: сужен меткой намеренно: в обычной задаче `#N` может стоять «см. #52», и
#: отметка по чужому закрытию была бы враньём.
EPIC_LABEL: Final = "epic"


def linked_item(text: str) -> int | None:
    """Задача, которую пункт называет, — если РОВНО одну; иначе ``None``.

    Одна ссылка — пункт и есть эта задача, и её состояние про него. Две и
    больше — пункт говорит о чём-то своём, а задачи упомянуты, и вывести из их
    закрытия ничего нельзя (045: лучше не отметить, чем отметить неверно).
    """
    plain = changerefs.outside_code(text)
    numbers = {int(found["number"]) for found in TASK_REF_RE.finditer(plain)}
    return next(iter(numbers)) if len(numbers) == 1 else None


def followed(body: str, closed: Callable[[int], bool]) -> tuple[str, list[int]]:
    """Отмечает пункты, чьи задачи закрыты; отдаёт новое тело и их номера.

    Чистая: площадка приходит одним `closed`. Так проверка идёт по данным, а
    не по подделке транспорта.
    """
    lines = body.splitlines()
    followed_now: list[int] = []
    for place, line in enumerate(lines):
        open_item = CHECKLIST_RE.match(line)
        if not open_item:
            continue
        number = linked_item(open_item.group("text"))
        if number is None or not closed(number):
            continue
        lines[place] = line.replace("[ ]", "[x]", 1)
        followed_now.append(number)
    return "\n".join(lines), followed_now


def follow(repo: str, token: str, *, dry_run: bool = False) -> int:
    """Пункт эпика следует состоянию названной им задачи.

    ПОЧЕМУ ЭТО ВЫВОДИТСЯ, А НЕ ВЕДЁТСЯ. Пункт-ссылка не имеет своего состояния:
    оно уже есть у задачи, на которую он показывает
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    Второе место, где то же состояние ведётся руками, расходится с первым — и
    расходилось: замер 10.09.2026 — четыре пункта эпика #2 стояли открытыми при
    закрытых задачах, и старшая из них закрыта неделей раньше.

    ПОЧЕМУ ТОЛЬКО ВПЕРЁД. Закрытая задача отмечает пункт; переоткрытая его НЕ
    снимает. Снятие отметки — потеря следа работы, а переоткрытие задачи чаще
    значит новую работу, чем отменённую старую (154: механизм не выбирает за
    человека там, где знать неоткуда).
    """
    state: dict[int, bool] = {}

    def closed(number: int) -> bool:
        # ОТКАЗ ПО ОДНОМУ ПУНКТУ НЕ УНОСИТ ВЕСЬ ЗАХОД. Спрашивается площадка, и
        # спрашивается по разу на каждую названную задачу: один отказ транспорта
        # ронял бы отметку ВСЕХ пунктов эпика, включая уже сосчитанные. Незнание
        # трактуется как «не закрыта» — сторону выбираем ту, где механизм ничего
        # не портит: неотмеченный пункт отметится следующим заходом, а
        # отмеченный по ошибке снимет только человек. Нашёл внешний взгляд
        # на #118.
        if number not in state:
            try:
                issue = ghrest.request("GET", f"repos/{repo}/issues/{number}", token) or {}
            except ghrest.TransportError as exc:
                print(f"::warning::задача #{number} не прочитана: {exc}", file=sys.stderr)
                return False
            state[number] = issue.get("state") == "closed"
        return state[number]

    touched = 0
    epics = ghrest.request(
        "GET", f"repos/{repo}/issues?state=open&labels={EPIC_LABEL}&per_page=100", token
    )
    for epic in epics or []:
        if "pull_request" in epic:
            continue
        body = str(epic.get("body") or "")
        number = int(epic.get("number") or 0)
        try:
            updated, done = followed(body, closed)
        except ghrest.TransportError as exc:
            print(f"  состояние пунктов #{number} не выведено: {report.cut(str(exc))}")
            continue
        if not done:
            continue
        # Основание печатается всегда: отметка выведена, а не объявлена
        # автором, и человеку должно быть видно, из чего.
        said = ", ".join(f"#{one}" for one in done)
        print(f"  #{number}: пунктов вслед за закрытыми задачами {len(done)} — {said}")
        if dry_run:
            continue
        try:
            ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": updated})
        except ghrest.TransportError as exc:
            print(f"  пункты #{number} не записаны: {report.cut(str(exc))}")
            continue
        touched += len(done)
    return touched


def declared_in(body: str) -> tuple[list[int], list[str]]:
    """Что изменение объявило: связанные задачи и закрытые пункты."""
    return (
        sorted({link.number for link in changerefs.links_in(body)}),
        changerefs.closed_items_in(body),
    )


def sweep(repo: str, token: str, limit: int = WINDOW, *, dry_run: bool = False) -> int:
    """Догоняющий обход: отмечает объявленное в недавно слитых изменениях.

    ПОЧЕМУ ОБХОД, А НЕ ТОЛЬКО СОБЫТИЕ. Событие слияния — верный момент, но не
    единственный источник промаха: событие теряется
    ([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md)),
    запись в задачу отказывает, а заход в этот момент уже закончился. Прежде
    такая потеря была молчаливой и окончательной: механизм печатал «пункты не
    отмечены» и забывал о них навсегда.

    ОТМЕТКА ИДЕМПОТЕНТНА, и на этом обход и держится: уже отмеченный пункт
    остаётся отмеченным, а запись не отправляется вовсе, если тело задачи не
    изменилось. Поэтому повторный проход по тем же изменениям ничего не портит
    и почти ничего не стоит.
    """
    touched = 0
    for change in merged_changes(repo, token, limit):
        numbers, wanted = declared_in(str(change.get("body") or ""))
        if not wanted:
            continue
        # Осиротевшее объявление сюда доходит намеренно: разбирает его `mark`,
        # он же и говорит о нём вслух. Прежний пропуск по `not numbers`
        # означал, что на обходе такое объявление исчезало молча — то есть
        # ровно то, ради чего обход и заведён.
        outcome = mark(
            repo, numbers, wanted, token, dry_run=dry_run, origin=int(change.get("number") or 0)
        )
        if outcome.marked:
            touched += len(outcome.marked)
    return touched


#: Объявление осиротело: пункты названы закрытыми, а задачи, где их отмечать,
#: изменение не назвало. Текст один на всех, кто это состояние видит: два
#: понимания одного состояния разошлись бы молча (090).
NO_ADDRESS: Final = "пункты названы закрытыми, а связи с задачей нет — отмечать негде"


def mark(
    repo: str,
    numbers: list[int],
    items: list[str],
    token: str,
    *,
    dry_run: bool = False,
    origin: int | None = None,
) -> Outcome:
    """Отмечает пункты в названных задачах и возвращает исход по каждому.

    Отказ записи не роняет заход: отметка — след работы, а не её условие
    ([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
    Но и молчать о нём нельзя: «отметил ноль из трёх» и «отметил всё» снаружи
    одинаковы.
    """
    if items and not numbers:
        # Пункты объявлены, а связи с задачей нет — отмечать негде, и это
        # состояние, а не отказ: изменение уже сделано. Молчать нельзя,
        # объявленный пункт иначе пропадает бесследно (045). Откуда объявление
        # пришло, называется здесь же: на обходе окна без номера изменения
        # строка не адресуется ни к чему.
        print(f"  {f'#{origin}: ' if origin else ''}{NO_ADDRESS}")
        return Outcome([], [], list(items))
    if dry_run:
        print(f"  (пробный заход) отметил бы пунктов: {len(items)} в задачах {numbers}")
        return Outcome([], [], [])

    left = list(items)
    done: list[str] = []
    unwritten: list[str] = []
    for number in numbers:
        # Список объявляется ДО попытки: отказ на самом чтении задачи оставил
        # бы имя неопределённым, и разбор отказа упал бы раньше, чем сообщил.
        pending: list[str] = []
        try:
            issue = ghrest.request("GET", f"repos/{repo}/issues/{number}", token) or {}
            body = str(issue.get("body") or "")
            updated = body
            already: list[str] = []
            for item in list(left):
                after, found = marked(updated, item)
                if not found:
                    continue
                # Пункт, УЖЕ отмеченный раньше, записи не требует, и отказ
                # записи по соседнему пункту той же задачи его не касается.
                (pending if after != updated else already).append(item)
                updated = after
            for item in already:
                left.remove(item)
                done.append(item)
            if updated != body:
                ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": updated})
            # Из счёта пункт уходит ТОЛЬКО после удавшейся записи: убрать его
            # раньше значило бы объявить обработанным то, что не записалось.
            for item in pending:
                left.remove(item)
                done.append(item)
            if already or pending:
                print(
                    f"  #{number}: пунктов на месте {len(already) + len(pending)} из {len(items)}"
                )
        except ghrest.TransportError as exc:
            print(f"  пункты в #{number} не отмечены: {report.cut(str(exc))}")
            for item in pending:
                if item in left:
                    left.remove(item)
                    unwritten.append(item)

    # Два разных состояния и два разных сообщения: «пункта нигде нет» зовёт
    # проверить формулировку, «нашёлся, но не записался» — повторить заход.
    for item in unwritten:
        print(f"  пункт найден, но запись не удалась: «{item}»")
    for item in left:
        print(f"  пункт не найден ни в одной связанной задаче: «{item}»")
    return Outcome(done, unwritten, left)
