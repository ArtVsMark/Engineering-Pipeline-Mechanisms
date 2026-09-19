"""Образец, разбирающий ВЫЗОВ питона, заменяется разбором — или объявляется.

Вызов — отношение, а не строка: `Path.home()`, `pathlib . Path . home ()` и
`from pathlib import Path as P; P.home()` — одно и то же обращение, записанное
тремя способами. Образец по тексту видит одно написание из трёх и промахивается
в ОБЕ стороны: пропускает остальные два и засчитывает упоминание в докстроке
([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).

ЧЕМ ЭТО ХУЖЕ ОБЫЧНОЙ ОШИБКИ. Промах ПРЕДИКАТА краснеет: проверка отвергла
верное, это видно и чинится. Промах образца, которым ОТБИРАЮТ предмет, не
краснеет никогда — файл просто не попадает в проверку, и гейт остаётся зелёным,
ничего о нём не проверив
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Образцов, разбирающих вызов, в
дереве было ПЯТЬ. Четыре из них разбирали питон и заменены разбором — и замена
не косметическая: `.parents`-образец не видел ни `from os import getcwd`, ни
`pathlib.Path.cwd()`, а образец общей площадки не видел `Path . home ()` и
краснел бы на прозе о `/tmp`. Пятый разбирает не питон и объявлен ниже с
причиной.

РОД СЧИТАН, А НЕ ПОЧУВСТВОВАН. «Подстрока вместо отношения» — шесть встреч в
`.rules/finding-kinds.json`, из них четыре поймано в окне. Общего гейта на род
нет, и причина там же: грубый предикат «модуль судит исходник строкой» даёт 45
модулей из 60. Здесь взят УЗКИЙ и острый признак вместо широкого и вкусового
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: образец, описывающий
обращение по точке БЕЗ скобки — `tempfile\\.gettempdir`. Отличить такой от
расширения файла (`\\.py`, `\\.json`) предикатом нельзя: в дереве это 22
образца, и почти все — про пути, а не про питон. Единственный такой образец о
питоне был в `tests/test_suite_owns_its_ground.py` и уехал разбором вместе с
соседями
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, walk

#: Где ищем образцы: набор, механизмы, перехваты и общий низ.
WHERE: Final = ("tests", "scripts", ".claude/hooks", "packages/transport")

#: Как узнают образец, разбирающий вызов: ИМЯ вплотную к экранированной скобке.
#: Скобка Markdown (`](`) сюда не попадает намеренно — там перед скобкой не имя.
A_CALL: Final = re.compile(r"\w\\\(")

#: Куда кладут образец: сборка впрок и разовые вызовы разбора.
PATTERN_GOES_TO: Final = frozenset(
    {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "split"}
)

#: Образцы, которые разбирают НЕ питон, — закрытый список с причиной у каждого
#: (068, 154). Ключ — адрес места, а не сам образец: образец правят, и запись
#: отстала бы молча.
PARSES_SOMETHING_ELSE: Final = {
    "tests/test_review_safety.py": (
        "разбирает вызов инструмента Bash в строке разрешения ревью, а не питон. "
        "Разбором питона его не заменить: строка приходит из настроек действия и "
        "исходником не является"
    ),
}


def patterns() -> list[tuple[Path, int, str]]:
    """Все образцы дерева, отданные разбору: файл, строка, сам образец."""
    found: list[tuple[Path, int, str]] = []
    for where in WHERE:
        for path in walk(ROOT / where, "*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                head = node.func
                name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
                if name not in PATTERN_GOES_TO:
                    continue
                said = node.args[0]
                if isinstance(said, ast.Constant) and isinstance(said.value, str):
                    found.append((path, node.lineno, said.value))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    assert patterns(), "в дереве не нашлось ни одного образца — сверять нечего"


def test_no_pattern_parses_a_python_call() -> None:
    """Вызов питона читается разбором, а не образцом по тексту.

    Исключение — только объявленное: образец, разбирающий чужой язык. Молчаливое
    исключение неотличимо от недосмотра
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    stray = [
        f"{path.relative_to(ROOT)}:{line} — «{said[:48]}»"
        for path, line, said in patterns()
        if A_CALL.search(said) and path.relative_to(ROOT).as_posix() not in PARSES_SOMETHING_ELSE
    ]
    assert not stray, (
        "образец разбирает вызов питона (166):\n  "
        + "\n  ".join(stray)
        + "\n  Замените разбором: tests/conftest.py::names_used и string_args_of"
        " читают употребление имени и доводы вызова в любой записи."
        "\n  Если образец разбирает НЕ питон — объявите его в"
        " PARSES_SOMETHING_ELSE с причиной."
    )


def test_every_declared_exception_still_has_its_pattern() -> None:
    """Объявленное исключение не переживает своего образца.

    Запись, чей образец уже заменён разбором, — разрешение, которое никто не
    просил: оно молча пропустит следующий такой образец в том же файле
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    alive = {
        path.relative_to(ROOT).as_posix() for path, _, said in patterns() if A_CALL.search(said)
    }
    dead = sorted(set(PARSES_SOMETHING_ELSE) - alive)
    assert not dead, f"объявлено исключение, а образца в файле нет: {dead} — снимите запись"


def test_every_declared_exception_names_its_reason() -> None:
    """У исключения названа причина, а не поставлена галочка (154)."""
    bare = [where for where, why in PARSES_SOMETHING_ELSE.items() if len(why.strip()) < 40]
    assert not bare, f"исключение без причины: {bare}"
