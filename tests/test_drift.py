"""Дрейф: внешний вход сдвинулся, дерево не менялось.

Проверяется не «механизм зовёт площадку», а три свойства, без которых
совещательный канал по расписанию превращается в шум:

* расхождение названо числами — «было X, стало Y», а не «устарело»;
* у каждой записи есть следующий шаг: запись без него — сообщение о погоде;
* источники независимы, и неспрошенный источник не выглядит как «всё сошлось».
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("drift.py")


def test_a_moved_export_contract_is_named_with_both_numbers() -> None:
    """Выгрузка каталога поднялась — сказано, до чего и с чего.

    Подъём контракта означает, что ответы стоит ПЕРЕЧИТАТЬ, а не только
    починить схему (157), и следующий шаг записи говорит именно это.
    """
    found = module.catalogue_moved({"contracts": {"export": "1.6"}}, {"answers_to": "1.5"})
    assert len(found) == 1
    assert "1.6" in found[0].said and "1.5" in found[0].said
    assert "перечитать" in found[0].next_step.lower()


def test_a_settled_catalogue_says_nothing() -> None:
    """Сошедшийся каталог записи не даёт: пустая запись учит пролистывать."""
    export = {"contracts": {"export": "1.5", "bindings": "1.2"}, "count": 2}
    mine = {"answers_to": "1.5", "schema": "1.2", "rules": {"001": {}, "002": {}}}
    assert module.catalogue_moved(export, mine) == []


def test_new_rules_in_the_catalogue_are_counted() -> None:
    """Правил в каталоге больше, чем наших ответов — это очередь разбора."""
    found = module.catalogue_moved({"count": 200}, {"rules": {"001": {}}})
    assert len(found) == 1
    assert "200" in found[0].said and "1" in found[0].said


def test_a_stale_snapshot_names_the_rules_it_shows_wrong() -> None:
    """Сводка семьи показывает механизм документом — правила названы поимённо.

    Замер 10.09.2026: снимок семичасовой давности показывал шесть правил
    документами, когда они уже держались гейтами, и разрез приоритета — наш
    собственный — назвал их долгом, которого нет.
    """
    where = {
        "consumers": [
            {
                "repo": "o/Engineering-Pipeline-Mechanisms",
                "holds": {"074": {"mechanism": "document"}},
            }
        ]
    }
    mine = {"rules": {"074": {"mechanism": "gate"}}}
    found = module.snapshot_is_stale(where, mine, "o/Engineering-Pipeline-Mechanisms")
    assert len(found) == 1
    assert "074" in found[0].said


def test_a_snapshot_that_agrees_is_not_a_drift() -> None:
    """Сводка показывает то же, что дерево — записи нет."""
    where = {
        "consumers": [
            {"repo": "o/Engineering-Pipeline-Mechanisms", "holds": {"074": {"mechanism": "gate"}}}
        ]
    }
    mine = {"rules": {"074": {"mechanism": "gate"}}}
    assert module.snapshot_is_stale(where, mine, "o/Engineering-Pipeline-Mechanisms") == []


def test_missing_from_the_family_is_said_out_loud() -> None:
    """Нас нет в сводке вовсе — это находка, а не пустой ответ (045)."""
    found = module.snapshot_is_stale(
        {"consumers": []}, {"rules": {}}, "o/Engineering-Pipeline-Mechanisms"
    )
    assert len(found) == 1
    assert "нет в сводке" in found[0].said


def test_a_silent_source_never_reads_as_settled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Источник не ответил — это сказано, а не превращено в «дрейфа нет».

    Молчание источника и сошедшееся состояние снаружи одинаковы, и разница
    здесь стоит целого канала: пропущенный молча источник делает совещательный
    прогон вежливым «выключен».
    """

    def broken(*_: Any, **__: Any) -> Any:
        raise module.NotRun("снимок не прочитан")

    monkeypatch.setattr(module, "fetch", broken)
    monkeypatch.setattr(module, "pinned_tag_moved", lambda *_: [])
    found, silent = module.look("o/r", "token", {"rules": {}})
    assert found == []
    assert silent == ["каталог", "сводка семьи"]
    assert "Не спрошено" in module.render_body(found, silent)


def test_one_silent_source_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """Недоступный каталог не отменяет устаревшей сводки: источники независимы."""
    drift = module.Drift("family-snapshot", "разошлось", "починить")
    monkeypatch.setattr(module, "fetch", lambda url: {})
    monkeypatch.setattr(
        module, "catalogue_moved", lambda *_: (_ for _ in ()).throw(module.NotRun("нет"))
    )
    monkeypatch.setattr(module, "snapshot_is_stale", lambda *_: [drift])
    monkeypatch.setattr(module, "pinned_tag_moved", lambda *_: [])
    found, silent = module.look("o/r", "token", {})
    assert found == [drift]
    assert silent == ["каталог"]


def test_every_record_carries_its_next_step() -> None:
    """У записи есть следующий шаг: без него это сообщение о погоде (142)."""
    line = str(module.Drift("source", "было X, стало Y", "сделать Z"))
    assert "что делать" in line
    assert "сделать Z" in line


def test_an_empty_body_is_not_a_lie() -> None:
    """Пустое тело говорит «сошлись», а не молчит."""
    assert "сошлись" in module.render_body([])
