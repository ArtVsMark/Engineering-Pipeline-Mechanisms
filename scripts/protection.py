#!/usr/bin/env python3
"""Защита общей ветки: объявление и действующее — одно чтение на всех.

ЧИТАТЕЛЕЙ ДВОЕ, И ОНИ РАСХОДИЛИСЬ. Дрейф спрашивал площадку про **набор
правил** (`rules/branches/<ветка>`), а сверка обязательного контекста — про
**классическую защиту** (`branches/<ветка>/protection/...`). Это две разные
поверхности одной настройки, и проект защищён первой: замер 15.09.2026 — набор
«Protect main», режим `active`, правила `deletion`, `non_fast_forward`,
`required_status_checks` с единственным контекстом `ci-complete`. Сверка при этом
читала пустоту и объявляла находку «у ветки нет обязательных контекстов» —
красное на здоровой настройке, то есть красное, которое учат обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md),
[022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Нашёл это первый же настоящий заход сверки — его попросил владелец.

ФОРМА ЗАЩИТЫ НАЗЫВАЕТСЯ, А НЕ ПОДРАЗУМЕВАЕТСЯ. Ветка бывает защищена и
классически — у соседей по семье так и есть. Пустой ответ про набор правил на
защищённой ветке означает «защита другой формы», а не «защиты нет»: выдать одно
за другое значило бы соврать в сторону, удобную механизму
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ТОКЕН ВЛАДЕЛЬЦА ЗДЕСЬ НЕ НУЖЕН, И ЭТО ЗАМЕР, А НЕ ДОПУЩЕНИЕ. Набор правил
площадка отдаёт публично: 15.09.2026 оба адреса — `rules/branches/main` и
`rulesets` — прочитаны вообще без токена. Классическая защита требует прав, и
именно из-за неё сверка считалась «ненастроенной без токена владельца».
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import ghrest
import paths

#: Правило набора, несущее список обязательных контекстов.
CHECKS_RULE: Final = "required_status_checks"


class NotRead(RuntimeError):
    """Настройку прочитать не удалось: это отказ входа, а не «защиты нет»."""


def declared(where: Path | None = None) -> dict[str, Any]:
    """Объявленная защита общей ветки — из дерева."""
    path = where or paths.PROTECTION
    if not path.is_file():
        raise NotRead(f"нет {path}: защита общей ветки не объявлена (075)")
    said: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not said.get("branch"):
        raise NotRead(f"{path}: ветка не названа — сравнивать не с чем (075)")
    return said


def live(repo: str, branch: str, token: str) -> list[dict[str, Any]]:
    """Правила, действующие на ветке, — из набора правил площадки."""
    try:
        # СПИСОК ЧИТАЕТСЯ ДО КОНЦА (212): правило за краем первой страницы
        # иначе не сравнилось бы с объявленным.
        said = list(ghrest.paginate(f"repos/{repo}/rules/branches/{branch}", token))
    except ghrest.TransportError as exc:
        raise NotRead(f"правила ветки «{branch}» не прочитаны: {exc}") from exc
    return [one for one in said if isinstance(one, dict)]


def guarded(repo: str, branch: str, token: str) -> bool:
    """Считает ли площадка ветку защищённой — чем бы та ни была защищена.

    Спрашивается, только когда набор правил пуст: тогда ответ «да» означает
    защиту ДРУГОЙ формы, и это разные находки для человека (154).
    """
    try:
        said = ghrest.request("GET", f"repos/{repo}/branches/{branch}", token) or {}
    except ghrest.TransportError as exc:
        raise NotRead(f"состояние ветки «{branch}» не прочитано: {exc}") from exc
    return bool(said.get("protected"))


def kinds(rules: list[dict[str, Any]]) -> list[str]:
    """Виды действующих правил, по одному разу каждый."""
    return sorted({str(one.get("type") or "") for one in rules})


def contexts(rules: list[dict[str, Any]]) -> list[str]:
    """Обязательные контексты из действующих правил — каждое имя по одному разу.

    ПОВТОР ИМЕНИ НЕ НАХОДКА. Ветку вправе накрывать несколько наборов правил —
    репозитория и организации, — и один и тот же контекст приходит тогда дважды.
    Список с повтором не сошёлся бы с объявлением, и сверка назвала бы находку на
    исправной настройке: красное на законном учат обходить
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Нашёл внешний взгляд (`824d3cf`).
    """
    found: set[str] = set()
    for one in rules:
        if str(one.get("type") or "") != CHECKS_RULE:
            continue
        given = one.get("parameters") or {}
        found.update(
            str((item or {}).get("context") or "")
            for item in given.get("required_status_checks") or []
        )
    return sorted(name for name in found if name)


def strict(rules: list[dict[str, Any]]) -> bool:
    """Требует ли площадка свежести изменения относительно общей ветки."""
    return any(
        bool((one.get("parameters") or {}).get("strict_required_status_checks_policy"))
        for one in rules
        if str(one.get("type") or "") == CHECKS_RULE
    )
