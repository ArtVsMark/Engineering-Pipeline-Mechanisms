"""Форма задачи проверяется отказом: оба счёта обязаны находить предмет.

Счёт, который видели только на нуле, доказывает ровно одно — он отработал.
Поэтому здесь и находка, и граница: что именно правило считать НЕ велит.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script, needs_history, walk

module = load_script("task_shape.py")

PROSE = """Три независимых пункта, и ни одной галочки.

- первый
- второй
* третий
"""
BOXES = """- [ ] первый
- [x] второй
- [ ] третий
"""


def issue(number: int, body: str, *, title: str = "задача", **extra: Any) -> dict[str, Any]:
    """Задача в том виде, в каком её отдаёт площадка."""
    return {"number": number, "title": title, "body": body, **extra}


def test_three_prose_items_are_found() -> None:
    """От трёх пунктов прозой задача — кандидат на чек-лист (028)."""
    found = module.without_a_checklist([issue(1, PROSE)])
    assert [(task.number, task.items) for task in found] == [(1, 3)]


def test_two_prose_items_are_not_the_subject() -> None:
    """Один-два пункта: чек-лист дороже предмета — правило этого не просит."""
    assert module.without_a_checklist([issue(1, "- первый\n- второй\n")]) == []


def test_a_task_with_boxes_already_keeps_a_checklist() -> None:
    """Галочки есть — счёт ведётся, и прозы рядом правило не запрещает."""
    assert module.without_a_checklist([issue(1, BOXES + PROSE)]) == []


def test_an_epic_with_children_needs_no_boxes() -> None:
    """У эпика прогресс считает сам трекер: второй счёт того же разошёлся бы (022)."""
    epic = issue(7, PROSE, sub_issues_summary={"total": 8, "completed": 8})
    assert module.without_a_checklist([epic]) == []


def test_the_biggest_prose_list_comes_first() -> None:
    """Порядок — по числу пунктов: читателю нужен худший случай, а не первый."""
    found = module.without_a_checklist([issue(1, PROSE), issue(2, PROSE + "- четвёртый\n")])
    assert [task.number for task in found] == [2, 1]


def test_a_closed_task_with_open_boxes_is_found() -> None:
    """Ревизия закрытого находит живое — это и есть признак нарушения (121)."""
    found = module.closed_with_live_units([issue(5, BOXES)])
    assert [(task.number, task.unchecked) for task in found] == [(5, 2)]


def test_a_closed_epic_with_open_children_is_found() -> None:
    """Единицы эпика — подзадачи; их счёт площадка кладёт прямо в ответ."""
    epic = issue(7, "", sub_issues_summary={"total": 8, "completed": 6})
    found = module.closed_with_live_units([epic])
    assert [(task.number, task.children) for task in found] == [(7, 2)]
    assert "подзадач открыто 2" in found[0].said


def test_a_closed_task_with_everything_ticked_is_clean() -> None:
    """Всё закрыто — находки нет: счёт не обязан находить, чтобы работать."""
    done = issue(6, "- [x] один\n", sub_issues_summary={"total": 2, "completed": 2})
    assert module.closed_with_live_units([done]) == []


def test_both_kinds_of_life_are_named_at_once() -> None:
    """Пункты и подзадачи называются обе: они чинятся по-разному (154)."""
    both = issue(9, BOXES, sub_issues_summary={"total": 3, "completed": 1})
    said = module.closed_with_live_units([both])[0].said
    assert "пунктов открыто 2" in said and "подзадач открыто 2" in said


def test_a_broken_child_count_does_not_go_negative() -> None:
    """Площадка сказала «закрыто больше, чем всего» — это ноль, а не минус."""
    odd = issue(9, "", sub_issues_summary={"total": 1, "completed": 3})
    assert module.children_left(odd) == 0


def test_a_task_kept_by_a_mechanism_is_not_a_candidate() -> None:
    """Задачу, которую ведёт механизм, чек-лист не касается (нашёл владелец).

    Её тело пересобирается заново каждым заходом: галочка, поставленная рукой,
    исчезнет на следующем. А состояние её и так счётчик — записи появляются и
    уходят сами; требовать сверх этого чек-лист значит требовать второй счёт
    того же (022).
    """
    findings = load_script("findings.py")
    registry = issue(89, findings.marker("unlooked") + "\n" + PROSE)
    assert module.without_a_checklist([registry]) == []


def test_the_verdict_does_not_depend_on_how_full_the_registry_is() -> None:
    """Форма задачи не зависит от того, сколько в неё записал механизм.

    Правило 028 — о ФОРМЕ. Без границы выше счёт менялся с наполнением:
    реестр находок #23 утром 11.09.2026 считался кандидатом с тридцатью тремя
    «пунктами прозой», а к вечеру перестал — не изменившись ни формой, ни
    назначением.
    """
    findings = load_script("findings.py")
    mark = findings.marker("review-findings")
    full = issue(23, mark + "\n" + PROSE + "\n".join(f"- запись {n}" for n in range(30)))
    empty = issue(23, mark + "\nПусто — все находки названы разобранными.")
    assert module.without_a_checklist([full]) == module.without_a_checklist([empty]) == []


def test_a_human_task_with_prose_is_still_a_candidate() -> None:
    """Граница не съела предмет: задача человека с прозой по-прежнему кандидат."""
    assert [task.number for task in module.without_a_checklist([issue(182, PROSE)])] == [182]


def test_a_task_closed_before_the_counter_is_marked_as_such() -> None:
    """Закрытое до счётчика пунктов помечено (нашёл владелец вопросом).

    Отметить пункты в таких задачах было НЕЧЕМ: механизм заведён позже. Ответ
    по ним известен заранее и одинаков для всех, а счёт, который не меняется
    никогда, перестают читать (051).
    """
    early = issue(3, BOXES, closed_at="2026-09-09T10:00:00Z")
    late = issue(99, BOXES, closed_at="2026-09-12T10:00:00Z")
    found = {
        task.number: task.before_the_counter
        for task in module.closed_with_live_units([early, late])
    }
    assert found == {3: True, 99: False}


@needs_history
def test_the_boundary_is_the_day_the_mechanism_appeared() -> None:
    """Граница названа датой заведения механизма, а не круглым числом.

    `scripts/items.py`, `scripts/task_items.py` и прогон `task-items` заведены
    изменением #97; задачи первого дня закрыты сутками раньше. Дата берётся
    оттуда, и проверка держит связь: сдвинуть её «на глаз» не выйдет.
    """
    from tests.conftest import ROOT

    born = subprocess.run(
        ["git", "log", "--reverse", "--format=%ad", "--date=short", "--", "scripts/items.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    ).stdout.split("\n")[0]
    if not born:
        pytest.skip("история обрезана: дату заведения механизма взять неоткуда")
    assert born == module.ITEMS_SINCE, f"граница {module.ITEMS_SINCE}, а механизм заведён {born}"


def test_a_task_closed_without_a_date_is_counted_as_fresh() -> None:
    """Даты закрытия нет — задача считается свежей, а не списанной в старые.

    Ошибка в сторону лишнего взгляда: неизвестность не должна выводить запись
    из ревизии (045).
    """
    said = module.closed_with_live_units([issue(50, BOXES)])
    assert said[0].before_the_counter is False


def labelled(number: int, *names: str, body: str = "Предмет.") -> dict[str, Any]:
    """Задача с метками в том виде, в каком их отдаёт площадка."""
    return issue(number, body, labels=[{"name": name} for name in names])


def test_a_task_without_zone_or_kind_is_named_with_what_it_lacks() -> None:
    """Задаче без зоны или рода называется, ЧЕГО именно не хватает (#655).

    Замер 23.09.2026: пять задач смены провисели без меток с утра до 13:17 —
    заметил владелец, а не механизм.
    """
    found = module.unlabelled(
        [
            labelled(1),
            labelled(2, "area/gates"),
            labelled(3, "bug"),
            labelled(4, "area/core", "enhancement", "difficulty/easy"),
            labelled(5, "area/docs", "epic"),
        ],
        KINDS,
    )
    assert [(task.number, task.missing) for task in found] == [
        (1, ("зона", "род")),
        (2, ("род",)),
        (3, ("зона",)),
    ]


def test_a_live_issue_kept_by_a_mechanism_is_not_a_bare_task() -> None:
    """Реестр и план ведёт механизм — меток им не нужно, и узнаются они маркером.

    Вторая половина предиката: без неё все семь живых задач-адресатов
    называлась бы голыми, и счёт учили бы пролистывать (051).
    """
    kept = labelled(23, body=module.findings.marker("review-findings") + "\n\nреестр")
    assert module.unlabelled([kept], KINDS) == []


def test_difficulty_is_not_asked() -> None:
    """Сложность — подсказка разбирающему, а не вход механизма: её отсутствие не долг."""
    assert module.unlabelled([labelled(7, "area/merge", "tech-debt")], KINDS) == []


#: Роды в подделке — те же имена, что объявлены в файле сегодня.
KINDS = frozenset({"epic", "bug", "enhancement", "documentation", "tech-debt"})


def test_the_kinds_are_read_from_the_label_set_both_ways(tmp_path: Any) -> None:
    """Род — это метка с `kind: true` в объявлении, и только она (#655, `a226398`).

    Обе стороны: новая метка с полем попадает в род сама, метка без поля — нет.
    Прежний литерал в коде держался в одну сторону: новый род в файле в список
    не попадал, и задачи с ним молча считались бы голыми.
    """
    declared = module.labels.kinds_of(module.labels.load())
    # Не равенство с литералом — иначе второй список переехал бы из кода в
    # проверку (`eb31734`). Держится отношение: род эпика, по которому
    # `items.follow` находит эпики, обязан быть родом.
    assert module.items.EPIC_LABEL in declared, declared
    written = tmp_path / "labels.yml"
    written.write_text(
        '- name: "chore"\n  color: "cccccc"\n  description: "Уборка"\n  kind: true\n'
        '- name: "area/x"\n  color: "cccccc"\n  description: "Зона"\n',
        encoding="utf-8",
    )
    assert module.labels.kinds_of(module.labels.load(written)) == {"chore"}


def test_a_zone_cannot_be_a_kind(tmp_path: Any) -> None:
    """`kind: true` у метки `area/*` — отказ разбора: одна метка закрыла бы обе нехватки."""
    declared = tmp_path / "labels.yml"
    declared.write_text(
        '- name: "area/x"\n  color: "cccccc"\n  description: "Зона"\n  kind: true\n',
        encoding="utf-8",
    )
    with pytest.raises(module.labels.BadConfig, match="зона не может быть родом"):
        module.labels.load(declared)


def test_the_label_and_the_bare_name_agree_on_a_zone() -> None:
    """У свойства метки и у голого имени ответ о зоне один (`9218c72`)."""
    zone = module.labels.Label("area/x", "cccccc", "Зона")
    kind = module.labels.Label("bug", "cccccc", "Дефект", kind=True)
    assert zone.is_zone and module.labels.zone_named("area/x")
    assert not kind.is_zone and not module.labels.zone_named("bug")


def zone_carriers() -> tuple[set[str], str]:
    """Чем в коде можно назвать приставку зоны: имена её констант и сама приставка.

    Имя константы берётся у модуля ПО ЗНАЧЕНИЮ, а не пишется строкой:
    переименуй её — и гейт узнает новое имя сам (`48ba174`). Литерал — слово
    зоны без черты (`split("/")[0] == "area"`) и всё, что начинается с
    приставки (`fnmatch(…, "area/*")`): оба — копия.
    """
    prefix = module.labels.ZONE_PREFIX
    names = {name for name, value in vars(module.labels).items() if value == prefix}
    return names, prefix


def zone_literal(value: object, prefix: str) -> bool:
    """Строка называет зону: её слово без черты или всё, что начинается с приставки."""
    return isinstance(value, str) and (value == prefix.rstrip("/") or value.startswith(prefix))


#: Владелец упоминания, стоящего в самом определении константы: `=<имя>`.
DEFINES: Final = "="


def zone_owner(top: ast.stmt, names: set[str], prefix: str) -> str:
    """Чьё упоминание: имя функции или класса, `=<имя>` у определения, `""` — модуль.

    Определение — это ровно присваивание литерала приставки имени-носителю;
    всё прочее на уровне модуля (`is_zone = lambda n: …`) — уровень модуля, и
    прощать его значило бы прощать копию (`d459e0f`).
    """
    if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return top.name
    target: ast.expr | None = top.target if isinstance(top, ast.AnnAssign) else None
    if isinstance(top, ast.Assign) and len(top.targets) == 1:
        target = top.targets[0]
    value = getattr(top, "value", None)
    if (
        isinstance(target, ast.Name)
        and target.id in names
        and isinstance(value, ast.Constant)
        and value.value == prefix
    ):
        return DEFINES + target.id
    return ""


def zone_mentions(path: Path) -> list[tuple[str, int]]:
    """Упоминания приставки зоны в модуле: чьё оно и на какой строке.

    Носитель узнаётся и под другим именем: `from labels import ZONE_PREFIX as Z`
    добавляет `Z` к носителям этого модуля, а сам импорт — тоже упоминание
    (`f820159`).
    """
    names, prefix = zone_carriers()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    here = set(names) | {
        one.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for one in node.names
        if one.name in names and one.asname
    }
    found: list[tuple[str, int]] = []
    for top in tree.body:
        owner = zone_owner(top, names, prefix)
        # АННОТАЦИЯ ОПРЕДЕЛЕНИЯ — НЕ ОПРЕДЕЛЕНИЕ: она исполняется на уровне
        # модуля, и `ZONE_PREFIX: (lambda n: n.startswith("area/")) = "area/"`
        # прощалась бы целиком (`d648f8a`).
        aside = (
            set(ast.walk(top.annotation))
            if isinstance(top, ast.AnnAssign) and owner.startswith(DEFINES)
            else set()
        )
        for node in ast.walk(top):
            named = getattr(node, "id", None) or (
                node.attr if isinstance(node, ast.Attribute) else None
            )
            imported = isinstance(node, ast.alias) and node.name in names
            value = node.value if isinstance(node, ast.Constant) else None
            literal = zone_literal(value, prefix)
            # Имя носителя строкой — `getattr(labels, "ZONE_PREFIX")` — тот же
            # носитель, только взятый по имени (`b099b65`).
            by_name = isinstance(value, str) and value in names
            if named in here or imported or literal or by_name:
                where = "" if node in aside else owner
                found.append((where, getattr(node, "lineno", 0) or top.lineno))
    return found


def test_no_reader_keeps_its_own_zone_predicate() -> None:
    """Приставку зоны называет только определение и `labels.zone_named` — в любой форме.

    Прежняя редакция ловила одну форму — `startswith(<приставка>)` первым
    доводом — и исключала `labels.py` целиком: кортеж, `in`, срез, `fnmatch`,
    `removeprefix` и вторая копия внутри самого `labels.py` проходили
    (`d4df347`, `4ddf650`, `e184f12`, `161710b`). Здесь судится НОСИТЕЛЬ
    приставки, а не форма вызова: без константы или литерала приставку не
    назвать ничем. Замер 23.09.2026 по дереву: константа упомянута дважды —
    определение и `zone_named`, литерал — один раз, в определении.

    Прощается ровно определение — присваивание литерала имени-носителю, — а
    не весь уровень модуля `labels.py`: модульная `lambda` или `async def` с
    приставкой — такая же копия (`d459e0f`). Носитель под другим именем
    (`from labels import ZONE_PREFIX as Z`) узнаётся по импорту (`f820159`),
    а взятый по имени строкой (`getattr(labels, "ZONE_PREFIX")`) — по строке
    (`b099b65`). Аннотация определения определением не считается (`d648f8a`).

    ГРАНИЦА: приставку, собранную из частей (`"ar" + "ea/"`), гейт не видит —
    такую запись пишут, чтобы обойти, и её ловит взгляд, а не машина (057).
    """
    names, _ = zone_carriers()
    assert names, "константы приставки зоны у labels нет — предмет гейта исчез (075)"
    allowed = {DEFINES + name for name in names} | {"zone_named"}
    outside = [
        f"{path.name}:{line}"
        for path in walk(ROOT / "scripts", "*.py")
        for owner, line in zone_mentions(path)
        if path.name != "labels.py" or owner not in allowed
    ]
    assert not outside, "приставка зоны названа вне labels.zone_named: " + ", ".join(outside)
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: гейт обязан узнать и определение, и саму
    # функцию — иначе он зелен и тогда, когда не видит ничего (`e2f6d9c`, 075).
    own = [owner for owner, _ in zone_mentions(ROOT / "scripts" / "labels.py")]
    assert any(owner.startswith(DEFINES) for owner in own), own
    assert [owner for owner in own if not owner.startswith(DEFINES)] == ["zone_named"], own
