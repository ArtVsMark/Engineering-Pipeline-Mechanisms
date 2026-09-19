"""Путь зоны совпадает хоть с одним файлом дерева.

Зона размечает изменение по тронутым файлам: `scripts/labels.py::zones_for`
сверяет каждый путь изменения с образцами зоны. Образец, не совпадающий ни с
чем, выводит зону НИКОГДА — и делает это молча: гейт разметки требует хотя бы
одной зоны, а её ставит автор, так что снаружи «зона выведена» и «зона
поставлена рукой» выглядят одинаково
([070](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/070-a-heuristic-guard-fails-open-with-a-written-risk.md)).

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Меток 26, путей объявлено у
ЧЕТЫРЁХ зон, мёртвых образцов ноль. То есть ответ проекта — «поле `paths` есть
только у зон, чьи файлы уже существуют» — был верен и не держался ничем:
переименуй каталог, и зона перестанет выводиться, не покраснев нигде
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЗОНА БЕЗ ПУТЕЙ — ЗАКОННОЕ СОСТОЯНИЕ, И ОНО НЕ ПРЕДМЕТ. Таких 22, и молчат они
намеренно: механизмов у них ещё нет, метку ставит человек при разборе. Требовать
путей от них значило бы требовать выдумать образец, указывающий в будущее, — а
он и дал бы тот самый молчаливый промах
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import fnmatch
from typing import Final

import pytest

from tests.conftest import ROOT, load_script, walk_deep

labels = load_script("labels.py")
paths = load_script("paths.py")


#: Что считается деревом для сверки: пути, какими их видит разметка, — от корня
#: и с косой чертой, ровно как приходят от площадки.
def tree_files() -> list[str]:
    """Файлы дерева в том виде, в каком разметка получает их от площадки."""
    return [
        one.relative_to(ROOT).as_posix()
        for one in walk_deep(ROOT, "*")
        if one.is_file() and ".git/" not in one.as_posix()
    ]


def zones_with_paths() -> list[object]:
    """Зоны, объявившие образцы путей, — предмет этой проверки."""
    return [one for one in labels.load(ROOT / paths.LABELS) if one.is_zone and one.paths]


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    assert zones_with_paths(), "ни одна зона не объявляет путей — выводить нечего"
    assert tree_files(), "дерево пусто — сверять образцы не с чем"


@pytest.mark.parametrize("zone", zones_with_paths(), ids=lambda one: str(one.name))
def test_every_declared_pattern_matches_something(zone: object) -> None:
    """Каждый образец зоны совпадает хоть с одним файлом дерева.

    Проверяется КАЖДЫЙ образец, а не зона целиком: зона с двумя образцами, из
    которых жив один, выводится по живому и молчит о мёртвом — то есть частичная
    смерть неотличима от полного здоровья
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    files = tree_files()
    dead = [
        pattern
        for pattern in zone.paths  # type: ignore[attr-defined]
        if not any(fnmatch.fnmatch(one, pattern) for one in files)
    ]
    assert not dead, (
        f"зона «{zone.name}» объявляет образцы, не совпадающие ни с чем: {dead}."  # type: ignore[attr-defined]
        "\n  Каталог переименован или ещё не заведён — зона по такому образцу не"
        " выведется НИКОГДА, а снаружи это выглядит как «автор поставил метку сам»."
    )


def test_a_zone_without_paths_is_not_judged() -> None:
    """Граница названа замером: зоны без путей в дереве есть, и они законны.

    Исчезнут они — довод о границе станет пустым, и предмет можно будет
    расширить
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    silent: Final = [
        one for one in labels.load(ROOT / paths.LABELS) if one.is_zone and not one.paths
    ]
    assert silent, "зон без объявленных путей нет — довод о границе пуст"
