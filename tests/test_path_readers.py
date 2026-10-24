"""Читатели данных проекта берут адрес из таблицы путей дерева (#1632, пакет 2).

Каждый читатель проверен с двух сторон: переназначенный таблицей путь читается
там, куда его поставили, а битая таблица — названный отказ своего читателя, а не
трасса и не молчаливое умолчание (045).
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

main_red = load_script("main_red.py")
protection = load_script("protection.py")
labels = load_script("labels.py")
schedules_seen = load_script("schedules_seen.py")
automerge = load_script("automerge.py")
findings = load_script("findings.py")
drift = load_script("drift.py")
work_plan = load_script("work_plan.py")
audit_profile = load_script("audit_profile.py")
check_reread = load_script("check_reread.py")
runs_series = load_script("runs_series.py")

#: Ключ таблицы → читатель, который обязан пойти по переназначенному адресу.
#: Файла по адресу нет, и отказ называет именно его — так видно, куда читатель
#: пошёл, без подделки содержимого каждого файла.
MISSING: dict[str, tuple[Callable[[], Any], type[BaseException]]] = {
    "rerun": (main_red.rerunnable, main_red.NotRun),
    "protection": (protection.declared, protection.NotRead),
    "labels": (labels.load, labels.BadConfig),
    "schedules": (schedules_seen.declared, schedules_seen.NotRun),
    "proposals": (drift.ours_proposals, drift.NotRun),
}

BROKEN = "paths:\n  bindings: /вне-дерева.json\n"


def table(root: Path, text: str) -> None:
    """Кладёт ответ проекта с таблицей путей в корень."""
    (root / ".pipeline.yml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("key", sorted(MISSING))
def test_the_reader_goes_where_the_table_points(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Переназначенный путь — отказ называет его, а не умолчание."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, f"paths:\n  {key}: cfg/moved.data\n")
    reader, refusal = MISSING[key]
    with pytest.raises(refusal, match=r"cfg/moved\.data"):
        reader()


@pytest.mark.parametrize("key", sorted(MISSING))
def test_a_broken_table_is_the_readers_named_refusal(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Битая таблица — отказ своего читателя с причиной, а не трасса."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, f"paths:\n  {key}: /вне-дерева\n")
    reader, refusal = MISSING[key]
    with pytest.raises(refusal, match="вне дерева"):
        reader()


def test_the_queue_and_the_kinds_read_the_moved_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ступень очереди и род находки узнают ответ по таблице; битая — умолчание с пометкой."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, "paths:\n  bindings: cfg/answer.json\n")
    for cached in (automerge.rules_answer, findings.answer_file):
        cached.cache_clear()
        assert cached() == "cfg/answer.json"
    table(tmp_path, BROKEN)
    for cached, default in (
        (automerge.rules_answer, automerge.RULES_ANSWER),
        (findings.answer_file, findings.ANSWER_FILE),
    ):
        cached.cache_clear()
        assert cached() == default
        assert "::warning::таблица путей не разобрана" in capsys.readouterr().err
        cached.cache_clear()


def test_the_roles_map_follows_the_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Карта ролей — по таблице; битая таблица — пустая карта с пометкой, а не трасса."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, "paths:\n  roles: /вне-дерева.json\n")
    findings.roles.cache_clear()
    try:
        assert findings.roles() == frozenset()
    finally:
        findings.roles.cache_clear()
    assert "::warning::таблица путей не разобрана" in capsys.readouterr().err


def test_the_contract_paths_are_relative_to_the_root(tmp_path: Path) -> None:
    """Адрес контракта — от корня по таблице, а не абсолютный путь чтения."""
    table(tmp_path, "paths:\n  proposals: cfg/proposals.json\n")
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "proposals.json").write_text('{"schema": "1.4"}', encoding="utf-8")
    assert drift.ours_relative("proposals", tmp_path) == Path("cfg/proposals.json")
    said = {name: path for name, path, _ in drift.ours_by_contract({}, tmp_path)}
    assert said["proposals"] == "cfg/proposals.json", said
    assert ("proposals", "cfg/proposals.json", "1.4") in drift.ours_by_contract({}, tmp_path)


def test_the_plan_names_a_broken_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сборщик плана на битой таблице — непрочитанный источник с причиной."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, BROKEN)
    assert "таблица путей не разобрана" in (work_plan.birth_part(bodies=[]).unread or "")


@pytest.mark.parametrize(
    ("module", "argv"),
    [
        (audit_profile, []),
        (check_reread, []),
        (runs_series, ["--store", "runs.json", "--repo", "o/r"]),
    ],
    ids=["audit_profile", "check_reread", "runs_series"],
)
def test_a_broken_table_stops_the_script_with_a_reason(
    module: Any,
    argv: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Скрипт на битой таблице не молчит и не падает трассой: код и причина."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, "paths:\n  bindings: /a.json\n  series: /b.json\n")
    assert module.main(argv) != 0
    captured = capsys.readouterr()
    assert "вне дерева" in captured.out + captured.err


pipeline_checks = load_script("pipeline_checks.py")
finding_kinds = load_script("finding_kinds.py")
review_findings = load_script("review_findings.py")


def test_a_named_path_follows_the_table_and_warns_on_a_broken_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Названный путь — из таблицы; битая таблица — умолчание с пометкой, а не отказ."""
    table(tmp_path, "paths:\n  release-doc: docs/our-release.md\n")
    assert pipeline_checks.named_path("release-doc", tmp_path) == Path("docs/our-release.md")
    table(tmp_path, "paths:\n  release-doc: /вне-дерева.md\n")
    said = pipeline_checks.named_path("release-doc", tmp_path)
    assert said == pipeline_checks.paths.PROJECT["release-doc"]
    assert "::warning::таблица путей не разобрана, «release-doc»" in capsys.readouterr().err


@pytest.mark.parametrize("key", ["finding-kinds", "proposals", "bindings"])
def test_the_kinds_read_their_files_by_the_table(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Словарь родов, очередь и ответ — по таблице; битая таблица — отказ родов с причиной."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, f"paths:\n  {key}: cfg/moved.data\n")
    assert finding_kinds.table_path(key) == Path("cfg/moved.data")
    table(tmp_path, f"paths:\n  {key}: /вне-дерева\n")
    with pytest.raises(finding_kinds.NotRun, match="вне дерева"):
        finding_kinds.table_path(key)


def test_an_answer_finding_names_the_moved_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Предмет находки об ответе — ответ по таблице, тот же, что у пола рода (022)."""
    monkeypatch.chdir(tmp_path)
    table(tmp_path, "paths:\n  bindings: cfg/answer.json\n")
    review_findings.findings.answer_file.cache_clear()
    try:
        entry = review_findings.findings.Entry(1, "замечание", "без места")
        assert review_findings.subject_of(entry) == {"cfg/answer.json"}
    finally:
        review_findings.findings.answer_file.cache_clear()
