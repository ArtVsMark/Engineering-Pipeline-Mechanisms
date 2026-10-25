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
    (tmp_path / "export").mkdir()
    (tmp_path / "export" / "rules.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".github" / "actions").mkdir(parents=True)
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
        ({"surface": ["./"]}, "всё дерево"),
        ({"surface": ["export"], "kind": ["a"]}, "журналу неизвестен"),
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
        "корень",
        "род-не-строкой",
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


def test_a_declared_path_that_is_a_link_is_named(tmp_path: Path) -> None:
    """Объявленный путь — ссылка: она называется, а не даёт пустую поверхность (взгляд на #1672)."""
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "export").symlink_to(tmp_path / "real")
    form = module.Form((Path("export"), Path("real")), "changed")
    assert module.missing(form, tmp_path) == []
    assert module.linked(form, tmp_path) == ["export"]


def test_the_form_reader_of_the_gate_refuses_a_missing_or_linked_path(tmp_path: Path) -> None:
    """Читатель формы для `check_contract` сверяет пути сам (взгляд на #1672)."""
    answer = tmp_path / ".pipeline.yml"
    answer.write_text("contract-surface:\n  surface: [нет]\n", encoding="utf-8")
    with pytest.raises(module.NotRun, match="нет в дереве — нет"):
        pipeline_checks.contract_form_at(answer)
    (tmp_path / "real").mkdir()
    (tmp_path / "export").symlink_to(tmp_path / "real")
    answer.write_text("contract-surface:\n  surface: [export]\n", encoding="utf-8")
    with pytest.raises(module.NotRun, match="символическая ссылка"):
        pipeline_checks.contract_form_at(answer)
