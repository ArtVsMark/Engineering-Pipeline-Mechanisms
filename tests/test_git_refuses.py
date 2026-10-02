"""Вызов git в механизме без git на пути — отказ, а не трасса (039, 045, #1027).

Взгляд дважды находил одну беду у разных соседей: `subprocess.run(["git", …])`
без `OSError`, то есть падение трассой вместо третьего исхода. На #1008 —
`release.git` и `window.git`, на #1021 — `items_left` и `review_map`. Вторая
находка по одному месту останавливает починку по одной форме (210): круг рвёт
это правило, а не следующая правка.

ПРАВИЛО СТРОГОЕ. Вызов процесса в `scripts/` со списком, начинающимся словом
`"git"`, стоит В ТЕЛЕ `try`, чей обработчик ловит `OSError` (или его
наследника `FileNotFoundError`). Общий вызов `gitcall.output` так и делает.
Поимка выше, у вызывающего, законной не считается: она живёт в другом месте и
уезжает от вызова молча. Не считается и поимка где-то в той же функции, если
вызова она не обнимает.

ВЫЗОВ ПРОЦЕССА — ПО ИМЕНИ, А НЕ ПО ЗАПИСИ. `run`, `check_output`,
`check_call`, `call`, `Popen` — и через `subprocess.`, и импортом напрямую.
Первая редакция судила только `subprocess.run` и `subprocess.check_output`, а
поимку засчитывала у любого `except` функции. Взгляд на #1030 нашёл обе
дыры сразу — вторая находка по тому же предикату (210), поэтому вместо
седьмой формы разбора правило стало строже. Строгое правило нашло в дереве
два вызова, которые прежнее пропускало: `check_rule_links.links` ловил
`OSError` у чтения файла, а не у git, и `preflight.push_branch` — у соседнего
шага.

ПОДПИСАННЫХ ИСКЛЮЧЕНИЙ НЕТ, И ЭТО ЗАМЕР, А НЕ ЗАБЫВЧИВОСТЬ. Задача
допускала обход с подписью рядом, как `SIGNED` у 071, — но ни одному из
одиннадцати мест он не понадобился: у всех нашлась поимка на месте. Список
подписей без единой записи доказывал бы только себя (075), поэтому он не
заведён. Понадобится — заводится вместе с первой записью.

СОСЕД ЗА ГРАНИЦЕЙ (195): вызов, чья команда не литерал-список с `"git"`
первым словом (`journal.git` берёт команду целиком), предикат не судит —
он не знает, что зовётся git. Не судит он и вызов через переменную-псевдоним
(`spawn = subprocess.run`). Такой вызов ловит `OSError` сам, и держит это
чтение, а не гейт.

ЗАМЕР 01.10.2026 (#1027): функций с вызовом git без `OSError` было 19 в 11
модулях; восемь сняты в #1021, одиннадцать — изменением этого гейта.
Строгое правило (см. выше) нашло ещё два — итого тринадцать мест в десяти
модулях.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, walk

#: Классы, поимка которых означает «без git на пути — свой исход».
CATCHES: Final = frozenset({"OSError", "FileNotFoundError", "Exception"})
#: Вызовы процесса, которые судятся, — по имени, с `subprocess.` или без.
SPAWNS: Final = frozenset({"run", "check_output", "check_call", "call", "Popen"})


def spawned_name(func: ast.expr) -> str:
    """Имя вызываемого: `subprocess.run` и `run` из импорта — одно имя."""
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def calls_git(call: ast.Call) -> bool:
    """Вызов процесса, чья команда — литерал-список с `"git"` первым словом."""
    if spawned_name(call.func) not in SPAWNS or not call.args:
        return False
    command = call.args[0]
    return (
        isinstance(command, ast.List)
        and bool(command.elts)
        and isinstance(command.elts[0], ast.Constant)
        and command.elts[0].value == "git"
    )


def caught(block: ast.Try) -> set[str]:
    """Имена классов, которые ловят обработчики этого `try`."""
    names: set[str] = set()
    for handler in block.handlers:
        if handler.type is not None:
            kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            names |= {ast.unparse(one).rsplit(".", 1)[-1] for one in kinds}
    return names


def guarded(function: ast.FunctionDef) -> set[int]:
    """Узлы, стоящие в ТЕЛЕ `try` с поимкой отсутствия git, — не в обработчике и не после."""
    inside: set[int] = set()
    for block in ast.walk(function):
        if isinstance(block, ast.Try) and caught(block) & CATCHES:
            inside |= {id(node) for statement in block.body for node in ast.walk(statement)}
    return inside


def unguarded(source: str) -> list[str]:
    """Вызовы git исходника, которых не обнимает поимка их отсутствия."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        safe = guarded(node)
        found += [
            f"{node.name}:{one.lineno}"
            for one in ast.walk(node)
            if isinstance(one, ast.Call) and calls_git(one) and id(one) not in safe
        ]
    return found


