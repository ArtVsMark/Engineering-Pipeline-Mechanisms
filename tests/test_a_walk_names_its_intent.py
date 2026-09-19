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


def _called(node: ast.Call) -> str:
    """Имя вызванного — ОБЕИМИ формами записи: `walk(…)` и `помощник.walk(…)`.

    Голое имя знала только первая. Разбор через точку уходил молча: общий
    обходчик, вызванный из модуля, прозрачным не считался, имя от него
    записывалось в чужой корень, и голый обход от этого имени оставался
    невидимым (045).
    """
    return getattr(node.func, "id", "") or getattr(node.func, "attr", "")


def leftmost(node: ast.AST) -> str:
    """Самое левое имя выражения пути: `ROOT`, `tmp_path`, `WORKFLOWS`…

    ОБЩИЙ ОБХОДЧИК ПРОЗРАЧЕН: `walk(ROOT, …)` отдаёт пути НАСТОЯЩЕГО дерева, и
    имя, связанное его результатом, тоже настоящее. Без этого `package` из
    включения по `walk(ROOT, …)` считался чужим корнем, и голый обход от него
    оставался невидимым (нашёл внешний взгляд на #510).
    """
    if isinstance(node, ast.Call) and _called(node) in SHARED and node.args:
        return leftmost(node.args[0])
    # СПИСОК ПУТЕЙ — ТОТ ЖЕ ПУТЬ. `for one in [ROOT / "scripts"]` прячет корень
    # внутрь литерала, и без этого имя цикла считалось чужим (найдено откатом,
    # третьей формой из четырёх).
    if isinstance(node, ast.List | ast.Tuple | ast.Set) and node.elts:
        return leftmost(node.elts[0])
    while isinstance(node, ast.BinOp | ast.Attribute | ast.Subscript | ast.Call):
        node = (
            node.left
            if isinstance(node, ast.BinOp)
            else (node.value if isinstance(node, ast.Attribute | ast.Subscript) else node.func)
        )
    return getattr(node, "id", "?")


def bound_by(node: ast.AST) -> tuple[list[ast.AST], ast.AST | None]:
    """Что связывает узел: какие имена он даёт и из чего они выведены."""
    if isinstance(node, ast.AnnAssign):
        return [node.target], node.value
    if isinstance(node, ast.Assign):
        return list(node.targets), node.value
    if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
        return [node.target], node.iter
    return [], None


#: Чем записывают распаковку: `a, b = …` и `[a, b] = …` — одна и та же форма.
UNPACKED: Final = (ast.Tuple, ast.List)


def paired(targets: list[ast.AST], source: ast.AST) -> list[tuple[str, ast.AST]]:
    """Связывания «имя ← из чего», ПЯТАЯ форма записи в том числе.

    `a, b = ROOT / x, ROOT / y` даёт одну цель-кортеж, а не два имени, и разбор,
    читающий только `ast.Name`, не размечал НИ ОДНОГО из них: голый обход от
    `a` оставался невидимым. Нашёл внешний взгляд (`f8abcb3`).

    РАСПАКОВКА РАЗБИРАЕТСЯ ПОЭЛЕМЕНТНО, А НЕ СПЛОШЬ. `a, b = ROOT / x, чужое`
    связывает корнем только `a`: пометить оба значило бы расширить предмет на
    законное имя и отвергать верную работу
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Когда длины не совпадают или в цели есть звёздочка, поэлементно не выходит,
    и источником для каждого имени считается всё выражение целиком — так же,
    как у `a, b = что_то()`.
    """
    made: list[tuple[str, ast.AST]] = []
    for target in targets:
        if isinstance(target, ast.Name):
            made.append((target.id, source))
            continue
        if not isinstance(target, UNPACKED):
            continue
        elts = target.elts
        starred = any(isinstance(one, ast.Starred) for one in elts)
        if isinstance(source, UNPACKED) and not starred and len(source.elts) == len(elts):
            # ВГЛУБЬ, ПОТОМУ ЧТО РАСПАКОВКА БЫВАЕТ ВЛОЖЕННОЙ. `a, (b, c) = …`
            # даёт внутри цели снова кортеж, и плоский разбор терял `b` и `c`
            # ЦЕЛИКОМ: ни поэлементно, ни откатом на всё выражение. Нашёл
            # внешний взгляд (`4709f9c`).
            for one, from_what in zip(elts, source.elts, strict=True):
                made += paired([one], from_what)
            continue
        # ПОЭЛЕМЕНТНО НЕ ВЫХОДИТ — источником считается всё выражение, и это
        # тоже идёт вглубь: `a, (b, c) = что_то()` связывает корнем все три.
        for one in elts:
            made += paired([one], source) if not isinstance(one, ast.Name) else [(one.id, source)]
    return made


