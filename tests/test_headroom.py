"""Сторож запаса: медленнейшая ячейка против доли предела (#1697).

Обе половины: запас мал — сказано с ячейкой, длительностью, пределом и
долей; запас есть — сказано, что есть. Короткий ряд и необъявленный сторож —
«не судится», а не «запас есть»; отказ площадки — «не отработал» (039).
Ряды — из замера 26.10.2026: 8:52 при пределе 10 говорит, 5:36 молчит.
"""

import json
import sys
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


@pytest.mark.parametrize(("runs", "fits"), [(1, True), (100, True), (101, False), (0, False)])
def test_a_series_longer_than_a_page_is_refused(tmp_path: Path, runs: int, fits: bool) -> None:
    """Ряд длиннее страницы площадки был бы вечным «ряд мал» — отказ с пределом (#1700)."""
    path = tmp_path / "series.json"
    said = {"workflow": "ci.yml", "jobs": ["t"], "share": 0.7, "runs": runs}
    path.write_text(json.dumps({"headroom": said}), encoding="utf-8")
    if fits:
        assert module.Watch.read(path) is not None
        return
    with pytest.raises(module.NotRun, match=f"до {module.RUNS_CAP}"):
        module.Watch.read(path)


def test_limits_are_read_from_the_workflow_not_written_twice() -> None:
    """Предел — из `timeout-minutes` прогона; нет числа или работы — отказ."""
    assert module.limits(CI, ("test-matrix",)) == {"test-matrix": 10}
    with pytest.raises(module.NotRun, match="timeout-minutes"):
        module.limits(CI.replace("    timeout-minutes: 10\n", ""), ("test-matrix",))
    with pytest.raises(module.NotRun, match="timeout-minutes"):
        module.limits(CI.replace("timeout-minutes: 10", "timeout-minutes: 0"), ("test-matrix",))
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


def test_a_job_named_by_an_expression_owns_what_the_platform_substituted() -> None:
    """`test (${{ matrix.py }})` приходит как `test (3.14)` — это его запись (#1700)."""
    watched = {"test (${{ matrix.py }})": 10}
    assert module.owner_of("test (3.14)", watched) == "test (${{ matrix.py }})"
    assert module.owner_of("test ()", watched) == ""
    assert module.owner_of("testx (3.14)", watched) == ""
    assert module.owner_of("test", watched) == ""


def test_any_exception_is_a_refusal_not_a_low_headroom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Трасса — исход 2, а не 1 «запас мал»: класс закрыт в точке входа (#1700, 210)."""
    root = tree(tmp_path)

    def empty(*_: Any) -> Any:
        return None.get("jobs")  # type: ignore[attr-defined]

    monkeypatch.setattr(module, "jobs_of_runs", empty)
    argv = ["--repo", "o/r", "--root", str(root)]
    with pytest.raises(AttributeError):
        module.main(argv)
    assert module.guarded(argv) == module.EXIT_BROKEN
    assert "не находка о запасе" in capsys.readouterr().err


def test_a_broken_onboard_is_a_refusal_not_a_low_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ загрузки `onboard` — под `guarded`, исход 2, а не 1 «запас мал» (#1707).

    `onboard` тянет десяток модулей проекта; импорт в шапке сторожа выводил
    отказ любого из них кодом 1 мимо точки входа.
    """
    text = (ROOT / "scripts" / "headroom.py").read_text(encoding="utf-8")
    assert "\nimport onboard\n" not in text, "onboard снова грузится в шапке модуля"
    monkeypatch.setitem(sys.modules, "onboard", None)
    with pytest.raises(ImportError):
        module.shape_of("test (${{ matrix.py }})")
    monkeypatch.setattr(module, "main", lambda _argv: module.shape_of("${{ x }}") and 0)
    assert module.guarded([]) == module.EXIT_BROKEN


def test_the_script_enters_through_the_guard() -> None:
    """Точка входа процесса — `guarded`, а не голый `main`: иначе трасса снова код 1."""
    text = (ROOT / "scripts" / "headroom.py").read_text(encoding="utf-8")
    assert "sys.exit(guarded())" in text and "sys.exit(main())" not in text


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

    def garbled(*_: Any) -> Any:
        raise ValueError("не JSON")

    monkeypatch.setattr(module, "jobs_of_runs", garbled)
    assert module.main(argv) == module.EXIT_BROKEN, "битый ответ выдан за «запас мал»"
    monkeypatch.setattr(module, "jobs_of_runs", lambda *_: [[job("test-matrix (3.14)", 600)]])
    unwritable = ["--repo", "o/r", "--root", str(root), "--report", str(tmp_path / "нет" / "r.md")]
    assert module.main(unwritable) == module.EXIT_BROKEN, "неписаный отчёт выдан за «запас мал»"
    bare = tree(tmp_path / "bare", declared=False)
    assert module.main(["--repo", "o/r", "--root", str(bare)]) == module.EXIT_UNJUDGED


def test_a_low_headroom_outranks_a_job_without_samples() -> None:
    """Запас мал у одной работы, у другой нет замера — исход 1, а не 3 (взгляд на #1700)."""
    watched = {"test-matrix": 10, "test-next": 10}
    code, lines = module.verdict(watch(), watched, {"test-matrix": ("test-matrix (3.14)", 600)}, 2)
    assert code == module.EXIT_LOW, lines
    assert any("ни одного замера" in one for one in lines)
