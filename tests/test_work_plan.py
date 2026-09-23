"""План работ: зеркало источников 0–6 в одной живой задаче.

Механизм совещательный — слияния он не держит, — поэтому проверяется не
«краснеет ли он», а четыре свойства, каждое из которых уже стоило проекту
работы где-то ещё:

* **строка без адреса отвергается**: снять её было бы нечем (154);
* **ручные разделы переносятся дословно**: сочинённое за владельца — это
  потерянное указание владельца;
* **закрытый адрес уносит строку**: сделанное исчезает, а не копится
  зачёркнутым, — тем же приёмом, что у реестра находок;
* **молчание источника не выдаётся за пустоту** (045).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("work_plan.py")


BODY = """<!-- work-plan: не удаляйте -->

> **Читатель:** окно.

Шапка договора.

## 0 · Краснота общей ветки

**Пусто.**

## 4 · Прямое указание владельца

*У него есть предмет, которого механизм не знает.*

- **#640** — сборщик плана
- **#700** — это уже сделано

## 6 · План автора

- **#642** — инвентарь переносимого
- `abc1234` · #635 — находка, ещё не разобранная

---

**Собрано:** вчера, рукой.
"""


def open_issues(closed: set[int]) -> Any:
    """Площадка, отвечающая по номеру задачи «открыта» либо «закрыта»."""

    def request(_method: str, path: str, *_rest: Any, **_kw: Any) -> dict[str, Any]:
        number = int(path.rsplit("/", 1)[-1])
        return {"state": "closed" if number in closed else "open"}

    return request


def test_a_row_carries_its_address_and_the_first_one_is_the_subject() -> None:
    """Адрес строки — ПЕРВЫЙ номер либо отпечаток, а не любой упомянутый.

    Строка плана называет соседей по делу: «#547 — это то, что #642 описывает».
    Снимать её обязано закрытие 547, а не 642, — иначе работа исчезала бы из
    плана раньше, чем сделана
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    assert module.address_of("- **#547** — это то, что #642 описывает") == "#547"
    assert module.address_of("- `abc1234` · #635 — находка") == "abc1234"
    assert module.address_of("- переделать бы доки") == ""


def test_a_row_without_an_address_refuses_the_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Строка без адреса — отказ сборки, а не строка.

    Снимает строку закрытая задача или ушедшая находка. Безадресную прозу
    снять нечем: она осталась бы в плане навсегда, и план стал бы списком
    желаний, который нечем закрыть
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    monkeypatch.setattr(module.ghrest, "request", open_issues(set()))
    said = BODY.replace("- **#700** — это уже сделано", "- переделать бы доки")
    with pytest.raises(module.NotRun) as beda:
        module.held_rows(said, 4, "o/r", "t", set())
    assert "без адреса" in str(beda.value)


