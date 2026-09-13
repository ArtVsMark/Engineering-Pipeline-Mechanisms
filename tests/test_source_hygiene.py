"""Три дефекта, которые не видны ни в обзоре, ни в зелёном прогоне.

Общее у них одно: каждый молча превращает проверку в ничто, оставляя её
зелёной. Путь с пробелом выпадает из списка, потому что git его экранировал;
условие на переменной с не-ASCII именем всегда идёт одной веткой, потому что
подстановка пуста; кодировка вывода берётся у локали раннера, и разбор ломается
только на подходящих данных.

Правила каталога: 165 (список путей читают по NUL и называют охват), 167 (имена
переменных оболочки — латиницей), 176 (умолчание, взятое из окружения, задаётся
явно).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

#: Команды git, отдающие СПИСОК ПУТЕЙ для последующего чтения.
PATH_LISTING = ("--name-only", "--name-status", "ls-files", "diff-tree")

#: Присваивание в оболочке: имя до знака равенства.
SHELL_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([^\s=]+)=", re.M)


def calls(path: Path) -> list[ast.Call]:
    """Вызовы, встреченные в файле."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def keyword_of(call: ast.Call, name: str) -> ast.keyword | None:
    """Именованный аргумент вызова, если он задан."""
    return next((kw for kw in call.keywords if kw.arg == name), None)


def literals(call: ast.Call) -> list[str]:
    """Строковые литералы среди позиционных аргументов вызова, включая списки."""
    found: list[str] = []
    for argument in call.args:
        items = argument.elts if isinstance(argument, ast.List | ast.Tuple) else [argument]
        found += [
            item.value
            for item in items
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_subprocess_text_names_its_encoding(path: Path) -> None:
    """`text=True` без `encoding` берёт кодировку у локали раннера (176).

    Матрица прогонов этого не доказывает: дефект требует совпадения ячейки и
    данных, и зелёное говорит «совпадения не случилось», а не «задано верно».
    """
    for call in calls(path):
        text = keyword_of(call, "text")
        if text is None or not (isinstance(text.value, ast.Constant) and text.value.value is True):
            continue
        assert keyword_of(call, "encoding") is not None, (
            f"{path.name}:{call.lineno}: text=True без encoding — кодировка приходит из окружения"
        )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_git_path_lists_are_read_by_nul(path: Path) -> None:
    """Список путей из git запрашивается с `-z` (165).

    Без него имена с пробелами и не-ASCII приходят экранированными, путь не
    разрешается, и файл выпадает из обработки молча.
    """
    for call in calls(path):
        arguments = literals(call)
        if not any(marker in arguments for marker in PATH_LISTING):
            continue
        assert "-z" in arguments, f"{path.name}:{call.lineno}: список путей из git читается без -z"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_path_lists_are_read_by_nul(path: Path) -> None:
    """То же требование к спискам путей, запрошенным прямо в шаге прогона (165)."""
    text = path.read_text(encoding="utf-8")
    bad = [
        line.strip()
        for line in text.splitlines()
        if "git " in line and any(marker in line for marker in PATH_LISTING) and " -z" not in line
    ]
    assert not bad, f"{path.name}: список путей из git без -z: {bad}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_shell_variable_names_are_ascii(path: Path) -> None:
    """Имя переменной оболочки — ASCII, даже если проект ведётся не на латинице (167).

    Опаснее не падение с кодом 127, а тихий случай: переменная окружения с
    не-ASCII именем создаётся штатно, `$ИМЯ` не раскрывается вовсе, и условие
    на ней всегда идёт одной веткой при зелёном гейте.
    """
    names = SHELL_ASSIGN_RE.findall(path.read_text(encoding="utf-8"))
    bad = [name for name in names if not name.isascii()]
    assert not bad, f"{path.name}: имя переменной оболочки не на латинице: {bad}"


def sleeping(tree: ast.AST) -> list[ast.FunctionDef]:
    """Функции, в которых есть ожидание — `time.sleep`."""
    found: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "sleep"
            ):
                found.append(node)
                break
    return found


#: Слова, которыми в этом дереве называется срок ожидания. Список
#: РАЗРЕШИТЕЛЬНЫЙ: новое имя срока не проходит молча, а дописывается сюда (068).
DEADLINE_WORDS = ("deadline", "timeout", "tries", "until")


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_every_wait_has_a_deadline(path: Path) -> None:
    """У всякого ожидания есть срок: цикл без него ждёт до конца прогона.

    Правило 100. Ожидание без срока снаружи неотличимо от зависшего механизма:
    прогон стоит, лога нет, и единственное, что его кончает, — предел времени
    самой площадки, который скажет «job timed out», а не что ждали и чего не
    дождались.

    Сроком считается любое из названных слов в той же функции: заход, который
    спит, обязан знать, когда перестать.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in sleeping(tree):
        said = ast.dump(node)
        assert any(word in said for word in DEADLINE_WORDS), (
            f"{path.name}: «{node.name}» ждёт, но срока не называет — "
            "ожидание без срока неотличимо от зависшего механизма (100)"
        )


def env_defaults(tree: ast.AST) -> list[tuple[int, str]]:
    """Умолчания, подставляемые вместо непрочитанного окружения.

    Считаются обе формы: второй довод `os.environ.get(…, «что-то»)` и правая
    часть `os.environ.get(…) or «что-то»`. Форма разная, смысл один — тихая
    подстановка, и разбор, знающий одну, дал бы уверенность на половине
    дерева.
    """
    found: list[tuple[int, str]] = []

    def is_env(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
        )

    def said_of(node: ast.expr) -> str:
        return str(node.value) if isinstance(node, ast.Constant) else ""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and is_env(node)
            and len(node.args) > 1
            and said_of(node.args[1]).strip()
        ):
            found.append((node.lineno, said_of(node.args[1])))
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for left, right in zip(node.values, node.values[1:], strict=False):
                if is_env(left) and said_of(right).strip():
                    found.append((node.lineno, said_of(right)))
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_an_environment_default_is_declared_not_inlined(path: Path) -> None:
    """Умолчание вместо непрочитанного окружения — объявленная константа, не литерал.

    Правило 176: умолчание из окружения — скрытая зависимость от площадки. Пока
    оно стоит литералом в строке, у него нет имени, а значит нет и места, где
    сказано, ПОЧЕМУ именно это значение. Замер: имя общей ветки жило в дереве
    тремя написаниями сразу — `"main"`, `TRUNK` и `DEFAULT_BRANCH`, — и
    переименование ветки чинилось бы поиском по строке.

    Пустая строка умолчанием не считается: она означает «не задано» и ведёт к
    отказу, а не к тихой подстановке.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    said = env_defaults(tree)
    assert not said, (
        f"{path.name}: умолчание окружения литералом — "
        + ", ".join(f"строка {line}: «{value}»" for line, value in said)
        + " — дайте ему имя (176)"
    )
