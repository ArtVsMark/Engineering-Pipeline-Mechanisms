"""Обрезка вывода: сказать, что урезано, и насколько.

Молчаливая обрезка выглядит как полный ответ — читатель ищет причину в первых
трёхстах знаках, когда она в четырёхсот первом. Копий обрезки было четыре, у
каждого механизма своя; здесь проверяется и поведение, и то, что копия одна.
"""

from __future__ import annotations

import ast

from tests.conftest import ROOT, load_script

report = load_script("report.py")
SCRIPTS = ROOT / "scripts"


def test_short_text_is_left_alone() -> None:
    """Короткий вывод не трогают: обрезки не было — и говорить не о чем."""
    assert report.cut("коротко") == "коротко"


def test_long_text_says_how_much_was_cut() -> None:
    """Урезанный вывод называет полный объём, а не ставит многоточие."""
    cut = report.cut("я" * 400)
    assert cut.endswith("(обрезано, всего 400 знаков)")
    assert len(cut) < 400 + 40


def test_the_limit_is_the_boundary_not_a_suggestion() -> None:
    """На самой границе обрезки нет: 300 знаков — ещё полный ответ."""
    assert report.cut("я" * report.LIMIT) == "я" * report.LIMIT


def test_no_mechanism_cuts_output_silently() -> None:
    """Гейт на дрейф: срез строки-вывода не пишут заново в каждом механизме.

    Копий было четыре — шаг открытия, гейт журнала, транспорт и сборка тела
    уплотнения, — и каждая обрезала молча. Разошлись бы они так же молча.
    """
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name == "report.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
                continue
            upper = node.slice.upper
            if (
                isinstance(upper, ast.Constant)
                and isinstance(upper.value, int)
                and upper.value >= 100
            ):
                raise AssertionError(f"{path.name}: вывод режется на месте, а не общим механизмом")
