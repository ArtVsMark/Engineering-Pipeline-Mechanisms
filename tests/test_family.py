"""Разрез по общим механизмам семьи: что он считает и чего не считает.

Число здесь — мерило «второго исхода» эпика: окупается ли общий модуль. Ошибка
в нём не роняет ничего и потому особенно опасна — на неё будут смотреть и
принимать по ней решения о переносе.

Отвергаемое двойное: посчитать документы за механизмы (тогда сводка показывает
объём документации, а не машинное соблюдение) и выдать непрочитанное за ноль
(тогда «сводка недоступна» читается как «общие механизмы ничего не закрывают»).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

family = load_script("family.py")
facts = load_script("build_facts.py")


def summary(*consumers: dict[str, Any], schema: str = "1.2") -> dict[str, Any]:
    """Сводка каталога в том виде, в каком он её публикует."""
    return {"schema": schema, "consumers": list(consumers)}


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


def test_a_mechanism_of_two_projects_is_shared(tmp_path: Path) -> None:
    """Механизм у двух и более проектов считается общим — это весь предмет."""
    document = summary(
        consumer("o/a", **{"001": ("gate", "scripts/check_x.py")}),
        consumer("o/b", **{"002": ("gate", "tools/check_x.py")}),
    )
    picture = family.picture(document)
    assert picture["shared"] == 1
    assert picture["closed_by_shared"] == 2


def test_a_mechanism_of_one_project_is_not_shared(tmp_path: Path) -> None:
    """Домашний механизм общим не считается, сколько бы правил ни держал.

    Восемнадцать правил у одного проекта — не повод выносить: они про его
    предмет. Число говорит, где смотреть, а не что делать.
    """
    document = summary(consumer("o/a", **{"001": ("gate", "scripts/own.py")}))
    assert family.picture(document)["shared"] == 0


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
    assert picture["mechanisms"] == 0
    assert picture["held_by_machine"] == 0


def test_an_answer_without_an_address_is_not_counted() -> None:
    """Ответ без разрешимого адреса в счёт не идёт: механизма там может и не быть.

    Гейт, чей адрес нельзя назвать, обычно и не гейт — это замер каталога на
    собственных ответах, и здесь он даёт то же: считать такое значило бы
    считать прозу.
    """
    document = summary(consumer("o/a", **{"001": ("gate", "держится всеми скриптами разом")}))
    assert family.picture(document)["mechanisms"] == 0


def test_the_share_is_of_machine_held_only() -> None:
    """Доля считается от машинного соблюдения, а не от всех ответов подряд.

    Знаменатель со всеми видами включал бы документы и занижал долю вдвое —
    мерило «окупается ли общий модуль» показывало бы не то.
    """
    document = summary(
        consumer("o/a", **{"001": ("gate", "scripts/x.py"), "002": ("document", "CLAUDE.md")}),
        consumer("o/b", **{"003": ("gate", "scripts/x.py")}),
    )
    picture = family.picture(document)
    assert picture["held_by_machine"] == 2
    assert picture["share"] == 1.0


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


def test_the_top_is_ordered_by_rules(tmp_path: Path) -> None:
    """В верхушке сначала те, кто держит больше правил: разрез про это и есть."""
    document = summary(
        consumer("o/a", **{"1": ("gate", "a.py"), "2": ("gate", "b.py"), "3": ("gate", "b.py")}),
        consumer("o/b", **{"4": ("gate", "a.py"), "5": ("gate", "b.py")}),
    )
    top = family.picture(document)["top"]
    assert [item["name"] for item in top] == ["b.py", "a.py"]


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
