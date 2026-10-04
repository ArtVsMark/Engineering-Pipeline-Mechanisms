"""Факты сверяются со схемой витрины до публикации (#1001).

Проверяются обе половины на настоящей форме договора 1.3 — `release` серией
`X.Y` — и третий исход: схему не прочитать — «не отработал», а не «отвечает».
Схема здесь — выдержка той же формы, а не сетевая: набор не ходит наружу.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("check_facts_schema.py")

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema", "release"],
    "properties": {
        "schema": {"type": "string"},
        "release": {"type": "string", "pattern": r"^[0-9]+\.[0-9]+$"},
    },
}


def facts_file(tmp_path: Path, **facts: Any) -> Path:
    """Файл фактов в подготовленном дереве."""
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def on_trunk(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Принадлежность коммита витрине — без сети: по умолчанию коммит в её истории."""
    asked: list[str] = []
    monkeypatch.setattr(module, "pinned_on_trunk", lambda sha, _token: asked.append(sha))
    return asked


def test_facts_of_the_contract_pass() -> None:
    """Серия `1.3` отвечает схеме — расхождений нет."""
    assert module.problems({"schema": "1.3", "release": "1.3"}, SCHEMA) == []


def test_a_tag_instead_of_a_series_is_named_by_its_path() -> None:
    """Тег `v1.3.0` — расхождение, и оно названо путём поля (#1046)."""
    found = module.problems({"schema": "1.3", "release": "v1.3.0"}, SCHEMA)
    assert len(found) == 1 and found[0].startswith("release:"), found


def test_a_missing_field_is_named_at_the_root() -> None:
    """Отсутствующее обязательное поле называется у корня."""
    found = module.problems({"schema": "1.3"}, SCHEMA)
    assert found and found[0].startswith("<корень>:"), found


def test_main_rejects_facts_that_do_not_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Файл, не отвечающий схеме, — отказ, и коммит схемы назван."""
    monkeypatch.setattr(module, "read_schema", lambda *_: SCHEMA)
    path = facts_file(tmp_path, schema="1.3", release="v1.3.0")
    assert module.main([str(path)]) == module.EXIT_REJECTED
    assert module.SCHEMA_SHA[:7] in capsys.readouterr().err


def test_main_passes_facts_that_fit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Файл, отвечающий схеме, — чисто."""
    monkeypatch.setattr(module, "read_schema", lambda *_: SCHEMA)
    assert module.main([str(facts_file(tmp_path, schema="1.3", release="1.3"))]) == module.EXIT_OK


def test_an_unreadable_schema_is_the_third_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Схему не прочитать — «не отработал», а не «отвечает» (045)."""

    def refuse(*_: object, **__: object) -> None:
        raise module.ghrest.TransportError("сети нет")

    monkeypatch.setattr(module.ghrest, "raw_json", refuse)
    path = facts_file(tmp_path, schema="1.3", release="1.3")
    assert module.main([str(path)]) == module.EXIT_BROKEN


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "нет-такого-типа"},
        {"$ref": "#/$defs/нет"},
    ],
    ids=["неизвестный-тип", "неразрешимая-ссылка"],
)
def test_a_broken_schema_is_not_run_rather_than_a_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema: dict[str, Any]
) -> None:
    """Испорченная схема — «не отработал» (2), а не «файл отклонён» (1) (взгляд на #1112)."""
    monkeypatch.setattr(module, "read_schema", lambda *_: schema)
    assert module.main([str(facts_file(tmp_path, schema="1.3"))]) == module.EXIT_BROKEN


def test_the_draft_is_taken_from_the_schema_itself() -> None:
    """Черновик — по `$schema` схемы: draft-04 читает `exclusiveMaximum` логическим."""
    draft4 = {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "properties": {"n": {"maximum": 5, "exclusiveMaximum": True}},
    }
    assert module.problems({"n": 5}, draft4), "draft-04 не прочитан как draft-04"


def test_a_format_is_checked() -> None:
    """`format` проверяется, а не служит пометкой (взгляд на #1112)."""
    schema = {"properties": {"when": {"type": "string", "format": "date"}}}
    assert module.problems({"when": "вчера"}, schema)
    assert module.problems({"when": "2026-10-04"}, schema) == []


def test_the_pinned_commit_is_asked_about_and_a_foreign_one_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_trunk: list[str]
) -> None:
    """Прибитый коммит спрашивается у витрины; не из её истории — отказ (взгляд на #1112)."""
    monkeypatch.setattr(module, "read_schema", lambda *_: SCHEMA)
    path = facts_file(tmp_path, schema="1.3", release="1.3")
    assert module.main([str(path)]) == module.EXIT_OK
    assert on_trunk == [module.SCHEMA_SHA]

    def foreign(*_: object) -> None:
        raise module.Foreign("не из истории")

    monkeypatch.setattr(module, "pinned_on_trunk", foreign)
    assert module.main([str(path)]) == module.EXIT_REJECTED


