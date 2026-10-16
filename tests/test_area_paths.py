"""Роль взгляда «правила каталога»: правила отбираются по тронутым путям (#1277).

Таблица `.rules/area-paths.json` сопоставляет области каталога путям дерева.
Проверяется: форма таблицы и живость её образцов, отбор правил с тремя
исходами и незнанием, которое не отсеивает, и чтение таблицы с общей ветки.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script, walk

module = load_script("review_map.py")
TABLE: dict[str, Any] = json.loads((ROOT / ".rules" / "area-paths.json").read_text("utf-8"))


def tracked() -> list[str]:
    """Пути дерева под git — то, с чем сверяются образцы таблицы."""
    # `-z`: имя с кириллицей или пробелом без него приходит экранированным (165).
    said = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return [one for one in said.stdout.split("\0") if one]


def test_every_area_has_paths_or_a_reason() -> None:
    """Пустой список путей — только с причиной: молчаливая область неотличима от забытой."""
    areas = TABLE["areas"]
    assert areas, "таблица областей пуста"
    silent = [
        name for name, one in areas.items() if not one["paths"] and not one.get("why", "").strip()
    ]
    assert not silent, f"область без путей и без причины: {silent}"


def test_every_pattern_finds_a_path_in_the_tree() -> None:
    """Образец, не находящий ни одного пути, — мёртвая строка: область по нему не задеть."""
    files = tracked()
    dead = [
        f"{name}: {mask}"
        for name, one in TABLE["areas"].items()
        for mask in one["paths"]
        if not any(module.matches(path, mask) for path in files)
    ]
    assert not dead, f"образцы без единого пути: {dead}"


#: Вызов общего шага из прогона: `uses: ./.github/workflows/step-….yml`.
CALLED_STEP = re.compile(r"uses:\s*\./(\.github/workflows/step-[\w-]+\.yml)")


def test_an_area_of_a_caller_names_its_called_step() -> None:
    """Область, назвавшая тонкий вызывающий прогон, называет и шаг, куда ушло тело.

    Тело прогона переезжает в `step-*.yml` (#1385), а вызывающий остаётся
    одной строкой `uses:`. Область, знающая только вызывающего, правку тела не
    видит, и отбор правил её пропускает (находка `463c623` на #1413). Замер
    16.10.2026: так отстали шесть мест — шаги claude, main-red, release,
    schedules-seen, stuck и step-facts у области metrics.

    ГРАНИЦА НАЗВАНА (195): сверяется вызов по относительному адресу в этом
    дереве. Вызов адресом с тегом — у потребителя, его области здесь не судятся.
    """
    pairs = [
        (name, caller.name, step, any(module.matches(step, mask) for mask in one["paths"]))
        for name, one in TABLE["areas"].items()
        for caller in walk(ROOT / ".github" / "workflows", "*.yml")
        if any(module.matches(f".github/workflows/{caller.name}", mask) for mask in one["paths"])
        for step in CALLED_STEP.findall(caller.read_text(encoding="utf-8"))
    ]
    assert pairs, "ни одна область не называет вызывающего — предмета нет (075)"
    behind = [f"{name}: {caller} → {step}" for name, caller, step, named in pairs if not named]
    assert not behind, f"область знает вызывающего, но не его шаг: {behind}"


def test_the_live_table_reads_in_the_mechanism_shape() -> None:
    """Таблица дерева проходит тот же разбор, что механизм делает на общей ветке."""
    table = module.area_table("HEAD")
    assert set(table) == set(TABLE["areas"])


TABLE_OF = {"gates": ["scripts/check_*.py"], "docs": ["docs/*"], "pace": []}


def test_narrowing_keeps_only_rules_whose_areas_were_touched() -> None:
    """Задета область — правило роли отдано; не задета — отсеяно; не видна — названа."""
    areas_of = {"001": ["gates"], "002": ["docs"], "003": ["pace"], "004": ["docs", "gates"]}
    said = module.narrow(["001", "002", "003"], ["004"], areas_of, TABLE_OF, ["scripts/check_x.py"])
    assert said.eyes == ["001"]
    assert said.inapplicable == ["004"]
    assert said.untouched == ["002"]
    assert said.blind == ["003"]
    assert said.unknown == []


def test_an_inapplicable_rule_is_never_narrowed_away() -> None:
    """Неприменимое роль спрашивает всегда, задета его область или нет (решение 042).

    Таблица говорит, где предмет живёт сейчас, а у неприменимого его нет: и
    слепая область, и обычная незадетая, и неизвестная таблице — правило у роли.
    """
    areas_of = {"003": ["pace"], "065": ["pace"], "077": ["pace", "docs"], "009": ["docs"]}
    said = module.narrow(["003"], ["065", "077", "009", "120"], areas_of, TABLE_OF, ["README.md"])
    assert said.inapplicable == ["065", "077", "009", "120"]
    assert said.blind == ["003"]
    assert said.untouched == []


def test_the_untouched_line_speaks_of_eye_rules_only() -> None:
    """Строка «не задеты» — только о правилах глаз; неприменимые отданы все (#1369)."""
    areas_of = {"001": ["gates"], "002": ["docs"], "009": ["docs"]}
    said = module.narrow(["001", "002"], ["009"], areas_of, TABLE_OF, ["scripts/check_x.py"])
    assert said.untouched == ["002"] and said.inapplicable == ["009"]
    note = "\n".join(module.narrowed_said(said))
    assert "не задеты этим изменением — 1 (002). Неприменимые отданы роли все." in note


def test_the_map_names_untouched_rules_by_number() -> None:
    """Отсеянные как «не задетые» правила карта называет номерами (взгляд на #1357)."""
    areas_of = {"001": ["gates"], "002": ["docs"]}
    said = module.narrow(["001", "002"], [], areas_of, TABLE_OF, ["scripts/check_x.py"])
    note = "\n".join(module.narrowed_said(said))
    assert "не задеты этим изменением — 1 (002)" in note
    empty = module.narrow(["001"], [], {"001": ["gates"]}, TABLE_OF, ["scripts/check_x.py"])
    assert "не задеты этим изменением — 0 (ни одного)" in "\n".join(module.narrowed_said(empty))


def test_unknown_areas_do_not_drop_a_rule() -> None:
    """Области нет в таблице — правило остаётся, а отставание таблицы названо (045)."""
    said = module.narrow(["001", "002"], [], {"001": ["новая"]}, TABLE_OF, ["README.md"])
    assert said.eyes == ["001", "002"]
    assert said.unknown == ["новая"]
    note = "\n".join(module.narrowed_said(said))
    assert "Областей каталога нет в таблице: новая" in note


def test_an_unnarrowed_map_says_why() -> None:
    """Отбора не было — карта называет причину и отдаёт списки целиком, а не молчит."""
    note = "\n".join(module.narrowed_said(None, "токен не передан"))
    assert "НЕ отобраны: токен не передан" in note
    assert module.CATALOGUE_ROLE in note


def test_the_table_comes_from_the_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Таблица — с общей ветки: сузившее её изменение не прячет правил от взгляда (085)."""
    asked: list[tuple[str, Path]] = []

    def shown(base: str, path: Path) -> str:
        asked.append((base, path))
        return json.dumps({"areas": {"gates": {"paths": ["tests/*"]}}})

    monkeypatch.setattr(module, "shown_from_base", shown)
    assert module.area_table("origin/main") == {"gates": ["tests/*"]}
    assert asked == [("origin/main", module.paths.AREA_PATHS)]


@pytest.mark.parametrize(
    "said",
    [
        "не json",
        json.dumps({"areas": {}}),
        json.dumps({"areas": {"gates": {"paths": "tests/*"}}}),
        json.dumps({"areas": {"pace": {"paths": []}}}),
    ],
    ids=["не-разбирается", "пусто", "пути-строкой", "пусто-без-причины"],
)
def test_a_broken_table_is_a_refusal(monkeypatch: pytest.MonkeyPatch, said: str) -> None:
    """Таблица не той формы — отказ отбора, а не пустой отбор (075)."""
    monkeypatch.setattr(module, "shown_from_base", lambda base, path: said)
    with pytest.raises(module.NotRun):
        module.area_table("B")


def test_the_map_hands_the_role_only_touched_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Заход карты целиком: тронутые пути сужают правила глаз, неприменимое отдано (042)."""
    where = tmp_path / "карта.md"
    monkeypatch.setattr(
        module, "split", lambda said: (["010"], ["001", "002"], {"not-applicable": ["003"]})
    )
    monkeypatch.setattr(module, "from_base", lambda base: {})
    monkeypatch.setattr(
        module, "export_meta", lambda: ({}, {"001": ["gates"], "002": ["docs"], "003": ["docs"]})
    )
    monkeypatch.setattr(module, "touched_files", lambda repo, pr: (["scripts/check_a.py"], ""))
    monkeypatch.setattr(module, "area_table", lambda base: TABLE_OF)
    monkeypatch.setattr(module, "touches_the_answer", lambda base, head="HEAD": False)
    monkeypatch.setattr(module, "roles_section", lambda *a, **k: "")
    monkeypatch.setattr(module, "role_declared", lambda base: True)
    assert module.main(["--out", str(where)]) == module.EXIT_OK
    text = where.read_text("utf-8")
    assert "**001**" in text and "**002**" not in text
    assert "- 003" in text, "неприменимое отсеяно таблицей областей"
    assert "не задеты этим изменением — 1 (002)" in text


def test_the_export_gives_titles_and_english_areas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одно чтение выгрузки даёт и заголовки, и области — английскими именами таблицы."""

    def export(_: str) -> dict[str, Any]:
        rule = {"id": "003", "title": {"ru": "Т"}, "areas": {"ru": ["врата"], "en": ["gates"]}}
        return {"rules": [rule, {"id": "004", "areas": "не словарь"}]}

    monkeypatch.setattr(module.ghrest, "raw_json", export)
    named, areas = module.export_meta()
    assert named == {"003": "Т"}
    assert areas == {"003": ["gates"]}


def test_touched_files_say_why_they_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без номера или токена путей нет — и это причина словами, а не пустой список молча."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.touched_files("o/r", 7) == (
        [],
        "номер изменения, репозиторий или токен не переданы",
    )
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module, "changed_files", lambda repo, number, token: ["a.py"])
    assert module.touched_files("o/r", 7) == (["a.py"], "")


def test_narrowing_answers_in_its_named_shape() -> None:
    """Отбор отвечает записью `Narrowed`: каждая группа названа полем, а не местом в кортеже."""
    said = module.narrow([], [], {}, TABLE_OF, [])
    assert isinstance(said, module.Narrowed)
    assert said._fields == ("eyes", "inapplicable", "untouched", "blind", "unknown")


def test_a_project_without_the_role_gets_no_word_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Роль не объявлена в таблице ролей — карта о ней молчит и списков не сужает (взгляд на #1357).

    Карту собирает код механизмов у всей семьи; у соседа без роли строки о ней
    были бы указанием роли, которой у него нет.
    """
    where = tmp_path / "карта.md"
    monkeypatch.setattr(module, "split", lambda said: ([], ["001", "002"], {}))
    monkeypatch.setattr(module, "from_base", lambda base: {})
    monkeypatch.setattr(module, "export_meta", lambda: ({}, {"001": ["gates"], "002": ["docs"]}))
    monkeypatch.setattr(module, "touched_files", lambda repo, pr: (["scripts/check_a.py"], ""))
    monkeypatch.setattr(module, "touches_the_answer", lambda base, head="HEAD": False)
    monkeypatch.setattr(module, "roles_section", lambda *a, **k: "")
    monkeypatch.setattr(module, "role_declared", lambda base: False)
    assert module.main(["--out", str(where)]) == module.EXIT_OK
    text = where.read_text("utf-8")
    assert module.CATALOGUE_ROLE not in text
    assert "**001**" in text and "**002**" in text


def test_the_role_is_declared_by_the_base_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """Объявлена ли роль — по таблице ролей с общей ветки; таблицы нет — не объявлена."""
    table = {
        "required": ["тестировщик"],
        "by_path": [{"paths": ["x"], "roles": ["правила каталога"]}],
    }
    monkeypatch.setattr(module, "shown_from_base", lambda base, path: json.dumps(table))
    assert module.role_declared("B") is True
    monkeypatch.setattr(module, "shown_from_base", lambda base, path: json.dumps({"required": []}))
    assert module.role_declared("B") is False

    def refuse(base: str, path: Path) -> str:
        raise module.NotRun("нет файла")

    monkeypatch.setattr(module, "shown_from_base", refuse)
    assert module.role_declared("B") is False


def test_our_table_names_the_role() -> None:
    """У механизмов роль объявлена: живое дерево, а не подделка (146)."""
    assert module.role_declared("HEAD") is True


def test_a_changelog_fragment_touches_no_area() -> None:
    """Фрагмент журнала области не задевает: он есть почти в каждом изменении (взгляд на #1357).

    Иначе его область не отсеивалась бы никогда — по той же причине он в
    `ignored` таблицы ролей (#785). Фрагмент рода `contract` — исключение.
    """
    hit = [
        name
        for name, one in TABLE["areas"].items()
        if any(module.matches("changelog.d/x.fixed.md", mask) for mask in one["paths"])
    ]
    assert not hit, f"фрагмент журнала задевает области: {hit}"
