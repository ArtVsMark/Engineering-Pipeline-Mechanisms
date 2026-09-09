"""Записи решений держат один формат — механизмом, а не вниманием автора.

Решения читают по порядку: номер, читатель, статус, задача. Стоит одной записи
выпасть из формата — и читателю приходится искать глазами то, что в остальных
стоит на месте. Замер: запись 006 ушла с другим заголовком и без ссылки на
задачу, и нашёл это внешний взгляд, а не сборка.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import ROOT

DECISIONS = ROOT / "docs" / "decisions"
TITLE_RE = re.compile(r"^# (\d{3})\. \S")
STATUS_RE = re.compile(
    r"^\*\*Статус:\*\* .+ · \*\*Дата:\*\* \d{4}-\d{2}-\d{2} · \*\*Задача:\*\* \[#\d+\]"
)
READER_RE = re.compile(r"^> \*\*Читатель:\*\* \S")


def records() -> list[Path]:
    """Записи решений, кроме служебных файлов каталога."""
    found = sorted(p for p in DECISIONS.glob("*.md") if p.name != "README.md")
    assert found, "записей решений нет — предмет проверки не найден (075)"
    return found


@pytest.mark.parametrize("path", records(), ids=lambda p: p.name)
def test_record_has_a_numbered_title(path: Path) -> None:
    """Заголовок начинается номером: по нему запись находят и на неё ссылаются."""
    first = path.read_text(encoding="utf-8").splitlines()[0]
    match = TITLE_RE.match(first)
    assert match, f"{path.name}: заголовок не вида «# NNN. Название» — {first[:60]}"
    assert path.name.startswith(match.group(1)), (
        f"{path.name}: номер в заголовке не тот, что в имени"
    )


@pytest.mark.parametrize("path", records(), ids=lambda p: p.name)
def test_record_names_its_reader(path: Path) -> None:
    """У записи назван читатель: документы разделены по нему (021)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert any(READER_RE.match(line) for line in lines[:6]), f"{path.name}: читатель не назван"


@pytest.mark.parametrize("path", records(), ids=lambda p: p.name)
def test_record_links_its_task(path: Path) -> None:
    """Статус, дата и задача стоят одной строкой и в одном виде.

    Ссылка на задачу здесь не украшение: решение принимается по задаче, и без
    адреса его основание теряется вместе с памятью того, кто принимал.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    assert any(STATUS_RE.match(line) for line in lines[:8]), (
        f"{path.name}: нет строки «**Статус:** … · **Дата:** ГГГГ-ММ-ДД · **Задача:** [#N](…)»"
    )


#: Раздел, без которого запись — не решение, а ход работы (161).
REJECTED_RE = re.compile(r"^## Отвергнут(?:ые|ый) (?:варианты|вариант|альтернативы)", re.M)


@pytest.mark.parametrize("path", records(), ids=lambda p: p.name)
def test_record_names_the_rejected_alternative(path: Path) -> None:
    """Запись называет отвергнутую альтернативу (161).

    Без неё это не поворот, а ход работы, и место ему в журнале: читатель не
    может отличить решение, у которого был выбор, от записи о сделанном.
    """
    text = path.read_text(encoding="utf-8")
    assert REJECTED_RE.search(text), (
        f"{path.name}: нет раздела об отвергнутом варианте — это ход работы, а не решение"
    )