@pytest.mark.parametrize(
    ("status", "outcome"),
    [("ahead", None), ("identical", None), ("diverged", "Foreign"), ("behind", "Foreign")],
)
def test_on_trunk_reads_the_compare_answer(
    monkeypatch: pytest.MonkeyPatch, status: str, outcome: str | None
) -> None:
    """«ahead» и «identical» — коммит в истории `main`; «diverged», «behind» — нет."""
    monkeypatch.undo()
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: {"status": status})
    if outcome is None:
        module.pinned_on_trunk(module.SCHEMA_SHA, "токен")
        return
    with pytest.raises(module.Foreign):
        module.pinned_on_trunk(module.SCHEMA_SHA, "токен")


def test_on_trunk_without_a_token_or_network_is_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без токена или сети историю не спросить — «не отработал», а не «чужой»."""
    monkeypatch.undo()
    with pytest.raises(module.NotRun):
        module.pinned_on_trunk(module.SCHEMA_SHA, "")

    def refuse(*_: object, **__: object) -> None:
        raise module.ghrest.TransportError("сети нет")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    with pytest.raises(module.NotRun):
        module.pinned_on_trunk(module.SCHEMA_SHA, "токен")


def test_another_schema_names_itself_not_the_pinned_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    on_trunk: list[str],
) -> None:
    """Чужой `--schema` называется своим адресом и коммитом витрины не прикрывается."""
    monkeypatch.setattr(module, "read_schema", lambda *_: SCHEMA)
    path = facts_file(tmp_path, schema="1.3", release="1.3")
    assert module.main([str(path), "--schema", "https://пример/схема.json"]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "https://пример/схема.json" in said and module.SCHEMA_SHA[:7] not in said
    assert on_trunk == []


def test_an_unreadable_facts_file_is_the_third_outcome(tmp_path: Path) -> None:
    """Файла фактов нет — «не отработал»."""
    assert module.main([str(tmp_path / "нет.json")]) == module.EXIT_BROKEN


def test_the_schema_is_pinned_to_a_commit_not_a_branch() -> None:
    """Адрес схемы несёт sha коммита, а не имя ветки (152)."""
    assert module.SCHEMA_SHA in module.SCHEMA_URL
    assert "/main/" not in module.SCHEMA_URL
    assert len(module.SCHEMA_SHA) == 40


def test_read_schema_asks_the_pinned_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """Схема читается общим транспортом по прибитому адресу; отказ — `NotRun`."""
    asked: list[str] = []

    def answer(url: str, *_: object, **__: object) -> dict[str, Any]:
        asked.append(url)
        return SCHEMA

    monkeypatch.setattr(module.ghrest, "raw_json", answer)
    assert module.read_schema() == SCHEMA
    assert asked == [module.SCHEMA_URL]

    def refuse(*_: object, **__: object) -> None:
        raise module.ghrest.TransportError("сети нет")

    monkeypatch.setattr(module.ghrest, "raw_json", refuse)
    with pytest.raises(module.NotRun, match="схема не прочитана"):
        module.read_schema()
