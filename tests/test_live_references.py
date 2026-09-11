"""Ссылка на чужую функцию в прозе обязана указывать на живое имя.

ПЕРЕИМЕНОВАНИЕ РАСХОДИТСЯ С ПРОЗОЙ МОЛЧА, и это не мелочь оформления. Проза
здесь — не украшение: комментарий «тот же приём и по той же причине — в такой-то
функции такого-то модуля» отправляет читателя к разбору, ради которого он и
написан. После переименования такой адрес ведёт в пустоту, и читатель
заключает, что механизма нет.

Пример адреса пишется здесь БЕЗ точки намеренно: этот файл проверяется наравне
с остальными, и образец внутри него сработал бы на себе.

ЗАМЕР 11.09.2026: одно переименование (было `own_jobs`, стало `roster_of`) оставило ТРИ
мёртвых адреса в двух чужих модулях, и внешний взгляд назвал каждый отдельной
находкой. Три находки об одном — это не три правки, а отсутствующий механизм
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЧИТАЮТСЯ ТОЛЬКО СВОИ МОДУЛИ. `pathlib.Path` и `json.loads` сюда не попадают: у
чужого имени нет нашего дерева, и проверять его нечем. Границу задаёт список
файлов в `scripts/`, а не догадка по виду имени
([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SOURCES = sorted(SCRIPTS.glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))

#: Адрес вида `модуль.имя` внутри инлайн-кода. Скобки вызова необязательны:
#: в прозе пишут и `roster_of`, и `roster_of()`.
REFERENCE_RE = re.compile(r"`(?P<module>[a-z_][a-z0-9_]*)\.(?P<name>[a-z_][a-z0-9_]*)\(?\)?`")

#: Расширения файлов: `drift.py` — ИМЯ ФАЙЛА, а не адрес функции, и по виду они
#: неразличимы. Перечислены, а не угаданы по длине (068).
FILE_SUFFIXES = frozenset({"py", "yml", "yaml", "json", "md", "svg", "txt", "toml", "cfg", "lock"})

#: Файлы, где такие адреса — ДАННЫЕ, а не ссылки. Список закрытый, и у каждого
#: названа причина: иначе он станет местом, куда сваливают неудобное (154).
NOT_REFERENCES = {
    "test_finding_identity.py": (
        "дословные записи реестра находок: их текст — предмет проверки, "
        "и править его значило бы подделать замер"
    ),
}


def names_of(path: Path) -> set[str]:
    """Имена верхнего уровня модуля: функции, классы, присваивания."""
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        # ИМПОРТЫ СЧИТАЮТСЯ ИМЕНАМИ МОДУЛЯ. `automerge.ghrest` — законный адрес:
        # общий транспорт зовут через модуль, который его импортировал, и в
        # прозе это пишут именно так.
        if isinstance(node, ast.Import):
            found.update((one.asname or one.name.split(".")[0]) for one in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.update((one.asname or one.name) for one in node.names)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            found.update(one.id for one in node.targets if isinstance(one, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


LIVE = {path.stem: names_of(path) for path in sorted(SCRIPTS.glob("*.py"))}


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_a_named_function_of_ours_still_exists(path: Path) -> None:
    """Каждый адрес `модуль.имя` в прозе указывает на существующее имя."""
    if path.name in NOT_REFERENCES:
        pytest.skip(NOT_REFERENCES[path.name])
    dead = [
        f"{found.group('module')}.{found.group('name')}"
        for found in REFERENCE_RE.finditer(path.read_text(encoding="utf-8"))
        if found.group("name") not in FILE_SUFFIXES
        and found.group("module") in LIVE
        and found.group("name") not in LIVE[found.group("module")]
    ]
    assert not dead, f"{path.name}: адреса ведут в пустоту после переименования: {dead}"


def test_the_gate_has_a_subject() -> None:
    """Гейт, не нашедший ни одного адреса, доказывает только себя (075)."""
    seen = sum(
        1
        for path in SOURCES
        if path.name not in NOT_REFERENCES
        for found in REFERENCE_RE.finditer(path.read_text(encoding="utf-8"))
        if found.group("module") in LIVE and found.group("name") not in FILE_SUFFIXES
    )
    assert seen, "адресов вида `модуль.имя` в дереве нет — предмет проверки не найден"
