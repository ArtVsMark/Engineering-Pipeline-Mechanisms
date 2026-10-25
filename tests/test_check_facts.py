"""Договор фактов держат механизмы (#1563): проверка издателя и её исходы.

Переехало из каталога вместе с договором: случаи — набора каталога на
`353bf10`. Самопроверка самого файла (`check_facts.selftest`) идёт здесь же:
у издателя файл лежит один, и набор держит его исходы снаружи.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

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
    # Номер — из `facts.version`: вписанный строкой, он не поймал бы совет на
    # прежнем теге после подъёма договора (взгляд на #1679).
    number = (EXAMPLE.parent / "facts.version").read_text(encoding="utf-8").strip()
    assert f"facts-v{number} механизмов" in done.stdout


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
    # Номер — из `facts.version`, а не строкой: вписанный рукой, он молча
    # перестал бы совпадать с прозой при первом же подъёме договора, и подмена
    # ничего не подменила бы (#1675).
    number = (cf.CONTRACT_PATH.parent / "facts.version").read_text(encoding="utf-8").strip()
    said = cf.CONTRACT_PATH.read_text(encoding="utf-8")
    assert f"FACTS_CONTRACT: facts-v{number}" in said, "шаг для CI не назван номером договора"
    prose = said.replace(f"FACTS_CONTRACT: facts-v{number}", "FACTS_CONTRACT: facts-v1.6.0")
    stale = tmp_path / "facts-contract.md"
    stale.write_text(prose, encoding="utf-8")
    monkeypatch.setattr(cf, "CONTRACT_PATH", stale)
    monkeypatch.setattr(sys, "argv", ["check_facts.py", "--contract"])
    assert cf.main() == 1


def test_the_ci_step_downloads_from_the_mechanisms_release() -> None:
    """Шаг для CI издателя читает проверку из дерева механизмов по тегу, а не каталога.

    Из дерева, а не со страницы выпуска: файлы страницы заменяются, не трогая тега.
    """
    step = cf.ci_step(cf.CONTRACT_PATH.read_text(encoding="utf-8")) or ""
    assert (
        "raw.githubusercontent.com/ArtVsMark/Engineering-Pipeline-Mechanisms/$FACTS_CONTRACT/"
        in step
    )
    assert "releases/download" not in step
    assert "Engineering-Incidents-Playbook" not in step


# --- имена проверки по одному ---------------------------------------------


def schema() -> dict[str, Any]:
    """Схема договора с диска — та, что едет на страницу выпуска."""
    said: dict[str, Any] = json.loads(cf.SCHEMA_PATH.read_text(encoding="utf-8"))
    return said


def test_validate_passes_the_example_and_names_the_place_of_a_flaw() -> None:
    """`validate`: образец чист, порча называется путём к месту."""
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert cf.validate(example, schema()) == []
    assert cf.validate({"x": 1}, {"type": "object", "properties": {"x": {"type": "string"}}})
    with pytest.raises(ValueError, match="незнакомого"):
        cf.validate({}, {"strange": True})


def test_advise_is_silent_on_the_example_and_names_a_root_field() -> None:
    """`advise`: образец без советов, чужое поле корня — совет, а не отказ."""
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    # Серия «мажор.минор», а не полный номер: так зовут оба вызывающих.
    number = cf.contract_version(cf.VERSION_PATH.read_text(encoding="utf-8"))
    current = ".".join(number.split(".")[:2])
    assert cf.advise(example, schema(), current) == []
    said = cf.advise({**example, "своё": 1}, schema(), current)
    assert any("своё" in one for one in said), said
    assert cf.advise([], schema(), current) == []


def test_advise_family_names_a_missing_manifest() -> None:
    """`advise_family`: нет манифеста — совет с адресом, есть верный — тишина."""
    assert any(cf.MANIFEST_PATH in one for one in cf.advise_family(None))
    assert cf.advise_family("не JSON")


def test_annotate_is_a_platform_command_only_in_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """`annotate`: в прогоне — команда площадки, вне его — текст как есть."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert cf.annotate("warning", "т") == "::warning::т"
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert cf.annotate("warning", "т") == "т"


def test_contract_version_takes_only_three_numbers() -> None:
    """`contract_version`: X.Y.Z проходит, иная форма — `ValueError`."""
    assert cf.contract_version(" 2.1.0\n") == "2.1.0"
    with pytest.raises(ValueError, match="не формы"):
        cf.contract_version("2.1")


def test_contract_drift_catches_a_number_raised_in_one_place() -> None:
    """`contract_drift`: свой номер — пусто, чужой — расхождение названо."""
    number = cf.contract_version(cf.VERSION_PATH.read_text(encoding="utf-8"))
    prose = cf.CONTRACT_PATH.read_text(encoding="utf-8")
    assert cf.contract_drift(number, schema(), prose) == []
    assert cf.contract_drift("9.9.0", schema(), prose)


def test_read_manifest_tells_absent_from_broken(tmp_path: Path) -> None:
    """`read_manifest`: нет файла — `None`, не JSON — причина строкой."""
    assert cf.read_manifest(tmp_path / "нет.json") is None
    (tmp_path / "битый.json").write_text("{", encoding="utf-8")
    assert cf.read_manifest(tmp_path / "битый.json") == "не JSON"
    (tmp_path / "верный.json").write_text('{"family": "1.0"}', encoding="utf-8")
    assert cf.read_manifest(tmp_path / "верный.json") == {"family": "1.0"}


def test_the_move_advice_names_the_contract_it_judges_by() -> None:
    """Совет о переезде называет тег и формат того договора, которым судят, а не вписанный."""
    said = cf.moved("2.7")
    assert "facts-v2.7.0" in said and "schema «2.7»" in said
