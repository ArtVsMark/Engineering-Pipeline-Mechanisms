#!/usr/bin/env python3
"""Гейт: изменение несёт фрагмент журнала.

Правило 030: журнал собирается из фрагментов, и фрагмент едет **вместе с
изменением**, а не пишется после выпуска по памяти. Гейт держит именно это:
изменение, тронувшее что-либо кроме журнала и производных файлов, обязано
принести фрагмент.

Правило 154: ответ «журналу это безразлично» — состояние, а не молчание.
Выражается фрагментом рода ``internal``, первая строка которого называет
причину.

Гейт судит по **коммитам**, а не по рабочему дереву: в прогоне на изменении
всё уже зафиксировано, и рабочего дерева там нет вовсе. Локально это значит,
что фрагмент надо закоммитить, а не только положить рядом.

Исходы (правило 039): ``0`` фрагмент есть · ``1`` изменение отвергнуто ·
``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Final

FRAGMENT_RE: Final = re.compile(r"^changelog\.d/[\w.-]+\.(contract|feat|fix|docs|internal)\.md$")
# Тронув только это, изменение журналу ничего не сообщает.
EXEMPT_PREFIXES: Final = ("changelog.d/",)
EXEMPT_FILES: Final = frozenset({"CHANGELOG.md"})

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «прошло»."""


def run(args: list[str]) -> str:
    """Зовёт git, обращая любой отказ в третий исход."""
    try:
        return subprocess.run(args, capture_output=True, check=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise NotRun(f"{' '.join(args)} → {str(detail).strip()[:300]}") from exc


def changed_files(base: str) -> list[str]:
    """Отдаёт файлы, тронутые изменением относительно общего предка с базой."""
    merge_base = run(["git", "merge-base", base, "HEAD"]).strip()
    if not merge_base:
        raise NotRun(f"общий предок с «{base}» не найден")
    out = run(["git", "diff", "--name-only", "-z", f"{merge_base}...HEAD"])
    files = [name for name in out.split("\0") if name]
    if not files:
        raise NotRun(
            f"относительно «{base}» изменений нет — гейту нечего проверять, "
            "и это ошибка входа, а не «прошло» (075)"
        )
    return files


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    # Площадка отдаёт базу коротким именем («main»), а в дереве прогона она
    # существует как `origin/main`, поэтому приставка нужна. Но ставится она
    # ТОЛЬКО к умолчанию из окружения: переданное ключом имя — это то, что
    # имел в виду зовущий, и молча переписывать его нельзя. Ровно на этом гейт
    # и упал в первом же прогоне на площадке — локально переменной нет, и
    # расхождение не воспроизводилось.
    from_env = os.environ.get("GITHUB_BASE_REF")
    default_base = f"origin/{from_env}" if from_env else "origin/main"
    parser.add_argument("--base", default=default_base, help="ветка сравнения")
    args = parser.parse_args(argv)

    try:
        files = changed_files(args.base)
    except NotRun as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    fragments = [name for name in files if FRAGMENT_RE.match(name)]
    if fragments:
        print(f"фрагмент журнала есть: {', '.join(fragments)}")
        return EXIT_OK

    substantive = [
        name for name in files if name not in EXEMPT_FILES and not name.startswith(EXEMPT_PREFIXES)
    ]
    if not substantive:
        print("изменение тронуло только журнал и производные файлы — фрагмент не нужен")
        return EXIT_OK

    print(
        "отвергнуто: изменение не несёт фрагмента журнала.\n\n"
        "Тронуто файлов вне журнала: "
        f"{len(substantive)}, первые — {', '.join(substantive[:5])}\n\n"
        "Положите changelog.d/<задача>.<род>.md. Если потребителю это\n"
        "безразлично — род `internal`, и первой строкой названа причина:\n"
        "молчание состоянием не является (154). Формат — changelog.d/README.md.",
        file=sys.stderr,
    )
    return EXIT_REJECTED


if __name__ == "__main__":
    raise SystemExit(main())
