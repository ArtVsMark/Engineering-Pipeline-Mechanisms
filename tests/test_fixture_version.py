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

from tests.conftest import FAKE_VERSION, ROOT, walk

#: Имя файла версии: по нему узнают получателя записи.
VERSION_FILE = "CONTRACT_VERSION"


def writes_the_version(path: Path) -> bool:
    """Записывает ли тест файл версии в подделанное дерево — по разбору.

    Отношение здесь составное: вызов `.write_text`, а внутри его получателя
    названа версия. Обе половины читаются из дерева разбора, а не из написания
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    """
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        head = node.func
        if not (isinstance(head, ast.Attribute) and head.attr == "write_text"):
            continue
        if VERSION_FILE in ast.unparse(head.value):
            return True
    return False


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
