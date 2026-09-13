"""Один скрипт — один экземпляр в процессе проверок.

ЧТО ЗДЕСЬ ПРЕДМЕТ. Обвязка `load_script` исполняла файл на каждый вызов и
клала результат в `sys.modules`, затирая прежний. Скрипты импортируют друг
друга обычным `import`, который смотрит туда же, — и кто импортировал соседа
раньше, оставался с первым экземпляром, а кто позже, получал второй. Снаружи
модули одинаковы, по личности — разные.

ПОЧЕМУ ЭТО НЕ МЕЛОЧЬ ОБВЯЗКИ. Проект держит «одно место на одно понимание»
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md))
проверками вида «читатели зовут ОДНУ функцию». Такая проверка сравнивает
личности, и на двойном экземпляре её ответ говорит о порядке сбора, а не о
дереве: `pytest $(ls -r tests/test_*.py)` ронял
`test_the_events_key_is_read_in_one_place`, а обычный прогон — нет. Зелёное,
которое держится порядком файлов, не держит ничего.

Предмет считается по дереву тестов, а не перечисляется руками
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
"""

from __future__ import annotations

import re
from types import ModuleType
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

#: Как тест зовёт скрипт. Форма одна на весь набор, и это её и держит.
CALL_RE: Final = re.compile(r'load_script\(\s*"(?P<name>[a-z_0-9]+\.py)"\s*\)')


def asked_by_tests() -> list[str]:
    """Скрипты, которые набор загружает как модули: предмет этой проверки."""
    names: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        for match in CALL_RE.finditer(path.read_text(encoding="utf-8")):
            if (ROOT / "scripts" / match["name"]).is_file():
                names.add(match["name"])
    return sorted(names)


def neighbours(module: ModuleType) -> list[str]:
    """Соседи-скрипты, которые этот модуль импортировал обычным `import`."""
    return sorted(
        name
        for name, value in vars(module).items()
        if isinstance(value, ModuleType) and (ROOT / "scripts" / f"{name}.py").is_file()
    )


ASKED: Final = asked_by_tests()


def test_the_subject_is_found() -> None:
    """Набор вообще загружает скрипты — иначе проверять нечего (075)."""
    assert ASKED, "ни один тест не зовёт load_script — предмет не найден"


@pytest.mark.parametrize("name", ASKED)
def test_a_script_is_executed_once(name: str) -> None:
    """Повторный запрос отдаёт ТОТ ЖЕ объект, а не второе исполнение файла."""
    assert load_script(name) is load_script(name), (
        f"{name} исполняется заново на каждый запрос: в `sys.modules` ляжет второй "
        "экземпляр, и тот, кто импортировал его раньше, останется с первым"
    )


@pytest.mark.parametrize("name", ASKED)
def test_a_script_shares_one_copy_of_its_neighbours(name: str) -> None:
    """Сосед внутри скрипта и сосед у загрузчика — один объект.

    Это и есть та личность, которую сравнивают проверки «читают одной
    функцией». Разойдись она — и их ответ будет о порядке сбора.
    """
    module = load_script(name)
    for neighbour in neighbours(module):
        assert getattr(module, neighbour) is load_script(f"{neighbour}.py"), (
            f"{name} видит {neighbour} не тем экземпляром, который отдаёт загрузчик: "
            "две личности одного модуля, и проверки «одно место на одно понимание» "
            "начинают говорить о порядке файлов, а не о дереве"
        )
