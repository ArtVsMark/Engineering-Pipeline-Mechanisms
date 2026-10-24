"""Нынешняя голова на синтетическом слиянии `pull_request` (взгляд на #1605)."""

from pathlib import Path

import pytest

from tests.test_scope import git
from tests.test_scope_again import commit, green_head, platform, scope, tree, write


def test_the_merge_commit_excludes_the_change_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """На слиянии нынешняя голова — второй родитель: зелёной считается прежняя."""
    root = tree(tmp_path)
    old = green_head(root)
    write(root, "scripts/b.py", "B = 3\n")
    head = commit(root, "нынешний")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "слияние площадки", head)
    assert scope.current_heads(root) >= {head}
    platform(monkeypatch, [old, head], {old, head})
    assert scope.last_green("о/р", 7, "т", root) == old


def test_a_plain_head_is_one(tmp_path: Path) -> None:
    """Не слияние — нынешняя голова одна."""
    root = tree(tmp_path)
    head = green_head(root)
    assert scope.current_heads(root) == {head}
