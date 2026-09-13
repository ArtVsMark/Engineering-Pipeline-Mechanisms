"""Разбор объявленных исходов: что механизм обещает и что набор прогоняет.

ЗАЧЕМ ОТДЕЛЬНЫМ МОДУЛЕМ. Читателей у этого разбора двое — роспись отказов
(`test_gates_reject.py`) и реестр исходов (`test_outcomes_run.py`), — и второе
понимание той же формы разошлось бы с первым молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ЧТО СЧИТАЕТСЯ ПРОГОНОМ ИСХОДА. Только сравнение исхода с числом или с
объявленной константой: имя, попавшее в прозу или в набор строк, прогоном не
является. Предел разбора назван честно — предметом считается МОДУЛЬ теста, а
не отдельный случай: гейты нередко запускают вспомогательной функцией, и
разбор по случаям терял такие прогоны
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.conftest import ROOT

#: Приставка, которой этот проект называет объявленный исход механизма.
OUTCOME_PREFIX: Final = "EXIT_"

#: Как тест добирается до механизма: запуском процессом или импортом модуля.
WAYS_IN: Final = frozenset({"run_script", "load_script"})


def whole_numbers(tree: ast.AST) -> dict[str, int]:
    """Целые константы уровня модуля — и `X = 2`, и `X: Final = 2`.

    Обе формы нужны: механизмы объявляют исходы с `Final`, а тесты называют их
    у себя простым присваиванием (`BROKEN = 2`). Разбор, знающий одну форму,
    считает половину сравнений несостоявшимися — на первом замере это дало
    тринадцать ложных пробелов из сорока восьми
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    found: dict[str, int] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name, value = node.targets[0].id, node.value
        else:
            continue
        said = value.value if isinstance(value, ast.Constant) else None
        if isinstance(said, int) and not isinstance(said, bool):
            found[name] = said
    return found


def tree_of(path: Path) -> ast.AST:
    """Разбор файла — одной строкой на всех читателей."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=path.name)


def declared(script: str) -> dict[str, int]:
    """Исходы, которые ЭТОТ механизм объявляет: имя константы → число.

    Спрашивается у механизма, а не назначается списком: отказ не всегда
    единица, а «не настроено» у части гейтов объявлено тройкой.
    """
    return {
        name: value
        for name, value in whole_numbers(tree_of(ROOT / "scripts" / script)).items()
        if name.startswith(OUTCOME_PREFIX)
    }


def with_outcomes() -> dict[str, dict[str, int]]:
    """Механизмы дерева, объявившие хоть один исход, — предмет реестра."""
    found: dict[str, dict[str, int]] = {}
    for path in sorted((ROOT / "scripts").glob("*.py")):
        said = declared(path.name)
        if said:
            found[path.name] = said
    return found


def started_by(tree: ast.AST) -> set[str]:
    """Механизмы, которые этот модуль запускает или загружает."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or getattr(node.func, "id", "") not in WAYS_IN:
            continue
        for one in node.args:
            if isinstance(one, ast.Constant) and str(one.value).endswith(".py"):
                found.add(str(one.value))
    return found


def asserted(tree: ast.AST) -> tuple[set[int], set[str]]:
    """С чем модуль сравнивает исход: числа и имена объявленных констант."""
    local = whole_numbers(tree)
    numbers: set[int] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for one in node.comparators:
            if isinstance(one, ast.Constant) and isinstance(one.value, int):
                if not isinstance(one.value, bool):
                    numbers.add(one.value)
            elif isinstance(one, ast.Name):
                if one.id in local:
                    numbers.add(local[one.id])
                elif one.id.startswith(OUTCOME_PREFIX):
                    names.add(one.id)
            elif isinstance(one, ast.Attribute) and one.attr.startswith(OUTCOME_PREFIX):
                names.add(one.attr)
    return numbers, names


def run_by_the_suite() -> dict[str, set[int]]:
    """Какие объявленные исходы каждого механизма набор действительно прогнал."""
    said = with_outcomes()
    found: dict[str, set[int]] = {name: set() for name in said}
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = tree_of(path)
        numbers, names = asserted(tree)
        for script in started_by(tree) & set(said):
            found[script] |= numbers & set(said[script].values())
            found[script] |= {said[script][name] for name in names if name in said[script]}
    return found


def gaps() -> dict[str, list[str]]:
    """Объявленные исходы без единого прогона: механизм → имена констант."""
    said = with_outcomes()
    ran = run_by_the_suite()
    found: dict[str, list[str]] = {}
    for script, outcomes in said.items():
        missing = sorted(name for name, code in outcomes.items() if code not in ran[script])
        if missing:
            found[script] = missing
    return found
