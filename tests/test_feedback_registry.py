"""Реестр записей соседей: очередь на вердикт, первые встречи и непрочитанное (#1665).

Проверяется то, без чего реестр был бы распечаткой файла обхода: запись без
вердикта стоит в очереди, а с вердиктом — нет; день первой встречи переживает
сборку и не сбрасывается у соседа, которого этой ночью не видно; битый раздел
и непрочитанный клон названы, а не выданы за «записей нет» (045).
"""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import RunScript, load_script

module = load_script("feedback_registry.py")
form = module.feedback_form

TODAY = date(2026, 10, 26)


def record(slug: str = "x", kind: str = "false-refusal") -> dict[str, str]:
    """Запись соседа так, как её кладёт обход."""
    return {
        "slug": slug,
        "mechanism": "step-journal",
        "version": "v1.11.0",
        "kind": kind,
        "measured": "3 из 10",
        "trace": "o/a#4",
    }


def uptake(*blocks: dict[str, Any], unread: tuple[str, ...] = ()) -> dict[str, Any]:
    """Файл обхода с разделом `feedback`."""
    return {"projects": {"unread_repos": list(unread)}, "feedback": list(blocks)}


def test_records_broken_sections_and_unread_clones_are_read_apart() -> None:
    """Запись, битый раздел и непрочитанный клон — три разных состояния, а не одно «пусто»."""
    said = module.collected(
        uptake(
            {"repo": "O/A", "records": [record()], "broken": ""},
            {"repo": "o/b", "records": [], "broken": "раздел feedback: version 2"},
            unread=("o/c",),
        )
    )
    assert [row.key for row in said.rows] == ["o/a:false-refusal/x"]
    assert said.broken == {"o/b": "раздел feedback: version 2"}
    assert said.unseen() == {"o/b", "o/c"}


@pytest.mark.parametrize(
    "data",
    [
        {"projects": {}},
        [],
        {"feedback": [{"records": []}]},
        {"feedback": [{"repo": "o/a", "records": [{"slug": "x"}]}]},
    ],
)
def test_a_file_without_the_channel_is_a_refusal_not_an_empty_queue(data: Any) -> None:
    """Обход старше канала или запись не той формы — отказ: «записей нет» сказать нельзя (045)."""
    with pytest.raises(module.NotRun):
        module.collected(data)


def test_the_first_meeting_survives_and_an_unseen_neighbour_keeps_his_day() -> None:
    """Новый ключ — сегодня, прежний — свой день; у непрочитанного соседа день не сброшен."""
    said = module.collected(
        uptake(
            {"repo": "o/a", "records": [record("old"), record("new")], "broken": ""},
            {"repo": "o/b", "records": [], "broken": "битый"},
        )
    )
    before = {
        "o/a:false-refusal/old": date(2026, 10, 1),
        "o/a:false-refusal/gone": date(2026, 10, 2),
        "o/b:false-pass/hidden": date(2026, 10, 3),
    }
    assert module.seen_now(said, before, TODAY) == {
        "o/a:false-refusal/new": TODAY,
        "o/a:false-refusal/old": date(2026, 10, 1),
        "o/b:false-pass/hidden": date(2026, 10, 3),
    }


