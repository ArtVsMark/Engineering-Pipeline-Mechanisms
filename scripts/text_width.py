#!/usr/bin/env python3
"""Ширина надписи в SVG — суммой ширин знаков по таблице шрифта, одна на механизмы.

ПЕРЕЕХАЛО ИЗ КАТАЛОГА (#1563, этап 3 ArtVsMark/Engineering-Incidents-Playbook#930):
значки и сверку семьи держат механизмы. Поведение — то же, что у
`scripts/text_width.py` каталога на `353bf10`; имена переведены на латиницу,
как в остальном дереве.

ОДНА РЕАЛИЗАЦИЯ ШИРИНЫ
([214](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/214-one-territory-one-parse.md)).
Ширину надписи у каталога прежде считали два генератора картинок, каждый своей
формулой «длина × коэффициент», и обе ошибались по-своему. Следующий генератор
берёт эту функцию, а не заводит третий коэффициент.

ПОЧЕМУ ТАБЛИЦА, А НЕ КОЭФФИЦИЕНТ (каталог #792). У Verdana 11px `l`, `i` и
пробел занимают 3–4 px, а `m` и `w` — 9–11: одна ширина на знак раздувала
значок на 20–25 %. Таблица `fonts/text_widths.json` снята с файлов шрифта
(hmtx) сборщиком `build_text_widths.py`, а не подобрана глазом.

Знак вне таблицы не сжимается: ему дана ширина самого широкого знака того же
начертания, и надпись скорее просторнее, чем обрезана (045).

ГРАНИЦА. Считается ширина начертания, названного в таблице. Какой шрифт
нарисует зритель, решает его площадка: если в списке `font-family` первым не
найдётся табличный, надпись выйдет другой ширины, и это отсюда не видно.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any, Final

#: Таблица ширин знаков: собирается `build_text_widths.py`, руками не правится.
TABLE: Final = Path(__file__).resolve().parent / "fonts" / "text_widths.json"


@cache
def _fonts() -> dict[str, Any]:
    fonts: dict[str, Any] = json.loads(TABLE.read_text(encoding="utf-8"))["fonts"]
    return fonts


def _face(font: str, weight: int) -> tuple[dict[str, int], int]:
    """Таблица ближайшего начертания НЕ ЛЕГЧЕ запрошенного и единицы на кегль.

    Тяжелее — значит шире: ошибка в эту сторону даёт воздух, а не обрезку.
    """
    data = _fonts()[font]
    weights = sorted(int(one) for one in data["weights"])
    fitting = next((one for one in weights if one >= weight), weights[-1])
    return data["weights"][str(fitting)], int(data["units"])


def width(
    text: str,
    font: str = "Verdana",
    size: float = 11.0,
    weight: int = 400,
    spacing: float = 0.0,
) -> float:
    """Ширина надписи в пикселях: сумма ширин знаков плюс разрядка между ними."""
    table, units = _face(font, weight)
    widest = max(table.values())
    total = sum(table.get(sign, widest) for sign in text)
    return total * size / units + spacing * len(text)