def test_a_closed_address_takes_its_row_away(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сделанное ИСЧЕЗАЕТ, а не лежит зачёркнутым.

    Галочка копит историю там, где нужен остаток: план из двадцати строк, где
    восемнадцать зачёркнуты, перестаёт отвечать на вопрос «чем заняться». След
    не теряется — он в источнике и в слитом изменении, которое строку сняло.
    """
    monkeypatch.setattr(module.ghrest, "request", open_issues({700}))
    kept = module.held_rows(BODY, 4, "o/r", "t", set())
    assert any("#640" in one for one in kept), "живая строка пропала"
    assert not any("#700" in one for one in kept), "закрытая строка осталась"


def test_a_finding_leaves_when_the_registry_lets_it_go(monkeypatch: pytest.MonkeyPatch) -> None:
    """Строку-находку снимает реестр, а не задача.

    У находки адрес — отпечаток, и живёт она в #23. Спрашивать о ней площадку
    было бы вторым источником правды о том же (022).
    """
    monkeypatch.setattr(module.ghrest, "request", open_issues(set()))
    kept = module.held_rows(BODY, 6, "o/r", "t", {"abc1234"})
    assert any("abc1234" in one for one in kept), "неразобранная находка пропала"
    gone = module.held_rows(BODY, 6, "o/r", "t", set())
    assert not any("abc1234" in one for one in gone), "разобранная находка осталась"


def test_the_owner_section_is_carried_word_for_word(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ручной раздел переносится дословно, а не пересказывается.

    Разделы 4 и 6 — предмет, которого механизм не знает. Сочинить их заново
    значило бы потерять указание владельца, ради которого раздел и заведён.
    """
    monkeypatch.setattr(module.ghrest, "request", open_issues(set()))
    kept = module.held_rows(BODY, 4, "o/r", "t", set())
    assert "*У него есть предмет, которого механизм не знает.*" in kept
    assert "- **#640** — сборщик плана" in kept


def test_the_footer_is_not_read_as_a_row() -> None:
    """Подвал плана строкой раздела не считается: раздел кончается чертой.

    Без этой границы механизм сохранял бы дословно собственную прошлую
    подпись — включая «механизма сборки ещё нет» — и подпись пережила бы сам
    механизм ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
    """
    rows = module.rows_of(BODY, module.HEADS[6])
    assert not any("Собрано" in one for one in rows), rows
    assert any("#642" in one for one in rows)


def test_a_silent_source_is_not_an_empty_one() -> None:
    """Непрочитанный источник говорит об этом, а не показывает «Пусто».

    Пустота и молчание снаружи неотличимы, а значат разное: по первому работу
    не берут, по второму — идут спрашивать канал
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    quiet = "\n".join(module.render(3, module.Source(unread="реестр не ответил")))
    empty = "\n".join(module.render(3, module.Source()))
    assert "Не спрошено" in quiet and "Пусто" not in quiet
    assert "**Пусто** на " in empty
    assert quiet != empty


def test_the_sections_come_out_in_the_order_of_the_contract() -> None:
    """Разделы идут 0→6, потому что порядок и есть правило (091).

    План, в котором источники переставлены, отвечает на вопрос «чем заняться»
    неверно — а больше он ни на что не отвечает.
    """
    said = module.assemble(BODY, {one: module.Source() for one in module.BUILT}, {}, "01.01.2026")
    places = [said.index(f"## {module.HEADS[one]}") for one in sorted(module.HEADS)]
    assert places == sorted(places), said


def quiet_platform(monkeypatch: pytest.MonkeyPatch, *, body: str = BODY) -> list[str]:
    """Площадка, отвечающая по всем источникам, — и лист записанного."""
    written: list[str] = []

    def patched(method: str, path: str, *rest: Any, **_kw: Any) -> dict[str, Any]:
        if method == "PATCH":
            written.append(str(rest[1].get("body") if len(rest) > 1 else ""))
            return {}
        return {"state": "open"}

    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "request", patched)
    monkeypatch.setattr(module.findings, "live_issue", lambda *_, **__: (639, body))
    # Задачи дрейфа нет: дрейф не заводит пустую, и это «пусто», а не отказ.
    monkeypatch.setattr(module.findings, "live_issue_seen", lambda *_, **__: (None, "", ""))
    monkeypatch.setattr(module.debt, "branch_debt", lambda *_: ([], []))
    monkeypatch.setattr(module.debt, "stuck_changes", lambda *_: ([], [], []))
    monkeypatch.setattr(module.debt, "findings_debt", lambda *_: [])
    monkeypatch.setattr(module.debt, "closed_issues", lambda *_: [])
    monkeypatch.setattr(module.debt, "inbox_body", lambda *_: ("", "", ""))
    monkeypatch.setattr(module.debt, "rules_debt", lambda _: (0, 0, 0))
    monkeypatch.setattr(module.debt, "contract_note", lambda _: None)
    return written


def test_a_read_plan_is_assembled_and_written(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все источники ответили — план собран и записан (исход 0)."""
    written = quiet_platform(monkeypatch)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert written and "## 0 · Краснота общей ветки" in written[0]


def test_a_silent_source_lowers_the_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Источник промолчал — исход 3, а не «план собран».

    Частичный ответ, выданный за полный, — это тихий запасной путь: план
    выглядел бы законченным, не будучи им
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    quiet_platform(monkeypatch)

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("канал молчит")

    monkeypatch.setattr(module.debt, "branch_debt", refuse)
    assert module.main(["--repo", "o/r"]) == module.EXIT_PARTIAL


def test_no_living_plan_is_a_refusal_not_an_empty_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живой задачи плана нет — отказ, а не пустой план.

    Завести её механизм не берётся: живая задача — это адресат, и заводить
    адресата за человека значило бы решать, где он будет смотреть
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    quiet_platform(monkeypatch)
    monkeypatch.setattr(module.findings, "live_issue", lambda *_, **__: (None, ""))
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN


def test_without_a_token_the_plan_is_not_invented(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет токена — исход 3: источники не спрошены, а не пусты."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r"]) == module.EXIT_PARTIAL


