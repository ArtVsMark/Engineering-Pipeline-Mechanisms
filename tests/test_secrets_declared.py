"""Каждый секрет прогонов назван в своде: чем держит и когда истекает.

Секрет — единственная часть механизма, которую окно не может ни увидеть, ни
починить. Истёкший токен снаружи выглядит как сломанный скрипт: «изменения
перестали открываться» будут искать в коде, а искать надо в дате (059).

Таблица в своде была, а гейта не было: новый секрет попал бы в прогон, и ничто
не потребовало бы назвать, что с ним держится. Проверяется здесь то, что из
данных следует, — совпадение состава, а не содержание сроков.
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"
AGENTS = ROOT / "AGENTS.md"
#: Обращение к секрету в прогоне: `${{ secrets.ИМЯ }}`.
SECRET_RE = re.compile(r"secrets\.(?P<name>[A-Z][A-Z0-9_]*)")
#: Секреты, которые площадка выдаёт сама и продлевать которые некому. Список
#: закрытый и назван с причиной: пустая отговорка тут стоила бы всей проверки.
BUILT_IN = {
    "GITHUB_TOKEN": "выдаётся площадкой на каждый прогон и живёт ровно его время",
}
#: Имя из примера в комментарии, а не настоящий секрет: `if: secrets.X != ''`.
EXAMPLES = {"X"}


def used() -> set[str]:
    """Секреты, к которым обращаются прогоны."""
    found: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        said = path.read_text(encoding="utf-8")
        found.update(match["name"] for match in SECRET_RE.finditer(said))
    return found - EXAMPLES


def test_there_are_secrets_to_check() -> None:
    """Предмет проверки найден: прогоны обращаются к секретам (075)."""
    assert used(), "секретов в прогонах не найдено — гейт проходит вхолостую"


@pytest.mark.parametrize("name", sorted(used()), ids=lambda n: str(n))
def test_a_used_secret_is_declared(name: str) -> None:
    """Секрет, которым пользуется прогон, назван в своде или объявлен встроенным.

    Не названный нигде секрет — это дата, которой нет: когда он истечёт, искать
    будут в коде, потому что больше искать негде.
    """
    if name in BUILT_IN:
        return
    said = AGENTS.read_text(encoding="utf-8")
    assert f"`{name}`" in said, (
        f"секрет {name} в прогонах есть, а в таблице свода его нет — "
        "назовите, что он держит и когда истекает (059)"
    )


def test_a_declared_secret_is_still_used() -> None:
    """Объявление, пережившее свой секрет, — мусор, устаревающий молча (005).

    Строка про то, чего в прогонах уже нет, читается как действующее
    обязательство: владелец будет продлевать токен, которым никто не
    пользуется.
    """
    said = AGENTS.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*`(?P<name>[A-Z][A-Z0-9_]*)`\s*\|", said, re.M)
    assert rows, "таблица секретов не разобралась — сверять нечего"
    for name in rows:
        assert name in used(), f"{name} объявлен в своде, а в прогонах его больше нет"


def test_a_built_in_secret_names_why_it_is_exempt() -> None:
    """У встроенного названа причина, а не просто пропуск (154)."""
    for name, why in BUILT_IN.items():
        assert len(why) > 20, f"{name}: причина освобождения ничего не объясняет"
