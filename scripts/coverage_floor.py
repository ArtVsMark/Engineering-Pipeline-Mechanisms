#!/usr/bin/env python3
"""Порог покрытия берётся из РЯДА замеров, а не пишется рукой.

ПОЧЕМУ ИЗ РЯДА. Рукописный порог устаревает в обе стороны: назначенный низко,
он молчит, пока покрытие сползает; назначенный высоко — краснеет на законном и
приучает себя обходить
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md),
[051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Ряд прогонов уже копит долю покрытия по дням, и порог из него ВЫВОДИТСЯ:
«не ниже достигнутого». Двигается он только вверх — не решением, а тем, что
максимум ряда не убывает.

НАПРАВЛЕНИЕ ЗЕРКАЛЬНО ПРАВИЛУ
[050](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/050-limits-move-down-only.md),
и это названо, а не подразумевается. Оно говорит про ПРЕДЕЛЫ — сверху, — и двигаются они
только вниз; здесь граница снизу, и ужесточение для неё — вверх. Принцип один:
граница ходит в сторону строгости, и послабление требует решения, а не правки
числа. Утверждать это цитатой без оговорки значило бы утверждать то, чего
правило не говорит
([204](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/204-a-citation-is-checked-by-applicability.md)).

ЧТО СРАВНИВАЕТСЯ: последний день ряда против максимума ряда. Оба числа — из
ОДНОГО источника, и второго замера здесь не заводится: витрина публикует ту же
долю, и два чтения одного разошлись бы молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

ЭТО СЧЁТ, А НЕ СТОП. Падение покрытия бывает законным — код вынесли в пакет,
покрытое удалили, — и держать на этом слияние значило бы краснеть на
законном. Поэтому строка едет в отчёт долга (класс `advisory`, адресат —
каждое изменение), а решение остаётся за человеком
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

РЯД КОРОТОК, И ЭТО НАЗВАНО. Замер 20.09.2026: точек четыре — 88.0, 88.1, 88.3,
88.6, — и ни одного падения. Предмета в истории у предиката НЕТ, и выдавать
это за подтверждение нельзя: порог проверяется откатом, а не прошлым
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
Пока точек мало, порог и есть почти последнее значение — тем он и честен:
сползание видно с первого дня, а не через месяц накопления.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Final, NamedTuple

import ghrest

#: Ветка, в которой механизм ряда публикует накопленное, и файл в ней.
SERIES_BRANCH: Final = "runs"
SERIES_FILE: Final = "runs.json"
#: Поле дня с долей покрытия — то же имя, которым его пишет ряд.
COVERAGE: Final = "coverage"


class NotRun(RuntimeError):
    """Порог не прочитан: третий исход, а не «покрытие в порядке»."""


class Floor(NamedTuple):
    """Порог, свежее значение и то, что из них следует."""

    #: День последнего замера — чтобы читатель видел, насколько число свежее.
    day: str
    #: Доля покрытия последнего дня ряда.
    now: float
    #: Максимум ряда: он и есть «достигнутое».
    floor: float
    #: Сколько дней в ряду. Короткий ряд не делает порог неверным, но делает
    #: его менее устойчивым, и читателю это видно.
    days: int

    @property
    def below(self) -> bool:
        """Опустилось ли покрытие ниже достигнутого."""
        return self.now < self.floor

    def said(self) -> str:
        """Строка отчёта долга: числа, а не оценка."""
        if not self.below:
            return (
                f"покрытие: {self.now:.1f}% при достигнутом {self.floor:.1f}% "
                f"(ряд {self.days} дн., замер {self.day})"
            )
        return (
            f"покрытие ниже достигнутого: {self.now:.1f}% против {self.floor:.1f}% "
            f"(ряд {self.days} дн., замер {self.day}) — это счёт, а не стоп: "
            f"падение бывает законным, и решение за человеком (154)"
        )


def series(repo: str, token: str) -> dict[str, Any]:
    """Ряд прогонов из своей ветки — общим транспортом, как и всё прочее (090).

    Читается ТЕМ ЖЕ приёмом, что и ответ потребителя: `contents` с указанием
    ссылки. Ветка `runs` — не общая, и без `ref` площадка отдала бы файл с
    `main`, где его нет вовсе.
    """
    try:
        got = ghrest.request(
            "GET", f"repos/{repo}/contents/{SERIES_FILE}?ref={SERIES_BRANCH}", token
        )
    except ghrest.TransportError as exc:
        raise NotRun(f"ряд прогонов не прочитан: {exc}") from exc
    if not got or "content" not in got:
        raise NotRun(
            f"в ветке «{SERIES_BRANCH}» нет {SERIES_FILE}: порог брать неоткуда. "
            "Ноль вместо незнания читался бы как «покрытия нет» (045)"
        )
    try:
        said = base64.b64decode(str(got["content"])).decode("utf-8")
        document: dict[str, Any] = json.loads(said)
    except (ValueError, UnicodeDecodeError) as exc:
        raise NotRun(f"{SERIES_FILE} не разобрался: {exc}") from exc
    return document


def floor_of(document: dict[str, Any]) -> Floor:
    """Порог и свежее значение из разобранного ряда.

    Чистая: площадка сюда не ходит. Так проверка идёт по данным, а не по
    подделке транспорта
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    days = document.get("days")
    if not isinstance(days, dict) or not days:
        raise NotRun("в ряду нет ни одного дня — порог брать неоткуда (075)")
    known = {
        day: float(one[COVERAGE])
        for day, one in days.items()
        if isinstance(one, dict) and isinstance(one.get(COVERAGE), int | float)
    }
    if not known:
        raise NotRun(
            f"ни один день ряда не несёт поля «{COVERAGE}» — покрытие в ряду не копится. "
            "Порог из пустоты был бы выдуман (075)"
        )
    last = max(known)
    return Floor(day=last, now=known[last], floor=max(known.values()), days=len(known))


def look(repo: str, token: str) -> Floor:
    """Порог по живому ряду: чтение и разбор вместе, для зовущего."""
    return floor_of(series(repo, token))
