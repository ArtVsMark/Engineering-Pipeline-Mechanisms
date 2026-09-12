"""Замер: счётчик видит подпроцессы, и «гейты прогоном» считаются по дереву.

ЧИСЛО, КОТОРОЕ ВРЁТ, ХУЖЕ ОТСУТСТВУЮЩЕГО. Гейты этого проекта проверяются
ЗАПУСКОМ: тест зовёт модуль отдельным процессом и смотрит исход. Счётчик
покрытия подпроцессов не видел, и четыре полностью проверенных модуля
показывали ноль при семнадцати вызовах из набора — на таком числе едва не
собрались строить порог
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.conftest import MEASURING, ROOT, load_script, under_counter

facts = load_script("build_facts.py")


def test_without_the_measure_nothing_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обычный заход идёт без счётчика: платить за замер каждый раз незачем."""
    monkeypatch.delenv(MEASURING, raising=False)
    command = under_counter(ROOT / "scripts" / "version.py", ("--check",))
    assert command[0] == sys.executable
    assert "coverage" not in command


def test_the_measure_is_declared_by_a_key_not_by_magic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Замер объявлен ключом и виден в команде.

    Обычный приём — положить `.pth` в каталог пакетов и поднимать счётчик у
    каждого процесса — правит чужое дерево и работает молча: сломается, и никто
    не заметит. Здесь видно, что запущено.
    """
    monkeypatch.setenv(MEASURING, "1")
    command = under_counter(ROOT / "scripts" / "version.py", ("--check",))
    assert command[1:4] == ["-m", "coverage", "run"]
    # Процессов много: без раздельных файлов они переписывали бы один друг за
    # другом, и свести их потом было бы нечем.
    assert "--parallel-mode" in command
    assert command[-1] == "--check", "аргументы механизма потерялись в обёртке"


def test_the_runnable_are_the_denominator() -> None:
    """Знаменатель — запускаемые модули, а не все.

    Модуль без точки входа процессом не запускается по устройству, и требовать
    от него такого прогона значило бы мерить долг там, где его нет.
    """
    counts = facts.script_runs(ROOT)
    assert counts["runnable"] > 0, "запускаемых механизмов не нашлось — предмет не найден (075)"
    assert 0 < counts["started"] <= counts["runnable"]
    modules = len(list((ROOT / "scripts").glob("*.py")))
    assert counts["runnable"] < modules, "все модули объявлены запускаемыми — разбор не разбирает"


def test_the_badge_shows_both_numbers() -> None:
    """Значок показывает долю, а не голое число: одно без другого ничего не значит."""
    said = facts.scripts_badge({"scripts": {"runnable": 31, "started": 17}})
    assert "17/31" in said
    assert "нет данных" in facts.scripts_badge({}), "пустой ответ выдан за число"


def test_a_missing_tree_is_not_a_zero(tmp_path: Path) -> None:
    """Пустое дерево даёт ноль запускаемых, а не ложную полноту (075)."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    assert facts.script_runs(tmp_path) == {"runnable": 0, "started": 0}


def test_coverage_without_a_report_is_not_a_zero(tmp_path: Path) -> None:
    """Отчёта нет — так и говорится; ноль читался бы как «ничего не покрыто» (045)."""
    assert facts.coverage_facts(None) == {"read": False, "percent": 0.0}
    assert facts.coverage_facts(tmp_path / "нет.json") == {"read": False, "percent": 0.0}
    assert "не прочитано" in facts.coverage_badge({})


def test_a_broken_report_is_a_refusal(tmp_path: Path) -> None:
    """Отчёт есть, но не разбирается — это отказ, а не «не прочитано».

    Разница не косметическая: «счётчик не запускали» чинится прогоном, «отчёт
    сломан» — разбором формы, и сводить их в одно значило бы отправить искать
    не туда (154).
    """
    bad = tmp_path / "coverage.json"
    bad.write_text("{не json", encoding="utf-8")
    with pytest.raises(facts.NotRun):
        facts.coverage_facts(bad)
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(facts.NotRun):
        facts.coverage_facts(empty)


def test_the_coverage_badge_shows_the_share() -> None:
    """Значок покрытия показывает долю числом, а не цветом наугад."""
    said = facts.coverage_badge({"coverage": {"read": True, "percent": 77.0}})
    assert "77%" in said
