"""Снисхождение перечислено таблицей и отключается режимом (правило 102).

ПОЧЕМУ ЭТО НЕ ПЕДАНТИЗМ. Послабление при сравнении — «почти совпало считается
совпавшим» — ошибается в обе стороны, и одна из сторон дорогая: слипшиеся
находки стоят ПОТЕРЯННОЙ находки. Пока послабления живут по одному в докстрингах
разных модулей, на вопрос «а это будет считаться совпадением?» нельзя ответить,
не прочитав код, — и набор таких правил перестают считать правилами.

ЧТО ДЕРЖИТ ГЕЙТ. Что всякая объявленная строка ведёт к живому имени (адрес
гниёт первым), что у каждой есть причина и замер, и что строгий режим ВЫКЛЮЧАЕТ
послабление — проверено прогоном, а не наличием флага
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

ЧЕГО НЕ ДЕРЖИТ — ПОЛНОТЫ, и это сказано вслух. Предикат «это сравнение с
послаблением» по дереву не отличим от обычного приведения регистра. Держится
сильнейшая форма: всякое пословное сходство (`SequenceMatcher`) обязано быть
объявлено. Нормализации перечислены руками, и новая может не попасть в таблицу
молча
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

module = load_script("review_findings.py")
paths = load_script("paths.py")

TABLE: Final = ROOT / paths.LENIENCY
#: Замер: день, названный числом, — та же форма, что у расписаний и списка
#: перезапуска, и по той же причине (005).
MEASURED: Final = re.compile(r"\d{2}\.\d{2}\.\d{4}")
#: Сильнейшая форма послабления: пословное сходство. Её и держит гейт полноты.
SIMILARITY: Final = "SequenceMatcher"


def table() -> list[dict[str, Any]]:
    """Объявленные послабления."""
    said = json.loads(TABLE.read_text(encoding="utf-8"))
    return list(said.get("allowed") or [])


def names_of(path: Path) -> set[str]:
    """Имена верхнего уровня модуля: функции, классы, присваивания."""
    found: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            found.update(one.id for one in node.targets if isinstance(one, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


def test_the_table_has_entries_to_judge() -> None:
    """Таблица не пуста: пустая проверяется впустую (075).

    Пустой список здесь был бы законным состоянием ровно до первого
    послабления, а оно в дереве есть — иначе не было бы и правила.
    """
    assert table(), "таблица послаблений пуста, а сравнения с послаблением в дереве есть"


@pytest.mark.parametrize("one", table(), ids=lambda one: str(one.get("symbol", "?")))
def test_every_leniency_names_where_why_and_a_measurement(one: dict[str, Any]) -> None:
    """У послабления назван адрес, что именно прощается, почему и чем замерено.

    «Почти совпало» без замера — вкус автора: порог, выбранный на глаз, снаружи
    неотличим от порога, стоящего в пустоте между замеренными значениями.
    """
    for field in ("where", "symbol", "forgives", "why", "measured"):
        assert str(one.get(field) or "").strip(), f"{one.get('symbol', '?')}: не назван «{field}»"
    assert MEASURED.search(str(one["measured"])), (
        f"{one['symbol']}: замер без дня — «{one['measured']}» (005)"
    )


@pytest.mark.parametrize("one", table(), ids=lambda one: str(one.get("symbol", "?")))
def test_every_leniency_points_at_a_living_name(one: dict[str, Any]) -> None:
    """Имя, названное в таблице, живёт по названному адресу.

    Переименование расходится с таблицей молча, и тогда таблица описывает
    дерево, которого нет, — а читает её тот, кто дереву доверяет (005, 022).
    """
    where = ROOT / str(one["where"])
    assert where.exists(), f"{one['symbol']}: адреса «{one['where']}» в дереве нет"
    assert str(one["symbol"]) in names_of(where), (
        f"«{one['symbol']}» не объявлено в {one['where']} — таблица описывает то, чего нет"
    )


def similarity_sites() -> list[tuple[str, str]]:
    """Где в дереве считают пословное сходство: (файл, объемлющая функция).

    ИМЕННО ФУНКЦИЯ, А НЕ ФАЙЛ. Первая редакция этой проверки сверяла файлы — и
    была зелена впустую: в одном файле объявлено пять послаблений, и снятие
    любого из таблицы файл из списка не убирало. Поймано откатом: он не
    покраснел
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            if SIMILARITY in body:
                found.append((path.relative_to(ROOT).as_posix(), node.name))
    return found


