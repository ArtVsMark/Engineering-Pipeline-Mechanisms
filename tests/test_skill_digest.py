"""Недельная сводка навыков: ряд с размером выборки, семья поимённо, текст человека цел (#1694)."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, RunScript, load_script

module = load_script("skill_digest.py")

TODAY = date(2026, 10, 26)


def rec(pr: int, day: str, expected: list[str], invoked: list[str]) -> dict[str, Any]:
    """Запись той формы, что пишет `skill_record`."""
    return {"pr": pr, "merged_at": day, "expected": expected, "invoked": invoked}


def test_the_tally_counts_expected_invoked_and_unexpected_per_week() -> None:
    """Ждали, из них вызван, вызван без ожидания — по неделе слияния ISO."""
    said = module.tally(
        [
            rec(1, "2026-10-26", ["a", "b"], ["a", "c"]),
            rec(2, "2026-10-27", ["a"], []),
            rec(3, "2026-10-19", ["b"], ["b"]),
            rec(4, "не дата", ["a"], ["a"]),
        ]
    )
    assert said["2026-W44"][("?", "a")] == [2, 1, 0]
    assert said["2026-W44"][("?", "b")] == [1, 0, 0]
    assert said["2026-W44"][("?", "c")] == [0, 0, 1]
    assert said["2026-W43"][("?", "b")] == [1, 1, 0]
    assert said["?"][("?", "a")] == [1, 1, 0], (
        "день не разобран — своя строка, а не нынешняя неделя"
    )


def test_a_neighbours_row_is_not_folded_into_ours() -> None:
    """Записи соседа и свои — разными строками навыка: «по семье» читается по проектам."""
    records = [
        *module.mine("o/мы", [rec(1, "2026-10-26", ["a"], ["a"])]),
        *module.mine("o/сосед", [rec(7, "2026-10-26", ["a"], [])]),
    ]
    said = module.tally(records)["2026-W44"]
    assert said[("o/мы", "a")] == [1, 1, 0] and said[("o/сосед", "a")] == [1, 0, 0]
    text = module.block(records, [], [], TODAY)
    assert "| o/мы | `a` | 1 | 1 | 0 |" in text and "| o/сосед | `a` | 1 | 0 | 0 |" in text


def test_the_block_names_the_neighbours_it_could_not_read() -> None:
    """Сосед без записей и непрочитанный — поимённо, разными строками: незнание не ноль."""
    text = module.block([rec(1, "2026-10-26", ["a"], ["a"])], ["o/пуст"], ["o/молчит"], TODAY)
    assert text.startswith(module.BLOCK_START) and text.endswith(module.BLOCK_END)
    assert "Записей нет у соседей: o/пуст." in text and "**Не прочитаны:** o/молчит" in text
    assert "| `a` | 1 | 1 | 0 |" in text
    assert "ряд начнётся" in module.block([], [], [], TODAY)


def test_the_humans_text_outside_the_block_is_kept() -> None:
    """Блок переписывается между метками; вопросы человека ниже остаются как были."""
    fresh = module.block([], [], [], TODAY)
    first = module.body_with("", fresh)
    assert first.startswith(module.MARKER) and "## Вопросы и решения" in first
    human = first + "\n- почему #12 без навыка? — окно не знало признака\n"
    again = module.body_with(human, module.block([rec(1, "2026-10-26", ["a"], [])], [], [], TODAY))
    assert "почему #12 без навыка?" in again and "| `a` | 1 | 0 | 0 |" in again
    assert again.count(module.BLOCK_START) == 1
    lost = module.body_with(f"{module.MARKER}\nтекст без блока", fresh)
    assert lost.startswith(module.MARKER) and "текст без блока" in lost and fresh in lost


def test_gather_reads_ours_and_names_every_neighbour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свои — обязательно; сосед без файла — «записей нет», сосед с отказом — «не прочитан»."""

    def by_api(repo: str, name: str, token: str) -> dict[str, Any]:
        if repo == "o/нет":
            raise module.ghrest.NotFound("404")
        if repo == "o/сбой":
            raise module.ghrest.TransportError("503")
        return {"schema": 1, "records": [rec(1, "2026-10-26", ["a"], ["a"])]}

    monkeypatch.setattr(module.badges_read, "by_api", by_api)
    records, empty, unread = module.gather("o/мы", "t", ["o/нет", "o/сбой", "o/есть"])
    assert len(records) == 2 and empty == ["o/нет"] and unread == ["o/сбой"]

    def ours_broken(repo: str, name: str, token: str) -> dict[str, Any]:
        raise module.ghrest.TransportError("503")

    monkeypatch.setattr(module.badges_read, "by_api", ours_broken)
    with pytest.raises(module.NotRun, match="свои записи"):
        module.gather("o/мы", "t", [])


