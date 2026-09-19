"""Подделка версии не совпадает с настоящей — и это держится проверкой.

Гейт «версия живёт в одном источнике» видит ЧИСЛО в дереве и не знает, что это
фикстура. Пока подделки писались от руки, они трижды за одну смену совпадали с
настоящей версией — и гейт краснел на здоровом коде, каждый раз уже на площадке.

Внимательность здесь не работает по устройству: совпадение появляется не когда
пишут тест, а когда проект ДОРАСТАЕТ до этого номера. Поэтому подделки берут
заведомо чужой номер, а держит это проверка ниже.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.conftest import FAKE_VERSION, ROOT, walk

#: Имя файла версии: по нему узнают получателя записи.
VERSION_FILE = "CONTRACT_VERSION"


def _points_at_version(node: ast.expr | None, known: dict[str, bool]) -> bool:
    """Указывает ли выражение на файл версии — прямо или через известное имя."""
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return known.get(node.id, False)
    return VERSION_FILE in ast.unparse(node)


def _writes_in(body: list[ast.stmt], known: dict[str, bool]) -> bool:
    """Пишет ли этот блок файл версии; `known` — что имена значат ЗДЕСЬ.

    Блок читается ПО ПОРЯДКУ, и состояние имён меняется по ходу: присваивание
    либо делает имя версионным, либо снимает эту метку. Вложенный блок получает
    КОПИЮ состояния — соседняя функция не должна учить это имя своему значению
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _writes_in(stmt.body, dict(known)):
                return True
            continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = list(stmt.targets) if isinstance(stmt, ast.Assign) else [stmt.target]
            points = _points_at_version(stmt.value, known)
            for one in targets:
                if isinstance(one, ast.Name):
                    # Снятие так же важно, как установка: переприсвоенное имя
                    # версию больше не пишет, и «помним первое» было бы ложным
                    # срабатыванием — гейт отвергал бы верную работу (051).
                    known[one.id] = points
            if stmt.value is not None and _has_version_write(stmt.value, known):
                return True
            continue
        # Ветки `if`/`for`/`with`/`try` идут тем же состоянием: они часть того
        # же порядка, а не отдельная область.
        for part in _branches_of(stmt):
            if _writes_in(part, known):
                return True
        for node in ast.iter_child_nodes(stmt):
            if isinstance(node, ast.expr) and _has_version_write(node, known):
                return True
    return False


