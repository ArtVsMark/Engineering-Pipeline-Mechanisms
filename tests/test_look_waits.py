"""Взгляд — последним: ждёт вердикта сводного гейта головы (#762)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("look_waits.py")


def gate(*answers: list[dict[str, Any]]) -> Any:
    """Площадка, отвечающая записями гейта по очереди на каждый опрос."""
    left = list(answers)

    def paginate(path: str, *_rest: Any, **_kw: Any) -> Any:
        assert f"check_name={module.GATE}" in path
        return iter(left.pop(0) if len(left) > 1 else left[0])

    return paginate


DONE_GREEN = [{"status": "completed", "conclusion": "success"}]
DONE_RED = [{"status": "completed", "conclusion": "failure"}]
RUNNING = [{"status": "in_progress", "conclusion": None}]


@pytest.mark.parametrize(
    ("answers", "said"),
    [
        ([DONE_GREEN], module.GREEN),
        ([DONE_RED], module.RED),
        ([RUNNING, [], DONE_GREEN], module.GREEN),
        ([RUNNING], module.SILENT),
        (
            [
                [
                    {**DONE_GREEN[0], "started_at": "2026-09-24T10:00:00Z"},
                    {**DONE_RED[0], "started_at": "2026-09-24T11:00:00Z"},
                ]
            ],
            module.RED,
        ),
    ],
    ids=["зелёная", "красная", "дождались", "не дождались", "последняя из записей красная"],
)
def test_the_look_waits_for_the_gate(
    monkeypatch: pytest.MonkeyPatch, answers: list[list[dict[str, Any]]], said: str
) -> None:
    """Зелёная — идти, красная — нет, не дождались — идти, как до #762."""
    monkeypatch.setattr(module.ghrest, "paginate", gate(*answers))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module.wait("o/r", "abc", "t", timeout=0.05, interval=0.01) == said


