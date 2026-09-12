"""Шаг 11 проверяется ПОДДЕЛАННЫМ застрявшим, а не зелёным обходом.

Предмет шага — состояние, которое нигде не краснеет: обязательной проверки не
создалось вовсе, значок не выдан, слияния не случилось. Прогон на здоровом
репозитории о таком не скажет ничего, потому что его там нет, — поэтому каждое
состояние подделывается ответом площадки
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("stuck.py")

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
REQUIRED = ["lint", "test", "pr-meta"]


def change(**over: Any) -> dict[str, Any]:
    """Ответ площадки об изменении: зелёное, с согласием, готовое к слиянию."""
    payload: dict[str, Any] = {
        "number": 42,
        "draft": False,
        "mergeable_state": "clean",
        "labels": [{"name": "automerge"}],
        "auto_merge": None,
        "head": {"sha": "deadbee"},
    }
    payload.update(over)
    return payload


def runs(
    *names: str, conclusion: str = "success", status: str = "completed"
) -> list[dict[str, Any]]:
    """Записи проверок на голове: по одной на имя."""
    return [
        {
            "name": name,
            "status": status,
            "conclusion": conclusion,
            "started_at": "2026-09-12T11:00:00Z",
        }
        for name in names
    ]


def verdict(payload: dict[str, Any], found: list[dict[str, Any]], **over: Any) -> Any:
    """Вердикт при значениях по умолчанию: значка нет, голова старая."""
    kwargs: dict[str, Any] = {"armed": False, "fresh": False}
    kwargs.update(over)
    return module.judge(payload, found, REQUIRED, **kwargs)


def test_a_lost_event_leaves_no_record_and_that_is_the_finding() -> None:
    """Записей на голове нет вовсе — событие не дошло, и краснеть нечему.

    Это тот самый случай, ради которого шаг заведён: защита ветки ждёт вердикт,
    которого не будет, а проверок, которые могли бы покраснеть, не создалось
    (075, 104).
    """
    said = verdict(change(), [])
    assert said.stuck
    assert said.why == module.STUCK_NO_RUNS


def test_a_required_check_that_was_never_created_names_its_name() -> None:
    """Часть обязательных имён на голове отсутствует — и они названы поимённо.

    Сказать «что-то не создалось» значит отправить человека перебирать все
    проверки; имя отправляет его в один файл (154).
    """
    said = verdict(change(), runs("lint", "test"))
    assert said.stuck
    assert said.why == module.STUCK_MISSING
    assert said.missing == ("pr-meta",)


def test_green_with_consent_but_unarmed_is_named() -> None:
    """Всё зелено, согласие стоит, а значка слияния нет — очередь не сработала."""
    said = verdict(change(), runs(*REQUIRED))
    assert said.stuck
    assert said.why == module.STUCK_UNARMED


def test_armed_and_green_but_unmerged_is_named() -> None:
    """Значок выдан, всё зелено — а слияния нет: не сработала площадка.

    Отдельная причина, а не «значок не выдан»: починка другая — там будят
    очередь, здесь спрашивают площадку (154).
    """
    said = verdict(change(), runs(*REQUIRED), armed=True)
    assert said.stuck
    assert said.why == module.STUCK_ARMED


@pytest.mark.parametrize(
    ("payload", "found", "why"),
    [
        (change(draft=True), [], module.WHY_DRAFT),
        (change(labels=[{"name": "hold"}]), [], module.WHY_HOLD),
        (change(mergeable_state="unknown"), [], module.WHY_UNCOMPUTED),
        (change(mergeable_state="dirty"), [], module.WHY_NEIGHBOUR),
        (change(), runs("lint", "test", "pr-meta", conclusion="failure"), module.WHY_NEIGHBOUR),
        (change(), runs("lint", "test", "pr-meta", status="in_progress"), module.WHY_RUNNING),
        (change(labels=[]), runs(*REQUIRED), module.WHY_NO_CONSENT),
    ],
    ids=[
        "черновик",
        "стоп-метка",
        "не посчитано",
        "конфликт",
        "своё красное",
        "идут",
        "без согласия",
    ],
)
def test_standing_for_a_reason_is_not_stuck(
    payload: dict[str, Any], found: list[dict[str, Any]], why: str
) -> None:
    """Стоять законно можно семью способами, и каждый назван словом.

    Свести их к молчанию значит сделать «не застряло» неотличимым от «не
    смотрели вовсе»
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    said = verdict(payload, found)
    assert not said.stuck
    assert said.why == why


