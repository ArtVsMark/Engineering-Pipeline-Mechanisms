"""Замер: счётчик видит подпроцессы, и «гейты прогоном» считаются по дереву.

ЧИСЛО, КОТОРОЕ ВРЁТ, ХУЖЕ ОТСУТСТВУЮЩЕГО. Гейты этого проекта проверяются
ЗАПУСКОМ: тест зовёт модуль отдельным процессом и смотрит исход. Счётчик
покрытия подпроцессов не видел, и четыре полностью проверенных модуля
показывали ноль при семнадцати вызовах из набора — на таком числе едва не
собрались строить порог
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.conftest import MEASURING, ROOT, load_script, under_counter, walk

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
    modules = len(list(walk(ROOT / "scripts", "*.py")))
    assert counts["runnable"] < modules, "все модули объявлены запускаемыми — разбор не разбирает"


def test_a_same_named_mechanism_is_named_not_collapsed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Одноимённые механизмы в двух каталогах не схлопываются в одну единицу.

    Знаменатель ключевался именем файла, а каталогов с кодом два. Одноимённый
    модуль с точкой входа в обоих уменьшал бы знаменатель МОЛЧА — и витрина
    показывала бы покрытие лучше настоящего
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд находкой `2ce9aef` на #411; одноимённых в дереве
    сегодня нет, поэтому это риск, а не дефект, и проверяется он подделкой.

    СТОЛКНОВЕНИЕ НАЗЫВАЕТСЯ, а не чинится выбором: набор зовёт механизм по имени
    файла, и при двух одноимённых неизвестно, какой из них прогнан (154).
    """
    said = "def main() -> int:\n    return 0\n"
    for where in facts.paths.SOURCES:
        (tmp_path / where).mkdir(parents=True)
        (tmp_path / where / "двойник.py").write_text(said, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    counts = facts.script_runs(tmp_path)
    assert counts["runnable"] == 2, f"два модуля схлопнулись в {counts['runnable']}"
    assert "::warning::" in capsys.readouterr().err, "столкновение осталось молчаливым"


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


def test_a_counted_zero_is_never_published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сосчитанный ноль НЕ публикуется: граница между счётом и витриной.

    Счётчику ноль отдавать честно — его зовут и с синтетическим корнем, где
    пусто законно (соседняя проверка выше). А вот ОПУБЛИКОВАННЫЙ ноль уже
    утверждение о проекте: значок покажет «тестов 0» так же уверенно, как показал
    бы 1743, и читатель не отличит «посчитали» от «не нашли, где считать».
    Переименуй каталог набора — и витрина соврёт, не покраснев нигде
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    ЗАМЕР 19.09.2026, ИЗ-ЗА КОТОРОГО ПРОВЕРКА И НАПИСАНА: на дереве без каталога
    набора `test_counts` отдавал `{'total': 0, 'modules': 0}`, и витрина
    опубликовала бы это как факт. Найдено не чтением, а ЗАПУСКОМ механизмов на
    пустом корне.
    """
    настоящие = facts.collect(ROOT, "голова")
    подделка = json.loads(json.dumps(настоящие))
    подделка["tests"]["functions"] = 0
    monkeypatch.setattr(facts, "collect", lambda *a, **k: подделка)
    код = facts.main(
        ["--root", str(ROOT), "--out-dir", str(tmp_path), "--sha", "голова", "--repo", "o/r"]
    )
    assert код == facts.EXIT_BROKEN, "витрина опубликовала сосчитанный ноль"
    assert not list(tmp_path.glob("*.svg")), "значки нарисованы при обрыве обхода"


def test_a_real_tree_still_publishes(tmp_path: Path) -> None:
    """Вторая половина: на настоящем дереве витрина собирается.

    Без неё «ноль не публикуется» держалось бы тем, что не публикуется НИЧЕГО
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    assert (
        facts.main(
            ["--root", str(ROOT), "--out-dir", str(tmp_path), "--sha", "голова", "--repo", "o/r"]
        )
        == 0
    )
    assert (tmp_path / facts.PUBLISHED_DIR / "facts.json").is_file(), (
        "фактов нет при здоровом дереве"
    )


def test_coverage_without_a_report_is_not_a_zero(tmp_path: Path) -> None:
    """Отчёта нет — так и говорится; ноль читался бы как «ничего не покрыто» (045)."""
    assert facts.coverage_facts(None) == {"read": False}
    assert facts.coverage_facts(tmp_path / "нет.json") == {"read": False}
    assert "coverage_percent" not in facts.contract_coverage({"read": False})
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
    said = facts.coverage_badge({"coverage_percent": 77.0})
    assert "77%" in said


def test_facts_without_a_repo_are_not_published(tmp_path: Path) -> None:
    """Без имени проекта минимум контракта не собран — публикации нет (#759)."""
    code = facts.main(
        ["--root", str(ROOT), "--out-dir", str(tmp_path), "--sha", "голова", "--repo", ""]
    )
    assert code == facts.EXIT_BROKEN
    assert not (tmp_path / facts.PUBLISHED_DIR / "facts.json").exists()
