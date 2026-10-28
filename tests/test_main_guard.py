"""Вход механизма: трасса — исход отказа, а не код 1 «нашёл» (#1720).

Обе половины: обёртка отдаёт исход `main` и превращает исключение в отказ с
трассой; гейт обходит все скрипты и краснеет на механизме с исходом 1, чей
вход идёт мимо обёртки.
"""

import ast
from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script, walk
from tests.test_settings_anchor import STANDS_ALONE

module = load_script("main_guard.py")


def test_the_outcome_of_main_passes_through() -> None:
    """Исход `main` — как есть, обёртка его не трогает."""
    assert module.run(lambda: 1, 2) == 1
    assert module.run(lambda: 0, 2) == 0


def test_an_exception_is_the_broken_outcome(capsys: pytest.CaptureFixture[str]) -> None:
    """Исключение — исход отказа, трасса и слова «не находка» в stderr (039)."""

    def boom() -> int:
        empty: dict[str, int] = {}
        return empty["нет"]

    assert module.run(boom, 2) == 2
    said = capsys.readouterr().err
    assert "KeyError" in said and "не находка" in said
    assert module.run(boom, 3, "сторож: не находка о запасе") == 3
    assert "сторож: не находка о запасе" in capsys.readouterr().err


def test_a_system_exit_is_not_swallowed() -> None:
    """`SystemExit` — решение самого механизма (выход `argparse`), он не ловится."""

    def leave() -> int:
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        module.run(leave, 2)


def finds_with_one(tree: ast.Module) -> bool:
    """Объявлен ли на уровне модуля исход `EXIT_*` с кодом 1 — «нашёл»."""
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        value = getattr(node, "value", None)
        if (
            isinstance(target, ast.Name)
            and target.id.startswith("EXIT_")
            and isinstance(value, ast.Constant)
            and value.value == 1
        ):
            return True
    return False


def enters_through_the_guard(tree: ast.Module) -> bool:
    """Вход `__main__` зовёт `main_guard.run` сам или через функцию модуля, которая его зовёт."""

    def calls_run(node: ast.AST) -> bool:
        return any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "run"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "main_guard"
            for call in ast.walk(node)
        )

    guards = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef) and calls_run(node)
    }
    for node in tree.body:
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            called = {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            return calls_run(node) or bool(called & guards)
    return True


def guards_itself(tree: ast.Module) -> bool:
    """Вход `__main__` ловит любое исключение сам — так защищается модуль-одиночка."""
    for node in tree.body:
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            return any(
                isinstance(handler, ast.ExceptHandler)
                and isinstance(handler.type, ast.Name)
                and handler.type.id == "Exception"
                for handler in ast.walk(node)
            )
    return False


def unguarded(root: Path, alone: frozenset[str] = frozenset()) -> list[str]:
    """Механизмы с исходом 1, чей вход идёт мимо `main_guard.run`.

    Модуль-одиночка (`alone`) нашего не импортирует: его вход защищается сам.
    """
    found = []
    for path in walk(root / "scripts", "*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not finds_with_one(tree):
            continue
        guarded = guards_itself(tree) if path.name in alone else enters_through_the_guard(tree)
        if not guarded:
            found.append(path.name)
    return sorted(found)


def test_every_mechanism_with_a_finding_enters_through_the_guard() -> None:
    """Всякий механизм с исходом 1 входит через `main_guard.run` (#1720).

    Мерка 28.10.2026: таких механизмов 36, вход под защитой был у одного.
    ГРАНИЦА НАЗВАНА: исход, объявленный не константой `EXIT_*` модуля, обход не видит.
    """
    scripts = walk(ROOT / "scripts", "*.py")
    counted = [p for p in scripts if finds_with_one(ast.parse(p.read_text(encoding="utf-8")))]
    assert len(counted) > 30, "механизмов с исходом 1 не найдено — гейт доказывал бы только себя"
    assert unguarded(ROOT, frozenset(STANDS_ALONE)) == []


def test_the_gate_reds_on_a_bare_entry(tmp_path: Path) -> None:
    """Голый `raise SystemExit(main())` у механизма с исходом 1 — отказ гейта."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x.py").write_text(
        "EXIT_FOUND = 1\ndef main() -> int:\n    return 0\n"
        'if __name__ == "__main__":\n    raise SystemExit(main())\n',
        encoding="utf-8",
    )
    assert unguarded(tmp_path) == ["x.py"]


def test_a_standing_alone_module_must_guard_itself(tmp_path: Path) -> None:
    """Одиночке обёртка не положена — но голый вход и у неё отказ гейта."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x.py").write_text(
        "EXIT_FOUND = 1\ndef main() -> int:\n    return 0\n"
        'if __name__ == "__main__":\n    raise SystemExit(main())\n',
        encoding="utf-8",
    )
    assert unguarded(tmp_path, frozenset({"x.py"})) == ["x.py"]
