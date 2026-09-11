"""Живая задача-адресат находок: одна, и найденная по маркеру.

Механизм обещает ОДНУ живую задачу. Две — это не выбор, а происшествие: часть
записей лежит там, куда никто не смотрит, и адресат, размноженный надвое, —
это отсутствующий адресат (142).

Здесь проверяется место, где вторая заводится: разница между «список пуст» и
«в списке нет нашей».
"""

from __future__ import annotations

import pytest

from tests.conftest import load_script

module = load_script("findings.py")


def test_an_empty_answer_is_not_an_absent_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой ответ площадки — не «задачи нет», а подозрительный ответ.

    Список открытых записей у живого проекта пуст не бывает: там всегда есть
    хотя бы сама эта задача. Ноль записей означает, что площадка отдала 200 с
    пустым телом, и принять это за отсутствие — тихий запасной ответ (045).

    Замер 10.09.2026: заход в 15:00:50 не нашёл #23, завёл #139 и переписал в
    неё 47 записей. Уникального в дубле не оказалось ни одного — все они уже
    лежали в #23, и следующий заход снова писал туда. Адресат, размноженный
    надвое, — это отсутствующий адресат (142).
    """
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([]))
    with pytest.raises(module.ghrest.TransportError):
        module.live_issue("o/r", "token")


def test_a_non_empty_answer_without_our_task_is_an_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Задачи есть, нашей среди них нет — вот это законное отсутствие.

    Разница между «список пуст» и «в списке нет нашей» — то самое место, где
    механизм либо заводит нужную задачу, либо плодит вторую живую.
    """
    monkeypatch.setattr(
        module.ghrest,
        "paginate",
        lambda *_, **__: iter([{"number": 7, "body": "чужая задача"}]),
    )
    assert module.live_issue("o/r", "token") == (None, "")


def test_a_listing_of_only_changes_is_not_an_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    """В ответе одни ИЗМЕНЕНИЯ и ни одной задачи — это не «задачи нет» (находка #144).

    Ветка `seen` считает ЗАПИСИ ответа, а не задачи: изменения приходят в том
    же списке и отсеиваются ниже. Если площадка отдала только их, счёт записей
    ненулевой, и отсутствие нашей задачи законно — заводить вторую живую не
    нужно. Ветка не была покрыта ничем, а разница здесь та же, что стоила
    дубля #139: «пусто» и «нашей нет» — разные состояния (045).
    """
    monkeypatch.setattr(
        module.ghrest,
        "paginate",
        lambda *_, **__: iter([{"number": 7, "body": "", "pull_request": {"url": "…"}}]),
    )
    assert module.live_issue_seen("o/r", "token") == (None, "", "")


def test_an_empty_answer_is_suspicious_for_the_dated_reader_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Тот же запрет на пустой ответ держится и у чтения с датой.

    Два входа в один источник расходятся тем охотнее, чем невиннее выглядят
    (022): здесь проверяется, что строгость у них одна.
    """
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([]))
    with pytest.raises(module.ghrest.TransportError):
        module.live_issue_seen("o/r", "token")


def test_the_earliest_live_task_wins_and_the_rest_are_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Живых задач несколько — пишем в самую раннюю и называем лишние (154)."""
    rows = [
        {"number": 139, "body": module.MARKER, "updated_at": "b"},
        {"number": 23, "body": module.MARKER, "updated_at": "a"},
    ]
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter(rows))
    number, _, seen = module.live_issue_seen("o/r", "token")
    assert (number, seen) == (23, "a")
    assert "#139" in capsys.readouterr().err


def test_every_registry_marker_is_built_from_one_phrase() -> None:
    """Метка живой задачи собирается из одной фразы, а не повторяется в пяти модулях.

    Фразу повторяли дословно реестр находок, «входящие», непросмотренное,
    краснота общей ветки и дрейф. Разошлись бы они молча: задача с чуть иной
    фразой просто перестала бы находиться (022, 090).
    """
    for name in ("main_red.py", "unlooked.py", "drift.py"):
        other = load_script(name)
        assert module.is_kept_by_a_mechanism(other.MARKER), (
            f"{name}: метка собрана мимо общей фразы"
        )
    assert module.is_kept_by_a_mechanism(module.MARKER)
    assert module.is_kept_by_a_mechanism(module.INBOX_MARKER)


def test_a_plain_body_is_not_kept_by_a_mechanism() -> None:
    """Обычная задача машинной не считается: признак — метка, а не догадка."""
    assert not module.is_kept_by_a_mechanism("задача человека с прозой\n- раз\n- два")
    assert not module.is_kept_by_a_mechanism("")
