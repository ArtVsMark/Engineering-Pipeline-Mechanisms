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

import pytest

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


def test_a_conflict_is_not_announced_by_its_own_run() -> None:
    """У оклика есть путь, не зависящий от прогона окликаемого изменения.

    ЗАМЕР 11.09.2026, изменение #217. Конфликт был сделан НАМЕРЕННО, чтобы
    прогнать объявленный исход (145), — и прогон нашёл замкнутый круг: у
    конфликтного изменения нет ссылки слияния, площадке нечего собрать, и `ci`
    на нём не стартует вовсе. Записей проверок на голове оказалась одна —
    `agent-pr`, и та от толчка ветки.

    Значит оклик про конфликт не может прийти по прогону ТОГО ЖЕ изменения:
    сработал бы только чужой прогон, а при пустой очереди чужого нет. Второй
    путь обязателен — события теряются
    ([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md)).
    """
    import yaml

    from tests.conftest import ROOT

    document = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "hail.yml").read_text(encoding="utf-8")
    )
    events = set(document[True])
    assert "workflow_run" in events, "оклик перестал ходить по событию"
    # ПРОВЕРЯЕТСЯ ИМЕННО ПЕРИОДИЧНОСТЬ, А НЕ «ЕЩЁ КАКОЕ-ТО СОБЫТИЕ». Кнопка —
    # тоже событие, но она требует руки, а работа не должна её ждать (104).
    # Нашёл внешний взгляд на #218.
    assert "schedule" in events, (
        "у оклика нет ПЕРИОДИЧЕСКОГО пути: конфликт, чей прогон не стартует, "
        "не найдётся, пока кто-нибудь не нажмёт кнопку"
    )
    hours = {str(one["cron"]).split()[1] for one in document[True]["schedule"]}
    assert hours == {"*"}, f"заход не ежечасный: {hours}"


# --- объявленные исходы захода -----------------------------------------------


def test_without_the_owner_token_the_hail_says_it_is_not_set(monkeypatch: Any, capsys: Any) -> None:
    """Нет токена владельца — «не настроено», а не «окликать некого».

    Состояние слияния площадка отдаёт только с доступом на запись: на токене
    прогона оклик про конфликт был бы слепым, а слепой оклик хуже
    отсутствующего. Молчание тут состоянием не является
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    monkeypatch.delenv(module.ENV_TOKEN, raising=False)
    assert module.main(["--repo", "o/r"]) == module.EXIT_UNSET
    assert module.ENV_TOKEN in capsys.readouterr().err


def test_a_hail_that_placed_nothing_is_clean(monkeypatch: Any, capsys: Any) -> None:
    """Никому не о чем сказать — законный ноль, а не «предмет не найден».

    Предмет здесь список живых изменений, и он прочитан; пустой список окликов
    — ответ, а не молчание.
    """
    monkeypatch.setenv(module.ENV_TOKEN, "владельца")
    monkeypatch.setattr(module, "hail", lambda repo, token, *, dry_run, now: 0)
    assert module.main(["--repo", "o/r"]) == module.EXIT_OK
    assert "окликов поставлено: 0" in capsys.readouterr().out


def test_a_platform_refusal_is_the_third_outcome(monkeypatch: Any, capsys: Any) -> None:
    """Площадка отказала — «не отработал», а не «окликать некого» (045)."""

    def refuse(repo: str, token: str, *, dry_run: bool, now: Any) -> int:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setenv(module.ENV_TOKEN, "владельца")
    monkeypatch.setattr(module, "hail", refuse)
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN
    assert "не отработал" in capsys.readouterr().err


# --- ленивый ответ площадки ----------------------------------------------------


def test_the_lazy_answer_is_awaited_not_skipped(monkeypatch: Any) -> None:
    """Первый запрос заказывает расчёт — оклик ждёт, а не уходит ни с чем.

    Площадка отдаёт `unknown` на первый вопрос о готовности слияния. Прежняя
    редакция читала это как «окликать рано» и шла дальше, а второго шанса у
    оклика почти нет: про конфликт он узнаёт либо чужим прогоном, либо
    расписанием, которое площадка исполняет 14 раз из 60 (реестр #270).
    """
    answers = ["unknown", "unknown", module.STATE_CONFLICT]
    asked: list[str] = []

    def fake(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        asked.append(path)
        return {"mergeable_state": answers[len(asked) - 1]}

    monkeypatch.setattr(module.ghrest, "request", fake)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module.merge_state("o/r", 7, "токен") == module.STATE_CONFLICT
    assert len(asked) == 3, f"ожидание не состоялось: спрошено {len(asked)} раз"


def test_a_state_that_never_comes_stays_unknown(monkeypatch: Any) -> None:
    """Не дождались — это по-прежнему «не знаю», а не «конфликта нет» (045).

    Округлить незнание до чистого значило бы промолчать там, где предмет есть.
    """
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: {"mergeable_state": "unknown"})
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module.merge_state("o/r", 7, "токен") in module.UNCOMPUTED


def test_a_ready_answer_is_not_asked_twice(monkeypatch: Any) -> None:
    """Готовый ответ берётся с первого раза: ожидание не цена по умолчанию."""
    asked: list[str] = []

    def fake(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        asked.append(path)
        return {"mergeable_state": "clean"}

    monkeypatch.setattr(module.ghrest, "request", fake)
    monkeypatch.setattr(module.time, "sleep", lambda _: pytest.fail("паузы быть не должно"))
    assert module.merge_state("o/r", 7, "токен") == "clean"
    assert len(asked) == 1


def test_the_wait_is_declared_not_endless() -> None:
    """Ожидание объявлено числами, а не «пока не ответит»."""
    assert module.WAIT_TRIES == 3, "число попыток разошлось с объявленным"
    assert module.WAIT_PAUSE == 2.0, "пауза разошлась с объявленной"
    assert module.WAIT_TRIES * module.WAIT_PAUSE <= 10, "ожидание держало бы обход"
