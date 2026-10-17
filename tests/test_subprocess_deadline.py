"""Вызов процесса в механизме несёт дедлайн и ловит его истечение (100, 220, #1439).

ПРЕДМЕТ — МЕХАНИЗМ, А НЕ ПРОГОН. Ответ по 100 называл дедлайны прогонов
(`timeout-minutes`) и опрос `ci_complete`, а сами гейты звали процессы без
предела: замер 17.10.2026 по `scripts/`, `packages/transport/` и
`.claude/hooks/` — 21 вызов в 15 файлах. Зависший `git` или `bash` держал
гейт до предела площадки, и красное приходило через сорок минут причиной
«превышено время», а не названным отказом. Правило 220: охват мета-гейта —
все механизмы дерева, а не место рождения правила.

ПРАВИЛО СТРОГОЕ, И У НЕГО ДВЕ ПОЛОВИНЫ. Вызов процесса (`run`,
`check_output`, `check_call`, `call` — по имени, с `subprocess.` или без)
несёт довод `timeout=`, И стоит в теле `try`, чей обработчик ловит
`TimeoutExpired` (или его предка `SubprocessError`, или `Exception`).
Дедлайн без поимки менял бы зависание на трассу с кодом 1 — то же
нарушение третьего исхода (039), только быстрее.

`Popen` ДЕДЛАЙНА В ВЫЗОВЕ НЕ БЕРЁТ — у него `communicate(timeout=)`, — и
предикат его отвергает целиком: сегодня таких вызовов ноль, и первый
появится вместе с решением, как его судить (075).

ТЕЛО `try` — ТО, ЧТО ИСПОЛНЯЕТСЯ В НЁМ (находка `f7d1815`). Вызов внутри
`def`, `lambda` или `class`, вложенных в тело, исполнится позже и вне этого
`try`: такой вызов поимкой внешнего блока не считается. Предел назван: довод
по умолчанию и декоратор вложенного `def` исполняются при определении, то есть
в `try`, — их предикат тоже не засчитывает, и это строгость, а не дыра.

МОДУЛЬ ПОД ДРУГИМ ИМЕНЕМ — ТОТ ЖЕ МОДУЛЬ (находка `bde3e93`): `import
subprocess as sp` даёт `sp.run`, и предикат его видит наравне с
`from subprocess import run as r`.

СОСЕД ЗА ГРАНИЦЕЙ (195): вызов через переменную-псевдоним (`spawn =
subprocess.run`) и `os.system` предикат не видит. Набор `tests/` не судится:
это не механизм, а его проверка, и предел ей ставит площадка.

КОРНИ — ОДИН СПИСОК (находка `5a5a96a`, правило 071): механизмы — это
`code_files(with_hooks=True)`, то есть `paths.SOURCES` и хуки окна, обходом
по `git ls-files`, а не свой каталог хуков рядом.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, code_files

#: Вызовы процесса, которые судятся, — по имени, как у `tests/test_git_refuses.py`.
SPAWNS: Final = frozenset({"run", "check_output", "check_call", "call", "Popen"})
#: Поимка, означающая «истёк дедлайн — свой исход».
CATCHES: Final = frozenset({"TimeoutExpired", "SubprocessError", "Exception"})
#: Узлы, тело которых исполняется не там, где написано, — вне объемлющего `try`.
SCOPES: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def mechanisms() -> list[Path]:
    """Код механизмов: источники проекта и хуки окна (220) — одним списком корней."""
    return code_files(with_hooks=True)


def spawned_name(func: ast.expr) -> str:
    """Имя вызываемого: `subprocess.run` и `run` из импорта — одно имя."""
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def is_spawn(call: ast.Call, imported: set[str], modules: frozenset[str] = frozenset()) -> bool:
    """Вызов процесса: атрибут модуля `subprocess` (под любым именем) или имя, взятое из него."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr in SPAWNS
            and isinstance(func.value, ast.Name)
            and func.value.id in {"subprocess", *modules}
        )
    return isinstance(func, ast.Name) and func.id in imported


def executed(statement: ast.AST) -> list[ast.AST]:
    """Узлы, исполняемые там, где написан `statement`: в тела `def`, `lambda`, `class` не входит."""
    found: list[ast.AST] = []
    todo = [statement]
    while todo:
        node = todo.pop()
        found.append(node)
        if not isinstance(node, SCOPES):
            todo.extend(ast.iter_child_nodes(node))
    return found


def caught(block: ast.Try) -> set[str]:
    """Имена классов, которые ловят обработчики этого `try`."""
    names: set[str] = set()
    for handler in block.handlers:
        if handler.type is not None:
            kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            names |= {ast.unparse(one).rsplit(".", 1)[-1] for one in kinds}
    return names


