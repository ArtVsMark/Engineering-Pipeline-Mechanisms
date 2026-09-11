"""Долг перед планом: находки и незакрытая работа по правилам.

Шаг совещательный, поэтому проверяется не «краснеет ли он», а два свойства:
числа он ЧИТАЕТ, а не считает заново, и непрочитанное не выдаёт за пустое.
Второе важнее: остаток, показанный нулём вместо «неизвестно», — тихий
запасной путь (045).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.conftest import ROOT, RunScript, load_script

debt = load_script("debt.py")
task_shape = load_script("task_shape.py")

INBOX = """## Ступень 0 — незакрытая работа по правилам

**Задач по правилам: 3. Правил без ответа или «не рассмотрено»: 129.
Признано действующими, но держится ничем: 7.**

⚠️ **Контракт разошёлся.** формат ответа объявлен как 1.0, каталог ждёт 1.2 —
ответы перечитываются под новый контракт
"""


def test_three_numbers_are_read_from_the_inbox() -> None:
    """Три числа правила 177 читаются из задачи, которую ведёт каталог."""
    assert debt.rules_debt(INBOX) == (3, 129, 7)


@pytest.mark.parametrize("body", ["", "задача есть, а строки счёта нет", "Задач по правилам: 3."])
def test_a_missing_count_is_not_zero(body: str) -> None:
    """Нет строки счёта — «неизвестно», а не «долга нет».

    Ноль вместо неизвестности читается как «всё разобрано» и снимает
    приоритет с источника, который никто не проверял.
    """
    assert debt.rules_debt(body) is None


def test_a_diverged_contract_is_reported() -> None:
    """Расхождение контракта — третий вид долга по 177, и он назван словами."""
    note = debt.contract_note(INBOX)
    assert note is not None and "1.2" in note


def test_no_contract_note_when_it_matches() -> None:
    """Сошедшийся контракт молчит: пустое состояние не выдумывается."""
    assert debt.contract_note("**Задач по правилам: 0. …**") is None


# --- решение «есть ли долг» --------------------------------------------------
#
# Печать и решение — разные вещи, и разошлись они именно здесь: числа шаг
# печатал верно, а решал по ним неверно. Поэтому решение проверяется отдельно
# от вывода.


def test_open_rule_tasks_alone_are_not_a_debt() -> None:
    """Задачи по правилам в трекере долгом не считаются.

    Долг по 177 — три вида: правило без ответа, правило «действует и не
    держится ничем», разошедшийся контракт. Первое число строки счёта — сколько
    задач по правилам заведено, и оно ненулевое почти всегда. Считать его
    долгом значит объявлять долг ВСЕГДА, а напоминание, звучащее всегда,
    перестаёт что-либо значить (051).
    """
    assert debt.rules_left((3, 0, 0), None) is False


def test_a_rule_without_an_answer_is_a_debt() -> None:
    """Правило без ответа — первый вид долга."""
    assert debt.rules_left((0, 1, 0), None) is True


def test_a_rule_held_by_nothing_is_a_debt() -> None:
    """Правило «действует и не держится ничем» — второй вид."""
    assert debt.rules_left((0, 0, 1), None) is True


def test_a_diverged_contract_is_a_debt_on_its_own() -> None:
    """Расхождение контракта — третий вид, и оно решает само по себе (157).

    Печаталось оно и раньше, а в решение не входило: поднявшийся контракт
    означает, что ответы надо перечитать, и напоминание молчало ровно там, где
    обязано было звучать.
    """
    assert debt.rules_left((0, 0, 0), "объявлено 1.0, каталог ждёт 1.2") is True


def test_unknown_counts_are_a_debt_not_an_absence() -> None:
    """Числа не прочитаны — долг НЕИЗВЕСТЕН, а не равен нулю (045)."""
    assert debt.rules_left(None, None) is True


def test_everything_closed_is_not_a_debt() -> None:
    """Здоровый вход обязан пройти: иначе решение всегда «да» (097)."""
    assert debt.rules_left((7, 0, 0), None) is False


def test_the_step_does_not_count_rules_itself() -> None:
    """Гейт на дрейф: числа читаются, а не считаются вторым разом (022).

    Свой счёт по `.rules/bindings.json` разошёлся бы с каталогом молча —
    оба числа выглядят одинаково правдоподобно, а спорят они между собой.
    """
    source = (ROOT / "scripts" / "debt.py").read_text(encoding="utf-8")
    assert "bindings.json" not in source, "шаг завёл второй счёт того же"


def test_unread_debt_is_not_reported_as_none(run_script: RunScript) -> None:
    """Без токена долг НЕИЗВЕСТЕН, и шаг говорит это словами."""
    run = run_script("debt.py", env={"GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""})
    assert run.code == 3, run.text
    assert "не прочитан" in run.text


def test_the_step_names_where_the_order_is_written(run_script: RunScript) -> None:
    """Вывод ведёт к договору и к правилу, а не пересказывает их (029)."""
    run = run_script("debt.py", env={"GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""})
    assert "behaviour.md" in run.text or "177" in run.text


def test_the_order_puts_debts_before_the_plan() -> None:
    """Договор ставит находки и правила выше плана, а не рядом с ним.

    Гейт на согласованность документа: по этому порядку окно выбирает работу,
    и перестановка строк меняет поведение проекта.
    """
    text = (ROOT / "docs" / "behaviour.md").read_text(encoding="utf-8")
    findings_at = text.index("неразобранные находки внешнего взгляда")
    rules_at = text.index("незакрытая работа по правилам каталога")
    plan_at = text.index("задача из трекера и план автора")
    assert findings_at < rules_at < plan_at


def test_the_charter_cites_the_rule_behind_the_order() -> None:
    """Приоритет правил — требование каталога, а не местное изобретение."""
    text = (ROOT / "docs" / "behaviour.md").read_text(encoding="utf-8")
    assert "177-unfinished-rule-work-comes-first" in text


def test_the_step_is_declared_advisory() -> None:
    """Класс шага объявлен данными: долг не держит слияние, но виден."""
    answer = (ROOT / ".pipeline.yml").read_text(encoding="utf-8")
    assert "debt:" in answer and "advisory" in answer


# --- третье число: слитое без внешнего взгляда --------------------------------


def registry(*lines: str) -> str:
    """Тело реестра слитого без взгляда — в том виде, в каком его ведёт `unlooked`."""
    return "\n".join(["Просмотрено до: #90", "", "## Не просмотрено", "", *lines])


def test_the_third_number_counts_only_what_was_never_looked_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Считается «взгляда не было», а не все записи реестра.

    Поздний взгляд по общей ветке — состоявшийся разбор, пусть и другой. Считать
    его наравне с «взгляда не было» значило бы сказать, что работа канала
    пропала, когда она состоялась (154).
    """
    body = registry(
        f"- #88 · {debt.unlooked.STATE_NONE} · 2026-09-10",
        f"- #80 · {debt.unlooked.STATE_LATE} · 2026-09-01",
    )
    monkeypatch.setattr(debt.findings, "live_issue", lambda *_, **__: (7, body))
    left = debt.unlooked_debt("owner/repo", "token")
    assert [entry.number for entry in left] == [88]


def test_the_third_number_is_read_not_counted_again() -> None:
    """Число берётся из реестра, а не пересчитывается по площадке.

    Второй счёт того же разошёлся бы с первым молча, и оба выглядели бы
    правдоподобно (022). Здесь это видно по коду: шаг не ходит за слитыми
    ИЗМЕНЕНИЯМИ сам.

    Предмет запрета — именно изменения, а не всякая закрытая запись: задачи со
    `state=closed` шаг читает законно, потому что задачу-«входящие» закрывает
    прогон каталога, и её числа остаются последним, что каталог сказал. Прежняя
    редакция запрещала подстроку `state=closed` целиком и ловила это чтение как
    второй счёт — гейт был шире своего предмета (154).
    """
    source = (ROOT / "scripts" / "debt.py").read_text(encoding="utf-8")
    assert "merged_changes" not in source, "шаг считает слитое сам"
    assert "pulls?state=closed" not in source, "шаг ходит за слитыми изменениями"


def test_the_third_number_does_not_switch_the_reminder_on() -> None:
    """Слитое без взгляда печатается, но приоритета перед планом не даёт.

    Долг — это работа, которую обязаны сделать раньше новой. Посмотреть слитое
    заново можно, обязанности нет, и напоминание, звучащее всегда, перестаёт
    что-либо значить (051).

    Печать и решение здесь уже расходились однажды — на числах правила 177, —
    поэтому решение проверяется отдельно от вывода: в него входят ровно два
    источника, и добавить третий молча не выйдет.
    """
    source = (ROOT / "scripts" / "debt.py").read_text(encoding="utf-8")
    assert "remind(bool(left) or bool(lagging) or rules_left(numbers, note))" in source, (
        "решение о напоминании собрано иначе — проверьте, не вошло ли в него слитое без взгляда"
    )


