"""Разбор вердикта ревьюера и живая задача-адресат.

Находка читается СТРОКАМИ, а не прозой (166): формулировка ревьюера меняется от
прогона к прогону, а строка — нет. Здесь проверяется именно это чтение, потому
что на нём держится всё остальное: не распознанная строка равна потерянной
находке, и потеря выглядит как «находок нет».
"""

from __future__ import annotations

from typing import Any

from tests.conftest import load_script

module = load_script("review_findings.py")


def comment(body: str) -> dict[str, Any]:
    """Комментарий в том виде, в каком его отдаёт площадка."""
    return {"body": body}


def test_fingerprint_survives_reflow() -> None:
    """Отпечаток не зависит от переносов и лишних пробелов.

    Заголовок находки переносят при правке — если бы отпечаток от этого менялся,
    снятая запись возвращалась бы следующим заходом как новая.
    """
    one = module.fingerprint("гейт не проверяет свой предмет")
    two = module.fingerprint("гейт  не проверяет\n  свой предмет")
    assert one == two
    assert len(one) == 7


def test_findings_are_read_in_order_without_repeats() -> None:
    """Находки берутся по порядку и без повторов между комментариями."""
    comments = [
        comment("НАХОДКА: первая\nтекст\nНАХОДКА: вторая"),
        comment("НАХОДКА: первая\nВЕРДИКТ: находок 2"),
    ]
    assert module.findings_of(comments) == ["первая", "вторая"]


def test_finding_survives_markdown_decoration() -> None:
    """Оформление вокруг заголовка не мешает: ревьюер пишет прозой вокруг строк."""
    assert module.findings_of([comment("НАХОДКА: **жирный заголовок**")]) == ["жирный заголовок"]


def test_last_verdict_wins() -> None:
    """Вердикт берётся последний: ревьюер обновляет свой комментарий по ходу."""
    comments = [comment("ВЕРДИКТ: находок 1"), comment("ВЕРДИКТ: находок 3")]
    assert module.verdict_of(comments) == 3


def test_absent_verdict_is_not_zero() -> None:
    """Нет строки вердикта — это не «находок нет», а отсутствие ответа (075)."""
    assert module.verdict_of([comment("просто текст")]) is None


def test_entries_survive_a_round_trip() -> None:
    """Тело живой задачи разбирается обратно в те же записи.

    Задача — единственное хранилище состояния этого механизма, и читает он его
    из собственного вывода. Значит вывод обязан разбираться обратно точно,
    иначе заметки теряются при каждом заходе.
    """
    entries = {"abc1234": (18, "первая находка"), "def5678": (21, "вторая находка")}
    parsed = module.parse_entries(module.render_body(entries))
    assert parsed == entries


def test_body_carries_the_marker() -> None:
    """Скрытый маркер в теле есть всегда: по нему задача находится снова."""
    assert module.MARKER in module.render_body({})
    assert module.MARKER in module.render_body({"abc1234": (1, "находка")})


def test_empty_body_says_so_explicitly() -> None:
    """Пустое состояние объявляется, а не выглядит как обрыв (027)."""
    assert "Пусто" in module.render_body({})


def test_resolution_line_is_recognised() -> None:
    """Строка снятия читается из тела изменения, включая отступ и регистр."""
    found = module.RESOLVED_RE.findall("текст\n  Разобрано: ABC1234 — починено\nещё")
    assert [mark.lower() for mark in found] == ["abc1234"]
