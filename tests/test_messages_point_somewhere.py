"""Путь, названный сообщением механизма, существует.

Сообщение отказа отправляет читателя КУДА-ТО: «смотрите `scripts/check_env.py`»,
«объявите в `.rules/rerun.json`». Если адрес мёртв, отказ отправляет в никуда —
и хуже того, делает это уверенно: снаружи живой адрес и переименованный
выглядят одинаково
([076](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/076-messages-point-at-what-the-user-actually-has.md)).

ПОЧЕМУ ЭТО РАССЫХАЕТСЯ МОЛЧА. Переименованный механизм чинит свои импорты
сразу — иначе не запустится, — а строку сообщения не чинит ничто: она едет
дальше и продолжает называть прежнее имя. Гейт при этом остаётся зелёным, потому
что проверяет он дерево, а не свою же прозу.

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Путей, названных сообщениями
механизмов, — 47, и все живы. То есть требование исполнялось и держалось
внимательностью: первое же переименование не покраснело бы нигде
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ГРАНИЦЫ НАЗВАНЫ ЗАМЕРОМ, А НЕ ВКУСОМ — обе.

* **Набор в предмет не входит.** Его сообщения называют пути ПОДДЕЛАННОГО
  дерева: `changelog.d/a-theme.added.md` собирается в `tmp_path` и в рабочем
  дереве не существует по построению. Замер: таких 32 из 218, и требовать от
  них существования значило бы красить исправное
  ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
* **Докстрока в предмет не входит.** Она называет несуществующий путь НАРОЧНО —
  когда сама находка в том, что его нет. Замер: таких два, и оба именно такие:
  `tests/test_journal.py` в `check_journal.py` назван как «сторож, которого не
  существует», а `scripts/было.py` — образец переименования
  ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from tests.conftest import ROOT

#: Где живут механизмы: их сообщения читает окно и владелец.
WHERE: Final = ("scripts", "packages/transport", ".claude/hooks")

#: Что считается путём НАШЕГО дерева. Список приставок закрытый: «похоже на
#: путь» приняло бы и чужой адрес, и кусок URL
#: ([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
OURS: Final = (
    "scripts",
    "tests",
    "docs",
    "packages",
    ".github",
    ".rules",
    ".claude",
    "changelog.d",
)
A_PATH: Final = re.compile(
    r"(?<![\w./-])((?:"
    + "|".join(one.replace(".", r"\.") for one in OURS)
    + r")/[\w./-]+\.[a-z]{2,5})"
)


def prose_of(tree: ast.AST) -> set[int]:
    """Докстроки по месту: их путь бывает мёртв нарочно."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def paths_in_messages() -> list[tuple[Path, int, str]]:
    """Пути, названные сообщениями механизмов: файл, строка, адрес."""
    found: list[tuple[Path, int, str]] = []
    for where in WHERE:
        for path in sorted((ROOT / where).glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            prose = prose_of(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in prose:
                    continue
                for said in A_PATH.findall(node.value):
                    found.append((path.relative_to(ROOT), node.lineno, said))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    said = paths_in_messages()
    assert said, "ни одно сообщение механизма не называет пути — сверять нечего"


def test_every_path_named_by_a_message_exists() -> None:
    """Адрес, названный сообщением, ведёт к живому файлу или каталогу.

    Проверяется СУЩЕСТВОВАНИЕ, а не вид: сообщение отправляет и к каталогу
    («положите фрагмент в `changelog.d/`»), и к файлу.
    """
    dead = [
        f"{path}:{line} — «{said}»"
        for path, line, said in paths_in_messages()
        if not (ROOT / said).exists()
    ]
    assert not dead, (
        "сообщение механизма называет путь, которого нет (076):\n  "
        + "\n  ".join(dead)
        + "\n  Механизм переименован или переехал — поправьте сообщение."
        "\n  Если адрес назван НАРОЧНО мёртвым (сама находка в том, что его нет),"
        " ему место в докстроке, а не в сообщении: докстрока из предмета выведена."
    )


def test_a_dead_path_in_prose_is_not_judged() -> None:
    """Граница названа замером: мёртвый путь в докстроке в дереве есть.

    `check_journal.py` называет `tests/test_journal.py` именно затем, чтобы
    сказать «сторожем был назначен адрес, которого не существует». Исчезнет
    такая проза — довод о границе станет пустым, и это увидит проверка, а не
    читатель докстроки
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    prose_paths: list[str] = []
    for where in WHERE:
        for path in sorted((ROOT / where).glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            prose = prose_of(tree)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) in prose
                ):
                    prose_paths += [
                        one for one in A_PATH.findall(node.value) if not (ROOT / one).exists()
                    ]
    assert prose_paths, (
        "в докстроках механизмов нет ни одного намеренно мёртвого адреса — "
        "довод о границе пуст, и докстроку можно вернуть в предмет"
    )