def test_an_address_is_asked_of_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Судьбу задачи спрашивают у площадки, а у реестра — судьбу находки.

    Тело плана пишет тот же механизм; спрашивать его о судьбе работы значило бы
    спрашивать себя
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    """
    monkeypatch.setattr(module.ghrest, "request", open_issues({700}))
    assert module.still_open("#640", "o/r", "t", set())
    assert not module.still_open("#700", "o/r", "t", set())
    assert module.still_open("abc1234", "o/r", "t", {"abc1234"})
    assert not module.still_open("abc1234", "o/r", "t", set())


def test_an_empty_section_says_the_day_it_was_looked_at() -> None:
    """Пустой раздел несёт день обхода, иначе застывший план от пустого неотличим."""
    said = "\n".join(module.render(0, module.Source(), "01.01.2026"))
    assert "**Пусто** на 01.01.2026." in said


def test_a_silent_neighbour_does_not_make_a_section_look_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ одного канала источника не выдаётся за прочитанный источник.

    Источник 3 складывается из ДВУХ каналов: реестра находок и задачи о
    красноте (совещательное, пережившее слияние). Пока отказ второго доходил
    только до источника 0, третий получал пустой список и выглядел полным —
    механизм нарушал инвариант, который объявляет о себе сам
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд на #651.
    """
    quiet_platform(monkeypatch)

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("задача о красноте молчит")

    monkeypatch.setattr(module.debt, "branch_debt", refuse)
    monkeypatch.setattr(module.debt, "findings_debt", lambda *_: [("abc1234", 635, "находка")])
    built, broken, _ = module.sources("o/r", "t")
    said = "\n".join(module.render(3, built[3], "01.01.2026"))
    assert "abc1234" in said, "прочитанная половина источника пропала"
    assert "Не спрошено" in said, "непрочитанная половина выдана за прочитанную"
    assert "3" in broken, "молчащий источник не назван в исходе"


