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

ЦЕНА ЭТОГО ПРЕДЕЛА ИЗМЕРЕНА, А НЕ ОЦЕНЕНА НА ГЛАЗ. Внешний взгляд назвал на
#289 верное: модуль, запускающий гейт и сравнивающий число по другому поводу,
засчитает исход по совпадению. Замер 13.09.2026 на живом наборе:

* сужение до ФУНКЦИИ (запуск и утверждение в одном теле) отняло бы **64**
  исхода у 33 механизмов — почти всё покрытие идёт через помощников модуля, и
  долг вырос бы с 17 строк до восьмидесяти с лишним;
* точечное сужение — считать лишь сравнения, где левая часть говорит об исходе
  (`code`, `returncode`, `rc`, вызов `main`), — отняло бы **27** исходов у 21
  механизма, и отличить среди них ложное покрытие от записанного иначе этим
  разбором нельзя.

Оба сужения объявили бы непокрытым то, что прогоняется, — то есть позвали бы
писать прогоны там, где они есть. ТОЧЕЧНОЕ СУЖЕНИЕ ВСЁ ЖЕ СДЕЛАНО 24.09.2026
(#687), и замер показал другое: с левой частью «вызов, кроме счёта, или
код выхода» совпадением числа держались ровно ПЯТЬ исходов у четырёх
механизмов — `len(problems) == 1`, `seen.missed == 0`, `said.count(…) == 1`
и `len(problems) == 2`. Все пять прогнаны теперь по имени точкой входа.
Сужение до функции по-прежнему не делается. Поэтому предел оставлен и назван числом:
реестр ловит механизм, у которого исхода не касались НИГДЕ, и не притворяется,
что ловит больше
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

ЧИТАТЕЛЕЙ У РАЗБОРА ТРИ: роспись отказов, реестр исходов и прогон третьего
исхода. Обобщение делалось по первым двум, и третий это подтвердил, а не
опроверг
([093](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/093-seam-early-generalisation-late.md)).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, walk

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
    for path in walk(ROOT / "scripts", "*.py"):
        said = declared(path.name)
        if said:
            found[path.name] = said
    return found


def script_names(node: ast.AST) -> set[str]:
    """Имена `*.py` среди строковых литералов этого узла."""
    return {
        str(one.value)
        for one in ast.walk(node)
        if isinstance(one, ast.Constant)
        and isinstance(one.value, str)
        and one.value.endswith(".py")
    }


def started_by(tree: ast.AST) -> set[str]:
    """Механизмы, которые этот модуль запускает или загружает.

    ПРЯМОЙ ВЫЗОВ — НЕ ЕДИНСТВЕННАЯ ФОРМА ЗАПУСКА. Набор гоняет гейты и
    параметризованно: `@pytest.mark.parametrize("gate", WITHOUT_INPUT)` и
    `run_script(gate, ...)`. Разбор, знающий только литерал в скобках, таких
    прогонов не видел вовсе — семь прогонов третьего исхода не засчитались, и
    реестр показывал долг, которого уже нет
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

    Поэтому имена берутся ещё из набора параметров и из констант уровня
    модуля — но ТОЛЬКО у модуля, который механизмы действительно запускает.
    Цена названа: модуль, перечисливший имя в константе и не прогнавший его,
    засчитает лишнее. Имя в прозе так не пройдёт — докстринг константой
    модуля не является
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    found: set[str] = set()
    direct = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or getattr(node.func, "id", "") not in WAYS_IN:
            continue
        direct = True
        found |= {name for one in node.args for name in script_names(one)}
    if not direct:
        return found

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "parametrize":
            found |= {name for one in node.args for name in script_names(one)}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            found |= script_names(node.value)
    return found


#: Вызовы, чей результат — счёт или форма, а не исход механизма: число рядом
#: с ними говорит о длине списка, а не о коде выхода (#687).
COUNTERS: Final = frozenset(
    {"len", "sum", "min", "max", "sorted", "list", "set", "tuple", "dict", "frozenset"}
    | {"str", "int", "abs", "round", "any", "all", "type", "bool", "getattr", "isinstance"}
    | {"count", "index", "find", "get"}
)

#: Имена, которыми тест называет код выхода, когда он уже взят из прогона.
CODE_NAMES: Final = frozenset({"code", "returncode", "rc", "exit_code"})


def speaks_of_an_outcome(left: ast.expr) -> bool:
    """Говорит ли левая часть сравнения об исходе механизма.

    ЧИСЛО ЗАСЧИТЫВАЕТСЯ ТОЛЬКО РЯДОМ С ИСХОДОМ. Прежде годилось любое
    сравнение: `assert len(lines) == 2` засчитывалось за прогон `EXIT_BROKEN
    = 2` у двух механизмов разом, и когда строк стало три, выяснилось, что по
    имени эти исходы не прогонял никто (#687). Исход — это вызов (`main(…)`,
    помощник модуля `run(…)`), кроме вызовов счёта (`COUNTERS`), либо код,
    уже взятый из прогона (`done.code`, `result.returncode`, `rc`).
    """
    if isinstance(left, ast.Call):
        func = left.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        return name not in COUNTERS
    if isinstance(left, ast.Attribute):
        return left.attr in CODE_NAMES
    return isinstance(left, ast.Name) and left.id in CODE_NAMES


def asserted(tree: ast.AST) -> tuple[set[int], set[str]]:
    """С чем модуль сравнивает исход: числа рядом с исходом и имена констант.

    Имя объявленной константы засчитывается при любой левой части: сравнение
    с `EXIT_FOUND` называет исход само. Число — только рядом с исходом
    (`speaks_of_an_outcome`).
    """
    local = whole_numbers(tree)
    numbers: set[int] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        near = speaks_of_an_outcome(node.left)
        for one in node.comparators:
            if isinstance(one, ast.Constant) and isinstance(one.value, int):
                if near and not isinstance(one.value, bool):
                    numbers.add(one.value)
            elif isinstance(one, ast.Name):
                if one.id in local:
                    if near:
                        numbers.add(local[one.id])
                elif one.id.startswith(OUTCOME_PREFIX):
                    names.add(one.id)
            elif isinstance(one, ast.Attribute) and one.attr.startswith(OUTCOME_PREFIX):
                names.add(one.attr)
            # Исход берут и по имени из разбора самого механизма:
            # `declared(gate)["EXIT_BROKEN"]`. Строка живёт внутри сравнения, а
            # не в прозе, и не назвать это прогоном значило бы держать в долге
            # строку, которую уже прогоняют (075).
            names |= {
                str(said.value)
                for said in ast.walk(one)
                if isinstance(said, ast.Constant)
                and isinstance(said.value, str)
                and said.value.startswith(OUTCOME_PREFIX)
            }
    return numbers, names


def run_by_the_suite() -> dict[str, set[int]]:
    """Какие объявленные исходы каждого механизма набор действительно прогнал."""
    said = with_outcomes()
    found: dict[str, set[int]] = {name: set() for name in said}
    for path in walk(ROOT / "tests", "test_*.py"):
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
