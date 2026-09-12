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
        (change(labels=[{"name": "hold"}], body="Ждёт: #262"), [], module.WHY_HOLD),
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


def test_the_head_time_is_read_from_the_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отметка берётся у коммита головы, а не у изменения.

    `updated_at` изменения двигает любой комментарий, и срок по нему обнулялся
    бы разговором, а не работой.
    """
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda *a, **k: {"commit": {"committer": {"date": "2026-09-12T11:00:00Z"}}},
    )
    assert module.head_time("o/r", "deadbee", "t") == "2026-09-12T11:00:00Z"


def test_an_unasked_head_time_is_empty_not_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не спросили — не угадываем: пустая отметка, а не «только что».

    Подставить текущее время значило бы выдать «изменение свежее» за
    прочитанное и замолчать застрявшее ровно там, где площадка не ответила
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Пустая отметка читается как СТАРАЯ — разбор идёт, а не отменяется.
    """

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    assert module.head_time("o/r", "deadbee", "t") == ""
    assert module.is_fresh("", NOW) is False


def test_marks_read_a_change_without_labels() -> None:
    """Меток может не быть вовсе, и это пустое множество, а не отказ.

    Ключ `labels` площадка отдаёт пустым списком, но у сухого захода и у
    подделки его может не быть ключом — разбор не должен на этом падать.
    """
    assert module.marks_of({}) == set()
    assert module.marks_of({"labels": [{"name": "hold"}, {"name": "automerge"}]}) == {
        "hold",
        "automerge",
    }


def test_a_dry_sweep_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без ключа записи реестр не трогается вовсе — только называется намерение.

    Необратимого здесь нет, но тело живой задачи — общий ресурс, и сухой заход,
    молча его переписывающий, отличался бы от настоящего только выводом.
    """
    calls: list[str] = []

    def note(method: str, path: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append(f"{method} {path}")
        return {}

    monkeypatch.setattr(module.findings, "live_issue", lambda *a, **k: (77, ""))
    monkeypatch.setattr(module.ghrest, "request", note)
    module.save("o/r", "t", [module.Verdict(7, True, module.STUCK_ARMED)], NOW, apply=False)
    assert calls == []


def test_an_applied_sweep_updates_the_living_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """С ключом — обновляет по месту, а не заводит вторую задачу (022)."""
    calls: list[tuple[str, str]] = []

    def note(method: str, path: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append((method, path))
        return {}

    monkeypatch.setattr(module.findings, "live_issue", lambda *a, **k: (77, ""))
    monkeypatch.setattr(module.ghrest, "request", note)
    module.save("o/r", "t", [], NOW, apply=True)
    assert calls == [("PATCH", "repos/o/r/issues/77")]


def held(body: str) -> dict[str, Any]:
    """Изменение, остановленное меткой, с названным (или нет) условием."""
    return change(labels=[{"name": "hold"}], body=body)


def test_a_stop_switch_that_names_nothing_has_no_addressee() -> None:
    """Стоп-метка без строки «Ждёт:» — отменяющий переключатель без адресата.

    Это ТРЕТИЙ исход, а не «остановлено»: поставивший знает, чего ждёт, а через
    неделю не знает никто, и снять такую метку механизму нечем
    ([147](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/147-a-cancelling-switch-needs-an-addressee.md)).
    """
    said = verdict(held("обычное тело без условия"), [])
    assert said.stuck
    assert said.why == module.STUCK_HOLD_MUTE
    assert not said.lift


def test_a_named_and_open_subject_keeps_the_switch_down() -> None:
    """Названное открыто — стоп-кран осознан, и шаг молчит."""
    said = verdict(held("Ждёт: #262"), [], lifted=False)
    assert not said.stuck
    assert said.why == module.WHY_HOLD
    assert not said.lift


def test_a_named_and_closed_subject_lifts_the_switch() -> None:
    """Названное закрыто — снимать больше не о чем, и метка снимается (018)."""
    said = verdict(held("Ждёт: #262"), [], lifted=True)
    assert not said.stuck
    assert said.why == module.WHY_HOLD_LIFTED
    assert said.lift


def test_free_text_is_a_named_reason_but_not_a_resolvable_one() -> None:
    """Свободный текст — законный второй исход: причина есть, спросить нечего."""
    assert module.waits_for("Ждёт: пока вернётся владелец") == "пока вернётся владелец"
    assert module.named_subject("пока вернётся владелец") == 0
    assert module.named_subject("#262") == 262


def test_the_first_named_condition_is_the_one() -> None:
    """Читается ПЕРВАЯ строка: два условия означали бы снятие по половине."""
    assert module.waits_for("Ждёт: #262\nЖдёт: #99") == "#262"


def test_an_unasked_subject_counts_as_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не спросили — считаем открытым: чужую остановку по незнанию не снимают.

    Вернуть стоп-кран может только человек, и «закрыто», выведенное из отказа
    площадки, стоило бы слитого изменения, которого не ждали (045).
    """

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    assert module.is_settled("o/r", 262, "t") is False


