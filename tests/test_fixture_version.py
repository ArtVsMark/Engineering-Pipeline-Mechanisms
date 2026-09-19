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


def named_version_paths(tree: ast.Module) -> set[str]:
    """Имена, которым присвоен путь с файлом версии.

    Путь к подделке чаще собирают отдельной строкой, а пишут уже по имени:
    ``файл = корень / "CONTRACT_VERSION"`` и следом ``файл.write_text(...)``.
    Для отношения «тест пишет версию» это одна и та же запись, и различает их
    только НАПИСАНИЕ
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    """
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if node.value is None or VERSION_FILE not in ast.unparse(node.value):
            continue
        named.update(one.id for one in targets if isinstance(one, ast.Name))
    return named


def writes_the_version(path: Path) -> bool:
    """Записывает ли тест файл версии в подделанное дерево — по разбору.

    Отношение здесь составное: вызов `.write_text`, а получатель — либо сам
    путь с именем файла версии, либо ИМЯ, которому такой путь присвоен. Обе
    половины читаются из дерева разбора, а не из написания (166).

    ЗАПИСЬ ПО ИМЕНИ РАНЬШЕ ВЫПАДАЛА. Предикат смотрел только непосредственного
    получателя вызова, то есть проверял написание там, где докстрока обещала
    отношение, — нашёл внешний взгляд (`2ccec1a`). Замер 19.09.2026: подделок в
    дереве пять, все пишут путь прямо в вызове, пропущенных НЕТ. Предмета у
    пропуска сегодня нет, и правится не он, а расхождение обещания с
    механизмом: пока они врозь, первая же подделка, собранная по имени, выпадет
    из отбора молча
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    named = named_version_paths(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        head = node.func
        if not (isinstance(head, ast.Attribute) and head.attr == "write_text"):
            continue
        said = ast.unparse(head.value)
        if VERSION_FILE in said or said in named:
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