def guarded(tree: ast.AST) -> set[int]:
    """Узлы в ТЕЛЕ `try` с поимкой истёкшего дедлайна — не в обработчике и не после."""
    inside: set[int] = set()
    for block in ast.walk(tree):
        if isinstance(block, ast.Try) and caught(block) & CATCHES:
            inside |= {id(node) for statement in block.body for node in executed(statement)}
    return inside


def undeadlined(source: str) -> list[str]:
    """Вызовы процесса исходника без дедлайна или без поимки его истечения."""
    tree = ast.parse(source)
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess"
        for alias in node.names
        if alias.name in SPAWNS
    }
    modules = frozenset(
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "subprocess" and alias.asname
    )
    safe = guarded(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and is_spawn(node, imported, modules)):
            continue
        if spawned_name(node.func) == "Popen":
            found.append(f"{node.lineno}: Popen — дедлайн не в вызове")
        elif not any(word.arg == "timeout" for word in node.keywords):
            found.append(f"{node.lineno}: без timeout=")
        elif id(node) not in safe:
            found.append(f"{node.lineno}: TimeoutExpired не пойман")
    return found


def test_every_spawn_has_a_deadline_and_catches_it() -> None:
    """Каждый вызов процесса в механизмах несёт `timeout=` и ловит его истечение."""
    found = {
        path.relative_to(ROOT).as_posix(): bad
        for path in mechanisms()
        if (bad := undeadlined(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"вызов процесса без дедлайна или без его поимки (100, 039): {found}. "
        "Назовите timeout= и ловите subprocess.TimeoutExpired тем же исходом, что OSError"
    )


def test_the_predicate_sees_spawns_in_the_tree() -> None:
    """У гейта есть предмет: вызовы процесса в механизмах есть (075)."""
    seen = sum(
        is_spawn(node, set())
        for path in mechanisms()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
    )
    assert seen > 10, f"вызовов процесса найдено {seen} — предикат смотрит не туда"


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        (
            "import subprocess\ntry:\n    subprocess.run(['x'], timeout=5)\n"
            "except subprocess.TimeoutExpired:\n    pass\n",
            False,
        ),
        (
            "import subprocess\ntry:\n    subprocess.run(['x'], timeout=5)\n"
            "except (OSError, subprocess.SubprocessError):\n    pass\n",
            False,
        ),
        ("import subprocess\ntry:\n    subprocess.run(['x'])\nexcept Exception:\n    pass\n", True),
        ("import subprocess\nsubprocess.run(['x'], timeout=5)\n", True),
        (
            "import subprocess\ntry:\n    subprocess.run(['x'], timeout=5)\n"
            "except OSError:\n    pass\n",
            True,
        ),
        ("from subprocess import check_output as co\nco(['x'])\n", True),
        ("import subprocess\nsubprocess.Popen(['x'])\n", True),
        ("import re\nre.compile('x').search('y')\nrun = 1\n", False),
        (
            "import subprocess\ntry:\n    def later():\n        subprocess.run(['x'], timeout=5)\n"
            "except subprocess.TimeoutExpired:\n    pass\n",
            True,
        ),
        (
            "import subprocess\ntry:\n    f = lambda: subprocess.run(['x'], timeout=5)\n"
            "except subprocess.TimeoutExpired:\n    pass\n",
            True,
        ),
        (
            "import subprocess\ndef later():\n    try:\n        subprocess.run(['x'], timeout=5)\n"
            "    except subprocess.TimeoutExpired:\n        pass\n",
            False,
        ),
        ("import subprocess as sp\nsp.run(['x'], timeout=5)\n", True),
        (
            "import subprocess as sp\ntry:\n    sp.run(['x'], timeout=5)\n"
            "except sp.TimeoutExpired:\n    pass\n",
            False,
        ),
    ],
    ids=[
        "дедлайн и поимка",
        "предок в кортеже",
        "поимка без дедлайна",
        "дедлайн без поимки",
        "поимка не того класса",
        "импорт под другим именем",
        "Popen",
        "не процесс",
        "def-в-теле-try",
        "lambda-в-теле-try",
        "try-внутри-def",
        "модуль-под-другим-именем",
        "модуль-под-другим-именем-пойман",
    ],
)
def test_the_predicate_has_both_halves(source: str, bad: bool) -> None:
    """Гейт ловит и пропуск дедлайна, и пропуск поимки — и не трогает чужое."""
    assert bool(undeadlined(source)) is bad
