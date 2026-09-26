"""Архив находок сверяется с историей независимым чтением (193, #864)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("archive_against_history.py")

LOG = """Тема (#10)

Разобрано: aaa1111 — починено
Разобрано: bbb2222 дубль ccc3333, ddd4444 дубль eee5555 — повтор

Тема (#11)

- Разобрано: `fff6666` дубль `aaa1111`
"""


def archive(resolutions: dict[str, str]) -> dict[str, Any]:
    """Архив со снятиями: отпечаток → двойник."""
    return {
        "resolutions": {mark: {"by": 10, "twin_of": twin} for mark, twin in resolutions.items()}
    }


def test_a_faithful_archive_has_no_difference() -> None:
    """Снятия и пары, стоящие рядом в строке, подтверждены."""
    said = archive(
        {"aaa1111": "", "bbb2222": "ccc3333", "ddd4444": "eee5555", "fff6666": "aaa1111"}
    )
    assert module.check(said, LOG) == {"без строки": [], "связь без пары": []}


def test_a_chain_across_a_comma_is_not_a_pair() -> None:
    """«B дубль C, D дубль E» не значит «C дубль D»: цепочка через запятую — расхождение."""
    said = archive({"ccc3333": "ddd4444"})
    assert module.check(said, LOG)["связь без пары"] == ["ccc3333 дубль ddd4444"]


def test_a_resolution_absent_from_history_is_named() -> None:
    """Снятие, которого нет ни в одной строке `Разобрано:`, называется."""
    assert module.check(archive({"9999999": ""}), LOG)["без строки"] == ["9999999"]


def test_a_mark_in_prose_does_not_confirm() -> None:
    """Отпечаток в прозе, не в строке снятия, снятие не подтверждает."""
    log = "Тема (#12)\n\nупомянут 1234567 в тексте\n"
    assert module.check(archive({"1234567": ""}), log)["без строки"] == ["1234567"]


def test_main_names_the_difference_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Расхождение — код 3 и аннотация; сходится — код 0."""
    monkeypatch.setattr(module, "trunk_log", lambda ref: LOG)
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(archive({"ccc3333": "ddd4444"})), encoding="utf-8")
    assert module.main(["--archive", str(path)]) == module.EXIT_DIFFERS
    assert "::warning" in capsys.readouterr().out
    path.write_text(json.dumps(archive({"aaa1111": ""})), encoding="utf-8")
    assert module.main(["--archive", str(path)]) == module.EXIT_OK


@pytest.mark.parametrize("body", [None, {"resolutions": {}}])
def test_an_empty_input_is_the_third_outcome(tmp_path: Path, body: dict[str, Any] | None) -> None:
    """Архива нет или снятий нет — отказ, а не «сходится» (075)."""
    path = tmp_path / "findings.json"
    if body is not None:
        path.write_text(json.dumps(body), encoding="utf-8")
    assert module.main(["--archive", str(path)]) == module.EXIT_BROKEN


def test_trunk_log_reads_the_live_history() -> None:
    """История читается процессом git; несуществующая ветка — отказ."""
    assert module.trunk_log("HEAD")
    with pytest.raises(module.NotRun):
        module.trunk_log("нет-такой-ветки")


def test_resolution_lines_take_only_resolution_lines() -> None:
    """Строки снятия берутся по началу строки, с маркером списка и кавычками."""
    assert len(module.resolution_lines(LOG)) == 3


def test_the_badges_run_checks_the_archive() -> None:
    """Сборка значков сверяет архив с историей после его дописывания (#864)."""
    flow = (ROOT / ".github/workflows/badges.yml").read_text(encoding="utf-8")
    assert "archive_against_history.py" in flow
    assert flow.index("findings_archive.py") < flow.index("archive_against_history.py")


def test_twin_said_needs_the_pair_side_by_side() -> None:
    """Пара подтверждается соседством через «дубль», а не присутствием обоих."""
    assert module.twin_said("Разобрано: `aaa1111` дубль `bbb2222`", "aaa1111", "bbb2222")
    assert not module.twin_said("Разобрано: aaa1111, bbb2222 дубль ccc3333", "aaa1111", "bbb2222")