def test_a_closed_subject_is_read_as_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обратная сторона: прочитанное закрытое читается закрытым (097)."""
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: {"state": "closed"})
    assert module.is_settled("o/r", 262, "t") is True


def test_lifting_returns_the_consent_the_switch_took(monkeypatch: pytest.MonkeyPatch) -> None:
    """Снятие возвращает согласие: его снял сам стоп-кран, а не человек.

    Убрать причину и оставить следствие значило бы, что снятия нет, — есть
    уборка мусора, после которой изменение стоит так же, только молча (018).
    """
    calls: list[tuple[str, str]] = []

    def note(method: str, path: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append((method, path))
        return {}

    monkeypatch.setattr(module.ghrest, "request", note)
    module.lift_hold("o/r", 7, "t", apply=True)
    assert calls == [
        ("DELETE", "repos/o/r/issues/7/labels/hold"),
        ("POST", "repos/o/r/issues/7/labels"),
    ]


def test_a_dry_lift_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без ключа записи чужая метка не трогается — только называется намерение."""
    calls: list[str] = []

    def note(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append("тронул")
        return {}

    monkeypatch.setattr(module.ghrest, "request", note)
    module.lift_hold("o/r", 7, "t", apply=False)
    assert calls == []


def test_a_refused_lift_does_not_stop_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ снятия не роняет обход: остальные изменения ещё не посмотрены (084)."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.lift_hold("o/r", 7, "t", apply=True)


def test_a_draft_is_not_paid_for_with_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Черновик со стоп-меткой не стоит обходу вопроса о названном условии.

    `judge` отбрасывает черновик первым же условием, и состояние названного
    никто не прочтёт: запрос был бы платой за ответ, который выбрасывают.
    Нашёл внешний взгляд на #264.
    """
    asked: list[str] = []

    def answer(_method: str, path: str, *_args: object, **_kwargs: object) -> dict[str, Any]:
        asked.append(path)
        if path.endswith("/commits/deadbee"):
            return {"commit": {"committer": {"date": "2026-09-12T09:00:00Z"}}}
        if "check-runs" in path:
            return {"check_runs": []}
        return {
            "number": 42,
            "draft": True,
            "mergeable_state": "clean",
            "labels": [{"name": "hold"}],
            "body": "Ждёт: #7",
            "auto_merge": None,
            "head": {"sha": "deadbee"},
        }

    monkeypatch.setattr(module.ghrest, "paginate", lambda *a, **k: iter([{"number": 42}]))
    monkeypatch.setattr(module.ghrest, "request", answer)
    seen = module.sweep("o/r", "t", NOW)
    assert [item.why for item in seen] == [module.WHY_DRAFT]
    assert not [path for path in asked if path.endswith("issues/7")], (
        f"состояние названного спрошено у черновика: {asked}"
    )
