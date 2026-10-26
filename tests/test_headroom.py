"""Сторож запаса: медленнейшая ячейка против доли предела (#1697).

Обе половины: запас мал — сказано с ячейкой, длительностью, пределом и
долей; запас есть — сказано, что есть. Короткий ряд и необъявленный сторож —
«не судится», а не «запас есть»; отказ площадки — «не отработал» (039).
Ряды — из замера 26.10.2026: 8:52 при пределе 10 говорит, 5:36 молчит.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("headroom.py")

CI = """
jobs:
  lint:
    timeout-minutes: 5
    steps: []
  test-matrix:
    name: test-matrix
    timeout-minutes: 10
    strategy:
      matrix:
        python: ["3.14", "3.15"]
    steps: []
"""


def watch(runs: int = 2, share: float = 0.7) -> Any:
    """Объявление сторожа для проб."""
    return module.Watch(workflow="ci.yml", jobs=("test-matrix",), share=share, runs=runs)


def job(name: str, seconds: int, conclusion: str = "success") -> dict[str, Any]:
    """Запись работы площадки с длительностью."""
    return {
        "name": name,
        "conclusion": conclusion,
        "started_at": "2026-10-26T08:10:00Z",
        "completed_at": f"2026-10-26T08:{10 + seconds // 60:02d}:{seconds % 60:02d}Z",
    }


def test_the_live_declaration_reads_and_its_jobs_are_in_our_ci() -> None:
    """Наше объявление читается, и его работы есть в нашем `ci.yml` с числовым пределом."""
    said = module.Watch.read(ROOT / ".rules" / "series.json")
    assert said is not None and said.jobs == ("test-matrix",)
    found = module.limits(
        (ROOT / ".github" / "workflows" / said.workflow).read_text("utf-8"), said.jobs
    )
    assert set(found) == {"test-matrix"} and found["test-matrix"] > 0


def test_an_absent_key_is_undeclared_and_a_broken_one_is_refused(tmp_path: Path) -> None:
    """Ключа нет — `None`; ключ без полей или с долей вне (0, 1] — отказ."""
    path = tmp_path / "series.json"
    path.write_text(json.dumps({"window_days": 90}), encoding="utf-8")
    assert module.Watch.read(path) is None
    for broken in ({}, {"workflow": "ci.yml", "jobs": ["t"], "share": 1.5, "runs": 3}):
        path.write_text(json.dumps({"headroom": broken}), encoding="utf-8")
        with pytest.raises(module.NotRun):
            module.Watch.read(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.Watch.read(path)


def test_limits_are_read_from_the_workflow_not_written_twice() -> None:
    """Предел — из `timeout-minutes` прогона; нет числа или работы — отказ."""
    assert module.limits(CI, ("test-matrix",)) == {"test-matrix": 10}
    with pytest.raises(module.NotRun, match="timeout-minutes"):
        module.limits(CI.replace("    timeout-minutes: 10\n", ""), ("test-matrix",))
    with pytest.raises(module.NotRun, match="нет в прогоне"):
        module.limits(CI, ("test",))
    with pytest.raises(module.NotRun):
        module.limits("jobs: [", ("test-matrix",))


def test_a_matrix_cell_belongs_to_its_job_and_a_neighbour_does_not() -> None:
    """`test-matrix (3.14)` — ячейка `test-matrix`; `test-matrix-x` и `test` — нет."""
    watched = {"test-matrix": 10}
    assert module.owner_of("test-matrix (3.14)", watched) == "test-matrix"
    assert module.owner_of("test-matrix", watched) == "test-matrix"
    assert module.owner_of("test-matrix-x", watched) == ""
    assert module.owner_of("test", watched) == ""


def test_only_a_job_that_ran_is_timed() -> None:
    """Отменённая по пределу — замер; пропущенная и без времени — нет."""
    assert module.seconds_of(job("t", 600, "cancelled")) == 600
    assert module.seconds_of(job("t", 600, "skipped")) is None
    assert module.seconds_of({"conclusion": "success"}) is None


def test_the_slowest_cell_is_taken_across_the_runs() -> None:
    """Медленнейшая ячейка — по всему ряду, чужие работы не в счёт."""
    runs = [
        [job("test-matrix (3.14)", 336), job("test-matrix (3.15)", 422), job("lint", 900)],
        [job("test-matrix (3.14)", 600, "cancelled"), job("test-matrix (3.15)", 532)],
    ]
    assert module.slowest(runs, {"test-matrix": 10}) == {"test-matrix": ("test-matrix (3.14)", 600)}
    assert module.clock(532) == "8:52"


def test_the_verdict_speaks_on_the_measured_red_and_is_quiet_on_the_good_morning() -> None:
    """8:52 при пределе 10 — запас мал; 5:36 — запас есть (замер 26.10.2026)."""
    watched = {"test-matrix": 10}
    code, lines = module.verdict(watch(), watched, {"test-matrix": ("test-matrix (3.15)", 532)}, 2)
    assert code == module.EXIT_LOW
    assert "`test-matrix (3.15)`" in lines[0] and "8:52" in lines[0] and "10:00" in lines[0]
    assert "89%" in lines[0] and "порог 70%" in lines[0]
    code, lines = module.verdict(watch(), watched, {"test-matrix": ("test-matrix (3.14)", 336)}, 2)
    assert code == module.EXIT_OK and lines[0].startswith("запас есть"), lines


def test_a_short_series_and_a_job_without_samples_are_not_judged() -> None:
    """Ряд короче объявленного и работа без замера — «не судится», а не «есть»."""
    watched = {"test-matrix": 10}
    code, lines = module.verdict(watch(runs=10), watched, {}, 3)
    assert code == module.EXIT_UNJUDGED and "3 из 10" in lines[0]
    code, lines = module.verdict(watch(runs=2), watched, {}, 2)
    assert code == module.EXIT_UNJUDGED and "ни одного замера" in lines[0]


def test_runs_are_asked_on_the_trunk_and_their_jobs_one_by_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Заходы — завершённые на общей ветке, не больше объявленного; работы — по каждому."""
    asked: list[str] = []

    def request(method: str, path: str, token: str) -> dict[str, Any]:
        asked.append(path)
        return {"workflow_runs": [{"id": 1}, {"id": 2}, {"id": 3}]}

    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token, key: iter([{"name": path}]))
    said = module.jobs_of_runs("o/r", "t", watch(runs=2))
    assert "branch=main" in asked[0] and "status=completed" in asked[0] and "per_page=2" in asked[0]
    assert said == [
        [{"name": "repos/o/r/actions/runs/1/jobs"}],
        [{"name": "repos/o/r/actions/runs/2/jobs"}],
    ]


