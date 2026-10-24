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

СИЛА СУДИТСЯ В ЛЮБОЙ ЗАПИСИ, КОТОРУЮ ПРИМЕТ GIT (взгляд на #1468). Склеенные
ключи прежде перечислялись поштучно, и `clean -xf`, `-dfx`, `-ffd` или
`checkout -fB` проходили гейт. Теперь короткая склейка разбирается по буквам —
до первой буквы, которая берёт довод (`-Bf` — ветка с именем `f`, а не сила), —
а длинный ключ узнаётся и сокращённым: git принимает однозначный префикс
(`git help cli`), поэтому `--forc` — та же сила, что `--force`.

ГРАНИЦА НАЗВАНА (046). Судятся строковые постоянные вызова — позиционные
доводы и элементы списка или кортежа, — а не собранная на ходу команда:
`[*base, "--force"]` признак видит, имя переменной с ключом — нет. Шаги прогонов
(`.github/`) не судятся: замер 17.10.2026 — `checkout --force`, `reset --hard`
и `clean -f` в `.github/` не встречаются ни разу.

СОСЕДИ БЕЗ КЛЮЧА СИЛЫ НЕ СУДЯТСЯ — ЭТО ГРАНИЦА (195, взгляды на #1468 и #1474).
Правки стирают и вызовы, которым сила не нужна вовсе: `checkout -- <путь>`,
`restore <путь>` и `stash drop`. Гейт судит запись силы, а не исход, и эти
вызовы назвал бы чистыми. Замер 24.10.2026: в `scripts/`, `packages/` и
хуках окна таких вызовов 0 — это граница, а не дефект.
"""

import ast
from dataclasses import dataclass
from typing import Final

import pytest

from tests.conftest import ROOT, code_files


@dataclass(frozen=True)
class Force:
    """Как подкоманда git пишет силу: длинные ключи, буква в склейке, буквы с доводом."""

    long: frozenset[str]
    letter: str = ""
    valued: frozenset[str] = frozenset()


#: Подкоманда git → как она пишет силу. Буквы с доводом взяты из справки
#: подкоманды: после них остаток склейки — значение, а не ключи.
FORCED: Final = {
    "checkout": Force(frozenset({"--force", "--discard-changes"}), "f", frozenset("bB")),
    "switch": Force(frozenset({"--force", "--discard-changes"}), "f", frozenset("cC")),
    "reset": Force(frozenset({"--hard"})),
    "clean": Force(frozenset({"--force"}), "f", frozenset("e")),
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


def forces(force: Force, word: str) -> bool:
    """Пишет ли слово силу: длинным ключом, его сокращением или буквой в склейке."""
    if word.startswith("--"):
        return len(word) > 2 and any(key.startswith(word) for key in force.long)
    if not word.startswith("-") or not force.letter:
        return False
    for letter in word[1:]:
        if letter == force.letter:
            return True
        if letter in force.valued:
            return False
    return False


def forced(source: str) -> list[int]:
    """Строки вызовов, где смена ветки или файлов несёт принудительный ключ."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        said = words(node)
        if any(
            command in said and any(forces(force, word) for word in said)
            for command, force in FORCED.items()
        ):
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
        ('run(["git", "clean", "-xf"])', True),
        ('run(["git", "clean", "-dfx"])', True),
        ('run(["git", "clean", "-ffd"])', True),
        ('git(root, "checkout", "-fB", "b", "origin/main")', True),
        ('git(root, "switch", "-qf", "b")', True),
        ('git(root, "checkout", "--forc", "b")', True),
        ('run(["git", "reset", "--ha", "origin/main"])', True),
        ('git(root, "checkout", "--quiet", "-B", "b", "origin/main")', False),
        ('git(root, "checkout", "--quiet", "--detach", "origin/main")', False),
        ('git(root, "checkout", "--quiet", "start", "--")', False),
        ('git(root, "checkout", "-Bf", "origin/main")', False),
        ('run(["git", "clean", "-efoo", "-n"])', False),
        ('run(["git", "reset", "--soft", "HEAD~1"])', False),
        ('run(["git", "push", "--force-with-lease"])', False),
    ],
    ids=[
        "checkout-force",
        "switch-f",
        "reset-hard",
        "clean-f",
        "звёздочка",
        "clean-xf",
        "clean-dfx",
        "clean-ffd",
        "checkout-fB",
        "switch-qf",
        "сокращение-длинного",
        "сокращение-hard",
        "без-силы",
        "отвязка",
        "возврат-на-место",
        "ветка-по-имени-f",
        "образец-с-буквой-f",
        "мягкий-reset",
        "толчок",
    ],
)
def test_the_sign_tells_force_from_a_plain_switch(source: str, bad: bool) -> None:
    """Обе половины признака: сила видна в любой форме записи, обычная смена — нет."""
    assert bool(forced(source)) is bad
