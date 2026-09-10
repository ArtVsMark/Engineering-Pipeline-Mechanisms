"""Витрина отвечает на объявленный набор вопросов — или называет, чего нет.

Набор один на все проекты семьи и взят у каталога: разные наборы не сравнить, и
то, что проект перестал отвечать, не заметит никто (022). Замер каталога по
пяти публичным проектам: из восьми вопросов пять отвечал один грейдер, остальные
четыре — ни одного.

Проверяется здесь то, без чего ответ витрине был бы объявлением намерения:

* на КАЖДЫЙ вопрос набора есть ответ — значок, адрес или названная причина;
* причина отсутствия — предложение, а не отписка: отсутствующий значок и
  застывший с витрины неотличимы (046, 075);
* у вопроса посетителя значок ПОКАЗАН в витрине: значок, которого никто не
  видит, отвечает в пустоту;
* у вопроса сопровождающего адрес РАЗРЕШАЕТСЯ в дереве, а не назван прозой (049).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

facts = load_script("build_facts.py")

SHOWCASE = ROOT / ".rules" / "showcase.json"
README = ROOT / "README.md"
#: Насколько длинной должна быть причина, чтобы ею что-то объяснялось. Число
#: взято у каталога, где правило родилось: короче — это отписка, а не причина.
REASON_AT_LEAST = 20


def answers() -> list[dict[str, Any]]:
    """Ответы проекта по вопросам витрины."""
    said = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    return list(said["questions"])


def test_the_showcase_answer_exists() -> None:
    """Ответ витрине заведён и непуст — иначе проверять нечего (075)."""
    assert SHOWCASE.is_file(), "ответа витрине нет вовсе"
    assert len(answers()) >= 5, "набор вопросов подозрительно мал"


@pytest.mark.parametrize("question", answers(), ids=lambda q: str(q["id"]))
def test_every_question_has_an_answer(question: dict[str, Any]) -> None:
    """У вопроса либо значок, либо адрес, либо названная причина.

    Пропуск не проходит: вопрос без ответа выглядит как забытый, а не как
    решённый, и отличить одно от другого снаружи нельзя.
    """
    kinds = [key for key in ("badge", "where", "absent") if question.get(key)]
    assert kinds, f"{question['id']}: ответа нет ни в каком виде"
    assert len(kinds) == 1, f"{question['id']}: ответов сразу несколько — {kinds}"


@pytest.mark.parametrize(
    "question", [q for q in answers() if q.get("absent")], ids=lambda q: str(q["id"])
)
def test_an_absent_answer_explains_itself(question: dict[str, Any]) -> None:
    """Причина отсутствия — объяснение, а не отписка."""
    said = str(question["absent"]).strip()
    assert len(said) >= REASON_AT_LEAST, f"{question['id']}: причина слишком коротка"


@pytest.mark.parametrize(
    "question", [q for q in answers() if q.get("where")], ids=lambda q: str(q["id"])
)
def test_a_maintainer_answer_resolves_in_the_tree(question: dict[str, Any]) -> None:
    """Адрес источника разрешается в дереве, а не назван прозой.

    Рецепт для человека («получается прогоном pytest -q») разошёлся бы с деревом
    молча: у сопровождающего должен быть адрес, по которому число ЖИВЁТ (049).
    """
    said = str(question["where"])
    assert (ROOT / said).exists(), f"{question['id']}: адрес «{said}» в дереве не разрешается"


@pytest.mark.parametrize(
    "question", [q for q in answers() if q.get("badge")], ids=lambda q: str(q["id"])
)
def test_a_visitor_badge_is_shown_and_built(question: dict[str, Any]) -> None:
    """Значок посетителя показан в витрине и собирается механизмом.

    Значок, которого никто не показывает, отвечает в пустоту; значок, который
    никто не собирает, застывает — и с витрины эти два случая неотличимы.
    """
    name = Path(str(question["badge"])).name
    assert name in README.read_text(encoding="utf-8"), f"{question['id']}: значка нет в витрине"
    source = (ROOT / "scripts" / "build_facts.py").read_text(encoding="utf-8")
    assert name in source, f"{question['id']}: значок объявлен, а собирать его нечем"


def test_a_badge_from_another_branch_is_not_expected_in_the_tree() -> None:
    """Значок с ветки `badges` в дереве общей ветки не лежит и не должен (125).

    Требовать его здесь значило бы требовать того, чего быть не может: ветка
    заведена ровно для того, чтобы пересборка не двигала общую.
    """
    for question in answers():
        badge = question.get("badge")
        if badge and question.get("branch") == "badges":
            assert not (ROOT / str(badge)).exists(), f"{question['id']}: артефакт вернулся в дерево"