def test_the_registry_is_read_once_per_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Реестр находок читается ОДИН раз за заход.

    Отпечатки нужны и разделу 3, и снятию строк ручных разделов. Второе чтение
    того же стоило бы вызова из общей квоты и разошлось бы с первым молча,
    изменись реестр между ними
    ([058](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/058-when-the-quota-is-out-stop.md),
    [022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    Нашёл внешний взгляд на #651.
    """
    quiet_platform(monkeypatch)
    asked: list[int] = []

    def counted(*_: Any, **__: Any) -> list[tuple[str, int, str]]:
        asked.append(1)
        return []

    monkeypatch.setattr(module.debt, "findings_debt", counted)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert len(asked) == 1, f"реестр прочитан {len(asked)} раза за один заход"


def test_a_silent_registry_does_not_erase_what_was_already_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Непрочитанный канал не вытесняет прочитанный — и в эту сторону тоже.

    Дефект был симметричным, и первая починка закрыла только одну его половину:
    сперва непрочитанное выдавалось за пустоту, а в обратную сторону
    непрочитанное ВЫТЕСНЯЛО уже прочитанное — ветка отказа заводила раздел
    заново и выбрасывала строки соседнего канала. Нашёл внешний взгляд на #652.

    Ровно тот инвариант, который объявляет докстрока `Source`: отказ одного
    канала не делает пустым другой
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    quiet_platform(monkeypatch)

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("реестр молчит")

    monkeypatch.setattr(module.debt, "branch_debt", lambda *_: ([], ["test-next (3.15)"]))
    monkeypatch.setattr(module.debt, "findings_debt", refuse)
    built, broken, marks = module.sources("o/r", "t")
    said = "\n".join(module.render(3, built[3], "01.01.2026"))
    assert "test-next (3.15)" in said, "прочитанная половина источника выброшена"
    assert "Не спрошено" in said, "молчание реестра не названо"
    assert "3" in broken
    assert marks == set(), "отпечатки взялись ниоткуда при молчащем реестре"


def drift_issue(found: list[Any], silent: list[str], seen: str = "2026-09-23T07:43:00Z") -> Any:
    """Живая задача дрейфа в том виде, в каком её пишет сам дрейф."""
    body = module.drift.render_body(found, silent)
    return lambda *_, **__: (193, body, seen)


def test_drift_records_land_in_section_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """Записи дрейфа — строки раздела 5 с адресом задачи дрейфа.

    Договор называет дрейф частью источника 5 (`docs/behaviour.md`, контур
    1), а сборщик его не читал: раздел выглядел полным, когда дрейф называл бы
    работу. Нашёл владелец вопросом по #665.

    Тело задачи строит ЗДЕСЬ сам дрейф (`render_body`): разбор проверяется на
    форме, которую пишет механизм, а не на переписанной рукой копии.
    """
    quiet_platform(monkeypatch)
    moved = module.drift.Drift("action-behind", "actions/setup-python: v5, выпущен v7", "поднять")
    monkeypatch.setattr(module.findings, "live_issue_seen", drift_issue([moved], ["сводка семьи"]))
    built, broken, _ = module.sources("o/r", "t")
    assert broken == []
    assert built[5].rows == ["#193 · `action-behind` — actions/setup-python: v5, выпущен v7"]
    assert "дрейф не спросил: сводка семьи" in built[5].note


def test_a_silent_drift_does_not_erase_the_rules_half(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача дрейфа не прочиталась — половина о правилах остаётся, отказ назван.

    Тот же урок, что у источника 3 (#651): прочитанная половина не вытесняет
    непрочитанную, а непрочитанная — прочитанную.
    """
    quiet_platform(monkeypatch)
    monkeypatch.setattr(module.debt, "rules_debt", lambda _: (0, 4, 0))

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("502")

    monkeypatch.setattr(module.findings, "live_issue_seen", refuse)
    built, broken, _ = module.sources("o/r", "t")
    assert built[5].rows == ["правил без ответа: **4**"]
    assert "задача дрейфа не прочитана" in built[5].unread
    assert "5" in broken


def test_a_late_drift_names_its_own_night_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задачу дрейфа давно не переписывали — называется пропуск ДРЕЙФА, а не каталога."""
    quiet_platform(monkeypatch)
    monkeypatch.setattr(
        module.findings, "live_issue_seen", drift_issue([], [], seen="2020-01-01T00:00:00Z")
    )
    built, _, _ = module.sources("o/r", "t")
    assert module.DRIFT_LATE in built[5].note
    assert "каталога" not in built[5].note.split("обход дрейфа", 1)[1]


def test_no_drift_issue_is_emptiness_not_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задачи дрейфа нет — половина источника 5 пуста, а не молчит.

    Дрейф не заводит пустую задачу (`drift.save`): её отсутствие значит
    «записей не было ни разу», и называть это отказом значило бы красить
    исход сборщика по состоянию, которое исправно.
    """
    monkeypatch.setattr(module.findings, "live_issue_seen", lambda *_, **__: (None, "", ""))
    assert module.drift_part("o/r", "t") == module.Source()


def test_rules_half_without_numbers_is_named_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Входящие» прочитаны, а чисел в них нет — половина называет это, а не пустоту."""
    monkeypatch.setattr(module.debt, "closed_issues", lambda *_: [])
    monkeypatch.setattr(module.debt, "inbox_body", lambda *_: ("", "", ""))
    monkeypatch.setattr(module.debt, "rules_debt", lambda _: None)
    said = module.rules_part("o/r", "t")
    assert said.rows == [] and "числа каталога не найдены" in said.unread
