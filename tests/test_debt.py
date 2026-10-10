"""Долг перед планом: находки и незакрытая работа по правилам.

Шаг совещательный, поэтому проверяется не «краснеет ли он», а два свойства:
числа он ЧИТАЕТ, а не считает заново, и непрочитанное не выдаёт за пустое.
Второе важнее: остаток, показанный нулём вместо «неизвестно», — тихий
запасной путь (045).
"""

import ast
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

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
    text = (ROOT / "docs" / "agent" / "behaviour.md").read_text(encoding="utf-8")
    findings_at = text.index("неразобранные **дефекты** внешнего взгляда")
    rules_at = text.index("незакрытая работа по правилам каталога")
    plan_at = text.index("задача из трекера и план автора")
    assert findings_at < rules_at < plan_at


def test_the_charter_cites_the_rule_behind_the_order() -> None:
    """Приоритет правил — требование каталога, а не местное изобретение."""
    text = (ROOT / "docs" / "agent" / "behaviour.md").read_text(encoding="utf-8")
    assert "177-unfinished-rule-work-comes-first" in text


def test_the_step_is_declared_advisory() -> None:
    """Класс шага объявлен данными: долг не держит слияние, но виден."""
    answer = (ROOT / ".pipeline.yml").read_text(encoding="utf-8")
    assert '"debt / debt":' in answer and "advisory" in answer


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
    left, _ = debt.unlooked_debt("owner/repo", "token")
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


def function_named(path: Path, name: str) -> ast.FunctionDef:
    """Определение функции по имени — разбором, а не подстрокой."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )


def plan_sections() -> set[int]:
    """Разделы, которые собирает `work_plan.sources`: ключи `built[N] = …`, цепочки включительно."""
    sources = function_named(ROOT / "scripts" / "work_plan.py", "sources")
    found: set[int] = set()
    for node in ast.walk(sources):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "built"
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, int)
            ):
                found.add(target.slice.value)
    assert found, "`work_plan.sources` не собирает ни одного раздела — предмет не найден (075)"
    return found


def call_name(node: ast.Call) -> str:
    """Имя вызова в обеих формах записи: `f(...)` и `модуль.f(...)`."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def decision_call() -> ast.Dict:
    """Словарь прочитанного, который `debt.main` отдаёт решению через `checked`."""
    main = function_named(ROOT / "scripts" / "debt.py", "main")
    calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and call_name(node) == "checked"
    ]
    assert len(calls) == 1, f"`checked` зовётся из шага {len(calls)} раз, ожидался один"
    asked = calls[0].args[0] if calls[0].args else None
    assert isinstance(asked, ast.Dict), "прочитанное отдано решению не словарём"
    return asked


def test_the_decision_is_derived_from_the_tables() -> None:
    """`before_plan` спрашивается `owed_by`, а не выражением рукой (взгляд на #1260)."""
    main = function_named(ROOT / "scripts" / "debt.py", "main")
    calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and call_name(node) == "before_plan"
    ]
    assert len(calls) == 1, f"`before_plan` зовётся из шага {len(calls)} раз, ожидался один"
    [asked] = calls[0].args
    assert isinstance(asked, ast.Call) and call_name(asked) == "owed_by", ast.unparse(asked)


def test_the_decision_asks_every_source_the_plan_puts_first() -> None:
    """`BEFORE_PLAN` со `STOP` — ровно разделы плана, и шаг спрашивает решение по каждому (210).

    Решение дважды не видело источник, который шаг читал и печатал рядом:
    копящиеся находки (взгляд на #1236), затем конфликт и красное на своих
    (взгляд на #1256). Поэтому не перечень параметров, а строгое правило:
    набор источников выводится из сборщика плана, а вызов из шага обязан
    назвать каждый.
    """
    assert not set(debt.BEFORE_PLAN) & set(debt.STOP), "раздел и в долге, и в остановке"
    assert set(debt.BEFORE_PLAN) | set(debt.STOP) == plan_sections()
    assert set(debt.FED_BY) == set(debt.BEFORE_PLAN)
    assert set(debt.UNREAD_BY) <= set(debt.BEFORE_PLAN)
    keys = {key.value for key in decision_call().keys if isinstance(key, ast.Constant)}
    assert keys == debt.read_names()


def test_each_name_is_read_from_its_own_value() -> None:
    """Значение каждого ключа прочитанного — само имя или вызов чтеца того же имени.

    Иначе таблица решала бы по подмене: `"red": []` или `"conflicting": red`
    сверку по ключам проходили бы (взгляд на #1260).
    """
    for key, value in zip(decision_call().keys, decision_call().values, strict=True):
        assert isinstance(key, ast.Constant) and isinstance(key.value, str)
        named = value.id if isinstance(value, ast.Name) else ""
        called = call_name(value) if isinstance(value, ast.Call) else ""
        assert key.value in (named, called), f"«{key.value}» прочитан из {ast.unparse(value)}"


