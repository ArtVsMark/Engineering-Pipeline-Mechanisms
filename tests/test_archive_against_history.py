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

Разобрано: `fff6666` дубль `aaa1111`
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
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written[module.UNCONFIRMED] == ["ccc3333 дубль ddd4444"], "список не лёг в архив"
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
    """Строкой снятия считается слово с двоеточием в начале строки, как у разбора."""
    assert len(module.resolution_lines(LOG)) == 3
    assert module.resolution_lines("- разобрано — в прозе\nразобрано без двоеточия") == []


def test_the_badges_run_checks_the_archive() -> None:
    """Сборка значков сверяет архив с историей после его дописывания (#864)."""
    flow = (ROOT / ".github/workflows/badges.yml").read_text(encoding="utf-8")
    assert "archive_against_history.py" in flow
    assert flow.index("findings_archive.py") < flow.index("archive_against_history.py")


def test_twin_said_needs_the_pair_side_by_side() -> None:
    """Пара подтверждается соседством через «дубль», а не присутствием обоих."""
    assert module.twin_said("Разобрано: `aaa1111` дубль `bbb2222`", "aaa1111", "bbb2222")
    assert not module.twin_said("Разобрано: aaa1111, bbb2222 дубль ccc3333", "aaa1111", "bbb2222")


def test_a_known_difference_is_not_warned_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Расхождение, уже названное прежним архивом, предупреждения не даёт; новое — даёт."""
    monkeypatch.setattr(module, "trunk_log", lambda ref: LOG)
    previous = tmp_path / "prev.json"
    previous.write_text(
        json.dumps({module.UNCONFIRMED: ["ccc3333 дубль ddd4444"]}), encoding="utf-8"
    )
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(archive({"ccc3333": "ddd4444"})), encoding="utf-8")
    assert module.main(["--archive", str(path), "--previous", str(previous)]) == module.EXIT_OK
    assert "::warning" not in capsys.readouterr().out
    path.write_text(json.dumps(archive({"ccc3333": "ddd4444", "9999999": ""})), encoding="utf-8")
    assert module.main(["--archive", str(path), "--previous", str(previous)]) == module.EXIT_DIFFERS


def test_a_mark_inside_a_longer_hash_does_not_confirm() -> None:
    """Отпечаток внутри длинного хеша снятие не подтверждает: граница — целое слово."""
    log = "Разобрано: aaa1111bcd — хеш коммита, а не отпечаток\n"
    assert module.check(archive({"aaa1111": ""}), log)["без строки"] == ["aaa1111"]


def test_a_fix_check_resolution_is_counted_apart() -> None:
    """Снятие проверкой починки строки не имеет и расхождением не считается (#848)."""
    said = {"resolutions": {"1234567": {"by": 10, "twin_of": "", "fix_check": True}}}
    assert module.check(said, LOG) == {"без строки": [], "связь без пары": []}


def test_fresh_names_only_the_new() -> None:
    """Новое — то, чего не было в прежнем списке."""
    found = {"без строки": ["a"], "связь без пары": ["b дубль c"]}
    assert module.fresh(found, ["a"]) == ["b дубль c"]


def test_mark_said_needs_a_whole_word() -> None:
    """Отпечаток — целое слово из семи знаков."""
    assert module.mark_said("Разобрано: aaa1111 — да", "aaa1111")
    assert not module.mark_said("Разобрано: aaa11112 — нет", "aaa1111")


def test_read_refuses_a_missing_archive(tmp_path: Path) -> None:
    """Нет файла архива — отказ."""
    with pytest.raises(module.NotRun):
        module.read(tmp_path / "нет.json")


@pytest.mark.parametrize(
    ("line", "pairs"),
    [
        ("Разобрано: aaaaaaa дубль bbbbbbb", {("aaaaaaa", "bbbbbbb")}),
        (
            "Разобрано: aaaaaaa, ccccccc дубль bbbbbbb",
            {("aaaaaaa", "bbbbbbb"), ("ccccccc", "bbbbbbb")},
        ),
        (
            "Разобрано: aaaaaaa дубль bbbbbbb, ccccccc дубль ddddddd",
            {("aaaaaaa", "bbbbbbb"), ("ccccccc", "ddddddd")},
        ),
        (
            "Разобрано: aaaaaaa дубль bbbbbbb дубль ccccccc",
            {("aaaaaaa", "bbbbbbb"), ("bbbbbbb", "ccccccc")},
        ),
        ("Разобрано: aaaaaaa дубль bbbbbbb, ccccccc", {("aaaaaaa", "bbbbbbb")}),
    ],
    ids=["пара", "список", "пары", "цепочка", "хвост"],
)
def test_pairs_in_reads_the_grammar_directly(line: str, pairs: set[tuple[str, str]]) -> None:
    """Независимый читатель различает пары, списки и цепочки так же, как грамматика (#872)."""
    assert module.pairs_in(line) == pairs
