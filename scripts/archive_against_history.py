#!/usr/bin/env python3
"""Архив находок сверяется с историей общей ветки — приёмка строже чинимого (193).

ЗАЧЕМ (#864). Перечитка архива (`findings_archive.py --reread`) — массовая
автоматическая починка данных: за один проход она дописала 107 снятий и
связей. Приёмка у неё была «тест на синтетике и второй проход с нулём». Второй
проход доказывает идемпотентность, но не верность: ошибись разбор строки
снятия — повторный проход тем же разбором тоже дал бы ноль.

КРИТЕРИЙ СТРОЖЕ — НЕЗАВИСИМЫЙ ЧИТАТЕЛЬ ТОГО ЖЕ ИСТОЧНИКА. Здесь не зовётся
общий разбор снятий (`changerefs.resolutions_parsed`): сверка идёт по телам
коммитов общей ветки самым прямым способом —

* снятие подтверждено, если отпечаток стоит в строке `Разобрано:` хоть одного
  коммита общей ветки;
* связь «A дубль B» подтверждена, если в такой строке эти два отпечатка стоят
  РЯДОМ и между ними только слово «дубль».

Правило смежности нарочно проще грамматики разбора: там, где они расходятся,
неправ может быть любой, и расхождение называется числом, а не сглаживается.

ЗАМЕР 26.09.2026 НА НАСТОЯЩЕМ АРХИВЕ (ветка `badges`): снятий 1255, без строки
в истории — 0; связей 107, не подтверждено 11. Все 11 — одна форма: строка
«A дубль B, C дубль D», которую общий разбор читает цепочкой через запятую и
приписывает двойника цели. Чинит это отдельная задача: разбор общий с #809, и
в #864 он не меняется.

ПРЕДЕЛ НАЗВАН. Снятие проверкой починки (#848) строки `Разобрано:` не имеет —
его источник лента изменения, а не история. Такое снятие здесь не
подтверждается и считается отдельной строкой, а не расхождением.

Исходы (правило 039): ``0`` архив сходится с историей · ``2`` не отработал ·
``3`` расхождения есть и названы.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_DIFFERS: Final = 3

#: Строка снятия в теле коммита: слово в начале, после маркера списка и кавычек.
RESOLUTION_HEAD: Final = "разобрано"
#: Сколько расхождений печатать поимённо: остальное — числом.
SHOWN: Final = 20


class NotRun(RuntimeError):
    """Сверка не отработала: третий исход, а не «сходится»."""


def resolution_lines(log: str) -> list[str]:
    """Строки `Разобрано:` всех тел — прямым чтением, без общего разбора."""
    return [
        line
        for line in log.splitlines()
        if line.strip().lstrip("-*` ").lower().startswith(RESOLUTION_HEAD)
    ]


def twin_said(lines: str, mark: str, twin: str) -> bool:
    """Стоят ли «mark дубль twin» рядом в строке снятия."""
    return re.search(rf"{mark}`?\s+дубль\s+`?{twin}", lines, re.IGNORECASE) is not None


def check(archive: dict[str, Any], log: str) -> dict[str, list[str]]:
    """Расхождения архива с историей: снятия без строки и связи без пары."""
    text = "\n".join(resolution_lines(log))
    resolutions: dict[str, dict[str, Any]] = archive.get("resolutions") or {}
    unseen = sorted(mark for mark in resolutions if mark not in text)
    unpaired = sorted(
        f"{mark} дубль {said['twin_of']}"
        for mark, said in resolutions.items()
        if said.get("twin_of") and not twin_said(text, mark, str(said["twin_of"]))
    )
    return {"без строки": unseen, "связь без пары": unpaired}


def trunk_log(ref: str) -> str:
    """Тела всех коммитов общей ветки."""
    done = subprocess.run(
        ["git", "log", ref, "--format=%B"], capture_output=True, text=True, encoding="utf-8"
    )
    if done.returncode != 0 or not done.stdout.strip():
        raise NotRun(f"история {ref} не прочитана: {done.stderr.strip() or 'пусто'} (075)")
    return done.stdout


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает счёт сверки и аннотацию при расхождении."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, help="findings.json архива")
    parser.add_argument("--ref", default="origin/main", help="общая ветка")
    args = parser.parse_args(argv)
    try:
        path = Path(args.archive)
        if not path.is_file():
            raise NotRun(f"архива {path} нет — сверять нечего (075)")
        archive = json.loads(path.read_text(encoding="utf-8"))
        if not archive.get("resolutions"):
            raise NotRun("в архиве нет снятий — пустой вход, а не «сходится» (075)")
        found = check(archive, trunk_log(args.ref))
    except (NotRun, OSError, ValueError) as refusal:
        print(f"сверка архива не отработала: {refusal}", file=sys.stderr)
        return EXIT_BROKEN
    resolutions = archive["resolutions"]
    twins = sum(1 for said in resolutions.values() if said.get("twin_of"))
    print(
        f"снятий {len(resolutions)}, без строки в истории {len(found['без строки'])}; "
        f"связей {twins}, без пары {len(found['связь без пары'])}"
    )
    for kind, items in found.items():
        for item in items[:SHOWN]:
            print(f"  {kind}: {item}")
        if len(items) > SHOWN:
            print(f"  {kind}: ещё {len(items) - SHOWN}")
    if not any(found.values()):
        return EXIT_OK
    print(
        f"::warning title=архив находок расходится с историей (193)::"
        f"без строки {len(found['без строки'])}, связей без пары "
        f"{len(found['связь без пары'])} — см. вывод шага"
    )
    return EXIT_DIFFERS


if __name__ == "__main__":
    raise SystemExit(main())
