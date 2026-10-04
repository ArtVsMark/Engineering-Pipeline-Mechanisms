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
