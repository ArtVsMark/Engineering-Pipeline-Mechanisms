"""Загрузчик предполётной у потребителя: тег из `uses:`, выкачка в кеш, вызов механизмов (#1553)."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

onboard = load_script("onboard.py")

LOADER: Final = ROOT / onboard.DATA_KIT / onboard.paths.PREFLIGHT_LOADER
#: Заглушка предполётной поставщика: печатает доводы и путь к транспорту.
STUB: Final = (
    "import os, sys\n"
    "print('доводы:', *sys.argv[1:])\n"
    "print('транспорт:', os.environ['PYTHONPATH'])\n"
)


def git(where: Path, *args: str) -> str:
    """Git подделки, с дедлайном."""
    done = subprocess.run(
        ["git", "-C", str(where), "-c", "user.email=a@b", "-c", "user.name=t", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return done.stdout


def supplier(tmp_path: Path, tag: str = "v1.2.3") -> Path:
    """Поставщик `o/m`: заглушка `scripts/preflight.py` под тегом."""
    origin = tmp_path / "origin"
    repo = origin / "o" / "m.git"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "preflight.py").write_text(STUB, encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "механизмы")
    git(repo, "tag", tag)
    return origin


def consumer(tmp_path: Path, *calls: str) -> Path:
    """Дерево потребителя, чьи прогоны зовут общие шаги по названным ссылкам."""
    tree = tmp_path / "consumer"
    flows = tree / ".github" / "workflows"
    flows.mkdir(parents=True)
    for number, call in enumerate(calls):
        (flows / f"f{number}.yml").write_text(f"jobs:\n  j:\n    uses: {call}\n", encoding="utf-8")
    git(tree, "init", "-q", "-b", "main")
    return tree


def load(tree: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Позвать загрузчик так, как его зовёт окно потребителя: `bash <путь>` из дерева."""
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "MECHANISMS_ORIGIN": (tmp_path / "origin").as_uri(),
        "PYTHON": sys.executable,
    }
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        ["bash", str(LOADER), *args],
        cwd=tree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )


def test_the_loader_runs_the_supplier_preflight_at_the_tag(tmp_path: Path) -> None:
    """Тег — из `uses:`; выкачка — в кеш; предполётная — поставщика, против дерева потребителя."""
    supplier(tmp_path)
    tree = consumer(tmp_path, "o/m/.github/workflows/step-lint.yml@v1.2.3")
    done = load(tree, tmp_path, "--list")
    assert done.returncode == 0, done.stderr
    cache = tmp_path / "cache" / "mechanisms" / "o_m@v1.2.3"
    assert (
        f"доводы: --root {tree.resolve()} --mechanisms {cache} --supplier o/m --list" in done.stdout
    )
    assert f"транспорт: {cache}/packages/transport" in done.stdout


def test_foreign_and_commented_calls_are_not_the_supplier(tmp_path: Path) -> None:
    """Чужой переиспользуемый прогон и старый `# uses:` поставщиком не считаются (#1618)."""
    supplier(tmp_path)
    tree = consumer(
        tmp_path,
        "o/m/.github/workflows/step-lint.yml@v1.2.3",
        "someone/else/.github/workflows/deploy.yml@v2",
    )
    (tree / ".github" / "workflows" / "old.yml").write_text(
        "jobs:\n  j:\n    # uses: o/m/.github/workflows/step-lint.yml@v1.0.0\n",
        encoding="utf-8",
    )
    done = load(tree, tmp_path)
    assert done.returncode == 0, done.stderr
    assert "--supplier o/m" in done.stdout


def test_two_tags_are_named_as_pairs(tmp_path: Path) -> None:
    """Причина отказа называет пары «поставщик тег», а не слова вперемешку (#1618)."""
    supplier(tmp_path)
    tree = consumer(
        tmp_path,
        "o/m/.github/workflows/step-a.yml@v1.2.3",
        "o/m/.github/workflows/step-b.yml@v1.3.0",
    )
    assert "o/m v1.2.3; o/m v1.3.0" in load(tree, tmp_path).stderr


def test_a_second_run_takes_the_cache(tmp_path: Path) -> None:
    """Второй заход не ходит к поставщику: выкачка тега лежит в кеше окна."""
    supplier(tmp_path)
    tree = consumer(tmp_path, '"o/m/.github/workflows/step-lint.yml@v1.2.3"')
    assert load(tree, tmp_path).returncode == 0
    (tmp_path / "origin").rename(tmp_path / "gone")
    assert load(tree, tmp_path).returncode == 0


