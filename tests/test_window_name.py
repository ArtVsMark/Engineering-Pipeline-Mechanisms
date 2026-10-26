"""Имя окна собирается из таблицы поставщика, а не придумывается (#1703).

Обе половины: проект из таблицы получает `[<окружение>] <проект> · <ДД.ММ>`;
проект вне таблицы и клон без адреса площадки — исход 3 с причиной, а не имя
из частей адреса. Негодная таблица и чужое окружение — исход 2 (039).
"""

import datetime
import json
import subprocess
from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script

module = load_script("window_name.py")


def clone(root: Path, origin: str) -> Path:
    """Пустой клон с адресом `origin`."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", origin], check=True)
    return root


def table(path: Path, names: dict[str, str]) -> Path:
    """Таблица кратких имён с разделом `names`."""
    path.write_text(json.dumps({"names": names}), encoding="utf-8")
    return path


def test_the_supplier_table_is_well_formed_and_names_us() -> None:
    """Живая таблица проходит свою форму и знает поставщика; адрес — от якоря."""
    assert module.TABLE == ROOT / module.paths.WINDOW_NAMES
    assert module.names()["artvsmark/engineering-pipeline-mechanisms"] == "EPM"


def test_a_name_has_three_parts() -> None:
    """Окружение в скобках, краткое имя, день и месяц."""
    assert module.compose("WEB", "EPM", datetime.date(2026, 10, 26)) == "[WEB] EPM · 26.10"


def test_a_project_in_the_table_gets_its_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Репозиторий из `origin` клона находит своё краткое имя без учёта регистра."""
    root = clone(tmp_path / "c", "https://github.com/artvsmark/engineering-progress-ledger.git")
    code = module.main(["--env", "local", "--root", str(root)])
    assert code == module.EXIT_OK
    today = f"{datetime.date.today():%d.%m}"
    assert capsys.readouterr().out.strip() == f"[LOCAL] EPL · {today}"


def test_a_project_outside_the_table_is_not_invented(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Имя из частей адреса правдоподобно и неверно — исход 3 с адресом таблицы."""
    root = clone(tmp_path / "c", "https://github.com/Someone/Other.git")
    assert module.main(["--env", "WEB", "--root", str(root)]) == module.EXIT_UNJUDGED
    out = capsys.readouterr().out
    assert "Someone/Other" in out and str(module.paths.WINDOW_NAMES) in out


def test_a_clone_without_a_platform_origin_is_not_judged(tmp_path: Path) -> None:
    """Локальный путь вместо адреса площадки — не судится."""
    root = clone(tmp_path / "c", str(tmp_path / "elsewhere"))
    assert module.main(["--env", "WEB", "--root", str(root)]) == module.EXIT_UNJUDGED


def test_an_unknown_environment_is_refused() -> None:
    """Окружение не из перечня 038 — отказ, а не имя с выдуманной приставкой."""
    assert module.main(["--env", "TV"]) == module.EXIT_BROKEN


@pytest.mark.parametrize(
    ("names", "said"),
    [
        ({"A/B": "EPM", "C/D": "EPM"}, "уже занято"),
        ({"A/B": "epm"}, "не 2–5"),
        ({"A/B": "ABCDEF"}, "не 2–5"),
        ({}, "names"),
    ],
)
def test_a_bad_table_is_named(tmp_path: Path, names: dict[str, str], said: str) -> None:
    """Повтор имени, строчные буквы, длина и пустой раздел — отказ с причиной."""
    with pytest.raises(module.BadTable, match=said):
        module.names(table(tmp_path / "t.json", names))
