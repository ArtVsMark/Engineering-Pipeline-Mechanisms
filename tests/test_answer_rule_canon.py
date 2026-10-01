"""Правило снятия находки «об ответе» пересказывается только каноном (#978).

Канон один — докстрока `scripts/review_findings.py::closable`. За 30.09.2026 правило
пересказывалось заново в пяти заходах подряд (#965, #967, #969, #973, #976): шапка
реестра, `subject_of`, докстроки тестов. Каждый пересказ находил поздний взгляд, а
не машина, и один раз его пропустил и поиск окна — `grep -i` в локали C кириллицу
не сворачивает.

ПРАВИЛО СТРОГОЕ, А НЕ РАЗБОР СЛОВ (навык `build-a-gate`, шаг 3а). Абзац текста,
где стоит «об ответе» (без учёта регистра) и глагол снятия, обязан назвать канон
`closable`. Что абзац говорит о снятии — не судится: это суждение о смысле
(057). Судится, что читатель пересказа получает адрес канона.

ЕДИНИЦА — АБЗАЦ, А НЕ ОКНО СТРОК. В `.py` абзац — часть докстроки, комментария или
подряд идущих строковых литералов одного выражения между пустыми строками;
литерал `""` — граница абзаца, как в шапке реестра. В `.md` — абзац между пустыми
строками. Окно в ±2 строки было шире предмета: из двенадцати названных им мест
ни одно не было пересказом, а шапку реестра, где канон назван четырьмя строками
ниже, оно объявляло нарушением (замер 30.09.2026).

ЗАМЕР ПЕРЕД ПОСТРОЙКОЙ 30.09.2026: абзацев под предикатом восемь. Один — шапка
реестра, которую разбор принимал за нарушение из-за f-строки (в Python 3.12 она
режется на токены, и имя внутри не видно) — починен разбор. Семь — история,
пометка рода и докстроки тестов `closable` — дополнены адресом канона.

ГРАНИЦЫ НАЗВАНЫ (195). Не проверяются: тело самой `closable` (это канон);
журнал (`CHANGELOG.md`, `changelog.d/`) — выпущенное не правится; сам этот файл —
его таблица держит пересказы без канона намеренно; `.github/` — прозы о снятии
там нет, задание ревьюеру о пометке ведёт карта взгляда в `scripts/review_map.py`,
которую обход видит; `.rules/` — данные ответов и родов, а не текст о правиле
снятия. Замер 30.09.2026: «об ответе» в `.github/` и `.rules/` не встречается.

ГРАНИЦА АБЗАЦА — ПУСТАЯ СТРОКА И КОНЕЦ ОПЕРАТОРА (взгляд на #983). Два блока
комментариев через пустую строку и докстрока с комментарием под ней — разные
абзацы: иначе канон, названный в одном, прикрыл бы пересказ в соседнем.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, load_script, walk_deep

#: Где живут тексты, которые читают окно и ревьюер, и в каких расширениях.
#: Пара названа явно: обход пустой пары — обрыв проверки, а не «нарушений нет»
#: (075). Замер 30.09.2026: `scripts/` и `tests/` — только `.py`, `docs/` — только
#: `.md`, `.claude/` — оба.
DIRS: Final = (
    ("scripts", "*.py"),
    ("tests", "*.py"),
    (".claude", "*.py"),
    (".claude", "*.md"),
    ("docs", "*.md"),
)
#: Документы свода в корне.
FILES: Final = ("AGENTS.md", "CLAUDE.md", "README.md")
#: Предмет правила — находка об ответе; сравнение после `casefold`.
SUBJECT: Final = "об ответе"
#: Глаголы снятия: снимает, снятие, отвергается, принимается и их формы.
REMOVAL: Final = re.compile(r"\b(сним\w*|снят\w*|отверг\w*|принима\w*)")
#: Канон и его адрес — у самой функции, а не буквами: переименование увело бы
#: гейт в пустоту молча (209, взгляд на #983).
REGISTRY: Final = load_script("review_findings.py")
CANONICAL: Final = REGISTRY.closable
CANON: Final = CANONICAL.__name__
CANON_AT: Final = f"{Path(CANONICAL.__code__.co_filename).relative_to(ROOT)}::{CANON}"
#: Модуль канона — для формы через точку (`review_findings.closable`).
CANON_MODULE: Final = Path(CANONICAL.__code__.co_filename).stem
#: Функция, которая ПЕЧАТАЕТ адрес канона. Абзац, где её зовут, канон называет:
#: в выводе стоит адрес, а в исходнике — вызов (взгляд на #988, `ebd3754`).
CANON_CALL: Final = f"{REGISTRY.canon_at.__name__}("
#: Этот файл: таблица ниже держит пересказы без канона — это красные случаи.
SELF: Final = Path(__file__).resolve()
#: Пустой строковый литерал — граница абзаца в списке строк.
EMPTY_LITERAL: Final = re.compile(r"[rbuRBU]*(\"\"|'')")
#: Токены, которые абзаца не прерывают: перенос внутри выражения и отступы.
#: Пустая строка (`NL` на пустой строке) и конец оператора (`NEWLINE`) — прерывают.
SPACING: Final = (tokenize.NL, tokenize.INDENT, tokenize.DEDENT)


def retold(text: str) -> bool:
    """Абзац говорит о снятии находки об ответе и не называет канона."""
    folded = " ".join(text.split()).casefold()
    named = CANON in folded or CANON_CALL in folded
    return SUBJECT in folded and bool(REMOVAL.search(folded)) and not named


def py_paragraphs(source: str) -> list[tuple[int, str]]:
    """Абзацы строк и комментариев модуля с номером первой строки; тело канона пропущено."""
    lines = source.splitlines(keepends=True)
    skip: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == CANON:
            skip.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    found: list[tuple[int, str]] = []
    run: list[str] = []
    start = 0

    def flush() -> None:
        nonlocal run
        if run:
            found.extend((start, part) for part in re.split(r"\n\s*\n", "\n".join(run)))
        run = []

    def take(line: int, text: str) -> None:
        nonlocal start
        if not run:
            start = line
        run.append(text)

    fstring: tuple[int, int] | None = None
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        line = tok.start[0]
        if line in skip:
            flush()
            continue
        # F-строка в 3.12 режется на части, и имя внутри `{}` — отдельный токен:
        # абзац берёт её исходник целиком, от начала до конца.
        if tok.type == getattr(tokenize, "FSTRING_START", None):
            fstring = tok.start
            continue
        if fstring is not None:
            if tok.type == getattr(tokenize, "FSTRING_END", None):
                row, end_row = fstring[0], tok.end[0]
                piece = "".join(lines[row - 1 : end_row])
                take(row, piece)
                fstring = None
            continue
        if tok.type == tokenize.STRING:
            if EMPTY_LITERAL.fullmatch(tok.string):
                flush()
            else:
                take(line, tok.string)
        elif tok.type == tokenize.COMMENT:
            take(line, tok.string.lstrip("#:").strip())
        elif tok.type == tokenize.NEWLINE or (tok.type == tokenize.NL and not tok.line.strip()):
            flush()
        elif tok.type in SPACING or tok.string == ",":
            continue
        else:
            flush()
    flush()
    return found


def md_paragraphs(text: str) -> list[tuple[int, str]]:
    """Абзацы Markdown с номером первой строки."""
    found: list[tuple[int, str]] = []
    line = 1
    for part in re.split(r"\n[ \t]*\n", text):
        found.append((line, part))
        line += part.count("\n") + 2
    return found


def texts() -> list[Path]:
    """Файлы под правилом: модули и документы, кроме этого."""
    found = [path for root, pattern in DIRS for path in walk_deep(ROOT / root, pattern)]
    found += [ROOT / name for name in FILES]
    return [p for p in found if "__pycache__" not in p.parts and p.resolve() != SELF]


def retellings(path: Path) -> list[str]:
    """Пересказы правила без канона в одном файле: «файл:строка».

    Пустой список у файла, который не удалось прочитать, был бы зелёным впустую:
    ошибка разбора роняет проверку, а не прячет файл (075).
    """
    source = path.read_text(encoding="utf-8")
    paragraphs = py_paragraphs(source) if path.suffix == ".py" else md_paragraphs(source)
    rel = path.relative_to(ROOT)
    return [f"{rel}:{line}" for line, text in paragraphs if retold(text)]


@pytest.mark.parametrize(
    ("text", "is_retold"),
    [
        ("Находку об ответе снимает только правка ответа.", True),
        ("Находку ОБ ОТВЕТЕ снимает только правка ответа.", True),
        ("снятие находки об ответе отвергается вслух", True),
        ("снятие находки об ответе — по канону `closable`", False),
        ("снятие находки об ответе — по адресу f'{canon_at()}'", False),
        ("Пометку «об ответе» ставит ревьюер.", False),
        ("Находку о коде снимает любая правка.", False),
    ],
)
def test_a_retelling_is_told_from_a_reference(text: str, is_retold: bool) -> None:
    """Предикат различает пересказ без канона и ссылку на канон — обе стороны (140)."""
    assert retold(text) is is_retold


def test_a_paragraph_is_bounded_by_an_empty_literal_and_the_canon_is_skipped() -> None:
    """Абзац кончается пустым литералом, f-строка берётся целиком, тело канона пропущено."""
    source = (
        "HEAD = [\n"
        '    "Находку об ответе снимает не всякое снятие,",\n'
        '    f"канон — {closable.__name__}.",\n'
        '    "",\n'
        '    "Находку об ответе снимает только правка ответа.",\n'
        "]\n"
        "def closable():\n"
        '    """Находку об ответе снимает правка ответа или места."""\n'
    )
    found = [line for line, text in py_paragraphs(source) if retold(text)]
    assert found == [5]


@pytest.mark.parametrize(
    "source",
    [
        "# канон — closable\n\n# Находку об ответе снимает только правка ответа.\n",
        '"""Модуль: канон — closable."""\n\n# Находку об ответе снимает правка ответа.\n',
    ],
    ids=["два блока комментариев", "докстрока и комментарий"],
)
def test_a_blank_line_ends_a_paragraph(source: str) -> None:
    """Пустая строка разделяет абзацы: канон в одном не прикрывает пересказ в другом (#983)."""
    assert any(retold(text) for _, text in py_paragraphs(source))


#: Адрес канона, набранный буквами: путь к модулю и имя через `::`.
WRITTEN_AT: Final = re.compile(rf"([\w./-]+\.py)::{CANON}\b")
#: Вторая форма того же адреса — через точку (взгляд на #988, `a67d296`).
#: СТРОГО: берётся ВСЯ цепочка имён до `.closable`, и судится её последнее
#: звено — модуль. Так одной формой держатся и `review_findings.closable`, и
#: пакетная `scripts.review_findings.closable`, которую прежний образец с
#: одним звеном не видел (взгляд на #1000, `b3c2306`). Ищется только в прозе:
#: в коде `module.closable` — переменная, а не адрес.
DOTTED_AT: Final = re.compile(rf"(?<![\w./])((?:[A-Za-z_]\w*\.)+){CANON}\b")
#: Поле подстановки f-строки — код, а не проза: `{module.closable.__name__}`
#: адресом чужого модуля не является (взгляд на #1000, `86fe75b`).
REPLACEMENT_FIELD: Final = re.compile(r"\{[^{}]*\}")


def dotted_module(found: re.Match[str]) -> str:
    """Модуль точечного адреса — последнее звено цепочки перед именем канона."""
    return found.group(1).rstrip(".").rsplit(".", 1)[-1]


def test_a_written_canon_address_leads_to_the_canon() -> None:
    """Адрес канона, набранный буквами в тексте, ведёт в сам канон (взгляд на #988).

    В документе адрес иначе как буквами не записать, и это не дефект — дефект,
    когда буквы разошлись с функцией. Соседи шапки по адресу названы (195):
    `docs/agent/review.md`, докстрока этого файла и любой новый — обход тот же,
    что у пересказов, плюс сам этот файл.
    """
    files = [*texts(), SELF]
    written = [
        (path, match.group(1))
        for path in files
        for match in WRITTEN_AT.finditer(path.read_text(encoding="utf-8"))
    ]
    assert written, "адрес канона буквами не найден нигде — обход не туда"
    stale = [f"{p.relative_to(ROOT)}: {at}" for p, at in written if f"{at}::{CANON}" != CANON_AT]
    assert not stale, f"адрес канона разошёлся с `{CANON_AT}`: " + "; ".join(stale)


def prose_of(path: Path) -> list[str]:
    """Проза файла: абзацы строк и комментариев модуля либо текст документа.

    У модуля поля подстановки f-строк вырезаются: их содержимое — выражение,
    а не адрес, написанный словами.
    """
    source = path.read_text(encoding="utf-8")
    if path.suffix != ".py":
        return [source]
    return [REPLACEMENT_FIELD.sub("", text) for _, text in py_paragraphs(source)]


@pytest.mark.parametrize(
    ("text", "module"),
    [
        ("канон — `review_findings.closable`.", "review_findings"),
        ("канон — findings.closable, без кавычек.", "findings"),
        ("канон — `scripts.review_findings.closable`.", "review_findings"),
        ("канон — `scripts.findings.closable`.", "findings"),
        ("путь `scripts/review_findings.py::closable`", None),
    ],
    ids=["верный модуль", "чужой модуль", "пакетная форма", "пакетная с чужим", "форма через ::"],
)
def test_a_dotted_canon_address_is_told(text: str, module: str | None) -> None:
    """Форма через точку узнаётся целой цепочкой, а форма через `::` ей не мешает."""
    found = DOTTED_AT.search(text)
    assert (dotted_module(found) if found else None) == module


def test_a_replacement_field_is_not_prose(tmp_path: Path) -> None:
    """Выражение в f-строке — код: адресом чужого модуля оно не читается (#1000)."""
    module = tmp_path / "mod.py"
    module.write_text('LINE = f"канон — {module.closable.__name__}"\n', encoding="utf-8")
    assert not any(DOTTED_AT.search(text) for text in prose_of(module))


def test_a_dotted_canon_address_leads_to_the_canon() -> None:
    """Адрес канона через точку называет модуль самого канона (взгляд на #988).

    ПЕРЕЧЕНЬ ФОРМ — ЦЕЛИКОМ (210), после трёх заходов взгляда по этому месту:

    * голое имя `closable` — требует гейт пересказа;
    * вызов `canon_at(` — гейт пересказа принимает за названный канон, и это
      держит строка таблицы `test_a_retelling_is_told_from_a_reference`;
    * путь и имя через `::` — соседний тест `WRITTEN_AT`;
    * цепочка через точку любой длины — этот тест: судится последнее звено;
    * поле подстановки f-строки — код, вырезается из прозы (`prose_of`).

    За границей (195): путь через `/` с точкой перед именем
    (`scripts/review_findings.closable`) формой адреса не является — так канон
    не пишут, и предикат её не ищет.
    """
    written = [
        (path, dotted_module(match))
        # Сам этот файл не обходится: его таблица держит неверные формы
        # намеренно — это красные случаи.
        for path in texts()
        for text in prose_of(path)
        for match in DOTTED_AT.finditer(text)
    ]
    assert written, "адрес канона через точку не найден нигде — обход не туда"
    stale = [f"{p.relative_to(ROOT)}: {at}" for p, at in written if at != CANON_MODULE]
    assert not stale, f"адрес канона через точку называет не `{CANON_MODULE}`: " + "; ".join(stale)


def test_the_answer_removal_rule_is_retold_only_by_its_canon() -> None:
    """Абзац о снятии находки об ответе называет канон `closable` (#978)."""
    files = texts()
    assert len(files) > 100, "текстов под правилом подозрительно мало — обход не туда"
    found = [where for path in files for where in retellings(path)]
    assert not found, (
        "абзац говорит о снятии находки «об ответе» и не называет канона — "
        f"сошлитесь на `{CANON_AT}` вместо пересказа: " + "; ".join(found)
    )
