"""Классификатор задетого (#1597): рёбра графа, выбор тестов, сценарий, база и голова.

Граф проверяется на подделке дерева настоящим git: тронутое считается от общего
предка, а граф базы читается из дерева коммита, и подделка `git` проверяла бы
не механизм, а её саму.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

scope = load_script("scope.py")

FILES = frozenset({"scripts/a.py", "scripts/b.py", ".rules/x.json", "docs/use/one.md"})
DIRS = frozenset({"scripts", ".rules", "docs", "docs/use"})
INDEX = scope.modules(FILES)


def edges(text: str) -> Any:
    """Рёбра исходника на подделке индекса."""
    found = scope.edges_of(text.encode(), INDEX, FILES, DIRS)
    assert isinstance(found, scope.Edges)
    return found


def test_fresh_edges_are_empty_and_understood() -> None:
    """Пустые рёбра — ни кода, ни данных, и граф файл понял: `whole` пуст."""
    fresh = scope.Edges()
    assert (fresh.code, fresh.data, fresh.whole) == (set(), set(), "")


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("import a\n", {"scripts/a.py"}),
        ("import a as z\n", {"scripts/a.py"}),
        ("from a import f\n", {"scripts/a.py"}),
        ("from scripts import a\n", {"scripts/a.py"}),
        ("from . import b\n", {"scripts/b.py"}),
        ("from tests.conftest import ROOT\n", {"tests/conftest.py"}),
        ('m = load_script("a.py")\n', {"scripts/a.py"}),
        ('run_script("b.py", "--x")\n', {"scripts/b.py"}),
        ('fixture.run_script("b.py")\n', {"scripts/b.py"}),
    ],
    ids=[
        "import",
        "import-as",
        "from-import",
        "from-package",
        "from-dot",
        "conftest",
        "load_script",
        "run_script",
        "run_script-attribute",
    ],
)
def test_every_form_of_a_code_edge_is_seen(source: str, code: set[str]) -> None:
    """Каждая форма вызова или импорта модуля — ребро кода."""
    found = edges(source)
    assert code <= found.code
    assert not found.whole


@pytest.mark.parametrize(
    ("source", "data"),
    [
        ('Path(".rules/x.json")\n', {".rules/x.json"}),
        ('ROOT / "docs"\n', {"docs/"}),
        ('walk(Path("docs/use"))\n', {"docs/use/"}),
        ('walk("docs/use")\n', {"docs/use/"}),
        ("code_files()\n", set(scope.CODE_ROOTS)),
    ],
    ids=["file", "dir-piece", "walk-path", "walk", "code_files"],
)
def test_every_form_of_a_data_edge_is_seen(source: str, data: set[str]) -> None:
    """Литерал пути и обход каталога — рёбра данных."""
    assert data <= edges(source).data


@pytest.mark.parametrize(
    "source",
    ["load_script(name)\n", "run_script(script)\n", "def (\n"],
    ids=["load_script-variable", "run_script-variable", "syntax"],
)
def test_what_the_graph_cannot_read_depends_on_everything(source: str) -> None:
    """Вызов не литералом и неразобранный файл — «дерево целиком», а не «ничего»."""
    assert edges(source).whole


def test_a_string_that_is_no_path_is_no_edge() -> None:
    """Слово, не совпадающее с путём дерева, ребром не становится."""
    found = edges('x = "просто текст"\ny = "a"\n')
    assert not found.data
    assert not found.code


def test_helpers_name_their_subject() -> None:
    """Помощники разбора: имя зовомого, литерал довода, путь, каталоги, покрытие."""
    import ast

    def call_of(text: str) -> ast.Call:
        """Вызов из строки исходника."""
        node = ast.parse(text).body[0]
        assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        return node.value

    call = call_of('obj.walk("docs", 1)')
    assert scope.called_name(call) == "walk"
    assert scope.first_text(call) == "docs"
    assert scope.first_text(call_of("f(x)")) is None
    assert scope.as_path("./docs/", FILES, DIRS) == "docs/"
    assert scope.as_path(".rules/x.json", FILES, DIRS) == ".rules/x.json"
    assert scope.as_path("нет", FILES, DIRS) is None
    assert scope.dirs_of(["a/b/c.py", "d.md"]) == {"a", "a/b"}
    assert scope.covers("docs/", "docs/use/one.md")
    assert scope.covers("a.py", "a.py")
    assert not scope.covers("a.py", "a.py.bak")
    assert scope.is_test("tests/test_x.py")
    assert not scope.is_test("tests/conftest.py")
    assert scope.modules(["scripts/a.py", "docs/a.md"])["a"] == {"scripts/a.py"}


def graph_of(files: dict[str, str]) -> dict[str, object]:
    """Граф подделки: путь → исходник."""
    known = frozenset(files)
    index = scope.modules(files)
    dirs = frozenset(scope.dirs_of(files))
    return {
        name: scope.edges_of(text.encode(), index, known, dirs)
        for name, text in files.items()
        if name.endswith(".py")
    }


TREE: dict[str, str] = {
    "scripts/low.py": 'DATA = Path(".rules/x.json")\nANCHOR = Path("docs")\n',
    "scripts/mid.py": "import low\n",
    "scripts/top.py": "import mid\n",
    "scripts/alone.py": "",
    "tests/conftest.py": 'def code_files(): ...\ncode_files()\nPAGE = Path("docs/a.md")\n',
    "tests/test_low.py": 'from tests.conftest import ROOT\nload_script("low.py")\n',
    "tests/test_top.py": 'load_script("top.py")\n',
    "tests/test_alone.py": 'from tests.conftest import ROOT\nload_script("alone.py")\n',
    "tests/test_docs.py": 'walk(ROOT / "docs")\n',
    "tests/test_any.py": "load_script(name)\n",
    ".rules/x.json": "",
    "docs/a.md": "",
}


def test_code_edges_are_transitive() -> None:
    """Тронут нижний модуль — выбран тест верхнего, который зовёт его по цепочке."""
    picked = scope.chosen(graph_of(TREE), {"scripts/low.py"})
    assert {"tests/test_low.py", "tests/test_top.py"} <= set(picked)
    assert "tests/test_alone.py" not in picked
    assert "tests/test_any.py" in picked  # зависит от всего


def test_data_edges_go_one_step() -> None:
    """Файл данных: выбран тест модуля, который его называет, но не тест его потребителя."""
    picked = scope.chosen(graph_of(TREE), {".rules/x.json"})
    assert "tests/test_low.py" in picked
    assert "tests/test_top.py" not in picked


def test_a_module_anchor_and_the_conftest_are_not_reads() -> None:
    """Каталог в литерале модуля и обход в conftest — не чтение каждого теста."""
    picked = scope.chosen(graph_of(TREE), {"docs/a.md"})
    assert "tests/test_docs.py" in picked  # тест обходит каталог сам
    assert "tests/test_low.py" not in picked  # `Path("docs")` в low.py — якорь
    assert "tests/test_alone.py" not in picked  # обход в conftest — не его


def test_touched_code_and_merged_follow_both_trees() -> None:
    """Объединение графов базы и головы: ребро, бывшее только в базе, — ребро."""
    base = graph_of({"scripts/gone.py": "", "tests/test_gone.py": 'load_script("gone.py")\n'})
    head = graph_of({"tests/test_gone.py": ""})
    both = scope.merged(base, head)
    assert "scripts/gone.py" in both["tests/test_gone.py"].code
    assert scope.touched_code(both, {"scripts/gone.py"}) >= {"tests/test_gone.py"}


@pytest.mark.parametrize(
    ("touched", "kind"),
    [
        (set(), scope.TEXT),
        ({"docs/a.md"}, scope.TEXT),
        ({".claude/skills/x/SKILL.md"}, scope.TEXT),
        ({"scripts/a.py"}, scope.CODE),
        ({"tests/test_a.py"}, scope.CODE),
        ({"docs/a.md", "scripts/a.py"}, scope.CODE),
        ({".github/workflows/ci.yml"}, scope.FLOWS),
        ({"tests/conftest.py"}, scope.FULL),
        ({"pyproject.toml"}, scope.FULL),
        ({"неведомое/x"}, scope.FULL),
    ],
    ids=[
        "empty",
        "doc",
        "skill",
        "code",
        "test",
        "union",
        "flows",
        "conftest",
        "pyproject",
        "unknown",
    ],
)
def test_the_scenario_follows_the_touched_places(touched: set[str], kind: str) -> None:
    """Сценарий — по местам дерева; несколько мест — шире из них; неизвестное — full."""
    assert scope.scenario(touched)[0] == kind


def test_classify_gives_everything_for_full_and_flows() -> None:
    """`full` и `flows` — полный набор (`tests` None) с причиной; прочие — выбор."""
    full = scope.classify({"pyproject.toml"}, {})
    assert full.tests is None and full.why
    assert scope.classify({"docs/a.md"}, graph_of(TREE)).tests == (
        "tests/test_any.py",
        "tests/test_docs.py",
    )


def git(root: Path, *args: str) -> str:
    """Git подделки, с дедлайном."""
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=a@b", "-c", "user.name=t", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return done.stdout


def repo(tmp_path: Path) -> Path:
    """Дерево с модулем и его тестом, база — `origin/main`."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts" / "gone.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_gone.py").write_text('load_script("gone.py")\n', encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text("", encoding="utf-8")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "база")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def test_a_removed_module_still_picks_the_test_that_called_it(tmp_path: Path) -> None:
    """Удалён модуль — тест, звавший его, выбран по графу базы, хотя сам не тронут."""
    root = repo(tmp_path)
    # Тест не тронут: в голове он зовёт модуль, которого нет, — ребро на него
    # знает только граф базы.
    (root / "scripts" / "gone.py").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-qm", "снят")
    said = scope.choose(root, "origin/main")
    assert said.scenario == scope.CODE
    assert said.tests == ("tests/test_gone.py",)


