"""Верификатор по плану: кого звать, сколько раз за сутки и что не уходит во вход (#1005).

Решение владельца 04.10.2026, вариант 3. Обе половины: зовётся висящая
находка по слитому без отметки верификатора — и не зовутся свежая, уже
проверенная, по открытому изменению и с чужой формой отпечатка; потолок суток
считается по именам прогонов.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("verify_queue.py")
findings = load_script("findings.py")

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def entry(pr: int, checked: str = "") -> Any:
    """Запись реестра: изменение, вес, заголовок и хвост проверки."""
    return findings.Entry(pr=pr, weight="риск", title="x — y", checked=checked)


def test_a_stale_unchecked_finding_on_merged_work_is_called() -> None:
    """Слитое раньше срока, без отметки — к проверке; старые идут первыми."""
    merged = {1: "2026-10-01T00:00:00Z", 2: module.LONG_AGO}
    queue = module.candidates({"aaaaaaa": entry(1), "bbbbbbb": entry(2)}, merged, NOW)
    assert queue == ["bbbbbbb", "aaaaaaa"]


@pytest.mark.parametrize(
    ("mark", "item", "merged"),
    [
        ("aaaaaaa", entry(1), {1: "2026-10-09T00:00:00Z"}),
        ("aaaaaaa", entry(1, checked="премиса подтверждена"), {1: "2026-10-01T00:00:00Z"}),
        ("aaaaaaa", entry(3), {}),
        ("не-метка", entry(1), {1: "2026-10-01T00:00:00Z"}),
    ],
    ids=["свежая", "уже-проверена", "не-слито", "чужая-форма"],
)
def test_what_is_not_called(mark: str, item: Any, merged: dict[int, str]) -> None:
    """Вторая половина: свежую, проверенную, неслитую и чужую форму не зовут (085)."""
    assert module.candidates({mark: item}, merged, NOW) == []


def test_launches_are_counted_by_run_name_within_the_day() -> None:
    """Потолок считается по имени прогона за текущие сутки UTC, а не памятью захода."""
    runs = [
        {"display_title": "verify aaaaaaa", "created_at": "2026-10-10T01:00:00Z"},
        {"display_title": "verify bbbbbbb", "created_at": "2026-10-09T23:59:00Z"},
        {"display_title": "review", "created_at": "2026-10-10T02:00:00Z"},
    ]
    assert module.launched_today(runs, NOW) == 1


def test_merged_dates_take_two_reads_not_one_per_change() -> None:
    """Дата — из окна закрытых; старше окна и не открыто — давно; открытое и неслитое — нет."""
    window = [
        {"number": 50, "merged_at": "2026-10-05T00:00:00Z"},
        {"number": 49, "merged_at": None},
        {"number": 40, "merged_at": "2026-10-01T00:00:00Z"},
    ]
    said = module.merged_dates({50, 49, 40, 10, 12}, window, live={12})
    assert said == {50: "2026-10-05T00:00:00Z", 40: "2026-10-01T00:00:00Z", 10: module.LONG_AGO}


def fake_platform(
    monkeypatch: pytest.MonkeyPatch, runs: list[dict[str, Any]], marks: dict[str, Any]
) -> list[dict[str, Any]]:
    """Площадка: реестр, окно слитых, открытые, запуски — и запись вызовов."""
    called: list[dict[str, Any]] = []
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.findings, "live_issue", lambda *_: (23, "тело"))
    monkeypatch.setattr(module.findings, "parse_entries", lambda _body: marks)
    monkeypatch.setattr(
        module.ghrest,
        "merged_page",
        lambda *_: ([], [{"number": 900, "merged_at": "2026-10-09T00:00:00Z"}]),
    )

    def paginate(path: str, *_: object, **__: object) -> Any:
        return iter(runs if "runs" in path else [])

    monkeypatch.setattr(module.ghrest, "paginate", paginate)

    def request(method: str, path: str, _token: str, body: Any = None) -> None:
        called.append({"method": method, "path": path, "body": body})

    monkeypatch.setattr(module.ghrest, "request", request)
    return called


def test_main_calls_no_more_than_the_room_left(monkeypatch: pytest.MonkeyPatch) -> None:
    """Осталось место на один запуск — зовётся один, самый старый, с отпечатком во входе."""
    marks = {f"{index:07x}": entry(100 + index) for index in range(1, 4)}
    runs = [
        {"display_title": "verify 0000aaa", "created_at": f"{datetime.now(UTC).date()}T00:00:00Z"}
    ] * (module.DAILY_CAP - 1)
    called = fake_platform(monkeypatch, runs, marks)
    assert module.main(["--repo", "o/r"]) == module.EXIT_OK
    assert len(called) == 1
    assert called[0]["path"] == "repos/o/r/actions/workflows/review.yml/dispatches"
    assert called[0]["body"]["inputs"]["mark"] in marks


def test_dry_run_calls_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пробный заход называет, кого позвал бы, и не зовёт никого."""
    called = fake_platform(monkeypatch, [], {"0000001": entry(101)})
    assert module.main(["--repo", "o/r", "--dry-run"]) == module.EXIT_OK
    assert called == []


def test_without_a_token_nobody_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без токена — свой исход, а не «звать некого» (045)."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r"]) == module.EXIT_UNSET


def test_a_refused_call_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ площадки в вызове — «не отработал»."""
    fake_platform(monkeypatch, [], {"0000001": entry(101)})

    def refuse(*_: object, **__: object) -> None:
        raise module.ghrest.TransportError("403")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN
