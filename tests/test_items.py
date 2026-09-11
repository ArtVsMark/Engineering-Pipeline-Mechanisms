"""Отметка пунктов задачи: один механизм на два основания.

Ставят её двое — шаг слияния по объявлению АВТОРА и разбор слитого по выводу
агента, — и работа у них одна: найти пункт в теле задачи и отметить, не
испортив уже отмеченного. Второе понимание того же разошлось бы с первым молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

Проверяется здесь именно эта общая работа: как пункт узнаётся, что происходит с
уже отмеченным, и чем отличается «пункта нигде нет» от «нашёлся, но не
записался». Оба состояния дают одинаковое бездействие и требуют разного.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

items = load_script("items.py")


def mark_change(body: str, *, dry_run: bool = False) -> Any:
    """Отмечает то, что объявило изменение с таким телом.

    Повторяет путь механизма: связи и пункты берутся из тела, а не задаются
    списком, — иначе проверялась бы не та дорога, по которой идёт заход.
    """
    numbers, wanted = items.declared_in(body)
    return items.mark("o/r", numbers, wanted, "token", dry_run=dry_run)


def test_a_declared_item_is_ticked_in_the_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пункт, названный закрытым, отмечается в теле задачи при слиянии.

    Момент единственный: раньше слияния это обещание, позже — уже история.
    """
    task = {"body": "- [ ] первый этап\n- [ ] второй этап\n"}
    written: list[dict[str, Any]] = []

    def platform(method: str, path: str, tok: str, body: Any = None) -> Any:
        if method == "GET":
            return task
        written.append(body)
        return {}

    monkeypatch.setattr(items.ghrest, "request", platform)
    item = "Refs #25\nЗакрывает пункт: второй этап"
    mark_change(item, dry_run=False)
    assert written and written[0]["body"] == "- [ ] первый этап\n- [x] второй этап"


def test_an_already_ticked_item_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный заход ничего не портит: отмеченное остаётся отмеченным."""
    task = {"body": "- [x] второй этап\n"}
    written: list[Any] = []
    monkeypatch.setattr(
        items.ghrest,
        "request",
        lambda method, path, tok, body=None: task if method == "GET" else written.append(body),
    )
    item = "Refs #25\nЗакрывает пункт: второй этап"
    mark_change(item, dry_run=False)
    assert written == [], "тело задачи переписано без нужды"


def test_an_item_that_matches_nothing_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ненайденный пункт называется вслух, а не теряется молча.

    «Отметил ноль из трёх» и «отметил всё» снаружи одинаковы (045).
    """
    monkeypatch.setattr(
        items.ghrest, "request", lambda method, path, tok, body=None: {"body": "- [ ] другой"}
    )
    item = "Refs #25\nЗакрывает пункт: которого нет"
    mark_change(item, dry_run=False)
    assert "пункт не найден" in capsys.readouterr().out


def test_a_declared_item_without_a_link_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пункт назван, а связи с задачей нет — отмечать негде, и это сказано."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("без связи задача читаться не должна")

    monkeypatch.setattr(items.ghrest, "request", refuse)
    mark_change("Закрывает пункт: сирота", dry_run=False)
    assert "отмечать негде" in capsys.readouterr().out


def test_a_refused_task_does_not_undo_the_merge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ площадки на отметке заход не роняет: изменение уже слито (084).

    Превращать это в красное значило бы объявить сломанным то, что сработало.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise items.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(items.ghrest, "request", refuse)
    mark_change("Refs #25\nЗакрывает пункт: этап", dry_run=False)
    assert "не отмечены" in capsys.readouterr().out


def test_a_dry_run_marks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пробный заход задачу не трогает."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("пробный заход не должен ходить на площадку")

    monkeypatch.setattr(items.ghrest, "request", refuse)
    mark_change("Refs #25\nЗакрывает пункт: этап", dry_run=True)


# --- метка присвоенного источника --------------------------------------------