def test_the_same_state_is_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тот же блок другим днём — без записи; сухой заход ничего не пишет."""
    calls: list[str] = []
    current = module.body_with("", module.block([], [], [], date(2026, 10, 1)))
    monkeypatch.setattr(module.findings, "live_issue", lambda *_: (9, current))
    monkeypatch.setattr(module.ghrest, "request", lambda method, *_a, **_k: calls.append(method))
    module.save("o/мы", "t", module.block([], [], [], TODAY), apply=True)
    assert calls == []
    module.save(
        "o/мы", "t", module.block([rec(1, "2026-10-26", ["a"], [])], [], [], TODAY), apply=False
    )
    assert calls == []
    module.save(
        "o/мы", "t", module.block([rec(1, "2026-10-26", ["a"], [])], [], [], TODAY), apply=True
    )
    assert calls == ["PATCH"]


def test_main_without_a_token_is_the_third_outcome(run_script: RunScript) -> None:
    """Нет токена — исход 2 с причиной (039)."""
    run = run_script("skill_digest.py", env={"GH_TOKEN": "", "GITHUB_TOKEN": ""})
    assert run.code == module.EXIT_BROKEN and "нет токена" in run.text


def test_main_writes_the_digest_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Весь заход без семьи: свои записи — в задачу, исход 0 и счёт словами."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(
        module.badges_read,
        "by_api",
        lambda *_: {"schema": 1, "records": [rec(1, "2026-10-26", [], [])]},
    )
    monkeypatch.setattr(module.findings, "live_issue", lambda *_: (None, ""))
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: {"number": 3})
    assert module.main(["--repo", "o/мы", "--apply"]) == module.EXIT_OK
    assert "записей навыков: 1" in capsys.readouterr().out


def test_a_store_of_a_foreign_form_and_an_unread_day_are_named() -> None:
    """Файл не той формы — отказ, а не пустой ряд; день не разобран — неделя «?» (045)."""
    with pytest.raises(module.NotRun, match="форма"):
        module.records_of({"schema": 1, "records": {}})
    assert module.records_of({"records": [{"pr": 1}, "мусор"]}) == [{"pr": 1}]
    assert module.week_of("2026-10-26") == "2026-W44" and module.week_of("") == "?"


def test_the_unknown_week_goes_last_and_takes_no_place(tmp_path: Path) -> None:
    """Неделя «?» — после всех настоящих и вне счёта `WEEKS` (поздний взгляд на #1715)."""
    days = [f"2026-{month:02d}-15" for month in range(1, 13)]
    records = [rec(n, day, ["a"], ["a"]) for n, day in enumerate(days)] + [rec(99, "", ["a"], [])]
    text = module.block(records, [], [], TODAY)
    weeks = [line for line in text.splitlines() if line.startswith("### Неделя")]
    assert len(weeks) == module.WEEKS + 1 and weeks[-1] == "### Неделя ?"


def test_the_family_walk_stops_at_its_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Соседи за пределом обхода — «не прочитаны» поимённо и без вызова площадки."""
    asked: list[str] = []

    def by_api(repo: str, name: str, token: str) -> dict[str, Any]:
        asked.append(repo)
        return {"schema": 1, "records": []}

    monkeypatch.setattr(module.badges_read, "by_api", by_api)
    family = [f"o/n{one}" for one in range(module.FAMILY_AT_MOST + 2)]
    _, _, unread = module.gather("o/мы", "t", family)
    assert unread == family[module.FAMILY_AT_MOST :]
    assert len(asked) == 1 + module.FAMILY_AT_MOST


def test_the_schedule_estimate_matches_the_walk() -> None:
    """Оценка вызовов площадки в расписании — по пределу обхода, а не на глаз (005)."""
    said = json.loads((ROOT / ".rules" / "schedules.json").read_text(encoding="utf-8"))
    entry = said["runs"]["skills.yml"]
    assert entry["gh_calls_per_run"] == 2 + 2 + module.FAMILY_AT_MOST * 2 + 1
