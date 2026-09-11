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


#: Строка таблицы без номера шага: `| — | выпуск | release.yml | … |`. Такая в
#: счёт заголовка не входит, и читатель, считающий строки глазами, получит на
#: единицу больше.
UNNUMBERED_ROW_RE = re.compile(r"^\|\s*[—-]\s*\|")


def test_an_unnumbered_row_is_named_under_the_heading() -> None:
    """Строка без номера названа прозой, иначе счёт заголовка спорит с глазами.

    Заголовок считает НОМЕРОВАННЫЕ строки; читатель считает все. Расхождение
    на единицу выглядит устаревшим числом, и внешний взгляд прочёл его именно
    так на #199 — «четырнадцать не совпадает с пятнадцатью файлами дерева».
    Разницу называет проза под заголовком, а не догадка (046).
    """
    text = (ROOT / "docs" / "pipeline.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    place = next(n for n, line in enumerate(lines) if line.startswith("## Скелет:"))
    table = lines[place:]
    unnumbered = [line for line in table if UNNUMBERED_ROW_RE.match(line)]
    if not unnumbered:
        return
    said = "\n".join(lines[place : place + 8])
    assert "без номера" in said, (
        f"в таблице {len(unnumbered)} строк без номера, а проза под заголовком о них молчит"
    )


#: Сколько первых строк документа читается в поисках читателя. Не весь файл:
#: объявление, стоящее в середине, читателю не поможет — он до него не дойдёт.
READER_HEAD = 12
#: Строка объявления. Форма взята у соседей по семье, где правило уже держится
#: машиной: расходящиеся формы стоили бы переноса гейта (162, 090).
READER_MARK = "Читатель:"
#: Документы, у которых читателя нет по построению: их читает механизм, а не
#: человек. Список закрытый и каждый назван с причиной — иначе он станет местом,
#: куда сваливают всё, что лень объявить (154).
WITHOUT_READER = {
    "CHANGELOG.md": "производное: собирается из фрагментов сборкой",
}


@pytest.mark.parametrize(
    "path",
    sorted(p for p in DOCS if "changelog.d" not in p.parts and p.name not in WITHOUT_READER),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_every_document_declares_its_reader(path: Path) -> None:
    """У документа объявлен читатель, и объявлен в его начале.

    Документ без названного читателя пишется «вообще» и потому не годится
    никому: свод агента и витрина посетителя отвечают на разные вопросы, и
    смешавшись, перестают отвечать на оба.

    Правило держалось вниманием: все тринадцать документов проекта читателя уже
    называли, но ничто не мешало четырнадцатому его не назвать. Гейт перенесён
    от соседей — у троих из пяти он уже стоит машиной (162).
    """
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:READER_HEAD])
    assert READER_MARK in head, (
        f"{path.relative_to(ROOT)}: читатель не объявлен в первых {READER_HEAD} строках"
    )


def test_the_reader_gate_found_its_subject() -> None:
    """Гейт читателя проверяет не пустоту: документы в дереве есть (075)."""
    subject = [p for p in DOCS if "changelog.d" not in p.parts and p.name not in WITHOUT_READER]
    assert len(subject) > 5, "предмет проверки не найден — гейт проходит вхолостую"
