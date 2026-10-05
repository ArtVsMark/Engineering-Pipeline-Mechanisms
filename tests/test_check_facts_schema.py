"""Факты сверяются со схемой витрины до публикации (#1001).

Проверяются обе половины на настоящей форме договора 1.3 — `release` серией
`X.Y` — и третий исход: схему не прочитать — «не отработал», а не «отвечает».
Схема здесь — выдержка той же формы, а не сетевая: набор не ходит наружу.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

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
    [
        ("ahead", None),
        ("identical", None),
        ("diverged", "Foreign"),
        ("behind", "Foreign"),
        ("", "NotRun"),
        ("неведомо", "NotRun"),
    ],
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
    with pytest.raises(getattr(module, outcome)):
        module.pinned_on_trunk(module.SCHEMA_SHA, "токен")


@pytest.mark.parametrize("said", [None, {}], ids=["пустое-тело", "без-статуса"])
def test_an_answer_without_a_status_is_not_run(
    monkeypatch: pytest.MonkeyPatch, said: dict[str, Any] | None
) -> None:
    """Пустое тело и ответ без `status` — «не прочитали», а не «чужой коммит» (#1116)."""
    monkeypatch.undo()
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: said)
    with pytest.raises(module.NotRun):
        module.pinned_on_trunk(module.SCHEMA_SHA, "токен")


def test_the_verdict_file_is_written_on_a_rejection_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вердикт отказа пишется только на отказе; сбой и чистая сверка файла не оставляют (#1116)."""
    verdict = tmp_path / "verdict.txt"
    monkeypatch.setattr(module, "read_schema", lambda *_: SCHEMA)
    bad = facts_file(tmp_path, schema="1.3", release="v1.3.0")
    assert module.main([str(bad), "--verdict", str(verdict)]) == module.EXIT_REJECTED
    assert verdict.read_text(encoding="utf-8") == module.VERDICT_REJECTED
    verdict.unlink()

    good = facts_file(tmp_path, schema="1.3", release="1.3")
    assert module.main([str(good), "--verdict", str(verdict)]) == module.EXIT_OK
    assert not verdict.exists(), "чистая сверка оставила вердикт отказа"

    def broken(*_: object) -> None:
        raise AttributeError("нежданное")

    monkeypatch.setattr(module, "read_schema", broken)
    assert module.main([str(bad), "--verdict", str(verdict)]) == module.EXIT_BROKEN
    assert not verdict.exists()


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


def test_an_unknown_draft_is_not_run_and_no_draft_is_2020_12(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Неизвестный `$schema` — исход 2, а не молчаливое 2020-12; без `$schema` — 2020-12 (#1116)."""
    unknown = {**SCHEMA, "$schema": "https://пример/черновик-9"}
    monkeypatch.setattr(module, "read_schema", lambda *_: unknown)
    assert (
        module.main([str(facts_file(tmp_path, schema="1.3", release="1.3"))]) == module.EXIT_BROKEN
    )
    bare = {key: value for key, value in SCHEMA.items() if key != "$schema"}
    assert module.draft_of(bare) is module.jsonschema.Draft202012Validator


def test_an_unexpected_failure_is_not_run_rather_than_a_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Непредвиденное исключение — исход 2 с названием, а не трассировка с кодом 1 (#1116)."""

    def broken(*_: object) -> None:
        raise AttributeError("нежданное")

    monkeypatch.setattr(module, "read_schema", broken)
    assert module.main([str(facts_file(tmp_path, schema="1.3"))]) == module.EXIT_BROKEN
    assert "AttributeError" in capsys.readouterr().err


def test_a_compare_answer_that_is_not_a_mapping_is_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """`compare` ответил не словарём — заход не отработал, а не «чужой коммит» (#1116)."""
    monkeypatch.undo()
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: ["не", "словарь"])
    with pytest.raises(module.NotRun, match="не словарём"):
        module.pinned_on_trunk(module.SCHEMA_SHA, "токен")


def test_the_publish_step_stops_only_on_a_rejection() -> None:
    """В `badges.yml` установка отдельно, с предупреждением; стоп — только исход 1 (#1116)."""
    import yaml

    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "badges.yml").read_text("utf-8"))
    step = next(
        one
        for job in flow["jobs"].values()
        for one in job.get("steps", [])
        if "check_facts_schema.py" in str(one.get("run") or "")
    )
    run = step["run"]
    assert "if ! python -m pip install" in run, "провал установки читался бы как отказ"
    # Останавливает вердикт, а не код: слово сверяется с константой скрипта.
    assert f'= "{module.VERDICT_REJECTED}" ]; then' in run and "--verdict" in run
    assert '*) exit "$rc"' not in run, "код выхода снова решает остановку"


@pytest.mark.parametrize(
    ("code", "verdict", "stops"),
    [(0, "", False), (1, "rejected", True), (1, "", False), (2, "", False)],
    ids=["чисто", "отказ", "трассировка-до-main", "не-отработал"],
)
def test_the_publish_step_decides_by_the_verdict_not_the_code(
    tmp_path: Path, code: int, verdict: str, stops: bool
) -> None:
    """Исполняется сам шаг: код 1 без вердикта — предупреждение, вердикт — остановка (#1116)."""
    import os
    import subprocess

    import yaml

    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "badges.yml").read_text("utf-8"))
    run = next(
        str(one["run"])
        for job in flow["jobs"].values()
        for one in job.get("steps", [])
        if "check_facts_schema.py" in str(one.get("run") or "")
    )
    decision = run[run.index("\nrc=0") + 1 :]
    fake = f'sh -c \'[ -n "{verdict}" ] && printf %s "{verdict}" > "$0"; exit {code}\' "$verdict"'
    lines = [
        fake if "scripts/check_facts_schema.py" in line else line for line in decision.splitlines()
    ]
    script = "\n".join(lines).replace(" || rc=$?", "") + "\n"
    script = script.replace(fake, fake + " || rc=$?")
    done = subprocess.run(
        ["bash", "-c", "set -uo pipefail\n" + script],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert (done.returncode != 0) is stops, done.stdout + done.stderr
    if code and not stops:
        assert "::warning::" in done.stdout


def test_an_unwritable_verdict_keeps_the_rejection_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Вердикт не записался — отказ остаётся отказом и назван, а не «сбоем» (#1120)."""
    monkeypatch.setattr(module, "read_schema", lambda *_: SCHEMA)
    bad = facts_file(tmp_path, schema="1.3", release="v1.3.0")
    nowhere = tmp_path / "нет-каталога" / "verdict.txt"
    assert module.main([str(bad), "--verdict", str(nowhere)]) == module.EXIT_REJECTED
    said = capsys.readouterr().err
    assert "вердикт не записан" in said and "непредвиденный" not in said
