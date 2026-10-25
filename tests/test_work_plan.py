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

import ast
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

module = load_script("work_plan.py")
findings = load_script("findings.py")


BODY = (
    module.MARKER
    + """

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
)


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
    rows = module.section_rows(BODY, 6)
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
    assert "Не прочитано" in quiet and "Пусто" not in quiet
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
    # Список открытых пустым не бывает: в нём всегда есть хотя бы сам план, а
    # пустой ответ читатель перечитывает и отвергает (#1580).
    # Подставленный тестом `paginate` по-прежнему читается — к нему лишь
    # добавляется план, когда тест открытых записей не дал.
    monkeypatch.setattr(
        module.findings,
        "open_listed",
        lambda repo, token: (
            list(module.ghrest.paginate(f"repos/{repo}/issues?state=open", token))
            or [{"number": 639, "title": "План", "body": ""}]
        ),
    )
    monkeypatch.setattr(module.debt, "branch_debt", lambda *_: ([], []))
    monkeypatch.setattr(module.debt, "stuck_changes", lambda *_: ([], [], []))
    monkeypatch.setattr(module.debt, "findings_debt", lambda *_: [])
    monkeypatch.setattr(module.debt, "open_changes", lambda *_: frozenset())
    monkeypatch.setattr(module.debt, "closed_issues", lambda *_: [])
    monkeypatch.setattr(module.debt, "inbox_body", lambda *_: ("", "", ""))
    monkeypatch.setattr(module.debt, "rules_debt", lambda _: (0, 0, 0))
    monkeypatch.setattr(module.debt, "contract_note", lambda _: None)
    # Поводы для правила читаются из дерева, а не с площадки: гасятся здесь,
    # чтобы проверки источников не зависели от сегодняшнего словаря родов.
    monkeypatch.setattr(module, "birth_part", lambda *_: module.Source())
    # Рождённых работой задач нет: пополнение раздела 4 проверяется отдельно.
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([]))
    return written


def test_a_read_plan_is_assembled_and_written(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все источники ответили — план собран и записан (исход 0)."""
    written = quiet_platform(monkeypatch)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert written and f"## {module.HEADS[0]}" in written[0]


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


def test_an_unsaid_merge_state_is_unread_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Несказанное слияние — раздел 1 прочитан не весь и исход 3, а не «Пусто» (взгляд на #1267).

    Шаг долга тем же предметом выходит исходом 3; план, державший его
    заметкой, печатал раздел пустым — два механизма расходились (195).
    """
    quiet_platform(monkeypatch)
    monkeypatch.setattr(module.debt, "stuck_changes", lambda *_: ([], ["#6 — работа"], []))
    built, broken, _ = module.sources("o/r", "t")
    assert "#6 — работа" in built[1].unread and not built[1].note
    # Причину несёт строка изменения, а не заголовок: «площадка ещё считает»
    # лгало, когда ждать не стали (взгляд на #1306).
    assert "ещё считает" not in built[1].unread
    assert "1" in broken
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
    monkeypatch.setattr(
        module.debt, "findings_debt", lambda *_: [("abc1234", 635, "дефект", "находка")]
    )
    built, broken, _ = module.sources("o/r", "t")
    said = "\n".join(module.render(3, built[3], "01.01.2026"))
    assert "abc1234" in said, "прочитанная половина источника пропала"
    assert "Не прочитано" in said, "непрочитанная половина выдана за прочитанную"
    assert "3" in broken, "молчащий источник не назван в исходе"


def test_an_empty_open_list_is_a_refusal_not_nothing_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой список открытых — «не прочитаны», а не «открытых нет» (#1580, находка `8d1f790`).

    `quiet_platform` подменяет `findings.open_listed` целиком, и поведение
    настоящего читателя не держал ни один тест: откат строки, где сборщик зовёт
    его, ничего не краснил. Здесь читатель настоящий, площадка отвечает пустым
    списком на каждой попытке — находки остаются долгом, и слепота названа.
    """
    real = module.findings.open_listed
    quiet_platform(monkeypatch)
    # Пустой ответ на каждой попытке: `quiet_platform` уже гасит `paginate`.
    monkeypatch.setattr(module.findings, "open_listed", real)
    monkeypatch.setattr(module.findings, "OPEN_PAUSE", 0)
    monkeypatch.setattr(
        module.debt, "findings_debt", lambda *_: [("abc1234", 635, "дефект", "находка")]
    )
    built, _, _ = module.sources("o/r", "t")
    said = "\n".join(module.render(3, built[3], "01.01.2026"))
    assert "abc1234" in said, "находка пропала вместо того, чтобы остаться долгом"
    assert "открытые изменения не прочитаны" in said, said


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

    def counted(*_: Any, **__: Any) -> list[tuple[str, int, str, str]]:
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
    assert "Не прочитано" in said, "молчание реестра не названо"
    assert "3" in broken
    assert marks == set(), "отпечатки взялись ниоткуда при молчащем реестре"


def drift_issue(found: list[Any], silent: list[str], seen: str = "2026-09-23T07:43:00Z") -> Any:
    """Живая задача дрейфа в том виде, в каком её пишет сам дрейф."""
    body = module.drift.render_body(found, silent)
    return lambda *_, **__: (193, body, seen)


def test_drift_records_land_in_section_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """Записи дрейфа — строки раздела 5 с адресом задачи дрейфа.

    Договор называет дрейф частью источника 5 (`docs/agent/behaviour.md`, контур
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


def test_an_owner_edit_during_the_pass_is_not_overwritten(monkeypatch: pytest.MonkeyPatch) -> None:
    """Владелец правит раздел 4, пока идёт заход, — его правка доходит до записи.

    ЗАМЕР 23.09.2026: владелец поставил #673 первым в раздел 4, а заход,
    прочитавший тело ДО правки, записал его ПОСЛЕ — и указание пропало молча.
    Здесь первое чтение отдаёт прежнее тело, а все следующие — поправленное:
    сборщик обязан заметить расхождение и собрать заново.
    """
    edited = BODY.replace(
        "- **#640** — сборщик плана\n",
        "- **#673** — первым, по слову владельца\n- **#640** — сборщик плана\n",
    )
    written = quiet_platform(monkeypatch)
    reads = iter([BODY])
    monkeypatch.setattr(module.findings, "live_issue", lambda *_, **__: (639, next(reads, edited)))
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert len(written) == 1
    section = written[0].split("## 4", 1)[1].split("## 5", 1)[0]
    assert section.index("#673") < section.index("#640"), section


def test_a_plan_edited_all_the_time_is_not_written_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """Рука правит план на каждом заходе — сборщик отказывает, а не пишет поверх."""
    written = quiet_platform(monkeypatch)
    counter = iter(range(100))
    monkeypatch.setattr(
        module.findings,
        "live_issue",
        lambda *_, **__: (
            639,
            BODY.replace("сборщик плана", f"сборщик плана, правка {next(counter)}"),
        ),
    )
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_BROKEN
    # Пишется только блок отказа поверх свежего тела (#1621): правка руки на месте.
    assert len(written) == 1 and module.REFUSAL_OPEN in written[0], written
    assert "сборщик плана, правка" in written[0], "блок отказа стёр правку руки"


def test_the_hand_part_is_the_head_and_the_owner_sections() -> None:
    """Рукой пишутся шапка и разделы 4 и 6; собранные разделы в сверку не входят."""
    said = module.hand_part(BODY)
    assert said[0].startswith(module.MARKER)
    assert "- **#640** — сборщик плана" in said and "- **#642** — инвентарь переносимого" in said
    assert "**Пусто.**" not in said


def test_a_dry_run_reads_the_body_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без записи сверять нечего: `fresh_build` читает тело один раз и отдаёт сборку."""
    quiet_platform(monkeypatch)
    reads: list[int] = []

    def counted(*_: Any, **__: Any) -> tuple[int, str]:
        reads.append(1)
        return 639, BODY

    monkeypatch.setattr(module.findings, "live_issue", counted)
    built = {one: module.Source() for one in module.BUILT}
    number, body, _held, said = module.fresh_build("o/r", "t", built, set(), "01.01.2026", False)
    assert (number, body) == (639, BODY) and "## 4" in said
    assert len(reads) == 1


automerge = load_script("automerge.py")


def test_the_plan_and_the_queue_count_sources_alike() -> None:
    """Разделы плана и ступени очереди нумеруются одним счётом источников 0–6.

    Ответ каталогу по 053 называет это «одним словарём на оба контура», а
    держалось оно дисциплиной: два литерала в двух файлах. Нашёл внешний
    взгляд на #681 (`b4d549d`). Подписи у разделов и ступеней свои — по
    предмету, — а номер один: работа до изменения и изменение в очереди
    стоят на одной ступени.
    """
    assert sorted(module.HEADS) == sorted(automerge.RANK_NAMES) == list(range(7))
    for number in module.HEADS:
        assert module.HEADS[number].startswith(f"{number} ·"), module.HEADS[number]
        assert automerge.RANK_NAMES[number].startswith(f"{number} ·"), automerge.RANK_NAMES[number]


@pytest.fixture(autouse=True)
def no_trunk_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Раздел поводов считает встречи по подделкам, а не по истории дерева набора (#1022)."""
    monkeypatch.setattr(module.trunk_log, "merged_bodies", lambda *_, **__: [])
    monkeypatch.setattr(module.trunk_log, "unseen", lambda *_, **__: 0)


def kinds_file(tmp_path: Any, kinds: dict[str, Any]) -> Any:
    """Словарь родов находок в той форме, в какой его ведёт дерево."""
    path = tmp_path / "finding-kinds.json"
    path.write_text(json.dumps({"kinds": kinds}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "proposals.json").write_text('{"proposals": []}', encoding="utf-8")
    (tmp_path / "bindings.json").write_text('{"rules": {"206": {}}}', encoding="utf-8")
    return path


def test_a_kind_at_the_threshold_without_an_answer_is_plan_work(tmp_path: Any) -> None:
    """Род у порога без ответа каталогу — строка раздела 5; с ответом или ниже порога — нет.

    Замер 23.09.2026 (#650): родов у порога восемь, все держатся механизмами,
    и ни у одного нет ответа каталогу — поводы для правила оставались без
    вопроса.
    """
    met = ["a", "b", "c"]
    path = kinds_file(
        tmp_path,
        {
            "без ответа": {"признак": "x", "встречен": met, "закрыт": "гейт"},
            "с ответом": {
                "признак": "x",
                "встречен": met,
                "закрыт": "гейт",
                "каталогу": "есть — 206",
            },
            "ниже порога": {"признак": "x", "встречен": ["a"], "закрыт": "нет — один случай"},
        },
    )
    said = module.birth_part(path)
    assert said.rows == ["род находок у порога без ответа каталогу: «без ответа» — встреч 3"]


def test_kind_lines_of_the_history_count_towards_the_threshold(tmp_path: Any) -> None:
    """Встречи строками `Род:` истории доводят род до порога и в плане (#1022).

    Словарь заморожен, и счёт по нему одному отставал бы от гейта рождения
    правила: род у порога по истории без ответа каталогу из плана выпадал бы.
    """
    path = kinds_file(tmp_path, {"род": {"признак": "x", "встречен": ["a", "b"], "закрыт": "гейт"}})
    assert module.birth_part(path, []).rows == []
    said = module.birth_part(path, ["Разобрано: aaaaaaa\nРод: род"])
    assert said.rows == ["род находок у порога без ответа каталогу: «род» — встреч 3"]


def test_merges_without_squash_are_named_in_the_section(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Слияния без уплотнения раздел называет пометкой, а не молчит (045, взгляд на #1086)."""
    monkeypatch.setattr(module.trunk_log, "unseen", lambda *_, **__: 17)
    path = kinds_file(tmp_path, {"род": {"признак": "x", "встречен": ["a"], "закрыт": "гейт"}})
    assert module.birth_part(path).note == f"{module.finding_kinds.UNSEEN_SAID} 17"


def test_an_unreadable_history_is_named_silence(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """История не прочитана — раздел молчит, а не считает по одному словарю (045)."""

    def refuse(*_: object, **__: object) -> list[str]:
        raise module.trunk_log.NotRun(module.trunk_log.SHALLOW)

    monkeypatch.setattr(module.trunk_log, "merged_bodies", refuse)
    path = kinds_file(tmp_path, {"род": {"признак": "x", "встречен": ["a"], "закрыт": "гейт"}})
    said = module.birth_part(path)
    assert said.rows == [] and module.trunk_log.SHALLOW in said.unread


def test_a_dry_run_names_the_plan_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Сухой заход печатает номер плана: навык отсылает за ним сюда (`5a0aac6`)."""
    written = quiet_platform(monkeypatch)
    assert module.main(["--repo", "o/r"]) == module.EXIT_OK
    assert written == []
    assert "план #639 — собрал бы так:" in capsys.readouterr().out


def test_no_kinds_file_is_named_silence_not_emptiness(tmp_path: Any) -> None:
    """Словаря родов нет — раздел называет молчание, а не «поводов нет» (`13f3a9d`).

    У плана словарь есть всегда; запуск не из корня прежде давал пустой
    раздел, неотличимый от настоящей пустоты.
    """
    said = module.birth_part(tmp_path / "нет.json")
    assert said.rows == [] and "роды находок не прочитаны" in said.unread


def test_no_queue_is_named_silence_not_unanswered_kinds(tmp_path: Any) -> None:
    """Очереди нет — молчание, а не «без ответа» у каждого «предложено» (`dd1da87`)."""
    path = kinds_file(
        tmp_path,
        {"род": {"встречен": ["a", "b", "c"], "каталогу": "предложено — sent"}},
    )
    (tmp_path / "proposals.json").unlink()
    said = module.birth_part(path)
    assert said.rows == [] and "очередь предложений не прочитана" in said.unread


def test_kinds_of_a_foreign_shape_are_named_silence(tmp_path: Any) -> None:
    """Раздел kinds строкой — молчание раздела, а не трасса сборщика (`19fe125`)."""
    path = tmp_path / "finding-kinds.json"
    path.write_text('{"kinds": "x"}', encoding="utf-8")
    said = module.birth_part(path)
    assert said.rows == [] and "раздел kinds не словарь" in said.unread


def test_an_unsent_proposal_keeps_the_kind_in_the_plan(tmp_path: Any) -> None:
    """Ответ «предложено» со слагом вне очереди — не ответ: род остаётся в плане (`72397b3`)."""
    path = kinds_file(
        tmp_path,
        {"род": {"встречен": ["a", "b", "c"], "каталогу": "предложено — not-sent-yet"}},
    )
    (tmp_path / "proposals.json").write_text('{"proposals": []}', encoding="utf-8")
    assert len(module.birth_part(path).rows) == 1
    (tmp_path / "proposals.json").write_text(
        '{"proposals": [{"slug": "not-sent-yet"}]}', encoding="utf-8"
    )
    assert module.birth_part(path).rows == []


def born_platform(
    issues: list[dict[str, Any]], subs: dict[int, list[dict[str, Any]]]
) -> tuple[Any, list[str]]:
    """Площадка со списком открытых задач и подзадачами — и лист запросов."""
    asked: list[str] = []

    def paginate(path: str, *_rest: Any, **_kw: Any) -> Any:
        asked.append(path)
        if path.endswith("/sub_issues"):
            return iter(subs.get(int(path.split("/")[-2]), []))
        # Список `?state=open` несёт поле состояния у каждой задачи — как
        # площадка: без него задача теперь не рождается (взгляд на #756).
        return iter({"state": "open", **one} for one in issues)

    return paginate, asked


#: Хранилище стенда и чужое — подзадача несёт адрес своего хранилища.
HOME: Final = "https://api.github.com/repos/o/r"
ELSEWHERE: Final = "https://api.github.com/repos/other/r"


HELD_ROWS: dict[int, list[str]] = {
    4: ["*У него есть предмет.*", "", "- **#640** — сборщик плана"],
    6: ["- **#642** — инвентарь переносимого", "- `abc1234` · #635 — находка"],
}


def test_a_task_born_in_the_work_joins_section_four(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача, связанная со строкой раздела 4 или 6, встаёт в раздел 4 (#747).

    Связь — телом (`Refs #642`) или подзадачей (#640). Не встают: уже стоящая
    в плане (в том числе в собранном разделе), ссылающаяся только на план или
    реестр, изменение, закрытая подзадача, подзадача чужого хранилища, живая
    задача механизма со связью в теле и ссылка на номер из строки-находки
    (взгляд на #750).
    """
    paginate, _ = born_platform(
        [
            {"number": 750, "title": "дыра инвентаря", "body": "Нашлось.\n\nRefs #642"},
            {"number": 642, "title": "инвентарь", "body": "Refs #640"},
            {"number": 752, "title": "чужая", "body": "Refs #639\nRefs #23"},
            {"number": 753, "title": "изменение", "body": "Refs #642", "pull_request": {}},
            {"number": 755, "title": "реестр", "body": f"{module.findings.marker('x')}\nrefs #642"},
            {"number": 756, "title": "план", "body": f"{module.MARKER}\nRefs #642"},
            {"number": 757, "title": "по находке", "body": "Refs #635"},
            {"number": 758, "title": "уже в разделе 5", "body": "Refs #642"},
        ],
        {
            640: [
                {
                    "number": 751,
                    "title": "подзадача сборщика",
                    "state": "open",
                    "repository_url": HOME,
                },
                {"number": 754, "title": "сделанная", "state": "closed", "repository_url": HOME},
                {"number": 759, "title": "чужая", "state": "open", "repository_url": ELSEWHERE},
                {
                    "number": 758,
                    "title": "уже в разделе 5",
                    "state": "open",
                    "repository_url": HOME,
                },
                {
                    "number": 760,
                    "title": "реестр подзадачей",
                    "state": "open",
                    "repository_url": HOME,
                    "body": module.findings.marker("x"),
                },
                {
                    "number": 761,
                    "title": "своя в другом регистре",
                    "state": "open",
                    "repository_url": "https://api.github.com/repos/O/R",
                },
            ]
        },
    )
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    assert module.born_rows("o/r", "t", HELD_ROWS, frozenset({758})) == [
        f"- **#750** — дыра инвентаря *({module.BORN_TAIL} #642)*",
        f"- **#751** — подзадача сборщика *({module.BORN_TAIL} #640)*",
        f"- **#761** — своя в другом регистре *({module.BORN_TAIL} #640)*",
    ]


def test_without_rows_nothing_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустые ручные разделы — родителей нет, и площадку не спрашивают."""
    paginate, asked = born_platform([{"number": 750, "title": "x", "body": "Refs #642"}], {})
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    assert module.born_rows("o/r", "t", {4: ["*курсив*"], 6: []}) == []
    assert asked == []


def test_a_born_task_lands_at_the_end_of_section_four(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сквозь сборку: рождённая задача — последней строкой раздела 4, раздел 6 цел."""
    written = quiet_platform(monkeypatch)
    paginate, _ = born_platform([{"number": 750, "title": "дыра", "body": "Refs #642"}], {})
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    four = module.rows_of(written[0], module.HEADS[4])
    assert four[-1] == f"- **#750** — дыра *({module.BORN_TAIL} #642)*"
    assert "#750" not in "\n".join(module.rows_of(written[0], module.HEADS[6]))


def test_a_task_already_in_a_built_section_is_not_born_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Задача, стоящая в собранном разделе, в раздел 4 не встаёт (`365d40a`)."""
    written = quiet_platform(monkeypatch)
    built = {one: module.Source() for one in module.BUILT}
    built[5] = module.Source(rows=["**#750** — задача по правилу"])
    monkeypatch.setattr(module, "sources", lambda *_: (built, [], set()))
    paginate, _ = born_platform([{"number": 750, "title": "дыра", "body": "Refs #642"}], {})
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert "#750" not in "\n".join(module.rows_of(written[0], module.HEADS[4]))


def test_both_ways_of_birth_share_one_gate() -> None:
    """Связь телом и подзадача проходят одну проверку кандидата (взгляд на #754)."""
    own = {"number": 761, "state": "open", "repository_url": "https://api.github.com/repos/O/R"}
    assert module.may_be_born(own, "o/r", set()) is True
    assert module.may_be_born({**own, "body": module.MARKER}, "o/r", set()) is False
    assert module.may_be_born({**own, "state": "closed"}, "o/r", set()) is False
    assert module.may_be_born(own, "o/r", {761}) is False


def test_birth_reads_the_plan_mark_by_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Кандидат судится меткой `findings.PLAN_MARKER`, а не её буквами (взгляд на #831).

    Подмена метки — единственное, что отличает ссылку от переписанных букв:
    вернись в `may_be_born` буквы начала метки, прежний тест не покраснел бы.
    """
    own = {"number": 763, "state": "open", "repository_url": "https://api.github.com/repos/o/r"}
    was = module.findings.PLAN_MARKER
    monkeypatch.setattr(module.findings, "PLAN_MARKER", "<!-- another-plan -->")
    assert module.may_be_born({**own, "body": "<!-- another-plan -->"}, "o/r", set()) is False
    # Прежняя метка, укороченная до начала, — уже не метка плана: выводится из
    # константы до подмены, а не буквами (209).
    assert module.may_be_born({**own, "body": was.split(":")[0] + " -->"}, "o/r", set()) is True


def test_a_born_row_needs_an_explicit_open_state(capsys: pytest.CaptureFixture[str]) -> None:
    """Без явного `state` задача не рождается, чужое хранилище названо вслух (#756)."""
    own = {"number": 762, "state": "open", "repository_url": "https://api.github.com/repos/o/r"}
    assert module.may_be_born({**own, "state": None}, "o/r", set()) is False
    assert module.may_be_born({k: v for k, v in own.items() if k != "state"}, "o/r", set()) is False
    elsewhere = {**own, "repository_url": "https://api.github.com/repos/other/r"}
    assert module.may_be_born(elsewhere, "o/r", set()) is False
    assert "#762 из другого хранилища" in capsys.readouterr().out


def test_the_plan_names_missing_answers_and_a_mistyped_rule(tmp_path: Any) -> None:
    """Без `bindings.json` раздел — отказ, а не пустота; опечатка номера видна в плане (#887)."""
    path = kinds_file(tmp_path, {"род": {"встречен": ["a", "b", "c"], "каталогу": "есть — 211"}})
    assert len(module.birth_part(path).rows) == 1, "опечатка номера не видна в плане"
    (tmp_path / "bindings.json").unlink()
    said = module.birth_part(path)
    assert said.rows == [] and module.finding_kinds.ANSWERS_UNREAD in said.unread, said


def test_a_history_kind_outside_the_dictionary_is_work(tmp_path: Any) -> None:
    """Род строки `Род:` вне словаря — строка раздела 5, и раздел не «Пусто» (#1086, #1096).

    Проверяется до вывода `render`: пометка, потерянная между `birth_part` и
    разделом, иначе осталась бы зелёной (`c2d193c`).
    """
    path = kinds_file(tmp_path, {"род": {"признак": "x", "встречен": ["a"], "закрыт": "гейт"}})
    said = module.birth_part(path, ["Разобрано: aaaaaaa\nРод: опечатка"])
    wanted = f"{module.finding_kinds.OUTSIDE_HISTORY} «опечатка» — встреч 1"
    assert [row for row in said.rows if row.startswith(wanted)], said
    shown = "\n".join(module.render(5, said))
    assert wanted in shown and "**Пусто**" not in shown, shown
    clean = module.birth_part(path, ["Разобрано: aaaaaaa\nРод: род"])
    assert clean.rows == [] and clean.note == "", clean


def test_the_open_list_is_read_once_and_handed_to_every_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Список открытых записей читается один раз и уходит всем каналам (#1084)."""
    quiet_platform(monkeypatch)
    listed = [{"number": 1}]
    reads: list[str] = []

    def read(*_: object) -> list[dict[str, int]]:
        reads.append("x")
        return listed

    monkeypatch.setattr(module.debt, "open_listed", read)
    got: dict[str, object] = {}
    monkeypatch.setattr(
        module.debt, "branch_debt", lambda r, t, seen=None: got.update(branch=seen) or ([], [])
    )
    monkeypatch.setattr(
        module.debt, "findings_debt", lambda r, t, seen=None: got.update(findings=seen) or []
    )
    monkeypatch.setattr(
        module.debt, "inbox_body", lambda r, t, c, seen=None: got.update(inbox=seen) or ("", "", "")
    )
    monkeypatch.setattr(
        module.findings,
        "live_issue_seen",
        lambda r, t, m, seen=None: got.update(drift=seen) or (None, "", ""),
    )
    assert module.main(["--repo", "o/r"]) == module.EXIT_OK
    assert reads == ["x"]
    assert got == {"branch": listed, "findings": listed, "inbox": listed, "drift": listed}


def test_born_rows_read_the_handed_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Рождённые строки берут переданный список, а не читают его заново (#1084)."""
    monkeypatch.setattr(
        module.ghrest,
        "paginate",
        lambda path, *_, **__: (
            (_ for _ in ()).throw(AssertionError(path)) if "state=open" in path else iter([])
        ),
    )
    held = {4: ["- **#10** — строка"], 6: []}
    child = {
        "number": 11,
        "title": "t",
        "body": "Refs #10",
        "state": "open",
        "html_url": "https://github.com/o/r/issues/11",
    }
    rows = module.born_rows("o/r", "t", held, frozenset(), [child])
    assert any("#11" in row for row in rows), rows


def test_late_minor_findings_accrue_in_source_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """На слитом дефект — долг раздела 3, риск и замечание копятся в разделе 5.

    Решение владельца 08.10.2026 (#639): поздний взгляд дробил план мелочью,
    и её починки крутили цикл. Находка на открытом изменении — долг любого веса.
    """
    quiet_platform(monkeypatch)
    monkeypatch.setattr(
        module.debt,
        "findings_debt",
        lambda *_: [
            ("aaaaaaa", 10, "дефект", "слитое ломается"),
            ("bbbbbbb", 10, "риск", "слитое сломается при условии"),
            ("ccccccc", 10, "замечание", "слитое написано криво"),
            ("ddddddd", 20, "замечание", "открытое написано криво"),
        ],
    )
    monkeypatch.setattr(module.debt, "open_changes", lambda *_: frozenset({20}))
    built, broken, marks = module.sources("o/r", "t")
    three = "\n".join(built[3].rows)
    five = "\n".join(built[5].rows)
    assert "aaaaaaa" in three and "ddddddd" in three, three
    assert "bbbbbbb" not in three and "ccccccc" not in three, three
    assert "bbbbbbb" in five and "ccccccc" in five, five
    assert "копится" in built[5].note, built[5].note
    assert marks == {"aaaaaaa", "bbbbbbb", "ccccccc", "ddddddd"}, "копящееся выпало из снятия"
    assert not broken


def test_unread_openness_keeps_the_registry_and_owes_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ чтения открытых изменений не выбрасывает реестр: всё — долг, и это названо.

    Взгляд на #1236: открытость читалась в одном `try` с реестром, и её отказ
    оставлял раздел 3 и снятие пустыми.
    """
    quiet_platform(monkeypatch)

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("список открытых молчит")

    monkeypatch.setattr(
        module.debt, "findings_debt", lambda *_: [("bbbbbbb", 10, "риск", "слитое сломается")]
    )
    monkeypatch.setattr(module.debt, "open_changes", refuse)
    built, _, marks = module.sources("o/r", "t")
    assert "bbbbbbb" in "\n".join(built[3].rows), "прочитанный реестр выброшен"
    assert "не прочитаны" in built[3].note, "слепота открытости не названа"
    assert "bbbbbbb" not in "\n".join(built[5].rows), "вслепую отложено в раздел 5"
    assert marks == {"bbbbbbb"}


# --- раздел 5 группами (#1263) -------------------------------------------


def test_section_five_prints_its_groups_and_skips_the_empty() -> None:
    """Подзаголовок у каждого непустого канала, пустой канал не печатается."""
    source = module.Source(
        rows=["a", "b"],
        groups=[("Правила каталога", ["a"]), ("Дрейф", []), ("Копящиеся находки · `x.py`", ["b"])],
    )
    lines = module.render(5, source)
    assert "*Правила каталога*" in lines and "*Копящиеся находки · `x.py`*" in lines
    assert "*Дрейф*" not in lines, "пустая группа напечатана"
    assert lines.index("- a") < lines.index("*Копящиеся находки · `x.py`*") < lines.index("- b")


def test_accrued_findings_are_grouped_by_file() -> None:
    """Находки — по файлу, без места — своей группой; одна группа — одно изменение."""
    rows = [
        "`aaaaaaa` · #1 — [риск] scripts/drift.py:12 — раз",
        "`bbbbbbb` · #2 — [замечание] (без места) — два",
        "`ccccccc` · #3 — [риск] scripts/drift.py:40-41 — три",
        "`ddddddd` · #4 — [риск] tests/test_x.py:5 — четыре",
    ]
    groups = module.by_file("Копящиеся находки", rows)
    assert [title for title, _ in groups] == [
        "Копящиеся находки · `scripts/drift.py`",
        "Копящиеся находки · `tests/test_x.py`",
        f"Копящиеся находки · {module.NO_PLACE}",
    ]
    assert groups[0][1] == [rows[0], rows[2]]


@pytest.mark.parametrize(
    ("title", "place"),
    [
        ("scripts/x.py:12 — голый путь", "scripts/x.py"),
        ("`scripts/x.py:12` — … — в кавычках", "scripts/x.py"),
        ("CONTRACT_VERSION:1 — путь без расширения", "CONTRACT_VERSION"),
        ("scripts/x.py:12, 40 — несколько строк", "scripts/x.py"),
        ("scripts/x.py:12 и tests/y.py:3 — два файла", "scripts/x.py"),
        ("(без места) — прозой", ""),
    ],
)
def test_a_finding_is_grouped_where_the_canon_places_it(title: str, place: str) -> None:
    """Группа находки — место по канону `findings.place_of`, во всех формах (взгляд на #1264).

    Своя регулярка расходилась с каноном на кавычках, пути без расширения и
    нескольких строках, и такие находки ложились в «без места» (210).
    """
    assert findings.place_of(title) == place
    [(group, _)] = module.by_file("К", [f"`aaaaaaa` · #1 — [риск] {title}"])
    assert group == (f"К · `{place}`" if place else f"К · {module.NO_PLACE}")


def test_groups_that_lose_a_row_are_refused() -> None:
    """Группы, не покрывающие строки раздела, — отказ, а не молчаливая потеря (взгляд на #1264)."""
    with pytest.raises(ValueError, match="1263"):
        module.Source(rows=["раз", "два"], groups=[("Г", ["раз"])])


def test_every_channel_of_section_five_has_a_title() -> None:
    """Подзаголовков столько же, сколько каналов в `parts`: новый канал без заголовка краснеет."""
    tree = ast.parse((ROOT / "scripts" / "work_plan.py").read_text(encoding="utf-8"))
    parts = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "parts"
        and isinstance(node.value, ast.Tuple)
    )
    assert isinstance(parts, ast.Tuple)
    assert len(module.FIVE_TITLES) == len(parts.elts)


#: Раздел 4 с прежними ручными заголовками групп — так его пишет рука сегодня.
SECTION_FOUR: Final = [
    "*Пояснение владельца.*",
    "",
    "*Сейчас*",
    "- **#701** — ждёт выпуска",
    "- **#702** — в работе",
    "*Ждёт владельца*",
    "- **#703** — ждёт решения",
    "",
    "*Отложено до 01.11*",
    "- **#704** — пересмотр 01.11.2026",
]


def test_section_four_is_laid_out_by_labels() -> None:
    """Группа — по метке задачи; порядок внутри — как в теле; пояснение сверху (#1433)."""
    labels = {701: {module.WAITS_RELEASE}, 703: {module.WAITS_OWNER}, 702: {"enhancement"}}
    assert module.grouped(SECTION_FOUR, labels) == [
        "*Пояснение владельца.*",
        "",
        "*Работаем сейчас*",
        "- **#702** — в работе",
        "",
        "*Ждёт решения*",
        "- **#703** — ждёт решения",
        "",
        "*Ожидаем выпуска*",
        "- **#701** — ждёт выпуска",
        "",
        "*Отложено до 01.11*",
        "- **#704** — пересмотр 01.11.2026",
    ]


def test_a_row_without_a_label_leaves_a_hand_group_for_now() -> None:
    """Без метки строка из «Ждёт владельца» встаёт в «Сейчас»: группу держит метка, а не тело."""
    said = module.grouped(SECTION_FOUR, {})
    assert "*Ждёт решения*" not in said and "*Ожидаем выпуска*" not in said
    assert said[said.index("*Работаем сейчас*") + 1 : said.index("*Работаем сейчас*") + 4] == [
        "- **#701** — ждёт выпуска",
        "- **#702** — в работе",
        "- **#703** — ждёт решения",
    ]


def test_a_born_row_joins_now_even_after_a_hand_group() -> None:
    """Рождённая строка встаёт по метке, а без метки — в «Сейчас», не в ручную группу (#1504).

    Ручная группа после раскладки всегда последняя, и строка, дописанная в
    конец тела, ложилась под неё: рождённая задача уходила в «Ждёт срока или
    чужого», и окно её не брало.
    """
    born = ["- **#705** — рождённая без метки", "- **#706** — рождённая с меткой выпуска"]
    said = module.grouped(SECTION_FOUR, {706: {module.WAITS_RELEASE}}, born)
    now, release = said.index("*Работаем сейчас*"), said.index("*Ожидаем выпуска*")
    hand = said.index("*Отложено до 01.11*")
    assert born[0] in said[now:release]
    assert born[1] in said[release:hand]
    assert said[hand + 1 :] == ["- **#704** — пересмотр 01.11.2026"]


def test_labels_are_read_from_the_open_listing() -> None:
    """Метки берутся из уже прочитанного списка открытых задач — по номеру."""
    listed = [{"number": 5, "labels": [{"name": module.WAITS_OWNER}, {"name": "x"}]}, {"x": 1}]
    assert module.labels_by_number(listed) == {5: {module.WAITS_OWNER, "x"}}


def test_the_built_plan_groups_section_four(monkeypatch: pytest.MonkeyPatch) -> None:
    """Собранный план раскладывает раздел 4 по меткам открытых задач."""
    written = quiet_platform(monkeypatch)
    listed = [{"number": 640, "labels": [{"name": module.WAITS_RELEASE}]}]
    monkeypatch.setattr(module.debt, "open_listed", lambda *_: listed)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    four = written[0].split("## 4 ·", 1)[1].split("## 5 ·", 1)[0]
    assert "*Работаем сейчас*\n- **#700**" in four
    assert "*Ожидаем выпуска*\n- **#640**" in four


def test_unread_labels_leave_section_four_as_written(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Список открытых не прочитан — раздел 4 как в теле, и это сказано (045)."""
    written = quiet_platform(monkeypatch)

    def refuse(*_: Any) -> list[dict[str, Any]]:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.debt, "open_listed", refuse)
    module.main(["--repo", "o/r", "--apply"])
    assert "*Работаем сейчас*" not in written[0]
    out = capsys.readouterr().out
    assert "раздел 4 оставлен как в теле" in out
    assert "рождённые задачи встанут следующим заходом" in out


def release_platform(
    listed: list[int], kept: frozenset[int] = frozenset(), gone: frozenset[int] = frozenset()
) -> tuple[Any, list[str]]:
    """Подделка площадки для снятия метки: список постранично, снятие, метки задачи.

    `kept` — задачи, на которых метка остаётся после снятия; `gone` — снятие
    отвечает 404 «метки уже нет». Метки задачи ПОМНЯТ снятие (взгляд на
    #1465): без снятия или при чтении до него метка на месте, и путь, где
    снятие не послано, краснеет, а не проходит.
    """
    calls: list[str] = []
    per = module.ghrest.PER_PAGE
    deleted: set[int] = set(gone)

    def platform(method: str, path: str, *_: Any) -> Any:
        calls.append(f"{method} {path}")
        if method == "DELETE":
            number = int(path.split("/issues/")[1].split("/")[0])
            if number in gone:
                raise module.ghrest.NotFound("404 Label does not exist")
            deleted.add(number)
            return {}
        if "/labels?" in path:
            number = int(path.split("/issues/")[1].split("/")[0])
            first = path.endswith("&page=1")
            carries = number in kept or number not in deleted
            return [{"name": module.WAITS_RELEASE}] if carries and first else []
        page = int(path.rsplit("page=", 1)[1])
        return [{"number": one} for one in listed[(page - 1) * per : page * per]]

    return platform, calls


def test_a_release_takes_the_waits_release_label_away(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Метка снимается со всех помеченных; список читается один раз, до снятия (#1433)."""
    platform, calls = release_platform([7, 9, 11])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "request", platform)
    assert module.main(["--repo", "o/r", "--released"]) == module.EXIT_OK
    listing = [one for one in calls if "labels=plan%2Fwaits-release" in one]
    assert len(listing) == 1, f"список перечитывается: {listing}"
    assert "DELETE repos/o/r/issues/11/labels/plan%2Fwaits-release" in calls
    assert "#7, #9, #11" in capsys.readouterr().out
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r", "--released"]) == module.EXIT_BROKEN


def test_more_than_a_page_of_labelled_issues_is_freed_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Помеченных больше страницы — снимаются все, хвост второй страницы тоже (`f9501b7`)."""
    many = list(range(1, module.ghrest.PER_PAGE + 3))
    platform, calls = release_platform(many)
    monkeypatch.setattr(module.ghrest, "request", platform)
    freed: list[int] = []
    module.released("o/r", "t", freed)
    assert freed == many
    first_delete = next(at for at, one in enumerate(calls) if one.startswith("DELETE"))
    assert any("page=2" in one for one in calls[:first_delete]), "список не дочитан до снятия"


def test_a_label_that_comes_back_is_a_refusal_naming_the_issue(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Метка осталась на задаче после снятия — отказ с номером, а не «снята» (`b790524`)."""
    platform, _ = release_platform([7, 9], kept=frozenset({9}))
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "request", platform)
    assert module.main(["--repo", "o/r", "--released"]) == module.EXIT_BROKEN
    said = capsys.readouterr().err
    assert "вернулась после снятия" in said and "#9" in said
    assert "уже снята — #7" in said


def test_a_refusal_midway_names_what_was_already_freed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ посреди захода называет уже снятые метки, а не «не снято ничего»."""
    platform, _ = release_platform([7, 9])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")

    def refusing(method: str, path: str, *rest: Any) -> Any:
        if method == "DELETE" and path.endswith("/9/labels/plan%2Fwaits-release"):
            raise module.ghrest.TransportError("502")
        return platform(method, path, *rest)

    monkeypatch.setattr(module.ghrest, "request", refusing)
    assert module.main(["--repo", "o/r", "--released"]) == module.EXIT_BROKEN
    assert "уже снята — #7" in capsys.readouterr().err


def test_a_refusal_after_the_delete_names_it_unverified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Снятие послано, а сверка отказала — задача названа «не сверено», а не «снята» (#1465)."""
    platform, _ = release_platform([7, 9])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")

    def refusing(method: str, path: str, *rest: Any) -> Any:
        if method == "GET" and "/issues/9/labels?" in path:
            raise module.ghrest.TransportError("502")
        return platform(method, path, *rest)

    monkeypatch.setattr(module.ghrest, "request", refusing)
    assert module.main(["--repo", "o/r", "--released"]) == module.EXIT_BROKEN
    said = capsys.readouterr().err
    assert "уже снята — #7;" in said and "послано, не сверено — #9" in said


def test_a_release_that_sends_no_delete_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подделка помнит снятие: заход без снятия видит метку на месте и отказывает (#1465)."""
    platform, _ = release_platform([7])

    def no_delete(method: str, path: str, *rest: Any) -> Any:
        return {} if method == "DELETE" else platform(method, path, *rest)

    monkeypatch.setattr(module.ghrest, "request", no_delete)
    with pytest.raises(module.NotRun, match="вернулась"):
        module.released("o/r", "t", [])


def test_a_label_already_gone_counts_as_freed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Снятие получило 404 — метки уже нет, задача названа снятой, отказа нет (`bb9fa10`).

    Так выглядит отстающий список: он отдаёт задачу, с которой метку уже сняли
    (замер на выпуске v1.7.0, 17.10.2026).
    """
    platform, calls = release_platform([7, 9], gone=frozenset({7}))
    monkeypatch.setattr(module.ghrest, "request", platform)
    freed: list[int] = []
    module.released("o/r", "t", freed)
    assert freed == [7, 9]
    assert "DELETE repos/o/r/issues/7/labels/plan%2Fwaits-release" in calls


def test_continuations_and_hand_groups_keep_their_rows() -> None:
    """Продолжение едет со строкой; ручная группа держит строки без метки (взгляд на #1446)."""
    lines = [
        "*Пояснение.*",
        "*Сейчас*",
        "- **#1** — первая",
        "  продолжение первой",
        "  - вложенный пункт",
        "*Отложено*",
        "- **#2** — отложена",
        "- **#3** — ждёт выпуска",
    ]
    said = module.grouped(lines, {3: {module.WAITS_RELEASE}})
    assert said == [
        "*Пояснение.*",
        "",
        "*Работаем сейчас*",
        "- **#1** — первая",
        "  продолжение первой",
        "  - вложенный пункт",
        "",
        "*Ожидаем выпуска*",
        "- **#3** — ждёт выпуска",
        "",
        "*Отложено*",
        "- **#2** — отложена",
    ]


def test_a_hand_head_is_a_whole_italic_line() -> None:
    """Заголовок ручной группы — курсив целиком; жирное и строка работы — нет."""
    assert module.hand_head("*Отложено*") and module.hand_head("  *Ждёт срока*  ")
    assert not module.hand_head("**жирное**") and not module.hand_head("- **#1** — работа")
    assert not module.hand_head("**") and not module.hand_head("*курсив* и текст")


def test_a_tail_frees_only_the_labels_set_before_its_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """С `before` метка, поставленная после тега, остаётся и называется (взгляд на #1488)."""
    platform, _ = release_platform([7, 9, 11])
    monkeypatch.setattr(module.ghrest, "request", platform)
    tag = datetime(2026, 10, 17, 12, tzinfo=UTC)
    at = {7: tag - timedelta(hours=1), 9: tag + timedelta(hours=1), 11: None}
    monkeypatch.setattr(module, "labelled_at", lambda repo, token, number: at[number])
    freed: list[int] = []
    later: list[int] = []
    module.released("o/r", "t", freed, before=tag, later=later)
    assert (freed, later) == ([7, 11], [9])


def test_the_label_time_is_the_last_labeling_of_waits_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Время метки — последнее событие `labeled` именно этой метки; чужие метки не в счёт."""
    events = [
        {
            "event": "labeled",
            "label": {"name": module.WAITS_RELEASE},
            "created_at": "2026-10-16T10:00:00Z",
        },
        {
            "event": "unlabeled",
            "label": {"name": module.WAITS_RELEASE},
            "created_at": "2026-10-16T11:00:00Z",
        },
        {
            "event": "labeled",
            "label": {"name": module.WAITS_RELEASE},
            "created_at": "2026-10-17T10:00:00Z",
        },
        {"event": "labeled", "label": {"name": "другая"}, "created_at": "2026-10-18T10:00:00Z"},
        {"event": "labeled", "label": {"name": module.WAITS_RELEASE}, "created_at": "не время"},
    ]
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token, **_: iter(events))
    assert module.labelled_at("o/r", "t", 7) == datetime(2026, 10, 17, 10, tzinfo=UTC)
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token, **_: iter([]))
    assert module.labelled_at("o/r", "t", 7) is None


@pytest.mark.parametrize("before", ["вчера", "2026-10-17T12:00:00"], ids=["не-время", "без-пояса"])
def test_a_border_that_is_not_a_zoned_time_does_not_run(
    monkeypatch: pytest.MonkeyPatch, before: str
) -> None:
    """Граница без пояса или не время — исход 2 до первого снятия, а не догадка о поясе."""
    calls: list[str] = []
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: calls.append(str(a)))
    code = module.main(["--repo", "o/r", "--released", "--before", before])
    assert code == module.EXIT_BROKEN and calls == []


def test_when_of_reads_only_a_time() -> None:
    """Время события — ISO с поясом; иное — `None`."""
    assert module.when_of("2026-10-17T10:00:00Z") == datetime(2026, 10, 17, 10, tzinfo=UTC)
    assert module.when_of("вчера") is None and module.when_of(None) is None


# --- отказ сборки виден (#1621) ---------------------------------------------


def test_a_refusal_block_sits_under_the_marker_and_leaves_the_rest() -> None:
    """Блок отказа — сразу под маркером; разделы — как были; второй не множится."""
    body = f"{module.MARKER}\nшапка\n\n## 0 · Раздел\n\nстрока\n"
    said = module.with_refusal(body, "строка без адреса", "прогон/1")
    lines = said.splitlines()
    assert lines[0] == module.MARKER and lines[1] == module.REFUSAL_OPEN, lines
    assert "строка без адреса" in said and "прогон/1" in said
    assert said.endswith("## 0 · Раздел\n\nстрока\n"), said
    again = module.with_refusal(said, "другая причина", "прогон/2")
    assert again.count(module.REFUSAL_OPEN) == 1 and "другая причина" in again
    assert "строка без адреса" not in again


def test_without_refusal_restores_the_body() -> None:
    """Успешная сборка снимает блок, и тело — то, что было до отказа."""
    body = f"{module.MARKER}\nшапка\n\n## 0 · Раздел\n"
    assert module.without_refusal(module.with_refusal(body, "п", "р")) == body
    assert module.without_refusal(body) == body


def test_run_address_names_the_run_or_says_it_is_not_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Адрес прогона — из переменных площадки; вне неё — честное «не назван»."""
    for name in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    assert "не назван" in module.run_address()
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "7")
    assert module.run_address() == "https://github.com/o/r/actions/runs/7"


def test_a_failed_refusal_write_is_named_not_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Сбой записи блока назван строкой, а не трассой: исход 2 уже сказан (039)."""
    monkeypatch.setattr(module.findings, "live_issue", lambda *_, **__: (639, "<!-- м -->\n"))

    def refuse(*_: Any, **__: Any) -> dict[str, Any]:
        raise module.ghrest.TransportError("нет сети")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.announce_refusal("o/r", "t", "причина")
    assert "в план не записан" in capsys.readouterr().err


def test_a_missing_plan_issue_is_named_not_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Живой задачи плана нет — блок не пишется, и журнал это говорит (`80c4703`)."""
    monkeypatch.setattr(module.findings, "live_issue", lambda *_, **__: (None, ""))
    module.announce_refusal("o/r", "t", "причина")
    assert "живой задачи плана нет" in capsys.readouterr().err


def test_the_red_step_promises_the_block_only_on_a_refusal() -> None:
    """Блок в шапке обещается только на отказе 2; на прочих кодах — журнал (`a13f591`)."""
    text = (ROOT / ".github/workflows/step-work-plan.yml").read_text(encoding="utf-8")
    step = text[text.index("- name: отказ сборки плана виден") :]
    assert 'if [ "${RC:-}" = "2" ]' in step
    assert "блока в шапке плана нет" in step
    # И на коде 2 блок не обещается: задачи плана может не быть, запись —
    # упасть; сообщение отсылает к строке журнала (взгляд на #1650).
    assert "причина строкой в шапке плана" not in step
    assert "отказ сборки назван в плане" in step


def test_a_successful_build_drops_the_refusal_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """Следующая успешная сборка снимает блок отказа из шапки (#1621)."""
    body = module.with_refusal(BODY, "прежний отказ", "прогон/1")
    written = quiet_platform(monkeypatch, body=body)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert written and module.REFUSAL_OPEN not in written[-1], written[-1][:300]


def test_the_step_turns_red_only_on_a_refused_build() -> None:
    """Шаг прогона краснеет на отказе сборки и на пустом коде, но не на 0 и 3 (#1621)."""
    import yaml

    flow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "step-work-plan.yml").read_text(encoding="utf-8")
    )
    steps = [one for job in flow["jobs"].values() for one in job.get("steps", [])]
    build = next(one for one in steps if one.get("id") == "plan")
    assert build.get("continue-on-error") is True, "сборка перестала быть совещательной (084)"
    assert '"rc=$rc" >>"$GITHUB_OUTPUT"' in build["run"]
    red = next(one for one in steps if "steps.plan.outputs.rc" in str(one.get("if", "")))
    assert red["if"] == "steps.plan.outputs.rc != '0' && steps.plan.outputs.rc != '3'"
    assert "exit 1" in red["run"] and not red.get("continue-on-error")


def test_a_multiline_reason_stays_one_quoted_line() -> None:
    """Причина отказа — одной строкой и с пределом: из цитаты она не выходит (взгляд на #1629)."""
    body = f"{module.MARKER}\nшапка\n"
    said = module.with_refusal(body, "строка один\n\nстрока два " + "х" * 500, "р")
    block = said.split(module.REFUSAL_OPEN, 1)[1].split(module.REFUSAL_CLOSE, 1)[0].strip()
    assert block.count("\n") == 0 and block.startswith(">"), block
    assert "строка один строка два" in block and "…" in block
    assert len(block) < module.REASON_LIMIT + 200


def test_section_four_has_five_groups_and_the_hand_date_group_is_gone() -> None:
    """Повтор и срок — группы по метке; прежняя ручная «Ждёт срока или чужого» снята (#1655)."""
    lines = [
        "*Ждёт срока или чужого — пересмотр 25.10.2026*",
        "*Ждёт срока или чужого*",
        "- **#1** — неделя локальной работы",
        "- **#2** — анализ отдачи после выпуска",
        "- **#3** — в работе",
    ]
    said = module.grouped(lines, {1: {module.WAITS_DATE}, 2: {module.RECURRING}})
    assert said[said.index("*Работаем сейчас*") + 1] == "- **#3** — в работе"
    assert (
        said[said.index("*Повторяющиеся действия*") + 1] == "- **#2** — анализ отдачи после выпуска"
    )
    assert said[said.index("*Ожидаем до даты*") + 1] == "- **#1** — неделя локальной работы"
    assert "*Ждёт срока или чужого*" not in said
    assert [head for head, _ in module.GROUPS][1:] == [
        "*Ждёт решения*",
        "*Ожидаем выпуска*",
        "*Повторяющиеся действия*",
        "*Ожидаем до даты*",
    ]


def test_section_of_sends_neighbours_to_six_and_four_labels_to_four() -> None:
    """Соседи — раздел 6 и сильнее групп раздела 4; без метки строка остаётся, где стоит."""
    assert module.section_of({module.WAITS_NEIGHBOUR, module.WAITS_OWNER}, 4) == 6
    assert module.section_of({module.WAITS_OWNER}, 6) == 4
    assert module.section_of({"enhancement"}, 6) == 6
    assert module.section_of(set(), 4) == 4


def test_routed_moves_a_row_with_its_indented_continuation() -> None:
    """Строка уходит в раздел своей метки вместе с продолжением под отступом (#1655)."""
    held = {
        4: ["*Пояснение.*", "- **#1** — ждёт соседа", "  продолжение", "- **#2** — наша"],
        6: ["- **#3** — ждёт решения", "- **#4** — своя очередь"],
    }
    labels = {1: {module.WAITS_NEIGHBOUR}, 3: {module.WAITS_OWNER}}
    kept, moved = module.routed(held, labels)
    assert kept == {4: ["*Пояснение.*", "- **#2** — наша"], 6: ["- **#4** — своя очередь"]}
    assert moved == {4: ["- **#3** — ждёт решения"], 6: ["- **#1** — ждёт соседа", "  продолжение"]}


def test_queued_rows_name_open_tasks_the_plan_lacks() -> None:
    """Открытая задача без строки встаёт в очередь; план, реестр, изменение и стоящее — нет."""
    listed = [
        {"number": 9, "title": "Интеграция", "state": "open", "body": ""},
        {"number": 8, "title": "Стоит в плане", "state": "open", "body": ""},
        {"number": 7, "title": "Изменение", "state": "open", "body": "", "pull_request": {}},
        {"number": 6, "title": "План", "state": "open", "body": module.MARKER},
        {"number": 5, "title": "Закрыта", "state": "closed", "body": ""},
    ]
    assert module.queued_rows("o/r", listed, {8}) == [
        f"- **#9** — Интеграция *({module.QUEUED_TAIL})*"
    ]


def test_the_built_plan_routes_rows_and_queues_the_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Сборка: раздел 6 под новым именем, соседская строка в 6, не стоявшая в плане — очередью."""
    written = quiet_platform(monkeypatch)
    listed = [
        {"number": 640, "labels": [{"name": module.WAITS_NEIGHBOUR}]},
        {"number": 711, "title": "Без строки", "state": "open", "body": "", "labels": []},
    ]
    monkeypatch.setattr(module.debt, "open_listed", lambda *_: listed)
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert f"## {module.HEADS[6]}" in written[0] and "## 6 · План автора" not in written[0]
    six = written[0].split(f"## {module.HEADS[6]}", 1)[1]
    assert "*Ожидаем действия соседей*\n- **#640**" in six
    assert "*Ждёт своей очереди*\n- **#642**" in six
    assert f"- **#711** — Без строки *({module.QUEUED_TAIL})*" in six
    assert "#642" not in written[0].split("## 4 ·", 1)[1].split("## 5 ·", 1)[0]
    assert "дописано задач, которых в плане не было: 1" in capsys.readouterr().out


def test_laid_out_writes_born_and_queued_rows_into_the_section_of_their_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Рождённая — в 4, не стоявшая в плане — в 6, но обе по метке: соседская — в 6 (#1655)."""
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([]))
    held = {4: ["- **#10** — наша"], 6: ["- **#20** — своя очередь"]}
    listed = [
        {"number": 11, "title": "Рождённая", "state": "open", "body": "Refs #10", "labels": []},
        {
            "number": 12,
            "title": "Вне плана, ждёт соседа",
            "state": "open",
            "body": "",
            "labels": [{"name": module.WAITS_NEIGHBOUR}],
        },
        {"number": 13, "title": "Вне плана", "state": "open", "body": "", "labels": []},
    ]
    said = module.laid_out("o/r", "t", held, frozenset(), listed)
    four, six = "\n".join(said[4]), "\n".join(said[6])
    assert "#11" in four and module.BORN_TAIL in four
    assert "*Ожидаем действия соседей*\n- **#12**" in six
    assert "*Ждёт своей очереди*\n- **#20**" in six and "- **#13** — Вне плана" in six


def test_a_row_moved_between_sections_is_not_counted_as_done(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Перенос строки меткой между 4 и 6 — не «снято сделанных» (взгляд на #1657)."""
    quiet_platform(monkeypatch)
    said: list[str] = []
    for labels in ([], [{"name": module.WAITS_OWNER}]):
        listed = [{"number": 642, "labels": labels}]
        monkeypatch.setattr(module.debt, "open_listed", lambda *_, listed=listed: listed)
        assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
        said.append(capsys.readouterr().out)
    # Без метки снимается одна строка — находка, чьего отпечатка нет в реестре;
    # перенос #642 в раздел 4 счёт не меняет.
    assert "снято сделанных строк: 1" in said[0]
    assert said[1] == said[0]


def test_zero_fixes_pair_a_fix_with_the_red_it_holds_from_either_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0б: «Чинит красное: #M» у починки и «Ждёт: #N» у красного — пары; 0а: «Чинит main:»."""
    pulls = [
        {"number": 30, "body": f"{module.changerefs.FIXES_RED_KEY} #31"},
        {"number": 31, "body": f"{module.changerefs.WAITS_KEY} починки #30"},
        {"number": 32, "body": f"{module.changerefs.WAITS_KEY} #40, слияния соседа"},
        {"number": 33, "body": f"{module.changerefs.FIXES_MAIN_KEY} tests"},
        {"number": 34, "body": f"{module.changerefs.WAITS_KEY} #41"},
        {"number": 37, "body": f"{module.changerefs.FIXES_RED_KEY} #36"},
        {"number": 38, "body": f"{module.changerefs.WAITS_KEY} #39"},
        {"number": 40, "body": "починка соседа"},
        {"number": 42, "body": f"{module.changerefs.FIXES_MAIN_KEY} lint"},
    ]
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter(pulls))
    monkeypatch.setattr(module.agent_pr, "red_on_trunk", lambda _r, _t, step, _b: step == "tests")
    red = ["#31 — красное", "#32 — красное", "#35 — своё красное", "#38 — красное"]
    main_rows, rows, held = module.zero_fixes("o/r", "t", red)
    assert main_rows == ["**#33** — чинит «tests» на общей ветке"], "зелёный lint у #42 — не 0а"
    assert rows == ["**#30** — держит #31", "**#40** — держит #32"]
    assert held == {31, 32}, "зелёное #34, не красное #36 и #38 с закрытой #39 не держимы"


def test_zero_fixes_keeps_a_main_fix_whose_red_was_not_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Краснота шага не спрошена — строка 0а остаётся с причиной, а не пропадает (039)."""
    pulls = [{"number": 33, "body": f"{module.changerefs.FIXES_MAIN_KEY} tests"}]
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter(pulls))

    def refuse(*_: object) -> bool:
        raise module.agent_pr.NotRun("голова не прочитана")

    monkeypatch.setattr(module.agent_pr, "red_on_trunk", refuse)
    main_rows, _, _ = module.zero_fixes("o/r", "t", [])
    assert main_rows == ["**#33** — чинит «tests»; краснота не спрошена: голова не прочитана"]


def test_the_built_plan_splits_zero_and_moves_the_held_red_out_of_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сборка: 0а и 0б подзаголовками, держимое красное — не в разделе 2."""
    written = quiet_platform(monkeypatch)
    monkeypatch.setattr(module.debt, "branch_debt", lambda *_: (["tests"], []))
    monkeypatch.setattr(
        module.debt, "stuck_changes", lambda *_: ([], [], ["#31 — красное", "#35 — своё красное"])
    )
    pulls = [{"number": 30, "body": f"{module.changerefs.FIXES_RED_KEY} #31"}]
    monkeypatch.setattr(
        module.ghrest,
        "paginate",
        lambda path, *_, **__: iter(pulls if path.endswith("pulls?state=open") else []),
    )
    assert module.main(["--repo", "o/r", "--apply"]) == module.EXIT_OK
    zero = written[0].split("## 0 ·", 1)[1].split("## 1 ·", 1)[0]
    two = written[0].split("## 2 ·", 1)[1].split("## 3 ·", 1)[0]
    assert f"*{module.ZERO_TITLES[0]}*\n- **tests** — держит слияние" in zero
    assert f"*{module.ZERO_TITLES[1]}*\n- **#30** — держит #31" in zero
    assert "#31" not in two and "#35 — своё красное" in two