@pytest.mark.parametrize("name", sorted({n for names in debt.FED_BY.values() for n in names}))
def test_each_read_name_decides_its_own_source(name: str) -> None:
    """Непустое прочитанное в одиночку включает ровно свой источник (взгляд на #1260).

    Имя, упомянутое в выражении, ещё не решает: `bool(x) and False` сверку по
    именам проходил. Здесь решение спрашивается поведением.
    """
    read = debt.checked({one: one == name for one in debt.read_names()})
    owed = debt.owed_by(read)
    assert {source for source, yes in owed.items() if yes} == {
        source for source, names in debt.FED_BY.items() if name in names
    }


def test_a_read_missing_a_name_is_refused() -> None:
    """Прочитанное без имени из таблиц — отказ, а не молчаливое «пусто» (210)."""
    with pytest.raises(ValueError, match="210"):
        debt.checked({"conflicting": []})


#: Одно непустое прочитанное — имя в таблицах шага долга, чтец, общий у
#: шага и сборщика плана, и что он вернёт. Перечень обязан покрыть ВСЕ имена
#: `read_names()` — это держит тест ниже, а не память (005).
ONE_READ: Final[tuple[tuple[str, str, object], ...]] = (
    ("conflicting", "stuck_changes", (["#1 — x"], [], [])),
    ("unknown", "stuck_changes", ([], ["#1 — x"], [])),
    ("red", "stuck_changes", ([], [], ["#1 — x"])),
    ("lagging", "branch_debt", ([], ["lint"])),
    ("left", "findings_debt", [("abc1234", 5, "дефект", "x")]),
    ("kept", "findings_debt", [("abc1234", 5, "риск", "x")]),
    ("rules_left", "rules_debt", (0, 1, 0)),
)


def plan_with(monkeypatch: pytest.MonkeyPatch, reader: str, said: object) -> dict[int, Any]:
    """Разделы плана, собранные, когда чтец `reader` вернул `said`, а прочие — пустоту."""
    plan = load_script("work_plan.py")
    quiet: dict[str, object] = {
        "branch_debt": ([], []),
        "stuck_changes": ([], [], []),
        "findings_debt": [],
        "open_changes": frozenset(),
        "closed_issues": [],
        "inbox_body": ("", "", ""),
        "rules_debt": (0, 0, 0),
        "contract_note": None,
    }
    quiet[reader] = said
    for name, value in quiet.items():
        monkeypatch.setattr(plan.debt, name, lambda *_, value=value, **__: value)
    monkeypatch.setattr(plan.findings, "live_issue_seen", lambda *_, **__: (None, "", ""))
    monkeypatch.setattr(plan, "birth_part", lambda *_: plan.Source())
    monkeypatch.setattr(plan.ghrest, "paginate", lambda *_, **__: iter([]))
    built: dict[int, Any] = plan.sources("o/r", "t", [])[0]
    return built


def test_one_read_covers_every_name_of_the_tables() -> None:
    """Перечень случаев — ровно имена таблиц: новое имя без случая краснеет (взгляд на #1275)."""
    assert {name for name, _, _ in ONE_READ} == debt.read_names()


@pytest.mark.parametrize(("name", "reader", "said"), ONE_READ, ids=[one[0] for one in ONE_READ])
def test_the_plan_puts_each_read_where_the_tables_say(
    monkeypatch: pytest.MonkeyPatch, name: str, reader: str, said: object
) -> None:
    """Строгое правило сверено ПОВЕДЕНИЕМ, а не разбором кода (взгляды на #1260, #1267, #1275; 210).

    Одно непустое прочитанное подаётся сборщику плана; оно обязано лечь ровно
    в тот раздел и то поле, что называют `FED_BY` (строки) и `UNREAD_BY`
    (непрочитанное), и больше никуда. Разбор кода по именам видел только
    прямые вызовы `debt.*` и для разделов 3 и 5 проходил пустым.
    """
    built = plan_with(monkeypatch, reader, said)
    where = {
        (section, field)
        for section in debt.BEFORE_PLAN
        for field in ("rows", "unread")
        if getattr(built[section], field)
    }
    owed = {(section, "rows") for section, names in debt.FED_BY.items() if name in names}
    unread = {(section, "unread") for section, said in debt.UNREAD_BY.items() if name in said}
    assert where == owed | unread, f"«{name}»: план кладёт в {sorted(where)}"


