"""База находок для анализа (#1139): сборка из архива, повтор без дублей, отказ на чужой форме."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import RunScript, load_script

module = load_script("findings_db.py")
archive_module = load_script("findings_archive.py")

BROKEN = 2
CLEAN = 0


def finding(pr: int, **fields: Any) -> dict[str, Any]:
    """Запись находки в форме архива; поля по умолчанию — как у живого архива."""
    return {
        "pr": pr,
        "seen_on": [pr],
        "weight": "риск",
        "kind": "код",
        "role": "механик",
        "title": "scripts/x.py:1 — что-то не так",
        "place": "scripts/x.py",
        "checked": "",
        "resolved_by": None,
        "twin_of": "",
        "род": None,
        "правило": None,
        **fields,
    }


def archive(repo: str = "o/r", **overrides: Any) -> dict[str, Any]:
    """Архив той формы, которую пишет сборщик архива сегодня."""
    return {
        "schema": archive_module.SCHEMA,
        "repo": repo,
        "generated_at": "2026-10-05T08:00:00+00:00",
        "counted": [10, 11],
        "gaps": [],
        "findings": {
            "aaaaaaa": finding(10, род="форма записи не разобрана", resolved_by=11),
            "bbbbbbb": finding(11, seen_on=[11, 12]),
        },
        "resolutions": {
            "aaaaaaa": {"by": 11, "twin_of": ""},
            "ccccccc": {"by": 12, "twin_of": "", "fix_check": True},
        },
        "kinds": {
            "форма записи не разобрана": {
                "встреч": 3,
                "каталогу": {
                    "вид": "есть",
                    "сказано": "206: форма, которую гейт не видит, — обход",
                },
                "породил": ["tests/test_x.py::test_a — гейт формы", "tests/test_y.py::test_b"],
            },
            "своё предложение": {
                "встреч": 1,
                "каталогу": {"вид": "предложено", "сказано": "a-slug-not-yet-numbered"},
                "породил": [],
            },
            "без ответа": {"встреч": 0, "каталогу": None, "породил": []},
        },
        "unconfirmed": [],
        **overrides,
    }


def written(tmp_path: Path, name: str, body: dict[str, Any]) -> Path:
    """Кладёт архив файлом и отдаёт путь."""
    path = tmp_path / name
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def rows(db: Path, query: str) -> list[tuple[Any, ...]]:
    """Строки ответа на запрос к собранной базе."""
    with sqlite3.connect(db) as connection:
        return list(connection.execute(query))


def test_an_archive_lands_in_every_table(tmp_path: Path) -> None:
    """Находки, их изменения, снятия и роды ложатся в свои таблицы с проектом."""
    out = tmp_path / "f.sqlite"
    counts = module.build([written(tmp_path, "a.json", archive())], out)
    assert counts == {
        "projects": 1,
        "findings": 2,
        "seen_on": 3,
        "resolutions": 2,
        "kinds": 3,
        "kind_spawned": 2,
    }
    assert rows(out, "SELECT mark, rod FROM findings ORDER BY mark") == [
        ("aaaaaaa", "форма записи не разобрана"),
        ("bbbbbbb", None),
    ]
    assert rows(out, "SELECT mark, fix_check FROM resolutions ORDER BY mark") == [
        ("aaaaaaa", 0),
        ("ccccccc", 1),
    ]
    assert rows(out, "SELECT DISTINCT repo FROM findings") == [("o/r",)]


def test_a_rebuild_replaces_the_base_instead_of_adding(tmp_path: Path) -> None:
    """Повторная сборка из того же входа даёт ту же базу, а не дубли."""
    out = tmp_path / "f.sqlite"
    source = written(tmp_path, "a.json", archive())
    first = module.build([source], out)
    assert module.build([source], out) == first
    assert rows(out, "SELECT count(*) FROM findings") == [(2,)]


def test_two_projects_lie_side_by_side(tmp_path: Path) -> None:
    """Архивы двух проектов — одна база; одинаковый отпечаток у разных проектов не спорит."""
    out = tmp_path / "f.sqlite"
    module.build(
        [written(tmp_path, "a.json", archive()), written(tmp_path, "b.json", archive("o/s"))],
        out,
    )
    assert rows(out, "SELECT repo, count(*) FROM findings GROUP BY repo ORDER BY repo") == [
        ("o/r", 2),
        ("o/s", 2),
    ]


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (archive(schema="99"), "форма архива '99' не знакома"),
        ({k: v for k, v in archive().items() if k != "kinds"}, "нет ключа 'kinds'"),
        (
            archive(findings={"aaaaaaa": {k: v for k, v in finding(1).items() if k != "role"}}),
            "`role` не str",
        ),
        (archive(findings=[]), "не словарь записей"),
        # Форма — целиком (взгляд на #1154): каждая часть, тип записи, тип поля.
        ({k: v for k, v in archive().items() if k != "findings"}, "нет ключа 'findings'"),
        (archive(findings=None), "`findings` не словарь записей"),
        (archive(resolutions=[]), "`resolutions` не словарь записей"),
        (archive(kinds=None), "`kinds` не словарь записей"),
        (archive(kinds={"род": "строка"}), "kinds род — запись не словарь"),
        (
            archive(kinds={"род": {"встреч": 1, "каталогу": None, "породил": "abc"}}),
            "`породил` не list",
        ),
        (archive(kinds={"род": {"встреч": 1, "породил": []}}), "нет поля `каталогу`"),
        (
            archive(kinds={"род": {"встреч": 1, "каталогу": "x", "породил": []}}),
            "`каталогу` не dict",
        ),
        (archive(resolutions={"aaaaaaa": {"by": True, "twin_of": ""}}), "`by` не int"),
        (archive(findings={"aaaaaaa": finding(1, resolved_by="11")}), "`resolved_by` не int"),
        (
            archive(findings={"aaaaaaa": {k: v for k, v in finding(1).items() if k != "род"}}),
            "нет поля `род`",
        ),
    ],
)
def test_a_foreign_form_is_the_third_outcome(
    run_script: RunScript, tmp_path: Path, body: dict[str, Any], said: str
) -> None:
    """Чужая форма архива — исход 2 с причиной, и прежняя база не тронута."""
    out = tmp_path / "f.sqlite"
    module.build([written(tmp_path, "good.json", archive())], out)
    result = run_script(
        "findings_db.py", "--out", str(out), str(written(tmp_path, "bad.json", body))
    )
    assert result.code == BROKEN and said in result.text, result.text
    assert rows(out, "SELECT count(*) FROM findings") == [(2,)]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["bad.json", "f.sqlite", "good.json"]


def test_one_project_twice_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Два архива одного проекта — отказ: какой верен, сборка не решает."""
    source = written(tmp_path, "a.json", archive())
    result = run_script(
        "findings_db.py", "--out", str(tmp_path / "f.sqlite"), str(source), str(source)
    )
    assert result.code == BROKEN and "передан дважды" in result.text, result.text
    assert not (tmp_path / "f.sqlite").exists()