def test_an_already_done_item_is_not_called_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Уже отмеченный пункт — повтор, а не пропажа.

    «Отметил» и «был отмечен» дают одинаковое тело задачи, а значат разное.
    Пока их различало сравнение тел, механизм звал на помощь там, где всё было
    в порядке (045).
    """
    monkeypatch.setattr(
        items.ghrest,
        "request",
        lambda method, path, tok, body=None: {"body": "- [x] второй этап\n"},
    )
    item = "Refs #25\nЗакрывает пункт: второй этап"
    mark_change(item, dry_run=False)
    assert "пункт не найден" not in capsys.readouterr().out


def test_a_failed_write_keeps_the_item_in_the_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пункт уходит из счёта только после удавшейся записи — и назван верно.

    Убрать его раньше значило бы объявить обработанным то, что не записалось:
    отказ на одной из нескольких задач тихо съел бы пункт, и он не попал бы ни
    в отметку, ни в отчёт.

    Но и «не найден» здесь неправда: пункт нашёлся, не записался. Одно слово на
    оба состояния отправило бы человека искать опечатку в формулировке, которой
    нет, — а повторить заход не подсказало бы (154).
    """

    def platform(method: str, path: str, tok: str, body: Any = None) -> Any:
        if method == "GET":
            return {"body": "- [ ] этап\n"}
        raise items.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(items.ghrest, "request", platform)
    item = "Refs #25\nЗакрывает пункт: этап"
    mark_change(item, dry_run=False)
    printed = capsys.readouterr().out
    assert "не отмечены" in printed
    assert "запись не удалась" in printed, "пункт исчез из счёта, хотя запись не удалась"
    assert "не найден" not in printed, "найденный пункт назван ненайденным"


