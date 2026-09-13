"""Пропущенный заход по расписанию проверяется подделанным пропуском.

Предмет здесь — событие, которого НЕ БЫЛО, и на здоровом репозитории его не
достать: заход либо случился, либо площадка о нём молчит. Поэтому счёт
ожидаемого проверяется на подделанных окнах, а счёт случившегося — на
подделанных ответах площадки
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("schedules_seen.py")

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("cron", "days", "count", "about"),
    [
        ("17 6 * * *", 7, 7, "ежедневно за неделю"),
        ("17 6 * * *", 1, 1, "ежедневно за сутки"),
        ("17 * * * *", 1, 24, "ежечасно за сутки"),
        ("0 * * * *", 0, 1, "ежечасно в пустом окне — ровно текущий час"),
    ],
    ids=lambda one: one if isinstance(one, str) else "",
)
def test_the_expected_count_follows_the_declared_schedule(
    cron: str, days: int, count: int, about: str
) -> None:
    """Ожидаемое число считается из объявленного расписания, а не из наблюдений.

    Считать ожидание по наблюдённому значило бы объявлять пропусков ноль
    всегда: сколько случилось, столько и ожидали.
    """
    since = NOW - timedelta(days=days)
    assert module.expected_between(cron, since, NOW) == count, about


@pytest.mark.parametrize(
    "cron",
    ["17 6 * * 1", "17 6 1 * *", "*/5 * * * *", "17 */2 * * *", "17 6 * *"],
    ids=["день недели", "день месяца", "минута шагом", "час шагом", "четыре поля"],
)
def test_an_unsupported_form_refuses_instead_of_counting_zero(cron: str) -> None:
    """Неразобранная форма — это отказ, а не «пропусков нет».

    Приблизительный ответ, выданный за точный, объявил бы канал исправным там,
    где его не считали
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    with pytest.raises(module.NotRun):
        module.expected_between(cron, NOW - timedelta(days=1), NOW)


def test_extra_runs_do_not_pay_for_missed_ones() -> None:
    """Лишние заходы в минус не уводят: ручной запуск не гасит пропуск.

    Прогон могли толкнуть кнопкой, и вычитание спрятало бы потерю расписания за
    работой человека.
    """
    seen = module.Seen("hail.yml", "17 * * * *", expected=3, happened=9, fell=0)
    assert seen.missed == 0


def test_a_missed_run_is_counted_and_named() -> None:
    """Пропуск считается и печатается словами, а не выводится читателем."""
    seen = module.Seen("hail.yml", "17 * * * *", expected=28, happened=5, fell=0)
    assert seen.missed == 23
    assert seen.loud
    assert "пропущено 23" in seen.said()


def test_a_single_miss_is_tolerated_and_said_so() -> None:
    """Один пропуск не крик: задержка площадки — не потеря (051).

    Порог — ГИПОТЕЗА: ряда у нас пока нет, и первый же ряд её пересматривает.
    Случай держит границу, а не число: изменив порог, придётся изменить и его.
    """
    seen = module.Seen("drift.yml", "43 7 * * *", expected=8, happened=7, fell=0)
    assert seen.missed == 1
    assert not seen.loud


def test_a_fallen_run_is_loud_even_without_misses() -> None:
    """Упавший заход требует взгляда сам по себе (097).

    Он краснеет, но краснеет на вкладке прогонов, а вкладка адресатом не
    является: её открывают, уже заподозрив.
    """
    seen = module.Seen("review.yml", "11 8 * * *", expected=7, happened=7, fell=1)
    assert seen.missed == 0
    assert seen.loud
    assert "упало 1" in seen.said()


def answers(runs: list[dict[str, Any]], created: str = "2026-09-01T00:00:00Z") -> Any:
    """Ответ площадки: возраст прогона и его заходы по расписанию."""

    def reply(_method: str, path: str, *_args: object, **_kwargs: object) -> dict[str, Any]:
        if "/runs?" in path:
            return {"workflow_runs": runs}
        return {"created_at": created}

    return reply


def test_a_cancelled_run_is_not_a_run_that_happened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отменённый заход состоявшимся не считается: работы он не сделал."""
    monkeypatch.setattr(
        module.ghrest,
        "request",
        answers(
            [
                {"created_at": "2026-09-12T06:17:00Z", "conclusion": "cancelled"},
                {"created_at": "2026-09-11T06:17:00Z", "conclusion": "success"},
            ]
        ),
    )
    happened, fell = module.fired("o/r", "x.yml", "t", NOW - timedelta(days=7))
    assert (happened, fell) == (1, 0)


def test_a_run_outside_the_window_is_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заход старше окна в счёт не идёт — иначе окно ничего не ограничивает."""
    monkeypatch.setattr(
        module.ghrest,
        "request",
        answers([{"created_at": "2026-08-01T06:17:00Z", "conclusion": "success"}]),
    )
    happened, _ = module.fired("o/r", "x.yml", "t", NOW - timedelta(days=7))
    assert happened == 0


def test_a_fallen_run_counts_as_both_happened_and_fallen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Упавший заход СЛУЧИЛСЯ: считать его пропуском значило бы сложить два разных состояния."""
    monkeypatch.setattr(
        module.ghrest,
        "request",
        answers([{"created_at": "2026-09-12T06:17:00Z", "conclusion": "failure"}]),
    )
    assert module.fired("o/r", "x.yml", "t", NOW - timedelta(days=7)) == (1, 1)


def test_an_unknown_workflow_is_an_input_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Прогон, неизвестный площадке, — расхождение объявления с деревом (075)."""

    def missing(*_args: object, **_kwargs: object) -> None:
        raise module.ghrest.NotFound("нет такого")

    monkeypatch.setattr(module.ghrest, "request", missing)
    with pytest.raises(module.NotRun):
        module.fired("o/r", "нет.yml", "t", NOW)


def test_the_declaration_is_read_from_the_one_place(tmp_path: Path) -> None:
    """Расписания берутся из того же объявления, по которому считается цена (022)."""
    where = tmp_path / "schedules.json"
    where.write_text(json.dumps({"runs": {"a.yml": {"cron": "17 6 * * *"}}}), encoding="utf-8")
    assert module.declared(where) == {"a.yml": "17 6 * * *"}


def test_an_empty_declaration_is_an_input_error(tmp_path: Path) -> None:
    """Пустое объявление — ошибка входа, а не «расписаний нет» (075)."""
    where = tmp_path / "schedules.json"
    where.write_text(json.dumps({"runs": {}}), encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.declared(where)


def test_the_registry_shows_the_whole_row_not_only_the_loud() -> None:
    """Реестр печатает весь ряд, а не только шумное.

    Ряд и есть мера надёжности канала: по одной строке «требует взгляда» не
    видно, норма это или исключение (169).
    """
    body = module.render_body(
        [
            module.Seen("hail.yml", "17 * * * *", 28, 5, 0),
            module.Seen("drift.yml", "43 7 * * *", 2, 2, 0),
        ],
        NOW,
        7,
    )
    assert "## Требуют взгляда" in body and "## Весь ряд" in body
    assert "drift.yml" in body.split("## Весь ряд")[1]


def test_an_empty_registry_says_empty() -> None:
    """Пусто говорится словом, а не выглядит незаполненным (154)."""
    body = module.render_body([module.Seen("a.yml", "17 6 * * *", 7, 7, 0)], NOW, 7)
    assert "Пусто" in body
