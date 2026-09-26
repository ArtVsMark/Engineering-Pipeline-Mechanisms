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

С 26.09.2026 СУДИТСЯ И ОБРАЗЕЦ СТРОКОЙ В ВЫЗОВЕ `re.*`, а не только в
`re.compile` (взгляд на #861): при расширении нашлось два повтора — отпечаток
находки (`changerefs`, `findings_archive`, один предмет, сведён) и «числа
подряд» (общая грамматика, в `SIGNED`).

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

#: Намеренные копии образца — с причиной у каждой (071). Подпись ставится на
#: ПАРУ МОДУЛЕЙ, а не на образец целиком: общий образец вроде «числа подряд»
#: иначе освобождался бы в любом числе модулей, и третий, разобравший им
#: настоящий предмет, прошёл бы молча (взгляд на #869).
SIGNED: Final[dict[str, tuple[frozenset[str], str]]] = {
    r"\d+": (
        frozenset({"scripts/check_env.py", "scripts/check_reread.py"}),
        "грамматика «числа подряд», а не предмет: check_env режет версию пакета, "
        "check_reread — номер выгрузки каталога; источники и правила версий разные",
    ),
}


#: Вызовы модуля `re`, чей первый довод — образец. Образец строкой прямо в
#: `re.findall` или `re.search` — тот же разбор предмета, что и в `re.compile`,
#: и гейт, видевший только второй, пропускал первый (взгляд на #861).
TAKES_A_PATTERN: Final = frozenset(
    {"compile", "match", "search", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
)


def re_names(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    """Как модуль называет `re`: имена самого модуля и функций, взятых из него.

    `import re as rx` и `from re import findall` — та же операция под другим
    именем; гейт, видевший только `re.<имя>`, пропускал их молча (взгляд на #869).
    ПРЕДЕЛ НАЗВАН (195): `from re import *` и присваивание `rx = re` гейт не
    видит — имён он не выводит, а читает только импорты (взгляд на #877).
    """
    modules = {"re"}
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {one.asname or one.name for one in node.names if one.name == "re"}
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            functions |= {one.asname or one.name: one.name for one in node.names}
    return modules, functions


def patterns(path: Path) -> list[tuple[str, int]]:
    """Образцы строкой в вызовах `re.*` модуля — под любым именем: текст и строка."""
    found: list[tuple[str, int]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules, functions = re_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        called = str(getattr(func, "id", ""))
        if isinstance(func, ast.Attribute):
            name = func.attr
            of_re = getattr(func.value, "id", None) in modules
        else:
            name = functions.get(called, called)
            of_re = called in functions
        first = node.args[0]
        if not (name == "compile" or (of_re and name in TAKES_A_PATTERN)):
            continue
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
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
        if len({one.split(":")[0] for one in places}) > 1 and not signed(said, places)
    }


def signed(said: str, places: list[str]) -> bool:
    """Повтор подписан, только если все его модули названы подписью."""
    allowed, _ = SIGNED.get(said, (frozenset(), ""))
    return {one.split(":")[0] for one in places} <= allowed


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
    inline = tmp_path / "inline.py"
    inline.write_text('import re\nfound = re.findall(r"/runs/(\\d+)", "")\n', encoding="utf-8")
    assert list(repeated([first, inline], tmp_path)) == [r"/runs/(\d+)"], (
        "образец в findall не судится"
    )
    assert repeated([first, asks], tmp_path) == {}


def test_a_signature_covers_its_pair_and_no_third_module() -> None:
    """Подписанный образец в третьем модуле краснеет: подпись — на пару, а не на образец."""
    pair = ["scripts/check_env.py:1", "scripts/check_reread.py:2"]
    assert signed(r"\d+", pair)
    assert not signed(r"\d+", [*pair, "scripts/automerge.py:3"])


def test_an_aliased_or_imported_re_is_still_seen(tmp_path: Path) -> None:
    """`import re as rx` и `from re import findall` судятся так же, как `re.findall` (#869)."""
    first = tmp_path / "first.py"
    first.write_text('import re\nRUN = re.compile(r"/runs/(\\d+)")\n', encoding="utf-8")
    aliased = tmp_path / "aliased.py"
    aliased.write_text(
        'import re as rx\nfound = rx.findall(r"/runs/(\\d+)", "")\n', encoding="utf-8"
    )
    imported = tmp_path / "imported.py"
    imported.write_text(
        'from re import findall\nfound = findall(r"/runs/(\\d+)", "")\n', encoding="utf-8"
    )
    assert list(repeated([first, aliased], tmp_path)) == [r"/runs/(\d+)"], "псевдоним не судится"
    assert list(repeated([first, imported], tmp_path)) == [r"/runs/(\d+)"], "импорт не судится"


def test_a_module_that_knows_the_version_form_does_not_cut_it() -> None:
    """Модуль, спрашивающий `paths.VERSION_RE`, не режет номер по точке сам (#877).

    Ответ 214 обещает: разряды номера читаются `version.digits`. Обещание без
    гейта держалось чтением, и нарезка `split(".")` пережила починку в
    сортировке выпусков. Предмет — модули, которые форму номера уже знают:
    нарезка там — второе чтение того же. ПРЕДЕЛ НАЗВАН (195): модуль, не
    спрашивающий `paths.VERSION_RE`, гейт не судит — `pipeline_checks.compatible`
    читает MAJOR.MINOR входа потребителя, который бывает короче X.Y.Z.
    """
    cut = []
    for path in walk(ROOT / "scripts", "*.py"):
        source = path.read_text(encoding="utf-8")
        if "paths.VERSION_RE" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "split"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "."
            ):
                cut.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not cut, "номер режется по точке мимо version.digits (214): " + ", ".join(cut)
