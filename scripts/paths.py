"""Якорь дерева: где лежат настройки. Один на все механизмы.

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ КОНСТАНТА У КАЖДОГО. Правило каталога
[115](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/115-config-has-one-anchor-and-a-bounded-search.md)
требует у настроек ОДИН якорь и запрещает поиск вверх по дереву. До этого
модуля якорь держался построением, а не механизмом: каждый читатель писал
`Path("...")` сам, и завести второй якорь ничто не мешало.

ЗАВЕСТИ УСПЕЛИ. Замер 09.09.2026: `CONTRACT_VERSION` строился в трёх модулях —
`build_changelog.py`, `build_facts.py`, `check_version.py`, — то есть у одного
источника версии было три независимых адреса. Разъехались бы они молча: путь
короткий, правка в одном месте выглядит полной.

ПОИСКА ВВЕРХ ЗДЕСЬ НЕТ И НЕ БУДЕТ. Пути относительны корню репозитория, а
корнем работает рабочий каталог прогона: механизмы зовутся из него. Поиск
`.pipeline.yml` вверх по дереву нашёл бы чужой файл соседнего проекта и молча
принял бы его за свой — ровно тот отказ, из-за которого правило записано.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

#: Ответ проекта по классам проверок конвейера.
PIPELINE: Final = Path(".pipeline.yml")
#: Состав меток репозитория.
LABELS: Final = Path(".github/labels.yml")
#: Ответ проекта каталогу правил и канал предложений в него.
BINDINGS: Final = Path(".rules/bindings.json")
PROPOSALS: Final = Path(".rules/proposals.json")

#: Ответ проекта по набору вопросов витрины — файл каталога по форме, наш по
#: содержанию.
SHOWCASE: Final = Path(".rules/showcase.json")

#: Объявленные расписания и роль каждого: наблюдает оно или действует.
SCHEDULES: Final = Path(".rules/schedules.json")

#: Чем защищена общая ветка — объявлением, а не памятью. Настройка живёт вне
#: дерева, и ослабление её не краснеет нигде само по себе.
PROTECTION: Final = Path(".rules/protection.json")
#: Фрагменты журнала и собранный журнал.
FRAGMENTS: Final = Path("changelog.d")
RELEASED: Final = FRAGMENTS / "released"
CHANGELOG: Final = Path("CHANGELOG.md")
#: Единственный источник версии контракта (035).
VERSION: Final = Path("CONTRACT_VERSION")
#: Описания прогонов.
WORKFLOWS: Final = Path(".github/workflows")
#: Согласованные имена атрибуции.
AUTHORS: Final = Path(".github/authors.txt")

#: Всё, что объявлено здесь. Список разрешительный (068): путь, которого в нём
#: нет, механизм строить не должен. Полноту держит
#: `tests/test_settings_anchor.py::test_the_declared_list_covers_every_address` —
#: иначе «список всего» разошёлся бы с модулем молча, а неполный список снаружи
#: неотличим от полного.
ALL: Final = (
    PIPELINE,
    LABELS,
    BINDINGS,
    PROPOSALS,
    SHOWCASE,
    SCHEDULES,
    PROTECTION,
    FRAGMENTS,
    RELEASED,
    CHANGELOG,
    VERSION,
    WORKFLOWS,
    AUTHORS,
)
