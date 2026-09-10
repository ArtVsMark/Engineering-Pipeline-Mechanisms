#!/usr/bin/env python3
"""Мерило общих механизмов: сколько ПРАВИЛ семьи они закрывают.

ПОЧЕМУ ЭТО ОТДЕЛЬНАЯ ОСЬ. Порядок переноса в эпике выведен из размера кода и
расхождения копий — это цена выноса. Но у выноса есть и вторая сторона: сколько
машинного соблюдения он приносит с собой. Оси разные и дают разный порядок:
транспорт по строкам первый, а по числу закрываемых правил — шестой. Ни одна из
них не отменяет другую, но вторая до сих пор была не видна.

ВТОРОГО СБОРЩИКА НЕ ЗАВОДИТСЯ. Данные уже собраны каталогом: `export/where.json`
несёт по каждому потребителю ключ `holds` — правило → вид механизма и его адрес.
Читать `.rules/bindings.json` пяти проектов заново не нужно и не следует: два
сборщика одних данных разошлись бы молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Здесь только разрез над готовым.

СЧИТАЮТСЯ МЕХАНИЗМЫ, А НЕ ДОКУМЕНТЫ, И ЭТО НЕ ПРИДИРКА. Без фильтра по виду
топ забивают `CLAUDE.md` (80 правил у пятерых), `README.md` (25),
`bindings.json` (20). Формально они механизмы в ответах каталога
(`mechanism: document`), фактически — текст, который выносить некуда: сводка со
всеми видами показывает не механизмы, а объём документации.

СОПОСТАВЛЕНИЕ ИДЁТ ПО ИМЕНИ ФАЙЛА, И ОДНОИМЁННОСТЬ — НЕ ТОЖДЕСТВО. Копии лежат
по разным путям намеренно, но замер расхождения говорит прямо: ни одна пара
копий не совпала. Число показывает, ГДЕ смотреть, а не что делать
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-numbers-in-prose-need-a-marker.md)).

ЧИСЛО НЕ РЕШАЕТ ЗА ЧЕЛОВЕКА. Механизм, держащий одно правило, бывает
необходим; держащий восемнадцать — оставаться домашним, если правила про
предмет одного проекта.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

#: Адрес механизма внутри ответа: путь к файлу с расширением, которое исполняют.
ADDRESS_RE: Final = re.compile(r"[\w./-]+\.(?:py|yml|yaml)\b")
#: Виды, которые считаются механизмом. Документ — не механизм: его не вынести.
KINDS: Final = frozenset({"gate", "pipeline", "code"})
#: Со скольких проектов механизм считается общим.
SHARED_FROM: Final = 2
#: Версия сводки каталога, под которую написан этот разрез. Подъём — повод
#: перечитать разрез, а не подвинуть число
#: ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).
READS_SCHEMA: Final = "1.2"


class NotRun(RuntimeError):
    """Разрез не отработал: третий исход, а не «общих механизмов нет»."""


@dataclass
class Mechanism:
    """Один механизм по имени файла: у кого живёт и сколько правил держит."""

    name: str
    projects: set[str] = field(default_factory=set)
    rules: int = 0

    @property
    def shared(self) -> bool:
        """Живёт ли механизм у двух и более проектов."""
        return len(self.projects) >= SHARED_FROM


def load(path: Path) -> dict[str, Any]:
    """Читает сводку каталога, отвергая любой дефект входа."""
    if not path.is_file():
        raise NotRun(f"сводки семьи нет: {path} — считать нечего (075)")
    try:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc
    if not document.get("consumers"):
        raise NotRun(f"{path}: в сводке нет ни одного потребителя — предмет не найден (075)")
    return document


def schema_of(summary: dict[str, Any]) -> str:
    """Версия формы сводки — как её объявил каталог."""
    return str(summary.get("schema") or "")


def mechanisms(summary: dict[str, Any]) -> dict[str, Mechanism]:
    """Механизмы семьи по имени файла: у кого живут и сколько правил держат."""
    found: dict[str, Mechanism] = defaultdict(lambda: Mechanism(""))
    for consumer in summary.get("consumers") or []:
        repo = str(consumer.get("repo") or "")
        for answer in (consumer.get("holds") or {}).values():
            if not isinstance(answer, dict) or answer.get("mechanism") not in KINDS:
                continue
            address = ADDRESS_RE.search(str(answer.get("where") or ""))
            if address is None:
                continue
            name = address.group(0).rsplit("/", 1)[-1]
            item = found[name]
            item.name = name
            item.projects.add(repo)
            item.rules += 1
    return dict(found)


def held_by_machine(summary: dict[str, Any]) -> int:
    """Сколько ответов семьи держатся машиной — знаменатель доли."""
    return sum(
        1
        for consumer in summary.get("consumers") or []
        for answer in (consumer.get("holds") or {}).values()
        if isinstance(answer, dict) and answer.get("mechanism") in KINDS
    )


def picture(summary: dict[str, Any]) -> dict[str, Any]:
    """Разрез целиком: числа, которые публикуются фактом.

    Доля общих механизмов — прямое мерило «второго исхода» эпика: если общий
    модуль окупается, она растёт; если нет — стоит на месте, и это видно
    числом, а не ощущением.
    """
    found = mechanisms(summary)
    shared = {name: item for name, item in found.items() if item.shared}
    machine = held_by_machine(summary)
    closed = sum(item.rules for item in shared.values())
    return {
        "schema_read": schema_of(summary),
        "consumers": len(summary.get("consumers") or []),
        "mechanisms": len(found),
        "shared": len(shared),
        "held_by_machine": machine,
        "closed_by_shared": closed,
        "share": round(closed / machine, 3) if machine else 0.0,
        "top": [
            {"name": item.name, "projects": len(item.projects), "rules": item.rules}
            for item in sorted(shared.values(), key=lambda one: (-one.rules, one.name))[:10]
        ],
    }