def _branches_of(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Вложенные блоки оператора — ветви условия, тела циклов, обработчики.

    ОБРАБОТЧИК НЕ ОПЕРАТОР, И ЭТО НЕ МЕЛОЧЬ РАЗБОРА. `handlers` у `try` — это
    список `ExceptHandler`, который классу `ast.stmt` НЕ принадлежит, и первая
    редакция отсеивала его вместе с не-блоками: запись версии внутри `except`
    выпадала из отбора вопреки заявленному «ветви идут тем же состоянием».
    Нашёл внешний взгляд (`35d4bf6`). Тело обработчика берётся у него самого.
    """
    found: list[list[ast.stmt]] = []
    for field in ("body", "orelse", "finalbody"):
        part = getattr(stmt, field, None)
        if isinstance(part, list) and part and isinstance(part[0], ast.stmt):
            found.append(part)
    for handler in getattr(stmt, "handlers", []) or []:
        if isinstance(handler, ast.ExceptHandler) and handler.body:
            found.append(handler.body)
    return found


def _has_version_write(node: ast.AST, known: dict[str, bool]) -> bool:
    """Есть ли внутри выражения вызов `.write_text` по пути версии."""
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        head = inner.func
        if not isinstance(head, ast.Attribute) or head.attr != "write_text":
            continue
        if _points_at_version(head.value, known):
            return True
    return False


def writes_the_version(path: Path) -> bool:
    """Записывает ли тест файл версии в подделанное дерево — по разбору.

    Отношение составное: вызов `.write_text`, а получатель — либо сам путь с
    именем файла версии, либо имя, которому такой путь присвоен ЗДЕСЬ И
    РАНЬШЕ. Обе половины читаются из дерева разбора, а не из написания (166).

    ИМЯ РАЗРЕШАЕТСЯ ТАМ, ГДЕ НАПИСАНО, И В ТОМ ПОРЯДКЕ. Первая редакция
    собирала версионные имена по ВСЕМУ файлу и не снимала их: имя, занятое под
    версию в одной функции и переприсвоенное в другой, засчитывалось записью;
    переприсвоенное тут же — тоже. Взгляд назвал это тремя рисками
    (`d27903b`, `79204bd`, `3286efa`), и предмет в дереве уже есть — замер
    19.09.2026: версионное имя присваивается дважды в `test_contract_surface.py`
    (`current`) и здесь же (`real`).

    Цепочка имён разрешается транзитивно: `другой = файл` наследует значение,
    потому что для отношения это та же запись.

    ГРАНИЦА НАЗВАНА: разбор не следит за областью видимости дальше блоков —
    `global`, замыкания и присваивание через распаковку он не читает. Подделка,
    написанная так, выпадет из отбора, и это предел, а не полнота (046, 195).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return _writes_in(tree.body, {})


def test_the_fake_version_is_not_the_real_one() -> None:
    """Подделка и настоящая версия — разные числа.

    Иначе гейт версии покраснеет на собственных проверках проекта, и красное
    придётся объяснять вместо того, чтобы чинить.
    """
    real = (ROOT / "CONTRACT_VERSION").read_text(encoding="utf-8").strip()
    assert real != FAKE_VERSION, (
        f"подделка версии совпала с настоящей ({real}) — гейт версии покраснеет "
        "на проверках; возьмите заведомо чужой номер"
    )


def test_the_fake_version_stays_out_of_reach() -> None:
    """Подделка заведомо выше настоящей: проект до неё не дорастёт случайно.

    Мажор растёт только с закрытой приёмкой (decisions/009), поэтому чужой
    мажор — надёжная граница, а не «пока не совпало».
    """
    real = (ROOT / "CONTRACT_VERSION").read_text(encoding="utf-8").strip()
    assert int(FAKE_VERSION.split(".")[0]) > int(real.split(".")[0]), (
        "подделка версии не выше настоящей по мажору — совпадение вопрос времени"
    )


def test_the_checklists_of_the_project_use_it() -> None:
    """Проверки, подделывающие версию, берут общую константу, а не свой литерал.

    Свой литерал в каждом файле — это тот же список руками: он отстанет молча, и
    ловить его снова придётся гейту на площадке.

    Предмет — те, кто версию ЗАПИСЫВАЕТ в подделанное дерево. Упоминание её
    имени в прозе поводом не является: замер о трёх якорях говорит о ней
    словами и подделкой не занимается.

    ОТБОР ИДЁТ РАЗБОРОМ. Прежний образец требовал буквального
    `"CONTRACT_VERSION").write_text` — то есть закрывающей скобки вплотную к
    точке. Тот же вызов через переменную, через `paths.CONTRACT_VERSION` или
    разнесённый по строкам не виден, и подделка со своим литералом молча
    выпадала из предмета: гейт зеленел, ничего о ней не проверив (045).
    """
    users = [
        path.name
        for path in walk(ROOT / "tests", "test_*.py")
        if path.name != "test_fixture_version.py" and writes_the_version(path)
    ]
    assert users, "ни один тест не подделывает версию — предмет не найден (075)"
    for name in users:
        source = (ROOT / "tests" / name).read_text(encoding="utf-8")
        assert "FAKE_VERSION" in source or "9.9" in source, (
            f"{name} подделывает версию своим литералом вместо общей константы"
        )


#: Записи, которые для отношения «тест пишет файл версии» ОДНО И ТО ЖЕ, и
#: записи, которые им только кажутся. Таблица, а не отдельные проверки: у
#: предиката две ошибки — пропустить своё и засчитать чужое, — и вторая дороже,
#: потому что гейт начинает отвергать верную работу (051, 195).
WRITES = {
    "прямо в вызове": '(Path("к") / "CONTRACT_VERSION").write_text("9.9")',
    "по имени": 'ф = Path("к") / "CONTRACT_VERSION"\nф.write_text("9.9")',
    "цепочкой имён": 'ф = Path("к") / "CONTRACT_VERSION"\nдругой = ф\nдругой.write_text("9.9")',
    "запись версии внутри except": (
        'try:\n    pass\nexcept Exception:\n    ф = Path("к") / "CONTRACT_VERSION"\n'
        '    ф.write_text("9.9")'
    ),
    "внутри функции": (
        'def t() -> None:\n    ф = Path("к") / "CONTRACT_VERSION"\n    ф.write_text("9.9")'
    ),
}

NOT_WRITES = {
    "чужой файл": 'иное = Path("к") / "ПРОЧЕЕ"\nиное.write_text("9.9")',
    "имя снято переприсвоением": (
        'ф = Path("к") / "CONTRACT_VERSION"\nф = Path("к") / "ИНОЕ"\nф.write_text("9.9")'
    ),
    "занято в СОСЕДНЕЙ функции": (
        'def a() -> None:\n    ф = Path("к") / "CONTRACT_VERSION"\n'
        'def b() -> None:\n    ф = Path("к") / "ИНОЕ"\n    ф.write_text("9.9")'
    ),
    "имя названо, но не записано": 'ф = Path("к") / "CONTRACT_VERSION"\nprint(ф)',
    # ЧУЖОЕ ИМЯ ИЗ СОСЕДНЕЙ ФУНКЦИИ: `b` пишет по имени, которого САМА не
    # задавала — версионным его сделала `a`, и в своей области. Случай завёлся
    # ОТКАТОМ: изоляция блоков копией состояния не краснела ни на одной записи
    # таблицы, то есть держалась ничем. Откат, который не покраснел, — находка,
    # а не облегчение
    # ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    "запись внутри except": (
        'try:\n    pass\nexcept Exception:\n    ф = Path("к") / "ИНОЕ"\n    ф.write_text("9.9")'
    ),
    "имя занято соседней функцией": (
        'def a() -> None:\n    ф = Path("к") / "CONTRACT_VERSION"\n'
        'def b() -> None:\n    ф.write_text("9.9")'
    ),
}