def test_the_third_number_does_not_switch_the_reminder_on() -> None:
    """Слитое без взгляда печатается, но в решение о долге не входит.

    Долг — это работа, которую обязаны сделать раньше новой. Посмотреть слитое
    заново можно, обязанности нет, и напоминание, звучащее всегда, перестаёт
    что-либо значить (051).
    """
    used = {node.id for node in ast.walk(decision_call()) if isinstance(node, ast.Name)}
    assert "unlooked_left" not in used and "unlooked_tally" not in used, used


def test_a_decision_missing_a_source_is_refused() -> None:
    """Решение без источника — отказ, а не молчаливое «долга нет» (взгляд на #1256)."""
    partial = {one: False for one in debt.BEFORE_PLAN if one != 1}
    with pytest.raises(ValueError, match="210"):
        debt.before_plan(partial)


def test_an_unread_source_is_not_called_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """Источник с несказанным состоянием назван отдельно, а не в «пусты» (#1260)."""
    read = debt.checked({one: one == "unknown" for one in debt.read_names()})
    debt.remind(debt.before_plan(debt.owed_by(read)), debt.unread_in(read))
    said = capsys.readouterr().out
    assert f"источники {debt.sources_said()} пусты" not in said
    assert f"источники {debt.sources_said([1])} пусты" in said
    assert "Источник 1 прочитан не весь" in said


def test_a_one_shot_skip_is_honoured() -> None:
    """Пропуск одноразовым итератором не теряется после первой проверки (взгляд на #1267)."""
    assert "5" not in debt.sources_said(iter([5]))


@pytest.mark.parametrize("source", [None, *debt.BEFORE_PLAN])
def test_any_source_alone_comes_before_the_plan(source: int | None) -> None:
    """Любой источник перед планом в одиночку — долг; все пусты — нет (взгляды на #1236, #1256).

    Сборщик плана ставит каждый из них выше плана автора, а шаг при одних
    копящихся находках, а затем при одном конфликте говорил «работы нет».
    """
    owed = {one: one == source for one in debt.BEFORE_PLAN}
    assert debt.before_plan(owed) is (source is not None)


@pytest.mark.parametrize("owed", [True, False])
def test_the_reminder_names_the_debt_sources_from_the_declaration(
    owed: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """Напоминание называет источники долга из `BEFORE_PLAN`, а не рукописным «3 и 5» (005)."""
    debt.remind(owed)
    said = capsys.readouterr().out
    assert f"источники {debt.sources_said()}" in said
    assert debt.sources_said() == ", ".join(str(one) for one in debt.BEFORE_PLAN)


def test_every_read_channel_is_read_by_the_step() -> None:
    """Канал из `READ` шаг на деле читает: его функция зовётся в `main` (взгляд на #1256).

    Иначе строка в `READ` закрывала бы сверку каналов, а шаг выдавал бы
    непрочитанное за пустоту (195).
    """
    main = function_named(ROOT / "scripts" / "debt.py", "main")
    called = {call_name(node) for node in ast.walk(main) if isinstance(node, ast.Call)}
    missing = sorted(set(debt.READ.values()) - called)
    assert not missing, f"`READ` называет чтение, которого `main` не делает: {missing}"


def producers_in_main() -> dict[str, set[str]]:
    """Имя прочитанного → чтецы, которыми `main` его получил: присваиванием или в словаре."""
    main = function_named(ROOT / "scripts" / "debt.py", "main")
    made: dict[str, set[str]] = {}
    for node in ast.walk(main):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for target in node.targets:
                names = target.elts if isinstance(target, ast.Tuple) else [target]
                for one in names:
                    if isinstance(one, ast.Name):
                        made.setdefault(one.id, set()).add(call_name(node.value))
    for key, value in zip(decision_call().keys, decision_call().values, strict=True):
        if isinstance(key, ast.Constant) and isinstance(value, ast.Call):
            made.setdefault(str(key.value), set()).add(call_name(value))
    return made


def test_source_five_is_fed_by_the_read_channels() -> None:
    """Источник 5 решает то, что получено чтецами `READ`, и только оно (взгляд на #1260).

    Сверка «функция зовётся в `main`» не видела, что из неё получено: строка в
    `READ` пережила бы смену чтеца молча.
    """
    made = producers_in_main()
    readers = set(debt.READ.values())
    for name in debt.FED_BY[5]:
        assert made.get(name, set()) & readers, f"«{name}» получен не чтецом из `READ`"
    fed = {reader for name in debt.FED_BY[5] for reader in made.get(name, set())}
    assert readers <= fed, f"чтец из `READ` источник 5 не кормит: {sorted(readers - fed)}"


def source_five_channels(text: str) -> set[str]:
    """Каналы раздела 5 у сборщика плана — из кода `work_plan.sources`.

    Раздел 5 собирается кортежем `parts`. Канал называется чтецом, если имя
    присвоено вызовом `<что-то>_part(...)`, иначе — самим именем в `sources`
    (`work_plan.sources:<имя>`). НИЧЕГО НЕ ОТБРАСЫВАЕТСЯ: имя без присваивания
    или элемент кортежа не именем — отказ с названием, а не тихий пропуск
    (взгляд на #1256).
    """
    tree = ast.parse(text)
    sources = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "sources"
    )
    # ВСЕ ПРИСВАИВАНИЯ ИМЕНИ, А НЕ ПОСЛЕДНЕЕ: чтец, обёрнутый в try с запасным
    # `Source(unread=…)`, как у `kept_part`, иначе читался бы запасом
    # (взгляд на #1256).
    named: dict[str, set[str]] = {}
    parts: list[ast.expr] = []
    for node in ast.walk(sources):
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        target = node.targets[0].id
        if target == "parts" and isinstance(node.value, ast.Tuple):
            parts = node.value.elts
        elif isinstance(node.value, ast.Call):
            # Обе формы имени вызова: `drift_part(...)` и `work_plan.drift_part(...)`.
            call = node.value.func
            if isinstance(call, ast.Name):
                named.setdefault(target, set()).add(call.id)
            elif isinstance(call, ast.Attribute):
                named.setdefault(target, set()).add(call.attr)
    assert parts, "раздел 5 в `work_plan.sources` больше не собирается кортежем `parts`"
    channels: set[str] = set()
    for one in parts:
        assert isinstance(one, ast.Name), f"в `parts` не имя: {ast.unparse(one)}"
        assert one.id in named, f"канал раздела 5 «{one.id}» не присвоен вызовом в `sources`"
        readers = sorted(name for name in named[one.id] if name.endswith("_part"))
        assert len(readers) <= 1, f"канал «{one.id}» читают два чтеца: {readers}"
        channels.add(f"work_plan.{readers[0]}" if readers else f"work_plan.sources:{one.id}")
    return channels


