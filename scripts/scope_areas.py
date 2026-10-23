#!/usr/bin/env python3
"""Области потребителя для выбора тестов: раздел `scopes:` в `.pipeline.yml` (#1600).

ЗАЧЕМ. Граф `scope.py` выводит рёбра из кода нашими формами — импорт модуля
`scripts/`, `load_script`, литерал пути. Потребитель, чьи тесты зовут свой
код иначе, графом не судится: его выбор — области. Область называет пути и
тесты: изменение, не задевшее её путей, её тестов не гонит. Пример — `web` у
грейдера: интерфейс и связанные с ним модули.

ОБЛАСТЬ ТОЛЬКО СУЖАЕТ, И ТОЛЬКО ПОЛНЫЙ НАБОР. Выбор начинается со всех тестов
и теряет тесты нетронутых областей; тест вне всех областей идёт всегда. Общие
для всех файлы и прогоны по-прежнему дают полный набор — решает `scope.py`.

ФОРМА — ЗДЕСЬ, ЧТЕНИЕ ФАЙЛА — В `pipeline_checks`: YAML ответа разбирает один
модуль (090), как и раздел `journal:`. Модуль без зависимостей, чтобы его
могли звать и разборщик ответа, и классификатор без кругового импорта.
"""

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

#: Имя раздела в `.pipeline.yml`.
SECTION: Final = "scopes"
#: Ключи области; оба обязательны.
KEYS: Final = ("paths", "tests")


class BadAreas(ValueError):
    """Раздел областей не разбирается: причина названа, умолчанием не подменяется (045)."""


@dataclass(frozen=True, slots=True)
class Area:
    """Область: её пути и её тесты, образцами `fnmatch` (`*` ловит и `/`)."""

    name: str
    paths: tuple[str, ...]
    tests: tuple[str, ...]

    def touched_by(self, files: Iterable[str]) -> bool:
        """Задевает ли тронутое пути области."""
        return any(fnmatch.fnmatch(one, pattern) for pattern in self.paths for one in files)

    def owns(self, test: str) -> bool:
        """Тест ли это области."""
        return any(fnmatch.fnmatch(test, pattern) for pattern in self.tests)


def patterns(name: str, key: str, said: Any) -> tuple[str, ...]:
    """Непустой список непустых строк-образцов; иное — `BadAreas`."""
    if not isinstance(said, list) or not said:
        raise BadAreas(f"раздел {SECTION}: {name}.{key} — непустой список образцов")
    if not all(isinstance(one, str) and one.strip() for one in said):
        raise BadAreas(f"раздел {SECTION}: {name}.{key} — образцы строками, без пустых")
    return tuple(one.strip() for one in said)


def areas_of(section: Any) -> tuple[Area, ...]:
    """Области из раздела `scopes:`; раздела нет (`None`) — областей нет."""
    if section is None:
        return ()
    if not isinstance(section, dict) or not section:
        raise BadAreas(f"раздел {SECTION}: ожидалось непустое отображение имён на области")
    found: list[Area] = []
    for key, item in section.items():
        name = str(key).strip()
        if not isinstance(item, dict):
            raise BadAreas(f"раздел {SECTION}: {name} — отображение с ключами {', '.join(KEYS)}")
        unknown = sorted(set(item) - set(KEYS))
        if unknown:
            raise BadAreas(
                f"раздел {SECTION}: {name} — незнакомые ключи {', '.join(map(str, unknown))}"
            )
        found.append(Area(name, *(patterns(name, one, item.get(one)) for one in KEYS)))
    return tuple(found)


def known(path: str, areas: Iterable[Area]) -> bool:
    """Путь ли это какой-то области: такое место классификатору известно."""
    return any(area.touched_by([path]) for area in areas)


def narrowed(tests: Iterable[str], touched: set[str], areas: Iterable[Area]) -> tuple[str, ...]:
    """Тесты без тестов областей, которых тронутое не задело."""
    quiet = [area for area in areas if not area.touched_by(touched)]
    return tuple(sorted(one for one in tests if not any(area.owns(one) for area in quiet)))
