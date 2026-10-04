"""История общей ветки: тела слитых изменений и отказ на обрезанной истории (#1022)."""

import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import git, load_script

module = load_script("trunk_log.py")


def repo(tmp_path: Path) -> Path:
    """Дерево с двумя слитыми изменениями и прямым коммитом между ними."""
    root = tmp_path / "trunk"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    for subject, body in (
        ("Первое (#1)", "Разобрано: aaaaaaa\nРод: род"),
        ("Прямая правка", "Разобрано: bbbbbbb\nРод: род"),
        ("Второе (#2)", "без снятий"),
    ):
        git(root, "commit", "-q", "--allow-empty", "-m", subject, "-m", body)
    return root


def test_merged_bodies_are_the_squashed_ones_oldest_first(tmp_path: Path) -> None:
    """Тела берутся только у коммитов «Тема (#N)», от старых к новым."""
    root = repo(tmp_path)
    assert module.merged_bodies(root, "HEAD") == [
        "Первое (#1)\n\nРазобрано: aaaaaaa\nРод: род",
        "Второе (#2)\n\nбез снятий",
    ]


def test_branch_bodies_are_every_commit_of_the_range(tmp_path: Path) -> None:
    """Коммиты изменения — все, с темой «(#N)» и без: из них соберут тело уплотнения."""
    root = repo(tmp_path)
    git(root, "checkout", "-q", "-b", "work")
    git(root, "commit", "-q", "--allow-empty", "-m", "Своё", "-m", "Род: род — окно: a.py")
    assert module.branch_bodies("main", "HEAD", root) == ["Своё\n\nРод: род — окно: a.py"]


def test_a_shallow_clone_is_refused(tmp_path: Path) -> None:
    """Мелкий клон — отказ: встречи прежних слияний пропали бы молча (045)."""
    root = repo(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{root}", str(shallow)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(module.NotRun, match=re.escape(module.SHALLOW)):
        module.merged_bodies(shallow, "HEAD")
    # Вторая половина: полный клон того же дерева читается.
    assert len(module.merged_bodies(root, "HEAD")) == 2


def test_an_unknown_ref_is_refused(tmp_path: Path) -> None:
    """Ветки нет — отказ, а не пустая история."""
    with pytest.raises(module.NotRun):
        module.merged_bodies(repo(tmp_path), "нет-такой")


def test_merges_without_squash_are_counted(tmp_path: Path) -> None:
    """Слияние «Merge pull request #N» в теле изменения не несёт — его считают, а не читают."""
    root = repo(tmp_path)
    git(root, "commit", "-q", "--allow-empty", "-m", "Merge pull request #7 from o/agent/x")
    assert module.unseen(root, "HEAD") == 1
    assert len(module.merged_bodies(root, "HEAD")) == 2
