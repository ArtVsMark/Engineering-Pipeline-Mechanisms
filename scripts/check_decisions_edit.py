#!/usr/bin/env python3
"""Гейт правила 043: решение не правится задним числом — его отменяет новое.

ПОЧЕМУ ГЕЙТ СТОИТ НА ИЗМЕНЕНИИ, А НЕ НА ИСТОРИИ. Правило само называет признак
нарушения: «в истории файла с решением есть коммиты „актуализировал“». Соблазн
велик — пройти `git log` по всем записям и покраснеть на прошлом. Но прошлое
правкой изменения не чинится, а красное, которое нечем погасить, учат обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Поэтому предмет здесь — что ЭТО изменение делает с уже принятой записью.

ЗАМОРОЖЕНО НЕ ВСЁ, И ГРАНИЦА НАЗВАНА. Последствия решения копятся: они
становятся известны после того, как решение применили, и дописывать их — не
правка решения, а его жизнь. Строка статуса меняется тоже: именно ею запись
помечается заменённой. А вот контекст, само решение и рассмотренные
альтернативы — то, из чего решение состоит (042): переписать их значит выдать
новое решение за старое, задним числом, без следа.

ЗАПИСЬ НЕ ИСЧЕЗАЕТ. Удаление принятой записи — тот же подлог, только полный:
после него нечему быть заменённым. Переименование считается удалением
намеренно — ссылка на прежний адрес после него ведёт в никуда (022).

ЛОЖНАЯ ПРЕМИСА — НЕ ИСКЛЮЧЕНИЕ, И ЭТО РЕШЕНО ЗДЕСЬ. Запись `001` однажды
выдала себе такое исключение: её обоснование оказалось построено на
непроверенном утверждении, и она была ПРАВЛЕНА с пометкой «решение осталось
прежним, ложным было его обоснование». Внешний взгляд назвал это на #169:
правка тронула раздел, который тот же документ двумя коммитами раньше объявил
неприкосновенным. Гейт исключения не даёт: решение, стоявшее на ложной
премисе, стояло ни на чём, и честный ход — новая запись, называющая старую
заменённой. Так требование остаётся одним для всех, а не «одним, кроме
важных случаев» (051).

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Final

import paths

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Где живут записи решений. Каталог один: второй разъехался бы с первым молча.
RECORDS: Final = "docs/decisions/"
#: Заголовок раздела записи.
HEADING_RE: Final = re.compile(r"^## (?P<name>.+?)\s*$")
#: Разделы, которые изменение трогать не вправе. Это состав самого решения
#: (042) — остальное записи дописывают по ходу.
FROZEN_RE: Final = re.compile(r"^(?:Контекст|Решение|Отвергнут(?:ые|ый)\b)", re.IGNORECASE)


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def base_ref() -> str:
    """Общая ветка, относительно которой смотрится изменение."""
    return f"origin/{os.environ.get('GITHUB_BASE_REF') or paths.TRUNK}"


def _git(*args: str) -> str:
    """Запуск git; отказ — третий исход, а не пустой ответ."""
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def touched(base: str) -> list[tuple[str, str]]:
    """Записи решений, тронутые изменением: буква состояния и путь."""
    try:
        spot = _git("merge-base", base, "HEAD").strip()
    except NotRun as exc:
        raise NotRun(f"общая точка с {base} не найдена: {exc}") from exc
    # `-z` обязателен: без него git экранирует имена с не-ASCII, и такой путь
    # молча выпадает из отбора (165). Ответ идёт полем состояния и путём через
    # NUL; у переименования путей два — старый и новый.
    fields = [
        field
        for field in _git("diff", "--name-status", "-z", f"{spot}...HEAD").split("\0")
        if field
    ]
    found: list[tuple[str, str]] = []
    while fields:
        state = fields.pop(0)[:1]
        if not fields:
            break
        path = fields.pop(0)
        if state == "R" and fields:
            path = fields.pop(0)
        if path.startswith(RECORDS) and path.endswith(".md"):
            found.append((state, path))
    return found


def frozen(text: str) -> dict[str, str]:
    """Разделы записи, которые изменение трогать не вправе: имя → содержимое."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            name = heading["name"]
            current = name if FROZEN_RE.match(name) else None
            if current:
                sections[current] = []
            continue
        if current:
            sections[current].append(line.rstrip())
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def at(ref: str, path: str) -> str:
    """Содержимое файла на указанной точке истории."""
    return _git("show", f"{ref}:{path}")


def rewritten(base: str, path: str) -> list[str]:
    """Замороженные разделы записи, которые изменение переписало."""
    try:
        was, now = frozen(at(base, path)), frozen(at("HEAD", path))
    except NotRun as exc:
        raise NotRun(f"{path}: обе стороны не прочитаны — {exc}") from exc
    problems: list[str] = []
    for name, body in was.items():
        if name not in now:
            problems.append(f"{path}: раздел «{name}» пропал — решение переписано задним числом")
        elif now[name] != body:
            problems.append(f"{path}: раздел «{name}» переписан — пересмотр это НОВАЯ запись")
    return problems


def findings(base: str) -> list[str]:
    """Что изменение сделало с уже принятыми записями."""
    problems: list[str] = []
    for state, path in touched(base):
        if state in {"A", "?"}:
            continue
        if state in {"D", "R"}:
            problems.append(f"{path}: принятая запись удалена или переименована — заменять нечем")
            continue
        problems.extend(rewritten(base, path))
    return problems


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет записи решений на изменении с их видом в базе."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="точка сравнения; по умолчанию общая ветка")
    args = parser.parse_args(argv)
    base = args.base or base_ref()

    try:
        seen = touched(base)
        problems = findings(base)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not problems:
        print(
            f"чисто: записей решений тронуто {len(seen)}, принятое не переписано"
            if seen
            else "чисто: записей решений это изменение не трогает"
        )
        return EXIT_OK
    print(f"правок принятых решений задним числом: {len(problems)}")
    for said in problems:
        print(f"  {said}")
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
