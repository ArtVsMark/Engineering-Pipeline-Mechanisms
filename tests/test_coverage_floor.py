"""Порог покрытия выводится из ряда, а не пишется рукой.

Рукописный порог устаревает в обе стороны: низкий молчит, пока покрытие
сползает; высокий краснеет на законном и приучает себя обходить (005, 051).
Здесь проверяется то, без чего механизм был бы распечаткой памяти: порог —
максимум РЯДА, свежее значение — его последний день, а незнание называется
незнанием, а не «покрытие в порядке» (045).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("coverage_floor.py")


def series(**days: float) -> dict[str, Any]:
    """Ряд в той же форме, в какой его публикует механизм ряда прогонов."""
    return {"days": {day: {"runs": {}, "coverage": value} for day, value in days.items()}}


def test_the_floor_is_the_best_the_series_ever_saw() -> None:
    """Порог — МАКСИМУМ ряда, а не последнее значение.

    Иначе он сполз бы вместе с покрытием: каждый день становился бы новой
    нормой, и «не ниже достигнутого» превратилось бы в «не ниже вчерашнего».
    Это зеркало правила
    [050](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/050-limits-move-down-only.md):
    там предел
    сверху и ходит вниз, здесь граница снизу и ходит вверх, а принцип один —
    граница двигается в сторону строгости.
    """
    got = module.floor_of(series(**{"2026-09-17": 88.0, "2026-09-18": 90.0, "2026-09-19": 89.0}))
    assert got.floor == 90.0
    assert got.now == 89.0
    assert got.below


def test_holding_the_floor_is_not_a_finding() -> None:
    """Вторая половина: покрытие на уровне достигнутого — не находка.

    Без неё предикат был бы неотличим от «всегда находит», а такой учат
    обходить (051).
    """
    got = module.floor_of(series(**{"2026-09-19": 88.0, "2026-09-20": 88.0}))
    assert not got.below
    assert "ниже достигнутого" not in got.said()


def test_a_rise_is_not_a_finding_either() -> None:
    """Рост тем более не находка, и порог поднимается вместе с ним."""
    got = module.floor_of(series(**{"2026-09-19": 88.0, "2026-09-20": 91.5}))
    assert not got.below
    assert got.floor == 91.5


def test_a_fall_names_both_numbers() -> None:
    """Находка называет ОБА числа и день замера, а не «покрытие упало».

    Оценка без чисел не проверяема, и читателю нечем решить, законно ли
    падение (046).
    """
    said = module.floor_of(series(**{"2026-09-19": 90.0, "2026-09-20": 80.0})).said()
    assert "80.0" in said and "90.0" in said and "2026-09-20" in said
    assert re.search(r"ряд \d+ дн", said), said


def test_the_line_says_it_is_a_count_not_a_stop() -> None:
    """Строка сама говорит, что решение за человеком (154).

    Падение бывает законным — код вынесли в пакет, покрытое удалили, — и
    строка, звучащая как приказ, учила бы обходить её (051).
    """
    said = module.floor_of(series(**{"2026-09-19": 90.0, "2026-09-20": 80.0})).said()
    assert "не стоп" in said and "154" in said


def test_an_empty_series_is_the_third_outcome() -> None:
    """Дней нет — порог брать неоткуда, и это отказ, а не «покрытие в порядке»."""
    with pytest.raises(module.NotRun, match="ни одного дня"):
        module.floor_of({"days": {}})


def test_a_series_without_coverage_is_told_apart_from_a_fall() -> None:
    """Ряд есть, а поля покрытия в нём нет — СВОЙ отказ, а не ноль процентов.

    Ноль вместо незнания читался бы как «ничего не покрыто» — то есть худшая
    из возможных находок на месте простого молчания источника (045).
    """
    with pytest.raises(module.NotRun, match="не копится"):
        module.floor_of({"days": {"2026-09-20": {"runs": {}}}})


def test_a_missing_series_file_is_not_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Файла ряда нет — отказ с причиной, а не пустой ряд (075)."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: None)
    with pytest.raises(module.NotRun, match="порог брать неоткуда"):
        module.series("o/r", "т")


def test_an_unreadable_series_is_not_a_missing_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ транспорта и отсутствие файла — разные ответы, и оба названы."""

    def broken(*_a: object, **_k: object) -> None:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.ghrest, "request", broken)
    with pytest.raises(module.NotRun, match="не прочитан"):
        module.series("o/r", "т")


def test_the_series_is_read_from_its_own_branch() -> None:
    """Ссылка на ветку идёт в запрос: без неё площадка отдаёт файл с общей.

    В общей ветке `runs.json` нет вовсе, и запрос без `ref` отвечал бы «нет
    файла» — то есть механизм молчал бы по причине, не имеющей отношения к
    делу ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    asked: list[str] = []

    class Caught(RuntimeError):
        pass

    def spy(_method: str, where: str, *_a: object, **_k: object) -> None:
        asked.append(where)
        raise Caught

    module.ghrest.request, keep = spy, module.ghrest.request
    try:
        with pytest.raises(Caught):
            module.series("o/r", "т")
    finally:
        module.ghrest.request = keep
    assert asked and f"ref={module.SERIES_BRANCH}" in asked[0], asked


def test_the_state_carries_its_own_verdict() -> None:
    """Состояние `Floor` само отвечает, ниже ли порога, — и зовётся по имени.

    Сборка состояния мимо разбора ряда проверяет ровно то, что разбор в него
    кладёт: вердикт живёт в состоянии, а не в зовущем, и второй его подсчёт у
    каждого читателя разошёлся бы молча (090).
    """
    assert module.Floor(day="2026-09-20", now=87.9, floor=88.6, days=4).below
    assert not module.Floor(day="2026-09-20", now=88.6, floor=88.6, days=4).below
