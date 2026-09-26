"""Порядок перечитывания — замер, и проверяется он тем, что обязан отвергнуть.

Механизм называет, какой ответ читать раньше. Ошибиться он может тихо: профиль,
построенный на пустом входе, отдаёт пустой список — и это выглядит как «всё
сверено», а не как отказ
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, RunScript, load_script

module = load_script("audit_profile.py")


def rule(number: str, claim: str, title: str = "правило") -> dict[str, Any]:
    """Одна запись выгрузки в том виде, в каком её отдаёт каталог."""
    return {
        "id": number,
        "slug": f"slug-{number}",
        "title": {"ru": title},
        "claim": {"ru": claim},
    }


def test_the_closest_answer_goes_last() -> None:
    """Порядок — по подозрению: ответ, говорящий не о том, идёт первым."""
    export = {
        "rules": [
            rule("001", "конвейер держит обязательную проверку именем контекста"),
            rule("002", "изменение приезжает со своим фрагментом журнала"),
        ]
    }
    mine = {
        "001": {"status": "active", "where": "про совершенно постороннее содержимое"},
        "002": {"status": "active", "where": "изменение приезжает со своим фрагментом журнала"},
    }
    order = [row["rule"] for row in module.profile(export, mine)]
    assert order == ["001", "002"], "ближний к своему правилу ответ обязан идти последним"


def test_an_already_checked_answer_is_marked_as_such() -> None:
    """Сверенность берётся из самого ответа — из даты, а не из списка рядом (049)."""
    export = {"rules": [rule("001", "проверка называет свой предмет")]}
    looked = module.profile(export, {"001": {"status": "active", "analysed": "2026-09-18"}})
    assert looked[0]["looked"] is True
    fresh = module.profile(export, {"001": {"status": "active"}})
    assert fresh[0]["looked"] is False, "ответ без даты сверки не считается прочитанным"


def test_an_empty_export_is_the_third_outcome() -> None:
    """Выгрузки нет — отказ, а не «сверять нечего»."""
    with pytest.raises(module.NotRun, match="выгрузке"):
        module.profile({"rules": []}, {"001": {"status": "active"}})


def test_empty_answers_are_the_third_outcome() -> None:
    """Ответов нет — отказ: пустой профиль неотличим от законченного прохода."""
    with pytest.raises(module.NotRun, match="ответах"):
        module.profile({"rules": [rule("001", "что-нибудь")]}, {})


def test_answers_that_meet_no_rule_are_the_third_outcome() -> None:
    """Ни один номер не сошёлся — отказ, а не пустой список.

    Так выглядит съехавшая выгрузка: файлы на месте, оба непусты, а общего у них
    нет ничего. Молча отдать пустой профиль значило бы сказать «всё сверено».
    """
    with pytest.raises(module.NotRun, match="по номеру"):
        module.profile({"rules": [rule("001", "что-нибудь")]}, {"999": {"status": "active"}})


def test_a_rule_without_a_claim_is_the_third_outcome() -> None:
    """Притязание пусто — мерить нечем, и это отказ, а не доля ноль.

    Доля ноль означала бы «ответ дальше некуда» и поставила бы такое правило в
    самое начало прохода: отказ входа притворился бы находкой (045).
    """
    with pytest.raises(module.NotRun, match="притязание"):
        module.profile({"rules": [rule("001", "", title="")]}, {"001": {"status": "active"}})


def test_the_bands_cover_every_answer() -> None:
    """Полосы — разрез без потерь: сумма по ним равна числу ответов.

    Полоса выбирается обрезкой доли, и доля 1.0 попала бы в одиннадцатую полосу,
    которой нет. Такой ответ исчез бы из сводки молча, оставив её правдоподобной.
    """
    export = {"rules": [rule("001", "один и тот же текст"), rule("002", "другое")]}
    mine = {
        "001": {"status": "active", "where": "один и тот же текст"},
        "002": {"status": "active", "where": "ничего общего"},
    }
    rows = module.profile(export, mine)
    assert sum(module.bands(rows).values()) == len(rows)


def test_the_live_tree_profiles_without_a_platform(tmp_path: Path, run_script: RunScript) -> None:
    """Заход по снятой выгрузке идёт без сети и называет остаток.

    Своя площадка, а не живой каталог: проход обязан работать у окна, которому
    сеть недоступна, и проверяться без неё
    ([149](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/149-the-suite-owns-its-temp.md)).
    """
    export = tmp_path / "export.json"
    export.write_text(
        json.dumps({"rules": [rule("001", "проверка называет свой предмет")]}, ensure_ascii=False),
        encoding="utf-8",
    )
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps({"rules": {"001": {"status": "active", "where": "нечто иное"}}}),
        encoding="utf-8",
    )
    done = run_script(
        "audit_profile.py", "--export", str(export), "--answers", str(answers), "--take", "1"
    )
    assert done.code == module.EXIT_OK, done.err
    assert "осталось 1" in done.out, done.out


def test_since_reaches_the_count_through_main(tmp_path: Path, run_script: RunScript) -> None:
    """Ключ `--since` доходит от входа до счёта, а не только до `profile()` (#829)."""
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"rules": [rule("001", "что-нибудь")]}), encoding="utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps({"rules": {"001": {"status": "active", "analysed": "2026-09-18"}}}),
        encoding="utf-8",
    )
    base = ("audit_profile.py", "--export", str(export), "--answers", str(answers))
    assert "осталось 0" in run_script(*base).out
    assert "осталось 1" in run_script(*base, "--since", "2026-09-26").out


