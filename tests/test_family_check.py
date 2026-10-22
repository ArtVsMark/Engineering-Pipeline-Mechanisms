"""Семейный значок: сверка проекта со сводкой семьи по сегментам.

Переехало из каталога вместе со сверкой (#1563): случаи и ожидания — набора
каталога на `353bf10`. Отличие одно и названо: диапазон `contract:` судит наш
`pipeline_checks.span_bounds`, и `==0.6` здесь не «отстаёт», а «не той формы».

Источник подделки (правило 170): сводка — форма `export/family.json`, которую
собирает каталог (`family.сводка` у него), проект — строка `family.запись`;
дерево проекта — своё, во временном каталоге.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

fc = load_script("family_check.py")
contract = load_script("family_contract.py")

CATALOGUE = fc.catalogue.REPO
MECH = "ArtVsMark/Engineering-Pipeline-Mechanisms"
SHA = "a" * 40


def summary(*projects: dict[str, Any]) -> dict[str, Any]:
    """Сводка семьи с данными проектами."""
    return {"schema": contract.FAMILY_SCHEMA, "projects": list(projects)}


def publisher(repo: str, tag: str | None = "v1.5.0", **gives: str) -> dict[str, Any]:
    """Опубликованный манифест проекта в сводке."""
    return {
        "repo": repo,
        "state": "published",
        "schema": "1.0",
        "takes": [],
        "release": {"tag": tag, "sha": SHA} if tag else None,
        "gives": gives,
    }


def tree(tmp_path: Path, uses: str = "", answer: dict[str, Any] | None = None) -> Path:
    """Дерево проекта с одним прогоном и, если дан, ответом каталогу."""
    flows = tmp_path / ".github" / "workflows"
    flows.mkdir(parents=True)
    text = f"on: push\njobs:\n  x:\n    uses: {uses}\n" if uses else "on: push\n"
    (flows / "a.yml").write_text(text, encoding="utf-8")
    if answer is not None:
        (tmp_path / ".rules").mkdir()
        (tmp_path / ".rules" / "bindings.json").write_text(json.dumps(answer), encoding="utf-8")
    return tmp_path


def manifest_file(root: Path, tag: str | None, **over: Any) -> None:
    """Свой манифест проекта `o/p` в дереве."""
    (root / contract.MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "1.0",
        "project": "o/p",
        "takes": [],
        "gives": {"x": "1.0"},
        "release": {"tag": tag, "sha": SHA} if tag else None,
        **over,
    }
    (root / contract.MANIFEST).write_text(json.dumps(doc), encoding="utf-8")


def facts_file(root: Path, doc: object) -> None:
    """Свои факты проекта в дереве."""
    (root / ".github" / "badges").mkdir(parents=True, exist_ok=True)
    (root / fc.FACTS).write_text(json.dumps(doc), encoding="utf-8")


def pipeline_file(root: Path, text: str | None) -> None:
    """Ответ конвейеру `.pipeline.yml`, если дан."""
    if text is not None:
        (root / ".pipeline.yml").write_text(text, encoding="utf-8")


def states(
    root: Path, said: dict[str, Any], own: str = "o/p", manifest: dict[str, Any] | None = None
) -> dict[str, str]:
    """Код издателя → состояние связи с ним."""
    if manifest is not None:
        manifest_file(root, None, **manifest)
    return {one["code"]: one["state"] for one in fc.analyse(root, said, own)["publishers"]}


@pytest.mark.parametrize(
    ("ref", "state"),
    [
        ("v1.5.0", "ok"),
        ("v1.4.0", "behind"),  # минор — красный, а не жёлтый
        (SHA, "ok"),  # SHA последнего выпуска
        ("b" * 40, "behind"),  # SHA не последнего выпуска
    ],
)
def test_a_family_pin_is_compared_with_the_release(tmp_path: Path, ref: str, state: str) -> None:
    """Пин на издателя семьи сверяется с его последним выпуском — тегом или коммитом."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@{ref}")
    links = fc.family_links(root, summary(publisher(MECH)), CATALOGUE)
    assert [one.state for one in links] == [state]


