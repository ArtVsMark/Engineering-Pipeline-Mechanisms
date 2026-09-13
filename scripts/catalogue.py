"""Адреса каталога правил — в одном месте на всех читателей.

ЗАЧЕМ ОТДЕЛЬНЫМ МОДУЛЕМ. Выгрузку каталога читают сверка ссылок, дрейф, карта
ревью и сверка чужого разбора. Адрес у неё был написан в каждом из них заново —
четыре копии одной строки, — и переезд каталога чинился бы поиском по дереву,
а не правкой одного места
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
Пятый читатель и стал поводом поднять общее вверх, а не приписать вбок.

ЗДЕСЬ ТОЛЬКО АДРЕСА. Что делать с прочитанным, каждый читатель решает сам:
дрейф сравнивает числа, сверка ссылок — имена, карта ревью строит подсказку.
Свести это в «общий разбор каталога» значило бы связать четыре разных предмета
одной формой.
"""

from __future__ import annotations

from typing import Final

#: Репозиторий каталога: владелец и имя, как их знает площадка.
REPO: Final = "ArtVsMark/Engineering-Incidents-Playbook"

#: Корень сырых файлов каталога. Ветка называется в самом адресе: выгрузка
#: живёт на `main`, снимок «у кого чем держится» — на ветке значков.
RAW: Final = f"https://raw.githubusercontent.com/{REPO}"

#: Выгрузка правил: номера, имена файлов, разбор.
EXPORT_URL: Final = f"{RAW}/main/export/rules.json"

#: Снимок семьи: кто из соседей чем держит правило.
WHERE_URL: Final = f"{RAW}/badges/export/where.json"

#: Ответ каталога на предложения: вердикты по нашим записям.
PROPOSALS_URL: Final = f"{RAW}/main/.rules/proposals.json"

#: НАБОР ВОПРОСОВ ВИТРИНЫ — ЭТАЛОН, А НЕ НАША ПАМЯТЬ. Список один на все
#: проекты семьи, и живёт он у каталога; наш файл — копия, снятая рукой. Копия,
#: которую не с чем сверить, расходится молча
#: ([055](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/055-your-own-expectations-are-a-hypothesis.md)).
SHOWCASE_URL: Final = f"{RAW}/main/.rules/showcase.json"
