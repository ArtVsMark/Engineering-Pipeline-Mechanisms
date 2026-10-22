"""Разбор кодов в действии `project-badge` исполняется, а не читается (взгляд на #1576).

У действия своя логика сверх вызова скрипта: разбор кода `case "$rc"` и путь к
транспорту из своей выкачки. Подстрока не отличает ветвление от текста рядом —
исполнение отличает, как у соседа `tests/test_ci_complete_action.py`.
"""

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest
import yaml

from tests.conftest import ROOT, load_script

ACTION: Final = ROOT / ".github/actions/project-badge/action.yml"
pb = load_script("project_badge.py")
#: Входы действия, которые шаг рисования читает окружением; пустые — не заданы.
OPTIONAL: Final = ("FAMILY", "COVERAGE_JSON", "COVERAGE_ALL_JSON", "VERSION_JSON", "PYPI", "SUITES")


def step_run(name: str) -> str:
    """Тело шага действия по имени."""
    said = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    return next(str(one["run"]) for one in said["runs"]["steps"] if one.get("name") == name)


def run_draw(tmp_path: Path, rc: int) -> int:
    """Исполняет шаг рисования с подставным скриптом, отдающим код ``rc``."""
    fake = tmp_path / "mechanisms" / "scripts"
    fake.mkdir(parents=True)
    (fake / "project_badge.py").write_text(f"raise SystemExit({rc})\n", encoding="utf-8")
    env = {
        "PATH": os.environ["PATH"],
        "MECHANISMS": str(tmp_path / "mechanisms"),
        "GITHUB_WORKSPACE": str(tmp_path),
        "OUT_DIR": ".project-badge",
        "REPO": "o/p",
        "CI_WORKFLOW": "ci.yml",
        **dict.fromkeys(OPTIONAL, ""),
    }
    done = subprocess.run(
        ["bash", "-e", "-c", step_run("нарисовать значок проекта")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return done.returncode


@pytest.mark.parametrize(
    ("rc", "step"),
    [(pb.EXIT_OK, 0), (pb.EXIT_GREY, 0), (pb.EXIT_BROKEN, 2), (1, 2), (137, 2)],
    ids=["чисто", "серое", "не собран", "трасса", "незнакомый"],
)
def test_the_action_reads_every_code_of_the_badge(tmp_path: Path, rc: int, step: int) -> None:
    """Зелено только объявленное: серое — предупреждение, трасса и незнакомое — отказ (068)."""
    assert run_draw(tmp_path, rc) == step


def test_the_transport_is_taken_from_the_action_checkout() -> None:
    """Путь к транспорту из выкачки действия ведёт в пакет дерева, а не мимо него."""
    said = step_run("поставить транспорт из выкачки действия")
    relative = said.split('"$GITHUB_ACTION_PATH/', 1)[1].split('"', 1)[0]
    assert (ACTION.parent / relative / "pyproject.toml").is_file(), relative
