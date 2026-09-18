"""Собиратель находок доходит до конца обхода, а не возвращается из середины.

Механизм, который копит находки и возвращает их списком, обязан просмотреть ВСЁ:
выход из середины цикла отдаёт первую находку и молчит об остальных, а снаружи
это выглядит как «нашлась одна»
([159](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/159-a-set-verdict-comes-after-the-last-case.md)).

ЦЕНА ИМЕННО В МОЛЧАНИИ. Читатель чинит названное и заходит снова — и получает
вторую находку, которую механизм видел с самого начала. Два прохода вместо
одного там, где работа одна; а если находок пять, заходов пять.

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Собирателей в дереве 53,
возвратов из середины их циклов — НОЛЬ. То есть требование исполнялось и
держалось внимательностью: пятьдесят четвёртый собиратель с `return` в цикле не
покраснел бы нигде
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
Держало его до сих пор `tests/test_gates_complete.py::test_both_failures_are_named`
— но это прогон ОДНОГО механизма, а утверждение было о дереве.

СОБИРАТЕЛЬ УЗНАЁТСЯ ПО ТОМУ, ЧТО ДЕЛАЕТ, а не по имени: копит в список
(`.append`/`.extend`) и этим же списком заканчивается. Имя бывает любым —
`findings`, `verdict`, `touched`, — и список имён отстал бы от дерева молча
([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).

СОСЕД У СУЖЕНИЯ НАЗВАН: `break` в предмет НЕ входит. Замер того же дня: их три,
и все три кончают РАЗБОР, а не обход — поток полей `-z` иссяк
(`check_new_is_tested`, `check_decisions_edit`), хвостовой блок кончился пустой
строкой (`squash_body`). Отличить «разбор закончился» от «обход оборван» —
суждение о смысле цикла, и предикатом его не взять
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md),
[057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.conftest import ROOT

#: Где живут механизмы, чьи находки читает человек.
WHERE: Final = ("scripts", "packages/transport", ".claude/hooks")
#: Чем копят находки.
COLLECTS: Final = frozenset({"append", "extend"})


def collectors() -> list[tuple[Path, ast.FunctionDef]]:
    """Функции, которые КОПЯТ находки в список и им же заканчиваются."""
    found: list[tuple[Path, ast.FunctionDef]] = []
    for where in WHERE:
        for path in sorted((ROOT / where).glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef) or not node.body:
                    continue
                piles = {
                    one.func.value.id
                    for one in ast.walk(node)
                    if isinstance(one, ast.Call)
                    and isinstance(one.func, ast.Attribute)
                    and one.func.attr in COLLECTS
                    and isinstance(one.func.value, ast.Name)
                }
                last = node.body[-1]
                if (
                    isinstance(last, ast.Return)
                    and isinstance(last.value, ast.Name)
                    and last.value.id in piles
                ):
                    found.append((path.relative_to(ROOT), node))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    assert collectors(), "собирателей находок в дереве не нашлось — сверять нечего"


def test_no_collector_returns_from_inside_its_loop() -> None:
    """Собиратель не возвращается из середины обхода.

    Вложенные функции из предмета исключены: их `return` возвращает ИХ, а не
    обход снаружи. Без этого предикат отверг бы всякий собиратель, у которого
    внутри цикла объявлен помощник, — то есть красил бы исправное (044).
    """
    early: list[str] = []
    for path, node in collectors():
        inner = {
            id(one)
            for body in ast.walk(node)
            if isinstance(body, ast.FunctionDef | ast.Lambda) and body is not node
            for one in ast.walk(body)
        }
        for loop in ast.walk(node):
            if not isinstance(loop, ast.For | ast.While):
                continue
            early += [
                f"{path}:{one.lineno} — {node.name} возвращается из цикла"
                for one in ast.walk(loop)
                if isinstance(one, ast.Return) and id(one) not in inner
            ]
    assert not early, (
        "собиратель находок возвращается из середины обхода (159):\n  "
        + "\n  ".join(sorted(set(early)))
        + "\n  Копите находки до конца и решайте по списку: выход из середины"
        " отдаёт первую и молчит об остальных, а читатель зайдёт ещё раз."
    )


def test_a_break_is_not_judged_here_and_the_neighbour_exists() -> None:
    """Граница названа замером: `break` в дереве есть, и он не предмет.

    Исчезнут такие циклы — довод о границе станет пустым, и это увидит проверка,
    а не читатель докстроки
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    breaks = [
        f"{path}:{one.lineno}"
        for path, node in collectors()
        for loop in ast.walk(node)
        if isinstance(loop, ast.For | ast.While)
        for one in ast.walk(loop)
        if isinstance(one, ast.Break)
    ]
    assert breaks, "у собирателей нет ни одного `break` — довод о границе пуст"
