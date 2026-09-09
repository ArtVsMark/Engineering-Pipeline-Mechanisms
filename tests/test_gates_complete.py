"""Вердикт сводного гейта проверяется тем, что он обязан отвергнуть."""

from __future__ import annotations

from typing import Any

from tests.conftest import load_script

module = load_script("gates_complete.py")
REQUIRED = ["lint", "test"]


def run(name: str, status: str = "completed", conclusion: str | None = "success") -> dict[str, Any]:
    """Собирает одну запись проверки в том виде, в каком её отдаёт площадка."""
    return {"name": name, "status": status, "conclusion": conclusion}


def test_all_green_is_green() -> None:
    """Все объявленные зелёные — вердикт зелёный."""
    problems, waiting = module.verdict([run("lint"), run("test")], REQUIRED, "gates-complete")
    assert (problems, waiting) == ([], False)


def test_missing_record_is_rejected() -> None:
    """Записи нет на голове: прогон не стартовал, а не «зелено» (075)."""
    problems, _ = module.verdict([run("lint")], REQUIRED, "gates-complete")
    assert len(problems) == 1 and "записи нет" in problems[0]


def test_skipped_is_rejected() -> None:
    """Пропущенный джоб — отказ: иначе выключение шага обходит гейт."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="skipped")], REQUIRED, "gates-complete"
    )
    assert any("пропущен" in problem for problem in problems)


def test_cancelled_is_rejected() -> None:
    """Отменённая запись пройденной не является."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="cancelled")], REQUIRED, "gates-complete"
    )
    assert any("отменён" in problem for problem in problems)


def test_failure_is_rejected() -> None:
    """Красный сосед делает сводный красным, а не пропущенным."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="failure")], REQUIRED, "gates-complete"
    )
    assert any("failure" in problem for problem in problems)


def test_pending_makes_it_wait() -> None:
    """Незавершённый сосед означает ожидание, а не вердикт."""
    _, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress", conclusion=None)],
        REQUIRED,
        "gates-complete",
    )
    assert waiting is True


def test_duplicate_names_are_flagged() -> None:
    """Две живые записи с одним именем — неоднозначный вердикт, а не «зелено»."""
    problems, _ = module.verdict(
        [run("lint"), run("test"), run("test", conclusion="failure")], REQUIRED, "gates-complete"
    )
    assert any("записей с одним именем" in problem for problem in problems)


def test_itself_is_not_awaited() -> None:
    """Сводный не ждёт собственной записи — иначе он не дождётся никогда."""
    problems, waiting = module.verdict(
        [run("lint"), run("test")], [*REQUIRED, "gates-complete"], "gates-complete"
    )
    assert (problems, waiting) == ([], False)