def test_a_publisher_without_manifest_is_unknown(tmp_path: Path) -> None:
    """Издатель без манифеста в сводке — неизвестно, а не «сходится»."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@v1.5.0")
    links = fc.family_links(
        root, summary({"repo": MECH, "state": "absent", "why": "404"}), CATALOGUE
    )
    assert [one.state for one in links] == ["unknown"]
    assert fc.verdict(links) == "unknown"


def test_outside_the_family_is_not_compared(tmp_path: Path) -> None:
    """Чужое вне семьи не сверяется."""
    root = tree(tmp_path, "actions/checkout@v5")
    assert fc.family_links(root, summary(publisher(MECH)), CATALOGUE) == []


def test_the_answer_is_compared_with_the_catalogue_numbers(tmp_path: Path) -> None:
    """Номера ответа каталогу — с тем, что каталог отдаёт."""
    root = tree(tmp_path, answer={"schema": "1.8", "answers_to": "1.7"})
    said = summary(publisher(CATALOGUE, bindings="1.9", export="1.7"))
    links = fc.family_links(root, said, "o/p")
    assert {one.what: one.state for one in links} == {"bindings": "behind", "export": "ok"}


def test_a_pair_reads_the_number_from_the_named_file(tmp_path: Path) -> None:
    """Парная связь читает номер из названного файла по названному ключу."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "source.json").write_text('{"form": "6.0"}', encoding="utf-8")
    manifest = {
        "takes": [
            {"from": "o/glossary", "contract": "form", "where": "src/source.json", "field": "form"}
        ]
    }
    links = fc.pair_links(tmp_path, summary(publisher("o/glossary", form="6.1")), manifest)
    assert [(one.mine, one.latest, one.state) for one in links] == [("6.0", "6.1", "behind")]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ([], "unknown"),
        (["ok", "ok"], "ok"),
        (["ok", "unknown"], "unknown"),
        (["unknown", "behind"], "behind"),
    ],
)
def test_the_segment_color(given: list[str], expected: str) -> None:
    """Красное сильнее серого, серое сильнее зелёного; пусто — серый."""
    links = [fc.Link("family", "p", "w", "1", "1", "x", one) for one in given]
    assert fc.verdict(links) == expected


def test_the_badge_is_drawn_by_the_shared_picture(tmp_path: Path) -> None:
    """Значок рисует общая функция и называет число отстающих связей."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@v1.4.0")
    analysis = fc.analyse(root, summary(publisher(MECH)), CATALOGUE)
    svg = fc.badge(analysis)
    assert "family ✗1" in svg
    assert fc.COLOR["behind"] in svg
    assert analysis["segments"]["external"]["state"] == "unknown"
    assert analysis["segments"]["gives"]["why"]  # не издатель — названо


def test_main_without_summary_is_the_third_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Сводка не прочитана — исход 2 с адресом, а не пустой значок."""
    missing = tmp_path / "нет.json"
    assert fc.main(["--root", str(tmp_path), "--family", str(missing)]) == fc.EXIT_BROKEN
    assert str(missing) in capsys.readouterr().err


def test_being_ahead_is_not_lagging() -> None:
    """Моё новее опубликованного — серый с причиной, а не красный (каталог, обзор #807)."""
    link = fc.compare("family", "p", "bindings", "1.10", "1.9", "x")
    assert link.state == "unknown"
    assert "опережает" in link.why
    assert fc.compare("family", "p", "release", "v1.9.0", "v1.10.0", "x").state == "behind"


def test_an_incomplete_takes_entry_is_data(tmp_path: Path) -> None:
    """Неполная запись `takes` — серая связь, а не падение."""
    links = fc.pair_links(tmp_path, summary(), {"takes": [{"from": "o/g", "contract": "form"}]})
    assert [(one.state, "неполна" in one.why) for one in links] == [("unknown", True)]


@pytest.mark.parametrize(
    ("tag", "in_summary", "expected"),
    [
        ("v2.0.0", True, "ok"),
        ("v1.9.0", True, "behind"),  # манифест называет не последний выпуск дерева
        ("v2.0.0", False, "unknown"),  # до сводки не дошёл
    ],
)
def test_the_gives_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str, in_summary: bool, expected: str
) -> None:
    """Отдача: выпуск, форма и дошёл ли манифест до сводки."""
    monkeypatch.setattr(fc.version, "release_tag", lambda root: "v2.0.0")
    manifest_file(tmp_path, tag)
    said = summary(publisher("o/p", tag=tag, x="1.0")) if in_summary else summary()
    manifest = json.loads((tmp_path / contract.MANIFEST).read_text(encoding="utf-8"))
    assert fc.verdict(fc.gives_links(tmp_path, said, "o/p", manifest)) == expected


