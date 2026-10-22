"""Разрез по общим механизмам семьи: что он считает и чего не считает.

Число здесь — мерило «второго исхода» эпика: окупается ли общий модуль. Ошибка
в нём не роняет ничего и потому особенно опасна — на неё будут смотреть и
принимать по ней решения о переносе.

Отвергаемое двойное: посчитать документы за механизмы (тогда сводка показывает
объём документации, а не машинное соблюдение) и выдать непрочитанное за ноль
(тогда «сводка недоступна» читается как «общие механизмы ничего не закрывают»).
"""

import json
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

family = load_script("family.py")
facts = load_script("build_facts.py")


def summary(*consumers: dict[str, Any], schema: str = "") -> dict[str, Any]:
    """Сводка каталога в том виде, в каком он её публикует.

    Форма по умолчанию — ТА, ПОД КОТОРУЮ НАПИСАН РАЗРЕЗ, а не переписанное
    рядом число. Копия здесь стояла: `"1.2"` жило в подделке ещё девять дней
    после того, как каталог ушёл на 1.3, — и «сходится» проверялось против
    самой подделки, а не против живого разреза (022).
    """
    return {"schema": schema or family.READS_SCHEMA, "consumers": list(consumers)}


def consumer(repo: str, **holds: tuple[str, str]) -> dict[str, Any]:
    """Один потребитель: правило → вид механизма и его адрес."""
    return {
        "repo": repo,
        "holds": {
            rule: {"mechanism": kind, "where": where} for rule, (kind, where) in holds.items()
        },
    }


def written(tmp: Path, document: dict[str, Any]) -> Path:
    """Кладёт сводку в файл — механизм читает её с диска."""
    path = tmp / "where.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_documents_are_not_mechanisms(tmp_path: Path) -> None:
    """Документ механизмом не считается: его некуда выносить.

    Без этого фильтра топ забивают `CLAUDE.md` (80 правил у пятерых) и
    `README.md` — сводка показывала бы объём документации, а не машинное
    соблюдение.
    """
    document = summary(
        consumer("o/a", **{"001": ("document", "CLAUDE.md")}),
        consumer("o/b", **{"002": ("document", "CLAUDE.md")}),
    )
    picture = family.picture(document)
    assert picture["held_by_machine"] == 0
    assert picture["adopted"]["of"] == 0


def test_an_empty_summary_is_an_input_error(tmp_path: Path) -> None:
    """Сводка без потребителей — ошибка входа, а не «общих механизмов нет» (075)."""
    with pytest.raises(family.NotRun):
        family.load(written(tmp_path, {"schema": "1.2", "consumers": []}))


def test_a_missing_summary_is_an_input_error(tmp_path: Path) -> None:
    """Файла нет — отказ, а не пустой разрез."""
    with pytest.raises(family.NotRun):
        family.load(tmp_path / "нет.json")


def test_an_unreadable_summary_is_not_zero(tmp_path: Path) -> None:
    """Непрочитанная сводка объявляется НЕ прочитанной, а не нулевой.

    Ноль здесь читается как «общие механизмы ничего не закрывают» — то есть как
    ответ на вопрос эпика, которого никто не давал (045).
    """
    answer = facts.family_facts(tmp_path / "нет.json")
    assert answer["read"] is False
    assert answer["why"]
    assert "share" not in answer, "непрочитанное выдано числом"


