"""Механизм не сносит правки дерева принудительной сменой ветки (210, взгляд на #1434).

ТРЕТЬЯ НАХОДКА ПО ОДНОМУ МЕСТУ. Смена ветки поверх грязного дерева в
`scripts/deps_intercept.py` чинилась трижды, и каждый раз — у одного вызова:
взгляд на #1421, затем `7f52cb1`, затем возврат в `main`. Вторая находка по
одному месту чинится классом (210), поэтому правило строгое и о форме вызова,
а не о том, проверил ли механизм дерево перед ним.

ПРАВИЛО СТРОГОЕ. Вызов в коде механизмов, среди строковых доводов которого стоит
смена ветки или файлов (`checkout`, `switch`), не несёт `--force`, `-f` и
`--discard-changes`; `reset` не несёт `--hard`; `clean` не зовётся с `-f`.
Чистому дереву принудительность не нужна, а правку, которую проверка механизма
не увидела, git без неё стирать откажется сам.

ГРАНИЦА НАЗВАНА (046). Судятся строковые постоянные вызова — позиционные
доводы и элементы списка или кортежа, — а не собранная на ходу команда:
`[*base, "--force"]` признак видит, имя переменной с ключом — нет. Шаги прогонов
(`.github/`) не судятся: замер 17.10.2026 — `checkout --force`, `reset --hard`
и `clean -f` в `.github/` не встречаются ни разу.
"""

import ast
from typing import Final

import pytest

from tests.conftest import ROOT, code_files

#: Подкоманда git → её принудительные ключи.
FORCED: Final = {
    "checkout": frozenset({"--force", "-f", "--discard-changes"}),
    "switch": frozenset({"--force", "-f", "--discard-changes"}),
    "reset": frozenset({"--hard"}),
    "clean": frozenset({"-f", "--force", "-fd", "-fdx", "-xdf", "-df"}),
}


def words(call: ast.Call) -> list[str]:
    """Строковые постоянные вызова: позиционные доводы и элементы списков в них."""
    found: list[str] = []
    for arg in call.args:
        items = arg.elts if isinstance(arg, ast.List | ast.Tuple) else [arg]
        for item in items:
            inner = item.value if isinstance(item, ast.Starred) else item
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                found.append(inner.value)
    return found


def forced(source: str) -> list[int]:
    """Строки вызовов, где смена ветки или файлов несёт принудительный ключ."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        said = set(words(node))
        if any(command in said and said & keys for command, keys in FORCED.items()):
            found.append(node.lineno)
    return sorted(found)


def test_no_mechanism_switches_by_force() -> None:
    """В коде механизмов — всё, что обходит `code_files`, — смена ветки не стирает правок силой."""
    found = {
        path.relative_to(ROOT).as_posix(): lines
        for path in code_files()
        if (lines := forced(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"принудительная смена ветки или файлов стёрла бы правки дерева: {found} — "
        "проверьте `git status --porcelain` и переключайте без силы (210)"
    )


def test_the_gate_has_a_subject() -> None:
    """Предмет есть: механизмы вообще зовут `checkout` (075)."""
    assert any(
        "checkout" in words(node)
        for path in code_files()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
    ), "вызовов checkout в коде механизмов нет — признак смотрит не туда"


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        ('git(root, "checkout", "--quiet", "--force", "-B", "b", "origin/main")', True),
        ('run(["git", "switch", "-f", "b"])', True),
        ('run(["git", "reset", "--hard", "origin/main"])', True),
        ('run(["git", "clean", "-fdx"])', True),
        ('run([*base, "checkout", "--discard-changes"])', True),
        ('git(root, "checkout", "--quiet", "-B", "b", "origin/main")', False),
        ('git(root, "checkout", "--quiet", "--detach", "origin/main")', False),
        ('run(["git", "reset", "--soft", "HEAD~1"])', False),
        ('run(["git", "push", "--force-with-lease"])', False),
    ],
    ids=[
        "checkout-force",
        "switch-f",
        "reset-hard",
        "clean-f",
        "звёздочка",
        "без-силы",
        "отвязка",
        "мягкий-reset",
        "толчок",
    ],
)
def test_the_sign_tells_force_from_a_plain_switch(source: str, bad: bool) -> None:
    """Обе половины признака: сила видна в любой форме записи, обычная смена — нет."""
    assert bool(forced(source)) is bad