def test_a_foreign_form_of_gives_is_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Манифест чужого мажора формы — красный."""
    monkeypatch.setattr(fc.version, "release_tag", lambda root: "v2.0.0")
    manifest = {
        "schema": "2.0",
        "project": "o/p",
        "takes": [],
        "gives": {},
        "release": {"tag": "v2.0.0", "sha": SHA},
    }
    links = fc.gives_links(tmp_path, summary(publisher("o/p", tag="v2.0.0")), "o/p", manifest)
    assert [one.state for one in links if one.what == "form"] == ["behind"]


def test_main_writes_the_badge_and_the_analysis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Значок и разбор ложатся в папку значков проекта."""
    root = tree(tmp_path / "p", f"{MECH}/.github/workflows/step-x.yml@v1.4.0")
    source = tmp_path / "family.json"
    source.write_text(json.dumps(summary(publisher(MECH))), encoding="utf-8")
    (root / ".github" / "badges").mkdir(parents=True)
    assert fc.main(["--root", str(root), "--family", str(source), "--repo", "o/p"]) == fc.EXIT_OK
    analysis = json.loads((root / fc.VERDICT).read_text(encoding="utf-8"))
    assert analysis["segments"]["family"]["state"] == "behind"
    assert "family ✗1" in (root / fc.SVG).read_text(encoding="utf-8")
    assert "v1.4.0" in capsys.readouterr().out


def test_main_puts_the_badge_where_out_says(tmp_path: Path) -> None:
    """Действие у соседа: путь — его вход `out`, разбор — рядом с картинкой."""
    root = tree(tmp_path / "p", f"{MECH}/.github/workflows/step-x.yml@v1.5.0")
    source = tmp_path / "family.json"
    source.write_text(json.dumps(summary(publisher(MECH))), encoding="utf-8")
    out = root / "img" / "семья.svg"
    argv = ["--root", str(root), "--family", str(source), "--repo", "o/p", "--out", str(out)]
    assert fc.main(argv) == fc.EXIT_OK
    analysis = json.loads((root / "img" / fc.VERDICT.name).read_text(encoding="utf-8"))
    assert analysis["project"] == "o/p"
    assert analysis["segments"]["family"]["state"] == "ok"
    assert "family ✓" in out.read_text(encoding="utf-8")
    assert not (root / fc.SVG).exists()


