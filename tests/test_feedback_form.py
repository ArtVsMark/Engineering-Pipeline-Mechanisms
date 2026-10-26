"""Форма раздела `feedback:` — канал от соседей к нам (#1665).

Обе половины: годная запись читается, а каждое нарушение формы — отказ с
местом записи и поля; раздел сверяется тем же заходом, что ответ по шагам.
"""

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

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
    answer.write_text(answer.read_text(encoding="utf-8").split("feedback:")[0], encoding="utf-8")
    assert "e2e" in policy.load(answer), "без раздела сверка проходит"
