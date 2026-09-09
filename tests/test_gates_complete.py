"""Вердикт сводного гейта проверяется тем, что он обязан отвергнуть."""

from __future__ import annotations

from typing import Any

from tests.conftest import load_script

module = load_script("ci_complete.py")
REQUIRED = ["lint", "test"]


def run(name: str, status: str = "completed", conclusion: str | None = "success") -> dict[str, Any]:
    """Собирает одну запись проверки в том виде, в каком её отдаёт площадка."""
    return {"name": name, "status": status, "conclusion": conclusion}


def test_all_green_is_green() -> None:
    """Все объявленные зелёные — вердикт зелёный."""
    problems, waiting = module.verdict([run("lint"), run("test")], REQUIRED, "ci-complete")
    assert (problems, waiting) == ([], False)


def test_missing_record_is_rejected() -> None:
    """Записи нет на голове: прогон не стартовал, а не «зелено» (075)."""
    problems, _ = module.verdict([run("lint")], REQUIRED, "ci-complete")
    assert len(problems) == 1 and "записи нет" in problems[0]


def test_skipped_is_rejected() -> None:
    """Пропущенный джоб — отказ: иначе выключение шага обходит гейт."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="skipped")], REQUIRED, "ci-complete"
    )
    assert any("пропущен" in problem for problem in problems)


def test_all_cancelled_is_rejected() -> None:
    """Если все записи имени отменены, живого вердикта нет — это отказ."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="cancelled")], REQUIRED, "ci-complete"
    )
    assert any("все записи отменены" in problem for problem in problems)


def test_cancelled_beside_a_live_record_is_ignored() -> None:
    """Отмена от группы отмены не делает здоровую голову красной.

    Новый толчок или новая метка гасят прогон на той же голове, и его записи
    остаются лежать рядом с живыми. Первый прогон на площадке покраснел именно
    на этом: `filter=latest` записи отменённого прогона не отсекает.
    """
    runs = [
        run("lint", conclusion="cancelled"),
        run("lint"),
        run("test", conclusion="cancelled"),
        run("test"),
    ]
    assert module.verdict(runs, REQUIRED, "ci-complete") == ([], False)


def test_failure_beside_a_cancelled_record_still_rejects() -> None:
    """Отбрасывание отмен не прячет настоящий отказ."""
    runs = [run("lint"), run("test", conclusion="cancelled"), run("test", conclusion="failure")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete")
    assert any("failure" in problem for problem in problems)


def test_failure_is_rejected() -> None:
    """Красный сосед делает сводный красным, а не пропущенным."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="failure")], REQUIRED, "ci-complete"
    )
    assert any("failure" in problem for problem in problems)


def test_pending_makes_it_wait() -> None:
    """Незавершённый сосед означает ожидание, а не вердикт."""
    _, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress", conclusion=None)],
        REQUIRED,
        "ci-complete",
    )
    assert waiting is True


def test_two_live_records_with_one_name_are_flagged() -> None:
    """Одно обязательное имя от двух живых прогонов — вердикт неоднозначен."""
    problems, _ = module.verdict([run("lint"), run("test"), run("test")], REQUIRED, "ci-complete")
    assert any("живых записей с одним именем" in problem for problem in problems)


def test_itself_is_not_awaited() -> None:
    """Сводный не ждёт собственной записи — иначе он не дождётся никогда."""
    problems, waiting = module.verdict(
        [run("lint"), run("test")], [*REQUIRED, "ci-complete"], "ci-complete"
    )
    assert (problems, waiting) == ([], False)
