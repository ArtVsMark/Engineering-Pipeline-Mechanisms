"""Перепись отдачи после выпуска: раздел заметок, сдвиги с прошлого тега, отказ вслух (#1658)."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script
from tests.test_portable import ANSWERS

census = load_script("portable_census.py")
release = load_script("release.py")


def answers(**said: str) -> dict[str, Any]:
    """Перепись с ответами `путь=ответ`; у `ours` причина `@provider`."""
    return {
        "answers": {
            key.replace("__", "/"): {
                "answer": one,
                **({"why": "@provider"} if one == "ours" else {}),
            }
            for key, one in said.items()
        },
        "verified_by": {"whole-port": {"where": "none"}, "consumer-path": {"where": "x.yml"}},
    }


def repo(tmp_path: Path, tags: list[tuple[str, dict[str, Any] | None]]) -> Path:
    """Настоящий git с тегом на каждую перепись; `None` — тег без переписи."""
    run = ["git", "-C", str(tmp_path)]
    subprocess.run([*run, "init", "--quiet", "-b", "main"], check=True)
    subprocess.run([*run, "config", "user.email", "т@т"], check=True)
    subprocess.run([*run, "config", "user.name", "т"], check=True)
    target = tmp_path / ".rules" / "portable.json"
    for tag, said in tags:
        if said is None:
            (tmp_path / "README.md").write_text(tag, encoding="utf-8")
        else:
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(said), encoding="utf-8")
        subprocess.run([*run, "add", "-A"], check=True)
        subprocess.run([*run, "commit", "--quiet", "-m", tag], check=True)
        subprocess.run([*run, "tag", tag], check=True)
    return tmp_path


def test_the_section_counts_the_scale_and_marks_fresh_ours() -> None:
    """Счёт с разницей; `ours`, пришедшее с прошлого тега, отмечено; сдвиги и ушедшее названы."""
    before = census.parsed(json.dumps(answers(a="as-is", b="ours", c="configured")), "до")
    now = census.parsed(json.dumps(answers(a="ours", b="ours", d="as-is")), "сейчас")
    said = "\n".join(census.section(now, before, "v1.0.0"))
    assert "Ответов в переписи: **3** (на `v1.0.0` — 3)." in said
    assert "| `ours` | 2 | +1 |" in said and "| `configured` | 0 | -1 |" in said
    assert "`a` ★, `b`" in said, "пришедшее с прошлого выпуска не отмечено"
    assert "- `a`: as-is → ours" in said and "- `d`: — → as-is" in said
    assert "ушли из переписи: `c`" in said
    assert "**Каналы переноса без прогона:** `whole-port`" in said


def test_the_table_rows_add_up_to_the_total() -> None:
    """Строки таблицы складываются в итог: неотвеченное — своя строка, а не пропажа (`99c6b30`)."""
    now = census.parsed(json.dumps(answers(a="as-is", b="unreviewed", c="ours")), "сейчас")
    said = census.section(now, None, None)
    assert "| `unreviewed` | 1 | — |" in said
    rows = [line for line in said if line.startswith("| `")]
    assert sum(int(line.split("|")[2]) for line in rows) == len(now.answers)


def test_the_scale_is_the_gate_scale() -> None:
    """Шкала раздела — та же, что допускает гейт формы переписи."""
    assert set(census.SCALE) == ANSWERS


def test_a_broken_census_is_refused_with_its_place() -> None:
    """Не JSON и перепись без `answers` — `NotRun` с местом, а не пустой раздел (045)."""
    with pytest.raises(census.NotRun, match=r"v1\.0\.0:"):
        census.parsed("{", "v1.0.0:.rules/portable.json")
    with pytest.raises(census.NotRun, match="нет словаря"):
        census.parsed("[]", "голова")
    assert census.parsed('{"answers": {"a": {"answer": "as-is"}, "b": 1}}', "x") == census.Census(
        {"a": {"answer": "as-is"}}, {}
    ), "запись не той формы должна отсеиваться"


def test_the_release_section_compares_with_the_previous_tag(tmp_path: Path) -> None:
    """Раздел тега сравнивается с предыдущим выпуском его истории, а не с головой."""
    root = repo(
        tmp_path,
        [
            ("v1.0.0", answers(a="ours")),
            ("v1.1.0", answers(a="as-is")),
            ("v1.2.0", answers(a="ours")),
        ],
    )
    assert census.previous_tag("v1.1.0", root) == "v1.0.0"
    assert census.previous_tag("v1.0.0", root) is None
    said = "\n".join(census.for_release("v1.1.0", root))
    assert "Сменили шкалу с `v1.0.0`:** 1" in said and "- `a`: ours → as-is" in said


def test_no_census_on_the_tag_means_no_section(tmp_path: Path) -> None:
    """Проект без переписи — раздела нет; прошлый тег без неё — сравнения нет, а не отказ."""
    root = repo(tmp_path, [("v1.0.0", None), ("v1.1.0", answers(a="ours"))])
    assert not census.present("v1.0.0", root) and census.present("v1.1.0", root)
    assert census.scale_of(census.at("v1.1.0", root)) == {"ours": 1}
    assert census.for_release("v1.0.0", root) == []
    said = "\n".join(census.for_release("v1.1.0", root))
    assert "Ответов в переписи: **1**." in said and "Сменили шкалу" not in said
    # Прошлый тег без переписи — названо, а не похоже на первый выпуск (`f00240f`).
    assert "у прошлого выпуска `v1.0.0` переписи нет" in said
    (tmp_path / "п").mkdir()
    first = "\n".join(census.for_release("v1.1.0", repo(tmp_path / "п", [("v1.1.0", answers())])))
    assert "Сравнения нет" not in first


def test_a_tag_on_the_head_is_not_its_own_previous(tmp_path: Path) -> None:
    """`--tag HEAD` с тегом на голове — прошлый выпуск ниже, а не он сам (`e784e1f`)."""
    root = repo(tmp_path, [("v1.0.0", answers(a="ours")), ("v1.1.0", answers(a="as-is"))])
    assert census.previous_tag("HEAD", root) == "v1.0.0"


def test_the_release_page_carries_the_section_or_its_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Страница выпуска несёт раздел; несобранная перепись — строка с причиной, страница цела."""
    monkeypatch.setattr(release, "contract_at", lambda _tag: "0.14.0")
    monkeypatch.setattr(release.build_changelog, "read_fragments", lambda _where: [])
    monkeypatch.setattr(release.portable_census, "for_release", lambda *_: ["### Перепись отдачи"])
    assert "### Перепись отдачи" in release.page_body("1.12.0", "o/r")

    def refuse(*_: Any) -> list[str]:
        raise release.portable_census.NotRun("тег не прочитан")

    monkeypatch.setattr(release.portable_census, "for_release", refuse)
    said = release.page_body("1.12.0", "o/r")
    assert "Перепись отдачи не собрана: тег не прочитан." in said
    assert "Версия контракта на момент выпуска — `0.14.0`" in said


