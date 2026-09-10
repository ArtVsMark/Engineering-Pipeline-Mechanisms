#!/usr/bin/env python3
"""Отметка пунктов задачи: один разбор на всех, кто её ставит.

Площадка умеет только полное закрытие: `Closes #N` закрывает задачу целиком, и
задача из нескольких этапов закрывается преждевременно вместе с несделанными.
`Refs #N` не отмечает ничего. Поэтому пункт называется строкой в теле работы, и
отметка едет ВМЕСТЕ с работой, а не отдельным жестом, который забудут
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-a-rule-without-a-mechanism-is-a-wish.md)).

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
from dataclasses import dataclass
from typing import Any, Final

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


#: Сколько последних слитых изменений просматривает догоняющий обход. Окно
#: закрывает ПРОПУЩЕННОЕ событие и неудавшуюся запись, а не заменяет историю:
#: заход идёт по событию слияния, и обходить всё прошлое ему незачем.
WINDOW: Final = 20


def merged_changes(repo: str, token: str, limit: int = WINDOW) -> list[dict[str, Any]]:
    """Последние слитые изменения — только они предмет отметки."""
    items = ghrest.request("GET", f"repos/{repo}/pulls?state=closed&per_page={limit}", token) or []
    return [item for item in items if isinstance(item, dict) and item.get("merged_at")]


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
    ([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-a-manual-button-for-every-automation.md)),
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
        if not wanted or not numbers:
            continue
        outcome = mark(repo, numbers, wanted, token, dry_run=dry_run)
        if outcome.marked:
            touched += len(outcome.marked)
    return touched


def mark(
    repo: str,
    numbers: list[int],
    items: list[str],
    token: str,
    *,
    dry_run: bool = False,
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
        # объявленный пункт иначе пропадает бесследно (045).
        print("  пункты названы закрытыми, а связи с задачей нет — отмечать негде")
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
