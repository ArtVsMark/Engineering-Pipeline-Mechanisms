"""Защита общей ветки читается там, где живёт, — одним чтением на всех.

ЗАМЕР 15.09.2026, стоивший этой проверки. Читателей настройки было двое, и они
спрашивали РАЗНЫЕ поверхности: дрейф — набор правил, сверка обязательного
контекста — классическую защиту. Проект защищён набором, и та же настройка по
второму адресу выглядела отсутствующей: первый настоящий заход сверки — его
попросил владелец — объявил находку «у ветки нет обязательных контекстов» на
здоровой настройке
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

ОТВЕРГАЕМОЕ ЗДЕСЬ ДВОЙНОЕ: чтение не той поверхности — и «пусто» вместо «защита
другой формы». Второе тише и хуже: у соседей по семье защита классическая, и
такой ответ отправил бы человека чинить не то (045, 154).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("protection.py")

#: Ответ площадки на «какие правила действуют на ветке» — в той форме, в какой
#: он приходит на самом деле (замер 15.09.2026 по этому репозиторию).
LIVE: list[dict[str, Any]] = [
    {"type": "deletion", "ruleset_id": 1},
    {"type": "non_fast_forward", "ruleset_id": 1},
    {
        "type": "required_status_checks",
        "ruleset_id": 1,
        "parameters": {
            "strict_required_status_checks_policy": True,
            "required_status_checks": [{"context": "ci-complete", "integration_id": 15368}],
        },
    },
]


def asked(monkeypatch: pytest.MonkeyPatch, answer: Any) -> list[str]:
    """Подделывает границу с площадкой и отдаёт список спрошенных адресов."""
    seen: list[str] = []

    def request(method: str, path: str, token: str, *rest: Any, **kw: Any) -> Any:
        seen.append(path)
        return answer(path) if callable(answer) else answer

    monkeypatch.setattr(module.ghrest, "request", request)
    return seen


def test_the_live_rules_are_read_from_the_ruleset_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Спрашивается набор правил, и только он: классическая защита — не этот адрес."""
    seen = asked(monkeypatch, LIVE)
    rules = module.live("o/r", "main", "токен")
    assert [path.split("?")[0] for path in seen] == ["repos/o/r/rules/branches/main"]
    assert "page=1" in seen[0], "список правил читается не постранично (212)"
    assert module.kinds(rules) == ["deletion", "non_fast_forward", "required_status_checks"]
    assert module.contexts(rules) == ["ci-complete"]
    assert module.strict(rules) is True


def test_a_classic_protection_address_is_not_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ни одного обращения к классической защите — это и была причина находки.

    Проверяется поведением, а не чтением кода: адрес `…/protection/…` не должен
    появляться среди спрошенных ни при каком ответе площадки (140).
    """
    seen = asked(monkeypatch, [])
    module.live("o/r", "main", "токен")
    module.guarded("o/r", "main", "токен")
    assert not any("/protection" in path for path in seen), seen


def test_an_empty_ruleset_is_not_an_answer_about_protection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой набор правил сам по себе не говорит, защищена ветка или нет."""
    asked(monkeypatch, lambda path: {"protected": True} if "/branches/" in path else [])
    assert module.live("o/r", "main", "токен") == []
    assert module.guarded("o/r", "main", "токен") is True


def test_a_transport_refusal_is_not_an_absence_of_protection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ транспорта — отказ входа, а не «правил нет» (045)."""

    def refuse(method: str, path: str, token: str, *rest: Any, **kw: Any) -> Any:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    with pytest.raises(module.NotRead, match="не прочитаны"):
        module.live("o/r", "main", "токен")
    with pytest.raises(module.NotRead, match="не прочитано"):
        module.guarded("o/r", "main", "токен")


def test_the_declaration_is_read_from_the_tree() -> None:
    """Объявление берётся из дерева, и оно у проекта есть (075)."""
    said = module.declared()
    assert said["branch"] == "main"
    assert said["required_contexts"] == ["ci-complete"]


def test_a_declaration_without_a_branch_is_refused(tmp_path: Path) -> None:
    """Объявление без ветки сравнивать не с чем — отказ входа, а не пустота."""
    path = tmp_path / "protection.json"
    path.write_text(json.dumps({"rules": []}), encoding="utf-8")
    with pytest.raises(module.NotRead, match="ветка не названа"):
        module.declared(path)
    with pytest.raises(module.NotRead, match="не объявлена"):
        module.declared(tmp_path / "нет-такого.json")


def test_the_declaration_matches_what_the_platform_serves() -> None:
    """Объявленное и действующее сходятся — на подделке из живого замера.

    Замер живой настройки лежит в этом файле: набор «Protect main», три правила,
    единственный контекст `ci-complete`, свежесть требуется. Если объявление
    разойдётся с ним, разойдётся и проверка — а не проза рядом (005).
    """
    said = module.declared()
    assert sorted(said["rules"]) == module.kinds(LIVE)
    assert sorted(said["required_contexts"]) == module.contexts(LIVE)
    assert bool(said["strict"]) is module.strict(LIVE)
    assert (ROOT / ".rules" / "protection.json").is_file()


def test_one_context_named_by_two_rulesets_is_counted_once() -> None:
    """Ветку накрывают два набора — контекст в списке всё равно один.

    Повтор не сошёлся бы с объявлением, и сверка назвала бы находку на исправной
    настройке: красное на законном учат обходить (051).
    """
    двумя = [
        {
            "type": "required_status_checks",
            "ruleset_id": 1,
            "parameters": {"required_status_checks": [{"context": "ci-complete"}]},
        },
        {
            "type": "required_status_checks",
            "ruleset_id": 2,
            "parameters": {
                "required_status_checks": [{"context": "ci-complete"}, {"context": "review"}]
            },
        },
    ]
    assert module.contexts(двумя) == ["ci-complete", "review"]
    assert module.kinds(двумя) == ["required_status_checks"], "вид правила тоже один"