def test_an_already_marked_item_survives_a_failed_neighbour(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ записи по одному пункту не превращает соседний в ненайденный.

    ЗАМЕР — находка ревью по #86. Пункт, отмеченный ещё прошлым заходом, записи
    не требует: он уже на месте. Общий счёт снимался только после удавшегося
    PATCH, поэтому отказ по СОСЕДНЕМУ пункту той же задачи уносил и его — и
    механизм звал на помощь там, где всё в порядке (045).
    """

    def platform(method: str, path: str, tok: str, body: Any = None) -> Any:
        if method == "GET":
            return {"body": "- [x] первый этап\n- [ ] второй этап\n"}
        raise items.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(items.ghrest, "request", platform)
    item = "Refs #25\nЗакрывает пункт: первый этап\nЗакрывает пункт: второй этап"
    mark_change(item, dry_run=False)
    printed = capsys.readouterr().out
    assert "не найден" not in printed, "уже отмеченный пункт объявлен ненайденным"
    assert "первый этап" not in printed, "пункт, который был на месте, попал в отчёт об отказе"
    assert "второй этап" in printed, "пункт, который не записался, из отчёта пропал"


# --- разметка не ждёт решения о заморозке -------------------------------------
#
# Замечено владельцем 10.09.2026: после движения общей ветки статусы должны
# пересчитываться у КАЖДОГО открытого изменения, и «определение красного main»
# этому не предшественник, а сосед — вычислять их независимо.


# --- догоняющий обход ---------------------------------------------------------
#
# Момент слияния — верный, но не единственный источник промаха: событие
# теряется, запись в задачу отказывает, а заход к тому времени закончился.
# Прежде такая потеря была молчаливой и окончательной: механизм печатал
# «пункты не отмечены» и забывал о них навсегда.


def platform(state: dict[str, Any]) -> Any:
    """Подделка площадки: список слитых и тела задач, которые она отдаёт."""

    def request(method: str, path: str, tok: str, body: Any = None) -> Any:
        if path.startswith("repos/o/r/pulls?"):
            return state["merged"]
        number = int(path.rsplit("/", 1)[-1])
        if method == "GET":
            return {"body": state["tasks"][number]}
        state["tasks"][number] = body["body"]
        state.setdefault("written", []).append(number)
        return {}

    return request


def test_the_sweep_marks_what_the_event_missed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обход отмечает объявленное в недавно слитых, даже если событие потерялось."""
    state: dict[str, Any] = {
        "merged": [
            {"number": 7, "merged_at": "2026-09-10", "body": "Refs #25\nЗакрывает пункт: этап"}
        ],
        "tasks": {25: "- [ ] этап\n"},
    }
    monkeypatch.setattr(items.ghrest, "request", platform(state))
    assert items.sweep("o/r", "token") == 1
    assert state["tasks"][25] == "- [x] этап"


def test_a_second_sweep_costs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный обход по тем же изменениям ничего не портит и не пишет.

    На этом обход и держится: отметка идемпотентна, а запись не отправляется
    вовсе, если тело задачи не изменилось. Иначе догоняющий заход переписывал
    бы задачи на каждом слиянии.
    """
    state: dict[str, Any] = {
        "merged": [
            {"number": 7, "merged_at": "2026-09-10", "body": "Refs #25\nЗакрывает пункт: этап"}
        ],
        "tasks": {25: "- [x] этап\n"},
    }
    monkeypatch.setattr(items.ghrest, "request", platform(state))
    items.sweep("o/r", "token")
    assert state.get("written") is None, "тело задачи переписано без нужды"


def test_the_sweep_ignores_changes_without_declarations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменение, ничего не объявившее, обход не трогает вовсе."""
    state: dict[str, Any] = {
        "merged": [{"number": 7, "merged_at": "2026-09-10", "body": "Refs #25\nбез объявлений"}],
        "tasks": {25: "- [ ] этап\n"},
    }
    monkeypatch.setattr(items.ghrest, "request", platform(state))
    assert items.sweep("o/r", "token") == 0
    assert state["tasks"][25] == "- [ ] этап\n"


def test_an_unmerged_change_is_not_swept(monkeypatch: pytest.MonkeyPatch) -> None:
    """Закрытое без слияния не отмечается: пункт сделанным не стал."""
    state: dict[str, Any] = {
        "merged": [{"number": 7, "merged_at": None, "body": "Refs #25\nЗакрывает пункт: этап"}],
        "tasks": {25: "- [ ] этап\n"},
    }
    monkeypatch.setattr(items.ghrest, "request", platform(state))
    assert items.sweep("o/r", "token") == 0


def test_an_orphaned_declaration_is_named_by_the_sweep(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пункт объявлен, а задачи нет — обход говорит об этом и называет изменение.

    Прежде такое объявление пропускалось по `not numbers` и исчезало молча —
    то есть ровно в том механизме, который заведён против молчаливых потерь
    (045). Нашёл это разбор слитого на #109.
    """
    state: dict[str, Any] = {
        "merged": [{"number": 7, "merged_at": "2026-09-10", "body": "Закрывает пункт: этап"}],
        "tasks": {},
    }
    monkeypatch.setattr(items.ghrest, "request", platform(state))
    assert items.sweep("o/r", "token") == 0
    said = capsys.readouterr().out
    assert items.NO_ADDRESS in said, said
    assert "#7" in said, "сказано об осиротевшем объявлении, но не сказано, чьём"


def test_the_window_is_one_for_everyone() -> None:
    """«Недавно слитое» у всех механизмов значит одно и то же.

    Копий запроса было три — здесь, у реестра непросмотренного и у находок, —
    и отличались они только окном (20 против 30), причём разница нигде не
    объяснялась. Общий помощник поднимают вверх, а не тянут вбок (090).
    """
    assert items.merged_changes is items.ghrest.merged_changes
    assert items.WINDOW == items.ghrest.MERGED_WINDOW


def test_an_epic_item_follows_the_task_it_names() -> None:
    """Пункт-ссылка отмечается, когда названная им задача закрыта."""
    body = "- [ ] **1. Решения** — #3 (родная очередь)\n- [ ] #14 — обратная связь"
    updated, done = items.followed(body, lambda number: number == 3)
    assert done == [3]
    assert updated.startswith("- [x] **1. Решения**")
    assert "- [ ] #14" in updated, "пункт открытой задачи отмечен зря"


def test_an_item_naming_two_tasks_is_left_alone() -> None:
    """Пункт с двумя ссылками не отмечается: вывести из них нечего.

    «Как в #52 и #3» говорит о своей работе, а задачи упомянуты. Отметить его
    по чужому закрытию значило бы соврать о сделанном (045).
    """
    body = "- [ ] как в #52 и #3 сразу"
    updated, done = items.followed(body, lambda number: True)
    assert done == []
    assert updated == body


def test_an_item_that_only_cites_a_task_is_not_that_task() -> None:
    """Ссылка внутри прозы — упоминание, а не тождество, и это стоило эпика.

    11.09.2026 три пункта эпика #196 встали отмеченными, не будучи сделанными:
    «Пересмотр решения #3», «Последний открытый пункт #39», «Половина #15» —
    все три задачи закрыты, и следование прочитало цитату как «пункт и есть
    эта задача». Образцы здесь — дословные, из того самого тела
    ([204](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/204-a-citation-is-checked-by-applicability.md)).
    """
    cited = [
        "**2. Слияние отдаётся площадке.** Пересмотр решения #3 — НОВОЙ записью в",
        "**5. Повторный взгляд по номеру слитого.** Последний открытый пункт #39:",
        "**6. Версия контракта дисциплинирует СЕБЯ.** Половина #15, обращённая",
    ]
    for text in cited:
        assert items.linked_item(text) is None, text
    body = "\n".join(f"- [ ] {one}" for one in cited)
    updated, done = items.followed(body, lambda number: True)
    assert done == []
    assert updated == body


def test_a_heading_does_not_hide_the_subject() -> None:
    """Пункт-ссылка узнаётся и под жирным номером: заголовок — не проза.

    `**1. Решения** — #3` называет задачу собой; заголовок лишь нумерует пункт
    внутри эпика. Отличать его от «Пересмотр решения #3» и есть работа образца.
    """
    assert items.names_a_task("**1. Решения** — #3 (родная очередь)")
    assert items.names_a_task("#14 — обратная связь")
    assert not items.names_a_task("Пересмотр решения #3")
    assert not items.names_a_task("**0. Цели.** Свести `docs/roadmap.md`")


def test_a_reference_inside_code_is_not_a_link() -> None:
    """Ссылка внутри инлайн-кода — текст, а не адрес задачи."""
    assert items.linked_item("правило `#42` в примере") is None


def test_following_never_unmarks() -> None:
    """Отметка не снимается: переоткрытая задача чаще значит новую работу.

    Механизм не выбирает за человека там, где знать неоткуда (154), а снятие
    отметки — потеря следа уже сделанного.
    """
    body = "- [x] #27 — классы проверок"
    updated, done = items.followed(body, lambda number: False)
    assert done == []
    assert updated == body


def test_the_epic_label_is_the_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Предмет следования сужен меткой: в обычной задаче `#N` может быть «см.».

    Проверяется именно запрос: без метки в него попали бы все задачи проекта,
    и «см. #52» отметилось бы как сделанное.
    """
    asked: list[str] = []

    def spy(method: str, path: str, token: str, data: Any = None) -> Any:
        asked.append(path)
        return []

    monkeypatch.setattr(items.ghrest, "request", spy)
    items.follow("o/r", "token", dry_run=True)
    assert any(f"labels={items.EPIC_LABEL}" in path for path in asked), asked


def test_a_dry_follow_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пробный заход называет находки и не пишет ни одной."""
    written: list[str] = []

    def spy(method: str, path: str, token: str, data: Any = None) -> Any:
        if method == "PATCH":
            written.append(path)
        if "labels=" in path:
            return [{"number": 2, "body": "- [ ] #27 — классы проверок"}]
        return {"state": "closed"}

    monkeypatch.setattr(items.ghrest, "request", spy)
    assert items.follow("o/r", "token", dry_run=True) == 0
    assert written == [], written


def test_one_unread_task_does_not_lose_the_others(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ по одной задаче не уносит отметки остальных пунктов эпика.

    Площадка спрашивается по разу на каждую названную задачу, и один отказ
    транспорта ронял бы заход целиком — вместе с уже сосчитанными пунктами.
    Незнание трактуется как «не закрыта»: неотмеченный пункт отметится
    следующим заходом, а отмеченный по ошибке снимет только человек. Нашёл
    внешний взгляд на #118.
    """
    epic = {"number": 2, "body": "- [ ] #7 первая\n- [ ] #8 вторая\n"}
    written: dict[str, object] = {}

    def request(method: str, path: str, *rest: object, **__: object) -> object:
        if "labels=" in path:
            return [epic]
        if "/issues/7" in path:
            raise items.ghrest.TransportError("площадка молчит")
        if "/issues/8" in path:
            return {"state": "closed"}
        if method == "PATCH":
            written["body"] = rest[1] if len(rest) > 1 else None
        return {}

    monkeypatch.setattr(items.ghrest, "request", request)
    items.follow("o/r", "token", dry_run=True)
    said = capsys.readouterr().out
    assert "#8" in said, said
    assert "не выведено" not in said, "отказ по одной задаче унёс весь эпик"
