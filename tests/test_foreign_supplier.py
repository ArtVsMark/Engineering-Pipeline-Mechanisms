"""Чужой ли поставщик — и вне площадки, по `origin` рабочего дерева (взгляд на #1583)."""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

policy = load_script("pipeline_checks.py")


def clone_of(where: Path, origin: str) -> Path:
    """Пустой репозиторий с `origin` по адресу площадки."""
    where.mkdir(parents=True)
    for args in (("init", "-q"), ("remote", "add", "origin", f"https://github.com/{origin}.git")):
        subprocess.run(["git", "-C", str(where), *args], check=True, timeout=60)
    return where


@pytest.mark.parametrize(
    ("tree", "supplier", "foreign"),
    [("o/потребитель", "ArtVsMark/Engineering-Pipeline-Mechanisms", True), ("o/r", "o/r", False)],
    ids=["чужой", "свой"],
)
def test_foreign_reads_the_work_tree_without_the_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tree: str, supplier: str, foreign: bool
) -> None:
    """Без `GITHUB_REPOSITORY` своя сторона — `origin` рабочего дерева."""
    work = clone_of(tmp_path / "дерево", tree)
    cache = clone_of(tmp_path / "выкачка", supplier)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.chdir(work)
    policy.supplier_repo.cache_clear()
    assert policy.foreign(cache) is foreign


def test_the_platform_variable_comes_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Переменная площадки первее `origin`: в прогоне она и есть свой репозиторий."""
    work = clone_of(tmp_path / "дерево", "o/потребитель")
    cache = clone_of(tmp_path / "выкачка", "o/потребитель")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/другой")
    monkeypatch.chdir(work)
    policy.supplier_repo.cache_clear()
    assert policy.foreign(cache) is True
