"""Ссылка из оригинала в копию: только картинкой, никогда текстом.

Связь источника с витриной односторонняя. Ссылка из оригинала в копию уводит
читателя на заведомо более старое — витрина пересобирается прогоном и отстаёт от
дерева всегда, — а полноту источника начинают мерить по чужому справочнику
([089](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/089-never-link-from-the-original-to-its-copy.md)).

ЧЕМ КАРТИНКА ОТЛИЧАЕТСЯ ОТ ССЫЛКИ, И ПОЧЕМУ РАЗНИЦА НЕ КОСМЕТИЧЕСКАЯ. Значок
показывает ЧИСЛО и никуда не ведёт: читатель остаётся в дереве. Ссылка текстом
уводит — и уводит на копию, собранную прошлым прогоном. Поэтому разрешена ровно
одна форма: имя внутри цели картинки. Тот же предикат держит и «значок показан»
(`tests/conftest.py`), и по той же причине: проверка ОТНОШЕНИЯ через присутствие
подстроки зеленеет там, где отношения нет
([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН: документов в дереве 504, адресов
своего производного — шесть, все шесть картинкой, текстом ноль. То есть
требование исполнялось и не держалось ничем: соседний гейт
(`scripts/check_derived_refs.py`) проверяет ОБРАТНОЕ — что названное производное
нарисовано, — и ссылку текстом пропускает как законную
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

РАЗБОР АДРЕСА НЕ ЗАВОДИТСЯ ЗАНОВО: он живёт у `check_derived_refs.py`, который
знает обе формы адреса площадки — `raw.githubusercontent.com` и `blob|raw`. Вторая
копия разошлась бы с первой молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: ссылку на производное ЧУЖОГО
проекта. Там оригинал не наш, и правило говорит о связи со своей копией; сосед,
ссылающийся на нашу витрину, поступает законно — ему она и адресована
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, load_script, walk_deep

der = load_script("check_derived_refs.py")
paths = load_script("paths.py")

#: Цель картинки: `![подпись](адрес)`. Ссылка без восклицательного знака — не она.
IMAGE: Final = re.compile(r"!\[[^\]]*\]\([^)\s]*\)")
#: Наше имя у площадки — ВЛАДЕЛЕЦ И РЕПОЗИТОРИЙ ЦЕЛИКОМ, а не подстрока.
#: Сравнение подстрокой принимало за своё чужой `Somebody/…-Mechanisms-Fork`:
#: у соседа по имени наша копия не наша, и ссылка на неё законна
#: ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
#: Нашёл внешний взгляд.
OURS: Final = "ArtVsMark/Engineering-Pipeline-Mechanisms"


def documents() -> list[Path]:
    """Отслеживаемые документы дерева."""
    return sorted(path for path in walk_deep(ROOT, "*.md") if ".git" not in path.parts)


def addresses() -> list[tuple[Path, int, str, bool]]:
    """Адреса СВОЕГО производного в документах: файл, строка, ветка, внутри картинки."""
    found: list[tuple[Path, int, str, bool]] = []
    for path in documents():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in der.DERIVED_RE.finditer(line):
                where = match["rawrepo"] or match["repo"] or ""
                ref = match["rawref"] or match["ref"] or ""
                if where.lower() != OURS.lower() or ref == paths.TRUNK:
                    continue
                inside = any(
                    shot.start() <= match.start() and match.end() <= shot.end()
                    for shot in IMAGE.finditer(line)
                )
                found.append((path, number, ref, inside))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Адресов производного нет — отказ, а не «чисто» (075)."""
    assert documents(), "документов в дереве не нашлось — сверять нечего"
    assert addresses(), (
        "ни один документ не называет своего производного — предмет проверки не найден:"
        " витрина либо не показывается вовсе, либо адрес её изменился"
    )


def test_a_derived_address_is_only_ever_an_image() -> None:
    """Адрес производного стоит целью КАРТИНКИ, а не ссылкой в текст."""
    away = [
        f"{path.relative_to(ROOT)}:{number} — ветка «{ref}» названа ссылкой, а не картинкой"
        for path, number, ref, inside in addresses()
        if not inside
    ]
    assert not away, (
        "ссылка из оригинала в копию уводит читателя на заведомо более старое (089):\n  "
        + "\n  ".join(away)
        + "\n  Значок показывают картинкой — он несёт число и никуда не ведёт."
        "\n  За содержимым читателя отправляют к источнику в дереве, а не к витрине."
    )


def test_a_neighbours_repository_is_not_taken_for_ours() -> None:
    """Чужой репозиторий с похожим именем своим не считается.

    Сравнение подстрокой принимало за своё `Somebody/…-Mechanisms-Fork`: у
    соседа по имени наша копия не наша, и ссылка на неё законна — правило о
    связи оригинала с копией говорит о СВОЕЙ копии. Нашёл внешний взгляд.
    """
    assert OURS.count("/") == 1, "своё имя названо без владельца — сравнивать будет нечего"
    for foreign in (
        "Somebody/Engineering-Pipeline-Mechanisms-Fork",
        "Other/Engineering-Pipeline-Mechanisms",
        "ArtVsMark/Engineering-Pipeline-Mechanisms-Docs",
    ):
        assert foreign.lower() != OURS.lower(), f"{foreign} принят за своё"
