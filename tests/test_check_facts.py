"""Договор фактов держат механизмы (#1563): проверка издателя и её исходы.

Переехало из каталога вместе с договором: случаи — набора каталога на
`353bf10`. Самопроверка самого файла (`check_facts.selftest`) идёт здесь же:
у издателя файл лежит один, и набор держит его исходы снаружи.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script

cf = load_script("check_facts.py")

EXAMPLE = cf.EXAMPLE_PATH


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """Проверка отдельным процессом — так её зовёт шаг CI издателя."""
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_facts.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )


def test_the_selftest_is_two_sided() -> None:
    """Эталон проходит, каждая порча ловится, перенос без дерева работает."""
    assert cf.selftest() == 0


def test_the_number_agrees_with_prose_and_schema() -> None:
    """`--contract`: номер договора тот же в схеме, прозе и шаге для CI."""
    assert run("--contract").returncode == 0


def test_the_example_answers() -> None:
    """Образец выпуска отвечает договору."""
    assert run("--file", str(EXAMPLE), "--repo", "Owner/Project").returncode == 0


def test_a_foreign_repository_is_a_finding() -> None:
    """Файл о другом репозитории — расхождение, исход 1."""
    assert run("--file", str(EXAMPLE), "--repo", "Owner/Other").returncode == 1


def test_major_1_passes_with_a_move_advice(tmp_path: Path) -> None:
    """Мажор 1 принят с советом, и совет называет тег механизмов."""
    path = tmp_path / "facts.json"
    path.write_text(
        json.dumps({**json.loads(EXAMPLE.read_text(encoding="utf-8")), "schema": "1.6"}),
        encoding="utf-8",
    )
    done = run("--file", str(path), "--repo", "Owner/Project")
    assert done.returncode == 0
    assert "facts-v2.1.0 механизмов" in done.stdout


def test_without_a_file_is_the_third_outcome() -> None:
    """Без `--file` проверять нечего — исход 2 с подсказкой."""
    done = run()
    assert done.returncode == 2
    assert "--file" in done.stderr


def test_an_unreadable_file_is_the_third_outcome(tmp_path: Path) -> None:
    """Битый файл — «не отработала», а не «расхождения»."""
    path = tmp_path / "facts.json"
    path.write_text("{", encoding="utf-8")
    assert run("--file", str(path), "--repo", "Owner/Project").returncode == 2


def test_a_number_apart_from_the_prose_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--contract` отвергает прозу на прежнем номере, а не только пропускает верную."""
    prose = cf.CONTRACT_PATH.read_text(encoding="utf-8").replace(
        "FACTS_CONTRACT: facts-v2.1.0", "FACTS_CONTRACT: facts-v1.6.0"
    )
    stale = tmp_path / "facts-contract.md"
    stale.write_text(prose, encoding="utf-8")
    monkeypatch.setattr(cf, "CONTRACT_PATH", stale)
    monkeypatch.setattr(sys, "argv", ["check_facts.py", "--contract"])
    assert cf.main() == 1


def test_the_ci_step_downloads_from_the_mechanisms_release() -> None:
    """Шаг для CI издателя скачивает проверку со страниц выпуска механизмов, а не каталога."""
    step = cf.ci_step(cf.CONTRACT_PATH.read_text(encoding="utf-8")) or ""
    assert "Engineering-Pipeline-Mechanisms/releases/download/$FACTS_CONTRACT/" in step
    assert "Engineering-Incidents-Playbook" not in step
