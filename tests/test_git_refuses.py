"""Вызов git в механизме без git на пути — отказ, а не трасса (039, 045, #1027).

Взгляд дважды находил одну беду у разных соседей: `subprocess.run(["git", …])`
без `OSError`, то есть падение трассой вместо третьего исхода. На #1008 —
`release.git` и `window.git`, на #1021 — `items_left` и `review_map`. Вторая
находка по одному месту останавливает починку по одной форме (210): круг рвёт
это правило, а не следующая правка.

ПРАВИЛО СТРОГОЕ. Функция в `scripts/`, которая зовёт `subprocess.run` или
`subprocess.check_output` со списком, начинающимся буквой `"git"`, ловит
`OSError` (или его наследника `FileNotFoundError`) В ТОЙ ЖЕ ФУНКЦИИ. Общий
вызов `gitcall.output` так и делает. Поимка выше, у вызывающего, законной не
считается: она живёт в другом месте и уезжает от вызова молча.

СОСЕД ЗА ГРАНИЦЕЙ (195): вызов, чья команда не литерал-список с `"git"`
первым словом (`journal.git` берёт команду целиком), предикат не судит —
он не знает, что зовётся git. Такой вызов ловит `OSError` сам, и держит это
чтение, а не гейт.

ЗАМЕР 01.10.2026 (#1027): функций с вызовом git без `OSError` было 19 в 11
модулях; восемь сняты в #1021, одиннадцать — изменением этого гейта.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, walk

#: Классы, поимка которых означает «без git на пути — свой исход».
CATCHES: Final = frozenset({"OSError", "FileNotFoundError", "Exception"})
#: Вызовы процесса, которые судятся.
RUNS: Final = frozenset({"subprocess.run", "subprocess.check_output"})


def calls_git(call: ast.Call) -> bool:
    """Вызов процесса, чья команда — литерал-список с `"git"` первым словом."""
    if ast.unparse(call.func) not in RUNS or not call.args:
        return False
    command = call.args[0]
    return (
        isinstance(command, ast.List)
        and bool(command.elts)
        and isinstance(command.elts[0], ast.Constant)
        and command.elts[0].value == "git"
    )


def caught(function: ast.FunctionDef) -> set[str]:
    """Имена классов, которые ловит хоть один `except` этой функции."""
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            kinds = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            names |= {ast.unparse(one).rsplit(".", 1)[-1] for one in kinds}
    return names


def unguarded(source: str) -> list[str]:
    """Функции исходника, что зовут git и не ловят его отсутствие у себя."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        calls = any(isinstance(one, ast.Call) and calls_git(one) for one in ast.walk(node))
        if calls and not caught(node) & CATCHES:
            found.append(f"{node.name}:{node.lineno}")
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
    ],
    ids=["без поимки", "OSError", "кортеж с OSError", "только CalledProcessError", "не git"],
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
