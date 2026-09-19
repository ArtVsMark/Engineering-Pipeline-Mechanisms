"""Разбор вызова знает обе формы имени, а не одну.

`HTTPServer(...)` и `server.HTTPServer(...)` — один и тот же вызов, записанный
по-разному. Разбор, знающий только голое имя, пропускает второй молча: он не
отвергает и не сомневается, он просто не видит — и проверка остаётся зелёной,
ничего не проверив
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ПРИЗНАК ПРИВЯЗАН К САМОМУ `.func`, А НЕ К ТЕЛУ ФУНКЦИИ. Разница не
теоретическая: пока `ast.Attribute` и `"attr"` искались строкой по всему телу,
разбор `getattr(node.func, "id", "")` в `test_a_walk_names_its_intent.leftmost`
считался знающим обе формы — потому что `ast.Attribute` встречался в той же
функции по другому поводу, в спуске по выражению пути. Слепота была настоящей и
невидимой, и нашёл её не гейт, а сужение признака
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md),
[195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

ЧИСЕЛ ЗДЕСЬ НЕТ, И ЭТО НАМЕРЕННО. Вписанный замер разборщиков рассыхался
дважды за двое суток — «десять» становилось «22», «22» становилось «23» от
самого изменения, которое это число писало
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
Величину даёт команда, а не память::

    python -m pytest tests/test_call_forms.py -q -s --no-header \
        -k the_subject_of_this_gate_exists

ЗАЧЕМ ГЕЙТ ПРИ ПУСТОМ ДОЛГЕ. Род «форма записи не разобрана» встречался в
проекте не раз (`.rules/finding-kinds.json`), и каждый раз его находил внешний
взгляд, а не набор. Форма обязана держаться и на пустом множестве — иначе
первый же слепой разбор приедет молча
([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).

ПРЕДМЕТ ПРОВЕРЯЕТСЯ ОТДЕЛЬНО, А НЕ ПОДРАЗУМЕВАЕТСЯ. Гейт, у которого предмет
исчез, зеленеет вокруг пустоты и выглядит работающим
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: разбор, знающий обе формы, но
путающий их местами; разбор через чужой помощник, чьё тело лежит в другой
функции; и форма имени, добытая обходом `ast.walk` без чтения `.func` у
конкретного узла. Признак смотрит ТЕЛО функции на предмет чтений `.func`, и
вынесенный разбор ему невидим
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, walk

#: Где ищем разборы: набор, механизмы и перехваты перед git.
WHERE: Final = ("tests", "scripts", ".claude/hooks")
#: Поле вызова, чтение которого и делает функцию разборщиком.
THE_CALL: Final = "func"
#: Голое имя вызова: класс узла и поле, которым его читают.
BARE: Final = ("Name", "id")
#: Имя через точку: класс узла и поле, которым его читают.
THROUGH_DOT: Final = ("Attribute", "attr")


def _reads_the_call(node: ast.AST) -> bool:
    """Узел вида `<что-то>.func` — чтение имени вызова у конкретного узла."""
    return isinstance(node, ast.Attribute) and node.attr == THE_CALL


def _mentions(expr: ast.AST, node_name: str) -> bool:
    """Назван ли класс узла в выражении — `ast.Name`, `Name`, `ast.Name | ...`."""
    return any(
        (isinstance(n, ast.Attribute) and n.attr == node_name)
        or (isinstance(n, ast.Name) and n.id == node_name)
        for n in ast.walk(expr)
    )


def forms_of(fn: ast.FunctionDef) -> tuple[bool, bool]:
    """Какие формы имени разбираются ИМЕННО у `.func`: (голое, через точку).

    Три записи разбора, и все три — про один и тот же узел:
    `<X.func>.id`, `isinstance(<X.func>, ast.Name)`, `getattr(<X.func>, "id")`.
    Четвёртая, `match <X.func>: case ast.Name()`, читается тоже.
    """
    bare = dot = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Attribute) and _reads_the_call(n.value):
            bare |= n.attr == BARE[1]
            dot |= n.attr == THROUGH_DOT[1]
        if isinstance(n, ast.Call):
            called = getattr(n.func, "id", "") or getattr(n.func, "attr", "")
            if called == "isinstance" and len(n.args) == 2 and _reads_the_call(n.args[0]):
                bare |= _mentions(n.args[1], BARE[0])
                dot |= _mentions(n.args[1], THROUGH_DOT[0])
            if called == "getattr" and len(n.args) > 1 and _reads_the_call(n.args[0]):
                got = n.args[1]
                if isinstance(got, ast.Constant):
                    bare |= got.value == BARE[1]
                    dot |= got.value == THROUGH_DOT[1]
        if isinstance(n, ast.Match) and _reads_the_call(n.subject):
            for case in n.cases:
                bare |= _mentions(case.pattern, BARE[0])
                dot |= _mentions(case.pattern, THROUGH_DOT[0])
    return bare, dot


def parsers() -> list[tuple[Path, ast.FunctionDef]]:
    """Функции, разбирающие ИМЯ вызова, — предмет этой проверки.

    Чтения `.func` мало: спуск по выражению (`node = node.func`) вызов не
    разбирает, а сокращает. Предмет — те, кто у `.func` спрашивает хотя бы одну
    форму имени.
    """
    found: list[tuple[Path, ast.FunctionDef]] = []
    for where in WHERE:
        for path in walk(ROOT / where, "*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef) and any(forms_of(fn)):
                    found.append((path, fn))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Разборов имени вызова нет — отказ, а не «все знают обе формы» (075)."""
    found = parsers()
    print(f"\nразборщиков имени вызова: {len(found)}")
    for path, fn in found:
        bare, dot = forms_of(fn)
        mark = ("голое" if bare else "  —  ") + " " + ("точка" if dot else "  —  ")
        print(f"  {path.relative_to(ROOT)}:{fn.lineno} {mark} {fn.name}")
    assert found, (
        "в дереве не нашлось ни одной функции, разбирающей имя вызова — предмет"
        " проверки исчез, и зелёное здесь ничего не значит"
    )