@pytest.mark.parametrize("как", sorted(WRITES))
def test_every_form_of_writing_the_version_is_seen(как: str, tmp_path: Path) -> None:
    """Все записи версии опознаны: отношение одно, написаний много (166)."""
    path = tmp_path / "образец.py"
    path.write_text("from pathlib import Path\n" + WRITES[как] + "\n", encoding="utf-8")

    assert writes_the_version(path), f"запись «{как}» не опознана"


@pytest.mark.parametrize("как", sorted(NOT_WRITES))
def test_what_only_looks_like_writing_the_version(как: str, tmp_path: Path) -> None:
    """Похожее на запись записью не считается.

    ЗАМЕР 19.09.2026, ради которого таблица и заведена: первая редакция
    собирала версионные имена по ВСЕМУ файлу и не снимала их при
    переприсвоении. Взгляд назвал это тремя рисками (`d27903b`, `79204bd`,
    `3286efa`), и предмет в дереве уже был: версионное имя присваивается дважды
    в `test_contract_surface.py` (`current`) и в этом файле (`real`).
    """
    path = tmp_path / "образец.py"
    path.write_text("from pathlib import Path\n" + NOT_WRITES[как] + "\n", encoding="utf-8")

    assert not writes_the_version(path), f"«{как}» засчитано записью версии"


def test_a_write_through_a_name_is_still_a_write(tmp_path: Path) -> None:
    """Путь, собранный отдельной строкой, — та же запись версии.

    Отбор подделок ищет ОТНОШЕНИЕ «тест пишет файл версии», а не написание
    вызова (166). Пока он смотрел только непосредственного получателя,
    `файл = корень / "CONTRACT_VERSION"` с записью по имени выпадал молча —
    и выпадал бы именно у того, кто пишет аккуратнее прочих.

    ПРЕДМЕТА В ДЕРЕВЕ СЕГОДНЯ НЕТ: замер 19.09.2026 — подделок пять, все пишут
    путь прямо в вызове. Проверка держит обещание докстроки, а не найденный
    пропуск, и потому идёт на синтетическом входе: ждать первой такой подделки
    значило бы узнать о дыре из чужого прогона (002).
    """
    прямо = tmp_path / "прямо.py"
    прямо.write_text(
        'from pathlib import Path\n(Path("к") / "CONTRACT_VERSION").write_text("9.9")\n',
        encoding="utf-8",
    )
    по_имени = tmp_path / "по_имени.py"
    по_имени.write_text(
        'from pathlib import Path\nфайл = Path("к") / "CONTRACT_VERSION"\nфайл.write_text("9.9")\n',
        encoding="utf-8",
    )
    мимо = tmp_path / "мимо.py"
    мимо.write_text(
        'from pathlib import Path\nиное = Path("к") / "ПРОЧЕЕ"\nиное.write_text("9.9")\n',
        encoding="utf-8",
    )

    assert writes_the_version(прямо), "прямая запись версии не опознана"
    assert writes_the_version(по_имени), (
        "запись по имени не опознана: путь собран отдельной строкой, а отношение то же"
    )
    assert not writes_the_version(мимо), (
        "опознан чужой файл: предикат сработал шире своего предмета (195)"
    )
