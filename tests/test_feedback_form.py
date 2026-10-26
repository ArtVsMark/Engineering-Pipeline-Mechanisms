"""Форма раздела `feedback:` — канал от соседей к нам (#1665).

Обе половины: годная запись читается, а каждое нарушение формы — отказ с
местом записи и поля; раздел сверяется тем же заходом, что ответ по шагам.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("feedback_form.py")
policy = load_script("pipeline_checks.py")


def good() -> dict[str, Any]:
    """Годная запись."""
    return {
        "slug": "journal-tail-rejects-quote",
        "mechanism": "step-journal",
        "version": "v1.11.0",
        "kind": "false-refusal",
        "measured": "3 изменения из 10",
        "trace": "owner/repo#42",
    }


def test_a_good_record_is_read_and_no_section_means_no_records() -> None:
    """Раздела нет — записей нет; годная запись — `Record` с теми же полями."""
    assert module.form_of(None) == []
    [said] = module.form_of({"version": 1, "records": [good()]})
    assert said.kind == "false-refusal" and said.trace == "owner/repo#42"
    assert module.form_of({"version": 1, "records": [{**good(), "trace": "https://x.y/1"}]})


@pytest.mark.parametrize(
    ("section", "said"),
    [
        ([], "отображение"),
        ({"version": 1, "extra": 1}, "незнакомые ключи"),
        ({"version": 2, "records": []}, "ждётся 1"),
        ({"version": 1, "records": {}}, "список"),
        ({"version": 1, "records": ["x"]}, "запись 1"),
        ({"version": 1, "records": [{**good(), "who": 1}]}, "незнакомые поля"),
        ({"version": 1, "records": [{**good(), "measured": " "}]}, "measured"),
        ({"version": 1, "records": [{**good(), "slug": "С пробелом"}]}, "slug"),
        ({"version": 1, "records": [{**good(), "kind": "ложный отказ"}]}, "вид"),
        ({"version": 1, "records": [{**good(), "trace": "где-то"}]}, "trace"),
        ({"version": 1, "records": [{**good(), "mechanism": "журнал"}]}, "mechanism"),
        ({"version": 1, "records": [{**good(), "version": "1.11"}]}, "vX.Y.Z"),
        ({"version": 1, "records": [{**good(), "version": 1.11}]}, "в кавычки"),
        ({"version": 1, "records": [good(), good()]}, "дважды"),
    ],
)
def test_every_broken_form_is_refused_with_its_place(section: Any, said: str) -> None:
    """Каждое нарушение формы — `NotRun` с местом, а не молчаливое умолчание (045)."""
    with pytest.raises(module.NotRun, match=said):
        module.form_of(section)


def test_the_answer_check_judges_the_section(tmp_path: Path) -> None:
    """Битая запись — отказ сверки ответа проекта, как у других разделов наполнения."""
    answer = tmp_path / ".pipeline.yml"
    answer.write_text(
        'schema: 4\ncontract: ">=0.1,<0.2"\n'
        "checks:\n  e2e:\n    class: off\n    why: нет окружения\n"
        "feedback:\n  version: 1\n  records:\n    - slug: x\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="feedback"):
        policy.load(answer)
    head = answer.read_text(encoding="utf-8").split("feedback:")[0]
    answer.write_text(head, encoding="utf-8")
    assert "e2e" in policy.load(answer), "без раздела сверка проходит"
    # ГОДНАЯ ЗАПИСЬ ТОЖЕ ИДЁТ ЧЕРЕЗ СВЕРКУ (взгляд на #1702, 107): сверка,
    # однажды отвергнувшая законный раздел, иначе осталась бы зелёной.
    lines = [f"{key}: {value}" for key, value in good().items()]
    record = "    - " + "\n      ".join(lines) + "\n"
    answer.write_text(head + "feedback:\n  version: 1\n  records:\n" + record, encoding="utf-8")
    assert "e2e" in policy.load(answer), "годная запись сверку проходит"


def test_one_record_is_read_by_name_with_its_place() -> None:
    """`record_of` — запись по имени; место в отказе — номер записи."""
    assert module.record_of(good(), 1) == module.Record(**good())
    with pytest.raises(module.NotRun, match="запись 7"):
        module.record_of({**good(), "kind": "x"}, 7)


def verdicts(**one: Any) -> dict[str, Any]:
    """Файл вердиктов с одной записью по ключу `o/r:false-refusal/x`."""
    return {"version": 1, "verdicts": {"o/r:false-refusal/x": one}}


def test_the_live_verdicts_file_is_of_the_form() -> None:
    """Файл вердиктов дерева читается: форму держит один разбор, а не внимание (#1665)."""
    data = json.loads((ROOT / ".rules" / "feedback-verdicts.json").read_text(encoding="utf-8"))
    module.verdicts_of(data)


def test_every_verdict_names_what_its_outcome_requires() -> None:
    """Каждый исход читается со своим полем; ключ — тот же, что строит `key_of` (214)."""
    record = module.record_of(good(), 1)
    key = module.key_of("O/R", record)
    assert key == "o/r:false-refusal/journal-tail-rejects-quote"
    said = module.verdicts_of(
        {
            "version": 1,
            "verdicts": {
                key: {"verdict": "accepted", "release": "v1.12.0"},
                "o/r:false-pass/b": {"verdict": "rejected", "why": "зелёное законно: …"},
                "o/r:partial/c": {"verdict": "duplicate", "of": key},
                "o/r:not-run/d": {"verdict": "fixed", "release": "v1.12.1"},
            },
        }
    )
    assert said[key] == module.Verdict("accepted", "v1.12.0")
    assert said["o/r:false-pass/b"].said == "зелёное законно: …"


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (verdicts(verdict="rejected"), "поле why"),
        (verdicts(verdict="rejected", why="  "), "поле why"),
        (verdicts(verdict="accepted", release="main"), "тег нашего выпуска"),
        (verdicts(verdict="duplicate", of="o/r:false-refusal/x"), "ключ другой записи"),
        (verdicts(verdict="maybe"), "исход «maybe»"),
        (verdicts(verdict="fixed", release="v1.0.0", why="x"), "незнакомые поля why"),
        ({"version": 1, "verdicts": {"o/r:unknown/x": {}}}, "ключ"),
        ({"version": 1, "verdicts": {"o/r/x": {}}}, "ключ"),
        ({"version": True, "verdicts": {}}, "version"),
        ({"version": 2, "verdicts": {}}, "version"),
        ({"version": 1, "verdicts": []}, "отображение"),
    ],
)
def test_every_broken_verdict_is_refused_with_its_key(data: Any, said: str) -> None:
    """Отклонение без причины, чужой исход, не тег, дубль самого себя — отказ с ключом (154)."""
    with pytest.raises(module.NotRun, match=said):
        module.verdicts_of(data)