def rooted_names(tree: ast.AST) -> set[str]:
    """Имена, выведенные из корня дерева, — ГДЕ БЫ ОНИ НИ СВЯЗАЛИСЬ.

    ПЕРВАЯ РЕДАКЦИЯ СМОТРЕЛА ТОЛЬКО ВЕРХНИЙ УРОВЕНЬ МОДУЛЯ, и голый обход через
    локальную переменную оставался невидимым — при том что гейт объявлял себя
    ловящим «любой голый обход настоящего дерева». Два живых примера назвал
    внешний взгляд на #510: `package.parent.glob(…)`, где `package` приходит из
    включения по `walk(ROOT, …)`, и `directory.iterdir()`, где `directory` —
    переменная цикла по `ROOT / where`
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

    ОБХОД ИДЁТ ДО НЕПОДВИЖНОЙ ТОЧКИ: имя, выведенное из уже известного, само
    становится известным, и порядок связывания значения не имеет — включение
    может стоять раньше присваивания, которое его кормит.
    """
    found = {THE_TREE}
    while True:
        grown = set(found)
        for node in ast.walk(tree):
            targets, source = bound_by(node)
            if source is None:
                continue
            for name, from_what in paired(targets, source):
                if leftmost(from_what) in grown:
                    grown.add(name)
        if grown == found:
            return found
        found = grown


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


def _called_name(head: ast.expr) -> str:
    """Имя вызываемого — голое или последнее через точку.

    Обходчик зовут обеими записями: `walk(...)` у того, кто его импортировал, и
    `conftest.walk(...)` у того, кто взял модулем. Разбор, знающий только
    голое имя, вторую запись не видит, и проверка предмета зеленела бы, не
    найдя половины
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд (`7aa4bac`) — и нашёл потому, что гейт форм вызова эту
    функцию НЕ СУДИЛ: разбор через `getattr` в его предмет не попадал.
    """
    return str(getattr(head, "id", "") or getattr(head, "attr", ""))


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    shared = [
        one
        for path in walk(ROOT / "tests", "*.py")
        for one in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(one, ast.Call) and _called_name(one.func) in SHARED
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


#: Способы связать имя с настоящим деревом и способы связать его со своим —
#: одной таблицей, обе стороны разом. Числа здесь не называются: таблица
#: пополняется каждым разобранным случаем, и вписанное число рассыхается первой
#: же записью — оно уже рассохлось однажды, «пять» при шести истинных
#: ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
#:
#: Список закрытый и закреплён прогоном: первая редакция признака знала ТОЛЬКО
#: присваивание верхнего уровня, и три формы проходили мимо (нашёл внешний
#: взгляд на #510, назвав два живых примера). Распаковку назвал взгляд на #512
#: (`f8abcb3`): цель там одна и это КОРТЕЖ, а не имя, и прежний разбор не
#: размечал НИ ОДНОГО из распакованных. Вложенную — взгляд на #539
#: (`4709f9c`): плоский разбор терял её имена целиком.
WAYS_IN: Final = (
    ("присваиванием модуля", "СВОЙ = ROOT / 'scripts'\nСВОЙ.glob('*.py')\n", True),
    ("локальной переменной", "def f():\n    x = ROOT / 'scripts'\n    x.glob('*.py')\n", True),
    ("переменной цикла", "def f():\n    for d in [ROOT / 'scripts']:\n        d.iterdir()\n", True),
    (
        "целью включения",
        "def f():\n    [y for d in walk(ROOT, 's') for y in d.glob('*.py')]\n",
        True,
    ),
    (
        "распаковкой кортежа",
        "def f():\n    a, b = ROOT / 'scripts', ROOT / 'tests'\n    b.glob('*.py')\n",
        True,
    ),
    (
        "распаковкой из одного выражения",
        "def f():\n    a, b = (ROOT / 'scripts').parts\n    b.glob('*.py')\n",
        True,
    ),
    (
        "вложенной распаковкой",
        "def f():\n    a, (b, c) = ROOT / 's', (ROOT / 't', ROOT / 'u')\n    c.glob('*.py')\n",
        True,
    ),
    (
        "вложенной распаковкой из одного выражения",
        "def f():\n    a, (b, c) = (ROOT / 's').что_то()\n    c.glob('*.py')\n",
        True,
    ),
    ("своим корнем", "def f(tmp_path):\n    x = tmp_path / 'x'\n    x.glob('*.py')\n", False),
    (
        "чужая ветвь вложенной распаковки",
        "def f(tmp_path):\n"
        "    a, (b, c) = ROOT / 's', (tmp_path / 't', tmp_path / 'u')\n"
        "    c.glob('*.py')\n",
        False,
    ),
    # РАСПАКОВКА РАЗБИРАЕТСЯ ПОЭЛЕМЕНТНО: чужая половина остаётся чужой.
    # Пометить оба имени значило бы отвергать верную работу (051).
    (
        "чужая половина распаковки",
        "def f(tmp_path):\n    a, b = ROOT / 'scripts', tmp_path / 'x'\n    b.glob('*.py')\n",
        False,
    ),
)


def test_every_way_of_binding_a_rooted_name_is_seen() -> None:
    """Имя настоящего дерева опознаётся, КАК БЫ оно ни связалось.

    Формы перечислены списком, а не выведены, и каждая держится своим случаем:
    признак, знающий одну форму из четырёх, зеленеет на трёх остальных, ничего
    не проверив
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Пятый случай — отрицательный: свой корень остаётся чужим, иначе гейт красил
    бы исправное (044).
    """
    wrong: list[str] = []
    for what, source, rooted in WAYS_IN:
        tree = ast.parse(source)
        names = rooted_names(tree)
        seen = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in BARE
            and leftmost(node.func.value) in names
            for node in ast.walk(tree)
        )
        if seen is not rooted:
            wrong.append(f"«{what}»: опознано={seen}, ожидалось={rooted}")
    assert not wrong, "признак корня разошёлся с формами связывания:\n  " + "\n  ".join(wrong)


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
