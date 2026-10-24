"""Прогон или ответ не в UTF-8 — названный отказ модуля, а не трасса (взгляд на #1593).

Один класс у четырёх читателей прогонов: `run_of` и `family_check` чинились
раньше (#1567, #1593), а эти соседи читали `read_text` сами.
"""

from pathlib import Path

import pytest

from tests.conftest import load_script

BAD = b"name: \xff\xfe\n"


def bad_flow(where: Path) -> Path:
    """Каталог с одним прогоном, который не декодируется как UTF-8."""
    where.mkdir(parents=True, exist_ok=True)
    (where / "ci.yml").write_bytes(BAD)
    return where


def test_required_context_names_an_unreadable_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сверка обязательного контекста: прогон не в UTF-8 — `NotRun`."""
    gate = load_script("check_required_context.py")
    monkeypatch.setattr(gate, "GATES_DIR", bad_flow(tmp_path / "flows"))
    with pytest.raises(gate.NotRun, match="не прочитан"):
        gate.declared_context("ci-complete")


def test_runs_series_names_an_unreadable_flow(tmp_path: Path) -> None:
    """Ряд прогонов: шаги установки из прогона не в UTF-8 — `NotRun`."""
    series = load_script("runs_series.py")
    with pytest.raises(series.NotRun, match="не прочитан"):
        series.installing_steps(bad_flow(tmp_path / "flows"))


def test_preflight_names_an_unreadable_ci(tmp_path: Path) -> None:
    """Предполётная: `ci.yml` не в UTF-8 — `NotRun`, а не `UnicodeDecodeError`."""
    preflight = load_script("preflight.py")
    with pytest.raises(preflight.NotRun, match="не разбирается"):
        preflight.steps(bad_flow(tmp_path / "flows") / "ci.yml")


def test_contract_surface_names_unreadable_files(tmp_path: Path) -> None:
    """Снимок поверхности: прогон или ответ не в UTF-8 — `BadPolicy` с причиной."""
    contract = load_script("contract.py")
    with pytest.raises(contract.policy.BadPolicy, match="не прочитан"):
        contract.workflows_surface(bad_flow(tmp_path / "flows"))
    answer = tmp_path / ".pipeline.yml"
    answer.write_bytes(BAD)
    with pytest.raises(contract.policy.BadPolicy, match="не прочитан"):
        contract.checks_surface(answer)
    (tmp_path / "flows" / "ci.yml").write_text("a: [\n", encoding="utf-8")
    with pytest.raises(contract.policy.BadPolicy, match="не разбирается"):
        contract.parsed(tmp_path / "flows" / "ci.yml", "прогон")
