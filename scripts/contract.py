#!/usr/bin/env python3
"""Поверхность контракта: что потребитель видит и вызывает — снимком, а не прозой.

Пока поверхность описана только словами, «контракт изменился» остаётся делом
вкуса: одному переименование джоба кажется внутренним, другому — несовместимым.
Проза при этом верна и нужна (`docs/release.md`), но проверить по ней нечего
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЧТО ВХОДИТ В ПОВЕРХНОСТЬ, И ПОЧЕМУ ИМЕННО ЭТО:

* **имена джобов** — они и есть имена контекстов проверок, и попадают в защиту
  ветки ДОСЛОВНО и ВНЕ дерева. Переименование джоба ломает чужую настройку,
  которую отсюда не видно и не починить
  ([168](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/168-one-aggregating-required-check.md));
* **события прогонов** — по ним потребитель понимает, когда шаг сработает;
  снятое событие превращает работающий шаг в молчащий;
* **входы ручного запуска** и признак обязательности — вход, ставший
  обязательным, ломает существующий вызов кнопки;
* **имена проверок в `.pipeline.yml` и их классы** — форма ответа потребителя и
  допустимые значения: класс, переставший приниматься, делает чужой ответ
  красным;
* **схема `.pipeline.yml`** — номер формы ответа.

ЧЕГО В ПОВЕРХНОСТИ НЕТ НАМЕРЕННО. Шаги внутри джоба, их порядок и команды,
комментарии, тексты сообщений, внутренние функции механизмов. Потребитель на
них не полагается, и связать себе руки их правкой значило бы объявить контрактом
всё подряд — а контракт, меняющийся от каждой правки, перестают читать.

ПОВЕРХНОСТЬ СНИМАЕТСЯ С ДЕРЕВА, А НЕ ВЕДЁТСЯ СПИСКОМ РУКАМИ. Список руками
отстаёт молча: новый прогон добавляется файлом, и о нём никто не вспомнит
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import paths
import yaml

#: Ключ, под которым YAML 1.1 кладёт раздел событий: `on:` читается булевым.
ON_KEY: Final = True


def _events_of(document: dict[Any, Any]) -> dict[str, Any]:
    """События прогона и входы ручного запуска — как их видит потребитель."""
    raw = document.get("on", document.get(ON_KEY))
    if isinstance(raw, list):
        return {str(name): {} for name in raw}
    if not isinstance(raw, dict):
        return {str(raw): {}} if raw else {}

    events: dict[str, Any] = {}
    for name, body in raw.items():
        shape: dict[str, Any] = {}
        if isinstance(body, dict):
            # ТИПЫ СОБЫТИЯ — ПОВЕРХНОСТЬ: ими определено, КОГДА шаг сработает.
            # Снятый тип превращает работающий шаг в молчащий, и снаружи это
            # неотличимо от «шаг сломался».
            types = body.get("types")
            if types is not None:
                shape["types"] = sorted(str(item) for item in types)
            # У ручного запуска в поверхность входят ИМЕНА входов и их
            # обязательность: вход, ставший обязательным, ломает существующий
            # вызов. Описание и умолчание — не поверхность: вызова они не меняют.
            if str(name) == "workflow_dispatch":
                shape["inputs"] = {
                    str(key): bool((value or {}).get("required", False))
                    for key, value in (body.get("inputs") or {}).items()
                }
        events[str(name)] = shape
    return events


def workflows_surface(directory: Path = paths.WORKFLOWS) -> dict[str, Any]:
    """Снимок поверхности прогонов: имена джобов и события с входами."""
    found: dict[str, Any] = {}
    for path in sorted(directory.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        jobs = {
            str((job or {}).get("name") or job_id)
            for job_id, job in (document.get("jobs") or {}).items()
        }
        found[path.name] = {"jobs": sorted(jobs), "events": _events_of(document)}
    return found


def checks_surface(path: Path = paths.PIPELINE) -> dict[str, Any]:
    """Снимок формы ответа потребителя: схема, имена проверок и их классы."""
    if not path.is_file():
        return {}
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return {}
    checks = document.get("checks") or {}
    classes: dict[str, str] = {}
    for name, answer in checks.items():
        value = answer.get("class") if isinstance(answer, dict) else answer
        # `off` в YAML 1.1 приходит булевым — приводим к тому, как это читает
        # человек, иначе снимок «менялся» бы от способа записи.
        classes[str(name)] = "off" if value is False else str(value)
    return {"schema": document.get("schema"), "checks": classes}


def surface(root: Path = Path()) -> dict[str, Any]:
    """Полный снимок поверхности контракта."""
    return {
        "workflows": workflows_surface(root / paths.WORKFLOWS),
        "answer": checks_surface(root / paths.PIPELINE),
    }


def as_text(shape: dict[str, Any]) -> str:
    """Снимок в устойчивом виде — для сравнения и для показа человеку."""
    return json.dumps(shape, ensure_ascii=False, indent=2, sort_keys=True)


#: Приметы НЕСОВМЕСТИМОГО изменения поверхности: у потребителя от них ломается
#: то, что работало. Список закрытый и назван словами самих различий — второй
#: разбор той же строки разошёлся бы с первым молча (090).
BREAKING_MARKS: Final = ("джобов не стало", "прогон удалён", "схема ответа", "проверки не стало")


def breaking(changes: list[str]) -> list[str]:
    """Из различий поверхности — те, что ломают потребителя.

    ПОЧЕМУ ЭТО РАЗВОДИТСЯ. Добавленный джоб потребитель может не заметить и
    ничего не потерять; удалённый он держит в защите ветки ДОСЛОВНО, и защита
    начинает ждать контекста, которого никто не выдаст — изменение молча
    превращается в вечное ожидание. Требовать переход от обоих значило бы
    объявлять миграцию на каждое расширение и приучить писать её формально
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    return [said for said in changes if any(mark in said for mark in BREAKING_MARKS)]


def differences(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Что в поверхности изменилось — построчно и по-человечески.

    Сравниваются РАЗОБРАННЫЕ снимки, а не тексты файлов: перестановка ключей,
    правка комментария и переформатирование поверхности не меняют, и краснеть на
    них значило бы приучить обходить гейт (051).
    """
    found: list[str] = []
    for file, shape in sorted(after.get("workflows", {}).items()):
        was = (before.get("workflows") or {}).get(file)
        if was is None:
            found.append(f"{file}: новый прогон, джобы {shape['jobs']}")
            continue
        gone = sorted(set(was["jobs"]) - set(shape["jobs"]))
        fresh = sorted(set(shape["jobs"]) - set(was["jobs"]))
        if gone:
            found.append(f"{file}: джобов не стало — {gone}")
        if fresh:
            found.append(f"{file}: добавлены джобы — {fresh}")
        if was["events"] != shape["events"]:
            found.append(f"{file}: события или входы изменились")
    for file in sorted(set(before.get("workflows", {})) - set(after.get("workflows", {}))):
        found.append(f"{file}: прогон удалён целиком")

    was_answer = before.get("answer") or {}
    now_answer = after.get("answer") or {}
    if was_answer.get("schema") != now_answer.get("schema"):
        found.append(f"схема ответа: {was_answer.get('schema')} → {now_answer.get('schema')}")
    was_checks = was_answer.get("checks") or {}
    now_checks = now_answer.get("checks") or {}
    for name in sorted(set(was_checks) | set(now_checks)):
        if was_checks.get(name) != now_checks.get(name):
            found.append(
                f"проверка «{name}»: {was_checks.get(name, '—')} → {now_checks.get(name, '—')}"
            )
    return found
