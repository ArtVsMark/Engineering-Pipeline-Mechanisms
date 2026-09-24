"""Реестр: у каждого объявленного исхода механизма есть прогон (145).

ЧТО ЗДЕСЬ ПРЕДМЕТ. Механизм объявляет исходы константами `EXIT_*` и обещает
ими поведение: ноль — чисто, находка — своим числом, третий — «не отработал».
Объявление поведением не является. Прогон, которого нет, не расходится с
обещанием вслух: он молчит, и расхождение находит потребитель.

ПОЧЕМУ ЭТОГО НЕ ЛОВИЛА РОСПИСЬ ОТКАЗОВ. `test_gates_reject.py` спрашивает
одно: есть ли у гейта прогон ТОГО, ЧТО ОН ОБЯЗАН ОТВЕРГНУТЬ. Предмет там —
файлы с приставкой `check_`, а исход — только отказ. За границей остались и
механизмы без приставки (`stuck.py`, `drift.py`, `hail.py`), и два других
исхода у самих гейтов. Замер 13.09.2026: из 102 объявленных исходов **35** не
прогонялись ни разу, и большинство — третий, который снаружи неотличим от
«чисто»
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ПОЧЕМУ ДОЛГ ОБЪЯВЛЕН, А НЕ ЗАКРЫТ ОДНИМ ЗАХОДОМ. Тридцать пять прогонов в
одном изменении — это тридцать пять новых разборов за раз, и читателю столько
за раз не понять (`docs/decisions/008`). Пробел назван поимённо в
`.rules/outcomes.json` и может только убывать; ровнять его молчанием было бы
хуже неполноты
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
import json
from typing import Final

import pytest

from tests import outcomes
from tests.conftest import ROOT, walk

REGISTRY: Final = ROOT / ".rules" / "outcomes.json"


def debt() -> dict[str, list[str]]:
    """Объявленный долг: механизм → имена исходов без прогона."""
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {str(k): [str(one) for one in v] for k, v in doc["долг"].items()}


def test_the_registry_names_why_and_how_it_shrinks() -> None:
    """У реестра есть причина и правило сокращения — молчание не состояние (154)."""
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for key in ("почему", "как сокращается"):
        assert doc.get(key, "").strip(), f"в реестре исходов нет поля «{key}»"


def test_the_subject_is_found() -> None:
    """Механизмы с объявленными исходами в дереве есть — иначе реестр пуст (075)."""
    said = outcomes.with_outcomes()
    assert said, "ни один механизм не объявляет исходов — предмет реестра не найден"


def test_the_debt_names_only_real_outcomes() -> None:
    """Каждая строка долга указывает на существующий исход существующего механизма.

    Строка про снятый механизм или переименованную константу — это долг,
    который никогда не закроется и никого ни к чему не обязывает.
    """
    said = outcomes.with_outcomes()
    for script, names in debt().items():
        assert script in said, (
            f"долг называет «{script}», а такого механизма с объявленными исходами нет: "
            "строка не закроется никогда — вычеркните её"
        )
        for name in names:
            assert name in said[script], (
                f"долг называет исход «{name}» у {script}, а тот его не объявляет"
            )


def test_the_debt_has_no_closed_lines() -> None:
    """Прогнанный исход из долга вычеркнут: реестр, ничего не держащий, красен.

    Пока закрытая строка лежит в списке, реестр показывает долг, которого нет,
    и следующий заход верит числу, а не дереву
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    gaps = outcomes.gaps()
    closed = {
        script: sorted(set(names) - set(gaps.get(script, []))) for script, names in debt().items()
    }
    closed = {script: names for script, names in closed.items() if names}
    assert not closed, (
        "эти исходы уже прогоняются, а в долге ещё числятся: "
        + "; ".join(f"{script}: {', '.join(names)}" for script, names in sorted(closed.items()))
        + " — вычеркните их из .rules/outcomes.json"
    )


