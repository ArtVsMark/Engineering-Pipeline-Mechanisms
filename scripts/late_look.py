#!/usr/bin/env python3
"""Ответ позднего взгляда получает адресата, переживающего прогон.

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ ШАГ, А НЕ ПРАВО РЕВЬЮЕРА ПИСАТЬ САМОМУ. На изменении
действие ревью ведёт свой комментарий само — там есть событие и есть контекст
изменения. У позднего взгляда контекста нет: он запускается кнопкой по НОМЕРУ
уже слитого изменения, и адресата действию взять неоткуда. Выдать ревьюеру
право писать в площадку значило бы расширить список разрешённого до записи —
на канале, чей вход собран из проверяемого текста
([085](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/085-content-from-the-subject-is-untrusted-input-to-the-prompt.md)).
Поэтому ревьюер остаётся читателем, а комментарий пишет механизм: он берёт
ответ из файла прогона (`execution_file`) и кладёт его туда же, куда кладёт
ответ обычного ревью, — в само изменение.

ОТВЕТ НЕ ВЫДУМЫВАЕТСЯ. Файла нет, он не разобрался или ответа в нём нет —
это второй исход, а не пустой комментарий: комментарий «находок 0», которого
никто не выносил, хуже отсутствия комментария
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

КОММЕНТАРИЙ НАЗЫВАЕТ СЕБЯ ПОЗДНИМ, И ЭТО НЕ ОФОРМЛЕНИЕ. По скрытой строке
`unlooked.LATE_MARKER` реестр отличает поздний взгляд от взгляда до слияния:
без неё вердикт позднего прогона снял бы запись «взгляда не было», и реестр
сказал бы, что взгляд был вовремя
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

Исходы (правило 039): ``0`` ответ записан · ``2`` шаг не отработал.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

import ghrest
import report
import unlooked

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Тип последнего сообщения прогона: в нём лежит текст ответа.
RESULT: Final = "result"


class NotRun(RuntimeError):
    """Шаг не отработал: второй исход, а не «ответ пустой»."""


def answer_of(raw: str) -> str:
    """Достаёт текст ответа из файла прогона действия.

    Файл — список сообщений, последнее из которых с типом ``result`` несёт
    текст. Разбирается именно он, а не «последнее сообщение вообще»: прогон
    может оборваться, и тогда ответа нет — это состояние, а не пустая строка.
    """
    try:
        document: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotRun(f"файл прогона не разобрался: {exc}") from exc
    if not isinstance(document, list):
        raise NotRun("файл прогона не список сообщений — форма ответа изменилась")
    for message in reversed(document):
        if isinstance(message, dict) and message.get("type") == RESULT:
            text = str(message.get(RESULT) or "").strip()
            if not text:
                raise NotRun("прогон завершился без текста ответа")
            return text
    raise NotRun("в файле прогона нет сообщения с итогом — взгляд не состоялся")


def compose(number: int, answer: str) -> str:
    """Собирает комментарий: сначала граница, потом ответ."""
    return "\n".join(
        [
            unlooked.LATE_MARKER,
            "### Поздний взгляд по общей ветке",
            "",
            f"Это **не** ревью изменения #{number}, а взгляд на его код уже в общей",
            "ветке: соседние изменения влились, конфликтов нет, история переписана",
            "уплотнением. Записывается он отдельным состоянием реестра, а не как",
            "состоявшийся вовремя взгляд.",
            "",
            answer,
            "",
        ]
    )


def post(repo: str, number: int, token: str, body: str) -> None:
    """Кладёт ответ в само изменение — туда же, куда кладёт его обычное ревью."""
    ghrest.request("POST", f"repos/{repo}/issues/{number}/comments", token, {"body": body})


def main(argv: list[str] | None = None) -> int:
    """Точка входа: переносит ответ прогона в изменение и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr", type=int, required=True, help="номер слитого изменения")
    parser.add_argument("--from", dest="source", required=True, help="файл прогона действия")
    parser.add_argument("--apply", action="store_true", help="записать, а не показать")
    args = parser.parse_args(argv)

    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        source = Path(args.source)
        if not source.is_file():
            raise NotRun(f"файла прогона нет: {args.source}")

        body = compose(args.pr, answer_of(source.read_text(encoding="utf-8")))
        if not args.apply:
            print(f"записал бы в #{args.pr}:\n{body}")
            return EXIT_OK
        post(args.repo, args.pr, token, body)
        print(f"ответ позднего взгляда записан в #{args.pr}")
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except ghrest.TransportError as exc:
        print(f"шаг не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
