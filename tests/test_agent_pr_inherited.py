"""Описание изменения не наследует коммиты уже уплотнённой ветки (#1034).

Ветка, выросшая из чужой ветки, несёт её коммиты, а уплотнение кладёт в общую
ветку один новый коммит — `merge-base` остаётся прежним. Замер 01.10.2026,
#1033: заголовок, `Closes` и `Разобрано` пришли от слитого #1026.

Дерево строится настоящим git, а не подделкой: признак — совпадение
содержимого с деревом уплотнённого коммита, и на подделке проверялось бы
согласие кода с нашим представлением о git, а не с git (170).
"""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("agent_pr.py")


def git(root: Path, *args: str) -> str:
    """git в дереве теста; отказ — падение теста, а не тихий пропуск."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def commit(root: Path, name: str, text: str, message: str) -> None:
    """Один коммит, правящий один файл."""
    (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", message)


@pytest.fixture
def grown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Случай #1033: ветка `своя` растёт от `чужая`, а `чужую` слили уплотнением.

    У `своей` первый собственный коммит назван ТАК ЖЕ, как коммит `чужой`, —
    вторая половина приёмки: заголовок совпал, содержимое своё.
    """
    git(tmp_path, "init", "--quiet", "-b", "main")
    git(tmp_path, "config", "user.email", "т@т")
    git(tmp_path, "config", "user.name", "т")
    commit(tmp_path, "база.txt", "база\n", "база\n\nRefs #1")
    git(tmp_path, "checkout", "--quiet", "-b", "чужая")
    commit(
        tmp_path, "чужое.txt", "раз\n", "Чужая работа, первый\n\nCloses #998\nРазобрано: b560c75"
    )
    commit(tmp_path, "чужое.txt", "два\n", "Чужая работа, второй\n\nRefs #998")
    git(tmp_path, "checkout", "--quiet", "-b", "своя")
    commit(tmp_path, "своё.txt", "моё\n", "Чужая работа, второй\n\nRefs #1019")
    commit(tmp_path, "своё.txt", "моё ещё\n", "Своя работа\n\nRefs #1019")
    git(tmp_path, "checkout", "--quiet", "main")
    git(tmp_path, "merge", "--quiet", "--squash", "чужая")
    git(
        tmp_path,
        "commit",
        "--quiet",
        "-m",
        "Чужая работа, первый (+1) (#1026)\n\n* Чужая работа, первый\n\n* Чужая работа, второй",
    )
    commit(tmp_path, "база.txt", "база после\n", "Соседнее слияние\n\nRefs #2")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "main")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_inherited_commits_do_not_describe_the_change(grown: Path) -> None:
    """Заголовок — первый СВОЙ коммит; трейлеры уплотнённой ветки не переносятся."""
    said = module.describe("своя", "main")
    assert said.title == "Чужая работа, второй (+1)", said.title
    assert "#998" not in said.body and "b560c75" not in said.body, said.body
    assert "#1019" in said.body


def test_an_own_commit_named_like_a_landed_one_stays(grown: Path) -> None:
    """Свой коммит с заголовком слитого не выпадает: решает содержимое, а не имя."""
    merge_base = git(grown, "merge-base", "origin/main", "своя").strip()
    own_first = git(grown, "rev-list", "--reverse", f"{merge_base}..своя").split()[2]
    start = module.inherited(merge_base, "своя", "main")
    assert git(grown, "rev-list", f"{start}..своя").split()[-1] == own_first


def test_a_branch_from_the_trunk_keeps_all_its_commits(grown: Path) -> None:
    """Без уплотнённого предка унаследованного нет: начало — `merge-base`."""
    git(grown, "checkout", "--quiet", "-b", "прямая", "main")
    commit(grown, "прямое.txt", "да\n", "Чужая работа, первый\n\nRefs #3")
    merge_base = git(grown, "merge-base", "origin/main", "прямая").strip()
    assert module.inherited(merge_base, "прямая", "main") == merge_base


def test_a_branch_that_merged_the_trunk_still_drops_the_inherited(grown: Path) -> None:
    """Своя ветка влила общую ПОСЛЕ уплотнения чужой — унаследованное всё равно выпадает.

    Взгляд на #1052: слияние сдвигает `merge-base` за уплотнённый коммит, и
    кандидаты от него пусты. Обычный путь ветки под `automerge` — слияний
    общей ветки в ней бывает несколько.
    """
    git(grown, "checkout", "--quiet", "своя")
    git(grown, "merge", "--quiet", "--no-edit", "main")
    commit(grown, "своё.txt", "моё после слияния\n", "Своя работа после слияния\n\nRefs #1019")
    said = module.describe("своя", "main")
    # +3: два своих коммита и слияние — слияние считается, как у живых изменений.
    assert said.title == "Чужая работа, второй (+3)", said.title
    assert "#998" not in said.body and "b560c75" not in said.body, said.body
    assert "Соседнее слияние" not in said.body and "#2\n" not in said.body, said.body


def test_a_prefix_is_inherited_only_whole(grown: Path) -> None:
    """Дерево совпало, а заголовка раньше в уплотнении нет — не префикс (взгляд на #1052).

    Свой ранний коммит правит тот же файл, что слитая ветка, и вершина
    совпадает с деревом уплотнения. Без проверки префикса свой коммит выпал
    бы из описания как унаследованный.
    """
    git(grown, "checkout", "--quiet", "-b", "смесь", "чужая~2")
    commit(grown, "чужое.txt", "своё\n", "Своё раннее\n\nRefs #5")
    commit(grown, "чужое.txt", "два\n", "Чужая работа, второй\n\nRefs #5")
    merge_base = git(grown, "merge-base", "origin/main", "смесь").strip()
    assert module.inherited(merge_base, "смесь", "main") == merge_base
