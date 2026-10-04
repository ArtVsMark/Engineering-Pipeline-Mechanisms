"""Будильник сводного гейта перезапускает ровно ту сводку, что вынесена раньше конца `ci`.

Решение владельца 04.10.2026 (#1007, вариант 2). Проверяются обе половины:
что будильник перезапускает (красную сводку, завершённую до конца `ci`) и чего
не трогает — идущую, зелёную, отменённую, вынесенную после конца `ci` и
исчерпавшую попытки.
"""

from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, load_script

module = load_script("ci_complete_wake.py")

CI_DONE = "2026-10-04T12:00:00Z"


def run(**fields: Any) -> dict[str, Any]:
    """Прогон сводки: по умолчанию красный, завершён до конца `ci`, первая попытка."""
    base: dict[str, Any] = {
        "id": 7,
        "status": "completed",
        "conclusion": "failure",
        "created_at": "2026-10-04T11:30:00Z",
        "updated_at": "2026-10-04T11:45:00Z",
        "run_attempt": 1,
    }
    return {**base, **fields}


def test_a_red_summary_judged_before_ci_ended_is_stale() -> None:
    """Красная сводка, вынесенная раньше конца `ci`, — устаревшая."""
    assert module.stale_summary([run()], CI_DONE) == run()


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "in_progress", "conclusion": None},
        {"conclusion": "success"},
        {"conclusion": "cancelled"},
        {"updated_at": "2026-10-04T12:02:01Z"},
        {"run_attempt": module.MAX_ATTEMPTS},
    ],
    ids=["идёт", "зелёная", "отменена", "после-конца-ci", "попытки-исчерпаны"],
)
def test_a_summary_that_is_not_stale_is_left_alone(fields: dict[str, Any]) -> None:
    """Вторая половина: идущую, зелёную, отменённую, позднюю и исчерпанную не трогают."""
    assert module.stale_summary([run(**fields)], CI_DONE) is None


@pytest.mark.parametrize(
    "updated_at",
    ["2026-10-04T12:00:00Z", "2026-10-04T12:02:00Z"],
    ids=["ровно-конец-ci", "конец-запаса"],
)
def test_a_summary_finished_within_the_tail_is_stale(updated_at: str) -> None:
    """Граница включена: вердикт вынесен до конца `ci`, а завершение пришло хвостом (#1110)."""
    assert module.stale_summary([run(updated_at=updated_at)], CI_DONE) is not None


def test_the_manual_run_end_of_time_does_not_overflow() -> None:
    """Ручной заход передаёт последний миг календаря — сравнение не переполняется."""
    assert module.stale_summary([run()], "9999-12-31T23:59:59Z") is not None


def test_an_unread_platform_time_is_not_run() -> None:
    """Время площадки не прочитано — будильник не отработал, а не «не устарела» (045)."""
    with pytest.raises(module.NotRun, match="время"):
        module.stale_summary([run(updated_at="вчера")], CI_DONE)


def test_a_cancelled_ci_does_not_wake_the_summary() -> None:
    """Отменённый `ci` — новый толчок на голове: будильник не идёт (взгляд на #1110)."""
    flow = (ROOT / ".github" / "workflows" / "ci-complete-wake.yml").read_text(encoding="utf-8")
    condition = yaml.safe_load(flow)["jobs"]["ci-complete-wake"]["if"]
    assert "github.event.workflow_run.conclusion != 'cancelled'" in condition


def test_only_the_last_summary_of_the_head_counts() -> None:
    """Прежняя красная сводка не будится, если после неё есть новая (взгляд на выбор прогона)."""
    old = run(id=1, created_at="2026-10-04T11:00:00Z")
    new = run(id=2, created_at="2026-10-04T11:40:00Z", status="in_progress", conclusion=None)
    assert module.stale_summary([old, new], CI_DONE) is None


def test_wake_reruns_the_stale_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Устаревшая сводка перезапускается POST-ом на свой прогон."""
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([run(id=42)]))
    monkeypatch.setattr(
        module.ghrest, "request", lambda method, path, *_: asked.append((method, path))
    )
    said = module.wake("o/r", "abcdef1234", CI_DONE, "токен", dry_run=False)
    assert asked == [("POST", "repos/o/r/actions/runs/42/rerun")]
    assert "перезапущена" in said


def test_wake_without_summaries_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """Прогонов сводки нет — названо словами, а не молчанием (045)."""
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([]))
    assert "прогонов сводки нет" in module.wake("o/r", "abcdef12", CI_DONE, "т", dry_run=False)


def test_a_refused_rerun_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ площадки в перезапуске — «не отработал», а не «перезапускать нечего»."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([run()]))

    def refuse(*_: object) -> None:
        raise module.ghrest.TransportError("403")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    code = module.main(["--repo", "o/r", "--sha", "abcdef12", "--ci-done-at", CI_DONE])
    assert code == module.EXIT_BROKEN


def test_without_inputs_the_wake_does_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без головы или времени конца `ci` будить нечего — третий исход."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    assert module.main(["--repo", "o/r", "--sha", "", "--ci-done-at", ""]) == module.EXIT_BROKEN


def test_a_head_with_nothing_to_wake_is_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Зелёная сводка — исход «чисто», и что не будится, названо."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(
        module.ghrest, "paginate", lambda *_, **__: iter([run(conclusion="success")])
    )
    code = module.main(["--repo", "o/r", "--sha", "abcdef12", "--ci-done-at", CI_DONE])
    assert code == module.EXIT_OK
    assert "не устарела" in capsys.readouterr().out


def test_summary_runs_asks_only_the_change_event_of_the_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Прогоны сводки берутся по голове и ТОЛЬКО с события изменения.

    Прогон на общей ветке защиты не держит, и будить его незачем; ключ ответа
    площадки — `workflow_runs`, а не корень.
    """
    asked: list[tuple[str, str | None]] = []

    def paginate(path: str, _token: str, key: str | None = None) -> Any:
        asked.append((path, key))
        return iter([run()])

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    assert module.summary_runs("o/r", "abc", "т") == [run()]
    assert asked == [
        (
            "repos/o/r/actions/workflows/ci-complete.yml/runs?head_sha=abc&event=pull_request",
            "workflow_runs",
        )
    ]
