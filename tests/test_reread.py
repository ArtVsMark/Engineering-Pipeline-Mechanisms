"""Подпись под перечитыванием проверяется подделанной подписью.

Предмет гейта — утверждение, которое нельзя увидеть в дереве: «я перечитал
ответы». Снаружи честное перечитывание и механическое поднятие числа выглядят
одинаково — файл изменён, число выросло, дрейф замолчал. Поэтому обе стороны
подделываются
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("check_reread.py")


def answers(read_at: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ответы проекта: номер прочитанной выгрузки и сами ответы."""
    return {
        "schema": "1.3",
        "answers_to": read_at,
        "rules": rules if rules is not None else {"001": {"status": "active"}},
    }


def test_a_raised_number_without_a_touched_answer_is_refused() -> None:
    """Номер поднят, ответы не тронуты — подпись под несделанным.

    Механическое поднятие гасит сигнал дрейфа: после него молчание означает
    «ответы под новой выгрузкой», а они под прежней.
    """
    said = module.lonely(answers("1.6"), answers("1.7"))
    assert said
    assert "1.6" in said and "1.7" in said, "оба числа названы, а не «номер сдвинулся»"


def test_a_raised_number_with_a_touched_answer_passes() -> None:
    """Номер поднят и ответы тронуты — это и есть перечитывание."""
    assert not module.lonely(answers("1.6"), answers("1.7", {"001": {"status": "not-applicable"}}))


def test_a_touched_answer_without_raising_the_number_passes() -> None:
    """Обратное направление законно: починка одной строки перечитыванием не является.

    Гейт судит одно направление, и сосед назван, а не подразумевается
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    assert not module.lonely(answers("1.6"), answers("1.6", {"001": {"status": "off"}}))


def test_an_untouched_file_passes() -> None:
    """Ничего не менялось — сказать нечего."""
    assert not module.lonely(answers("1.7"), answers("1.7"))


def test_an_unreadable_base_is_the_third_outcome() -> None:
    """База не прочитана — гейт не отработал, а не «подпись честна» (045)."""
    with pytest.raises(module.NotRun):
        module.at("нет-такой-ревизии", ".rules/bindings.json")


def test_the_refusal_names_both_repairs() -> None:
    """Отказ называет обе починки: перечитать или вернуть номер (154).

    Названная одна оставляла бы вторую на догадку читателя, а они
    противоположны по смыслу.
    """
    said = module.lonely(answers("1.6"), answers("1.7"))
    assert "перечитайте" in said.lower() and "верните номер" in said.lower()
