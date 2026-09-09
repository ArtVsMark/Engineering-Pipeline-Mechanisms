"""Якорь дерева: где лежат настройки. Один на все механизмы.

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ КОНСТАНТА У КАЖДОГО. Правило каталога
[115](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/115-settings-have-one-anchor-not-a-search.md)
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

#: Всё, что объявлено здесь: по этому списку гейт сверяет, что второго якоря
#: не завели. Список разрешительный (068): путь, которого здесь нет, механизм
#: строить не должен.
ALL: Final = (
    PIPELINE,
    LABELS,
    BINDINGS,
    PROPOSALS,
    FRAGMENTS,
    RELEASED,
    CHANGELOG,
    VERSION,
    WORKFLOWS,
    AUTHORS,
)