def test_the_unread_channels_are_the_plans_other_readers() -> None:
    """`NOT_READ` и `READ` вместе — ровно каналы раздела 5 (взгляды на #1245, #1256).

    Новый канал раздела 5, не названный ни там, ни здесь, краснеет: иначе шаг
    снова молча выдал бы непрочитанное за пустоту (195).
    """
    text = (ROOT / "scripts" / "work_plan.py").read_text(encoding="utf-8")
    assert not set(debt.NOT_READ.values()) & set(debt.READ), "канал назван дважды"
    assert source_five_channels(text) == set(debt.NOT_READ.values()) | set(debt.READ)


@pytest.mark.parametrize(
    ("added", "said"),
    [
        ("    fresh = read_fresh(repo)\n", "work_plan.sources:fresh"),
        ("    fresh = changerefs.fresh_part(repo)\n", "work_plan.fresh_part"),
        ("", "не присвоен"),
    ],
)
def test_a_new_channel_is_not_dropped(added: str, said: str) -> None:
    """Новый канал в `parts` виден сверке в любой форме: чтецом, не-чтецом, без присваивания."""
    text = (ROOT / "scripts" / "work_plan.py").read_text(encoding="utf-8")
    old = "    parts = (rules, moved, born, kept_part)\n"
    assert old in text, "кортеж раздела 5 сменил форму — пример пересобрать"
    changed = text.replace(old, added + "    parts = (rules, moved, born, kept_part, fresh)\n")
    if said == "не присвоен":
        with pytest.raises(AssertionError, match=said):
            source_five_channels(changed)
        return
    assert said in source_five_channels(changed)


def test_an_empty_step_names_what_it_did_not_read(capsys: pytest.CaptureFixture[str]) -> None:
    """Без долга шаг не обещает «работу по плану»: дрейф и поводы он не читал (#1245)."""
    debt.remind(False)
    said = capsys.readouterr().out
    assert "работа берётся по плану" not in said
    assert "источники 3 и 5 пусты" not in said
    for name in debt.NOT_READ:
        assert name in said, f"непрочитанный канал «{name}» не назван"


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
    read = debt.checked({one: one == "lagging" for one in debt.read_names()})
    assert debt.owed_by(read)[3], "совещательное красное в решение о долге не входит"