def test_an_unparsed_summary_gives_the_reader_a_reason_not_a_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Неразобранная сводка — та же причина для читателя, а подробность в stderr.

    `str(exc)` нёс в публичный файл путь раннера и `repr` ошибки разбора — ту
    же трассу, что `none.python` до #1014 (взгляд на #1014, 195).
    """
    path = tmp_path / "summary.json"
    path.write_text("{не json", encoding="utf-8")
    answer = facts.family_facts(path)
    assert answer["read"] is False and answer["why"] == facts.NO_FAMILY
    assert answer["uptake"]["read"] is False, "непрочитанный обход выдан числом"
    assert str(path) in capsys.readouterr().err, "подробность отказа потеряна"


def test_a_read_summary_names_the_schema_it_expects(tmp_path: Path) -> None:
    """Разрез называет, под какую форму сводки он написан, и сходится ли она.

    Форма чужая: её подъём — повод перечитать разрез, а не подвинуть число
    (157). Расхождение стоит рядом с числами, а не прячется.
    """
    path = written(tmp_path, summary(consumer("o/a", **{"001": ("gate", "scripts/x.py")})))
    answer = facts.family_facts(path)
    assert answer["read"] is True
    assert answer["schema_expected"] == family.READS_SCHEMA
    assert answer["schema_agrees"] is True


def test_a_diverged_schema_is_named_not_hidden(tmp_path: Path) -> None:
    """Разошедшаяся форма сводки названа прямо, а числа всё равно показаны.

    Спрятать числа было бы хуже: разрез перестал бы работать в тот момент,
    когда каталог поднял версию, — и никто бы не понял почему.
    """
    path = written(
        tmp_path, summary(consumer("o/a", **{"001": ("gate", "scripts/x.py")}), schema="9.9")
    )
    answer = facts.family_facts(path)
    assert answer["read"] is True
    assert answer["schema_agrees"] is False


def test_a_diverged_schema_is_said_out_loud(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Расхождение формы ПЕЧАТАЕТСЯ, а не только кладётся в факты.

    ВЫЧИСЛЕННОЕ И НЕСКАЗАННОЕ РАВНО НЕСЧИТАННОМУ. Соседний тест держал, что
    расхождение «названо прямо», — и держал он при этом ключ в словаре,
    который никто не открывает. Замер: сводка ушла на 1.3 восьмого сентября,
    разрез остался под 1.2, `schema_agrees` считался ложью каждый прогон, и
    девять дней об этом не знал никто (046).
    """
    path = written(
        tmp_path, summary(consumer("o/a", **{"001": ("gate", "scripts/x.py")}), schema="9.9")
    )
    code = facts.main(["--family", str(path), "--out", str(tmp_path / "out"), "--repo", "o/r"])
    said = capsys.readouterr()
    assert code == facts.EXIT_OK
    assert "9.9" in said.err and family.READS_SCHEMA in said.err, (
        "расхождение формы не сказано вслух: " + said.err
    )


