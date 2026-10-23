"""Области потребителя сужают полный набор там, где граф не судит (#1600)."""

from pathlib import Path

import pytest

from tests.conftest import load_script
from tests.test_scope_again import commit, git, tree, write

areas = load_script("scope_areas.py")
scope = load_script("scope.py")

WEB = areas.Area("web", ("web/**",), ("tests/web/**",))


def test_an_area_knows_its_paths_and_its_tests() -> None:
    """Путь и тест области узнаются образцом; `*` ловит и `/`."""
    assert WEB.touched_by(["web/ui/page.py"])
    assert not WEB.touched_by(["scripts/a.py"])
    assert WEB.owns("tests/web/test_page.py")
    assert not WEB.owns("tests/test_a.py")
    assert areas.known("web/x.py", [WEB])
    assert not areas.known("other/x.py", [WEB])


def test_an_untouched_area_loses_its_tests() -> None:
    """Тронутое вне путей области — её тесты выпадают; задело — остаются."""
    every = ["tests/test_a.py", "tests/web/test_page.py"]
    assert areas.narrowed(every, {"scripts/a.py"}, [WEB]) == ("tests/test_a.py",)
    assert areas.narrowed(every, {"web/x.py"}, [WEB]) == tuple(every)


def test_no_section_is_no_areas() -> None:
    """Раздела нет — областей нет: прежнее поведение."""
    assert areas.areas_of(None) == ()


@pytest.mark.parametrize(
    "section",
    [[], {}, {"web": []}, {"web": {"paths": ["w"]}}, {"web": {"paths": [""], "tests": ["t"]}}],
    ids=["список", "пусто", "не-отображение", "без-тестов", "пустой-образец"],
)
def test_a_broken_section_names_its_reason(section: object) -> None:
    """Битый раздел — `BadAreas` с причиной, а не тихое «областей нет» (045)."""
    with pytest.raises(areas.BadAreas, match="раздел scopes"):
        areas.areas_of(section)


def consumer(tmp_path: Path) -> Path:
    """Дерево потребителя: тесты зовут код своими формами, у `web` — область."""
    root = tree(tmp_path)
    write(root, "web/page.py", "P = 1\n")
    write(root, "tests/web/test_page.py", "import page\n")
    write(
        root,
        ".pipeline.yml",
        "scopes:\n  web:\n    paths: ['web/**']\n    tests: ['tests/web/**']\n",
    )
    commit(root, "области")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def test_a_change_outside_the_area_skips_its_tests(tmp_path: Path) -> None:
    """Правка вне `web` гонит всё, кроме тестов `web`: граф не судит, судит область."""
    root = consumer(tmp_path)
    write(root, "scripts/b.py", "B = 2\n")
    said = scope.choose(root, "origin/main")
    assert said.tests is not None
    assert "tests/web/test_page.py" not in said.tests
    assert "tests/test_a.py" in said.tests, "область заменяет граф: тест вне областей идёт"
    assert "web" in said.why


def test_a_change_inside_the_area_runs_everything(tmp_path: Path) -> None:
    """Правка в `web` — области задеты все, набор полный; путь области — известное место."""
    root = consumer(tmp_path)
    write(root, "web/page.py", "P = 2\n")
    said = scope.choose(root, "origin/main")
    assert (said.scenario, said.tests) == (scope.TEXT, None)


def test_shared_files_stay_the_whole_set_with_areas(tmp_path: Path) -> None:
    """Общий для всех файл — полный набор и при областях: область только сужает."""
    root = consumer(tmp_path)
    write(root, "pyproject.toml", "[x]\n")
    assert scope.choose(root, "origin/main").tests is None


def test_a_broken_section_is_the_third_outcome(tmp_path: Path) -> None:
    """Битый раздел областей — классификатор не отработал, а не «областей нет»."""
    root = consumer(tmp_path)
    write(root, ".pipeline.yml", "scopes: [web]\n")
    with pytest.raises(scope.NotRun, match="раздел scopes"):
        scope.choose(root, "origin/main")
