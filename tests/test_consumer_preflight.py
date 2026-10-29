"""Загрузчик предполётной у потребителя: тег из `uses:`, выкачка в кеш, вызов механизмов (#1553)."""

import os
import shutil
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


def launch(
    tree: Path, tmp_path: Path, *args: str, env_over: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Позвать запускатель так, как его зовёт навык окна потребителя (#1552)."""
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "MECHANISMS_ORIGIN": (tmp_path / "origin").as_uri(),
        "PYTHON": sys.executable,
        **(env_over or {}),
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


@pytest.mark.parametrize(("entry", "code"), [(False, 2), (True, 0)], ids=["без-входа", "со-входом"])
def test_a_path_table_without_an_entry_is_refused(tmp_path: Path, entry: bool, code: int) -> None:
    """`paths.py` старого тега без `__main__` — отказ с причиной, а не пустой адрес (`6ae19d9`)."""
    origin = supplier(tmp_path)
    repo = origin / "o" / "m.git"
    body = "print('.rules/bindings.json')\n"
    if entry:
        body = f'if __name__ == "__main__":\n    {body}'
    (repo / "scripts" / "paths.py").write_text(body if entry else "TABLE = {}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "таблица путей")
    git(repo, "tag", "-f", "v1.2.3")
    tree = consumer(tmp_path, "o/m/.github/workflows/step-a.yml@v1.2.3")
    done = launch(tree, tmp_path, "paths.py", "bindings")
    assert done.returncode == code, done.stdout + done.stderr
    if not entry:
        assert "нет точки входа" in done.stderr, done.stderr


def test_the_preflight_loader_goes_through_the_launcher() -> None:
    """Выкачка одна (214): у загрузчика предполётной своей нет, он зовёт запускатель."""
    said = LOADER.read_text(encoding="utf-8")
    assert "git" not in said.split("set -euo pipefail", 1)[1], "у загрузчика своя выкачка"
    assert 'mechanisms.sh" preflight.py' in said
    assert onboard.paths.LAUNCHER in onboard.DATA_KITTED


def test_without_a_deadline_tool_the_loader_names_it(tmp_path: Path) -> None:
    """Нет ни `timeout`, ни `gtimeout` — отказ называет их, а не «не выкачаны» (`20bdf07`)."""
    supplier(tmp_path)
    tree = consumer(tmp_path, "o/m/.github/workflows/step-lint.yml@v1.2.3")
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("bash", "dirname", "git", "grep", "sed", "sort", "wc", "tr", "rm", "mv"):
        found = shutil.which(name)
        assert found, f"без {name} загрузчик не позвать"
        (tools / name).symlink_to(found)
    env = {
        "PATH": str(tools),
        "HOME": str(tmp_path),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "MECHANISMS_ORIGIN": (tmp_path / "origin").as_uri(),
        "PYTHON": sys.executable,
    }
    done = subprocess.run(
        [shutil.which("bash") or "bash", str(LOADER)],
        cwd=tree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )
    assert done.returncode == 2, done.stderr
    assert "нет ни timeout, ни gtimeout" in done.stderr, done.stderr


def test_a_half_cache_is_named_and_left_in_place(tmp_path: Path) -> None:
    """Остаток прежнего запускателя назван отказом и не тронут (`3341be3`, взгляды на #1640).

    Перенос каталога кеша мог бы унести готовый кеш соседа, ставший на место
    остатка между проверкой и переносом; без переноса гонке негде случиться.
    """
    supplier(tmp_path)
    tree = consumer(tmp_path, "o/m/.github/workflows/step-lint.yml@v1.2.3")
    cache = tmp_path / "cache" / "mechanisms" / "o_m@v1.2.3"
    cache.mkdir(parents=True)
    (cache / "обрывок").write_text("", encoding="utf-8")
    done = load(tree, tmp_path)
    assert done.returncode == 2, done.stderr
    assert "остаток прежнего запускателя" in done.stderr, done.stderr
    assert sorted(path.name for path in cache.iterdir()) == ["обрывок"], "остаток тронут"
    assert sorted(path.name for path in cache.parent.iterdir()) == [cache.name], (
        "рядом с кешем осталась выкачка или унесённый каталог"
    )
    shutil.rmtree(cache)
    assert load(tree, tmp_path).returncode == 0, "после удаления остатка кеш не выкачан"
    assert (cache / "scripts" / "preflight.py").is_file()


def test_a_cache_won_by_a_neighbour_is_kept(tmp_path: Path) -> None:
    """Сосед положил кеш, пока шла своя выкачка, — его кеш цел, своя копия брошена.

    Сосед встаёт ровно в окно прежнего дефекта — после выкачки, до переноса:
    `git` в пути — обёртка, которая после настоящей выкачки кладёт кеш соседа.
    Прежний код стирал его `rm -rf` перед `mv` (находка на #1626).
    """
    origin = supplier(tmp_path)
    repo = origin / "o" / "m.git"
    (repo / "scripts" / "work_plan.py").write_text("print('свой')\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "скрипт")
    git(repo, "tag", "-f", "v1.2.3")
    tree = consumer(tmp_path, "o/m/.github/workflows/step-a.yml@v1.2.3")
    cache = tmp_path / "cache" / "mechanisms" / "o_m@v1.2.3"
    shims = tmp_path / "shims"
    shims.mkdir()
    real = shutil.which("git")
    assert real, "git не найден"
    (shims / "git").write_text(
        "#!/usr/bin/env bash\n"
        f'"{real}" "$@" || exit $?\n'
        'if [[ " $* " == *" clone "* ]]; then\n'
        f'  mkdir -p "{cache}/scripts"\n'
        f'  echo "print(\'сосед\')" > "{cache}/scripts/work_plan.py"\n'
        f'  : > "{cache}/scripts/preflight.py"\n'
        "fi\n",
        encoding="utf-8",
    )
    (shims / "git").chmod(0o755)
    done = subprocess.run(
        ["bash", str(LAUNCHER), "work_plan.py"],
        cwd=tree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **{k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}",
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "MECHANISMS_ORIGIN": (tmp_path / "origin").as_uri(),
            "PYTHON": sys.executable,
        },
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert "сосед" in done.stdout, "кеш соседа подменён своей копией"
    assert not list(cache.parent.glob("*.part.*")), "своя выкачка не убрана"


def test_an_interpreter_that_does_not_run_is_named(tmp_path: Path) -> None:
    """`PYTHON` не запускается — отказ называет интерпретатор, а не «кеш неполон» (#1640)."""
    supplier(tmp_path)
    tree = consumer(tmp_path, "o/m/.github/workflows/step-a.yml@v1.2.3")
    done = launch(tree, tmp_path, "work_plan.py", env_over={"PYTHON": str(tmp_path / "нет-такого")})
    assert done.returncode == 2, done.stderr
    assert "не запускается" in done.stderr, done.stderr
    assert "неполон" not in done.stderr, done.stderr


def test_a_tree_without_mechanisms_is_named_and_not_cached(tmp_path: Path) -> None:
    """По тегу выкачано не то дерево — названо отказом, кеш не занят (взгляд на #1642).

    Прежде такая выкачка вставала на место кеша, отказ говорил «перенос
    отказал», а следующий заход называл её «остатком прежнего запускателя».
    """
    origin = supplier(tmp_path)
    repo = origin / "o" / "m.git"
    git(repo, "rm", "-q", "scripts/preflight.py")
    (repo / "README.md").write_text("не механизмы\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "не то дерево")
    git(repo, "tag", "-f", "v1.2.3")
    tree = consumer(tmp_path, "o/m/.github/workflows/step-lint.yml@v1.2.3")
    cache = tmp_path / "cache" / "mechanisms" / "o_m@v1.2.3"
    for _ in range(2):
        done = load(tree, tmp_path)
        assert done.returncode == 2, done.stderr
        assert "выкачаны не механизмы" in done.stderr, done.stderr
        assert "остаток" not in done.stderr, done.stderr
    assert not cache.exists(), "чужое дерево встало на место кеша"
    assert not list(cache.parent.glob("*.part*")), "выкачка осталась рядом с кешем"


def interpreters(tmp_path: Path, floor_has_yaml: bool) -> dict[str, str]:
    """Подделки `python9.97` (планка) и `python3`: обе зовут настоящий, метя себя в `VIA`.

    Планка без `yaml` — тот же интерпретатор с `-S`: без `site` пакетов нет.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    floor_flag = "" if floor_has_yaml else " -S"
    for name, mark, flag in (("python9.97", "планка", floor_flag), ("python3", "python3", "")):
        fake = bin_dir / name
        fake.write_text(
            f'#!/bin/sh\nVIA={mark} exec "{sys.executable}"{flag} "$@"\n', encoding="utf-8"
        )
        fake.chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "PYTHON": ""}


def floored_consumer(tmp_path: Path, floor: str = 'want="9.97"  # планка\n') -> Path:
    """Потребитель с `floor.sh` и скриптом поставщика, которому нужен `yaml`."""
    origin = supplier(tmp_path)
    repo = origin / "o" / "m.git"
    (repo / "scripts" / "work_plan.py").write_text(
        "import os\nimport yaml\nprint('через:', os.environ.get('VIA'), yaml.__name__)\n",
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "ещё скрипт")
    git(repo, "tag", "-f", "v1.2.3")
    tree = consumer(tmp_path, "o/m/.github/workflows/step-a.yml@v1.2.3")
    hooks = tree / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "floor.sh").write_text(floor, encoding="utf-8")
    return tree


def test_the_launcher_runs_a_yaml_script_on_the_floor_interpreter(tmp_path: Path) -> None:
    """Без `PYTHON` скрипт с `import yaml` идёт планкой из `floor.sh`, а не `python3` (#1771).

    Хук старта ставит `pyyaml` в интерпретатор планки. `floor.sh` записан
    кавычками и с комментарием: читается точкой, как у прочих читателей (взгляд
    на #1777).
    """
    tree = floored_consumer(tmp_path)
    done = launch(tree, tmp_path, "work_plan.py", env_over=interpreters(tmp_path, True))
    assert done.returncode == 0, done.stderr
    assert "через: планка yaml" in done.stdout, done.stdout


def test_a_floor_without_yaml_does_not_displace_python3(tmp_path: Path) -> None:
    """Планка без `yaml` не вытесняет `python3` с ним (взгляд на #1777).

    Запись планки простая: держит проверка `yaml`, а не случайность разбора.
    """
    tree = floored_consumer(tmp_path, "want=9.97\n")
    done = launch(tree, tmp_path, "work_plan.py", env_over=interpreters(tmp_path, False))
    assert done.returncode == 0, done.stderr
    assert "через: python3 yaml" in done.stdout, done.stdout
