"""Код написан на версии планки, а не только объявлен на ней (217, #1058).

ПЛАНКА — ДВА ОБЕЩАНИЯ, А НЕ ОДНО. `requires-python` обещает потребителю, что
пакет заработает на этой версии, — это держит `scripts/check_env.py`. Но то же
число говорит читателю «код пишется на этой версии», и это обещание не держал
никто: правило 217 считает переезд сделанным, когда на версии написан код и всё
на ней исполняется, а не когда набор прошёл. Ruff с `UP` при
`target-version = "py314"` ловит часть отставания, но не эти две формы: на
обеих находках замера ниже ruff 0.16.10 ответил «All checks passed!».

ЗАМЕР ДО ПОЧИНКИ, 03.10.2026: отслеживаемых `.py` — 221, находок — 2, обе в
`.claude/hooks/push_guard.py`: одна `from __future__ import annotations` и
одно `except (A, B):` без `as`. Страж оставался на стиле 3.12 не по
недосмотру: его звал голый `python3` окна (3.11), и стиль планки уронил бы его
`SyntaxError`ом, а этот исход площадка считает НЕблокирующим. Причина снята там,
где жила: хук зовёт интерпретатор планки через `.claude/hooks/push_guard.sh`.
Исключений поэтому нет ни одного.

ЦЕЛЬ ВЫВОДИТСЯ ИЗ ПЛАНКИ, А НЕ ВПИСЫВАЕТСЯ (005). Каждое требование знает
версию, С КОТОРОЙ оно доступно, и действует, только когда планка до неё
доросла; планку читает один разборщик — `check_env.python_floor` (214).

ГЕЙТ ЖИВЁТ НАБОРОМ, А НЕ ОТДЕЛЬНЫМ СКРИПТОМ. Предмет — свойство самого дерева,
и такие свойства проект держит набором (`test_skips`, `test_docs_shape`). У
соседа-каталога то же сделано скриптом `check_py_style.py`; разница в форме, а
не в существе (090).
"""

import ast
import io
import subprocess
import tokenize
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

#: С какой версии языка доступно то, что требуется: аннотации ленивы сами
#: (PEP 649/749) — и `from __future__ import annotations` лишний.
LAZY_ANNOTATIONS: Final = (3, 14)
#: С какой версии несколько исключений пишутся без скобок, если нет `as` (PEP 758).
BARE_EXCEPT_TUPLE: Final = (3, 14)

OPENING: Final = frozenset("([{")
CLOSING: Final = frozenset(")]}")


def tracked_python() -> list[str]:
    """Отслеживаемые `.py` — то, что поедет, а не то, что лежит рядом.

    Пустой ответ — отказ, а не чистый прогон: гейт, не нашедший предмета,
    зеленел бы ноль раз (075).
    """
    done = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, f"git ls-files не отработал: {done.stderr.strip()}"
    found = sorted(one for one in done.stdout.split("\0") if one)
    assert found, "отслеживаемых .py нет ни одного — проверять нечего (075)"
    return found


def parenthesised_excepts(text: str) -> list[int]:
    """Строки, где НЕСКОЛЬКО исключений взяты в скобки без `as`.

    Токенами, а не регулярным выражением: `except (` внутри строкового литерала
    или комментария — не предмет. `except*` (группы исключений) — предмет тот
    же: PEP 758 снимает скобки и у него. Кортеж из одного элемента с хвостовой
    запятой, `except (A,):`, — не предмет: без скобок он не записывается вовсе.
    """
    tokens = [
        one
        for one in tokenize.generate_tokens(io.StringIO(text).readline)
        if one.type not in (tokenize.NL, tokenize.COMMENT)
    ]
    lines: list[int] = []
    for at, token in enumerate(tokens):
        if token.type != tokenize.NAME or token.string != "except":
            continue
        start = at + 1
        if start < len(tokens) and tokens[start].string == "*":
            start += 1
        if start >= len(tokens) or tokens[start].string != "(":
            continue
        depth, items, end = 0, 1, start
        while end < len(tokens):
            word = tokens[end].string
            if word in OPENING:
                depth += 1
            elif word in CLOSING:
                depth -= 1
            elif (
                depth == 1
                and word == ","
                and end + 1 < len(tokens)
                and tokens[end + 1].string != ")"
            ):
                items += 1
            if depth == 0:
                break
            end += 1
        if items > 1 and end + 1 < len(tokens) and tokens[end + 1].string == ":":
            lines.append(token.start[0])
    return lines


