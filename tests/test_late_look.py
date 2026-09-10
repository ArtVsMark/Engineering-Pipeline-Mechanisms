"""Перенос ответа позднего взгляда: что попадает в изменение и что не попадает.

Здесь отвергаемое — ПУСТОЙ ОТВЕТ, выданный за состоявшийся разбор. Прогон
обрывается, файл не пишется, форма ответа действия меняется — и во всех трёх
случаях соблазн один: положить в изменение пустой комментарий и считать шаг
отработавшим. Комментарий «находок 0», которого никто не выносил, хуже
отсутствия комментария: он выглядит как взгляд
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("late_look.py")
unlooked = load_script("unlooked.py")

ANSWER = (
    "разбор по общей ветке\nНАХОДКА[риск]: окно обхода не покрывает историю\nВЕРДИКТ: находок 1"
)


def run(text: str, **extra: Any) -> str:
    """Файл прогона действия: список сообщений, последнее — с итогом."""
    return json.dumps(
        [
            {"type": "system", "subtype": "init", "session_id": "s"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "…"}]}},
            {"type": "result", "subtype": "success", "result": text, **extra},
        ]
    )


def test_the_answer_is_taken_from_the_run() -> None:
    """Текст ответа берётся из итогового сообщения прогона."""
    assert module.answer_of(run(ANSWER)) == ANSWER


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("", "файл пуст"),
        ("не json", "файл не разобрался"),
        ('{"type": "result"}', "не список сообщений"),
        ("[]", "сообщений нет"),
        (json.dumps([{"type": "assistant"}]), "итога нет — прогон оборвался"),
        (run(""), "итог есть, а текста в нём нет"),
        (run("   \n "), "текст из одних пробелов"),
    ],
    ids=lambda item: item if isinstance(item, str) and " " in item else "",
)
def test_no_answer_is_a_state_not_an_empty_comment(raw: str, why: str) -> None:
    """Ответа нет — второй исход, а не пустой комментарий в изменении.

    Каждый случай здесь снаружи выглядит одинаково: шаг отработал. Разница
    только в том, что попадёт в изменение, — поэтому проверяется отказ.
    """
    with pytest.raises(module.NotRun):
        module.answer_of(raw)
    assert why


def test_the_comment_calls_itself_late() -> None:
    """Комментарий несёт отметку позднего взгляда — по ней его узнаёт реестр.

    Без отметки вердикт позднего прогона снял бы запись «взгляда не было», и
    реестр сказал бы, что взгляд состоялся вовремя (154). Отметка берётся у
    реестра, а не пишется здесь второй раз: разошлись бы они молча (090).
    """
    body = module.compose(77, ANSWER)
    assert unlooked.LATE_MARKER in body
    assert body.startswith(unlooked.LATE_MARKER), "отметка обязана быть до текста ревьюера"


def test_the_comment_says_it_is_not_a_review_of_the_change() -> None:
    """Граница названа в самом комментарии, а не только в своде.

    Читает его тот, кто пришёл в слитое изменение, — и он должен узнать, что
    смотрели код уже в общей ветке, там же, где читает находки (021).
    """
    body = module.compose(77, ANSWER)
    assert "#77" in body
    assert "не** ревью" in body or "не ревью" in body


def test_the_reviewers_answer_survives_verbatim() -> None:
    """Ответ ревьюера переносится как есть: строки находок читает другой механизм.

    Пересказ или обрезка здесь стоили бы находок: `review_findings` ищет
    строку целиком, и потерянная строка равна потерянной находке.
    """
    body = module.compose(77, ANSWER)
    assert ANSWER in body