def test_a_fresh_head_is_given_its_term_before_it_is_called_stuck() -> None:
    """Молодая голова не застряла: срок здесь защита от ложного крика (100)."""
    said = verdict(change(), [], fresh=True)
    assert not said.stuck
    assert said.why == module.WHY_FRESH


def test_the_neighbour_takes_red_before_the_missing_are_counted() -> None:
    """Красное уходит оклику ДАЖЕ когда часть имён пропала.

    Иначе одно состояние получило бы двух адресатов, и починку человек искал бы
    дважды (022). Порядок вопросов здесь и есть ответ.
    """
    said = verdict(change(), runs("lint", conclusion="failure"))
    assert not said.stuck
    assert said.why == module.WHY_NEIGHBOUR


def test_a_cancelled_record_does_not_hide_a_live_one() -> None:
    """Отменённая запись не выдаётся за вердикт имени, если есть живая.

    Тот же разбор гонки, что в `ci_complete.worst_per_name`: группа отмены
    гасит прежний заход, и его запись бывает СВЕЖЕЕ живой (090).
    """
    found = [
        {
            "name": "lint",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-09-12T11:00:00Z",
        },
        {
            "name": "lint",
            "status": "completed",
            "conclusion": "cancelled",
            "started_at": "2026-09-12T11:30:00Z",
        },
    ]
    picked = module.latest(found, "lint")
    assert picked is not None
    assert picked["conclusion"] == "success"


def test_a_name_with_only_cancelled_records_still_answers() -> None:
    """Отменены ВСЕ записи имени — вердикт всё равно есть, и он не «пусто».

    Иначе имя читалось бы как несозданное, а это другая починка: там будят
    событие, здесь ждут нового захода.
    """
    found = [
        {
            "name": "lint",
            "status": "completed",
            "conclusion": "cancelled",
            "started_at": "2026-09-12T11:00:00Z",
        }
    ]
    picked = module.latest(found, "lint")
    assert picked is not None
    assert picked["conclusion"] == "cancelled"


@pytest.mark.parametrize(
    "stamp", ["", "не дата", "2026-13-99T00:00:00Z"], ids=["пусто", "мусор", "нелепость"]
)
def test_an_unreadable_stamp_is_old_not_young(stamp: str) -> None:
    """Не прочитав отметку, срок НЕ выдаётся: из незнания вывод не делается.

    Молодой считалась бы голова, о которой ничего не известно, — и застрявшее
    молчало бы ровно там, где спросить не удалось (045).
    """
    assert module.is_fresh(stamp, NOW) is False


def test_a_recent_stamp_is_young() -> None:
    """Обратная сторона: прочитанная свежая отметка срок даёт (097)."""
    recent = (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    assert module.is_fresh(recent, NOW) is True


def test_the_registry_says_empty_rather_than_printing_nothing() -> None:
    """Пустой реестр говорит «пусто», а не выглядит незаполненным (154)."""
    body = module.render_body([], NOW)
    assert module.MARKER in body
    assert "Пусто" in body


def test_the_registry_names_the_reason_of_every_entry() -> None:
    """Запись реестра несёт причину, а не один номер."""
    body = module.render_body([module.Verdict(7, True, module.STUCK_UNARMED)], NOW)
    assert "#7" in body
    assert module.STUCK_UNARMED in body


def test_the_neighbour_is_named_in_the_registry() -> None:
    """Реестр называет соседа: читатель не должен гадать, где своё красное (195)."""
    assert "hail.py" in module.render_body([], NOW)