def test_every_word_similarity_in_the_tree_is_declared() -> None:
    """Всякое пословное сходство объявлено таблицей — это сильнейшее послабление.

    Полноты по нормализациям гейт не держит (см. модуль), но сходство держит
    целиком: именно оно решает, считать ли две РАЗНЫЕ находки одной, и именно
    его цена измеряется потерянной находкой.
    """
    declared = {(str(one["where"]), str(one["symbol"])) for one in table()}
    found = similarity_sites()
    assert found, f"в дереве нет ни одного «{SIMILARITY}» — предмет проверки не найден (075)"
    stray = [one for one in found if one not in declared]
    assert not stray, f"пословное сходство не объявлено в таблице послаблений: {stray}"


def test_the_strict_mode_forgives_nothing() -> None:
    """Строгий режим выключает послабление — проверено прогоном, а не флагом.

    Режим, объявленный и не работающий, хуже отсутствующего: на него ссылаются
    как на способ проверить подозрение, и он молча отвечает то же самое (045).
    """
    # Пара ЗАМЕРЕНА, а не подобрана на глаз: пословное сходство 0.923 при пороге
    # 0.85. Первая редакция брала перестановку слов и давала 0.471 — то есть
    # проверяла не то, что обещала, и поймано это прогоном, а не чтением (107).
    one = "шаг долга не называет причину отказа наружу"
    other = "шаг долга не называет причину отказа"
    assert module.same_finding(one, other), "замер устарел: пара перестала считаться одной находкой"
    assert not module.same_finding(one, other, strict=True), "строгий режим всё ещё прощает"


def test_the_strict_mode_reaches_the_registry() -> None:
    """Строгий режим доходит до поиска записи, а не остаётся в одной функции.

    Предикат можно посчитать верно и не применить, и снаружи это выглядит ровно
    как его отсутствие.
    """
    entries = {"abc1234": module.Entry(7, "дефект", "шаг долга не называет причину отказа наружу")}
    other = "шаг долга не называет причину отказа"
    assert module.existing_mark(entries, 7, other) == "abc1234"
    assert module.existing_mark(entries, 7, other, strict=True) is None


def test_the_table_signs_itself_as_a_deliberate_duplicate() -> None:
    """Таблица подписана дублем: канон живёт у механизма, здесь пересказ.

    Причины в таблице — пересказ докстрок, местами слово в слово. Дубль
    законный: у таблицы ДРУГОЙ читатель и другой вопрос — не «почему эта
    функция прощает вот это», а «что вообще прощает проект» (022). Но
    намеренный дубль обязан быть ПОДПИСАН
    ([071](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/071-deliberate-duplication-is-signed.md)),
    иначе следующий читатель примет пересказ за второй источник истины и
    поправит не тот. Нашёл неподписанность внешний взгляд на #406.
    """
    said = json.loads(TABLE.read_text(encoding="utf-8"))
    signed = [value for key, value in said.items() if key.startswith("_") and "071" in str(value)]
    assert signed, "таблица повторяет докстроки и дублем себя не объявляет (071)"
    only = signed[0]
    assert "границ" in only or "не ловит" in only.lower(), (
        "подпись дубля не называет, чего гейт не держит — "
        "подписанный дубль без названной цены читается как гарантия (046)"
    )
