"""Раздел «чего ещё нет» — утверждение о действительности, а не оборот речи.

Проза целиком непроверяема, и гейт её трогать не должен. Но у неё есть
подкласс, который рассыхается молча и выглядит при этом осознанным решением, —
СЧЁТ. Число в строке «ответа по N записям каталога» стареет каждой пачкой
разбора, и заметить это нечем: раздел никто не пересчитывает.

Правила каталога: 175 (утверждение «предмета нет», опровергаемое одной
командой, обязано быть гейтом), 005 и 127 (число в прозе без маркера и сборки
рассыхается).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARTER = ROOT / "AGENTS.md"
HEADING = "## 🕳 Чего в проекте ещё нет"


def gaps_rows() -> list[str]:
    """Строки таблицы пробелов — без шапки и разделителя."""
    text = CHARTER.read_text(encoding="utf-8")
    start = text.index(HEADING)
    section = text[start:].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return rows[2:]


def test_the_section_has_a_subject() -> None:
    """Таблица пробелов не пуста: иначе гейт зелен на отсутствии предмета (075)."""
    assert gaps_rows(), f"в {CHARTER.name} не нашлось таблицы пробелов — предмет проверки не найден"


def test_no_row_carries_a_count() -> None:
    """Ни один пробел не называется числом: счёт двигает механизм, а не рука.

    Число живёт там, где считается, — шаг `debt` печатает его на каждом
    изменении, `facts.json` в ветке `badges` публикует наружу. Вписанное сюда,
    оно расходится с деревом на первой же разобранной записи и продолжает
    выглядеть решением.
    """
    with_counts = [row for row in gaps_rows() if re.search(r"\d", row.split("|")[1])]
    assert not with_counts, f"число вписано в пробел прозой: {with_counts}"
