"""Гейт старого пина проверяется отказом на настоящем репозитории (`8bb4854`).

Вход гейта — история: база и изменение. Подменять её объектами значило бы
проверять не то, что пойдёт в прогоне, поэтому случаи строятся `git`. Обе
половины: новая строка с прежней версией краснеет, подъём, перестановка и
прежнее расхождение — нет.
"""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import RunScript, load_script

pins = load_script("check_action_pins.py")

UP = "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
OLD = "      - uses: actions/checkout@v4\n"
NEWER = "      - uses: actions/checkout@v8.0.0\n"
BARE = "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
FAMILY = "      - uses: ArtVsMark/Engineering-Pipeline-Mechanisms/.github/workflows/x.yml@v1.0.0\n"


def git(repo: Path, *args: str) -> None:
    """`git` в репозитории случая; отказ — падение теста, а не пропуск."""
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, timeout=30)


def run_file(*steps: str) -> str:
    """Файл прогона с данными строками шагов."""
    return "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n" + "".join(steps)


def change(tmp_path: Path, base: dict[str, str], head: dict[str, str]) -> Path:
    """Репозиторий: прогоны базы на `main`, прогоны изменения на ветке `work`."""
    repo = tmp_path / "repo"
    flows = repo / ".github" / "workflows"
    flows.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Тест")
    for name, text in base.items():
        (flows / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "база")
    git(repo, "checkout", "-qb", "work")
    for one in flows.iterdir():
        one.unlink()
    for name, text in head.items():
        (flows / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "изменение", "--allow-empty")
    return repo


def test_a_new_line_with_the_old_pin_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """#1674: в базе уже поднятое, изменение приносит прежний мажор новой строкой."""
    repo = change(
        tmp_path, {"a.yml": run_file(UP)}, {"a.yml": run_file(UP), "b.yml": run_file(OLD)}
    )
    done = run_script("check_action_pins.py", "--base", "main", cwd=repo)
    assert done.code == pins.EXIT_FOUND, done.out + done.err
    assert "actions/checkout@v4" in done.out and "v7.0.1" in done.out


@pytest.mark.parametrize(
    ("base", "head"),
    [
        # Подъём: новая версия старше — это решение о переезде, его держит дрейф.
        ({"a.yml": run_file(UP)}, {"a.yml": run_file(UP), "b.yml": run_file(NEWER)}),
        # Перестановка: строка ушла и пришла — прироста нет.
        ({"a.yml": run_file(OLD, UP)}, {"a.yml": run_file(UP, OLD)}),
        # Прежнее расхождение, которое изменение не трогает, — дрейфу.
        ({"a.yml": run_file(OLD, UP)}, {"a.yml": run_file(OLD, UP), "b.yml": run_file(UP)}),
        # Действие семьи судит гейт заготовки (155), не этот.
        ({"a.yml": run_file(FAMILY.replace("v1.0.0", "v2.0.0"))}, {"a.yml": run_file(FAMILY)}),
        # Действия в базе нет — сравнивать не с чем.
        ({"a.yml": run_file()}, {"a.yml": run_file(OLD)}),
    ],
    ids=["подъём", "перестановка", "прежнее-расхождение", "семья", "новое-действие"],
)
def test_the_lawful_is_not_refused(
    run_script: RunScript, tmp_path: Path, base: dict[str, str], head: dict[str, str]
) -> None:
    """Законное зеленеет: гейт судит только прирост с версией ниже уже стоящей."""
    repo = change(tmp_path, base, head)
    done = run_script("check_action_pins.py", "--base", "main", cwd=repo)
    assert done.code == pins.EXIT_OK, done.out + done.err


def test_a_hash_without_a_mark_is_named_not_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Хеш без пометки порядка не несёт: строка названа предупреждением, а не пропущена молча."""
    repo = change(
        tmp_path, {"a.yml": run_file(UP)}, {"a.yml": run_file(UP), "b.yml": run_file(BARE)}
    )
    done = run_script("check_action_pins.py", "--base", "main", cwd=repo)
    assert done.code == pins.EXIT_OK and "::warning::не судится" in done.out


def test_an_unknown_base_is_not_run(run_script: RunScript, tmp_path: Path) -> None:
    """Базы нет — третий исход, а не «чисто» (039)."""
    repo = change(tmp_path, {"a.yml": run_file(UP)}, {"a.yml": run_file(UP)})
    done = run_script("check_action_pins.py", "--base", "нет-такой", cwd=repo)
    assert done.code == pins.EXIT_BROKEN


@pytest.mark.parametrize(
    ("said", "expect"),
    [
        ("v4", (4, 0, 0)),
        ("v7.0.1", (7, 0, 1)),
        ("5", (5, 0, 0)),
        ("3d3c42e5", None),
        ("main", None),
    ],
)
def test_a_version_has_a_rank_and_a_hash_has_none(
    said: str, expect: tuple[int, ...] | None
) -> None:
    """`v4` ниже `v7.0.1`; хеш и имя ветки порядка не несут."""
    assert pins.rank(said) == expect