def test_a_matching_schema_says_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Форма сошлась — про неё молчат: строка о сходящемся учит не читать строк."""
    path = written(tmp_path, summary(consumer("o/a", **{"001": ("gate", "scripts/x.py")})))
    facts.main(["--family", str(path), "--out", str(tmp_path / "out"), "--repo", "o/r"])
    assert "форма сводки" not in capsys.readouterr().err


def test_no_second_collector_is_started() -> None:
    """Разрез читает готовую сводку и не собирает те же числа заново (022).

    Два сборщика одних данных расходятся молча, и оба выглядят правдоподобно.
    """
    source = (Path(__file__).resolve().parent.parent / "scripts" / "family.py").read_text("utf-8")
    # Проверяется ДЕЙСТВИЕ, а не слово: «bindings» законно стоит в докстроке,
    # где объяснено, почему их читать не надо. Второй сборщик виден иначе — он
    # ходит по дереву и открывает больше одного файла.
    assert source.count("read_text(") == 1, "разрез читает больше одного источника"
    assert "glob(" not in source, "разрез обходит дерево — это второй сборщик"


def test_the_cut_carries_the_date_of_the_snapshot_it_read() -> None:
    """Числа разреза едут вместе с датой снимка, по которому посчитаны.

    Они не о сегодняшнем дне семьи, а о том, каким её видел последний ночной
    заход каталога. Замер 10.09.2026: сводка семичасовой давности показывала
    восемь наших правил документами, когда они уже держались гейтами, и разрез
    приоритета по ней назвал долгом то, чего нет (005).
    """
    summary = {
        "schema": "1.2",
        "generated_at": "2026-09-10T07:27:49+00:00",
        "consumers": [],
    }
    assert family.picture(summary)["snapshot_at"] == "2026-09-10T07:27:49+00:00"


def test_a_snapshot_without_a_date_says_so() -> None:
    """Даты в снимке нет — поле пустое, а не подставленное сегодняшним днём."""
    assert family.picture({"schema": "1.2", "consumers": []})["snapshot_at"] == ""


# --- значки --------------------------------------------------------------


ORIGINS_PLANTED: Final = {
    "pairs": 22,
    "taken": 4,
    "adapted": 18,
    "undeclared": 0,
    "projects": {"took": 3, "of": 5},
}


def test_the_shared_step_lays_the_badge_inputs_from_consumer_facts(tmp_path: Path) -> None:
    """Режим `--endpoints-out` кладёт покрытие и версию — входы значка каталога (#1422).

    У потребителя в фактах нет наших разделов: оба значка читают общие
    показатели, а полноту версии — из темы обмена `steps`. Непрочитанный файл
    — отказ с причиной, а не пустой вход (045).
    """
    given = tmp_path / "facts.json"
    given.write_text(
        json.dumps(
            {
                "version": "1.7.3",
                "coverage_percent": 91.5,
                "exchange": {"steps": {"schema": "1.0", "version_whole": True}},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert facts.main(["--from-facts", str(given), "--endpoints-out", str(out)]) == facts.EXIT_OK
    assert sorted(path.name for path in out.iterdir()) == sorted(facts.BADGES)
    version = json.loads((out / "version.json").read_text(encoding="utf-8"))
    coverage = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert version["message"] == "1.7.3" and coverage["message"] == "91.5%"
    assert facts.endpoints_drawn(tmp_path / "нет.json", str(out)) == facts.EXIT_BROKEN


@pytest.mark.parametrize("said", ["[]", '{"coverage_percent": "много"}'], ids=["список", "строка"])
def test_endpoint_facts_of_a_wrong_shape_are_a_refusal_not_a_traceback(
    tmp_path: Path, said: str
) -> None:
    """Факты не объект или число не числом — исход 2 с причиной, а не трейсбек."""
    given = tmp_path / "facts.json"
    given.write_text(said, encoding="utf-8")
    assert facts.endpoints_drawn(given, str(tmp_path / "out")) == facts.EXIT_BROKEN


def test_endpoints_out_alone_is_a_refusal(tmp_path: Path) -> None:
    """`--endpoints-out` без `--from-facts` — отказ, а не тихая полная сборка (`303d8f0`)."""
    assert facts.main(["--endpoints-out", str(tmp_path)]) == facts.EXIT_BROKEN


def test_both_writers_lay_the_same_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Конечные точки кладут общий шаг и наша публикация — через одного писателя.

    Иначе покрытие на значке проекта и в `coverage.json` ветки разошлись бы
    при первой правке одного из двух циклов.
    """
    called: list[str] = []
    monkeypatch.setattr(facts, "draw_endpoints", lambda *_: called.append("endpoints"))
    # Страницы и файлы для машины читают наши разделы — здесь предмет не они.
    monkeypatch.setattr(facts, "PAGES", {})
    monkeypatch.setattr(facts, "MACHINE_READ", {})
    given = tmp_path / "facts.json"
    given.write_text("{}", encoding="utf-8")
    assert facts.endpoints_drawn(given, str(tmp_path / "shared")) == facts.EXIT_OK
    facts.draw_badges({"repo": "o/r"}, tmp_path)
    assert called == ["endpoints", "endpoints"]
    monkeypatch.undo()
    drawn = tmp_path / "drawn"
    drawn.mkdir()
    facts.draw_endpoints({}, drawn)
    assert sorted(path.name for path in drawn.iterdir()) == sorted(facts.BADGES)


def declared(repo: str, **holds: tuple[str, str, str]) -> dict[str, Any]:
    """Потребитель формы 1.6: правило → вид, origin и origin_kind."""
    return {
        "repo": repo,
        "holds": {
            rule: {"mechanism": kind, "where": "x.py", "origin": origin, "origin_kind": how}
            for rule, (kind, origin, how) in holds.items()
        },
    }


def test_a_gate_of_our_origin_is_adopted_and_a_namesake_is_not() -> None:
    """Засчитан гейт, чей origin ведёт к нам; одноимённая копия без origin — нет (#1199)."""
    ours = f"{family.OURS_ORIGIN}scripts/check_x.py@v1.4.0"
    document = summary(
        declared("o/a", **{"001": ("gate", ours, "called")}),
        declared("o/b", **{"002": ("gate", "", "")}),
        declared("o/c", **{"003": ("gate", "o/other:scripts/check_x.py@v1", "copied")}),
    )
    adopted = family.picture(document)["adopted"]
    assert adopted["ours"] == 1 and adopted["of"] == 3
    assert adopted["by"] == [{"repo": "o/a", "rule": "001", "origin": ours, "kind": "called"}]


def test_our_origin_in_another_case_is_still_ours() -> None:
    """Площадка имя репозитория различает без регистра — строчное объявление тоже наше."""
    ours = f"{family.OURS_ORIGIN.lower()}scripts/check_x.py@v1.4.0"
    document = summary(declared("o/a", **{"001": ("gate", ours, "called")}))
    assert family.picture(document)["adopted"]["ours"] == 1


def test_our_own_answers_are_not_counted_as_adopted() -> None:
    """Мерило о семье: свои ответы не входят ни в числитель, ни в знаменатель."""
    ours = f"{family.OURS_ORIGIN}scripts/x.py@v1"
    document = summary(
        declared(MINE, **{"001": ("gate", ours, "called")}),
        declared("o/a", **{"002": ("document", ours, "called")}),
    )
    assert family.picture(document, mine=MINE)["adopted"] == {"ours": 0, "of": 0, "by": []}


def test_neighbours_notes_are_read_and_ours_are_not() -> None:
    """Раздел `notes` читается поимённо; свои — нет, кривые записи — счётом (#1274, #1340)."""
    metric = {"what": "отмен за неделю", "value": 3, "measured": "2026-10-14"}
    neighbour = {
        **consumer("o/a"),
        "notes": {
            "002": {"note": "держим ревью вместо гейта"},
            "001": {"metric": metric},
            "003": "не объект",
            "004": {"note": "   "},
        },
    }
    own = {**consumer(MINE), "notes": {"005": {"note": "своё"}}}
    said = family.picture(summary(neighbour, own, {**consumer("o/b"), "notes": []}), mine=MINE)
    assert said["notes"] == {
        "count": 2,
        "read": 1,
        "unread": 0,
        "wrong_shape": 1,
        "wrong_entries": 2,
        "wrong_entries_by": [
            {"repo": "o/a", "rule": "003", "why": "запись не словарь"},
            {"repo": "o/a", "rule": "004", "why": "ни заметки, ни замера"},
        ],
        "by": [
            {"repo": "o/a", "rule": "001", "metric": metric},
            {"repo": "o/a", "rule": "002", "note": "держим ревью вместо гейта"},
        ],
    }


def test_an_empty_metric_is_not_counted_as_a_measurement() -> None:
    """Пустой замер не прибавляет запись к `count`: читать в нём нечего (взгляд на #1352)."""
    said = family.notes(summary({**consumer("o/a"), "notes": {"001": {"metric": {}}}}))
    assert said["count"] == 0 and said["by"] == []
    kept = family.notes(summary({**consumer("o/a"), "notes": {"001": {"note": "x", "metric": {}}}}))
    assert kept["by"] == [{"repo": "o/a", "rule": "001", "note": "x"}], "заметка потеряна"
    assert said["wrong_entries"] == 1


@pytest.mark.parametrize(
    ("entry", "why"),
    [
        ("не объект", "запись не словарь"),
        ({"note": "x", "seen": 1}, "чужие ключи: seen"),
        ({}, "ни заметки, ни замера"),
        ({"note": "   "}, "ни заметки, ни замера"),
        ({"note": 5}, "note не строка; ни заметки, ни замера"),
        ({"metric": "ноль"}, "metric не словарь; ни заметки, ни замера"),
        (
            {"note": 5, "seen": 1, "metric": {}},
            "чужие ключи: seen; note не строка; ни заметки, ни замера",
        ),
        ({"metric": {}}, "ни заметки, ни замера"),
        ({"metric": {"value": None}}, "ни заметки, ни замера"),
        ({"note": "x", "metric": {}}, ""),
        ({"note": "", "metric": {"value": 1}}, ""),
        ({"note": "x", "metric": {"value": 1}}, ""),
    ],
    ids=[
        "не-словарь",
        "чужой-ключ",
        "пустая",
        "пробельная-заметка",
        "заметка-не-строка",
        "замер-не-словарь",
        "все-причины",
        "пустой-замер",
        "замер-без-значений",
        "заметка-при-пустом-замере",
        "замер-без-заметки",
        "годная",
    ],
)
def test_every_form_of_a_notes_entry_is_named(entry: object, why: str) -> None:
    """Каждая форма записи, которую вход допускает, названа, а не пропущена молча (210, #1340)."""
    assert family.entry_wrong(entry) == why
    said = family.notes(summary({**consumer("o/a"), "notes": {"001": entry}}))
    assert said["wrong_entries"] == (1 if why else 0)


def test_a_good_half_of_a_crooked_entry_is_still_read() -> None:
    """Заметка при кривом замере читается, а запись всё равно названа кривой (#1340)."""
    said = family.notes(summary({**consumer("o/a"), "notes": {"001": {"note": "x", "metric": 1}}}))
    assert said["by"] == [{"repo": "o/a", "rule": "001", "note": "x"}]
    assert said["wrong_entries_by"] == [{"repo": "o/a", "rule": "001", "why": "metric не словарь"}]


def test_neighbours_notes_are_said_next_to_the_numbers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Заметки соседей и пары нашего происхождения печатаются рядом с `adopted` (#1340, #1325)."""
    kin = {
        "read": True,
        "schema_agrees": True,
        "adopted": {"ours": 1, "of": 3},
        "origins": ORIGINS_PLANTED,
        "notes": {
            "count": 2,
            "read": 4,
            "unread": 1,
            "wrong_shape": 2,
            "wrong_entries": 3,
            "wrong_entries_by": [{"repo": "o/a", "rule": "001", "why": "ни заметки, ни замера"}],
            "by": [],
        },
    }
    facts.say_family(kin)
    said = capsys.readouterr().out
    assert "заметок и замеров соседей по правилам: 2" in said
    assert "нет у 1" in said
    assert "пар «проект × механизм» 22 (взяты 4, переделаны 18, не объявлено 0)" in said
    # Ненулевые исходы «не той формы» тоже сказаны, а не только ноль (взгляд на #1340).
    assert "не той формы у 2" in said and "записей не той формы 3" in said
    # И названы поимённо с причиной (взгляд на #1352): число без причины не чинится.
    assert "  - o/a · правило 001: ни заметки, ни замера" in said


def test_a_neighbours_string_cannot_break_the_log_line(capsys: pytest.CaptureFixture[str]) -> None:
    """Перевод строки в ключе соседа не рвёт строку лога: команды `::…` не будет (#1358)."""
    kin = {
        "read": True,
        "adopted": {"ours": 0, "of": 0},
        "origins": {
            "pairs": 0,
            "taken": 0,
            "adapted": 0,
            "undeclared": 0,
            "projects": {"took": 0, "of": 0},
        },
        "schema_agrees": True,
        "notes": {
            "wrong_entries": 1,
            "wrong_entries_by": [{"repo": "o/a", "rule": "1\n::error::подлог", "why": "x"}],
        },
    }
    facts.say_family(kin)
    lines = capsys.readouterr().out.splitlines()
    assert not any(line.startswith("::") for line in lines), lines
    assert "  - o/a · правило 1 ::error::подлог: x" in lines


@pytest.mark.parametrize(
    ("over", "rest"), [(7, " … и ещё 7 "), (0, None)], ids=["сверх-предела", "ровно-предел"]
)
def test_a_long_list_of_wrong_entries_is_cut_and_counted(
    capsys: pytest.CaptureFixture[str], over: int, rest: str | None
) -> None:
    """Кривые записи соседа печатаются с пределом строк, остаток — числом (взгляд на #1358).

    Ровно предел — все строки и никакого «ещё»: граница сдвинутым сравнением
    или срезом краснела бы здесь (взгляд на #1366).
    """
    many = facts.WRONG_SHOWN + over
    kin = {
        "read": True,
        "adopted": {"ours": 0, "of": 0},
        "origins": {
            "pairs": 0,
            "taken": 0,
            "adapted": 0,
            "undeclared": 0,
            "projects": {"took": 0, "of": 0},
        },
        "schema_agrees": True,
        "notes": {
            "wrong_entries": many,
            "wrong_entries_by": [
                {"repo": "o/a", "rule": f"{n:03}", "why": "x"} for n in range(many)
            ],
        },
    }
    facts.say_family(kin)
    lines = capsys.readouterr().out.splitlines()
    named = [line for line in lines if line.startswith("  - o/a")]
    # Сверяются номера, а не счёт: срез с хвоста дал бы столько же строк.
    assert named == [f"  - o/a · правило {n:03}: x" for n in range(facts.WRONG_SHOWN)], named
    tails = [line for line in lines if line.startswith("  … и ещё")]
    if rest is None:
        assert tails == [], tails
    else:
        assert len(tails) == 1 and tails[0].startswith(" " + rest), tails


def test_a_summary_without_notes_reads_as_none() -> None:
    """Нет раздела и пустой раздел — разные исходы, а не один ноль (взгляд на #1340)."""
    said = family.picture(summary(consumer("o/a"), {**consumer("o/b"), "notes": {}}))["notes"]
    assert said == {
        "count": 0,
        "read": 1,
        "unread": 1,
        "wrong_shape": 0,
        "wrong_entries": 0,
        "wrong_entries_by": [],
        "by": [],
    }


def test_the_version_badge_names_incompleteness() -> None:
    """Версия посчитана неполно — сказано словом и цветом, а не скрыто."""
    whole = facts.version_badge({"version": "0.1.91", "version_whole": True})
    partial = facts.version_badge({"version": "0.1.91", "version_whole": False})
    assert "неполно" not in whole.message
    assert "неполно" in partial.message


# --- отставание от семьи -----------------------------------------------------


MINE = "ArtVsMark/Engineering-Pipeline-Mechanisms"


def test_a_rule_a_neighbour_holds_by_machine_and_we_do_not_is_named() -> None:
    """Сосед держит гейтом, у нас документ — это отставание, и оно видно числом.

    Цель «конвейер удовлетворяет потребности семьи» без числа остаётся
    ощущением: документ вместо гейта — либо наш пробел, либо устаревший ответ,
    и оба случая требуют работы (046).
    """
    document = summary(consumer("ArtVsMark/Glossary-Python", **{"077": ("gate", "scripts/x.py")}))
    left = family.behind(document, mine=MINE, ours={"077": {"mechanism": "document"}})
    assert left == ["077"]


def test_a_rule_we_hold_by_machine_is_not_behind() -> None:
    """Держим машиной — отставания нет, каким бы механизмом ни держал сосед."""
    document = summary(consumer("ArtVsMark/Glossary-Python", **{"077": ("gate", "scripts/x.py")}))
    # Каждым машинным видом канона, а не списком рукой (#1566).
    for ours in sorted(family.kinds.MACHINE):
        assert family.behind(document, mine=MINE, ours={"077": {"mechanism": ours}}) == []


def test_a_rule_nobody_holds_by_machine_is_not_behind() -> None:
    """Сосед держит документом — это не отставание: машины нет ни у кого.

    Иначе число мерило бы объём чужой документации, а не машинное соблюдение.
    """
    document = summary(consumer("ArtVsMark/Glossary-Python", **{"077": ("document", "docs/x.md")}))
    assert family.behind(document, mine=MINE, ours={}) == []


def test_our_own_answers_in_the_snapshot_do_not_count_as_a_neighbours() -> None:
    """Себя в чужих не считаем: снимок наших ответов отстаёт на смену.

    Иначе отставание выросло бы ровно на нашу же работу, сделанную после
    ночного захода каталога (005).
    """
    document = summary(consumer(MINE, **{"077": ("gate", "scripts/x.py")}))
    assert family.behind(document, mine=MINE, ours={"077": {"mechanism": "document"}}) == []


def test_an_unanswered_rule_counts_as_behind() -> None:
    """Ответа у нас нет вовсе — отставание тоже: молчание не механизм (154)."""
    document = summary(consumer("ArtVsMark/ArtVsMark", **{"112": ("gate", "scripts/x.py")}))
    assert family.behind(document, mine=MINE, ours={}) == ["112"]


def test_a_record_of_form_1_5_is_read_as_before() -> None:
    """Запись формы 1.5 с полем `skill`: навык в разрез не входит, машина — входит (#886).

    Вывод «разрез не меняется» держит тест с записью новой формы, а не чтение кода.
    """
    said = summary(
        {
            "repo": "o/a",
            "holds": {
                "157": {"mechanism": "skill", "skill": ".claude/skills/x", "where": "x"},
                "042": {
                    "mechanism": "gate",
                    "where": "scripts/check.py — гейт",
                    "skill": "catalogue:propose-a-rule",
                },
            },
        }
    )
    assert family.held_by_machine(said) == 1


def test_every_summary_reader_is_declared() -> None:
    """Кто читает сводку семьи, выводится из дерева и совпадает с `SUMMARY_READERS` (#888).

    Читатель узнаётся по обращению к `family.load` или `WHERE_URL`. ПРЕДЕЛ
    НАЗВАН (195): модуль, взявший адрес сводки буквами, мимо констант, не
    узнаётся — но и тогда он нарушает правило 209, и это видно чтением.
    """
    from tests.conftest import code_files

    # Корни — из `paths.SOURCES`: читатель сводки в общем низу так же обязан
    # быть объявлен, как скрипт (#1254).
    found = {
        path.stem
        for path in code_files()
        if path.stem != "catalogue"
        and (
            "WHERE_URL" in (text := path.read_text(encoding="utf-8"))
            or "family.load(" in text
            or ("def load(" in text and path.stem == "family")
        )
    }
    assert found == family.SUMMARY_READERS, (
        f"читатели сводки в дереве {sorted(found)}, объявлено {sorted(family.SUMMARY_READERS)}"
    )


def test_adopted_counts_only_machine_answers_of_the_family() -> None:
    """Знаменатель «взяли гейт» — машинные ответы семьи; документ с нашим origin не в счёт."""
    ours = f"{family.OURS_ORIGIN}scripts/x.py@v1"
    document = summary(
        declared("o/a", **{"001": ("gate", ours, "adapted"), "002": ("document", ours, "copied")}),
    )
    said = family.adopted(document)
    assert (said["ours"], said["of"]) == (1, 1)
    assert said["by"][0]["kind"] == "adapted"


def test_origins_count_pairs_of_project_and_mechanism() -> None:
    """Пара «проект × механизм» — одна, сколько бы правил её ни держали (#1325).

    Один механизм у двух проектов — два взятия; `own` и чужой `origin` не
    считаются; версия в адресе пару не дробит; переделка у одного правила
    делает переделанной всю пару.
    """
    lint = f"{family.OURS_ORIGIN}scripts/lint.py"
    hook = f"{family.OURS_ORIGIN}.claude/hooks/guard.py"
    document = summary(
        declared(
            "o/a",
            **{
                "001": ("gate", f"{lint}@v1.4.0", "called"),
                "002": ("gate", f"{lint}@v1.5.0", "adapted"),
                "003": ("document", "", "own"),
                "004": ("gate", "o/other:scripts/lint.py@v1", "copied"),
            },
        ),
        declared("o/b", **{"005": ("pipeline", f"{lint}@v1.5.0", "called")}),
        declared("o/c", **{"006": ("gate", f"{hook}@v1", "")}),
        declared(
            "o/d", **{"007": ("gate", "", "own"), "009": ("document", f"{lint}@v1", "called")}
        ),
        declared(
            "o/e",
            **{"010": ("pipeline", f"{hook}@v1", "own"), "011": ("gate", f"{lint}@v1", "лишнее")},
        ),
        declared(family.family_uptake.OURS, **{"008": ("gate", f"{lint}@v1", "called")}),
    )
    said = family.origins(document)
    # o/e: `own` и незнакомое слово при нашем адресе — «не объявлено», а не «взяты»;
    # o/d: документ с нашим адресом — не механизм, проект не засчитан (взгляд на #1346).
    assert (said["pairs"], said["taken"], said["adapted"], said["undeclared"]) == (5, 1, 1, 3)
    assert said["projects"] == {"took": 4, "of": 5}
    assert said["by"][0] == {
        "repo": "o/a",
        "mechanism": lint,
        "kind": "adapted",
        "rules": ["001", "002"],
    }
    assert family.picture(document)["origins"] == said


@pytest.mark.parametrize(
    ("origin", "mechanism"),
    [("o/r:scripts/x.py@v1.4.0", "o/r:scripts/x.py"), ("o/r:scripts/x.py", "o/r:scripts/x.py")],
    ids=["с-версией", "без-версии"],
)
def test_a_mechanism_is_named_without_its_version(origin: str, mechanism: str) -> None:
    """Версия в адресе пару не дробит: механизм на двух тегах — один механизм (#1325)."""
    assert family.unversioned(origin) == mechanism


def test_uptake_facts_name_an_unread_sweep(tmp_path: Path) -> None:
    """Числа обхода не пришли или не той формы — «не прочитано», а не ноль (045)."""
    assert facts.uptake_facts(None) == {"read": False, "why": facts.NO_UPTAKE}
    broken = tmp_path / "uptake.json"
    broken.write_text('{"projects": {}}', encoding="utf-8")
    assert facts.uptake_facts(broken)["read"] is False
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {
                "projects": {"took": 0, "of": 5, "unread": 0, "unread_repos": []},
                "steps": {"taken": 0, "of": 20, "names": []},
                "by": [],
            }
        ),
        encoding="utf-8",
    )
    said = facts.uptake_facts(good)
    assert said["read"] is True and said["steps"]["of"] == 20