# --- краснота общей ветки: два разных состояния, а не одно --------------------


RED_BODY = """## Держит слияние — источник 0

- **test**

## Не держит слияние, но не потеряно — источник 3

- **test (3.15)**

## Мигания

- lint · 10.09.2026 · прогон 100
"""


def test_the_two_kinds_of_branch_red_are_read_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    """Держащее слияние и не держащее читаются раздельно.

    Свалить их в одно число значило бы стереть разницу между простоем и
    долгом: первое решается починкой, второе — порядком работ (154).
    """
    monkeypatch.setattr(debt.findings, "live_issue", lambda *_, **__: (9, RED_BODY))
    holding, lagging = debt.branch_debt("owner/repo", "token")
    assert holding == ["test"]
    assert lagging == ["test (3.15)"]


def test_a_flake_is_not_counted_as_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Мигание красным не считается: оно уже позеленело, это находка о прошлом."""
    monkeypatch.setattr(debt.findings, "live_issue", lambda *_, **__: (9, RED_BODY))
    holding, lagging = debt.branch_debt("owner/repo", "token")
    assert "lint" not in holding + lagging


def test_a_missing_issue_is_not_a_red_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задачи нет — краснота не выдумывается: пустое состояние это состояние."""
    monkeypatch.setattr(debt.findings, "live_issue", lambda *_, **__: (None, ""))
    assert debt.branch_debt("owner/repo", "token") == ([], [])


def test_an_advisory_red_switches_the_reminder_on() -> None:
    """Совещательное красное общей ветки — долг перед планом.

    Работа помечена закрытой, а часть её не работает. Это то же основание, по
    которому выше плана стоят находки.
    """
    source = (ROOT / "scripts" / "debt.py").read_text(encoding="utf-8")
    assert "bool(lagging)" in source, "совещательное красное в решение о долге не входит"


def test_a_frozen_queue_is_not_called_a_debt() -> None:
    """Держащее слияние в долг перед планом НЕ входит.

    Это не долг, а остановка: пока очередь заморожена, порядок работ ничего не
    решает — решает починка. Напоминание «сделай долг раньше плана» здесь
    сказало бы не то (051).
    """
    source = (ROOT / "scripts" / "debt.py").read_text(encoding="utf-8")
    assert "bool(holding)" not in source, "заморозка объявлена долгом перед планом"


# --- задача, выглядящая готовой ----------------------------------------------


def issues_from(rows: list[dict[str, Any]]) -> Any:
    """Подделка площадки: обход задач отдаёт ровно эти записи."""

    def paginate(path: str, token: str, key: str | None = None) -> Any:
        return iter(rows)

    return paginate


def test_a_task_with_every_item_closed_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все пункты закрыты, а задача открыта — механизм её называет.

    До этого состояние не видел никто: `task_items` его вычисляет и молчит
    наружу. Живой случай 10.09.2026 — #26 и #25 простояли готовыми до вопроса
    владельца, и сколько именно, сказать нечем.
    """
    rows = [{"number": 26, "title": "Частичное закрытие", "body": "- [x] раз\n- [x] два\n"}]
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from(rows))
    assert debt.looks_done(debt.open_issues("o/r", "token")) == [(26, "Частичное закрытие")]


def test_one_open_item_is_enough_to_stay_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Один незакрытый пункт — задача не кандидат: работа не доделана."""
    rows = [{"number": 39, "title": "Слито без взгляда", "body": "- [x] раз\n- [ ] два\n"}]
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from(rows))
    assert debt.looks_done(debt.open_issues("o/r", "token")) == []


def test_a_task_without_items_is_not_a_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача без пунктов кандидатом не считается.

    Пустой чек-лист — это не «всё сделано», а «этапов не называли». У #25
    пунктов не было вовсе, и автоматическое «готова» стояло бы на ней с первого
    дня её жизни (154).
    """
    rows = [{"number": 25, "title": "Приоритет и мерило", "body": "Три вопроса прозой."}]
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from(rows))
    assert debt.looks_done(debt.open_issues("o/r", "token")) == []


def test_a_change_is_not_a_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменения приходят в том же списке и в счёт не идут."""
    rows = [{"number": 7, "title": "PR", "body": "- [x] раз\n", "pull_request": {"url": "…"}}]
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from(rows))
    assert debt.looks_done(debt.open_issues("o/r", "token")) == []


