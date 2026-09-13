"""Третий случай одной формы — повод пересмотреть, и он не находится глазом.

Правило каталога
[093](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/093-seam-early-generalisation-late.md):
шов вводят рано, а общую абстракцию — по ТРЕТЬЕЙ реализации. Две одинаковые по
форме функции законны: одинаковая форма ещё не общий приём, и обобщение по
второму случаю даёт абстракцию, натянутую на один пример.

ТРЕТИЙ СЛУЧАЙ НЕ ЗАМЕЧАЮТ. Первые две реализации пишет один заход и помнит обе;
третью пишет другой заход через смену, и она выглядит первой. Замер 13.09.2026
по всем 473 функциям дерева нашёл ровно одну форму, повторённую трижды, — и это
была работа той же смены, `drift.py`: два чтения наших файлов жили давно,
третье приехало часом раньше. Глазом его не увидел никто, включая автора.

ОТКАЗ ОТ ОБОБЩЕНИЯ ЗАКОНЕН, НО ЗАПИСЫВАЕТСЯ. «Иногда три разных лучше одного
натянутого» — слова самого правила; поэтому список исключений здесь есть, и
каждое названо причиной
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
Незаписанный отказ возвращается следующим предложением — и спорят о нём заново.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path
from typing import Final

from tests.conftest import ROOT

#: Сколько операторов в теле делают функцию предметом сравнения. Короче — это
#: не «одна реализация», а один и тот же оборот речи: проверка входа, ранний
#: выход, вызов с разбором. Замер 13.09.2026: порог в пять операторов оставляет
#: 473 функции из всех, что есть в дереве.
MIN_BODY: Final = 5

#: Сколько повторений формы правило разрешает без разговора. Два — законно,
#: третье — повод пересмотреть (093).
ALLOWED_REPEATS: Final = 2

#: Формы, повторённые трижды и оставленные врозь НАМЕРЕННО: по первому адресу
#: каждой и с причиной. Список закрытый и убывающий — он называет отказ от
#: обобщения, а не прячет его.
KEPT_APART: Final[dict[str, str]] = {}


def measured() -> list[Path]:
    """Механизмы и прогоны проекта — предмет замера."""
    return sorted([*(ROOT / "scripts").glob("*.py"), *(ROOT / "tests").glob("*.py")])


def shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Форма тела без имён: сравнивается устройство, а не словарь автора.

    Имена, атрибуты и строковые значения стираются: две реализации одного
    приёма отличаются именно ими, а совпадают тем, что делают. Докстрока не
    считается телом — она объясняет, а не работает.
    """
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if len(body) < MIN_BODY:
        return None
    copy = ast.parse(ast.unparse(ast.Module(body=list(body), type_ignores=[])))
    for one in ast.walk(copy):
        if isinstance(one, ast.Name):
            one.id = "_"
        elif isinstance(one, ast.arg):
            one.arg = "_"
        elif isinstance(one, ast.Attribute):
            one.attr = "_"
        elif isinstance(one, (ast.FunctionDef, ast.AsyncFunctionDef)):
            one.name = "_"
            one.decorator_list = []
        elif isinstance(one, ast.Constant) and isinstance(one.value, str):
            one.value = "_"
    return ast.unparse(copy)


def repeated() -> dict[str, list[str]]:
    """Формы и адреса, где они встречаются, — только повторённые трижды."""
    seen: dict[str, list[str]] = collections.defaultdict(list)
    for path in measured():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            form = shape(node)
            if form is not None:
                seen[form].append(f"{path.relative_to(ROOT)}:{node.lineno} {node.name}")
    return {form: where for form, where in seen.items() if len(where) > ALLOWED_REPEATS}


def test_the_measurement_has_a_subject() -> None:
    """Предмет замера найден: функции в дереве есть (075)."""
    assert len(measured()) > 20, "механизмов и прогонов не найдено — сравнивать нечего"


def test_a_third_case_is_either_generalised_or_written_down() -> None:
    """Третья реализация одной формы обобщена либо названа причиной.

    Это НЕ запрет повторения: два раза законно, а на третий правило просит
    пересмотреть — и разрешает оставить врозь, если три разных лучше одного
    натянутого. Гейт держит именно разговор, а не единственный исход: молчание
    здесь и есть то, чего правило не допускает.
    """
    loose = {form: where for form, where in repeated().items() if where[0] not in KEPT_APART}
    assert not loose, (
        "форма повторена трижды и не обобщена:\n"
        + "\n".join("  " + "; ".join(where) for where in loose.values())
        + (
            "\n\nЛибо поднимите общее вверх (090), либо впишите первый адрес в "
            "KEPT_APART с причиной: незаписанный отказ вернётся следующим предложением."
        )
    )


def test_kept_apart_names_only_what_is_still_repeated() -> None:
    """Список исключений не переживает свой предмет.

    Запись, чья форма обобщена или исчезла, остаётся разрешением на то, чего
    больше нет, — и однажды прикроет новое повторение молча (075).
    """
    live = {where[0] for where in repeated().values()}
    stale = sorted(set(KEPT_APART) - live)
    assert not stale, f"исключение названо, а повторения больше нет: {stale}"
