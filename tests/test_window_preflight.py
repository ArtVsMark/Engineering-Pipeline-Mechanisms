"""Окно проверяет окружение на входе и своё красное перед толчком.

Оба механизма проверяются тем, что обязаны ОТВЕРГНУТЬ
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-proved-by-what-it-rejects.md)):
подделанная версия интерпретатора и заведомо красная команда. Зелёное на
здоровом дереве не доказывает ничего — оно так же выглядит у механизма,
который не проверяет вовсе.

ЗАМЕР, ИЗ-ЗА КОТОРОГО ОБА НАПИСАНЫ, повторился в день написания: окно шло на
3.11, дерево требует `>=3.12`, и все локальные прогоны шли не на той версии, на
которой их гоняет площадка. Механизм назвал это первой же строкой.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import RunScript, load_script

env = load_script("check_env.py")
preflight = load_script("preflight.py")

PYPROJECT = '[project]\nname = "x"\nrequires-python = ">=3.12"\n'
WORKFLOW = """
name: ci
on: [pull_request]
jobs:
  lint:
    steps:
      - name: поставить проверки
        run: python -m pip install --quiet "ruff>=0.6,<1" "mypy>=1.11,<2"
      - name: линтер
        run: ruff check scripts/
"""


def tree(root: Path, project: str = PYPROJECT, workflow: str = WORKFLOW) -> Path:
    """Собирает дерево из требований и прогона; отдаёт корень."""
    (root / "pyproject.toml").write_text(project, encoding="utf-8")
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ci.yml").write_text(workflow, encoding="utf-8")
    return root


# --- сверка окружения ---------------------------------------------------------


def test_the_floor_comes_from_the_tree(tmp_path: Path) -> None:
    """Требование к интерпретатору читается из `pyproject.toml`, а не из кода."""
    assert env.python_floor(tree(tmp_path)) == (3, 12)


def test_a_tree_without_requirements_is_an_input_error(tmp_path: Path) -> None:
    """Требований нет — отказ входа, а не «подходит любая версия» (075)."""
    with pytest.raises(env.NotRun):
        env.python_floor(tmp_path)


def test_a_requirement_without_a_floor_is_refused(tmp_path: Path) -> None:
    """`requires-python` без нижней границы не выдаётся за требование."""
    tree(tmp_path, '[project]\nname = "x"\nrequires-python = "<4"\n')
    with pytest.raises(env.NotRun, match="нижней границы"):
        env.python_floor(tmp_path)


def test_tools_come_from_the_install_lines(tmp_path: Path) -> None:
    """Инструменты и границы берутся из строк установки в прогонах."""
    found = env.needs(tree(tmp_path))
    assert found["ruff"].bounds == ">=0.6,<1"
    assert found["mypy"].bounds == ">=1.11,<2"


def test_a_tree_that_argues_with_itself_is_refused(tmp_path: Path) -> None:
    """Одно имя с разными границами в двух прогонах — отказ, а не выбор механизма.

    Обе строки одинаково правдоподобны, и взять любую значило бы решить за
    проект молча (022).
    """
    root = tree(tmp_path)
    (root / ".github" / "workflows" / "other.yml").write_text(
        'jobs:\n  x:\n    steps:\n      - run: python -m pip install "ruff>=0.9,<1"\n',
        encoding="utf-8",
    )
    with pytest.raises(env.NotRun, match="по-разному"):
        env.needs(root)


def test_a_tree_without_install_lines_is_an_input_error(tmp_path: Path) -> None:
    """Ни одной строки установки — предмет сверки не найден (075)."""
    tree(tmp_path, workflow="name: ci\non: [push]\njobs: {}\n")
    with pytest.raises(env.NotRun):
        env.needs(tmp_path)


@pytest.mark.parametrize(
    ("version", "bounds", "good"),
    [
        ("3.12.3", ">=3.12", True),
        ("3.11.15", ">=3.12", False),
        ("0.16.6", ">=0.6,<1", True),
        ("1.2.0", ">=0.6,<1", False),
        ("6.0.3", ">=6,<7", True),
        ("7.0", ">=6,<7", False),
        ("8.4.2", "", True),
    ],
)
def test_bounds_are_read_the_way_the_tree_writes_them(
    version: str, bounds: str, good: bool
) -> None:
    """Границы разбираются так, как они записаны в дереве.

    Верхняя граница здесь не украшение: без неё несовместимая версия
    применяется молча — это то, ради чего проект их и требует.
    """
    assert env.fits(version, bounds) is good


def test_an_unknown_kind_of_bound_is_refused() -> None:
    """Незнакомый вид границы — отказ, а не «наверное, годится» (068).

    Молчаливое «подходит» на неразобранной границе неотличимо от проверки, и
    именно так проверка перестаёт что-либо значить.
    """
    with pytest.raises(env.NotRun):
        env.fits("1.0", "~=1.0")


def test_the_step_says_what_to_do(run_script: RunScript, tmp_path: Path) -> None:
    """Расхождение печатается вместе с действием, а не одной констатацией.

    «Версия не та» без продолжения оставляет окно ровно там, где застало: в
    окружении, где установка в системный запрещена, а нужного интерпретатора
    нет под рукой.
    """
    tree(tmp_path, '[project]\nname = "x"\nrequires-python = ">=99.0"\n')
    run = run_script("check_env.py", "--root", str(tmp_path))
    assert run.code == 3, run.text
    assert "что делать" in run.text
    assert "venv" in run.text


# --- свой прогон перед толчком ------------------------------------------------


def test_the_commands_come_from_the_workflow(tmp_path: Path) -> None:
    """Что запускается, взято из прогона, а не перечислено в механизме.

    Иначе добавленный в прогон гейт появился бы здесь через полгода — или не
    появился бы вовсе, и разошлись бы они молча (022).
    """
    root = tree(tmp_path)
    names = [step.command for step in preflight.steps(root / ".github" / "workflows" / "ci.yml")]
    assert names == ["ruff check scripts/"], names


def test_a_platform_command_is_not_run_locally(tmp_path: Path) -> None:
    """Проверка, которой нужна площадка, локально НЕ запускается.

    Объявить её пройденной здесь значило бы завести тихий запасной путь: она
    выглядела бы зелёной, ничего не проверив (045).
    """
    root = tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n"
            "      - run: python scripts/check_pr_meta.py --files-from /tmp/x\n"
            "      - run: ruff check scripts/\n"
        ),
    )
    found = preflight.steps(root / ".github" / "workflows" / "ci.yml")
    assert [step.command for step in found] == ["ruff check scripts/"]


def test_a_multiline_command_is_refused(tmp_path: Path) -> None:
    """Многострочную команду механизм не обрезает, а отвергает.

    Обрезанная команда запустилась бы и проверила НЕ ТО, что проверяет
    площадка, — и промолчала бы об этом.
    """
    root = tree(
        tmp_path,
        workflow=("jobs:\n  x:\n    steps:\n      - name: свод\n        run: ruff check \\\\\n"),
    )
    with pytest.raises(preflight.NotRun, match="многострочная"):
        preflight.steps(root / ".github" / "workflows" / "ci.yml")


def test_a_workflow_without_commands_is_an_input_error(tmp_path: Path) -> None:
    """Ни одной выполнимой команды — отказ входа, а не «всё зелено» (075)."""
    root = tree(tmp_path, workflow="jobs:\n  x:\n    steps:\n      - uses: actions/checkout@v4\n")
    with pytest.raises(preflight.NotRun):
        preflight.steps(root / ".github" / "workflows" / "ci.yml")


def test_red_is_caught_before_the_push(run_script: RunScript, tmp_path: Path) -> None:
    """Заведомо красная команда ловится здесь, а не логами площадки."""
    tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: заведомо красное\n"
            "        run: ruff check nowhere/\n"
        ),
    )
    run = run_script("preflight.py", "--root", str(tmp_path))
    assert run.code == 3, run.text
    assert "толкать рано" in run.text


def test_the_step_names_what_it_cannot_check(run_script: RunScript, tmp_path: Path) -> None:
    """Невыполнимое здесь названо НЕВЫПОЛНЕННЫМ, а не пропущено молча (046)."""
    tree(tmp_path)
    run = run_script("preflight.py", "--root", str(tmp_path), "--list")
    assert run.code == 0, run.text
    assert "не проверяет" in run.text
    assert "attribution" in run.text


def test_the_tools_come_from_the_running_interpreter(tmp_path: Path) -> None:
    """Команды идут тем интерпретатором, которым запущен механизм.

    Иначе `pytest` и `ruff` придут из системного пути, с ДРУГОЙ версией, — то
    есть прогон проверит не то окружение, ради которого он и заведён. Замер:
    ровно так этот механизм и упал в первом же заходе.
    """
    room = preflight.environment()
    assert room["PATH"].startswith(str(Path(preflight.sys.executable).parent))