# --- закрытые «входящие» -----------------------------------------------------


def test_a_closed_inbox_is_still_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Входящие» закрыл прогон каталога — числа всё равно читаются.

    Живой случай 10.09.2026: в 11:22 прогон каталога закрыл #37, и с той минуты
    шаг долга объявлял долг по правилам НЕИЗВЕСТНЫМ на каждом изменении. Это
    штатное состояние, а не поломка, и красное о нём учат пролистывать (142).
    """
    said = (
        "Задач по правилам: 0. Правил без ответа или «не рассмотрено»: 0. "
        "Признано действующими, но держится ничем: 1."
    )
    monkeypatch.setattr(debt.findings, "live_issue_seen", lambda *_, **__: (None, "", ""))
    monkeypatch.setattr(
        debt.ghrest,
        "paginate",
        issues_from(
            [
                {
                    "number": 37,
                    "body": f"{debt.findings.INBOX_MARKER}\n{said}",
                    "updated_at": "2026-09-10T11:22:13Z",
                }
            ]
        ),
    )
    closed = debt.closed_issues("o/r", "token")
    body, note, seen = debt.inbox_body("o/r", "token", closed)
    assert debt.rules_debt(body) == (0, 0, 1)
    assert note == debt.CLOSED_INBOX
    assert seen == "2026-09-10T11:22:13Z", "закрытая задача отдала числа без их возраста"


def test_an_open_inbox_wins_over_a_closed_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Открытая «входящие» читается всегда: она свежее закрытой."""
    monkeypatch.setattr(
        debt.findings,
        "live_issue_seen",
        lambda *_, **__: (37, "живое тело", "2026-09-10T12:00:00Z"),
    )
    body, note, seen = debt.inbox_body("o/r", "token", [])
    assert body == "живое тело"
    assert note == ""
    assert seen == "2026-09-10T12:00:00Z"


def test_no_inbox_at_all_is_still_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Входящих» нет ни открытых, ни закрытых — долг НЕИЗВЕСТЕН, а не нулевой.

    Послабление касается закрытых, а не отсутствующих: молчание непроверенного
    источника здесь по-прежнему считается долгом (045).
    """
    monkeypatch.setattr(debt.findings, "live_issue_seen", lambda *_, **__: (None, "", ""))
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from([]))
    assert debt.inbox_body("o/r", "token", []) == ("", "", "")
    assert debt.rules_debt("") is None


# --- возраст снимка ----------------------------------------------------------


def test_the_age_of_the_snapshot_is_printed_beside_its_numbers() -> None:
    """Возраст печатается всегда, а не только когда он плохой.

    Строка, появляющаяся лишь при беде, читается как беда; строка, стоящая
    всегда, делает свежесть видимой величиной, а не предположением.
    """
    said = debt.said_age(timedelta(hours=3))
    assert "3 ч назад" in said
    assert debt.STALE_NOTE not in said


def test_a_snapshot_older_than_a_day_is_told_apart() -> None:
    """Снимок старше суток отличим от свежего прямо в выводе шага.

    Ночной заход каталога ходит раз в сутки: больший возраст означает не
    «немного устарело», а ПРОПУЩЕННЫЙ заход — то есть числа не пересчитывались
    вовсе.
    """
    said = debt.said_age(timedelta(hours=30))
    assert debt.STALE_NOTE in said
    assert "30 ч назад" in said


def test_a_stale_snapshot_is_still_read() -> None:
    """Вчерашние числа читаются, а не отбрасываются.

    Они — последнее, что каталог сказал, и «неизвестно» вместо них строже
    правды (051). Решение шага записано: назвать возраст и продолжить.
    """
    # Текст собирается из порога, а не повторяет его прозой: «больше суток»
    # стояло рядом с порогом в 26 часов и расходилось с ним на два часа.
    hours = int(debt.STALE_AFTER.total_seconds() // 3600)
    assert f"больше {hours} ч" in debt.STALE_NOTE
    assert debt.rules_debt(
        "Задач по правилам: 1. Правил без ответа или «не рассмотрено»: 2. "
        "Признано действующими, но держится ничем: 3."
    ) == (1, 2, 3)


def test_an_unreadable_date_is_not_freshness() -> None:
    """Дата не разобралась — возраст НЕИЗВЕСТЕН, а не «только что» (045)."""
    assert debt.age_of("не дата") is None
    assert "неизвестен" in debt.said_age(None)


def test_a_forged_old_snapshot_reads_differently(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверено отказом: подделанный старый снимок читается иначе свежего.

    Оба захода дают одни и те же числа — разница ровно в дате, и она обязана
    доехать до вывода. Без этой проверки «возраст напечатан» держалось бы тем,
    что строка есть, а не тем, что она меняется (140).
    """
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    fresh = debt.said_age(debt.age_of("2026-09-10T11:00:00Z", now))
    stale = debt.said_age(debt.age_of("2026-09-08T11:00:00Z", now))
    assert fresh != stale
    assert debt.STALE_NOTE in stale and debt.STALE_NOTE not in fresh


