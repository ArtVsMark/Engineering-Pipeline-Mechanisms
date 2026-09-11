"""Форма задачи проверяется отказом: оба счёта обязаны находить предмет.

Счёт, который видели только на нуле, доказывает ровно одно — он отработал.
Поэтому здесь и находка, и граница: что именно правило считать НЕ велит.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import load_script

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
