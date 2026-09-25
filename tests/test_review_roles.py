"""Кем смотреть на изменение: обязательные роли и роли по тронутым путям (#776).

Решение владельца 24.09.2026: обязательные роли — проверяющего рода, остальные
зависят от контекста изменения. Выбор — сверка путей с таблицей
`.rules/review-roles.json`, а не суждение модели, и таблица с процедурой
`docs/review.md` читаются с ОБЩЕЙ ветки (085).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

review_map = load_script("review_map.py")
findings = load_script("findings.py")
paths = load_script("paths.py")
release = load_script("release.py")

TABLE: Final = json.loads((ROOT / paths.REVIEW_ROLES).read_text(encoding="utf-8"))


def test_every_role_of_the_table_is_a_profile() -> None:
    """Роль таблицы — заголовок профиля `docs/roles.md`, а не выдуманное имя (022)."""
    known = findings.roles(ROOT / paths.ROLES)
    assert known, "профили не прочитаны — сверять не с чем (075)"
    named = set(TABLE["required"]) | {role for rule in TABLE["by_path"] for role in rule["roles"]}
    assert named, "ролей в таблице нет"
    assert not named - known, f"ролей нет в карте ролей: {sorted(named - known)}"


def test_required_roles_are_the_checking_kind() -> None:
    """Обязательные — проверяющего рода, и они есть: без них взгляд шёл бы «общим чтением»."""
    assert set(TABLE["required"]) >= {"тестировщик", "аудитор", "ревизор"}


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["docs/pipeline.md"], {"техписатель", "редактор", "архитектор"}),
        ([".github/workflows/ci.yml"], {"инженер площадки", "безопасность", "эконом прогонов"}),
        (["scripts/automerge.py"], {"механик", "диспетчер"}),
        (["changelog.d/x.fixed.md"], set()),
        (["scripts/x.py", "changelog.d/x.fixed.md"], {"механик"}),
        (["scripts/release.py"], {"механик", "релиз-инженер"}),
        (["changelog.d/x.contract.md"], {"релиз-инженер"}),
        # Правила записи фрагментов — документ о выпуске: зовёт и тех, кто
        # смотрит документы, и релиз-инженера (взгляд на #801).
        (["changelog.d/README.md"], {"релиз-инженер", "техписатель", "редактор"}),
        (["tests/fixtures/x.md"], {"механик"}),
        (["docs/decisions/001-x.md"], {"техписатель", "редактор", "архитектор"}),
        (["README.md"], {"техписатель", "редактор"}),
        (["никуда/не/ведёт.txt"], set()),
    ],
    ids=[
        "договор",
        "прогон",
        "очередь",
        "журнал",
        "обычное изменение",
        "выпуск",
        "контракт",
        "правила фрагментов",
        "образец теста",
        "вложенный документ",
        "корневой документ",
        "чужой путь",
    ],
)
def test_context_roles_follow_the_touched_paths(files: list[str], expected: set[str]) -> None:
    """Одно изменение — одни и те же роли: выбор по путям, а не на глаз."""
    required, context = review_map.roles_for(files, TABLE)
    assert set(context) == expected
    assert not set(context) & set(required), "обязательная роль повторена в контекстных"
    for hit in context.values():
        assert set(hit) <= set(files)


def test_the_section_names_roles_and_what_called_them() -> None:
    """Раздел карты называет обязательные роли, контекстные и пути, что их позвали."""
    said = review_map.render_roles("ПРОЦЕДУРА", ["ревизор"], {"механик": ["scripts/a.py"]})
    assert "**Обязательные роли:** ревизор." in said
    assert "- **механик** — `scripts/a.py`" in said
    assert "ПРОЦЕДУРА" in said
    unread = review_map.render_roles("П", ["ревизор"], {}, unread="токена нет")
    assert "не выбраны: токена нет" in unread, "неизвестный контекст выдан за «ролей нет»"


def test_the_procedure_and_table_come_from_the_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Процедура и таблица — с общей ветки: читаются `git show <база>:<путь>` (085)."""
    asked: list[str] = []

    def shown(base: str, path: Path) -> str:
        asked.append(f"{base}:{path}")
        return json.dumps(TABLE) if path == paths.REVIEW_ROLES else "ПРОЦЕДУРА С БАЗЫ"

    monkeypatch.setattr(review_map, "shown_from_base", shown)
    monkeypatch.setattr(review_map.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(review_map, "changed_files", lambda repo, n, tok: ["scripts/x.py"])
    said = review_map.roles_section("FETCH_HEAD", "o/r", 7)
    assert asked == [f"FETCH_HEAD:{paths.REVIEW_PROCEDURE}", f"FETCH_HEAD:{paths.REVIEW_ROLES}"]
    assert "ПРОЦЕДУРА С БАЗЫ" in said and "**механик**" in said


def test_an_unread_base_is_named_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Процедура не прочиталась — раздел это говорит, а карта не падает (084)."""

    def refuse(base: str, path: Path) -> str:
        raise review_map.NotRun("нет на базе")

    monkeypatch.setattr(review_map, "shown_from_base", refuse)
    assert "не прочитана с общей ветки" in review_map.roles_section("B", "o/r", 7)


def test_changed_files_are_asked_of_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пути берутся у площадки: у позднего взгляда голова — уже общая ветка."""

    def paginate(path: str, token: str, **_: Any) -> Any:
        assert path == "repos/o/r/pulls/7/files"
        return iter([{"filename": "a.py"}, {"filename": ""}, {"filename": "b.md"}])

    monkeypatch.setattr(review_map.ghrest, "paginate", paginate)
    assert review_map.changed_files("o/r", 7, "t") == ["a.py", "b.md"]


def test_both_prompts_point_to_the_procedure_instead_of_retelling_it() -> None:
    """Обе подсказки отсылают к процедуре и не пересказывают её (#776, 022)."""
    text = (ROOT / ".github/workflows/review.yml").read_text(encoding="utf-8")
    assert text.count("Процедура взгляда и роли этого изменения") == 2
    assert "`РОЛЬ <имя>: нечего`" not in text, "процедура пересказана в подсказке"
    assert len(re.findall(r"review_map\.py[^\n]*\n\s*--pr ", text)) == 2, "шаг карты без номера"


def test_a_required_role_is_not_repeated_as_context() -> None:
    """Обязательная роль, названная и правилом путей, в контекстных не повторяется."""
    table = {
        "required": ["ревизор"],
        "by_path": [{"paths": ["*.py"], "roles": ["ревизор", "механик"]}],
    }
    required, context = review_map.roles_for(["a.py"], table)
    assert required == ["ревизор"] and list(context) == ["механик"]


def test_shown_from_base_reads_git_and_refuses_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """`shown_from_base` зовёт `git show <база>:<путь>`; отказ git — отказ, а не пустой текст."""
    import subprocess

    calls: list[list[str]] = []

    def run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        ok = args[-1].startswith("B:")
        return subprocess.CompletedProcess(args, 0 if ok else 128, "текст" if ok else "", "нет")

    monkeypatch.setattr(review_map.subprocess, "run", run)
    assert review_map.shown_from_base("B", Path("docs/review.md")) == "текст"
    assert calls[-1] == ["git", "show", "B:docs/review.md"]
    with pytest.raises(review_map.NotRun):
        review_map.shown_from_base("X", Path("docs/review.md"))


@pytest.mark.parametrize(
    "table",
    [
        [],
        {"required": "ревизор"},
        {"by_path": {"paths": ["*"]}},
        {"by_path": [{"paths": ["*"], "roles": "механик"}]},
        {"ignored": {"paths": "changelog.d/*"}},
        {"ignored": ["changelog.d/*"]},
    ],
    ids=[
        "не словарь",
        "required строкой",
        "by_path словарём",
        "roles строкой",
        "ignored строкой",
        "ignored списком",
    ],
)
def test_a_table_of_another_shape_is_named_not_fatal(
    monkeypatch: pytest.MonkeyPatch, table: Any
) -> None:
    """Таблица иной формы — раздел это называет, а карта не падает (взгляд на #785, 084)."""
    monkeypatch.setattr(review_map, "shown_from_base", lambda base, path: json.dumps(table))
    assert "не прочитана с общей ветки" in review_map.roles_section("B", "o/r", 7)


def test_the_live_table_has_its_shape() -> None:
    """Живая таблица проходит ту же сверку формы, что и прочитанная с базы."""
    assert review_map.table_shape(TABLE) is TABLE


def test_only_a_list_of_strings_is_a_list_of_the_table() -> None:
    """Список таблицы — список строк: строка, словарь и список с числом — нет."""
    assert review_map.strings([]) and review_map.strings(["a", "b"])
    assert not review_map.strings("a")
    assert not review_map.strings({"a": 1})
    assert not review_map.strings(["a", 1])


def test_the_contract_fragment_mask_follows_the_release_kind() -> None:
    """Исключение из `ignored` и строка релиз-инженера называют род контракта выпуска.

    Род фрагмента, двигающего контракт, объявлен у выпуска (`CONTRACT_KIND`);
    переименуй его там — и таблица молча перестала бы звать релиз-инженера.
    """
    mask = f"changelog.d/*{release.CONTRACT_KIND}"
    assert mask in TABLE["ignored"]["except"]
    release_rows = [rule for rule in TABLE["by_path"] if "релиз-инженер" in rule["roles"]]
    assert any(mask in rule["paths"] for rule in release_rows)


def test_a_mask_without_a_slash_matches_only_the_root() -> None:
    """Образец без `/` — только корень; с `/` — и вложенные пути, как у `fnmatch`."""
    assert review_map.matches("README.md", "*.md")
    assert not review_map.matches("tests/fixtures/x.md", "*.md")
    assert review_map.matches("docs/decisions/001-x.md", "docs/*")
