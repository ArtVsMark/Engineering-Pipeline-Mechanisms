#!/usr/bin/env python3
"""Заход агента называет свою модель и свой отказ — аннотацией, а не только логом.

ЗАМЕР 23.09.2026, ИЗ-ЗА КОТОРОГО ШАГ НАПИСАН. #669 объявил `--model
claude-opus-5-5` во всех пяти вызовах `anthropics/claude-code-action`, и после
слияния КАЖДЫЙ заход кончался за 0–1 с. Проверка оставалась зелёной (шаг
объявлен `continue-on-error`), изменения сливались без взгляда, а причину
отказа знал только лог — окну он закрыт прокси, человеку его надо открыть.
Нашлась причина обходом: CLI, который несло закреплённое действие (2.1.261),
этого имени в своём реестре моделей не знал (#673).

И ВТОРОЕ, ЧЕГО ПРОЕКТ НЕ ЗНАЛ: на какой модели идёт взгляд вообще (#663).
Модель — умолчание чужого действия, и сменись оно, сменился бы ревьюер без
следа.

Оба ответа лежат в файле захода (`execution_file`), который действие отдаёт и
при успехе, и при отказе: первое сообщение `system/init` несёт модель,
последнее `result` — итог и, при `is_error`, текст отказа. Шаг читает их и
печатает аннотациями проверки — их площадка отдаёт обычным чтением, и видит их
и человек в списке проверок, и окно через API.

ФОРМУ ФАЙЛА РАЗБИРАЕТ ОДИН МОДУЛЬ. Ответ позднего взгляда и разбор пунктов
читают тот же файл (`late_look.answer_of`); список сообщений разбирается здесь,
а они берут готовое
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ЧЕГО ШАГ НЕ ДЕЛАЕТ: не красит задание. Отказ взгляда держать слияние или нет —
вопрос #654, и решает его владелец; здесь отказ перестаёт быть НЕВИДИМЫМ.

Исходы (правило 039): ``0`` файл прочитан, названо всё, что в нём есть ·
``2`` шаг не отработал: файла нет или он не разобрался.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Тип сообщения с итогом захода.
RESULT: Final = "result"


class NotRun(RuntimeError):
    """Шаг не отработал: файла захода нет или он не разобрался."""


def messages_of(raw: str) -> list[dict[str, Any]]:
    """Сообщения захода из файла действия — список словарей.

    Не список — это не «пустой заход», а другая форма файла: чужое действие
    сменило выход, и разбирать дальше значило бы гадать (045).
    """
    try:
        document: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotRun(f"файл захода не разобрался: {exc}") from exc
    if not isinstance(document, list):
        raise NotRun("файл захода не список сообщений — форма выхода действия изменилась")
    return [one for one in document if isinstance(one, dict)]


def model_of(messages: list[dict[str, Any]]) -> str:
    """Модель захода из сообщения `system/init`; пусто — модель не названа."""
    for message in messages:
        if message.get("type") == "system" and message.get("subtype") == "init":
            return str(message.get("model") or "")
    return ""


def failure_of(messages: list[dict[str, Any]]) -> str | None:
    """Текст отказа захода; ``None`` — заход отказом не кончился.

    Отказ — это итог с `is_error`, а не отсутствие итога: оборванный заход без
    итога называется отдельно, словами «итога нет», и за отказ не выдаётся.
    """
    for message in reversed(messages):
        if message.get("type") == RESULT:
            if not message.get("is_error"):
                return None
            said = " ".join(str(message.get(RESULT) or "").split())
            return said or f"итог «{message.get('subtype') or 'не назван'}» без текста"
    return "итога нет — заход оборвался раньше, чем подвёл его"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает модель и отказ захода аннотациями проверки."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", required=True, help="файл захода действия")
    parser.add_argument("--call", default="агент", help="какой вызов агента — для подписи")
    args = parser.parse_args(argv)

    try:
        path = Path(args.source)
        if not path.is_file():
            raise NotRun(f"файла захода нет: {args.source}")
        messages = messages_of(path.read_text(encoding="utf-8"))
    except NotRun as exc:
        print(f"::warning::{args.call}: {exc} — ни модели, ни отказа не видно", file=sys.stderr)
        return EXIT_BROKEN

    model = model_of(messages)
    print(f"::notice::{args.call}: модель захода — {model or 'не названа в файле захода'}")
    failure = failure_of(messages)
    if failure is not None:
        # Текст отказа не режется: он короткий по природе («модель не найдена»),
        # а обрезанная причина — ровно то, из-за чего шаг заведён. Модуль
        # держится одной стандартной библиотекой: его зовут и там, где пакет
        # транспорта не ставится (ответ по обращению).
        print(f"::error::{args.call}: заход отказал — {failure}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
