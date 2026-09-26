"""Один предмет разбирает одна реализация: образец не повторяется в двух модулях (214).

Второй разбор того же предмета совпадает с первым в день появления и расходится
при первой правке одного из них, и молча: каждая копия исправна и покрыта своим
набором. Каталог принял правило 214 по замеру: восемь образцов, буква в букву
повторённых в двух модулях, шесть из них — один предмет.

ЗАМЕР ПО ДЕРЕВУ 26.09.2026, ДО ПОЧИНКИ: 86 образцов `re.compile` в `scripts/` и
`packages/transport/`, повторено в нескольких модулях — два, и оба один предмет:
номер прогона в адресе (`automerge`, `main_red`) и формат номера версии
(`check_version`, `build_changelog`). После починки второй модуль спрашивает
первый, и повторов ноль.

ГРАНИЦА НАЗВАНА (195). Судится буква образца, а не смысл: две разные записи
одного предмета гейт не видит, и это держит чтение. Общая грамматика, не
принадлежащая предмету, — заголовок markdown, разделитель таблицы, — повтором
предмета не является, и её копия заносится в `SIGNED` с причиной (071).
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, walk

#: Где живёт рабочий код, который разбирает предметы конвейера.
PLACES: Final = (ROOT / "scripts", ROOT / "packages" / "transport")

#: Намеренные копии образца — с причиной у каждой (071). Пусто на 26.09.2026.
SIGNED: Final[dict[str, str]] = {}


def patterns(path: Path) -> list[tuple[str, int]]:
    """Образцы `re.compile(<строка>)` модуля: текст и строка."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", None))
        first = node.args[0]
        if name == "compile" and isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((first.value, node.lineno))
    return found


def repeated(files: list[Path], root: Path = ROOT) -> dict[str, list[str]]:
    """Образцы, повторённые в нескольких модулях: текст → места от `root`."""
    seen: dict[str, list[str]] = defaultdict(list)
    for path in files:
        for said, line in patterns(path):
            seen[said].append(f"{path.relative_to(root)}:{line}")
    return {
        said: places
        for said, places in seen.items()
        if len({one.split(":")[0] for one in places}) > 1 and said not in SIGNED
    }


def modules() -> list[Path]:
    """Модули рабочего кода."""
    return [path for place in PLACES for path in walk(place, "*.py")]


def test_the_gate_found_its_subject() -> None:
    """Предмет есть: образцов в рабочем коде десятки, а не ноль (075)."""
    assert sum(len(patterns(path)) for path in modules()) >= 50


def test_no_pattern_is_parsed_in_two_modules() -> None:
    """Образец одного предмета живёт в одном модуле, остальные его спрашивают."""
    found = repeated(modules())
    assert not found, "образец повторён в нескольких модулях (214): " + "; ".join(
        f"{said!r} — {', '.join(places)}" for said, places in found.items()
    )


def test_the_predicate_tells_a_copy_from_a_reference(tmp_path: Path) -> None:
    """Обе половины: копия образца краснеет, ссылка на чужой образец — нет."""
    first = tmp_path / "first.py"
    first.write_text('import re\nRUN = re.compile(r"/runs/(\\d+)")\n', encoding="utf-8")
    copy = tmp_path / "copy.py"
    copy.write_text('import re\nRUN = re.compile(r"/runs/(\\d+)")\n', encoding="utf-8")
    asks = tmp_path / "asks.py"
    asks.write_text("import first\nRUN = first.RUN\n", encoding="utf-8")
    assert list(repeated([first, copy], tmp_path)) == [r"/runs/(\d+)"]
    assert repeated([first, asks], tmp_path) == {}