def test_the_body_queues_the_unjudged_and_keeps_its_days_readable() -> None:
    """Без вердикта — в очереди, с вердиктом — списком; блок дней читается обратно."""
    said = module.collected(
        uptake(
            {"repo": "o/a", "records": [record("waits"), record("done")], "broken": ""},
            {"repo": "o/b", "records": [], "broken": "битый"},
            unread=("o/c",),
        )
    )
    verdicts = {
        "o/a:false-refusal/done": form.Verdict("rejected", "зелёное законно"),
        "o/a:false-refusal/removed": form.Verdict("fixed", "v1.12.0"),
        "o/b:false-pass/hidden": form.Verdict("accepted", "v1.12.0"),
    }
    seen = module.seen_now(said, {"o/a:false-refusal/waits": date(2026, 10, 1)}, TODAY)
    body = module.render(said, verdicts, seen, TODAY)
    queue, rest = body.split("## С вердиктом", 1)
    assert "`o/a:false-refusal/waits`" in queue and "замечено 01.10.2026" in queue
    assert "`o/a:false-refusal/done`" in rest and "rejected: зелёное законно" in rest
    assert "o/b — раздел feedback: битый" in rest and "o/c — клон не прочитан" in rest
    # Сирота — только у прочитанного соседа: у o/b записей не видно, а не нет.
    assert "`o/a:false-refusal/removed`" in rest and "o/b:false-pass/hidden" not in rest
    assert module.seen_in(body) == seen
    assert body.startswith(module.MARKER)


def test_a_broken_days_block_costs_the_days_and_not_the_registry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Битый блок дней — сроки с сегодня и строка об этом, а не пропажа реестра (084)."""
    assert module.seen_in('<!-- feedback-seen: {"k": "не дата"} -->') == {}
    assert "не разобран" in capsys.readouterr().out
    assert module.seen_in("тело без блока") == {}


class Platform:
    """Площадка в памяти: живая задача и записанные запросы."""

    def __init__(self, number: int | None, body: str = "") -> None:
        self.number, self.body = number, body
        self.calls: list[tuple[str, str]] = []

    def live(self, *_: Any) -> tuple[int | None, str]:
        return self.number, self.body

    def request(self, method: str, path: str, *_: Any) -> dict[str, Any]:
        self.calls.append((method, path))
        return {"number": 7}


def saved(
    monkeypatch: pytest.MonkeyPatch, platform: Platform, said: Any, *, apply: bool = True
) -> list[tuple[str, str]]:
    """Зовёт `save` против площадки в памяти и отдаёт её запросы."""
    monkeypatch.setattr(module.findings, "live_issue", platform.live)
    monkeypatch.setattr(module.ghrest, "request", platform.request)
    module.save("o/us", "t", said, {}, apply=apply, today=TODAY)
    return platform.calls


def test_an_empty_registry_opens_no_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Записей нет и задачи нет — задача не заводится: адресат без записей — шум."""
    assert saved(monkeypatch, Platform(None), module.collected(uptake())) == []


def test_the_same_state_is_not_rewritten_and_a_new_one_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """То же состояние — без записи, хотя день сборки другой; новая запись — правка по месту."""
    said = module.collected(uptake({"repo": "o/a", "records": [record()], "broken": ""}))
    calls = saved(monkeypatch, Platform(None), said)
    assert calls == [("POST", "repos/o/us/issues")]
    seen = module.seen_now(said, {}, TODAY)
    # День сборки другой, а состояние то же: сверка его не читает.
    old = module.render(said, {}, seen, TODAY).replace(
        f"{module.DATED} 26.10.2026", f"{module.DATED} 01.10.2026"
    )
    assert saved(monkeypatch, Platform(5, old), said) == []
    more = module.collected(
        uptake({"repo": "o/a", "records": [record(), record("y")], "broken": ""})
    )
    assert saved(monkeypatch, Platform(5, old), more) == [("PATCH", "repos/o/us/issues/5")]
    assert saved(monkeypatch, Platform(5, old), more, apply=False) == []


def test_without_a_token_the_registry_is_not_run(run_script: RunScript, tmp_path: Path) -> None:
    """Нет токена — третий исход с причиной, а не пустой реестр (039)."""
    data = tmp_path / "uptake.json"
    data.write_text('{"feedback": []}', encoding="utf-8")
    run = run_script(
        "feedback_registry.py", "--uptake", str(data), env={"GH_TOKEN": "", "GITHUB_TOKEN": ""}
    )
    assert run.code == module.EXIT_BROKEN and "нет токена" in run.text
