"""Вход `skip-branches` шага взгляда: машинная ветка не зовёт взгляд и реестр (#1342).

Шаг исполняется сам, на подделанном окружении: проверяется сценарий, который
пойдёт на площадке, а не пересказ его условия.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT

FLOW = ROOT / ".github" / "workflows" / "step-review.yml"


def flow() -> dict[Any, Any]:
    """Файл шага взгляда, разобранный; ключ `on` YAML читает как `True`."""
    said: dict[Any, Any] = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    return said


def machine_step() -> dict[str, Any]:
    """Шаг карты, решающий, машинная ли ветка."""
    step: dict[str, Any] = next(
        one for one in flow()["jobs"]["map"]["steps"] if one.get("id") == "machine"
    )
    return step


def decided(tmp_path: Path, head: str, skip: str) -> tuple[str, str]:
    """Исполняет шаг: что он записал в вывод и в сводку."""
    output, summary = tmp_path / "out", tmp_path / "summary"
    done = subprocess.run(
        ["bash", "-c", str(machine_step()["run"])],
        env={
            **os.environ,
            "HEAD": head,
            "SKIP": skip,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    said = summary.read_text(encoding="utf-8") if summary.exists() else ""
    return output.read_text(encoding="utf-8"), said


@pytest.mark.parametrize(
    ("head", "skip", "machine"),
    [
        ("chore/metrics", "chore/ dependabot/", True),
        ("dependabot/pip/x", "chore/ dependabot/", True),
        ("agent/fix", "chore/ dependabot/", False),
        ("chore/metrics", "", False),
        ("chore/metrics", "*", False),
        ("chore/metrics", "chore/*", False),
    ],
    ids=["приставка", "вторая-приставка", "не-машинная", "входа-нет", "звёздочка", "маска"],
)
def test_a_machine_branch_is_named_by_its_prefix(
    tmp_path: Path, head: str, skip: str, machine: bool
) -> None:
    """Приставка — буквально: звёздочка во входе не раскрывается в маску (045).

    Приставка, а не маска: `*` в списке стала бы «смотреть никого», и одна
    опечатка во входе гасила бы взгляд у всех веток молча.
    """
    output, summary = decided(tmp_path, head, skip)
    assert output.strip() == f"machine={'yes' if machine else 'no'}"
    # Пропуск объявлен строкой в сводке, а не тишиной.
    assert (head in summary) is machine


def test_the_look_waits_for_the_machine_answer() -> None:
    """Взгляд не зовётся на машинной ветке; не ответившая карта взгляд не гасит."""
    jobs = flow()["jobs"]
    assert jobs["map"]["outputs"]["machine"] == "${{ steps.machine.outputs.machine }}"
    condition = " ".join(str(jobs["review"]["if"]).split())
    assert "needs.map.outputs.machine != 'yes'" in condition
    assert jobs["findings"]["needs"] == "review", "реестр находок обязан ждать взгляда"
    # Реестр уходит вслед за взглядом только потому, что его условие несёт
    # неявный success(): `always()` или `!cancelled()` пустили бы его на
    # машинную ветку молча (взгляд на #1350).
    registry = str(jobs["findings"].get("if") or "")
    assert "always()" not in registry and "cancelled()" not in registry, registry


def test_the_costly_map_steps_skip_a_machine_branch() -> None:
    """Дорогие шаги карты не идут на машинной ветке: `exit 0` кончает шаг, а не джоб (#1350).

    Условие — «не yes», а не «no»: не ответивший шаг решения карту не гасит.
    Шаги до решения и общего блока кода конвейера условия не несут.
    """
    steps = flow()["jobs"]["map"]["steps"]
    costly = [
        step
        for step in steps
        if step.get("id") in {"map", "mode"} or "setup-python" in str(step.get("uses"))
    ]
    assert len(costly) == 3, costly
    for step in costly:
        assert step.get("if") == "steps.machine.outputs.machine != 'yes'", step
    first = steps.index(costly[0])
    assert all("if" not in step for step in steps[:first]), "условие у шагов до карты"


def test_the_input_is_declared_empty_by_default() -> None:
    """Пустой вход — смотреть все ветки: у вызывающего, не знающего о входе, ничего не меняется."""
    said = flow()[True]["workflow_call"]["inputs"]["skip-branches"]
    assert said["type"] == "string" and said["default"] == ""


# --- реестр позднего взгляда (#1349) -------------------------------------------

AUTOMERGE = ROOT / ".github" / "workflows" / "step-automerge.yml"


@pytest.mark.parametrize(
    ("head", "machine"),
    [
        ({"ref": "chore/metrics"}, True),
        ({"ref": "agent/fix"}, False),
        ({}, False),
        (None, False),
    ],
    ids=["машинная", "своя", "имени-нет", "головы-нет"],
)
def test_the_registry_skips_a_merged_machine_branch(head: object, machine: bool) -> None:
    """Слитое с машинной ветки в реестр не встаёт; незнание имени взгляд не гасит (045)."""
    from tests.conftest import load_script

    unlooked = load_script("unlooked.py")
    item = {"number": 1, "head": head}
    assert unlooked.machine_branch(item, ["chore/", "dependabot/"]) is machine
    assert unlooked.machine_branch(item, []) is False


def test_the_registry_run_drops_machine_branches_before_the_scan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Заход реестра отсеивает машинную ветку ДО обхода и называет пропуск числом.

    Проверка одной `machine_branch` не держит подключение: сними отсев в `main`,
    и машинное слитое снова встанет в реестр при зелёном наборе (взгляд на #1353).
    """
    from tests.conftest import load_script

    unlooked = load_script("unlooked.py")
    merged = [
        {"number": 10, "head": {"ref": "chore/metrics"}, "merged_at": "2026-10-14"},
        {"number": 11, "head": {"ref": "agent/fix"}, "merged_at": "2026-10-14"},
    ]
    scanned: list[list[int]] = []

    def scan(items: Any, known: Any, watermark: int, look: Any) -> tuple[dict[int, Any], int]:
        scanned.append([item["number"] for item in items])
        return {}, watermark

    monkeypatch.setattr(unlooked.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(unlooked, "onboarded_at", lambda *_: None)
    monkeypatch.setattr(unlooked.findings, "live_issue", lambda *_: (89, unlooked.MARKER))
    monkeypatch.setattr(unlooked, "merged_changes", lambda *_: merged)
    monkeypatch.setattr(unlooked, "scan", scan)
    unlooked.main(["--repo", "o/r", "--skip-branches", "chore/ dependabot/"])
    assert scanned == [[11]], scanned
    assert "в реестр не встали: 1 (#10)" in capsys.readouterr().out


def test_both_steps_take_the_same_input() -> None:
    """Вход один по имени и форме у взгляда и у реестра: приставки передаются одной строкой."""
    automerge: dict[Any, Any] = yaml.safe_load(AUTOMERGE.read_text(encoding="utf-8"))
    review = flow()[True]["workflow_call"]["inputs"]["skip-branches"]
    registry = automerge[True]["workflow_call"]["inputs"]["skip-branches"]
    assert (review["type"], review["default"]) == (registry["type"], registry["default"])
    text = AUTOMERGE.read_text(encoding="utf-8")
    assert "SKIP_BRANCHES: ${{ inputs.skip-branches }}" in text, "вход не доходит до реестра"


def test_a_machine_entry_already_in_the_registry_is_dropped_and_the_window_counts_all(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Запись машинной ветки, вставшая до входа, снимается; полноту окна меряет весь список.

    Отсев касался только новых записей, а «окно заполнено» считалось после
    отсева, и волна машинных веток его прятала (взгляды на #1353).
    """
    from tests.conftest import load_script

    unlooked = load_script("unlooked.py")
    merged = [
        {"number": 10, "head": {"ref": "chore/metrics"}, "merged_at": "2026-10-14"},
        {"number": 11, "head": {"ref": "agent/fix"}, "merged_at": "2026-10-14"},
    ]
    # Человеческая запись обязана уцелеть: без неё `kept == [[]]` прошло бы и
    # при отсеве, снимающем всё подряд (взгляд на #1361).
    body = (
        f"{unlooked.MARKER}\n- #10 · вердикта нет · 2026-10-13\n- #11 · вердикта нет · 2026-10-13\n"
    )
    kept: list[list[int]] = []

    def scan(items: Any, known: Any, watermark: int, look: Any) -> tuple[dict[int, Any], int]:
        kept.append(sorted(known))
        return dict(known), watermark

    monkeypatch.setattr(unlooked.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(unlooked, "onboarded_at", lambda *_: None)
    monkeypatch.setattr(unlooked.findings, "live_issue", lambda *_: (89, body))
    monkeypatch.setattr(unlooked, "merged_changes", lambda *_: merged)
    monkeypatch.setattr(unlooked, "scan", scan)
    monkeypatch.setattr(unlooked, "late_on", lambda *a, **k: "")
    unlooked.main(["--repo", "o/r", "--skip-branches", "chore/", "--limit", "2"])
    said = capsys.readouterr()
    assert kept == [[11]], kept
    assert "машинные записи реестра сняты: #10" in said.out
    assert "окно обхода заполнено (2)" in said.err
