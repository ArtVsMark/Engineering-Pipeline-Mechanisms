"""Обход настоящего дерева идёт общим обходчиком, а не голым `glob`.

Пустой обход — самая тихая из поломок набора. Проверка, идущая по списку из
дерева, при пустом списке проходит свои утверждения НОЛЬ раз и зеленеет: снаружи
она неотличима от прошедшей
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
Переименуй каталог, смени расширение, перенеси механизмы — и гейт перестанет
проверять что-либо, не сказав ни слова.

ЧТО ЗДЕСЬ УЖЕ ЗАКРЫТО ДРУГИМ. Пустую ПАРАМЕТРИЗАЦИЮ ловит настройка набора
(`empty_parameter_set_mark = fail_at_collect`). Здесь предмет второй: обход
внутри тела проверки — циклом, включением, вызовом помощника. Настройка их не
видит, потому что случай у такой проверки один и он собран.

ПОЧЕМУ ОБЩИЙ ОБХОДЧИК, А НЕ ПРЕДИКАТ «НЕПУСТОТА ГДЕ-ТО УТВЕРЖДАЕТСЯ». Признак
пробовался и ОТВЕРГНУТ замером 19.09.2026 дважды: в первой редакции он назвал
22 модуля из 34, во второй — 14 из 51, и три из семи разобранных оказались
ложными: непустота там утверждается ПРОИЗВОДНЫМ именем, а не самим обходом.
Отличить одно от другого предикатом значит повторить суждение о смысле
([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).
Обходчик же ничего не судит: он просто не отдаёт пустоту молча.

ТРИ ИМЕНИ — ТРИ НАМЕРЕНИЯ, И ОБЪЯВЛЯЮТСЯ ОНИ В ТОЧКЕ ВЫЗОВА. `walk` — предмет
проверки, пустота здесь обрыв. `walk_deep` — то же вглубь; отдельное имя, а не
довод, потому что «вглубь или нет» читатель обязан видеть, не заглядывая в
доводы. `found_by` — обход-ВОПРОС, где пустота есть ответ: «адрес не
разрешается», «производного в дереве нет». Порода видна в вызове, а не
выводится из текста.

ЗАМЕР 19.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Обходов настоящего дерева в
наборе 80 в 51 модуле, голыми `glob`/`rglob` — все 80. Перевод нашёл ОДИН
мёртвый: `test_docs_shape.py` обходил `.github/**/*.md` и не находил ничего — и
не находил с самого начала, потому что разметки в `.github/` у проекта нет.
Проверки прозы шли мимо этого каталога, и снаружи это выглядело как «всё
проверено»
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ПОДДЕЛАННОЕ ДЕРЕВО В ПРЕДМЕТ НЕ ВХОДИТ, и это замер, а не поблажка: обход по
`tmp_path` законно пуст — проверка сама кладёт туда файлы и сама знает, сколько.
Отличается он ОТНОШЕНИЕМ — корнем выражения пути, — а не именем переменной.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, walk

#: Чем обходят дерево напрямую.
BARE: Final = frozenset({"glob", "rglob", "iterdir"})
#: Общие обходчики: имя объявляет намерение (предмет, предмет вглубь, вопрос).
SHARED: Final = frozenset({"walk", "walk_deep", "found_by", "code_files"})
#: Откуда растут пути НАСТОЯЩЕГО дерева. Прочие корни — своё, поддельное.
THE_TREE: Final = "ROOT"
#: Свой модуль из предмета исключён: объявление признака неизбежно содержит
#: образец, и гейт нашёл бы сам себя (замер 18.09.2026, тот же приём у гейта
#: своей площадки).
MINE: Final = "test_a_walk_names_its_intent.py"


def leftmost(node: ast.AST) -> str:
    """Самое левое имя выражения пути: `ROOT`, `tmp_path`, `WORKFLOWS`…"""
    while isinstance(node, ast.BinOp | ast.Attribute | ast.Subscript | ast.Call):
        node = (
            node.left
            if isinstance(node, ast.BinOp)
            else (node.value if isinstance(node, ast.Attribute | ast.Subscript) else node.func)
        )
    return getattr(node, "id", "?")


def rooted_names(tree: ast.Module) -> set[str]:
    """Имена модуля, выведенные из корня дерева, — по присваиваниям."""
    found = {THE_TREE}
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign) or node.value is None:
            continue
        if leftmost(node.value) not in found:
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        found |= {one.id for one in targets if isinstance(one, ast.Name)}
    return found


def bare_walks() -> list[str]:
    """Голые обходы НАСТОЯЩЕГО дерева в наборе: файл, строка, выражение."""
    found: list[str] = []
    for path in walk(ROOT / "tests", "*.py"):
        if path.name == MINE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rooted = rooted_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in BARE or leftmost(node.func.value) not in rooted:
                continue
            found.append(f"{path.name}:{node.lineno} — {ast.unparse(node)[:60]}")
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    shared = [
        one
        for path in walk(ROOT / "tests", "*.py")
        for one in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(one, ast.Call) and getattr(one.func, "id", "") in SHARED
    ]
    assert shared, "общими обходчиками в наборе не пользуется никто — сверять нечего"


def test_no_test_walks_the_real_tree_bare() -> None:
    """Обход настоящего дерева идёт общим обходчиком, который назовёт пустоту."""
    bare = bare_walks()
    assert not bare, (
        "голый обход настоящего дерева (075):\n  "
        + "\n  ".join(bare)
        + "\n  Возьмите общий обходчик и назовите им НАМЕРЕНИЕ:"
        "\n    walk / walk_deep — обход даёт ПРЕДМЕТ проверки, пустота здесь обрыв;"
        "\n    found_by — обход-ВОПРОС, пустота здесь ответ."
        "\n  Пустота, законная по существу, объявляется причиной:"
        " walk(..., may_be_empty=«…»)."
    )


def test_a_walk_over_a_built_tree_is_not_judged(tmp_path: Path) -> None:
    """Граница названа проверкой: обход поддельного дерева законно пуст.

    Проверка сама кладёт файлы в свой корень и сама знает, сколько их, — требовать
    от такого обхода непустоты значило бы красить исправное
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    Отличается он КОРНЕМ выражения, а не именем переменной.
    """
    assert list(tmp_path.glob("*.md")) == [], "поддельное дерево непусто — предмет не тот"
    said = ast.parse("for one in tmp_path.glob('*.md'):\n    pass\n")
    call = next(one for one in ast.walk(said) if isinstance(one, ast.Call))
    assert isinstance(call.func, ast.Attribute), "разбор дал не обход — предмет не тот"
    root = leftmost(call.func.value)
    assert root != THE_TREE, (
        f"корень поддельного дерева опознан как «{root}» — граница гейта стёрта,"
        " и обход по своему корню краснел бы наравне с обходом дерева"
    )
