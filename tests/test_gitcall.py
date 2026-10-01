"""Общий вызов git отдаёт вывод, а отказ — классом вызывающего (071, #999)."""

from __future__ import annotations

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


def test_git_missing_is_a_refusal_not_a_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без git на пути — тот же третий исход: прежняя форма падала здесь трассой."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(Refused, match=r"^git status → "):
        gitcall.output(["status"], Refused)
