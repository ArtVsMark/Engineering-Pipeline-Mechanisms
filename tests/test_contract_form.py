"""Раздел `contract-surface:` ответа проекта: форма, умолчание и сверка путей (#1664)."""

from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("contract_form.py")
pipeline_checks = load_script("pipeline_checks.py")


def test_without_the_section_our_surface_and_kind_stay(tmp_path: Path) -> None:
    """Раздела нет — наша поверхность и род `contract`; файла ответа нет — тоже."""
    assert module.form_of(None) == module.DEFAULT_FORM
    assert pipeline_checks.contract_form_at(tmp_path / ".pipeline.yml") == module.DEFAULT_FORM


def test_the_consumer_names_its_surface_and_kind(tmp_path: Path) -> None:
    """Каталог: выгрузка и действия, род `changed`."""
    (tmp_path / ".pipeline.yml").write_text(
        "contract-surface:\n  surface: [export/rules.json, .github/actions/]\n  kind: changed\n",
        encoding="utf-8",
    )
    said = pipeline_checks.contract_form_at(tmp_path / ".pipeline.yml")
    assert said == module.Form((Path("export/rules.json"), Path(".github/actions")), "changed")


@pytest.mark.parametrize(
    ("section", "why"),
    [
        ([], "ожидалось отображение"),
        ({"paths": ["a"]}, "незнакомые ключи paths"),
        ({}, "surface — непустой список"),
        ({"surface": "export"}, "surface — непустой список"),
        ({"surface": [""]}, "непустая строка"),
        ({"surface": ["/export"]}, "вне дерева"),
        ({"surface": ["../export"]}, "вне дерева"),
        ({"surface": ["export"], "kind": "breaking"}, "род «breaking» журналу неизвестен"),
    ],
    ids=[
        "не-отображение",
        "чужой-ключ",
        "без-поверхности",
        "строка",
        "пусто",
        "абс",
        "вверх",
        "род",
    ],
)
def test_a_broken_section_is_refused_with_its_reason(section: object, why: str) -> None:
    """Битый раздел — отказ с причиной, а не молчаливое умолчание (045)."""
    with pytest.raises(module.NotRun, match=why):
        module.form_of(section)


def test_a_declared_path_missing_from_the_tree_is_named(tmp_path: Path) -> None:
    """Поверхность из несуществующего — молчание: путь без файла называется (#1664)."""
    (tmp_path / "export").mkdir()
    form = module.Form((Path("export"), Path("CONNECT.md")), "changed")
    assert module.missing(form, tmp_path) == ["CONNECT.md"]