def test_a_call_parser_knows_both_forms_of_the_name() -> None:
    """Разбор, знающий голое имя, знает и вызов через точку.

    Обратное молчаливо: `server.HTTPServer(…)` проходит мимо, проверка зелена, и
    отличить её от работающей нечем. Род «форма записи не разобрана» находил в
    этом проекте внешний взгляд, а не набор.
    """
    blind = [
        f"{path.relative_to(ROOT)}:{fn.lineno} — {fn.name}"
        for path, fn in parsers()
        if forms_of(fn) == (True, False)
    ]
    assert not blind, (
        "разбор знает вызов только голым именем — запись через точку пройдёт молча"
        " (045):\n  " + "\n  ".join(blind) + "\n  Добавьте ветку ast.Attribute либо"
        " возьмите общий разбор у соседа."
    )


#: Записи, которые РАЗБИРАЮТ имя вызова — у самого `.func`, все четыре формы.
PARSES: Final = (
    ("класс узла", "isinstance(node.func, ast.Name)", (True, False)),
    ("класс через точку", "isinstance(node.func, ast.Attribute)", (False, True)),
    ("оба класса разом", "isinstance(node.func, ast.Name | ast.Attribute)", (True, True)),
    ("поле голым", 'getattr(node.func, "id", "")', (True, False)),
    ("поле через точку", 'getattr(node.func, "attr", "")', (False, True)),
    ("чтение напрямую", "x = node.func.id", (True, False)),
    ("чтение через точку", "x = node.func.attr", (False, True)),
    (
        "сопоставление",
        "match node.func:\n        case ast.Name():\n            pass",
        (True, False),
    ),
)

#: Записи, в которых те же слова стоят НЕ у `.func`. Каждая — ложное
#: срабатывание прежнего признака, искавшего их строкой по всему телу.
NOT_PARSES: Final = (
    ("чужой узел", "isinstance(node, ast.Name)"),
    ("чужое поле", 'getattr(node, "id", "")'),
    ("спуск по выражению", "node = node.func"),
    ("литерал в прозе", 'msg = "ast.Attribute и attr"'),
    ("поле у соседа", "x = node.value.attr"),
    ("своё имя поля", "x = other.func.name"),
)


def _one(source: str) -> ast.FunctionDef:
    """Функция из написанного руками текста — вход, которого механизм не строит."""
    body = "\n".join("    " + line if line else line for line in source.splitlines())
    fn = ast.parse(f"def сам(node):\n{body}\n").body[0]
    assert isinstance(fn, ast.FunctionDef)
    return fn


def test_every_way_of_writing_the_parse_is_seen() -> None:
    """Все четыре записи разбора видны — иначе функция уходит из предмета ВОВСЕ.

    Сужение предмета выглядит зелёным вердиктом: гейт не судит того, кого не
    видит, и молчит об этом
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    for name, source, want in PARSES:
        assert forms_of(_one(source)) == want, f"запись «{name}» разобрана неверно: {source}"


def test_the_same_words_away_from_the_call_are_not_a_parse() -> None:
    """Те же слова НЕ у `.func` разбором не считаются — вторая половина (051).

    Без неё признак неотличим от «в теле упомянуто слово»: такой засчитывает
    прозу, спуск по выражению и разбор соседнего узла. Ровно так слепота
    `leftmost` и оставалась невидимой
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    for name, source in NOT_PARSES:
        assert forms_of(_one(source)) == (False, False), (
            f"«{name}» принято за разбор имени вызова: {source}"
        )
