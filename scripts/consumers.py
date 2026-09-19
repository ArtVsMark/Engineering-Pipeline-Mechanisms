#!/usr/bin/env python3
"""Сверка потребителей: кто подключён, на какой версии стоит и что обошёл.

ОТДАЁТСЯ НАРУЖУ: этим заходом потребитель проверяет, что его видно.

ФАКТЫ О ПОТРЕБИТЕЛЕ ЧИТАЮТСЯ У НЕГО, А НЕ ВЕДУТСЯ У НАС. Версия, на которой он
стоит, и то, какие шаги он обошёл, лежат в ЕГО `.pipeline.yml`: факты о проекте
публикует сам проект (174). Реестр, ведомый за потребителя, разошёлся бы с ним
молча — и разошёлся бы в ту сторону, где мы считаем, что всё хорошо.

АДРЕСА ВСЁ ЖЕ НАШИ. Прочитать чужой ответ можно только зная, у кого спрашивать,
и за то, кого оповещать при смене версии контракта, отвечаем мы
([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).
Поэтому в `.rules/consumers.json` лежат адреса, и только они.

ОБХОД — ГЛАВНОЕ, ЧТО ЗДЕСЬ ВИДНО. Потребитель, обошедший общий механизм, —
сильнейшее свидетельство пробела, и оно невидимо, пока не объявлено: снаружи
обход неотличим от «шаг не подключён»
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

ПУСТОЙ СПИСОК — СОСТОЯНИЕ, А НЕ ОТКАЗ. Подключённых сегодня нет, и заход
говорит это словом. Считать пустоту поломкой значило бы требовать наличия
потребителей, а считать её тишиной — выдавать незнание за «всё хорошо»
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЧЕГО ЗАХОД НЕ ДЕЛАЕТ: не заводит потребителей и не правит их деревья.
Подключение — их решение, и след ведёт его владелец
([185](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/185-a-trail-is-an-address-and-its-owner-keeps-it-alive.md)).

Исходы (правило 039): ``0`` сверка прочитана · ``2`` не отработал ·
``3`` часть ответов не прочитана — сказано, а не выдано за «все на свежей».
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any, Final

import ghrest
import paths
import pipeline_checks as policy

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_UNREAD: Final = 3

#: Ключ со списком записей. Прочее в файле — пояснения, и читать их нечем.
CONNECTED: Final = "connected"
#: Что обязана назвать запись. Список разрешительный: поле, которого здесь нет,
#: в запись не попадает молча (068).
REQUIRED: Final = ("repo", "since", "why")
#: Как читается «подключённых нет»: состояние, а не тишина.
NOBODY: Final = "подключённых потребителей нет"


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не пустая сверка."""


def registry(root: Path) -> list[dict[str, Any]]:
    """Объявленные адреса потребителей — из реестра, а не из памяти."""
    path = root / paths.CONSUMERS
    if not path.is_file():
        raise NotRun(f"нет {path}: у кого спрашивать, взять неоткуда (075)")
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc
    rows = said.get(CONNECTED)
    if not isinstance(rows, list):
        raise NotRun(f"{path}: раздел «{CONNECTED}» не список — читать нечего")
    for one in rows:
        missing = [field for field in REQUIRED if not str((one or {}).get(field, "")).strip()]
        if missing:
            raise NotRun(f"{path}: запись {one} не называет {', '.join(missing)}")
    return [dict(one) for one in rows]


def answer_of(repo: str, token: str) -> dict[str, Any]:
    """Ответ потребителя по проверкам — из ЕГО дерева, а не из нашего реестра.

    Читается общая ветка: она и есть то, что у него работает. Отказ здесь —
    третий исход захода, а не пустой ответ: «файла не видно» и «обходов нет»
    снаружи неотличимы (045).
    """
    got = ghrest.request("GET", f"repos/{repo}/contents/{paths.PIPELINE}", token)
    if not isinstance(got, dict) or "content" not in got:
        raise NotRun(f"{repo}: ответ по проверкам не прочитан")
    raw = base64.b64decode(str(got["content"])).decode("utf-8")
    # РАЗБОР ФОРМЫ — У ТОГО, КТО ФОРМОЙ ВЛАДЕЕТ. Свой разбор YAML здесь был
    # бы вторым пониманием ответа по проверкам, и разошлись бы они молча (090).
    try:
        return policy.answer_text(raw, repo)
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc


def bypassed(answer: dict[str, Any]) -> list[str]:
    """Шаги, которые потребитель ОБОШЁЛ, — по его же объявлению.

    Обход объявляется классом `off` с причиной. Без причины это не состояние,
    а молчание, и такую запись заход называет отдельно.
    """
    found: list[str] = []
    for name, said in (answer.get("checks") or {}).items():
        # КЛАСС ПРИВОДИТСЯ К СТРОКЕ ЧУЖИМ РАЗБОРОМ, А НЕ СВОИМ. YAML 1.1 читает
        # `off` БУЛЕВЫМ — та же ловушка, что с `on:` в прогонах, — и свой разбор
        # был бы вторым её пониманием: разошлись бы они молча, а «обход» стал бы
        # невидимым ровно там, где он и объявлен
        # ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
        raw = said if not isinstance(said, dict) else (said or {}).get("class")
        if policy.text_of(raw) != policy.OFF:
            continue
        why = str(said.get("why", "")).strip() if isinstance(said, dict) else ""
        found.append(f"{name}" + ("" if why else " — БЕЗ ПРИЧИНЫ"))
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает сверку по каждому объявленному потребителю."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень ЭТОГО дерева")
    args = parser.parse_args(argv)

    try:
        rows = registry(args.root)
    except NotRun as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not rows:
        print(f"{NOBODY} — сверять не с кем, и это состояние, а не тишина (154)")
        return EXIT_OK

    token = ghrest.token_from_env()
    if not token:
        print(
            "ответы потребителей НЕ ПРОЧИТАНЫ: токена площадки нет, а лежат они в их"
            " деревьях. Это не «все на свежей версии» (045)",
            file=sys.stderr,
        )
        return EXIT_UNREAD

    unread = 0
    for one in rows:
        repo = str(one["repo"])
        try:
            answer = answer_of(repo, token)
        except (NotRun, ghrest.TransportError) as exc:
            print(f"  {repo}: не прочитан — {exc}", file=sys.stderr)
            unread += 1
            continue
        span = str(answer.get("contract") or "не объявлен")
        skipped = bypassed(answer)
        print(f"  {repo}: диапазон {span} · обойдено {len(skipped)}")
        for name in skipped:
            print(f"      обойдено: {name}")
    if unread:
        print(f"не прочитано ответов: {unread} из {len(rows)}", file=sys.stderr)
        return EXIT_UNREAD
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
