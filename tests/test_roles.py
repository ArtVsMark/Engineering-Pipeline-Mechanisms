"""Роли, задающие вопросы карты: у каждой роли состава есть профиль с запретом и пределом.

Карта направлений (`docs/directions.md`) называет вопрос и его владельца; файл
ролей (`docs/roles.md`) — кто этот владелец и как он спрашивает. Разведено по
решению владельца 24.09.2026 (#767): у них разный повод правки и разный
читатель. Полноту карты и стык «исход называет роль из состава» держит
`tests/test_directions_map.py`, и второй копии той проверки здесь нет (022).
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from tests.conftest import ROOT, load_script
from tests.test_directions_map import roster

paths = load_script("paths.py")

ROLES: Final = ROOT / paths.ROLES


# --- у роли есть профиль, а не только строка (#599) ---------------------------

#: Поля профиля, без которых роль неотличима от строки таблицы. «Вопрос» —
#: зачем она есть, «Запрещено» — чем она не становится, «Предел» — чего не
#: видит по построению. Последнее важнее прочего: роль, чей предел не назван,
#: кажется всесильной, и её молчание читают как «там чисто»
#: ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
PROFILE_FIELDS: Final = ("**Вопрос:**", "**Запрещено:**")
#: Предел называется одним из двух: просто названный или ИЗМЕРЕННЫЙ.
LIMIT_FIELDS: Final = ("**Предел:**", "**Предел ИЗМЕРЕН:**")


def profiles() -> dict[str, str]:
    """Профиль каждой роли: заголовок третьего уровня → тело."""
    said = ROLES.read_text(encoding="utf-8")
    after = said.partition("## Профили")[2]
    found: dict[str, str] = {}
    for part in re.split(r"^### ", after, flags=re.M)[1:]:
        head = part.splitlines()[0]
        name = re.sub(r"[^\w\s-]", "", head).strip()
        found[name] = part.split("\n## ", 1)[0]
    return found


def test_there_are_profiles_to_judge() -> None:
    """Предмет найден: профили в карте есть (075)."""
    assert len(profiles()) >= 10, f"профилей разобрано {len(profiles())} — раздела не видно"


def test_every_role_of_the_roster_has_a_profile() -> None:
    """У каждой роли состава есть профиль, а не только строка таблицы.

    ЗАМЕР, РАДИ КОТОРОГО ПРОВЕРКА ЗАВЕДЕНА (21.09.2026, #599). Состав был
    написан таблицей — имя, вход, возражение, — и владелец назвал это
    неполным: «не увидел описание и взаимодействие ролей». Строка отвечает
    «кто спрашивает», профиль — «как он спрашивает», а это и есть то, ради
    чего роль существует.
    """
    missing = sorted(roster() - set(profiles()))
    assert not missing, "роль в составе есть, а профиля у неё нет: " + ", ".join(missing)


@pytest.mark.parametrize("name", sorted(profiles()), ids=lambda one: str(one))
def test_a_profile_names_its_limit_and_its_ban(name: str) -> None:
    """Профиль называет запрет и предел, а не только достоинства.

    Роль, которой можно всё, поглощает соседнюю, и вход перестаёт их
    различать. Роль, чей предел не назван, кажется всесильной — и тогда её
    молчание читают как «там чисто», а не как «она туда не смотрит» (046).
    """
    body = profiles()[name]
    for field in PROFILE_FIELDS:
        assert field in body, f"{name}: в профиле нет поля {field}"
    assert any(one in body for one in LIMIT_FIELDS), (
        f"{name}: предел не назван — роль выглядит всесильной, "
        "и её молчание прочтут как «там чисто»"
    )