def test_a_number_apart_from_the_summary_is_grey(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сводка ещё не перечитала манифест — видно, но это не отставание (каталог, обзор #808)."""
    monkeypatch.setattr(fc.version, "release_tag", lambda root: "v2.0.0")
    manifest = {
        "schema": "1.1",
        "project": "o/p",
        "takes": [],
        "gives": {"x": "1.1"},
        "release": {"tag": "v2.0.0", "sha": SHA},
    }
    said = summary(publisher("o/p", tag="v2.0.0", x="1.0"))
    links = fc.gives_links(tmp_path, said, "o/p", manifest)
    assert [(one.state, one.why) for one in links if one.what == "x"] == [
        ("unknown", "сводка ещё не перечитала манифест")
    ]


def test_the_publishers_block(tmp_path: Path) -> None:
    """Свежий шаг механизмов без `.pipeline.yml` — частичная связь, каталог — связи нет."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@v1.5.0")
    assert states(root, summary(publisher(MECH))) == {"EIP": "none", "EPM": "partial"}


def test_a_lagging_pin_without_pipeline_stays_red(tmp_path: Path) -> None:
    """◐ решает, когда ставить ✓, а не прячет ✗ (каталог, обзор #839)."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@v1.4.0")
    assert states(root, summary(publisher(MECH)))["EPM"] == "behind"


@pytest.mark.parametrize(
    ("pin", "steps", "expected"),
    [
        ("v1.5.0", "0.7", "ok"),  # конвейер подключён, всё свежее
        ("v1.4.0", "0.7", "behind"),  # конвейер подключён, пин отстал
        ("v1.5.0", "0.9", "behind"),  # конвейер подключён, диапазон отстал
    ],
)
def test_mechanisms_with_pipeline_are_judged_by_freshness(
    tmp_path: Path, pin: str, steps: str, expected: str
) -> None:
    """С конвейером связь с механизмами судится свежестью пина и диапазона."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@{pin}")
    pipeline_file(root, 'contract: ">=0.5,<0.9"\n')
    assert states(root, summary(publisher(MECH, steps=steps)))["EPM"] == expected


def test_a_partial_link_names_the_count(tmp_path: Path) -> None:
    """Частичная связь называет число связей с механизмами."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@v1.5.0")
    analysis = fc.analyse(root, summary(publisher(MECH)), "o/p")
    block = {one["code"]: one for one in analysis["publishers"]}
    assert block["EPM"]["state"] == "partial"
    assert "связей с механизмами 1" in block["EPM"]["why"]
    assert "EPM ◐" in fc.badge(analysis)


def test_a_skip_with_reason_is_grey(tmp_path: Path) -> None:
    """Отказ с причиной — серый, а не красный."""
    root = tree(tmp_path)
    said = states(root, summary(), manifest={"skips": {"EPM": "шаги не нужны: нет PR"}})
    assert said["EPM"] == "skipped"
    assert "AVM" not in said


def test_the_own_publisher_shows_its_gives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Свой издатель показывает состояние отдачи, а не «связи нет»."""
    monkeypatch.setattr(fc.version, "release_tag", lambda root: None)
    root = tree(tmp_path)
    assert states(root, summary(), own=MECH, manifest={"project": MECH})["EPM"] != "none"


def test_a_skip_to_an_unknown_publisher_and_with_a_live_link(tmp_path: Path) -> None:
    """Опечатка в skips и отказ при живой связи не работают молча (каталог, обзор #809)."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@v1.5.0")
    manifest_file(root, None, skips={"EMP": "опечатка", "EPM": "не нужны"})
    analysis = fc.analyse(root, summary(publisher(MECH)), "o/p")
    why = [one["why"] for one in analysis["segments"]["gives"]["links"] if one["what"] == "skips"]
    assert any("такого издателя нет" in one for one in why)
    assert any("связь с ним в дереве есть" in one for one in why)


@pytest.mark.parametrize(
    ("mine", "deal", "state", "why"),
    [
        ("2.0", "2.0", "ok", ""),  # договор и свои факты на одном номере
        ("2.0", "2.1", "behind", ""),  # отстали внутри мажора — красный
        ("1.6", "2.0", "unknown", "#845"),  # переезд: форма та же, ждёт витрину
        ("1.2", "2.0", "unknown", "#845"),  # переезд и отставание внутри 1.x — тот же серый
        ("1.6", None, "unknown", "не опубликовано"),  # издатель договора не отдаёт
    ],
)
def test_facts_are_compared_with_the_deal(
    tmp_path: Path, mine: str, deal: str | None, state: str, why: str
) -> None:
    """Номер своих фактов — с договором фактов издателя; переезд 1 → 2 — серый."""
    root = tree(tmp_path)
    facts_file(root, {"schema": mine})
    gives = {"facts": deal} if deal else {}
    said = summary(publisher(CATALOGUE, **gives), publisher("ArtVsMark/ArtVsMark", facts="1.6"))
    links = fc.analyse(root, said, "o/p")["segments"]["family"]["links"]
    (link,) = [one for one in links if one["what"] == "facts"]
    assert link["publisher"] == CATALOGUE
    assert link["state"] == state
    assert why in link["why"]


def test_the_showcase_with_facts_is_not_a_publisher() -> None:
    """Витрина, ещё отдающая facts 1.x, роли издателя не получает (каталог #843)."""
    codes = fc.family_publishers(summary(publisher("ArtVsMark/ArtVsMark", facts="1.6")))
    assert set(codes.values()) == {"EIP", "EPM"}
    said = summary(publisher("o/a", facts="1.6"), publisher("o/b", facts="2.0"))
    assert fc.publisher_disputes(said) == []


@pytest.mark.parametrize(
    ("facts", "state", "behind", "why"),
    [
        (None, "unknown", 0, "фактов нет"),
        ({"schema": "1.6"}, "unknown", 0, "нет python.os"),
        ({"python": {"os": []}}, "unknown", 0, "нет python.os"),
        ({"python": {"os": ["ubuntu-26.04"]}}, "ok", 0, ""),
        ({"python": {"os": ["ubuntu-26.04", "windows-latest", "macos-latest"]}}, "behind", 2, ""),
        (["не объект"], "unknown", 0, "нет python.os"),
        ({"python": ["ubuntu-26.04"]}, "unknown", 0, "нет python.os"),
        ({"python": "3.14"}, "unknown", 0, "нет python.os"),
        ({"python": {"os": "ubuntu-26.04"}}, "unknown", 0, "нет python.os"),
        ({"python": {"os": ["ubuntu-26.04", 42]}}, "unknown", 0, "не строка"),
    ],
)
def test_ext_by_own_facts(tmp_path: Path, facts: object, state: str, behind: int, why: str) -> None:
    """Все формы входа ext: плавающая метка — красный, нечего судить — серый с причиной."""
    root = tree(tmp_path)
    if facts is not None:
        facts_file(root, facts)
    ext = fc.analyse(root, summary(), "o/p")["segments"]["external"]
    assert ext["state"] == state
    assert sum(one["state"] == "behind" for one in ext["links"]) == behind
    assert why in ext["why"]
    if behind:
        assert fc.caption("external", ext) == f"ext ✗{behind}"
        assert {one["what"] for one in ext["links"] if one["state"] == "behind"} == {
            "windows-latest",
            "macos-latest",
        }


@pytest.mark.parametrize("path", [".rules/bindings.json", ".github/badges/facts.json"])
def test_a_tree_file_not_an_object_does_not_break(tmp_path: Path, path: str) -> None:
    """Ответ и факты не той формы — сверять нечего, а не исключение."""
    root = tree(tmp_path)
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text("[1]", encoding="utf-8")
    said = summary(publisher(CATALOGUE, bindings="1.9", export="1.9"))
    links = fc.analyse(root, said, "o/p")["segments"]["family"]["links"]
    assert not [one for one in links if one["where"] == path]


@pytest.mark.parametrize(
    ("pipeline", "steps", "state", "why"),
    [
        (None, "0.7", None, ""),  # шагов не берёт — связи нет
        ("checks: {}\n", "0.7", "unknown", "не объявлен"),
        ('contract: "0.5..0.9"\n', "0.7", "unknown", "не той формы"),
        ('contract: ">=0.5,<0.9"\n', None, "unknown", "не опубликовано"),
        ('contract: ">=0.5,<0.9"\n', "0.7", "ok", ""),
        ("contract: '>=0.5,<0.9'  # окно перехода\n", "0.7", "ok", ""),
        ('contract: ">=0.5,<0.7"\n', "0.7", "behind", "вне объявленного"),
        ('contract: "==0.6"\n', "0.7", "unknown", "не той формы"),  # наша форма — с верхом
        ('contract: ">=0.8,<0.9"\n', "0.7", "unknown", "опережает"),
        ("contract: [не закрыт\n", "0.7", "unknown", "не разбирается"),
    ],
)
def test_the_steps_range(
    tmp_path: Path, pipeline: str | None, steps: str | None, state: str | None, why: str
) -> None:
    """Все формы входа диапазона шагов: нет файла, строки, формы, издателя; в и вне."""
    root = tree(tmp_path)
    pipeline_file(root, pipeline)
    gives = {"steps": steps} if steps else {}
    analysis = fc.analyse(root, summary(publisher(MECH, **gives)), "o/p")
    links = [one for one in analysis["segments"]["family"]["links"] if one["what"] == "steps"]
    if state is None:
        assert links == []
        return
    assert [one["state"] for one in links] == [state]
    assert why in links[0]["why"]


def test_the_range_under_a_dispute_is_grey(tmp_path: Path) -> None:
    """Контракт шагов отдают двое — сверять не с кем."""
    root = tree(tmp_path)
    pipeline_file(root, 'contract: ">=0.5,<0.9"\n')
    said = summary(publisher(MECH, steps="0.7"), publisher("o/mech-2", steps="0.8"))
    links = [
        one
        for one in fc.analyse(root, said, "o/p")["segments"]["family"]["links"]
        if one["what"] == "steps"
    ]
    assert links[0]["state"] == "unknown"
    assert "несколько проектов" in links[0]["why"]


def test_uptake_of_a_publisher_by_summary_links() -> None:
    """Сколько проектов семьи перешли на издателя (каталог #844)."""
    said = summary(
        {**publisher(CATALOGUE), "links": {}},
        {**publisher("o/a"), "links": {"EIP": "ok"}},
        {**publisher("o/b"), "links": {"EIP": "partial", "EPM": "ok"}},
        {**publisher("o/c"), "links": {"EIP": "none"}},
        {**publisher("o/e"), "links": {"EIP": "unknown"}},  # связь есть, свежесть не сверена
        {**publisher("o/f"), "links": {"EIP": "skipped"}},  # отказ — не перешёл
        publisher("o/d"),  # не прочитан
    )
    taken = fc.uptake(said, CATALOGUE, fc.family_publishers(said))
    assert taken == {"code": "EIP", "taken": 3, "of": 6, "unread": 1, "by": ["o/a", "o/b", "o/e"]}
    _label, count = fc.uptake_zone(taken)
    assert count[0] == "3/6"
    assert "не прочитано у 1" in count[2]


def test_no_uptake_for_a_non_publisher(tmp_path: Path) -> None:
    """У проекта, который семье ничего не издаёт, вопроса перехода нет."""
    root = tree(tmp_path)
    analysis = fc.analyse(root, summary({**publisher("o/a"), "links": {"EIP": "ok"}}), "o/p")
    assert "uptake" not in analysis
    assert all(zone[0][0] != "uptake" for zone in fc.zones(analysis))


def test_uptake_all_unread_is_grey() -> None:
    """Никто не прочитан — число серое, а не синее."""
    said = summary(publisher(CATALOGUE), publisher("o/a"))
    taken = fc.uptake(said, CATALOGUE, fc.family_publishers(said))
    assert fc.uptake_zone(taken)[1][1] == fc.COLOR["unknown"]


def test_one_lag_is_named_once_with_count_and_file() -> None:
    """Два uses: на одном старом выпуске — одна строка подсказки, а не повтор."""
    link = {
        "what": "release",
        "mine": "v1.5.0",
        "latest": "v1.8.0",
        "where": ".github/workflows/mechanisms.yml",
        "state": "behind",
    }
    fresh = {**link, "mine": "v1.8.0", "where": "a.yml", "state": "ok"}
    other = {**link, "where": "b.yml", "mine": "v1.4.0"}
    assert fc.lag([link, dict(link), fresh]) == (
        "release: v1.5.0 → v1.8.0 (связей 2, .github/workflows/mechanisms.yml)"
    )
    assert fc.lag([link, other]) == (
        "release: v1.5.0 → v1.8.0 (.github/workflows/mechanisms.yml); "
        "release: v1.4.0 → v1.8.0 (b.yml)"
    )


# ── своё: опоры механизмов вместо каталожных ──


def test_pins_are_read_from_workflows_and_actions_by_yaml(tmp_path: Path) -> None:
    """`uses:` работы, шага и шага действия — разбором YAML; локальное и docker — мимо."""
    root = tree(tmp_path, f"{MECH}/.github/workflows/step-x.yml@v1.5.0")
    (root / ".github" / "workflows" / "b.yml").write_text(
        "on: push\njobs:\n  y:\n    steps:\n"
        "      - uses: actions/checkout@v5  # комментарий не входит\n"
        "      - uses: ./local\n      - uses: docker://alpine:3\n",
        encoding="utf-8",
    )
    action = root / ".github" / "actions" / "one"
    action.mkdir(parents=True)
    (action / "action.yml").write_text(
        "runs:\n  using: composite\n  steps:\n"
        f"    - uses: {CATALOGUE}/.github/actions/answer@v2.1.0\n",
        encoding="utf-8",
    )
    found, refused = fc.pinned(root)
    assert found == [
        (MECH, "v1.5.0", ".github/workflows/a.yml"),
        ("actions/checkout", "v5", ".github/workflows/b.yml"),
        (CATALOGUE, "v2.1.0", ".github/actions/one/action.yml"),
    ]
    assert refused == []


def test_an_unparsed_workflow_is_a_grey_link(tmp_path: Path) -> None:
    """Прогон, который не разбирается, — серая связь с адресом, а не «связей нет»."""
    root = tree(tmp_path)
    (root / ".github" / "workflows" / "broken.yml").write_text(
        "jobs: [не закрыт\n", encoding="utf-8"
    )
    found, refused = fc.pinned(root)
    assert found == []
    assert [one.split(":")[0] for one in refused] == [".github/workflows/broken.yml"]
    links = fc.family_links(root, summary(publisher(MECH)), "o/p")
    assert [(one.what, one.state, one.where) for one in links] == [
        ("uses", "unknown", ".github/workflows/broken.yml")
    ]


@pytest.mark.parametrize(
    ("said", "expected"), [("v1.10.0", (1, 10, 0)), ("facts-v2.0.0", (2, 0, 0)), ("main", None)]
)
def test_number_reads_the_trailing_version(said: str, expected: tuple[int, ...] | None) -> None:
    """Число версии — из хвоста тега или номера; ветка — не версия."""
    assert fc.number(said) == expected


def test_compare_facts_names_the_move() -> None:
    """Переезд договора 1 → 2 — серый с причиной, отставание внутри мажора — красный."""
    assert fc.compare_facts("1.6", "2.0").state == "unknown"
    assert fc.compare_facts("2.0", "2.1").state == "behind"


def test_read_summary_by_address_and_path(tmp_path: Path) -> None:
    """Сводка по адресу — общим транспортом; отказ и чужая форма — беда с адресом."""
    url = "https://example.test/family.json"
    assert fc.read_summary(url, lambda _url: summary()) == (summary(), "")

    def broken(_url: str) -> dict[str, Any]:
        raise fc.ghrest.TransportError("нет ответа")

    doc, trouble = fc.read_summary(url, broken)
    assert doc is None
    assert url in trouble
    assert fc.read_summary(url, lambda _url: {"schema": "1.2"})[0] is None
    path = tmp_path / "family.json"
    path.write_text(json.dumps(summary()), encoding="utf-8")
    assert fc.read_summary(str(path)) == (summary(), "")


def test_known_names_every_project_of_the_summary() -> None:
    """Семья — все проекты сводки, прочитанные и нет."""
    said = summary(publisher("O/A"), {"repo": "o/b", "state": "absent", "why": "404"})
    assert fc.known(said) == {"o/a", "o/b"}
    assert set(fc.published(said)) == {"o/a"}
    assert fc.claimants(summary(publisher("o/a", steps="0.7")), "steps") == ["o/a"]


def test_steps_links_directly(tmp_path: Path) -> None:
    """Без `.pipeline.yml` связи нет; со свежим номером в диапазоне — сходится."""
    said = summary(publisher(MECH, steps="0.7"))
    assert fc.steps_links(tmp_path, said) == []
    pipeline_file(tmp_path, 'contract: ">=0.5,<0.9"\n')
    (link,) = fc.steps_links(tmp_path, said)
    assert (link.publisher, link.mine, link.latest, link.state) == (
        MECH,
        ">=0.5,<0.9",
        "0.7",
        "ok",
    )


def test_external_links_directly(tmp_path: Path) -> None:
    """Плавающая метка отстаёт, прибитая сходится; фактов нет — пусто с причиной."""
    assert fc.external_links(tmp_path) == ([], f"фактов нет: {fc.FACTS} не прочитан")
    facts_file(tmp_path, {"python": {"os": ["ubuntu-latest", "ubuntu-26.04"]}})
    links, why = fc.external_links(tmp_path)
    assert why == ""
    assert [(one.what, one.state) for one in links] == [
        ("ubuntu-latest", "behind"),
        ("ubuntu-26.04", "ok"),
    ]


def test_skip_flaws_directly() -> None:
    """Отказ от неизвестного — опечатка; отказ при живой связи — противоречие; иначе пусто."""
    live = [fc.Link("family", MECH, "release", "v1", "v1", "a.yml", "ok")]
    manifest = {"skips": {"EMP": "опечатка", "EPM": "не нужны", "EIP": "правила не нужны"}}
    flaws = fc.skip_flaws(manifest, fc.PUBLISHERS, live)
    assert [(one.publisher, one.state) for one in flaws] == [("EMP", "behind"), (MECH, "behind")]
    assert fc.skip_flaws(None, fc.PUBLISHERS, live) == []


def test_by_publisher_directly() -> None:
    """Свой издатель — состояние отдачи; без связи и отказа — `none`; со связью — её цвет."""
    link = asdict(fc.Link("family", CATALOGUE, "bindings", "1.9", "1.9", "x", "ok"))
    analysis = {
        "segments": {
            "gives": {"state": "unknown", "links": []},
            "family": {"state": "ok", "links": [link]},
            "pairs": {"state": "unknown", "links": []},
        }
    }
    block = {one["code"]: one for one in fc.by_publisher(analysis, MECH, None)}
    assert block["EPM"]["state"] == "unknown"
    assert block["EPM"]["why"] == "свой: состояние отдачи"
    assert block["EIP"]["state"] == "ok"
    alone = {one["code"]: one["state"] for one in fc.by_publisher(analysis, "o/p", None)}
    assert alone == {"EIP": "ok", "EPM": "none"}