def test_the_gate_verdict_waits_while_any_record_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Идёт хоть одна запись — вердикта нет: идущий заход скажет новее."""
    monkeypatch.setattr(module.ghrest, "paginate", gate(RUNNING))
    assert module.gate_verdict("o/r", "abc", "t") is None
    monkeypatch.setattr(module.ghrest, "paginate", gate(RUNNING + DONE_GREEN))
    assert module.gate_verdict("o/r", "abc", "t") is None


def record(conclusion: str, at: str) -> dict[str, Any]:
    """Завершённая запись гейта с исходом; время захода — начало и конец."""
    return {"status": "completed", "conclusion": conclusion, "started_at": at, "completed_at": at}


@pytest.mark.parametrize(
    ("records", "verdict"),
    [
        # Замер на голове #773: две отменённые рядом с двумя зелёными.
        (
            [
                record("success", "2026-09-24T18:59:41Z"),
                record("cancelled", "2026-09-24T18:59:02Z"),
                record("success", "2026-09-24T18:59:00Z"),
                record("cancelled", "2026-09-24T18:52:21Z"),
            ],
            "green",
        ),
        ([record("cancelled", "2026-09-24T10:00:00Z")], None),
        ([record("skipped", "2026-09-24T10:00:00Z")], None),
        (
            [record("failure", "2026-09-24T10:00:00Z"), record("success", "2026-09-24T11:00:00Z")],
            "green",
        ),
        (
            [record("success", "2026-09-24T10:00:00Z"), record("failure", "2026-09-24T11:00:00Z")],
            "red",
        ),
    ],
    ids=[
        "отменённые рядом с зелёными",
        "только отмена",
        "только пропуск",
        "перезапуск позеленел",
        "последний красный",
    ],
)
def test_a_cancelled_record_is_not_a_red_verdict(
    monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]], verdict: str | None
) -> None:
    """Отменённая запись вердиктом не является; решает последняя завершённая (#762)."""
    monkeypatch.setattr(module.ghrest, "paginate", gate(records))
    assert module.gate_verdict("o/r", "abc", "t") == verdict


def test_a_silent_platform_does_not_cancel_the_look(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — взгляд не отменяется: это «не дождались»."""

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("503")

    monkeypatch.setattr(module.ghrest, "paginate", refuse)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module.wait("o/r", "abc", "t", timeout=0.0, interval=0.0) == module.SILENT


@pytest.mark.parametrize(
    ("answer", "run"),
    [(DONE_RED, "no"), (DONE_GREEN, "yes"), (RUNNING, "yes")],
    ids=["красная — не идти", "зелёная — идти", "молчание — идти"],
)
def test_the_answer_lands_in_the_step_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: list[dict[str, Any]], run: str
) -> None:
    """Ответ пишется в вывод шага: на нём стоят условия шагов взгляда."""
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "paginate", gate(answer))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    code = module.main(["--repo", "o/r", "--sha", "abc", "--timeout", "0", "--interval", "0"])
    assert code == module.EXIT_OK
    assert out.read_text(encoding="utf-8") == f"run={run}\n"


def test_a_skip_on_a_red_head_is_noted_on_the_look_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пропуск на красной голове — аннотацией с заголовком `SKIPPED`, а не строкой лога.

    По этой пометке очередь узнаёт, что взгляд голова ещё должна (#762):
    позеленей она перезапуском без толчка — слилась бы без взгляда.
    """
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    for conclusion, noted in (("failure", True), ("success", False)):
        monkeypatch.setattr(
            module.ghrest, "paginate", gate([{"status": "completed", "conclusion": conclusion}])
        )
        module.main(["--repo", "o/r", "--sha", "abc", "--timeout", "0", "--interval", "0"])
        said = capsys.readouterr().out
        assert (f"::notice title={module.SKIPPED}::" in said) is noted, said


def test_without_a_head_the_wait_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет головы — ожидание не отработало, а не «зелено» (045)."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN


def test_the_look_step_waits_for_the_gate() -> None:
    """Шаги взгляда стоят на воротах, а ворота — до них (#762)."""
    text = (Path(__file__).parents[1] / ".github/workflows/review.yml").read_text(encoding="utf-8")
    job = text[: text.index("\n  findings:\n")]
    assert job.index("scripts/look_waits.py") < job.index("- name: внешний взгляд")
    look = job[job.index("- name: внешний взгляд") :]
    assert look.split("\n")[2].strip() == "if: steps.gate.outputs.run == 'yes'"


def test_a_zombie_record_is_not_a_running_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запись `in_progress` с уже проставленным исходом — завершённая (замер #73).

    Её держит тот же разбор, что у очереди (`ci_complete.pending`): своя копия
    ждала бы её до срока и пускала взгляд на красную голову (взгляд на #775).
    """
    # Как в замере #73: зомби несёт исход `success`, и он свежее красной записи.
    zombie = {
        "status": "in_progress",
        "conclusion": "success",
        "started_at": "2026-09-24T12:00:00Z",
    }
    red = record("failure", "2026-09-24T11:00:00Z")
    monkeypatch.setattr(module.ghrest, "paginate", gate([zombie, red]))
    assert module.gate_verdict("o/r", "abc", "t") == module.GREEN, "зомби принят за идущую запись"


def test_the_gate_reads_records_as_the_queue_does(monkeypatch: pytest.MonkeyPatch) -> None:
    """Перекрытые заходы: вердикт тот же, что у очереди — `ci_complete.worst_per_name`."""
    early_red = {
        **record("failure", "2026-09-24T10:00:00Z"),
        "completed_at": "2026-09-24T12:00:00Z",
    }
    late_green = {
        **record("success", "2026-09-24T11:00:00Z"),
        "completed_at": "2026-09-24T11:30:00Z",
    }
    monkeypatch.setattr(module.ghrest, "paginate", gate([early_red, late_green]))
    said = module.gate_verdict("o/r", "abc", "t")
    queue = module.ci_complete.worst_per_name([early_red, late_green])[0]
    assert said == (module.GREEN if queue["conclusion"] == "success" else module.RED)
    assert said == module.GREEN, "свежесть взята по концу захода, а не по началу, как у очереди"
