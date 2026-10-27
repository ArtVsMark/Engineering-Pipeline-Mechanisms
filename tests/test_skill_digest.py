"""Недельная сводка навыков: ряд с размером выборки, семья поимённо, текст человека цел (#1694)."""

from datetime import date
from typing import Any

import pytest

from tests.conftest import RunScript, load_script

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
    assert said["2026-W44"]["a"] == [2, 1, 0]
    assert said["2026-W44"]["b"] == [1, 0, 0]
    assert said["2026-W44"]["c"] == [0, 0, 1]
    assert said["2026-W43"]["b"] == [1, 1, 0]
    assert said["?"]["a"] == [1, 1, 0], "день не разобран — своя строка, а не нынешняя неделя"


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
