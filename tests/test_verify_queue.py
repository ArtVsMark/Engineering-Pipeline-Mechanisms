"""Верификатор по плану: кого звать, сколько раз за сутки и что не уходит во вход (#1005).

Решение владельца 04.10.2026, вариант 3. Обе половины: зовётся висящая
находка по слитому без отметки верификатора — и не зовутся свежая, уже
проверенная, по открытому изменению и с чужой формой отпечатка; потолок суток
считается по именам прогонов.
"""

import random
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
    merged = {1: "2026-10-01T00:00:00Z", 2: "2026-09-01T00:00:00Z"}
    queue = module.candidates({"aaaaaaa": entry(1), "bbbbbbb": entry(2)}, merged, NOW)
    assert queue == ["bbbbbbb", "aaaaaaa"]


@pytest.mark.parametrize(
    ("mark", "item", "merged"),
    [
        ("aaaaaaa", entry(1), {1: "2026-10-09T00:00:00Z"}),
        ("aaaaaaa", entry(1, checked="премиса подтверждена"), {1: "2026-10-01T00:00:00Z"}),
        ("aaaaaaa", entry(3), {}),
        ("не-метка", entry(1), {1: "2026-10-01T00:00:00Z"}),
        ("bbbbbbb", entry(1), {1: "2026-10-01T00:00:00Z"}),
    ],
    ids=["свежая", "уже-проверена", "не-слито", "чужая-форма", "звалась-недавно"],
)
def test_what_is_not_called(mark: str, item: Any, merged: dict[int, str]) -> None:
    """Вторая половина: свежую, проверенную, неслитую, чужую форму и недавно звавшуюся не зовут."""
    assert module.candidates({mark: item}, merged, NOW, frozenset({"bbbbbbb"})) == []


def test_every_manual_launch_of_the_day_counts_toward_the_cap() -> None:
    """В потолок идёт каждый ручной запуск суток, с именем или без (взгляд на #1115).

    Копия `review.yml` у потребителя может быть старше `run-name`, и запуски
    звались бы «review»: считай потолок по имени — его бы не было.
    """
    runs = [
        {"display_title": "verify aaaaaaa", "created_at": "2026-10-10T01:00:00Z"},
        {"display_title": "verify bbbbbbb", "created_at": "2026-10-09T23:59:00Z"},
        {"display_title": "review", "created_at": "2026-10-10T02:00:00Z"},
    ]
    assert module.launched_today(runs, NOW) == 2
    assert module.recently_called(runs) == {"aaaaaaa", "bbbbbbb"}


def test_merged_dates_ask_outside_the_window_and_skip_the_unmerged() -> None:
    """Вне окна дата спрашивается, а не выводится; открытое и неслитое не входят (#1115).

    Окно упорядочено по созданию: давнее изменение, слитое вчера, в него не
    попадает, и прежний вывод «вне окна — давно» звал бы его первым.
    """
    window = [
        {"number": 50, "merged_at": "2026-10-05T00:00:00Z"},
        {"number": 49, "merged_at": None},
    ]
    asked: list[int] = []

    def ask(number: int) -> str | None:
        asked.append(number)
        return {10: "2026-10-09T00:00:00Z"}.get(number)

    said, unasked = module.merged_dates({50, 49, 10, 11, 12}, window, {12}, ask)
    assert unasked == 0
    assert said == {50: "2026-10-05T00:00:00Z", 10: "2026-10-09T00:00:00Z"}
    assert sorted(asked) == [10, 11], "спрошено лишнее или не спрошено нужное"


def fake_platform(
    monkeypatch: pytest.MonkeyPatch, runs: list[dict[str, Any]], marks: dict[str, Any]
) -> list[dict[str, Any]]:
    """Площадка: реестр, окно слитых, открытые, запуски, настройки — и запись вызовов."""
    called: list[dict[str, Any]] = []
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.findings, "live_issue", lambda *_: (23, "тело"))
    monkeypatch.setattr(module.findings, "parse_entries", lambda _body: marks)
    monkeypatch.setattr(module.ghrest, "merged_page", lambda *_: ([], []))

    def paginate(path: str, *_: object, **__: object) -> Any:
        return iter(runs if "runs" in path else [])

    monkeypatch.setattr(module.ghrest, "paginate", paginate)

    def request(method: str, path: str, _token: str, body: Any = None) -> Any:
        if method == "GET" and "/pulls/" in path:
            return {"merged_at": "2026-09-01T00:00:00Z"}
        if method == "GET":
            return {"default_branch": "trunk"}
        called.append({"method": method, "path": path, "body": body})
        return None

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
    assert called[0]["body"]["ref"] == "trunk", "ветка вызова не взята у площадки"


