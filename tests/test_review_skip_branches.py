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


def test_the_input_is_declared_empty_by_default() -> None:
    """Пустой вход — смотреть все ветки: у вызывающего, не знающего о входе, ничего не меняется."""
    said = flow()[True]["workflow_call"]["inputs"]["skip-branches"]
    assert said["type"] == "string" and said["default"] == ""