def test_main_prints_the_section_and_names_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Точка входа: раздел — код 0; перепись не разобрана — причина и код 2."""
    root = repo(tmp_path, [("v1.0.0", answers(a="ours"))])
    assert census.main(["--tag", "v1.0.0", "--root", str(root)]) == census.EXIT_OK
    assert "### Перепись отдачи" in capsys.readouterr().out
    (root / ".rules" / "portable.json").write_text("{", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "commit", "-qam", "битая"], check=True)
    assert census.main(["--root", str(root)]) == census.EXIT_BROKEN
    assert "перепись отдачи не собрана" in capsys.readouterr().err


def test_a_broken_census_on_the_previous_tag_is_a_refusal(tmp_path: Path) -> None:
    """Перепись прошлого тега не разобрана — отказ с её местом, а не раздел без сравнения (045)."""
    root = repo(tmp_path, [])
    run = ["git", "-C", str(root)]
    (root / ".rules").mkdir()
    (root / ".rules" / "portable.json").write_text("{", encoding="utf-8")
    subprocess.run([*run, "add", "-A"], check=True)
    subprocess.run([*run, "commit", "--quiet", "-m", "битая"], check=True)
    subprocess.run([*run, "tag", "v1.0.0"], check=True)
    repo_tail = json.dumps(answers(a="as-is"))
    (root / ".rules" / "portable.json").write_text(repo_tail, encoding="utf-8")
    subprocess.run([*run, "commit", "--quiet", "-am", "целая"], check=True)
    subprocess.run([*run, "tag", "v1.1.0"], check=True)
    with pytest.raises(census.NotRun, match=r"v1\.0\.0:"):
        census.for_release("v1.1.0", root)


def test_without_a_previous_tag_there_is_no_delta_and_no_mark() -> None:
    """Первый выпуск: разница «—», а не «+0», и без ★ — сравнения не было (взгляд на #1660)."""
    now = census.parsed(json.dumps(answers(a="ours", b="as-is")), "сейчас")
    said = "\n".join(census.section(now, None, None))
    assert "| `ours` | 1 | — |" in said and "+0" not in said
    assert "★" not in said and "`a`" in said


def test_verified_by_of_the_wrong_form_is_a_refusal() -> None:
    """`verified_by` не словарь — `NotRun` с местом, а не трасса, роняющая страницу (#1660)."""
    with pytest.raises(census.NotRun, match="verified_by"):
        census.parsed(json.dumps({"answers": {}, "verified_by": ["x"]}), "v1.0.0")