def test_no_outcome_stays_unrun_outside_the_debt() -> None:
    """Новый объявленный исход приезжает со своим прогоном, а не в долг.

    Долг — это хвост, снятый замером один раз, а не место, куда дописывают
    свежее. Механизм, объявивший исход и не прогнавший его, обещает поведение,
    которого никто не проверял
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    """
    known = debt()
    fresh = {
        script: sorted(set(names) - set(known.get(script, [])))
        for script, names in outcomes.gaps().items()
    }
    fresh = {script: names for script, names in fresh.items() if names}
    assert not fresh, (
        "исходы объявлены, но не прогоняются и в долге не числятся: "
        + "; ".join(f"{script}: {', '.join(names)}" for script, names in sorted(fresh.items()))
        + " — прогоните их, а не дописывайте в .rules/outcomes.json"
    )


def narrowed_to_functions() -> dict[str, set[int]]:
    """Покрытие, засчитанное лишь когда запуск и утверждение в одном теле.

    Это и есть то сужение, которое просил внешний взгляд на #289. Считается
    здесь, чтобы цена отказа от него была ПРОВЕРЯЕМА, а не лежала в прозе
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
    """
    said = outcomes.with_outcomes()
    found: dict[str, set[int]] = {name: set() for name in said}
    for path in walk(ROOT / "tests", "test_*.py"):
        for node in ast.walk(outcomes.tree_of(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            numbers, names = outcomes.asserted(node)
            for script in outcomes.started_by(node) & set(said):
                found[script] |= numbers & set(said[script].values())
                found[script] |= {said[script][one] for one in names if one in said[script]}
    return found


def test_narrowing_the_parser_would_hide_runs_that_exist() -> None:
    """Сужение разбора до функции отняло бы покрытие, которое ЕСТЬ.

    Предел разбора оставлен намеренно, и читатель не обязан верить прозе:
    цена считается здесь. Порог взят с большим запасом от замера 13.09.2026
    (64 исхода у 33 механизмов) — проверяется ПОРЯДОК величины, а не число,
    которое поедет с деревом
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
    """
    ran = outcomes.run_by_the_suite()
    tight = narrowed_to_functions()
    lost = sum(len(ran[script] - tight[script]) for script in ran)
    assert lost > 20, (
        f"сужение до функции отняло бы всего {lost} исходов — цена предела упала, "
        "и решение его оставить надо пересмотреть"
    )


@pytest.mark.parametrize(
    ("source", "numbers"),
    [
        ("assert len(lines) == 2", set()),
        ("assert seen.missed == 0", set()),
        ("assert said.count('x') == 1", set()),
        ("assert main([]) == 2", {2}),
        ("assert module.main(['--x']) == 1", {1}),
        ("assert done.code == 1", {1}),
        ("assert result.returncode == 2", {2}),
        ("CLEAN = 0\nassert run(tree, '--head', 'w') == CLEAN", {0}),
        ("assert 2 == main([])", {2}),
        ("assert 2 == len(lines)", set()),
        ("assert main([]) in (0, 2)", {0, 2}),
        ("assert len(lines) in (1, 2)", set()),
    ],
    ids=[
        "len",
        "поле",
        "count",
        "main",
        "module.main",
        "code",
        "returncode",
        "помощник",
        "main справа",
        "len справа",
        "перечень",
        "перечень счёта",
    ],
)
def test_a_number_counts_only_beside_an_outcome(source: str, numbers: set[int]) -> None:
    """Число засчитывается прогоном только рядом с исходом (#687).

    Первая половина: счёт строк, поле объекта и `count` исходом не являются, и
    `len(lines) == 2` больше не сходит за прогон `EXIT_BROKEN`. Вторая:
    вызов точки входа, помощника модуля и код, взятый из прогона, по-прежнему
    засчитываются — иначе сужение позвало бы писать прогоны, которые есть.
    """
    assert outcomes.asserted(ast.parse(source))[0] == numbers


@pytest.mark.parametrize(
    ("source", "names"),
    [
        ('assert main([]) == declared("g.py")["EXIT_BROKEN"]', {"EXIT_BROKEN"}),
        ('assert "EXIT_BROKEN" in out', set()),
        ("assert main([]) == module.EXIT_FOUND", {"EXIT_FOUND"}),
        ("assert main([]) in (m.EXIT_OK, m.EXIT_FOUND)", {"EXIT_OK", "EXIT_FOUND"}),
        ("assert m.EXIT_SILENT not in (m.EXIT_OK, m.EXIT_FOUND)", set()),
        ("EXIT_X = 2\nassert len(lines) == EXIT_X", set()),
        ("код = main([])\nassert код == facts.EXIT_BROKEN", {"EXIT_BROKEN"}),
        ('assert m.EXIT_SILENT not in declared("g.py").values()', set()),
        ('assert m.EXIT_SILENT not in declared("g.py").keys()', set()),
        (
            'from tests.outcomes import declared\nassert m.EXIT_SILENT in declared("g.py")',
            set(),
        ),
        ("assert m.declared(tree) == m.EXIT_FOUND", {"EXIT_FOUND"}),
        (
            'from tests import outcomes\nassert m.EXIT_X in outcomes.declared("g.py")',
            set(),
        ),
        ("assert other.declared(tree) == m.EXIT_FOUND", {"EXIT_FOUND"}),
        ('from tests import outcomes as o\nassert m.EXIT_X in o.declared("g.py")', set()),
        ('from . import outcomes\nassert m.EXIT_X in outcomes.declared("g.py")', set()),
        ('from . import outcomes as o\nassert m.EXIT_X in o.declared("g.py")', set()),
        ('from .outcomes import declared\nassert m.EXIT_X in declared("g.py")', set()),
        ('from tests.outcomes import declared as d\nassert m.EXIT_X in d("g.py")', set()),
        ('from .outcomes import declared as d\nassert m.EXIT_X in d("g.py")', set()),
        ('import tests.outcomes\nassert m.EXIT_X in tests.outcomes.declared("g.py")', set()),
        ('import tests.outcomes as o\nassert m.EXIT_X in o.declared("g.py")', set()),
        ('import tests\nassert m.EXIT_X in tests.outcomes.declared("g.py")', set()),
        ('import tests as t\nassert m.EXIT_X in t.outcomes.declared("g.py")', set()),
        ('from tests.outcomes import *\nassert m.EXIT_X in declared("g.py")', set()),
        ('from .outcomes import *\nassert m.EXIT_X in declared("g.py")', set()),
        ('from tests import other\nassert other.declared("g.py") == m.EXIT_X', {"EXIT_X"}),
        ('assert declared("g.py") == m.EXIT_FOUND', {"EXIT_FOUND"}),
        ('assert outcomes.declared("g.py") == m.EXIT_FOUND', {"EXIT_FOUND"}),
    ],
    ids=[
        "ключ подписки",
        "проза вывода",
        "константа",
        "перечень имён",
        "сверка объявлений",
        "своя константа у счёта",
        "русский код",
        "сверка через values",
        "сверка через keys",
        "сверка через declared",
        "declared механизма",
        "помощник через модуль",
        "declared чужого модуля",
        "помощник под псевдонимом",
        "относительно модулем",
        "относительно модулем под псевдонимом",
        "относительно функцией",
        "функция под псевдонимом",
        "относительно функцией под псевдонимом",
        "import пакета",
        "import под псевдонимом",
        "import пакета без модуля",
        "import пакета под псевдонимом",
        "звёздочка",
        "звёздочка относительно",
        "другой модуль пакета",
        "свой declared теста",
        "outcomes без импорта",
    ],
)
def test_an_outcome_name_counts_as_a_key_not_as_prose(source: str, names: set[str]) -> None:
    """Строка `EXIT_…` засчитывается ключом подписки, а не голой строкой (`bcc5db5`)."""
    assert outcomes.asserted(ast.parse(source))[1] == names