def test_a_frozen_queue_is_not_called_a_debt() -> None:
    """Держащее слияние в долг перед планом НЕ входит.

    Это не долг, а остановка: пока очередь заморожена, порядок работ ничего не
    решает — решает починка. Напоминание «сделай долг раньше плана» здесь
    сказало бы не то (051).
    """
    assert "holding" not in debt.read_names(), "заморозка объявлена долгом перед планом"


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
    assert debt.looks_done(debt.open_issues(debt.open_listed("o/r", "token"))) == [
        (26, "Частичное закрытие")
    ]


def test_one_open_item_is_enough_to_stay_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Один незакрытый пункт — задача не кандидат: работа не доделана."""
    rows = [{"number": 39, "title": "Слито без взгляда", "body": "- [x] раз\n- [ ] два\n"}]
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from(rows))
    assert debt.looks_done(debt.open_issues(debt.open_listed("o/r", "token"))) == []


def test_a_task_without_items_is_not_a_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача без пунктов кандидатом не считается.

    Пустой чек-лист — это не «всё сделано», а «этапов не называли». У #25
    пунктов не было вовсе, и автоматическое «готова» стояло бы на ней с первого
    дня её жизни (154).
    """
    rows = [{"number": 25, "title": "Приоритет и мерило", "body": "Три вопроса прозой."}]
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from(rows))
    assert debt.looks_done(debt.open_issues(debt.open_listed("o/r", "token"))) == []


def test_a_change_is_not_a_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменения приходят в том же списке и в счёт не идут."""
    rows = [{"number": 7, "title": "PR", "body": "- [x] раз\n", "pull_request": {"url": "…"}}]
    monkeypatch.setattr(debt.ghrest, "paginate", issues_from(rows))
    assert debt.looks_done(debt.open_issues(debt.open_listed("o/r", "token"))) == []


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
    monkeypatch.setattr(debt.hail.time, "sleep", lambda _: None)
    conflicting, unknown, red = debt.stuck_changes("o/r", "token")
    assert (conflicting, red) == ([], [])
    assert unknown == [f"#6 — работа ({debt.hail.UNSAID_WAITED})"]


def test_a_merge_state_counted_while_waiting_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Первый ответ `unknown`, второй — посчитанный: долг читает второй (взгляд на #1275).

    План собирается сразу после `ci`, когда площадка ещё считает. Спрошенное
    один раз состояние роняло план в «не прочитано», хотя пара секунд дала бы ответ.
    """
    answers = iter(["unknown", "dirty"])
    asked: list[str] = []

    def request(method: str, path: str, *_: object, **__: object) -> object:
        asked.append(path)
        return {"mergeable_state": next(answers)}

    monkeypatch.setattr(debt.ghrest, "request", request)
    monkeypatch.setattr(debt.hail.time, "sleep", lambda _: None)
    assert debt.merge_state("o/r", 6, "token") == "dirty"
    assert asked == ["repos/o/r/pulls/6", "repos/o/r/pulls/6"]


