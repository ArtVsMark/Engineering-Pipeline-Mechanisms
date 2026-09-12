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
import pipeline_checks as policy
import yaml


def _events_of(document: dict[Any, Any]) -> dict[str, Any]:
    """События прогона и входы ручного запуска — как их видит потребитель."""
    raw = policy.events_raw(document)
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
BREAKING_MARKS: Final = (
    "джобов не стало",
    "прогон удалён",
    "схема ответа",
    # Снятая проверка: потребитель держит её имя в защите ветки ДОСЛОВНО, и
    # защита начинает ждать контекста, которого никто не выдаст. Примета была
    # в списке и раньше — словами «проверки не стало», — но таких слов не
    # печатал никто: снятие выходило строкой «проверка «x»: required → —» и
    # мимо списка. Мёртвая примета хуже отсутствующей: список выглядел полным.
    # Нашёл внешний взгляд на #142.
    "проверка снята",
    # Снятое событие превращает работающий шаг в молчащий, а снаружи это
    # неотличимо от «шаг сломался». Снятый ТИП события — то же самое, только
    # тише.
    "событий не стало",
    "типов события не стало",
    # Вход, ставший обязательным, ломает существующий вызов кнопки: у
    # потребителя он идёт без этого входа и начинает отвергаться.
    "входы стали обязательными",
    "входов не стало",
)


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


def _event_changes(file: str, was: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """Различия в событиях прогона — РАЗДЕЛЬНО: снятое отдельно от добавленного.

    Прежде здесь стояла одна строка «события или входы изменились», и она
    накрывала оба случая сразу. Для потребителя они противоположны: добавленное
    событие он может не заметить и ничего не потерять, а снятое превращает
    работающий шаг в молчащий — и снаружи это неотличимо от «шаг сломался».
    Одной строкой различить их было нельзя, и несовместимое проходило как
    расширение. Нашёл внешний взгляд на #142.
    """
    found: list[str] = []
    gone = sorted(set(was) - set(now))
    fresh = sorted(set(now) - set(was))
    if gone:
        found.append(f"{file}: событий не стало — {gone}")
    if fresh:
        found.append(f"{file}: добавлены события — {fresh}")
    for name in sorted(set(was) & set(now)):
        before_shape = was.get(name) or {}
        after_shape = now.get(name) or {}
        lost_types = sorted(
            set(before_shape.get("types") or ()) - set(after_shape.get("types") or ())
        )
        if lost_types:
            # ИМЯ СОБЫТИЯ ИДЁТ ПОСЛЕ ПРИМЕТЫ, а не внутри неё: примета ищется
            # подстрокой, и вставленное в середину имя разрывало совпадение —
            # строка печаталась, а несовместимой не считалась.
            found.append(f"{file}: типов события не стало у «{name}» — {lost_types}")
        new_types = sorted(
            set(after_shape.get("types") or ()) - set(before_shape.get("types") or ())
        )
        if new_types:
            # Расширение: шаг начнёт срабатывать чаще. Потребителю это видно и
            # его не ломает — поэтому строка есть, а приметы несовместимого нет.
            found.append(f"{file}: типы события «{name}» добавлены — {new_types}")
        was_inputs = before_shape.get("inputs") or {}
        now_inputs = after_shape.get("inputs") or {}
        lost_inputs = sorted(set(was_inputs) - set(now_inputs))
        if lost_inputs:
            found.append(f"{file}: входов не стало у «{name}» — {lost_inputs}")
        # ОБЯЗАТЕЛЬНОСТЬ ВХОДА — ЧАСТЬ ПОВЕРХНОСТИ, и она движется в одну
        # сторону больно: вход, ставший обязательным, отвергает существующий
        # вызов кнопки. Обратное — послабление, и ломать оно не может.
        # НОВЫЙ обязательный вход ломает так же, как ужесточённый: у
        # потребителя кнопка вызывается без него и начинает отвергаться.
        tightened = sorted(
            key for key, needed in now_inputs.items() if needed and not was_inputs.get(key, False)
        )
        if tightened:
            found.append(f"{file}: входы стали обязательными у «{name}» — {tightened}")
        loosened = sorted(
            key for key, needed in now_inputs.items() if not needed and was_inputs.get(key, False)
        )
        if loosened:
            # Послабление: прежний вызов остаётся верным. Видно — да, ломает —
            # нет, и различие названо строкой, а не молчанием (051).
            found.append(f"{file}: входы стали необязательными у «{name}» — {loosened}")
        added_inputs = sorted(set(now_inputs) - set(was_inputs) - set(tightened))
        if added_inputs:
            found.append(f"{file}: добавлены входы у «{name}» — {added_inputs}")
    return found


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
        found += _event_changes(file, was["events"], shape["events"])
    for file in sorted(set(before.get("workflows", {})) - set(after.get("workflows", {}))):
        found.append(f"{file}: прогон удалён целиком")

    was_answer = before.get("answer") or {}
    now_answer = after.get("answer") or {}
    if was_answer.get("schema") != now_answer.get("schema"):
        found.append(f"схема ответа: {was_answer.get('schema')} → {now_answer.get('schema')}")
    was_checks = was_answer.get("checks") or {}
    now_checks = now_answer.get("checks") or {}
    for name in sorted(set(was_checks) | set(now_checks)):
        if was_checks.get(name) == now_checks.get(name):
            continue
        if name not in now_checks:
            # СНЯТИЕ НАЗЫВАЕТСЯ СВОИМИ СЛОВАМИ, а не стрелкой в пустоту:
            # по этим словам его узнаёт `breaking()`, и «→ —» мимо него
            # проходило молча.
            found.append(f"проверка снята: «{name}» была {was_checks[name]}")
            continue
        if name not in was_checks:
            found.append(f"проверка добавлена: «{name}» — {now_checks[name]}")
            continue
        found.append(f"проверка «{name}»: {was_checks[name]} → {now_checks[name]}")
    return found