def test_the_touched_are_the_commits_the_tree_and_the_new_files(tmp_path: Path) -> None:
    """Тронутое — от общего предка: коммиты, правки рабочего дерева и новые файлы."""
    root = repo(tmp_path)
    fork = git(root, "rev-parse", "HEAD").strip()
    (root / "docs").mkdir()
    (root / "docs" / "new.md").write_text("x\n", encoding="utf-8")
    (root / "tests" / "test_other.py").write_text("# правка\n", encoding="utf-8")
    assert scope.touched_paths(root, fork) == {"docs/new.md", "tests/test_other.py"}
    assert "scripts/gone.py" in scope.tracked(root)
    assert "scripts/gone.py" in scope.tracked(root, fork)
    assert "tests/test_gone.py" in scope.base_graph(root, fork)


def test_a_missing_base_is_the_third_outcome(tmp_path: Path) -> None:
    """Базы нет — «не отработал» с причиной, а не «тронуто ничего» (039)."""
    root = repo(tmp_path)
    with pytest.raises(scope.NotRun):
        scope.choose(root, "origin/нет")
    assert scope.main(["--root", str(root), "--base", "origin/нет"]) == scope.EXIT_BROKEN


def test_main_names_the_scenario_and_the_tests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Заход печатает сценарий и число; с `--tests` — выбранные файлы построчно."""
    root = repo(tmp_path)
    (root / "scripts" / "gone.py").write_text("X = 2\n", encoding="utf-8")
    assert scope.main(["--root", str(root), "--base", "origin/main"]) == scope.EXIT_OK
    assert "сценарий: code; тест-файлов: 1" in capsys.readouterr().out
    assert scope.main(["--root", str(root), "--base", "origin/main", "--tests"]) == scope.EXIT_OK
    assert capsys.readouterr().out.split() == ["tests/test_gone.py"]


def test_every_test_file_of_the_tree_is_tied_to_something() -> None:
    """Каждый тест-файл набора привязан: к модулю, к пути или к «дереву целиком».

    Тест без единого ребра выбирался бы только полным набором — то есть на
    правке своего предмета молчал бы. Такой файл называется, а не угадывается.
    """
    tree = scope.graph(ROOT, scope.tracked(ROOT))
    loose = [
        name
        for name, said in tree.items()
        if scope.is_test(name) and not (said.code or said.data or said.whole)
    ]
    assert not loose, f"тест-файлы без рёбер графа: {loose}"


def test_a_removed_test_file_is_not_handed_to_pytest(tmp_path: Path) -> None:
    """Удалён тест-файл — в выборе его нет: граф базы помнит имя, а в голове файла нет."""
    root = repo(tmp_path)
    (root / "scripts" / "gone.py").write_text("X = 2\n", encoding="utf-8")
    (root / "tests" / "test_gone.py").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-qm", "тест снят")
    said = scope.choose(root, "origin/main")
    assert "tests/test_gone.py" not in (said.tests or ())


def test_nothing_touched_picks_nothing_even_a_whole_test() -> None:
    """Тронутого нет — тестов нет, и «дерево целиком» не идёт (взгляд на #1605)."""
    edges = {"tests/test_x.py": scope.Edges(whole="не разобран")}
    assert scope.chosen(edges, set()) == ()
    assert scope.chosen(edges, {"docs/a.md"}) == ("tests/test_x.py",)


def test_the_head_filter_keeps_a_full_choice() -> None:
    """Полный выбор фильтр не трогает: «все» — это все, что есть."""
    full = scope.Choice(scope.FULL, None, "x")
    assert scope.present(full, set()) is full