@pytest.mark.parametrize("said", ["2026/09/20", "2026-9-20", "26.09.2026", "вчера"])
def test_since_refuses_what_is_not_an_iso_day(said: str) -> None:
    """Дата не в форме ГГГГ-ММ-ДД — отказ на входе, а не молча неверный счёт."""
    with pytest.raises(SystemExit) as refused:
        module.main(["--since", said])
    assert refused.value.code == 2


def test_iso_day_keeps_the_form_it_compares_by() -> None:
    """`iso_day` отдаёт ту же строку, по которой идёт сравнение, и не нормализует её."""
    assert module.iso_day("2026-09-26") == "2026-09-26"
    with pytest.raises(argparse.ArgumentTypeError):
        module.iso_day("2026-9-26")


def test_a_missing_answers_file_is_the_third_outcome(tmp_path: Path, run_script: RunScript) -> None:
    """Файла ответов нет — отказ с адресом, а не пустой профиль (075)."""
    done = run_script("audit_profile.py", "--answers", str(tmp_path / "нет.json"))
    assert done.code == module.EXIT_BROKEN
    assert "взять неоткуда" in done.err, done.err


def test_the_gate_and_the_skill_name_each_other() -> None:
    """Механизм зовётся навыком, а навык — этим именем: иначе один из двух мёртв.

    Порядок без процедуры остаётся числом, которое некому применить, а процедура
    без механизма — пересказом, который каждое окно строит заново
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    skill = ROOT / ".claude" / "skills" / "audit-the-answers" / "SKILL.md"
    assert skill.is_file(), f"навык {skill} не найден — механизм зовут ниоткуда"
    said = skill.read_text(encoding="utf-8")
    assert "scripts/audit_profile.py" in said, "навык не называет механизма, которым идёт проход"


def test_a_stem_drops_the_short_and_the_empty_words() -> None:
    """Корень грубый и таким объявлен: мелочь отбрасывается, длинное режется.

    Это признак, на котором стоит ВЕСЬ порядок прохода, и меряется он здесь
    прямо, а не через профиль: ошибка в нём сдвинула бы очередь целиком, оставив
    её правдоподобной.
    """
    said = module.stems("Проверка называет свой предмет и не молчит")
    assert "прове" in said, "длинное слово обязано дать корень"
    assert "предм" in said
    assert "и" not in said and "не" not in said, "слова короче четырёх знаков не корни"
    assert "свой" not in said, "стоп-слово в корни не попадает"
    assert all(len(root) <= module.STEM for root in said), "корень длиннее объявленного предела"


def test_suspicion_is_one_when_the_answer_repeats_the_claim() -> None:
    """Полное совпадение — единица, пустое пересечение — ноль.

    Оба конца названы числом: доля, посчитанная неверно на краях, не заметна в
    середине распределения, а именно краями порядок и задаётся.
    """
    rule = {
        "id": "001",
        "title": {"ru": "заголовок правила"},
        "claim": {"ru": "механизм называет предмет проверки"},
    }
    same = module.suspicion(rule, {"where": "заголовок правила механизм называет предмет проверки"})
    assert same == pytest.approx(1.0), "ответ, повторивший притязание дословно, даёт единицу"
    other = module.suspicion(rule, {"where": "совсем посторонний текст"})
    assert other == pytest.approx(0.0), "ответ без общих корней даёт ноль"


def test_since_counts_only_a_fresh_reading() -> None:
    """Под новый аудит сверенным считается только ответ, прочитанный не раньше даты (#829)."""
    export = {"rules": [rule("001", "что-нибудь")]}
    mine = {"001": {"status": "active", "analysed": "2026-09-18"}}
    assert module.profile(export, mine)[0]["looked"] is True
    assert module.profile(export, mine, "2026-09-26")[0]["looked"] is False
    assert module.profile(export, mine, "2026-09-18")[0]["looked"] is True
