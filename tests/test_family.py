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
from typing import Any

import pytest

from tests.conftest import load_script

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


def test_the_rules_badge_counts_machines_not_answers() -> None:
    """Значок считает правила, держащиеся МАШИНОЙ, а не отвеченные.

    Прежняя редакция показывала `answered/total` и подписывала это «правил
    держится». Число было `195/195` и не могло стать другим: проект отвечает по
    каждому правилу каталога по построению (129). Значок, который не движется,
    ничего не говорит ни о том, где проект стоит, ни о том, что он сдвинулся.
    """
    said = facts.rules_badge(
        {"rules": {"by_mechanism": {"gate": 10, "pipeline": 2, "document": 8, "none": 1}}}
    )
    assert said.message == "12/21"
    assert said.label == "держится машиной"


def test_the_family_badge_says_when_it_has_no_data() -> None:
    """Снимок семьи не пришёл — значок говорит это, а не рисует ноль (045)."""
    assert facts.family_badge({"family": {"read": False}}).message == "нет данных"
    assert facts.family_badge({}).message == "нет данных"


def test_the_family_badge_shows_calls_steps_and_gates() -> None:
    """Значок несёт три числа с числителем и знаменателем (#1199, решение 07.10.2026)."""
    said = facts.family_badge(
        {
            "family": {
                "read": True,
                "adopted": {"ours": 2, "of": 800, "by": []},
                "uptake": {
                    "read": True,
                    "projects": {"took": 1, "of": 5, "unread": 0, "unread_repos": []},
                    "steps": {"taken": 3, "of": 20, "names": []},
                },
            }
        }
    )
    assert said.message == "1/5 проектов · 3/20 шагов · гейт 2/800 правил"


def test_an_unread_clone_is_named_on_the_badge_not_counted_as_zero() -> None:
    """Непрочитанные клоны названы числом рядом, а не спрятаны в знаменатель (045)."""
    said = facts.family_badge(
        {
            "family": {
                "read": False,
                "uptake": {
                    "read": True,
                    "projects": {"took": 0, "of": 5, "unread": 2, "unread_repos": ["a", "b"]},
                    "steps": {"taken": 0, "of": 20, "names": []},
                },
            }
        }
    )
    assert said.message == "0/5 проектов (2 не прочитано) · 0/20 шагов · гейт: нет данных"


def test_an_unread_sweep_is_not_a_zero_on_the_badge() -> None:
    """Обход не прочитан — «вызовы не прочитаны», а не «0/5» (045)."""
    said = facts.family_badge(
        {"family": {"read": True, "adopted": {"ours": 0, "of": 9}, "uptake": {"read": False}}}
    )
    assert said.message == "вызовы не прочитаны · гейт 0/9 правил"


# --- взяли гейт: объявленное происхождение ---------------------------------


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
    for ours in ("gate", "pipeline", "code"):
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
    from tests.conftest import ROOT, walk

    found = {
        path.stem
        for path in walk(ROOT / "scripts", "*.py")
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
