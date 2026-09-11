#!/usr/bin/env python3
"""Форма задачи в трекере: чек-лист вместо прозы и счёт живых единиц.

Здесь два счёта, и оба отвечают на один и тот же вопрос с разных сторон:
**состояние задачи читается счётчиком, а не вычитыванием**.

``028`` — комплексная задача ведёт чек-лист, а не перечисление. От трёх
независимых пунктов проза перестаёт быть описанием и становится работой
читателя: чтобы узнать, что осталось, её приходится прочесть целиком и
сравнить с деревом. Замер 11.09.2026: три живые задачи — реестр находок,
реестр непросмотренного и сравнение конвейеров — вели 33, 11 и 14 пунктов
прозой, и владелец спрашивал об их состоянии словами, а не смотрел на счётчик.

``121`` — закрытие контейнера не доказывает закрытия работы. Признак нарушения
правило называет прямо: «ревизия закрытого находит живое». Ревизии не было ни
разу: у `debt` есть счёт в одну сторону (`looks_done` — все пункты закрыты, а
задача открыта) и не было в обратную.

ОБА СЧЁТА — СЧЁТ, А НЕ ПРИКАЗ. Механизм называет кандидатов и не трогает ни
одной задачи: «пункт остался живым» и «пункт перестал быть нужен» снаружи
одинаковы, и различает их человек
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

ОБА ЧИТАЮТ УЖЕ ПРОЧИТАННОЕ. Списки задач берёт `debt` одним заходом и отдаёт
сюда: второй проход по тому же источнику разошёлся бы с первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Подзадачи спрашивать отдельно тоже не нужно — площадка кладёт их счёт в
`sub_issues_summary` прямо в ответ о задаче.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

import findings
import items

#: Пункт перечисления, который НЕ является галочкой. Три знака списка, потому
#: что все три законны в Markdown и все три встречаются в живых задачах.
BULLET_RE: Final = re.compile(r"^\s{0,3}[-*+]\s+(?!\[[ xX]\])(?P<text>\S.*)$")
#: С какого числа пунктов проза перестаёт быть описанием. Число из буквы
#: правила: «от трёх пунктов — галочки, а не проза».
FROM_ITEMS: Final = 3


@dataclass(frozen=True, slots=True)
class Prose:
    """Задача, которая ведёт пункты прозой: номер, заголовок, сколько их."""

    number: int
    title: str
    items: int


@dataclass(frozen=True, slots=True)
class Live:
    """Закрытая задача, у которой остались живые единицы работы."""

    number: int
    title: str
    unchecked: int
    children: int

    @property
    def said(self) -> str:
        """Чем именно она жива — пунктами, подзадачами или тем и другим."""
        parts = []
        if self.unchecked:
            parts.append(f"пунктов открыто {self.unchecked}")
        if self.children:
            parts.append(f"подзадач открыто {self.children}")
        return " · ".join(parts)


def children_left(issue: dict[str, Any]) -> int:
    """Сколько подзадач закрытой задачи ещё открыто — по счёту площадки."""
    summary = issue.get("sub_issues_summary") or {}
    total, done = int(summary.get("total") or 0), int(summary.get("completed") or 0)
    return max(total - done, 0)


def prose_items(body: str) -> int:
    """Пункты перечисления, которые галочками не являются."""
    return sum(1 for line in body.splitlines() if BULLET_RE.match(line))


def without_a_checklist(issues: list[dict[str, Any]]) -> list[Prose]:
    """Открытые задачи, которые ведут три и более пункта прозой (028).

    ЧТО СЮДА НЕ ПОПАДАЕТ, И ЭТО ГРАНИЦА ИЗ САМОГО ПРАВИЛА. Задача с галочками
    — любыми, открытыми или закрытыми — уже ведёт чек-лист. Эпик с дочерними
    задачами галочек не требует: прогресс считает сам трекер, и дублировать
    его списком значит завести второй счёт того же (022). Задача с одним-двумя
    пунктами тоже не кандидат — там чек-лист дороже предмета.

    ЗАДАЧА, КОТОРУЮ ВЕДЁТ МЕХАНИЗМ, КАНДИДАТОМ НЕ ЯВЛЯЕТСЯ ВОВСЕ. Её тело
    пересобирается заново каждым заходом, и галочка, поставленная рукой,
    исчезнет на следующем; а её состояние и так счётчик — записи появляются и
    уходят сами. Требовать от неё чек-лист значит требовать второй счёт того
    же (022) и работу, которую механизм тут же сотрёт.

    ПОЧЕМУ ЭТО НЕ ТОНКОСТЬ, А НЕВЕРНЫЙ ПРЕДМЕТ. Правило 028 о ФОРМЕ задачи, а
    без этой границы счёт зависел от того, сколько работы механизм успел в неё
    записать: реестр находок #23 утром 11.09.2026 считался кандидатом с
    тридцатью тремя «пунктами прозой», а к вечеру — после разбора — перестал,
    не изменившись ни формой, ни назначением. Нашёл владелец вопросом «на #89
    нет механизма разве?».
    """
    found: list[Prose] = []
    for issue in issues:
        body = str(issue.get("body") or "")
        summary = issue.get("sub_issues_summary") or {}
        if findings.is_kept_by_a_mechanism(body):
            continue
        if items.open_items(body) or items.done_items(body) or int(summary.get("total") or 0):
            continue
        counted = prose_items(body)
        if counted >= FROM_ITEMS:
            found.append(Prose(int(issue["number"]), str(issue.get("title") or ""), counted))
    return sorted(found, key=lambda task: -task.items)


def closed_with_live_units(issues: list[dict[str, Any]]) -> list[Live]:
    """Закрытые задачи, у которых остались незакрытые единицы работы (121).

    ОБРАТНАЯ СТОРОНА `looks_done`, и заведена она отдельно намеренно: та
    отвечает «работа сделана, а контейнер открыт», эта — «контейнер закрыт, а
    работа видна». Причины у них разные и починки тоже: первую закрывают,
    вторую — перечитывают.
    """
    found: list[Live] = []
    for issue in issues:
        body = str(issue.get("body") or "")
        unchecked, children = len(items.open_items(body)), children_left(issue)
        if not unchecked and not children:
            continue
        found.append(Live(int(issue["number"]), str(issue.get("title") or ""), unchecked, children))
    return sorted(found, key=lambda task: -task.number)