# --- застрявшие изменения: источники 1 и 2 ------------------------------------


def walks(
    changes: list[dict[str, Any]], runs: list[dict[str, Any]] | None = None
) -> Callable[..., Iterator[dict[str, Any]]]:
    """Подделка страничного обхода: открытые изменения и записи проверок.

    Список открытых изменений идёт СТРАНИЦАМИ, а не одним ответом: одна
    страница молча теряет хвост, и застрявшее за краем в долг не попадало.
    Подделка повторяет тот же вход, иначе тест проверял бы не то, что пойдёт
    в прогоне.
    """

    def paginate(path: str, *_: object, **__: object) -> Iterator[dict[str, Any]]:
        if path.startswith("repos/o/r/pulls?"):
            return iter(changes)
        return iter(runs or [])

    return paginate


def test_a_conflict_is_asked_per_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Состояние слияния берётся из одиночного ответа, а не из списка.

    В списочном ответе площадки поля `mergeable_state` НЕТ вовсе. Пока оно
    читалось оттуда, источник 1 не срабатывал ни разу: механизм молчал, и
    молчание выглядело как «конфликтов нет». Нашёл внешний взгляд на #132.
    """
    listing = [{"number": 5, "title": "работа", "draft": False, "head": {"sha": "abc"}}]

    def request(method: str, path: str, *_: object, **__: object) -> object:
        return {"mergeable_state": "dirty"} if path == "repos/o/r/pulls/5" else None

    monkeypatch.setattr(debt.ghrest, "request", request)
    monkeypatch.setattr(debt.ghrest, "paginate", walks(listing))
    conflicting, unknown, red = debt.stuck_changes("o/r", "token")
    assert conflicting == ["#5 — работа"]
    assert (unknown, red) == ([], [])


def test_an_unknown_merge_state_is_not_a_clean_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """`unknown` — не «конфликта нет»: площадка ещё считает.

    Выдать неизвестность за пустоту значит завести тихий запасной ответ (045):
    источник 1 молчал бы ровно тогда, когда о нём и надо спросить ещё раз.
    """
    listing = [{"number": 6, "title": "работа", "draft": False, "head": {"sha": "abc"}}]

    def request(method: str, path: str, *_: object, **__: object) -> object:
        return {"mergeable_state": "unknown"} if path == "repos/o/r/pulls/6" else None

    monkeypatch.setattr(debt.ghrest, "request", request)
    monkeypatch.setattr(debt.ghrest, "paginate", walks(listing))
    conflicting, unknown, red = debt.stuck_changes("o/r", "token")
    assert (conflicting, red) == ([], [])
    assert unknown == ["#6 — работа"]


def test_a_draft_is_not_stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    """Черновик застрять не может: он и не подан."""
    listing = [{"number": 7, "title": "черновик", "draft": True, "head": {"sha": "abc"}}]
    monkeypatch.setattr(debt.ghrest, "request", lambda *_, **__: None)
    monkeypatch.setattr(debt.ghrest, "paginate", walks(listing))
    assert debt.stuck_changes("o/r", "token") == ([], [], [])


# --- счёт по пунктам: то, что шаг говорит вслух ------------------------------


def test_a_blind_count_says_so_instead_of_zero() -> None:
    """В мелком клоне шаг говорит «не спрошено», а не «ноль».

    Фрагмент журнала обещал ровно эту строку, а в коде её не было: правка
    потерялась между двумя ветками, и ни один тест не заметил — вывода шага не
    спрашивал никто. Нашёл внешний взгляд на #152.
    """
    lines = debt.items_report([], [], blind=True)
    assert "не спрошено" in lines[0]
    assert "история обрезана" in lines[0]


def test_a_seeing_count_says_the_number() -> None:
    """История цела — печатается число, и ноль тоже печатается.

    Строка, появляющаяся лишь при находке, неотличима от выключенного
    механизма (142).
    """
    assert debt.items_report([], [], blind=False)[0].endswith(": 0")


# --- форма задачи: чек-лист вместо прозы и ревизия закрытого -----------------


def test_the_shape_report_speaks_both_numbers_at_zero() -> None:
    """Оба счёта печатаются и на нуле: молчащая строка выглядит выключенной (142)."""
    lines = debt.shape_report([], [])
    assert len(lines) == 2
    assert lines[0].startswith("задач с пунктами прозой, а не галочками: 0")
    assert lines[1].startswith("закрыто при живых единицах: 0")


def test_the_shape_report_names_every_candidate() -> None:
    """Названы все кандидаты, а не число: по номеру задачу открывают."""
    lines = debt.shape_report(
        [task_shape.Prose(23, "реестр находок", 33)],
        [task_shape.Live(7, "эпик", 0, 2)],
    )
    assert any("#23" in line and "пунктов 33" in line for line in lines), lines
    assert any("#7" in line and "подзадач открыто 2" in line for line in lines), lines


def test_the_revision_window_is_named_in_the_line() -> None:
    """Строка называет границу утверждения: живого нет ИМЕННО среди этих задач."""
    assert str(debt.CLOSED_WINDOW) in debt.shape_report([], [])[1]


# --- что нашёл внешний взгляд: каждая находка проверена отказом ---------------


def test_the_open_change_listing_goes_by_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Список открытых изменений идёт страницами, а не одной (находка #132).

    Одна страница молча теряет хвост: при числе открытых изменений больше
    пятидесяти застрявшее уезжало за край, и механизм отвечал «застрявших
    нет», не посмотрев на них. Проверяется тем, что найдено ИМЕННО то
    изменение, которое лежит за пятидесятым.
    """
    listing = [
        {"number": n, "title": f"работа {n}", "draft": False, "head": {"sha": "abc"}}
        for n in range(1, 61)
    ]
    monkeypatch.setattr(
        debt.ghrest,
        "request",
        lambda method, path, *_, **__: (
            {"mergeable_state": "dirty"}
            if path == "repos/o/r/pulls/57"
            else {"mergeable_state": "clean"}
        ),
    )
    monkeypatch.setattr(debt.ghrest, "paginate", walks(listing))
    conflicting, _, _ = debt.stuck_changes("o/r", "token")
    assert conflicting == ["#57 — работа 57"], "хвост списка потерян — читается одна страница"


