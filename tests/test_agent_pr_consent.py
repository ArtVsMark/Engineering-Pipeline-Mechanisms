"""Согласие отдать изменение очереди ставит механизм, а снимает человек.

Ветка с приставкой конвейера и есть заявленное согласие: окно резало её под
задачу, а не для того, чтобы зелёное изменение стояло и ждало метки. Ждать
руки значит вернуть ровно ту беду, от которой очередь заведена, — и у соседа
по семье это уже пройдено: там согласие ставится сразу при открытии.

Обратное направление тоньше и важнее. Отличить «метку ещё не ставили» от
«поставили и сняли» по состоянию изменения нельзя — оно одинаковое, — поэтому
снятое человеком согласие вернулось бы следующим толчком, и отмена не работала
бы вовсе. Отзыв выражается явно стоп-меткой, и она сильнее
([147](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/147-a-cancelling-switch-needs-an-addressee.md)).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("agent_pr.py")


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    """Записывает обращения к площадке вместо того, чтобы их выполнять."""
    seen: list[tuple[str, str, Any]] = []

    def remember(method: str, path: str, token: str, body: Any = None) -> Any:
        seen.append((method, path, body))
        return {}

    monkeypatch.setattr(module.ghrest, "request", remember)
    return seen


def test_a_fresh_change_is_handed_to_the_queue(platform: list[tuple[str, str, Any]]) -> None:
    """Только что открытому изменению согласие ставится сразу."""
    module.apply_consent("о/р", 7, "токен", set(), dry_run=False)
    assert platform == [("POST", "repos/о/р/issues/7/labels", {"labels": [module.CONSENT]})]


def test_the_stop_label_takes_the_consent_off(platform: list[tuple[str, str, Any]]) -> None:
    """Стоп-метка не просто держит очередь — она снимает согласие.

    Иначе след врёт: изменение помечено отданным автоматике, а автоматика его
    не двигает, и по меткам этого не видно.
    """
    module.apply_consent("о/р", 7, "токен", {module.HOLD, module.CONSENT}, dry_run=False)
    method, path, _ = platform[0]
    assert method == "DELETE" and path.endswith(f"/labels/{module.CONSENT}")


def test_a_refused_label_does_not_lose_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ разметки не роняет шаг: изменение уже открыто (084).

    Потерять открытие из-за метки — худший размен: метку поставит человек, а
    заново открытое изменение сменит автора.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.apply_consent("о/р", 7, "токен", set(), dry_run=False)


def test_a_dry_run_touches_nothing(platform: list[tuple[str, str, Any]]) -> None:
    """Пробный заход площадку не трогает — ни в ту, ни в другую сторону."""
    module.apply_consent("о/р", 7, "токен", set(), dry_run=True)
    module.apply_consent("о/р", 7, "токен", {module.HOLD}, dry_run=True)
    assert platform == []


def test_nothing_to_remove_is_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Согласия нет и стоп-метка на месте — обычное состояние повторного захода.

    Толчков в ветку с висящей стоп-меткой бывает много, и каждый звал снятие
    уже снятой метки: площадка отвечала отказом, а механизм жаловался на
    исправно работающую отмену (045).
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("снимать нечего — площадку звать незачем")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.apply_consent("о/р", 7, "токен", {module.HOLD}, dry_run=False)
    assert "не будет" in capsys.readouterr().out


def test_a_lost_race_is_the_same_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Метку сняли раньше нас — тот же успех, достигнутый не нами."""

    def gone(*args: object, **kwargs: object) -> None:
        raise module.ghrest.NotFound("404")

    monkeypatch.setattr(module.ghrest, "request", gone)
    module.apply_consent("о/р", 7, "токен", {module.HOLD, module.CONSENT}, dry_run=False)
    printed = capsys.readouterr().out
    assert "уже нет" in printed and "не снято" not in printed


def test_a_real_refusal_on_removal_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Настоящий отказ транспорта называется отказом, а не «уже снято» (045)."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.apply_consent("о/р", 7, "токен", {module.HOLD, module.CONSENT}, dry_run=False)
    assert "не снято" in capsys.readouterr().out
