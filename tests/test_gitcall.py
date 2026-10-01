"""Общий вызов git отдаёт вывод, а отказ — классом вызывающего (071, #999)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

gitcall = load_script("gitcall.py")


class Refused(RuntimeError):
    """Третий исход вызывающего модуля."""


def test_output_is_the_stdout_of_git() -> None:
    """Удачный вызов — вывод git как есть, без среза."""
    assert gitcall.output(["--version"], Refused).startswith("git version")


def test_a_refusal_of_git_is_the_callers_class() -> None:
    """Отказ git — исключение вызывающего с командой в тексте, а не пустой ответ (075)."""
    with pytest.raises(Refused, match=r"git rev-parse --verify нет-такой-ветки → "):
        gitcall.output(["rev-parse", "--verify", "нет-такой-ветки"], Refused)


def test_git_runs_in_the_named_directory(tmp_path: Path) -> None:
    """`cwd` называет дерево: git отвечает о нём, а не о рабочем каталоге."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert gitcall.output(
        ["rev-parse", "--show-toplevel"], Refused, cwd=str(tmp_path)
    ).strip() == str(tmp_path.resolve())


def test_git_missing_is_a_refusal_not_a_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без git на пути — тот же третий исход: прежняя форма падала здесь трассой."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(Refused, match=r"^git status → "):
        gitcall.output(["status"], Refused)


@pytest.mark.parametrize("name", ["window.py", "release.py"])
def test_a_module_wrapper_refuses_without_git(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Обёртки `window.git` и `release.git` без git — свой третий исход, а не трасса (#1008)."""
    module = load_script(name)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(module.NotRun, match=r"^git status → "):
        module.git("status")
