"""Как механизмы говорят с человеком: обрезка вывода — одна на всех.

Длинный вывод обрезают четверо: шаг открытия, гейт журнала, транспорт и сборка
тела уплотнения. Обрезали молча — `[:300]`, — и это ровно то, что запрещает
[016](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/016-no-silent-truncation.md):
урезанный результат выглядит как полный. Читатель ищет причину в первых
трёхстах знаках, когда она в четырёхсот первом.

Копий было четыре, и разошлись бы они молча — как уже расходились состав меток,
связь с задачей и роды журнала. Здесь она одна.
"""

from __future__ import annotations

from typing import Final

LIMIT: Final = 300


def cut(text: str, limit: int = LIMIT) -> str:
    """Обрезает длинный вывод, сказав, насколько он обрезан."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (обрезано, всего {len(text)} знаков)"
