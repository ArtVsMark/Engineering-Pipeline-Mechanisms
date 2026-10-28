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

ФАЙЛА ЗАХОДА НЕТ, А ВЫЗОВ УПАЛ — ЭТО ТОЖЕ ОТКАЗ. Действие отдаёт файл, только
если дошло до запуска CLI (`src/entrypoints/run.ts` на закреплённом
`46a42b4`); упавшее раньше — на токене, правах, установке — файла не отдаёт.
Шаг зовётся и тогда (условие `execution_file != ''` или исход
`failure`/`cancelled`) с пустым `--from` и называет отказ словами, которые
узнаёт реестр слитого без взгляда (`2e92154`). Прежнее условие «есть файл»
такой отказ пропускало молча. Исход `cancelled` — другое: задание сняли
(тайм-аут задания, ручная отмена или — только там, где группа прогона
объявляет `cancel-in-progress: true`, — замена новым прогоном), и шаг называет
снятие, а не отказ (`6af0b2a`); шаг, снятый собственным тайм-аутом, кончается
`failure` (`58b1367`). Успех без файла — законный пропуск (сверка процесса,
нет вызова по имени), и шаг тогда не зовётся вовсе.

ЗАХОД БЕЗ ОЖИДАЕМОЙ СТРОКИ — ТОЖЕ СВОЁ СОСТОЯНИЕ (#1480). Замер 17.10.2026:
четыре захода взгляда кончились «успехом» за полторы–две минуты, а строки
`ВЕРДИКТ:` в ответе не было — полный набор в такой срок не проходит. Вывод
агента в логе скрыт, а файл захода не выгружается, поэтому причину видно только
отсюда. Со входом `--expect` шаг ищет строку в итоге и в тексте комментария,
отданном инструменту комментария (комментарий взгляда пишется инструментом, а
не итогом), и без неё называет заход словами `NO_VERDICT`. Вход прочих
инструментов ответом не считается: взгляд на сам механизм вердикта зовёт
`grep "ВЕРДИКТ:"`, и такой заход без ответа читался бы заходом с ответом
(поздний взгляд на #1495). Рядом — то, что
обрывает заход молча: вызовы оболочки, ушедшие в фон (`run_in_background`), —
следующего хода у неинтерактивного захода нет, — и отказы разрешений с их
командами.

ЧЕГО ШАГ НЕ ДЕЛАЕТ: не красит задание. Отказ взгляда держать слияние или нет —
вопрос #654, и решает его владелец; здесь отказ перестаёт быть НЕВИДИМЫМ.

Исходы (правило 039): ``0`` файл прочитан, названо всё, что в нём есть, или
назван отказ действия без файла · ``2`` шаг не отработал: названного файла нет
или он не разобрался.
"""

# Модуль держится одной стандартной библиотекой: его зовут и там, где пакет
# транспорта не ставится (ответ по обращению).
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

import main_guard

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Тип сообщения с итогом захода.
RESULT: Final = "result"
#: Исход шага, снятого вместе с заданием: не отказ агента, а отмена.
CANCELLED: Final = "cancelled"
#: Слова, которыми аннотация называет отказ захода. По ним же отказ узнаёт реестр
#: слитого без взгляда (`unlooked`) — одна фраза на пишущего и читающего (090).
REFUSED: Final = "заход отказал"
#: Слова захода, кончившегося без ожидаемой строки ответа: по ним его узнаёт тот
#: же реестр, отдельным состоянием, а не «прошёл, а ответа нет» (#1480).
NO_VERDICT: Final = "заход без ответа"
#: Приставка инструментов, которыми заход пишет ОТВЕТ, — комментария действия.
#: Строка во входе прочих (`grep`, чтение файла) — упоминание, а не ответ.
ANSWER_TOOLS: Final = "mcp__github_comment__"
#: Предел чужого текста в аннотации — тот же, что у общей обрезки (016).
LIMIT: Final = 300


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


def tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Вызовы инструментов агента — блоки `tool_use` его сообщений, по порядку."""
    found: list[dict[str, Any]] = []
    for message in messages:
        if message.get("type") != "assistant":
            continue
        body = message.get("message")
        content = body.get("content") if isinstance(body, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                found.append(block)
    return found


def cut(text: str, limit: int = LIMIT) -> str:
    """Обрезает чужой текст для аннотации, сказав, насколько он обрезан (016).

    КОПИЯ `report.cut` НАМЕРЕННАЯ: модуль держится стандартной библиотекой (его
    зовут и там, где пакета транспорта нет). Подписана в
    `tests/test_one_body.py::SIGNED`, совпадение держит
    `tests/test_agent_run.py::test_the_cut_is_the_transport_one`.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (обрезано, всего {len(text)} знаков)"


def one_line(text: str) -> str:
    """Команда одной строкой, с пределом: аннотация многострочного не держит."""
    return cut(" ".join(text.split()))


def background_of(messages: list[dict[str, Any]]) -> list[str]:
    """Команды оболочки, которые агент увёл в фон: заход их не дождётся."""
    return [
        one_line(str((call.get("input") or {}).get("command") or ""))
        for call in tool_calls(messages)
        if call.get("name") == "Bash"
        and isinstance(call.get("input"), dict)
        and call["input"].get("run_in_background") is True
    ]


def denials_of(messages: list[dict[str, Any]]) -> list[str]:
    """Отказы разрешений из итога захода: инструмент и его команда или путь."""
    for message in reversed(messages):
        if message.get("type") != RESULT:
            continue
        said: list[str] = []
        for denial in message.get("permission_denials") or []:
            if not isinstance(denial, dict):
                continue
            given = denial.get("tool_input")
            what = ""
            if isinstance(given, dict):
                what = str(given.get("command") or given.get("file_path") or "")
            name = str(denial.get("tool_name") or "?")
            said.append(f"{name}: {one_line(what)}" if what else name)
        return said
    return []


def says(messages: list[dict[str, Any]], line: str) -> bool:
    """Есть ли строка в ответе захода: в итоге или в комментарии, отданном инструменту.

    Комментарий взгляда пишет инструмент, а итог захода бывает пересказом —
    поэтому смотрится и то и другое, а не только итог. Из вызовов — только
    инструменты комментария (`ANSWER_TOOLS`): `grep "ВЕРДИКТ:"` строку называет,
    но ответом не является.
    """
    texts = [str(one.get(RESULT) or "") for one in messages if one.get("type") == RESULT]
    texts += [
        json.dumps(call.get("input"), ensure_ascii=False)
        for call in tool_calls(messages)
        if str(call.get("name") or "").startswith(ANSWER_TOOLS)
    ]
    return any(line in text for text in texts)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает модель и отказ захода аннотациями проверки."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", required=True, help="файл захода действия")
    parser.add_argument("--call", default="агент", help="какой вызов агента — для подписи")
    parser.add_argument("--outcome", default="", help="исход шага вызова: success, failure, …")
    parser.add_argument(
        "--expect", default="", help="строка, без которой ответ захода не ответ (`ВЕРДИКТ:`)"
    )
    args = parser.parse_args(argv)

    if not args.source and args.outcome == CANCELLED:
        # СНЯТЫЙ ЗАХОД — НЕ ОТКАЗ АГЕНТА. `cancelled` дают тайм-аут ЗАДАНИЯ,
        # ручная отмена и отмена группой — но последняя только там, где группа
        # объявляет `cancel-in-progress: true`: весь прогон `review.yml`
        # (взгляд, верификатор, поздний взгляд); у ответа по обращению и разбора
        # пунктов замены нет. Комментарий у каждого из пяти вызовов — подписанный
        # дубль этого разбора (071). Какая из причин, шаг не знает, поэтому
        # называет все три, а не угадывает одну. Слова отказа здесь назвали бы
        # отказ, которого не было (`6af0b2a`).
        print(
            f"::warning::{args.call}: заход снят — задание отменено (тайм-аут задания, "
            "ручная отмена или, где группа прогона это объявляет, замена новым прогоном); "
            "это не отказ агента"
        )
        return EXIT_OK
    if not args.source:
        print(
            f"::error::{args.call}: {REFUSED} — действие не отдало файла захода: "
            "оно упало раньше, чем агент его записал"
        )
        return EXIT_OK
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
        # а обрезанная причина — ровно то, из-за чего шаг заведён.
        print(f"::error::{args.call}: {REFUSED} — {failure}")
    background = background_of(messages)
    denials = denials_of(messages)
    if background:
        print(f"::notice::{args.call}: увёл в фон — " + "; ".join(background))
    if denials:
        print(f"::notice::{args.call}: отказы разрешений — " + "; ".join(denials))
    if failure is None and args.expect and not says(messages, args.expect):
        causes = [f"в фоне: {len(background)}"] if background else []
        causes += [f"отказов разрешений: {len(denials)}"] if denials else []
        print(
            f"::warning::{args.call}: {NO_VERDICT} — строки «{args.expect}» нет ни в итоге, "
            "ни в комментарии"
            + (f" ({', '.join(causes)} — команды в соседних аннотациях)" if causes else "")
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