def test_a_snapshot_dated_in_the_future_is_unknown() -> None:
    """Дата снимка в будущем — «неизвестно», а не «очень свежо» (находка #126).

    «Снято -1 ч назад» читается как исправная работа: расхождение часов
    выглядело бы свежестью. Неизвестность называется, а не подменяется бодрым
    числом (045).
    """
    said = debt.said_age(timedelta(hours=-1))
    assert "-1" not in said
    assert "неизвестен" in said and "будущем" in said


def test_the_revision_window_is_taken_by_closing_not_by_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ревизия закрытого берёт недавно ЗАКРЫТЫЕ, а не недавно заведённые (находка #173).

    Умолчание площадки — сортировка по заведению, и окно набиралось из самых
    новых задач: старая задача, закрытая вчера, в ревизию не попадала вовсе.
    Проверяется двумя концами: и запросом, и порядком выдачи.
    """
    asked: list[str] = []

    def paginate(path: str, *_: object, **__: object) -> Iterator[dict[str, Any]]:
        asked.append(path)
        return iter(
            [
                {"number": 3, "closed_at": "2026-09-01T10:00:00Z"},
                {"number": 90, "closed_at": "2026-09-11T10:00:00Z"},
            ]
        )

    monkeypatch.setattr(debt.ghrest, "paginate", paginate)
    got = debt.closed_issues("o/r", "token")
    assert "sort=updated" in asked[0], f"запрос идёт с умолчанием площадки: {asked[0]}"
    assert [one["number"] for one in got] == [90, 3], "порядок не по дате закрытия"


def test_the_inbox_reads_the_window_it_was_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Входящие» читаются из уже прочитанного окна, а не вторым обходом (находка #125).

    Прежде шаг обходил ВСЕ закрытые задачи репозитория на каждом изменении.
    Проверяется тем, что страничный обход не зовётся вовсе: предмет приходит
    аргументом.
    """
    monkeypatch.setattr(debt.findings, "live_issue_seen", lambda *_, **__: (None, "", ""))

    def forbidden(*_: object, **__: object) -> Iterator[dict[str, Any]]:
        raise AssertionError("шаг пошёл за закрытыми задачами второй раз")

    monkeypatch.setattr(debt.ghrest, "paginate", forbidden)
    closed = [{"number": 37, "body": f"{debt.findings.INBOX_MARKER}\nчисла", "updated_at": "t"}]
    body, note, _ = debt.inbox_body("o/r", "token", closed)
    assert "числа" in body and note == debt.CLOSED_INBOX


def test_extra_closed_inboxes_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Лишние закрытые «входящие» называются, а не выбираются молча (находка #125).

    Две закрытые копии означают, что задачу заводили дважды; числа читаются из
    одной, и молчать о второй значит выбирать за читателя (154).
    """
    monkeypatch.setattr(debt.findings, "live_issue_seen", lambda *_, **__: (None, "", ""))
    closed = [
        {"number": 37, "body": f"{debt.findings.INBOX_MARKER}\nстарое", "updated_at": "a"},
        {"number": 58, "body": f"{debt.findings.INBOX_MARKER}\nновое", "updated_at": "b"},
    ]
    body, note, _ = debt.inbox_body("o/r", "token", closed)
    assert "новое" in body, "числа взяты не из последней копии"
    assert "#37" in note and "ещё 1" in note, note


def test_the_stale_threshold_says_it_is_an_assumption() -> None:
    """Порог устаревания объявлен допущением, а не выдан за замер (находка #126).

    Число, поданное как измеренное, спорить с собой не даёт: его двигают «по
    ощущению» и никогда не перепроверяют. Проверяется по самому модулю —
    ровно там, где читатель на порог и наткнётся.
    """
    source = (ROOT / "scripts" / "debt.py").read_text(encoding="utf-8")
    place = source.index("STALE_AFTER: Final")
    said = source[max(0, place - 1200) : place]
    assert "допущение, а не замер" in said.lower(), "порог подан как измеренная величина"


def test_the_debt_count_asks_the_owner_of_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Открытость состояния спрашивается у того, кто его ведёт (находка #190).

    У состояний реестра два читателя — сам реестр и счёт долга, — а сравнение
    было написано дважды. Одно из состояний несёт исход суффиксом, точное
    равенство его не берёт, и такая запись выпадала из долга молча. Первый
    конец чинился накануне в `unlooked`, второй остался здесь (090).
    """
    unlooked = load_script("unlooked.py")
    odd = f"{unlooked.STATE_ODD}: timed_out"
    body = f"- #7 · {odd} · 2026-09-11\n- #8 · {unlooked.STATE_LATE} · 2026-09-11\n"
    monkeypatch.setattr(debt.findings, "live_issue", lambda *_, **__: (99, body))
    left = debt.unlooked_debt("o/r", "token")
    assert [entry.number for entry in left] == [7], "суффиксная запись выпала из счёта долга"


def test_the_revision_counts_before_and_after_the_counter_apart() -> None:
    """Ревизия закрытого считается двумя числами, а не одним (нашёл владелец).

    Задачи, закрытые до появления счётчика пунктов, не изменятся никогда:
    отметить их было нечем. Держать их в общем числе значит держать в счёте
    постоянное слагаемое, а счёт, который не меняется, перестают читать (051).
    Они не исчезают — их называют тем, что они есть (046).
    """
    live = [
        task_shape.Live(3, "первый день", 5, 0, before_the_counter=True),
        task_shape.Live(99, "свежая", 2, 0),
    ]
    lines = debt.shape_report([], live)
    head = next(line for line in lines if line.startswith("закрыто при живых"))
    assert head.startswith("закрыто при живых единицах: 1"), head
    said = " ".join(lines)
    assert "#99" in said and "#3" in said, "старая запись исчезла из вывода"
    assert "до счётчика пунктов" in said and task_shape.ITEMS_SINCE in said
