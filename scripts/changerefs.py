"""Ссылки изменения наружу: задача и снятая находка — одно чтение на всех.

Читали её двое и по-разному. Шаг открытия — строгой строкой целиком
(``^Refs #12$``), гейт разметки — свободным поиском по заголовку и телу. Строка
`Refs #2, #29`, написанная в коммите, для первого не существовала вовсе: он
**молча** открыл изменение без раздела связи — ровно то изменение, которое
гейт тут же отверг. Один вход, два понимания: тот же дрейф, что был на составе
меток, только на другом поле.

Цена замерена: PR #32, красный `pr-meta` на здоровом коммите, где связь с
задачей была написана и человеком читалась.

СПИСОК ПОСЛЕ ОДНОГО ГЛАГОЛА РАЗБИРАЕТСЯ, НО В ТЕЛО ИДЁТ ПО СТРОКЕ НА ЗАДАЧУ.
По документации площадки ключевое слово действует на **каждый** номер
отдельно: `Closes #12, #13` закрывает только первую задачу. Замером это здесь
не проверялось и помечено гипотезой
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-by-measuring.md)),
но собирать тело по строке на задачу дешевле, чем выяснять это отказом при
слиянии.

ЗДЕСЬ ЖЕ ЧИТАЕТСЯ СНЯТИЕ НАХОДКИ. Строка `Разобрано: <отпечаток>` снимает
запись из живой задачи-адресата, и ищется она в теле СЛИТОГО изменения. Тело
собирает шаг открытия из коммитов — значит перенести строку туда обязан он,
иначе «снятие едет вместе с работой» держится тем, что кто-то вспомнит про
описание. Разбор общий по той же причине, что и у связи с задачей: два чтения
одной строки расходятся молча.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Глаголы читаются списком разрешённого (068). Новый глагол добавляется сюда
#: осознанно: `resolves` площадка понимает, а этот проект — нет, и добавить его
#: значит поменять поведение обоих механизмов сразу.
VERBS: Final = ("closes", "fixes", "refs", "part of")
CANON: Final = {"closes": "Closes", "fixes": "Fixes", "refs": "Refs", "part of": "Part of"}
CLOSING: Final = frozenset({"Closes", "Fixes"})

LINK_RE: Final = re.compile(
    r"\b(?P<verb>" + "|".join(VERBS) + r")\s+(?P<tasks>#\d+(?:\s*,\s*#?\d+)*)",
    re.IGNORECASE,
)
NUMBER_RE: Final = re.compile(r"#?(\d+)")
#: Кодовые вставки из разбора вырезаются: площадка ключевые слова внутри них
#: тоже не читает. Замер, стоивший ложной связи: описание правки цитировало
#: старую регулярку `^Refs #12$`, и механизм записал изменению задачу #12,
#: которой оно не касается (PR #32). Пример в тексте — не ссылка.
INLINE_RE: Final = re.compile(r"`[^`\n]*`")
#: Забор блока узнаётся по началу строки, как его понимает и разметка.
FENCE_RE: Final = re.compile(r"^\s*```")
#: Отпечаток находки — семь шестнадцатеричных знаков, как короткий хэш.
RESOLVED_RE: Final = re.compile(r"^\s*Разобрано:\s*([0-9a-f]{7})\b", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Link:
    """Одна связь: глагол и номер задачи."""

    verb: str
    number: int

    def __str__(self) -> str:
        """Строка ровно того вида, который читает площадка."""
        return f"{self.verb} #{self.number}"

    @property
    def closes(self) -> bool:
        """Закроет ли эта связь задачу при слиянии."""
        return self.verb in CLOSING


def outside_code(text: str) -> str:
    """Текст без кодовых вставок: пример в них ссылкой не считается.

    Разбор построчный и НЕ ЖАДНЫЙ через границы, потому что шаг открытия
    склеивает тела всех коммитов ветки в один текст. Одним образцом это
    ловится дважды и оба раза молча:

    * одиночная кавычка без пары тянулась до следующей — через абзацы и через
      границу коммита, унося строку связи из соседнего;
    * незакрытый забор смыкался не со своим концом, а с ОТКРЫВАЮЩИМ забором
      настоящего блока из более позднего коммита, съедая всё между ними.

    Оба замера сделаны на подделанном входе, оба показали пропажу `Refs #N`.
    Цена молчания — ветка с честно названной задачей, которая не открывается:
    связи не нашлось, шаг отказал.

    Поэтому: непарное число заборов означает, что блоков в тексте нет вовсе —
    заборы тогда просто разметка, и вырезать по ним нечего. Опечатка не
    уносит данные с собой.
    """
    lines = text.splitlines()
    fences = {index for index, line in enumerate(lines) if FENCE_RE.match(line)}
    # Незакрытый забор не открывает блок: половина пары — это не пара.
    paired = len(fences) % 2 == 0

    kept: list[str] = []
    inside = False
    for index, line in enumerate(lines):
        if paired and index in fences:
            inside = not inside
            kept.append(" ")
            continue
        kept.append(" " if inside else INLINE_RE.sub(" ", line))
    return "\n".join(kept)


def links_in(text: str) -> list[Link]:
    """Связи с задачами в порядке появления, без повторов."""
    found: list[Link] = []
    seen: set[tuple[str, int]] = set()
    for match in LINK_RE.finditer(outside_code(text)):
        verb = CANON[match["verb"].lower()]
        for number in NUMBER_RE.findall(match["tasks"]):
            key = (verb, int(number))
            if key in seen:
                continue
            seen.add(key)
            found.append(Link(verb, int(number)))
    return found


def has_link(text: str) -> bool:
    """Названа ли в тексте хотя бы одна задача."""
    return bool(links_in(text))


def resolved_in(text: str) -> list[str]:
    """Отпечатки находок, названных разобранными, в порядке появления."""
    found: list[str] = []
    for mark in RESOLVED_RE.findall(outside_code(text)):
        lowered = mark.lower()
        if lowered not in found:
            found.append(lowered)
    return found