def test_our_facts_say_how_fresh_the_takers_are(tmp_path: Path) -> None:
    """Свежесть взявших считается по НАШЕМУ выпуску и номеру из манифеста (#1344).

    Живое дерево: тег и `steps` — те же, что уходят в `contracts.json`, а не
    второе чтение тега. Проект на теге выпуска с совместимым диапазоном —
    свежий; на старом теге — в диапазоне.
    """
    said = facts.manifest_facts(ROOT)
    if said["release"] is None:
        pytest.skip("в клоне нет тега выпуска — свежесть мерить не по чему")
    tag, steps = said["release"]["tag"], said["gives"][facts.GIVES_STEPS]
    major, minor = (int(part) for part in steps.split("."))
    span = f">={major}.{minor},<{major}.{minor + 1}"
    numbers = tmp_path / "uptake.json"
    numbers.write_text(
        json.dumps(
            {
                "projects": {"took": 2, "of": 5, "unread": 0, "unread_repos": []},
                "steps": {"taken": 1, "of": 20, "names": ["lint"]},
                "by": [
                    {"repo": "o/свежий", "steps": ["step-lint"], "refs": [tag], "contract": span},
                    {
                        "repo": "o/старый",
                        "steps": ["step-lint"],
                        "refs": ["v0.0.1"],
                        "contract": span,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    fresh = facts.ours(ROOT, uptake=numbers)["family"]["uptake"]["fresh"]
    assert (fresh["release"], fresh["steps"]) == (tag, steps)
    assert (fresh["fresh"], fresh["in_range"], fresh["of"]) == (1, 1, 2)
    unknown = facts.ours(ROOT)["family"]["uptake"]["fresh"]
    assert unknown == {"read": False, "why": facts.family_uptake.NO_FRESHNESS}, (
        "без обхода свежесть выдана числом или пропала"
    )


# --- таблица «кем» -----------------------------------------------------------


def test_the_who_page_names_who_took_our_steps() -> None:
    """Таблица «кем» — из `family.uptake.by`, по проекту строка (#1213, вариант 1)."""
    page = facts.who_page(
        {
            "family": {
                "uptake": {
                    "read": True,
                    "projects": {"took": 1, "of": 3, "unread": 1, "unread_repos": ["o/c"]},
                    "by": [{"repo": "o/a", "steps": ["step-lint"], "refs": ["v1.6.0"]}],
                }
            }
        }
    )
    assert "| o/a | `step-lint` | `v1.6.0` |" in page
    assert "**Не прочитаны клоны:** o/c" in page


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ({"family": {"uptake": {"read": False, "why": "сеть"}}}, "**Не прочитано:** сеть."),
        ({}, f"**Не прочитано:** {facts.NO_UPTAKE}."),
        ({"family": {"uptake": {"read": True, "by": []}}}, "Пока никто"),
    ],
    ids=["обход-не-прочитан", "семьи-нет", "никто"],
)
def test_the_who_page_tells_unknown_from_nobody(said: dict[str, Any], expected: str) -> None:
    """Непрочитанный обход — «не прочитано», а не пустая таблица «никто» (045)."""
    page = facts.who_page(said)
    assert expected in page
    assert "|---|" not in page


def test_the_who_page_is_published_and_kept_on_the_branch(tmp_path: Path) -> None:
    """Страница рисуется вместе со значками и уборкой ветки не снимается (#1213)."""
    planted = {"repo": "Я/Проект", "manifest": {"release": None, "gives": {"steps": "0.7"}}}
    facts.draw_badges(
        {"rules": {"by_mechanism": {"gate": 1}}, "version": "1.0.0", **planted}, tmp_path
    )
    for name in facts.PAGES:
        assert (tmp_path / name).read_text(encoding="utf-8").startswith("# ")
        assert name in facts.branch_files()


@pytest.mark.parametrize(
    ("metric", "read"),
    [
        ({}, False),
        ({"value": None}, False),
        ({"value": ""}, False),
        ({"value": " \t"}, False),
        ({"value": " x "}, True),
        ({"value": [" "]}, False),
        ({"value": [None, {}]}, False),
        ({"value": {"x": None}}, False),
        ({"value": [" ", "x"]}, True),
        ({"value": {"x": 0}}, True),
        ({"value": 0}, True),
        ({"value": False}, True),
        ("x", False),
    ],
    ids=[
        "пусто",
        "null",
        "пустая-строка",
        "пробельная-строка",
        "строка-с-текстом",
        "список-из-пробела",
        "список-пустых",
        "словарь-с-null",
        "список-с-текстом",
        "словарь-с-нулём",
        "ноль-это-число",
        "false-это-значение",
        "не-словарь",
    ],
)
def test_a_metric_is_filled_only_by_a_value(metric: object, read: bool) -> None:
    """Замер — словарь хотя бы с одним непустым значением; ноль — значение (#1358)."""
    assert family.filled(metric) is read
    if isinstance(metric, dict):
        assert family.hollow(metric) is not read


@pytest.mark.parametrize("filled_at_bottom", [False, True], ids=["пусто", "текст"])
def test_hollow_survives_nesting_json_accepts(filled_at_bottom: bool) -> None:
    """Вложенность, которую разбирает JSON, не роняет `hollow` (поздний взгляд на #1366)."""
    depth = 10_000
    bottom = '"x"' if filled_at_bottom else '" "'
    value = json.loads("[" * depth + bottom + "]" * depth)
    assert family.hollow({"value": value}) is not filled_at_bottom
    assert family.filled({"value": value}) is filled_at_bottom


def test_a_deep_metric_reaches_the_written_facts(tmp_path: Path) -> None:
    """Глубокий замер соседа проходит чтение сводки, разрез и запись фактов — путём сборки.

    Звать надо то, что зовёт сборка (находка `dea89bd`): `family_facts` читает
    файл сводки тем же `family.load`, а `facts_text` пишет факты тем же
    вызовом, что `main`. Свой `json.dumps` рядом остался бы зелёным при смене
    записи сборки (взгляд на #1376 — у записи свой предел глубины).
    """
    build_facts = load_script("build_facts.py")
    depth = 10_000
    metric = {"value": json.loads("[" * depth + '"x"' + "]" * depth)}
    consumer = {"repo": "someone/else", "notes": {"195": {"note": "n", "metric": metric}}}
    path = tmp_path / "family.json"
    path.write_text(json.dumps(summary(consumer), ensure_ascii=False), encoding="utf-8")
    drawn = build_facts.family_facts(path)
    assert drawn["read"], drawn
    written = json.loads(build_facts.facts_text({"family": drawn}))["exchange"]["epm"]["family"]
    assert [row["rule"] for row in written["notes"]["by"]] == ["195"]
    assert written["notes"]["by"][0]["metric"] == metric


def test_a_summary_deeper_than_the_parser_is_the_third_outcome(tmp_path: Path) -> None:
    """Вложенность глубже предела разборщика — `NotRun`, а не трасса (`88edc0f`, `9846074`)."""
    path = tmp_path / "family.json"
    depth = 200_000
    path.write_text('{"consumers": ' + "[" * depth + "]" * depth + "}", encoding="utf-8")
    with pytest.raises(family.NotRun, match="не разбирается"):
        family.load(path)
