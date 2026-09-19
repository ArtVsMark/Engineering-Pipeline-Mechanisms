"""Разбор вызова знает обе формы имени, а не одну.

`HTTPServer(...)` и `server.HTTPServer(...)` — один и тот же вызов, записанный
по-разному. Разбор, знающий только голое имя, пропускает второй молча: он не
отвергает и не сомневается, он просто не видит — и проверка остаётся зелёной,
ничего не проверив
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЗАЧЕМ ГЕЙТ ПРИ ПУСТОМ ДОЛГЕ. Слепых разборов в дереве НОЛЬ — замер 18.09.2026 по
десяти функциям, разбирающим вызов. Гейт стоит не ради починки, а чтобы не
появилась одиннадцатая: род «форма записи не разобрана» встречен трижды
(`.rules/finding-kinds.json`), и все три раза его находил внешний взгляд, а не
набор. Форма обязана держаться и на пустом множестве — иначе первый же слепой
разбор приедет молча
([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).

ПРЕДМЕТ ПРОВЕРЯЕТСЯ ОТДЕЛЬНО, А НЕ ПОДРАЗУМЕВАЕТСЯ. Гейт, у которого предмет
исчез, зеленеет вокруг пустоты и выглядит работающим
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: разбор, знающий обе формы, но
путающий их местами, и разбор через чужой помощник, чьё тело лежит в другой
функции. Признак смотрит ТЕЛО функции, и вынесенный разбор ему невидим
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, walk

#: Где ищем разборы: набор, механизмы и перехваты перед git.
WHERE: Final = ("tests", "scripts", ".claude/hooks")
#: Обе формы имени у вызова: `имя(...)` и `что.имя(...)`.
BARE: Final = "ast.Name"
THROUGH_DOT: Final = "ast.Attribute"
#: По чему узнаётся, что функция вообще разбирает вызов.
PARSES_A_CALL: Final = ".func"


def parsers() -> list[tuple[Path, ast.FunctionDef]]:
    """Функции дерева, которые разбирают вызов, — предмет этой проверки."""
    found: list[tuple[Path, ast.FunctionDef]] = []
    for where in WHERE:
        for path in walk(ROOT / where, "*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "ast.Call" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.FunctionDef) and PARSES_A_CALL in ast.unparse(node):
                    found.append((path, node))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Разборов вызова нет — отказ, а не «все знают обе формы» (075)."""
    assert parsers(), (
        "в дереве не нашлось ни одной функции, разбирающей вызов — предмет проверки"
        " исчез, и зелёное здесь ничего не значит"
    )


def test_a_call_parser_knows_both_forms_of_the_name() -> None:
    """Разбор, знающий голое имя, знает и вызов через точку.

    Обратное молчаливо: `server.HTTPServer(…)` проходит мимо, проверка зелена, и
    отличить её от работающей нечем. Род «форма записи не разобрана» встречен
    трижды — и все три раза его находил внешний взгляд, а не набор.
    """
    blind = [
        f"{path.relative_to(ROOT)}:{node.lineno} — {node.name}"
        for path, node in parsers()
        if BARE in (body := ast.unparse(node)) and THROUGH_DOT not in body
    ]
    assert not blind, (
        "разбор знает вызов только голым именем — запись через точку пройдёт молча"
        " (045):\n  " + "\n  ".join(blind) + "\n  Добавьте ветку ast.Attribute либо"
        " возьмите общий разбор у соседа."
    )
