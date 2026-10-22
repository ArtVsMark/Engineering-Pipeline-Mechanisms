"""Форма контракта семьи: чужой манифест не проходит как свой.

Переехало из каталога вместе с формой (#1563): случаи `изъян_формы` набора
каталога на `353bf10`. Сбор сводки остался у каталога, и его случаев здесь нет.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

contract = load_script("family_contract.py")

GOOD: dict[str, Any] = {
    "schema": "1.0",
    "project": "o/a",
    "release": None,
    "gives": {"x": "1.0"},
    "takes": [],
}


def test_a_good_manifest_has_no_flaw() -> None:
    """Манифест верной формы — без изъяна; минор формата читается (поля, а не слом)."""
    assert contract.form_flaw(GOOD) is None
    assert contract.form_flaw({**GOOD, "schema": "1.3"}) is None
    assert contract.form_flaw({**GOOD, "skips": {"EPM": "шаги не нужны"}}) is None


@pytest.mark.parametrize(
    ("doc", "flaw"),
    [
        ([], "не объект"),
        ({**GOOD, "gives": None}, "«gives» не того типа"),
        ({key: value for key, value in GOOD.items() if key != "takes"}, "нет ключа «takes»"),
        ({**GOOD, "schema": "2.0"}, "формат 2.0"),
        ({**GOOD, "skips": {"EPM": " "}}, "skips"),
        ({**GOOD, "skips": ["EPM"]}, "skips"),
    ],
)
def test_a_foreign_form_is_named(doc: Any, flaw: str) -> None:
    """Каждая чужая форма называется своей причиной."""
    assert flaw in (contract.form_flaw(doc) or "")


def test_write_makes_the_folder_and_ends_with_newline(tmp_path: Path) -> None:
    """Запись создаёт папку, держит кириллицу как есть и кончается переводом строки."""
    path = tmp_path / "a" / "b.json"
    contract.write(path, {"why": "сверено"})
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert "сверено" in text
    assert json.loads(text) == {"why": "сверено"}
