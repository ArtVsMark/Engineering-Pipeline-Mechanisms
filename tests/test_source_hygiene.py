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