def test_an_unknown_merge_state_is_still_asked_for_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Красное от состояния слияния не зависит: неизвестное спрашивается и о нём (#1260)."""
    listing = [{"number": 6, "title": "работа", "draft": False, "head": {"sha": "abc"}}]
    runs = [{"name": "test", "status": "completed", "conclusion": "failure"}]

    def request(method: str, path: str, *_: object, **__: object) -> object:
        return {"mergeable_state": "unknown"} if path == "repos/o/r/pulls/6" else None

    monkeypatch.setattr(debt.ghrest, "request", request)
    monkeypatch.setattr(debt.ghrest, "paginate", walks(listing, runs))
    monkeypatch.setattr(debt.hail.time, "sleep", lambda _: None)
    _, unknown, red = debt.stuck_changes("o/r", "token")
    assert unknown == [f"#6 — работа ({debt.hail.UNSAID_WAITED})"]
    assert red == ["#6 — работа"]


def test_the_wait_budget_covers_the_whole_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Бюджет ожидания — на весь обход: израсходован — изменение спрашивается раз (#1306)."""
    listing = [
        {"number": n, "title": "работа", "draft": False, "head": {"sha": "abc"}} for n in (6, 7)
    ]
    asked: list[str] = []

    def request(method: str, path: str, *_: object, **__: object) -> object:
        asked.append(path)
        return {"mergeable_state": "unknown"}

    clock = iter([0.0, 0.0, debt.hail.WAIT_BUDGET + 1.0])
    monkeypatch.setattr(debt.ghrest, "request", request)
    monkeypatch.setattr(debt.ghrest, "paginate", walks(listing))
    monkeypatch.setattr(debt.hail.time, "sleep", lambda _: None)
    monkeypatch.setattr(debt.hail.time, "monotonic", lambda: next(clock))
    _, unknown, _ = debt.stuck_changes("o/r", "token")
    assert asked.count("repos/o/r/pulls/6") == debt.hail.WAIT_TRIES
    assert asked.count("repos/o/r/pulls/7") == 1, "бюджет обхода не держит второе изменение"
    # «Не дождались» и «ждать не стали» — разные ответы, и строка несёт свой
    # (взгляд на #1306): прежде обе звались «площадка ещё считает».
    assert unknown == [
        f"#6 — работа ({debt.hail.UNSAID_WAITED})",
        f"#7 — работа ({debt.hail.UNSAID_SPENT})",
    ]


def test_unsaid_why_tells_waited_from_spent() -> None:
    """Причина несказанного слияния — одна на всех читателей и различает два ответа (#1306)."""
    assert debt.hail.unsaid_why(spent=False) == debt.hail.UNSAID_WAITED
    assert debt.hail.unsaid_why(spent=True) == debt.hail.UNSAID_SPENT
    assert debt.hail.UNSAID_WAITED != debt.hail.UNSAID_SPENT


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


def test_the_shape_report_speaks_every_number_at_zero() -> None:
    """Все три счёта печатаются и на нуле: молчащая строка выглядит выключенной (142)."""
    lines = debt.shape_report([], [], [])
    assert len(lines) == 3
    assert lines[0].startswith("задач с пунктами прозой, а не галочками: 0")
    assert lines[1].startswith("закрыто при живых единицах: 0")
    assert lines[2].startswith("задач без зоны или рода: 0")


def test_the_shape_report_names_every_candidate() -> None:
    """Названы все кандидаты, а не число: по номеру задачу открывают."""
    lines = debt.shape_report(
        [task_shape.Prose(23, "реестр находок", 33)],
        [task_shape.Live(7, "эпик", 0, 2)],
        [],
    )
    assert any("#23" in line and "пунктов 33" in line for line in lines), lines
    assert any("#7" in line and "подзадач открыто 2" in line for line in lines), lines


def test_the_revision_window_is_named_in_the_line() -> None:
    """Строка называет границу утверждения: живого нет ИМЕННО среди этих задач."""
    assert str(debt.CLOSED_WINDOW) in debt.shape_report([], [], [])[1]


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
    left, _ = debt.unlooked_debt("o/r", "token")
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
    lines = debt.shape_report([], live, [])
    head = next(line for line in lines if line.startswith("закрыто при живых"))
    assert head.startswith("закрыто при живых единицах: 1"), head
    said = " ".join(lines)
    assert "#99" in said and "#3" in said, "старая запись исчезла из вывода"
    assert "до счётчика пунктов" in said and task_shape.ITEMS_SINCE in said


@pytest.mark.parametrize(
    ("unknown", "outcome"),
    [([], "EXIT_OK"), ([f"#6 — работа ({debt.hail.UNSAID_SPENT})"], "EXIT_PARTIAL")],
    ids=["всё-прочитано", "слияние-не-сказано"],
)
def test_a_fully_read_debt_is_clean(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unknown: list[str],
    outcome: str,
) -> None:
    """Все источники долга прочитаны — чистый исход, а не «частично».

    Несказанное состояние слияния — источник 1 прочитан не весь, и это тот же
    исход «прочитано не всё»: строка без кода проходила зелёной (взгляд на #1267).

    «Прочитано всё» и «часть неизвестна» — разные состояния, и второе у этого
    шага уже прогонялось, а первое было объявлено и не проверялось ни разу
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    """
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(debt, "open_listed", lambda repo, token: [])
    monkeypatch.setattr(debt, "findings_debt", lambda repo, token, listed: [])
    monkeypatch.setattr(debt, "unlooked_debt", lambda repo, token, listed: ([], {}))
    monkeypatch.setattr(debt, "branch_debt", lambda repo, token, listed: ([], []))
    monkeypatch.setattr(debt, "closed_issues", lambda repo, token: [])
    monkeypatch.setattr(
        debt, "inbox_body", lambda repo, token, closed, listed: ("правила: осталось 0", "", None)
    )
    monkeypatch.setattr(debt, "stuck_changes", lambda repo, token: ([], unknown, []))
    monkeypatch.setattr(debt, "looks_done", lambda issues: [])
    monkeypatch.setattr(debt.items_left, "look", lambda issues, opener: ([], []))
    monkeypatch.setattr(debt.task_shape, "without_a_checklist", lambda issues: [])
    monkeypatch.setattr(debt.task_shape, "closed_with_live_units", lambda closed: [])
    monkeypatch.setattr(debt, "rules_debt", lambda inbox: (0, 0, 0))
    monkeypatch.setattr(debt, "contract_note", lambda inbox: "")
    # ПОРОГ ПОКРЫТИЯ ТОЖЕ ПОДДЕЛЫВАЕТСЯ, И ЭТО НЕ ФОРМАЛЬНОСТЬ. Он читает ряд
    # прогонов у площадки, и без подделки проверка уходила бы в СЕТЬ. Нашёл
    # внешний взгляд на #568.
    monkeypatch.setattr(
        debt.coverage_floor,
        "look",
        lambda repo, token: debt.coverage_floor.Floor(
            day="2026-09-20", now=88.6, floor=88.6, days=4
        ),
    )

    # СТРАЖ СУДИТ ПОХОД В СЕТЬ, А НЕ ЦВЕТ. Отказ порога `debt` ловит и печатает
    # «не прочитан», оставляя исход зелёным: снятие подделки цвета НЕ меняет, и
    # проверка «исход зелёный» о сети не говорит ничего. Предмет здесь — сам
    # вызов, и поймано это откатом, который не покраснел
    # ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    def no_network(*_a: object, **_k: object) -> None:
        raise AssertionError("изолированный прогон ушёл в сеть")

    monkeypatch.setattr(debt.coverage_floor.ghrest, "request", no_network)
    assert debt.main(["--repo", "o/r"]) == getattr(debt, outcome)
    out = capsys.readouterr().out
    assert "слито без внешнего взгляда: 0" in out
    # ИСЧЕРПАННЫЙ БЮДЖЕТ ВИДЕН В ВЫВОДЕ, А НЕ ТОЛЬКО В ЧИСЛЕ ЗАПРОСОВ (взгляд на
    # #1306): причину несёт строка изменения, и заголовок её не перебивает.
    for said in unknown:
        assert said in out, f"строка несказанного слияния не напечатана: {said}"
    assert "ещё считает" not in out


def test_the_bare_tasks_are_counted_even_at_zero() -> None:
    """Счёт задач без меток печатается и нулём: пустая строка неотличима от выключенного (142)."""
    lines = debt.shape_report([], [], [])
    assert any(line.startswith("задач без зоны или рода: 0") for line in lines)
    bare = [debt.task_shape.Bare(642, "инвентарь", ("зона",))]
    lines = debt.shape_report([], [], bare)
    assert "задач без зоны или рода: 1 — метки ставит автор (#655)" in lines
    assert "  #642 — инвентарь · нет: зона" in lines


def test_a_silent_platform_is_the_broken_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка молчит на чтении задач — исход «шаг не отработал», а не «долга нет».

    Прежде этот исход засчитывался прогнанным по чужому `assert len(lines) == 2`
    в этом же наборе: распознаватель исходов узнаёт код по ЧИСЛУ. Как только
    строк стало три, выяснилось, что по имени его не прогонял никто.
    """

    def refuse(*_: object, **__: object) -> None:
        raise debt.ghrest.TransportError("502")

    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(debt, "open_listed", lambda repo, token: [])
    monkeypatch.setattr(debt, "findings_debt", lambda repo, token, listed: [])
    monkeypatch.setattr(debt, "unlooked_debt", lambda repo, token, listed: ([], {}))
    monkeypatch.setattr(debt, "branch_debt", lambda repo, token, listed: ([], []))
    monkeypatch.setattr(debt, "closed_issues", refuse)
    assert debt.main(["--repo", "o/r"]) == debt.EXIT_BROKEN


def test_a_broken_label_set_is_the_broken_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Объявление меток не разбирается — роды взять неоткуда, и это отказ шага, а не «голых нет»."""
    monkeypatch.setenv("GH_TOKEN", "токен")
    for name in ("closed_issues", "open_listed"):
        monkeypatch.setattr(debt, name, lambda repo, token: [])
    monkeypatch.setattr(debt, "findings_debt", lambda repo, token, listed: [])
    monkeypatch.setattr(debt, "unlooked_debt", lambda repo, token, listed: ([], {}))
    monkeypatch.setattr(debt, "branch_debt", lambda repo, token, listed: ([], []))
    monkeypatch.setattr(debt, "inbox_body", lambda repo, token, closed, listed: ("", "", None))
    monkeypatch.setattr(debt, "stuck_changes", lambda repo, token: ([], [], []))
    broken = tmp_path / "labels.yml"
    broken.write_text("не список меток\n", encoding="utf-8")
    real_load = debt.labels.load

    def load_broken(path: Path = broken) -> list[object]:
        return list(real_load(path))

    monkeypatch.setattr(debt.labels, "load", load_broken)
    assert debt.main(["--repo", "o/r"]) == debt.EXIT_BROKEN


def test_a_closed_inbox_does_not_claim_a_missed_run() -> None:
    """Старые закрытые «входящие» — не пропуск, старые открытые — пропуск (#980).

    Заход каталога закрытую задачу не пишет, и её дата стоит с закрытия:
    30.09.2026 план называл заход пропущенным при зелёных прогонах подряд.
    """
    now = datetime(2026, 9, 30, 21, 0, tzinfo=UTC)
    old = "2026-09-27T12:05:00Z"
    closed = debt.inbox_age(old, debt.CLOSED_INBOX, now)
    opened = debt.inbox_age(old, "", now)
    assert debt.STALE_NOTE not in closed and debt.CLOSED_LATE in closed
    assert debt.STALE_NOTE in opened and debt.CLOSED_LATE not in opened
    fresh = debt.inbox_age("2026-09-30T20:00:00Z", debt.CLOSED_INBOX, now)
    assert debt.CLOSED_LATE not in fresh


def test_the_open_list_is_read_once_and_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    """Список открытых записей читается ОДИН раз и уходит всем пяти счётам.

    ЗАМЕР 03.10.2026 (#1065): шаг читал `issues?state=open` пять раз за
    прогон — четыре поиска живой задачи и счёт по пунктам, — и каждый раз
    тратил запрос квоты на тот же ответ.
    """
    shared: list[dict[str, Any]] = []
    reads: list[str] = []
    seen: list[object] = []

    def listed(repo: str, token: str) -> list[dict[str, Any]]:
        reads.append(repo)
        return shared

    def keep(result: object) -> Callable[..., object]:
        def take(*args: object) -> object:
            seen.append(args[-1])
            return result

        return take

    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(debt, "open_listed", listed)
    monkeypatch.setattr(debt, "findings_debt", keep([]))
    monkeypatch.setattr(debt, "unlooked_debt", keep(([], {})))
    monkeypatch.setattr(debt, "branch_debt", keep(([], [])))
    monkeypatch.setattr(debt, "closed_issues", lambda repo, token: [])
    monkeypatch.setattr(debt, "inbox_body", keep(("", "", None)))
    monkeypatch.setattr(debt, "stuck_changes", lambda repo, token: ([], [], []))
    real_open = debt.open_issues

    def counted_open(given: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen.append(given)
        opened: list[dict[str, Any]] = real_open(given)
        return opened

    monkeypatch.setattr(debt, "open_issues", counted_open)
    monkeypatch.setattr(
        debt.coverage_floor,
        "look",
        lambda repo, token: debt.coverage_floor.Floor(
            day="2026-10-03", now=88.6, floor=88.6, days=4
        ),
    )
    debt.main(["--repo", "o/r"])
    assert reads == ["o/r"], f"список прочитан {len(reads)} раз"
    assert len(seen) == 5 and all(one is shared for one in seen), seen


def test_a_given_list_is_searched_without_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """`live_issue_seen` с готовым списком в сеть не ходит и находит по нему же."""
    findings = load_script("findings.py")

    def no_network(*_a: object, **_k: object) -> Iterator[dict[str, Any]]:
        raise AssertionError("готовый список, а поиск ушёл в сеть")

    monkeypatch.setattr(findings.ghrest, "paginate", no_network)
    given = [{"number": 7, "body": f"x {findings.MARKER}", "updated_at": "2026-10-03"}]
    assert findings.live_issue_seen("o/r", "t", listed=given) == (7, given[0]["body"], "2026-10-03")


def test_only_named_weights_accrue_and_only_on_merged() -> None:
    """Копится лишь `ACCRUED` на слитом; дефект, без веса и чужой вес — долг (068, 045)."""
    left = [
        ("a", 1, "дефект", "x"),
        ("b", 1, "риск", "x"),
        ("c", 1, "замечание", "x"),
        ("d", 1, "без веса", "x"),
        ("e", 1, "неведомый", "x"),
        ("f", 2, "замечание", "x"),
    ]
    owed, kept = debt.accrued(left, frozenset({2}))
    assert [one[0] for one in owed] == ["a", "d", "e", "f"]
    assert [one[0] for one in kept] == ["b", "c"]
    assert set(debt.findings.WEIGHTS) >= debt.ACCRUED, "копящийся вес не из словаря весов"
    assert debt.findings.DEFECT not in debt.ACCRUED


def test_open_changes_are_the_pull_requests_of_the_listing() -> None:
    """Открытые изменения — записи с `pull_request`; задачи в счёт не идут."""
    listed = [
        {"number": 5, "pull_request": {}},
        {"number": 6},
        {"number": 7, "pull_request": {"x": 1}},
    ]
    assert debt.open_changes(listed) == frozenset({5, 7})
