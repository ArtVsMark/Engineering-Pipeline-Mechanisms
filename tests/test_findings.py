"""Живая задача-адресат находок: одна, и найденная по маркеру.

Механизм обещает ОДНУ живую задачу. Две — это не выбор, а происшествие: часть
записей лежит там, куда никто не смотрит, и адресат, размноженный надвое, —
это отсутствующий адресат (142).

Здесь проверяется место, где вторая заводится: разница между «список пуст» и
«в списке нет нашей».
"""

from __future__ import annotations

from pathlib import Path

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


def test_the_role_survives_a_round_trip_through_the_entry_line() -> None:
    """Строка записи несёт роль `· глазами <роль>` и разбирается обратно (#763)."""
    entry = module.Entry(7, "риск", "предмет находки", role="архитектор")
    line = entry.said()
    assert f"· {module.ROLE_SAID} архитектор" in line
    back = module.parse_entries(f"- `abc1234` {line}")
    assert [one.role for one in back.values()] == ["архитектор"]
    bare = module.Entry(7, "риск", "без роли").said()
    plain = module.parse_entries(f"- `abc1234` {bare}")
    assert [one.role for one in plain.values()] == [""]


def test_roles_are_read_from_the_profiles_of_the_role_map(tmp_path: Path) -> None:
    """Роли — заголовки профилей карты, и только из раздела «Профили»."""
    card = tmp_path / "roles.md"
    card.write_text(
        "# Карта\n\n### 🧭 Не профиль\n\n## Профили\n\n### 🏛 Архитектор\n\n"
        "### 🧪 Тестировщик\n\n## Стыки\n\n### 🔌 Тоже не профиль\n",
        encoding="utf-8",
    )
    assert module.roles(card) == frozenset({"архитектор", "тестировщик"})
    assert module.roles(tmp_path / "нет.md") == frozenset()


def test_read_archive_checks_the_shape(tmp_path: Path) -> None:
    """Архив читается одним чтением с проверкой формы; чужая форма — `ValueError`."""
    path = tmp_path / "module.json"
    path.write_text('{"counted": [1], "findings": {"a": {"seen_on": [1]}}}', encoding="utf-8")
    assert module.read_archive(path)["counted"] == [1]
    path.write_text('{"counted": [true]}', encoding="utf-8")
    with pytest.raises(ValueError, match="не число"):
        module.read_archive(path)
    with pytest.raises(ValueError, match="не прочитан"):
        module.read_archive(tmp_path / "нет.json")


def test_unfilled_finds_only_the_fill_gap() -> None:
    """Неполнота — только строка наполнения; граница верификатора ею не считается."""
    gap = f"{module.UNFILLED}: не учтено слитых изменений — 3"
    assert module.unfilled({"gaps": ["ответы верификатора …", gap]}) == gap
    assert module.unfilled({"gaps": ["ответы верификатора …"]}) == ""


def test_read_archive_refuses_a_scalar_where_a_list_is(tmp_path: Path) -> None:
    """Скаляр вместо списка — отказ с причиной, а не трасса или обход по символам (#817)."""
    path = tmp_path / "findings.json"
    for said in (
        '{"counted": 5}',
        '{"gaps": "наполнение не дошло"}',
        '{"findings": {"a": {"seen_on": 3}}}',
    ):
        path.write_text(said, encoding="utf-8")
        with pytest.raises(ValueError, match="не список"):
            module.read_archive(path)
