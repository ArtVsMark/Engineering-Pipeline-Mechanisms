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


#: Числительные, которыми в договоре записан размер скелета. Прозой, а не
#: цифрой: заголовок читает человек. Отсюда и гейт — число прописью устаревает
#: ровно так же молча, как цифрой (005).
SPELLED = {
    10: "десяти",
    11: "одиннадцати",
    12: "двенадцати",
    13: "тринадцати",
    14: "четырнадцати",
    15: "пятнадцати",
    16: "шестнадцати",
    17: "семнадцати",
    18: "восемнадцати",
}
SPELLED_STEPS = {
    12: "двенадцать",
    13: "тринадцать",
    14: "четырнадцать",
    15: "пятнадцать",
    16: "шестнадцать",
    17: "семнадцать",
    18: "восемнадцать",
    19: "девятнадцать",
    20: "двадцать",
}
STEP_ROW_RE = re.compile(r"^\|\s*(?P<step>\d+)[a-zа-я]?\s*\|")
STEP_FILE_RE = re.compile(r"`(?P<file>[\w.-]+\.yml)`")


def test_the_skeleton_heading_matches_its_own_table() -> None:
    """Заголовок договора называет столько шагов, сколько в таблице под ним.

    Замер 10.09.2026: заголовок говорил «четырнадцать шагов в десяти файлах»,
    когда в таблице было шестнадцать в тринадцати. Число, вписанное в прозу
    руками, устаревает молча (005) — поэтому его сверяет гейт, а не читатель.
    """
    text = (ROOT / "docs" / "pipeline.md").read_text(encoding="utf-8")
    steps: set[int] = set()
    files: set[str] = set()
    for line in text.splitlines():
        row = STEP_ROW_RE.match(line)
        if not row:
            continue
        steps.add(int(row.group("step")))
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        files.update(found.group("file") for found in STEP_FILE_RE.finditer(cells[2]))
    assert steps and files, "таблица шагов не разобралась — гейту не с чем сверять"
    heading = next(line for line in text.splitlines() if line.startswith("## Скелет:"))
    assert SPELLED_STEPS[len(steps)] in heading.lower(), f"{heading}: шагов в таблице {len(steps)}"
    assert SPELLED[len(files)] in heading.lower(), f"{heading}: файлов в таблице {len(files)}"
