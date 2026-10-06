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
    monkeypatch: pytest.MonkeyPatch,
    runs: list[dict[str, Any]],
    marks: dict[str, Any],
    memory: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Площадка: реестр, окно слитых, открытые, запуски, настройки, архив — и запись вызовов."""
    called: list[dict[str, Any]] = []
    monkeypatch.setattr(module.ghrest, "raw_json", lambda _url: {"merged": memory or {}})
    monkeypatch.setattr(module, "archive_by_api", lambda *_: {"merged": memory or {}})
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

    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "step-review.yml").read_text("utf-8"))
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


def test_every_number_outside_the_window_is_offered_to_the_sample() -> None:
    """Выборке в каждом заходе отдаётся ВЕСЬ набор вне окна — никто не исключён (#1127).

    Отсюда и обещание «вечной немоты нет»: номер, который в набор не попадал бы,
    не спрашивался бы никогда при любой выборке. Набор между заходами меняется —
    растёт, теряет открытый номер, — и каждый заход отдаёт выборке ровно его
    нынешний состав. Распределение внутри выборки — свойство `random.sample` и
    здесь не проверяется (поздний взгляд на #1129); что выборка по умолчанию —
    именно она, а не срез, держит `test_the_default_pick_reaches_every_number`.
    """
    given: list[list[int]] = []

    def pick(population: list[int], k: int) -> list[int]:
        given.append(sorted(population))
        return population[:k]

    numbers = set(range(1, 41))
    expected: list[list[int]] = []
    for turn in range(10):
        live = {turn + 1}
        numbers |= {41 + turn}
        expected.append(sorted(numbers - live))
        module.merged_dates(numbers, [], live, lambda number: None, limit=4, pick=pick)
    assert given == expected, "выборке отдан не весь набор вне окна"


#: Заходов в проверке выборки. Хватает ли их, решает утверждение в самом
#: тесте, а не число в комментарии: здесь оно устарело бы при правке (005).
TURNS = 300
#: Допустимая вероятность пропустить номер при исправной выборке.
MISS_BOUND = 1e-12


def test_the_default_pick_reaches_every_number() -> None:
    """Умолчание `pick` — выборка, а не срез: без подстановки спрошен каждый номер (#1123).

    Тесты выше подставляют свой `pick`, а `main` берёт умолчание. Срез
    `population[:k]` на его месте оставил бы набор зелёным и вернул вечную
    немоту старших номеров (взгляд на #1134). Зерно закрепляется у ОБЩЕГО
    генератора: умолчание связано с `random.sample` при определении функции,
    и подмена атрибута модуля его не тронула бы.

    ЧИСЛО ЗАХОДОВ — ИЗ ГРАНИЦЫ, А НЕ ИЗ ЗЕРНА (поздний взгляд на #1134,
    `7ce9724`). Сорок заходов по четыре спроса на сорок номеров покрывали все
    номера лишь с вероятностью около 0,55, и зелёным тест держало зерно. При
    `TURNS` заходах вероятность пропустить хоть один номер не больше
    `n · (1 − limit/n)^TURNS` (n — число номеров), и утверждение в начале
    теста требует, чтобы это было меньше `MISS_BOUND` — при ЛЮБОМ зерне и любой исправной выборке;
    зерно оставлено только для повторяемости. Срез `population[:k]` при этом
    спрашивает лишь номера 1–4 и краснеет на любом числе заходов.
    """
    numbers = set(range(1, 41))
    limit = 4
    # Границу держит машина, а не комментарий (005, взгляд на #1152,
    # `43f3ef3`): уменьши `TURNS` — краснеет здесь, а не молчит за зерном.
    assert len(numbers) * (1 - limit / len(numbers)) ** TURNS < MISS_BOUND, TURNS
    state = random.getstate()
    random.seed(1134)
    asked: set[int] = set()

    def ask(number: int) -> str | None:
        asked.add(number)
        return None

    try:
        for _ in range(TURNS):
            module.merged_dates(numbers, [], set(), ask, limit=limit)
    finally:
        random.setstate(state)
    assert asked == numbers, f"не спрошены ни разу: {sorted(numbers - asked)}"


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


def test_remembered_dates_are_taken_without_asking() -> None:
    """Номер из памяти архива берёт дату без спроса; спрашиваются только неизвестные (#1136)."""
    asked: list[int] = []

    def ask(number: int) -> str | None:
        asked.append(number)
        return None

    given: list[list[int]] = []

    def pick(population: list[int], k: int) -> list[int]:
        given.append(list(population))
        return population[:k]

    said, unasked = module.merged_dates(
        {1, 2, 3}, [], set(), ask, pick=pick, known={1: "2026-09-01T00:00:00+00:00"}
    )
    assert said == {1: "2026-09-01T00:00:00+00:00"}
    assert given == [[2, 3]] and sorted(asked) == [2, 3] and unasked == 0


def test_an_old_finding_is_queued_on_the_first_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Давняя находка вне окна встаёт в очередь в первом же заходе — по памяти, без спроса (#1136).

    Площадка на вопрос о дате отвечает провалом теста: дата обязана прийти из
    архива, а не из удачной выборки.
    """
    marks = {"0000abc": entry(7)}
    called = fake_platform(monkeypatch, [], marks, {"7": "2026-01-01T00:00:00+00:00"})
    fallback = module.ghrest.request

    def request(method: str, path: str, token: str, body: Any = None) -> Any:
        if method == "GET" and "/pulls/" in path:
            pytest.fail("дата спрошена у площадки, хотя есть в памяти")
        return fallback(method, path, token, body)

    monkeypatch.setattr(module.ghrest, "request", request)
    assert module.main(["--repo", "o/r"]) == module.EXIT_OK
    assert [one["body"]["inputs"]["mark"] for one in called] == ["0000abc"]


def test_an_unread_archive_leaves_no_memory_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Архив не прочитан или без поля — память пуста, и это сказано, а не отказ захода (045)."""

    def refuse(_url: str) -> dict[str, Any]:
        raise module.ghrest.TransportError("404")

    assert module.remembered("o/r", refuse) == {}
    assert module.remembered("o/r", lambda _url: {"findings": {}}) == {}
    assert module.remembered("o/r", lambda _url: {"merged": {"5": "d", "x": "e"}}) == {5: "d"}
    said = capsys.readouterr().out
    assert said.count("памяти дат нет") == 2


def test_the_platform_date_wins_over_memory() -> None:
    """Номер из окна берёт дату площадки, а не память: та помнит время коммитера (#1158)."""
    window = [{"number": 1, "merged_at": "2026-09-01T00:00:00Z"}]
    said, _ = module.merged_dates(
        {1, 2},
        window,
        set(),
        lambda _n: None,
        known={1: "2026-09-20T00:00:00+00:00", 2: "2026-08-01T00:00:00+00:00"},
    )
    assert said == {1: "2026-09-01T00:00:00Z", 2: "2026-08-01T00:00:00+00:00"}


def test_the_archive_is_read_by_the_api_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """С токеном архив читается API площадки — блобом, как в приватном репозитории (#1158)."""
    import base64
    import json

    content = base64.b64encode(json.dumps({"merged": {"5": "d"}}).encode()).decode()
    asked: list[str] = []

    def request(method: str, path: str, token: str, body: Any = None) -> Any:
        asked.append(path)
        if "/contents/" in path:
            return {"sha": "b10b"}
        return {"content": content}

    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module.ghrest, "raw_json", lambda _url: pytest.fail("прямая ссылка"))
    assert module.remembered("o/r", token="t") == {5: "d"}
    assert module.archive_by_api("o/r", "t") == {"merged": {"5": "d"}}
    assert asked[:2] == [
        "repos/o/r/contents/.github/badges/findings.json?ref=badges",
        "repos/o/r/git/blobs/b10b",
    ]


def test_an_unreadable_blob_leaves_no_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Блоба нет или он не JSON — памяти нет, заход идёт по окну (045)."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: {})
    assert module.remembered("o/r", token="t") == {}
    answers = iter([{"sha": "b"}, {"content": "не base64!"}])
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: next(answers))
    assert module.remembered("o/r", token="t") == {}