@pytest.mark.parametrize(
    ("calls", "said"),
    [
        ((), "нет вызова общих шагов"),
        (
            (
                "o/m/.github/workflows/step-a.yml@v1.2.3",
                "o/m/.github/workflows/step-b.yml@v1.3.0",
            ),
            "по разным ссылкам",
        ),
        (("o/m/.github/workflows/step-a.yml@main",), "не по закреплённому тегу"),
        (("o/m/.github/workflows/step-a.yml@v9.9.9",), "не выкачаны"),
    ],
    ids=["нет-вызовов", "разные-теги", "ветка-а-не-тег", "тега-нет"],
)
def test_the_loader_refuses_with_a_reason(
    tmp_path: Path, calls: tuple[str, ...], said: str
) -> None:
    """Отказ загрузчика — исход 2 с причиной, а не трасса и не тихий успех (039)."""
    supplier(tmp_path)
    tree = consumer(tmp_path, *calls)
    done = load(tree, tmp_path)
    assert done.returncode == 2, done.stdout + done.stderr
    assert said in done.stderr


def test_the_loader_is_laid_by_onboarding() -> None:
    """Загрузчик — заготовка захода подключения, а не файл, который потребитель пишет сам."""
    assert onboard.paths.PREFLIGHT_LOADER in onboard.DATA_KITTED
    assert LOADER.is_file()


LAUNCHER: Final = ROOT / onboard.DATA_KIT / onboard.paths.LAUNCHER


def launch(tree: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Позвать запускатель так, как его зовёт навык окна потребителя (#1552)."""
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "MECHANISMS_ORIGIN": (tmp_path / "origin").as_uri(),
        "PYTHON": sys.executable,
    }
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        ["bash", str(LAUNCHER), *args],
        cwd=tree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )


def test_the_launcher_runs_any_supplier_script_from_the_consumer_root(tmp_path: Path) -> None:
    """Скрипт выкачки зовётся из корня потребителя, с `MECHANISMS`, без ключей предполётной."""
    origin = supplier(tmp_path)
    repo = origin / "o" / "m.git"
    (repo / "scripts" / "work_plan.py").write_text(
        "import os, sys\nprint('доводы:', *sys.argv[1:])\nprint('где:', os.getcwd())\n"
        "print('механизмы:', os.environ['MECHANISMS'])\n",
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "ещё скрипт")
    git(repo, "tag", "-f", "v1.2.3")
    tree = consumer(tmp_path, "o/m/.github/workflows/step-a.yml@v1.2.3")
    done = launch(tree, tmp_path, "work_plan.py", "--apply")
    assert done.returncode == 0, done.stderr
    assert "доводы: --apply" in done.stdout and "--root" not in done.stdout, done.stdout
    assert f"где: {tree.resolve()}" in done.stdout, done.stdout
    assert "mechanisms/o_m@v1.2.3" in done.stdout, done.stdout


@pytest.mark.parametrize(
    ("args", "said"),
    [
        ((), "не назван скрипт"),
        (("../x.py",), "не имя скрипта"),
        (("нет.py",), "не имя скрипта"),
        (("missing.py",), "нет scripts/missing.py"),
    ],
    ids=["без-скрипта", "путь", "не-латиница", "нет-такого"],
)
def test_the_launcher_refuses_with_a_reason(
    tmp_path: Path, args: tuple[str, ...], said: str
) -> None:
    """Отказ запускателя — исход 2 с причиной: имя вне `scripts/` не зовётся (039)."""
    supplier(tmp_path)
    tree = consumer(tmp_path, "o/m/.github/workflows/step-a.yml@v1.2.3")
    done = launch(tree, tmp_path, *args)
    assert done.returncode == 2, done.stdout + done.stderr
    assert said in done.stderr, done.stderr


def test_the_preflight_loader_goes_through_the_launcher() -> None:
    """Выкачка одна (214): у загрузчика предполётной своей нет, он зовёт запускатель."""
    said = LOADER.read_text(encoding="utf-8")
    assert "git" not in said.split("set -euo pipefail", 1)[1], "у загрузчика своя выкачка"
    assert 'mechanisms.sh" preflight.py' in said
    assert onboard.paths.LAUNCHER in onboard.DATA_KITTED