def tree(tmp_path: Path, declared: bool = True) -> Path:
    """Дерево с объявлением ряда и прогоном."""
    (tmp_path / ".rules").mkdir(parents=True)
    said: dict[str, Any] = {"window_days": 90, "recount_days": 3}
    if declared:
        said["headroom"] = {"workflow": "ci.yml", "jobs": ["test-matrix"], "share": 0.7, "runs": 1}
    (tmp_path / ".rules" / "series.json").write_text(json.dumps(said), encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(CI, encoding="utf-8")
    return tmp_path


def test_main_writes_the_section_and_names_the_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Запас мал — исход 1 и раздел в отчёте; необъявленный — 3; отказ площадки — 2."""
    root = tree(tmp_path)
    report = tmp_path / "runs.md"
    report.write_text("# ряд\n", encoding="utf-8")
    monkeypatch.setattr(module, "jobs_of_runs", lambda *_: [[job("test-matrix (3.14)", 600)]])
    argv = ["--repo", "o/r", "--root", str(root), "--report", str(report)]
    assert module.main(argv) == module.EXIT_LOW
    assert module.HEAD in report.read_text(encoding="utf-8")

    def refuse(*_: Any) -> Any:
        raise module.ghrest.TransportError("молчит")

    monkeypatch.setattr(module, "jobs_of_runs", refuse)
    assert module.main(argv) == module.EXIT_BROKEN
    bare = tree(tmp_path / "bare", declared=False)
    assert module.main(["--repo", "o/r", "--root", str(bare)]) == module.EXIT_UNJUDGED
