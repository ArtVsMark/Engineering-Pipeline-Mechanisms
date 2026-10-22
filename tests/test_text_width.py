"""Ширина надписи в SVG: одна функция по таблице знаков, а не «длина × k».

Переехало из каталога вместе с `text_width.py` (#1563). У каталога значок
`python-badge` выходил на 20–25 % шире текста: каждому знаку давалась ширина
7,2 px (каталог #792). Набор держит три вещи: таблица различает узкие и широкие
знаки, знак вне таблицы не сжимается, и вторую формулу ширины «len(...) * k»
находит детектор `own_width` — гейт по генераторам SVG приходит вместе с
первым генератором, `python_badge`.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("text_width.py")
builder = load_script("build_text_widths.py")

#: Имя коэффициента ширины на знак.
FACTOR_RE = re.compile(r"(?i)(?:^|_)k(?:$|_)|char|знак|ширин|width|px")


def own_width(source: str) -> list[str]:
    """Вторая реализация ширины надписи в модуле (214, каталог: обзор #795).

    Ищется не форма записи, а то, чем ширина считается без таблицы: число
    знаков, умноженное на коэффициент ширины, — `len(x) * k` в любом порядке,
    напрямую или через имя, которому присвоен `len(...)`; и своя таблица ширин —
    словарь, где больше десяти ключей-знаков. Коэффициент ширины — дробное число
    (px на знак) или имя, которое так и называется (`K`, `CHAR`, `ширина`,
    `px`): `row * len(data)` — высота по числу строк, и находкой она не
    является (051). ГРАНИЦА: коэффициент под другим именем и сумма по знакам без
    словаря разбором не видны.
    """
    tree = ast.parse(source)

    def length(node: ast.AST) -> bool:
        # Обе формы имени вызова: `len(x)` и `builtins.len(x)` (045).
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        return isinstance(func, ast.Name | ast.Attribute) and name == "len"

    from_length = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and length(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    def signs(node: ast.AST) -> bool:
        return length(node) or (isinstance(node, ast.Name) and node.id in from_length)

    def factor(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return isinstance(node.value, float)
        name = getattr(node, "id", None) or getattr(node, "attr", None) or ""
        return bool(FACTOR_RE.search(name))

    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mult)
            and (
                (signs(node.left) and factor(node.right))
                or (signs(node.right) and factor(node.left))
            )
        ):
            found.append(f"строка {node.lineno}: ширина по числу знаков")
        if (
            isinstance(node, ast.Dict)
            and sum(
                isinstance(key, ast.Constant) and isinstance(key.value, str) and len(key.value) == 1
                for key in node.keys
            )
            > 10
        ):
            found.append(f"строка {node.lineno}: своя таблица ширин знаков")
    return found


@pytest.mark.parametrize(
    "source",
    [
        "w = round(len(текст) * 7.2) + 14",
        "n = len(подпись)\nw = n * LABEL_K",
        "w = K * len(t)",
        "ШИРИНЫ = {" + ", ".join(f"'{c}': 7" for c in "abcdefghijkl") + "}",
    ],
)
def test_a_second_width_formula_is_caught(source: str) -> None:
    """Число знаков на коэффициент и своя таблица знаков — вторая реализация."""
    assert own_width(source)


@pytest.mark.parametrize(
    "source",
    [
        "x = len(текст) + 1",
        "n = len(строки)\nвысота = 20 + 14",
        "низ = TOP + row * len(data)",
        "цвета = {'ok': 'green', 'bad': 'red'}",
    ],
)
def test_what_is_not_a_width_formula_is_not_caught(source: str) -> None:
    """Высота по числу строк и словарь цветов — не ширина надписи (051)."""
    assert not own_width(source)


@pytest.mark.parametrize(("font", "weight"), [("Verdana", 400), ("Inter", 800)])
def test_a_narrow_text_is_narrower_than_a_wide_one_of_equal_length(font: str, weight: int) -> None:
    """Таблица различает узкие и широкие знаки — то, чего не умел коэффициент."""
    assert module.width("lili", font, weight=weight) < module.width("mwmw", font, weight=weight)


#: Поле части значка с каждой стороны, px: так считает часть `python_badge`
#: каталога (`_ширина`: округлённая ширина надписи плюс два поля).
FIELD = 5


@pytest.mark.parametrize(
    ("text", "px"),
    # Сумма advance width из hmtx Verdana 2.35 (sha256 96ed14949ca4) × 11/2048,
    # округлённая, плюс поля 5 + 5 — числа теста каталога, снятые с файла шрифта,
    # а не с этой таблицы (каталог, обзор #795).
    [("coverage / all (os)", 112), ("windows", 57), ("linux", 36), ("3.14", 35)],
)
def test_the_width_is_the_sum_of_the_font_table(text: str, px: int) -> None:
    """Ширина — сумма ширин знаков по таблице шрифта, а не их число на коэффициент."""
    assert round(module.width(text)) + 2 * FIELD == px


def test_a_sign_outside_the_table_gets_the_widest_width() -> None:
    """Неизвестный знак не сжимается молча: воздух лучше обрезки (045)."""
    table = json.loads(module.TABLE.read_text(encoding="utf-8"))["fonts"]["Verdana"]
    widest = max(table["weights"]["400"].values()) * 11.0 / table["units"]
    assert "中" not in table["weights"]["400"]
    assert module.width("中") == pytest.approx(widest)


def test_the_table_names_its_measured_source() -> None:
    """Таблица снята с файлов шрифта, и файл назван так, что замер повторим.

    Версия из таблицы имён и начало sha256 (каталог, обзор #795).
    """
    fonts = json.loads(module.TABLE.read_text(encoding="utf-8"))["fonts"]
    assert fonts, "в таблице ни одного шрифта — ширину считать не по чему (075)"
    for name, font in fonts.items():
        assert re.search(r"Version [\d.]+.*sha256:[0-9a-f]{12}", font["source"]), name


def test_the_table_is_what_the_builder_writes() -> None:
    """Файл таблицы — в форме, которую пишет сборщик: `--check` сверяет текст целиком."""
    text = module.TABLE.read_text(encoding="utf-8")
    assert builder.render(json.loads(text)) == text
    assert json.loads(text)["about"] == builder.ABOUT


def test_the_builder_takes_widths_from_the_font_map() -> None:
    """Знак есть в карте — ширина его глифа; нет — знак в таблицу не идёт."""
    cmap = {ord("a"): "glyph_a", ord("/"): "slash"}
    advance = {"glyph_a": 1229, "slash": 930}.__getitem__
    assert builder.widths(cmap, advance, "a/中") == {"a": 1229, "/": 930}


def test_the_face_is_not_lighter_than_asked() -> None:
    """Начертание берётся не легче запрошенного: 650 читается как 700."""
    assert module.width("abc", "Inter", weight=650) == module.width("abc", "Inter", weight=700)


def test_the_builder_without_fonttools_is_the_third_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Нет fontTools — «замер не сделан» кодом 2, а не трасса и не «совпало» (039)."""

    def no_fonttools(*_: object) -> dict[str, object]:
        raise ImportError("fontTools")

    monkeypatch.setattr(builder, "build", no_fonttools)
    code = builder.main(["--verdana", "v.ttf", "--inter", "i", "--check"])
    assert code == builder.EXIT_BROKEN
    assert "fontTools" in capsys.readouterr().err


def test_the_builder_checks_and_writes_the_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--check: совпало — 0, разошлось — 1 и файл не тронут; без --check — записано, 0."""
    table = json.loads(module.TABLE.read_text(encoding="utf-8"))
    target = tmp_path / "text_widths.json"
    target.write_text(builder.render(table), encoding="utf-8")
    monkeypatch.setattr(builder.text_width, "TABLE", target)
    monkeypatch.setattr(builder, "build", lambda *_: table)
    argv = ["--verdana", "v.ttf", "--inter", "i"]
    assert builder.main([*argv, "--check"]) == builder.EXIT_OK
    other = {**table, "about": "иначе"}
    monkeypatch.setattr(builder, "build", lambda *_: other)
    assert builder.main([*argv, "--check"]) == builder.EXIT_DIFFERS
    assert json.loads(target.read_text(encoding="utf-8")) == table
    assert builder.main(argv) == builder.EXIT_OK
    assert json.loads(target.read_text(encoding="utf-8")) == other
