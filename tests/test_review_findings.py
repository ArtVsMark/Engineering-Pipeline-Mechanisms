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
        comment("НАХОДКА[дефект]: первая\nтекст\nНАХОДКА[риск]: вторая"),
        comment("НАХОДКА[дефект]: первая\nВЕРДИКТ: находок 2"),
    ]
    assert module.findings_of(comments) == [("дефект", "первая"), ("риск", "вторая")]


def test_finding_survives_markdown_decoration() -> None:
    """Оформление вокруг заголовка не мешает: ревьюер пишет прозой вокруг строк."""
    assert module.findings_of([comment("НАХОДКА[замечание]: **жирный заголовок**")]) == [
        ("замечание", "жирный заголовок")
    ]


def test_a_finding_without_a_weight_says_so() -> None:
    """Вес не назван — так и записано, а не подставлен самый лёгкий.

    Подстановка решила бы за ревьюера в сторону, удобную разбирающему, и
    сделала бы «он не назвал» неотличимым от «он назвал лёгкое» (154).
    """
    assert module.findings_of([comment("НАХОДКА: без веса")]) == [(module.UNWEIGHED, "без веса")]


def test_a_weight_outside_the_scale_is_not_a_weight() -> None:
    """Слово вне шкалы весом не считается и к ближайшему не приводится.

    Шкала закрытая, как роды у фрагментов журнала: приведение «критично» к
    «дефекту» — догадка механизма о том, что имел в виду ревьюер (068).
    """
    assert module.findings_of([comment("НАХОДКА[критично]: чужое слово")]) == [
        (module.UNWEIGHED, "чужое слово")
    ]


def test_the_heaviest_finding_is_written_first() -> None:
    """Порядок записей — по весу, а не по приходу.

    Иначе разбирающий читает двадцать записей подряд, чтобы понять, с какой
    начинать, и порядок разбора становится делом настроения (053).
    """
    body = module.render_body(
        {
            "aaaaaaa": module.Entry(1, "замечание", "лёгкая"),
            "bbbbbbb": module.Entry(2, "дефект", "тяжёлая"),
            "ccccccc": module.Entry(3, module.UNWEIGHED, "неназванная"),
        }
    )
    order = [line for line in body.splitlines() if line.startswith("- `")]
    assert "тяжёлая" in order[0] and "лёгкая" in order[1] and "неназванная" in order[2], body


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
    entries = {
        "abc1234": module.Entry(18, "дефект", "первая находка"),
        "def5678": module.Entry(21, "замечание", "вторая находка"),
    }
    parsed = module.parse_entries(module.render_body(entries))
    assert parsed == entries


def test_body_carries_the_marker() -> None:
    """Скрытый маркер в теле есть всегда: по нему задача находится снова."""
    assert module.MARKER in module.render_body({})
    assert module.MARKER in module.render_body({"abc1234": module.Entry(1, "риск", "находка")})


def test_empty_body_says_so_explicitly() -> None:
    """Пустое состояние объявляется, а не выглядит как обрыв (027)."""
    assert "Пусто" in module.render_body({})


def test_resolution_line_is_recognised() -> None:
    """Строка снятия читается из тела изменения, включая отступ и регистр.

    Разбор общий с шагом открытия (`changerefs`): тот переносит строку из
    коммита в тело изменения, этот читает её оттуда. Второе чтение той же
    строки разошлось бы с первым молча — и снятие терялось бы по дороге.
    """
    found = module.changerefs.resolved_in("текст\n  Разобрано: ABC1234 — починено\nещё")
    assert found == ["abc1234"]