def test_every_git_call_refuses_without_git() -> None:
    """Каждая функция `scripts/`, зовущая git, ловит его отсутствие у себя."""
    found = {
        path.name: bad
        for path in walk(ROOT / "scripts", "*.py")
        if (bad := unguarded(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"вызов git без OSError — без git на пути механизм упадёт трассой (039): {found}. "
        "Зовите `gitcall.output` или ловите OSError в той же функции"
    )


def test_the_predicate_sees_git_calls_in_the_tree() -> None:
    """У гейта есть предмет: вызовы git в `scripts/` есть (075)."""
    seen = 0
    for path in walk(ROOT / "scripts", "*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen += sum(1 for one in ast.walk(tree) if isinstance(one, ast.Call) and calls_git(one))
    assert seen, "вызовов git в scripts/ не найдено — предикат не про то"


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        ('import subprocess\ndef f():\n    subprocess.run(["git", "log"])\n', True),
        (
            "import subprocess\ndef f():\n    try:\n"
            '        subprocess.run(["git", "log"])\n    except OSError:\n        pass\n',
            False,
        ),
        (
            "import subprocess\ndef f():\n    try:\n"
            '        subprocess.run(["git", "log"])\n'
            "    except (OSError, subprocess.CalledProcessError):\n        pass\n",
            False,
        ),
        (
            "import subprocess\ndef f():\n    try:\n"
            '        subprocess.run(["git", "log"])\n'
            "    except subprocess.CalledProcessError:\n        pass\n",
            True,
        ),
        ('import subprocess\ndef f():\n    subprocess.run(["tar", "-x"])\n', False),
        (
            "import subprocess\ndef f():\n"
            '    subprocess.run(["git", "log"])\n'
            "    try:\n        open('x')\n    except OSError:\n        pass\n",
            True,
        ),
        (
            "import subprocess\ndef f():\n    try:\n        pass\n    except OSError:\n"
            '        subprocess.run(["git", "log"])\n',
            True,
        ),
        ('from subprocess import run\ndef f():\n    run(["git", "log"])\n', True),
        ('import subprocess\ndef f():\n    subprocess.Popen(["git", "log"])\n', True),
        ('import subprocess\ndef f():\n    subprocess.check_call(["git", "log"])\n', True),
    ],
    ids=[
        "без поимки",
        "OSError",
        "кортеж с OSError",
        "только CalledProcessError",
        "не git",
        "OSError рядом, а не вокруг",
        "вызов в обработчике",
        "run импортом",
        "Popen",
        "check_call",
    ],
)
def test_the_predicate_has_both_halves(source: str, bad: bool) -> None:
    """Обе половины: незащищённый вызов краснеет, защищённый и чужой — нет."""
    assert bool(unguarded(source)) is bad


def test_a_converted_module_refuses_without_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Прогоном, а не только чтением: без git на пути — отказ модуля (139)."""
    from tests.conftest import load_script

    reread = load_script("check_reread.py")
    monkeypatch.setenv("PATH", "")
    with pytest.raises(reread.NotRun, match=r"^git show "):
        reread.at("HEAD", "x.json")
