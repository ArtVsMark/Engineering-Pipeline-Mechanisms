"""Посторонний автор не судится на авторство (#1599, эпик #1596).

Сверка исполняется оболочкой с обеими половинами: посторонний из вилки — не
судится; доверенный из вилки, ветка этого репозитория и событие без изменения —
судятся. Подстрока условия тут ничего бы не доказала.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT
from tests.test_review_safety import TRUSTED

STEP = ROOT / ".github" / "workflows" / "step-attribution.yml"
REPO = "о/р"


def steps() -> list[dict[str, Any]]:
    """Шаги джоба атрибуции."""
    flow = yaml.safe_load(STEP.read_text(encoding="utf-8"))
    found: list[dict[str, Any]] = flow["jobs"]["attribution"]["steps"]
    return found


def who_step() -> dict[str, Any]:
    """Шаг, решающий, посторонний ли автор."""
    (step,) = [one for one in steps() if one.get("id") == "who"]
    return step


@pytest.mark.parametrize(
    ("who", "head", "external"),
    [
        ("NONE", "чужой/р", True),
        ("CONTRIBUTOR", "чужой/р", True),
        ("", "чужой/р", True),
        *[(role, "чужой/р", False) for role in TRUSTED],
        ("NONE", REPO, False),
        ("NONE", "", False),
    ],
)
def test_only_an_outsider_from_a_fork_is_not_judged(
    who: str, head: str, external: bool, tmp_path: Path
) -> None:
    """Вилка и связь не из доверенных — не судится; всё прочее — судится."""
    out = tmp_path / "out"
    done = subprocess.run(
        ["bash", "-c", who_step()["run"]],
        env={
            "WHO": who,
            "HEAD_REPO": head,
            "REPO": REPO,
            "GITHUB_OUTPUT": str(out),
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert (f"external={'yes' if external else 'no'}") in out.read_text(encoding="utf-8")
    assert ("сливает человек" in done.stdout) is external


def test_the_gate_waits_for_the_answer() -> None:
    """Выкачка и гейт идут под ответом сверки, а сверка — первой."""
    names = steps()
    assert names[0].get("id") == "who", "сверка автора не первая"
    for one in names[1:]:
        assert "steps.who.outputs.external != 'yes'" in str(one.get("if") or ""), one
