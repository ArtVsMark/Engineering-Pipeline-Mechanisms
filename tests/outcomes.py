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
писать прогоны там, где они есть. Для ТОЧЕЧНОГО этот довод 24.09.2026 перестал
быть верным (#687): замер с другой меркой исхода — «вызов, кроме счёта, или
код выхода», а не только `main` и `code` — нашёл совпадением числа ровно ПЯТЬ
исходов у четырёх механизмов (`len(problems) == 1`, `seen.missed == 0`,
`said.count(…) == 1`, `len(problems) == 2`), и все пять прогнаны теперь по
имени. Число 27 выше — цена прежней, более узкой мерки, и она сохранена как
история. Точечное сужение сделано; довод остаётся в силе для сужения ДО
ФУНКЦИИ, и потому предел по модулю оставлен и назван числом:
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
from dataclasses import dataclass
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
#:
#: Сюда же — ВИДЫ СЛОВАРЯ `.values()` и `.keys()`: сверка
#: `m.EXIT_SILENT not in declared(g).values()` сравнивает имена между собой,
#: как и перечнем (`abd8efa`), но через вызов шла за прогон (`ea8b1fc`).
COUNTERS: Final = frozenset(
    {"len", "sum", "min", "max", "sorted", "list", "set", "tuple", "dict", "frozenset"}
    | {"str", "int", "abs", "round", "any", "all", "type", "bool", "getattr", "isinstance"}
    | {"count", "index", "find", "get"}
    | {"values", "keys"}
)

#: Помощник ЭТОГО модуля, читающий объявления: исходом его вызов не является.
#: УЗНАЁТСЯ ПО ИМПОРТУ, А НЕ ПО ИМЕНИ. Замер 24.09.2026, прочитанный
#: поимённо: помощник модули тестов получают только `from tests import
#: outcomes` (четыре файла) и зовут `outcomes.declared(…)`; все 17 голых
#: `declared(…)` в `test_*.py` — СВОИ функции `test_claims`,
#: `test_consumer_channel` и `test_schedules`, к помощнику отношения не
#: имеющие (взгляд на #745). Узнавание по одному имени отсекало их, узнавание
#: по `outcomes.` пропускало псевдоним — связь берётся из импортов модуля.
#: `m.declared(…)` у механизма — его собственная функция, и её вызов остаётся
#: исходом. Граница названа: `import tests.outcomes` в любой форме (вызов
#: `tests.outcomes.declared` или через псевдоним) и помощник теста с другим именем, возвращающий
#: объявления, сойдут за исход — в наборе сегодня нет ни того, ни другого.
READER: Final = "declared"
#: Модуль помощника — как его импортируют читатели.
READER_PACKAGE: Final = "tests"
READER_HOME: Final = "outcomes"


@dataclass(frozen=True, slots=True)
class Readers:
    """Под какими именами модуль теста знает помощник: его модуль и его самого."""

    homes: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()


#: Модуль, не импортировавший помощник: узнавать нечего.
NO_READERS: Final = Readers()


def readers_of(tree: ast.AST) -> Readers:
    """Имена, под которыми модуль импортировал помощник `declared` — с псевдонимами."""
    homes: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == READER_PACKAGE:
            homes |= {one.asname or one.name for one in node.names if one.name == READER_HOME}
        elif isinstance(node, ast.ImportFrom) and node.module == f"{READER_PACKAGE}.{READER_HOME}":
            names |= {one.asname or one.name for one in node.names if one.name == READER}
    return Readers(frozenset(homes), frozenset(names))


def reads_declarations(func: ast.expr, readers: Readers) -> bool:
    """Зовёт ли вызов помощник `declared` этого модуля — под тем именем, что импортировано."""
    if isinstance(func, ast.Name):
        return func.id in readers.names
    return (
        isinstance(func, ast.Attribute)
        and func.attr == READER
        and isinstance(func.value, ast.Name)
        and func.value.id in readers.homes
    )


#: Имена, которыми тест называет код выхода, когда он уже взят из прогона.
CODE_NAMES: Final = frozenset({"code", "returncode", "rc", "exit_code", "код"})


def speaks_of_an_outcome(side: ast.expr, readers: Readers = NO_READERS) -> bool:
    """Говорит ли сторона сравнения — любая — об исходе механизма.

    ЧИСЛО ЗАСЧИТЫВАЕТСЯ ТОЛЬКО РЯДОМ С ИСХОДОМ. Прежде годилось любое
    сравнение: `assert len(lines) == 2` засчитывалось за прогон `EXIT_BROKEN
    = 2` у двух механизмов разом, и когда строк стало три, выяснилось, что по
    имени эти исходы не прогонял никто (#687). Исход — это вызов (`main(…)`,
    помощник модуля `run(…)`), кроме вызовов счёта (`COUNTERS`), либо код,
    уже взятый из прогона (`done.code`, `result.returncode`, `rc`).
    """
    if isinstance(side, ast.Call):
        func = side.func
        if reads_declarations(func, readers):
            return False
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        return name not in COUNTERS
    if isinstance(side, ast.Attribute):
        return side.attr in CODE_NAMES
    return isinstance(side, ast.Name) and side.id in CODE_NAMES


def spelled_numbers(side: ast.expr, local: dict[str, int]) -> set[int]:
    """Числа, которые сторона сравнения называет: сама или перечнем.

    `assert main([]) in (0, 2)` называет оба исхода — кортеж, список и
    множество чисел читаются так же, как одно число (`877542e`).
    """
    parts = side.elts if isinstance(side, (ast.Tuple, ast.List, ast.Set)) else [side]
    found: set[int] = set()
    for one in parts:
        if isinstance(one, ast.Constant) and isinstance(one.value, int):
            if not isinstance(one.value, bool):
                found.add(one.value)
        elif isinstance(one, ast.Name) and one.id in local:
            found.add(local[one.id])
    return found


def spelled_names(side: ast.expr) -> set[str]:
    """Имена исходов, которые сторона называет: сама, перечнем или ключом подписки.

    Своя константа модуля теста (`EXIT_X = 2`) у сравнения счёта
    (`len(lines) == EXIT_X`) не засчитывается — его отсекает правило «только
    рядом с исходом» в `asserted` (`a646521`). Отдельного условия на неё здесь
    было заведено — и откат его не покраснел: оно ничего не держало и снято.
    """
    parts = side.elts if isinstance(side, (ast.Tuple, ast.List, ast.Set)) else [side]
    found: set[str] = set()
    for one in parts:
        if isinstance(one, ast.Name) and one.id.startswith(OUTCOME_PREFIX):
            found.add(one.id)
        elif isinstance(one, ast.Attribute) and one.attr.startswith(OUTCOME_PREFIX):
            found.add(one.attr)
        # Исход берут и по имени из разбора самого механизма:
        # `declared(gate)["EXIT_BROKEN"]`. Строка живёт ключом подписки, и не
        # назвать это прогоном значило бы держать в долге строку, которую уже
        # прогоняют (075).
        found |= {
            str(said.slice.value)
            for said in ast.walk(one)
            if isinstance(said, ast.Subscript)
            and isinstance(said.slice, ast.Constant)
            and isinstance(said.slice.value, str)
            and said.slice.value.startswith(OUTCOME_PREFIX)
        }
    return found


def asserted(tree: ast.AST) -> tuple[set[int], set[str]]:
    """С чем модуль сравнивает исход: числа рядом с исходом и имена констант.

    И число, и имя объявленной константы засчитываются только рядом с исходом
    (`speaks_of_an_outcome`), по одному или перечнем. Строка `"EXIT_…"` —
    только ключом подписки, `declared(gate)["EXIT_BROKEN"]`: голая строка в
    сравнении (`"EXIT_BROKEN" in out`) — проза вывода, а не прогон (`bcc5db5`).
    """
    local = whole_numbers(tree)
    readers = readers_of(tree)
    numbers: set[int] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # СТОРОНА НЕ ВАЖНА: `assert 2 == main([])` — тот же прогон, что и
        # `assert main([]) == 2`. Судилась одна левая часть, и обратный порядок
        # давал ложный долг (`397be6f`).
        sides = [node.left, *node.comparators]
        near = any(speaks_of_an_outcome(one, readers) for one in sides)
        # ИМЯ ТОЖЕ ЗАСЧИТЫВАЕТСЯ ТОЛЬКО РЯДОМ С ИСХОДОМ. Сверка объявлений
        # `m.EXIT_SILENT not in (m.EXIT_OK, …)` — не прогон, а сравнение имён
        # между собой, и она шла за прогон (`abd8efa`); перечень имён рядом с
        # исходом (`main([]) in (m.EXIT_OK, m.EXIT_FOUND)`) — прогон обоих
        # (`fb22afd`).
        if not near:
            continue
        for one in sides:
            numbers |= spelled_numbers(one, local)
            names |= spelled_names(one)
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
