"""Общий вызов git отдаёт вывод, а отказ — классом вызывающего (071, #999)."""

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


items_left = load_script("items_left.py")
review_map = load_script("review_map.py")


def test_items_left_without_git_is_unknown_not_a_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Без git признак пункта молчит, как при отказе git, а не падает трассой (взгляд на #1021)."""
    monkeypatch.setenv("PATH", "")
    assert items_left.tracked(tmp_path) == set()
    assert items_left.shallow(tmp_path) is True, "незнание — сторона молчания"
    assert items_left.born("x.py", tmp_path) is None


def test_review_map_without_git_refuses_not_a_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без git карта взгляда — третий исход и сторона «тронут», а не трасса (взгляд на #1021)."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(review_map.NotRun, match=r"^git show "):
        review_map.from_base("HEAD")
    with pytest.raises(review_map.NotRun):
        review_map.shown_from_base("HEAD", Path("README.md"))
    assert review_map.touches_the_answer("HEAD") is True
