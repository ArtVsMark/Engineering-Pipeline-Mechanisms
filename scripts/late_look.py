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
import os
import sys
from pathlib import Path
from typing import Final

import agent_run
import ghrest
import report
import unlooked

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Тип последнего сообщения прогона: в нём лежит текст ответа.
RESULT: Final = agent_run.RESULT
#: Метка ответа верификатора. СВОЯ, а не метка позднего взгляда: оба ответа
#: переносит этот шаг токеном прогона, и под общей меткой ответ верификатора
#: засчитывался поздним взглядом по изменению (взгляд на #815).
VERIFY_MARKER: Final = "<!-- verify: проверка премисы одной находки, а не взгляд на изменение -->"


class NotRun(RuntimeError):
    """Шаг не отработал: второй исход, а не «ответ пустой»."""


def answer_of(raw: str) -> str:
    """Достаёт текст ответа из файла прогона действия.

    Файл — список сообщений, последнее из которых с типом ``result`` несёт
    текст. Разбирается именно он, а не «последнее сообщение вообще»: прогон
    может оборваться, и тогда ответа нет — это состояние, а не пустая строка.

    ИТОГ С ОТКАЗОМ — НЕ ОТВЕТ. Отказ судит `agent_run.failure_of`, тот же, что
    печатает его аннотацией: прежде здесь итог с `is_error` принимался за
    ответ, и перенос ответа верификатора, который смотрит только на наличие
    токена, понёс бы в изменение текст отказа (`dde5c62`).
    """
    # ФОРМУ ФАЙЛА РАЗБИРАЕТ ОДИН МОДУЛЬ — `agent_run`: он же называет модель и
    # отказ захода, и второе понимание «что такое файл захода» разошлось бы с
    # первым молча (090).
    try:
        document = agent_run.messages_of(raw)
    except agent_run.NotRun as exc:
        raise NotRun(str(exc)) from exc
    failure = agent_run.failure_of(document)
    for message in reversed(document):
        if message.get("type") == RESULT:
            if failure is not None:
                raise NotRun(f"{agent_run.REFUSED} — {failure}")
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


def compose_verification(answer: str) -> str:
    """Собирает ответ верификатора: своя метка и своя граница, потом ответ."""
    return "\n".join(
        [
            VERIFY_MARKER,
            "### Проверка премисы находки",
            "",
            "Это ответ верификатора об одной находке из реестра, а не взгляд на",
            "изменение: позднего взгляда он не заменяет.",
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
    parser.add_argument(
        "--verify", action="store_true", help="ответ верификатора, а не позднего взгляда"
    )
    args = parser.parse_args(argv)
    report.announce(not args.apply)

    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        source = Path(args.source)
        if not source.is_file():
            raise NotRun(f"файла прогона нет: {args.source}")

        answer = answer_of(source.read_text(encoding="utf-8"))
        body = compose_verification(answer) if args.verify else compose(args.pr, answer)
        if not args.apply:
            print(f"записал бы в #{args.pr}:\n{body}")
            return EXIT_OK
        post(args.repo, args.pr, token, body)
        said = "верификатора" if args.verify else "позднего взгляда"
        print(f"ответ {said} записан в #{args.pr}")
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except ghrest.TransportError as exc:
        print(f"шаг не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
