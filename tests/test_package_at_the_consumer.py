"""Что пакет делает у ПОЛУЧАТЕЛЯ, а не у нас.

Пока общий низ жил в `scripts/`, обоих вопросов ниже не существовало: читатель
и дерево были одним и тем же. С 15.09.2026 у пакета есть получатель, который
ставит **дистрибутив**, а не дерево, — и два правила каталога, прежде
неприменимых, вступили вместе с ним.

ОБА ОТВЕТА БЫЛИ ПРОТУХШИМИ, И НИКТО ЭТОГО НЕ ЗАМЕТИЛ. Каждый называл условие
дословно — «правило вступит вместе с пакетом», — условие наступило, а перечитать
ответы было нечему: механизм перечитывания (`scripts/check_reread.py`) идёт по
номеру выгрузки КАТАЛОГА, а не по изменениям САМОГО проекта. Нашёл это владелец
вопросом «а в неприменимых ничего такого нет?», 16.09.2026.

ЗАМЕР ТОГО ЖЕ ДНЯ: нарушений ноль по обоим. Гейт заводится не на найденном
дефекте, а на классе, который **не виден изнутри дерева**: сообщение, зовущее в
`tests/`, у нас разрешается, а у получателя — нет, и «у автора работает» здесь
штатный исход
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT

#: Пути, которые есть у НАС и которых нет у получателя. Список назван, а не
#: выведен: у получателя нет ровно этих каталогов, и угадывать их по дереву
#: значило бы запретить заодно слова вроде «docs» в прозе.
TREE_ONLY: Final = re.compile(r"(?:^|[\s\"'`(])(?:tests|scripts|docs|changelog\.d)/")

#: Как модуль заводит файл на чужой машине. Формы названы поимённо: запрет
#: «любого обращения к файловой системе» задел бы чтение, которое законно.
WRITES: Final = ("write_text", "write_bytes", "mkdir", "makedirs", "NamedTemporaryFile")


def modules() -> list[Path]:
    """Модули пакетов дерева — по объявлению, а не по списку имён (005)."""
    return sorted(
        one
        for package in ROOT.glob("packages/*/pyproject.toml")
        for one in package.parent.glob("*.py")
    )


def test_the_tree_has_a_package_to_look_at() -> None:
    """Модули пакета найдены: без них проверки ниже — поверхность без предмета (075)."""
    assert modules(), "в дереве нет ни одного модуля локального пакета"


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_a_package_module_names_no_path_of_our_tree(path: Path) -> None:
    """Сообщение пакета не зовёт получателя туда, чего у него нет (правило 076).

    У ставящего пакет есть дистрибутив, а не наше дерево: подсказка «смотри
    `tests/`» у него ложна, и проверить её он не может. Изнутри дерева такая
    подсказка выглядит исправной — этим класс и опасен.
    """
    found = [
        node.value
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and TREE_ONLY.search(node.value)
    ]
    assert not found, f"{path.name}: строка зовёт в наше дерево, которого у получателя нет: {found}"


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_a_package_module_leaves_nothing_on_the_consumer_machine(path: Path) -> None:
    """Пакет не заводит у получателя файлов, о которых тот не просил (правило 112).

    Кеш или конфиг, появившийся от установки, обязан сниматься той же командой,
    какой пакет ставили. Проще этого не заводить вовсе — и сегодня не заведено.
    """
    text = path.read_text(encoding="utf-8")
    found = [one for one in WRITES if re.search(rf"\b{one}\s*\(", text)]
    opened = re.findall(r"open\s*\([^)]*[\"'][wax]", text)
    assert not found and not opened, (
        f"{path.name}: пакет заводит файл у получателя ({found or opened}) — "
        "тогда обязана быть и команда, которой это снимают (112)"
    )