def test_a_build_says_what_it_laid(run_script: RunScript, tmp_path: Path) -> None:
    """Вшивка: точка входа собирает базу и называет число строк по таблицам."""
    out = tmp_path / "f.sqlite"
    result = run_script(
        "findings_db.py", "--out", str(out), str(written(tmp_path, "a.json", archive()))
    )
    assert result.code == CLEAN, result.text
    assert "findings: 2" in result.text and out.is_file()


def test_the_supported_form_is_the_archive_builder_one() -> None:
    """Понимаемая форма берётся у сборщика архива, а не пишется вторым числом (022)."""
    assert archive_module.SCHEMA in module.SUPPORTED


def test_a_finding_reaches_its_rule_through_its_kind(tmp_path: Path) -> None:
    """Правило у находки — через род; номер только у «есть», у «предложено» его нет."""
    out = tmp_path / "f.sqlite"
    module.build([written(tmp_path, "a.json", archive())], out)
    assert rows(out, "SELECT mark, verdict, rule FROM finding_rules") == [
        ("aaaaaaa", "есть", "206")
    ]
    # Род, которого нет в разделе родов, не роняет находку из представления
    # (взгляд на #1154, `f86b56c`): она остаётся с пустым ответом.
    other = tmp_path / "g.sqlite"
    body = archive(findings={"ddddddd": finding(13, род="род без записи")})
    module.build([written(tmp_path, "b.json", body)], other)
    assert rows(other, "SELECT mark, rod, verdict, rule, kind_known FROM finding_rules") == [
        ("ddddddd", "род без записи", None, None, 0)
    ]
    # Род записан, но без ответа каталогу — тоже пустой `verdict`, а `kind_known` — 1.
    known = tmp_path / "h.sqlite"
    body = archive(findings={"eeeeeee": finding(14, род="без ответа")})
    module.build([written(tmp_path, "c.json", body)], known)
    assert rows(known, "SELECT mark, verdict, kind_known FROM finding_rules") == [
        ("eeeeeee", None, 1)
    ]
    assert rows(out, "SELECT name, verdict, rule FROM kinds ORDER BY name") == [
        ("без ответа", None, None),
        ("своё предложение", "предложено", None),
        ("форма записи не разобрана", "есть", "206"),
    ]
    assert rows(
        out, "SELECT count(*) FROM kind_spawned WHERE kind = 'форма записи не разобрана'"
    ) == [(2,)]


def test_the_pieces_are_held_directly(tmp_path: Path) -> None:
    """Сверка формы, разбор ответа рода и укладка архива названы прямо, а не только сборкой."""
    good = written(tmp_path, "a.json", archive())
    assert module.checked_archive(good)["repo"] == "o/r"
    with pytest.raises(module.NotRun):
        module.checked_archive(written(tmp_path, "b.json", archive(schema="99")))
    assert module.fate_row({"каталогу": {"вид": "есть", "сказано": "206: форма"}}) == (
        "есть",
        "206",
        "206: форма",
    )
    assert module.fate_row({"каталогу": {"вид": "предложено", "сказано": "a-slug"}}) == (
        "предложено",
        None,
        "a-slug",
    )
    assert module.fate_row({"каталогу": None}) == (None, None, None)
    assert module.misshapen_record({"a": 1, "b": None}, {"a": int}, {"b": str}) == ""
    assert module.misshapen_record({"a": 1}, {"a": int}, {"b": str}) == "нет поля `b`"
    assert (
        module.misshapen_record({"a": 1, "b": 2}, {"a": int}, {"b": str}) == "`b` не str и не null"
    )
    with sqlite3.connect(":memory:") as db:
        db.executescript(module.TABLES)
        module.fill(db, archive())
        with pytest.raises(module.NotRun, match="передан дважды"):
            module.fill(db, archive())
