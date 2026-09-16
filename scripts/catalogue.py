"""Адреса каталога правил — в одном месте на всех читателей.

ЗАЧЕМ ОТДЕЛЬНЫМ МОДУЛЕМ. Выгрузку каталога читают сверка ссылок, дрейф, карта
ревью и сверка чужого разбора. Адрес у неё был написан в каждом из них заново —
четыре копии одной строки, — и переезд каталога чинился бы поиском по дереву,
а не правкой одного места
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
Пятый читатель и стал поводом поднять общее вверх, а не приписать вбок.

ЗДЕСЬ АДРЕСА И ОДИН СПОСОБ ИХ ПРОЧИТАТЬ. Что делать с прочитанным, каждый
читатель решает сам: дрейф сравнивает числа, сверка ссылок — имена, карта ревью
строит подсказку. Свести это в «общий разбор каталога» значило бы связать
разные предметы одной формой.

А вот САМО ЧТЕНИЕ у всех одно, и различает оно два состояния, которые прежде
сливались: «каталог ответил» и «каталог не ответил». Второе — отказ КАНАЛА, а не
находка о нашем дереве, и держать слияние он не вправе
([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
Это уже стоило красного: 16.09.2026 на голове #370 обязательная проверка
`journal` дала зелёное, красное и снова зелёное на ОДНОМ дереве — упал шаг
«чужой разбор приведён ссылкой», и упал он на чтении выгрузки. Общая ветка за те
три минуты не двигалась, то есть дерево было то же; очередь встала из-за канала.

Проект уже решил этот класс — и решил иначе. `tests/test_rule_links.py` при
недоступном каталоге ПРОПУСКАЕТСЯ, и причина записана там же: «её предмет тогда
недоступен, и падение говорило бы о канале». Два места применяли одну доктрину
по-разному; здесь она сведена к одному чтению.
"""

from __future__ import annotations

from typing import Any, Final

import ghrest
import report

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


class Silent(RuntimeError):
    """Каталог не ответил.

    Отдельный класс, а не общий отказ чтения: «канал молчит» и «в выгрузке нет
    предмета» дают одинаковое бездействие и значат разное. Первое — состояние
    СЕТИ, и чинить его в дереве нечем; второе — поломка договора с каталогом, и
    она обязана краснеть
    ([039](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/039-three-outcomes-not-two.md)).
    """


def read(url: str) -> dict[str, Any]:
    """Снимок каталога по адресу; молчание канала поднимается своим классом.

    Читатель ловит `Silent` отдельно и отвечает на него СВОИМ исходом — не
    зелёным. Зелёное здесь было бы молчаливым отключением гейта: снаружи оно
    неотличимо от настоящей проверки
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    try:
        return ghrest.raw_json(url)
    except ghrest.TransportError as exc:
        raise Silent(f"каталог не ответил ({url}): {report.cut(str(exc))}") from exc