def imports_lazy_annotations(text: str) -> bool:
    """Включены ли аннотации `__future__` — любой формой импорта.

    Разбором, а не образцом строки: регулярка знала только одиночное
    `import annotations`, и `import annotations, division` или
    `import (annotations)` проходили гейт (`4a98809`).
    """
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in ast.walk(ast.parse(text))
    )


def style_findings(where: str, text: str, floor: tuple[int, int]) -> list[str]:
    """Что в файле отстаёт от планки — с адресом и причиной."""
    said = f"{floor[0]}.{floor[1]}"
    found: list[str] = []
    if floor >= LAZY_ANNOTATIONS and imports_lazy_annotations(text):
        found.append(
            f"{where}: `from __future__ import annotations` при планке {said}"
            " — аннотации и так ленивы (PEP 649)"
        )
    if floor >= BARE_EXCEPT_TUPLE:
        found += [
            f"{where}:{line}: `except (A, B):` без `as` при планке {said}"
            " — скобки не нужны (PEP 758)"
            for line in parenthesised_excepts(text)
        ]
    return found


def test_the_tree_is_written_on_the_floor() -> None:
    """Ни один отслеживаемый файл не отстаёт от планки — исключений нет (217)."""
    floor = load_script("check_env.py").python_floor(ROOT)
    findings = [
        one
        for where in tracked_python()
        for one in style_findings(where, (ROOT / where).read_text(encoding="utf-8"), floor)
    ]
    assert findings == [], "стиль отстаёт от планки:\n  " + "\n  ".join(findings)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("try:\n    pass\nexcept (A, B):\n    pass\n", [3]),
        ("try:\n    pass\nexcept* (A, B):\n    pass\n", [3]),
        ("try:\n    pass\nexcept (A, B) as e:\n    pass\n", []),
        ("try:\n    pass\nexcept (A,):\n    pass\n", []),
        ("try:\n    pass\nexcept A, B:\n    pass\n", []),
        ("try:\n    pass\nexcept (f(a, b), C):\n    pass\n", [3]),
        ("text = 'except (A, B):'\n# except (A, B):\n", []),
    ],
    ids=["скобки", "группа", "с as", "один элемент", "уже без скобок", "вызов внутри", "текст"],
)
def test_the_except_finder_sees_only_the_subject(source: str, expected: list[int]) -> None:
    """Предмет — скобки у нескольких исключений без `as`; литерал и `(A,)` — нет."""
    assert parenthesised_excepts(source) == expected


def test_the_requirements_follow_the_floor() -> None:
    """Ниже 3.14 обе формы законны: требование включает планка, а не этот файл (005)."""
    text = "from __future__ import annotations\ntry:\n    pass\nexcept (A, B):\n    pass\n"
    assert style_findings("x.py", text, (3, 13)) == []
    assert len(style_findings("x.py", text, (3, 14))) == 2


@pytest.mark.parametrize(
    "line",
    [
        "from __future__ import annotations",
        "from __future__ import annotations, division",
        "from __future__ import (annotations)",
        "from __future__ import division, annotations",
    ],
)
def test_every_form_of_the_future_import_is_seen(line: str) -> None:
    """Импорт `__future__` виден в любой форме, а соседний `division` — нет (`4a98809`)."""
    assert imports_lazy_annotations(f"{line}\n")
    assert not imports_lazy_annotations("from __future__ import division\n")