def test_no_room_reads_nothing_more(monkeypatch: pytest.MonkeyPatch) -> None:
    """Потолок выбран — реестр и даты не читаются вовсе (#1115)."""
    runs = [{"display_title": "review", "created_at": f"{datetime.now(UTC).date()}T00:00:00Z"}]
    called = fake_platform(monkeypatch, runs * module.DAILY_CAP, {"0000001": entry(101)})
    monkeypatch.setattr(module.findings, "live_issue", lambda *_: pytest.fail("читал реестр"))
    assert module.main(["--repo", "o/r"]) == module.EXIT_OK
    assert called == []


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


def test_a_verifier_call_does_not_walk_the_late_queue() -> None:
    """Кнопка с отпечатком — проверка одной находки: обход очереди с ней не идёт (#1115)."""
    import yaml

    from tests.conftest import ROOT

    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "review.yml").read_text("utf-8"))
    condition = " ".join(str(flow["jobs"]["late-queue"]["if"]).split())
    assert "(github.event_name == 'workflow_dispatch' && inputs.mark == '')" in condition
    # Голое `|| github.event_name == 'workflow_dispatch'` рядом с новой формой
    # снова пускало бы кнопку верификатора: ручной запуск назван ровно раз (#1121).
    assert condition.count("github.event_name == 'workflow_dispatch'") == 1, condition


def test_asks_are_bounded_and_the_rest_is_named() -> None:
    """Спросов не больше потолка; остаток назван числом (#1121)."""
    asked: list[int] = []

    def ask(number: int) -> str | None:
        asked.append(number)
        return "2026-09-01T00:00:00Z"

    said, unasked = module.merged_dates({5, 3, 4, 1, 2}, [], set(), ask, limit=2)
    assert len(asked) == 2 and set(said) == set(asked) and unasked == 3


def test_a_number_the_platform_no_longer_has_is_not_merged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """404 на номер находки — «не слито», а не сбой всего захода (#1121)."""
    fake_platform(monkeypatch, [], {"0000001": entry(101), "0000002": entry(102)})

    def request(method: str, path: str, _token: str, body: Any = None) -> Any:
        if path.endswith("/pulls/101"):
            raise module.ghrest.NotFound("404")
        if "/pulls/" in path:
            return {"merged_at": "2026-09-01T00:00:00Z"}
        if method == "GET":
            return {"default_branch": "trunk"}
        return None

    monkeypatch.setattr(module.ghrest, "request", request)
    assert module.main(["--repo", "o/r", "--dry-run"]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "0000002" in said, "404 на соседний номер погасил остальных"
    assert "0000001" not in said


def test_asks_are_a_sample_bounded_by_the_cap() -> None:
    """Спрос берёт выборку не больше потолка и только из номеров вне окна (#1127)."""
    given: list[tuple[list[int], int]] = []

    def pick(population: list[int], k: int) -> list[int]:
        given.append((list(population), k))
        return population[-k:]

    seen: list[int] = []

    def ask(number: int) -> str | None:
        seen.append(number)
        return None

    module.merged_dates({1, 2, 3, 4, 5}, [{"number": 5}], {4}, ask, limit=2, pick=pick)
    assert given == [([1, 2, 3], 2)] and seen == [2, 3]
    module.merged_dates({1}, [], set(), ask, limit=2, pick=pick)
    assert given[-1] == ([1], 1), "выборка больше набора"


def test_no_number_is_silent_forever_whatever_the_schedule() -> None:
    """Ни пропуск заходов, ни перемены набора не оставляют номер неспрошенным (#1127).

    Ровно те условия, на которых круг по часу немел: заходы только в чётные
    часы и набор, который растёт и теряет номера между заходами. Выборка с
    закреплённым зерном — чтобы прогон был воспроизводим, а не «обычно зелён».
    """
    rng = random.Random(1127)
    asked: set[int] = set()

    def ask(number: int) -> str | None:
        asked.add(number)
        return None

    numbers = set(range(1, 41))
    for run in range(0, 400, 2):
        live = {run % 40 + 1}
        numbers |= {41 + run // 50}
        module.merged_dates(numbers, [], live, ask, limit=4, pick=rng.sample)
    assert numbers - asked == set(), f"неспрошены навсегда: {sorted(numbers - asked)}"


def test_recently_called_findings_cost_no_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Звавшаяся за `RECALL_DAYS` находка отсеяна до спроса даты (#1123)."""
    runs = [{"display_title": "verify 0000001", "created_at": "2026-09-30T00:00:00Z"}]
    fake_platform(monkeypatch, runs, {"0000001": entry(101)})
    asked: list[str] = []

    def request(method: str, path: str, _token: str, body: Any = None) -> Any:
        if "/pulls/" in path:
            asked.append(path)
            return {"merged_at": "2026-09-01T00:00:00Z"}
        if method == "GET":
            return {"default_branch": "trunk"}
        return None

    monkeypatch.setattr(module.ghrest, "request", request)
    assert module.main(["--repo", "o/r", "--dry-run"]) == module.EXIT_OK
    assert asked == [], "спросили дату у находки, которую звать не будут"
