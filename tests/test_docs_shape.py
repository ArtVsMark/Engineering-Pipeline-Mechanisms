"""Форма документов проверяется там, где её читает не только человек.

Документы этого проекта читает окно — целиком, текстом, без интерфейса
площадки. Всё, что в интерфейсе разворачивается кликом, для такого читателя
остаётся заголовком без содержимого, и пропажа выглядит как пустой раздел, а не
как скрытый (008).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = sorted(
    [
        *ROOT.glob("*.md"),
        *(ROOT / "docs").rglob("*.md"),
        *(ROOT / ".github").rglob("*.md"),
        *(ROOT / "changelog.d").rglob("*.md"),
    ]
)

#: Сворачиваемый блок: содержимое видит только тот, кто кликнул.
COLLAPSED_RE = re.compile(r"<details\b|<summary\b", re.I)


def test_there_are_documents_to_check() -> None:
    """Предмет проверки найден: иначе гейт зелен на пустом списке (075)."""
    assert DOCS, "в дереве не нашлось ни одного документа — проверять нечего"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.as_posix())
def test_no_collapsed_blocks(path: Path) -> None:
    """Сворачиваемых блоков в документах нет: раскрывайте или не пишите (008)."""
    text = path.read_text(encoding="utf-8")
    hits = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if COLLAPSED_RE.search(line)
    ]
    assert not hits, f"{path.as_posix()}: сворачиваемый блок читается как обрубок: {hits}"
