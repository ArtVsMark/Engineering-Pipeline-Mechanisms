"""Оклик проверяется тем, что он обязан НЕ послать.

Механизм, который окликает про чужое или окликает дважды, приучают
пропускать — а пропускать начинают всё
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Поэтому здесь каждый объявленный исход — своим случаем: конфликт есть,
конфликта нет, состояние ещё не посчитано, окно мертво
([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from tests.conftest import load_script

module = load_script("hail.py")
findings = load_script("findings.py")

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def commit(message: str, when: datetime = NOW) -> dict[str, object]:
    """Один коммит в том виде, в каком его отдаёт площадка."""
    return {"commit": {"message": message, "committer": {"date": when.isoformat()}}}


def test_the_address_is_read_from_the_branch_not_assigned() -> None:
    """Номер окна берётся из трейлера коммитов, и берётся ПОСЛЕДНИЙ названный.

    Ветку мог продолжить другой заход, и чинить работу зовут того, кто трогал
    её позже.
    """
    older = commit("fix: раз\n\nClaude-Session: https://claude.ai/code/session_AAA")
    newer = commit("fix: два\n\nClaude-Session: https://claude.ai/code/session_BBB")
    assert module.session_of([older, newer]) == "session_BBB"


def test_a_change_opened_by_hand_has_no_window_address() -> None:
    """Адреса нет — законное состояние: изменение открыл человек.

    Выдумывать окно для такого нечем, и адресатом становится владелец.
    """
    assert module.session_of([commit("fix: руками, без трейлеров")]) == ""
    assert module.session_of([]) == ""


def test_only_the_states_the_window_fixes_itself_are_hailed() -> None:
    """Список родов закрытый, и он назван словами, а не выведен.

    Оклик про чужое — про красную общую ветку или про находку взгляда — звал бы
    окно туда, где у состояния уже есть свой адресат (#99, #23).
    """
    assert set(module.KINDS) == {module.KIND_CONFLICT, module.KIND_OWN_RED}
    assert set(module.KIND_SAID) == set(module.KINDS), "род без слов для человека"


def test_a_check_that_has_not_run_is_not_a_red_one() -> None:
    """«Проверка ещё не шла» красным не считается: это разные состояния.

    Оклик про незавершённую звал бы окно чинить то, чего ещё нет; разводит их
    сводный гейт, а не этот шаг.
    """
    runs = [
        {"name": "lint", "status": "completed", "conclusion": "failure"},
        {"name": "test", "status": "in_progress", "conclusion": None},
        {"name": "pr-meta", "status": "completed", "conclusion": "success"},
    ]
    assert module.own_red(runs, ["lint", "test", "pr-meta"]) == ["lint"]


def test_an_advisory_red_never_reaches_the_window() -> None:
    """Совещательное красное оклика не рождает: слияния оно не держит (084)."""
    runs = [{"name": "review", "status": "completed", "conclusion": "failure"}]
    assert module.own_red(runs, ["lint", "test"]) == []


def test_a_quiet_branch_moves_the_addressee_to_the_owner() -> None:
    """Ветка молчит дольше срока — адресат меняется, а оклик остаётся.

    Признака «сессия жива» у площадки нет; есть живой артефакт — дата
    последнего коммита (049).
    """
    fresh = (NOW - timedelta(hours=module.QUIET_AFTER_HOURS - 1)).isoformat()
    stale = (NOW - timedelta(hours=module.QUIET_AFTER_HOURS + 1)).isoformat()
    assert module.is_quiet(fresh, NOW) is False
    assert module.is_quiet(stale, NOW) is True


def test_an_unknown_date_is_not_silence() -> None:
    """Дату не прочитали — владельца не будим: незнание не повод звать человека.

    Сторона выбрана та, где механизм ничего не портит (045).
    """
    assert module.is_quiet("", NOW) is False
    assert module.is_quiet("вчера", NOW) is False


def subject(kind: str = module.KIND_CONFLICT, **rest: object) -> Any:
    """Один предмет оклика с разумными умолчаниями."""
    fields: dict[str, object] = {
        "number": 7,
        "head": "abcdef1234",
        "kind": kind,
        "session": "session_AAA",
        "quiet": False,
        "why": "почему",
    }
    fields.update(rest)
    return module.Subject(**fields)


def test_a_second_hail_on_the_same_state_is_not_placed() -> None:
    """Повторный заход на той же голове второго оклика не создаёт.

    Отпечаток ведётся не счётчиком, а чтением уже стоящих окликов: второй
    список того же разошёлся бы с первым молча (049).
    """
    one = subject()
    placed = [{"body": module.render(one)}, {"body": "обычный комментарий человека"}]
    assert one.stamp in module.standing(placed)


def test_a_new_head_earns_a_new_hail() -> None:
    """Новый коммит — новая работа и новый оклик: отпечаток включает голову."""
    before = subject(head="1111111111")
    after = subject(head="2222222222")
    assert before.stamp != after.stamp
    assert after.stamp not in module.standing([{"body": module.render(before)}])


def test_a_hail_names_the_window_it_addresses() -> None:
    """Живому окну оклик говорит его номер и откуда адрес взят."""
    said = module.render(subject())
    assert "session_AAA" in said
    assert "Claude-Session" in said, "адрес назван без источника — читателю негде проверить"
    assert findings.KEPT_BY_A_MECHANISM in said, "оклик не узнаётся своим же заходом"


def test_a_hail_to_the_owner_names_why_the_addressee_changed() -> None:
    """Смена адресата объявляется, а не делается молча (154)."""
    dead = module.render(subject(quiet=True))
    assert "владелец" in dead.lower()
    assert str(module.QUIET_AFTER_HOURS) in dead

    handmade = module.render(subject(session=""))
    assert "владелец" in handmade.lower()
    assert "не окном" in handmade


def test_the_hail_does_not_promise_to_wake_the_window() -> None:
    """Оклик прямо говорит, чего он НЕ делает.

    Разбудить сессию вправе учётная запись Claude, а не токен прогона (131).
    Молчание об этом читалось бы как «окно уже позвали» — и работа лежала бы,
    пока кто-нибудь не заметит.
    """
    assert "Толкнуть окно этот механизм не может" in module.render(subject())
