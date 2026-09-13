#!/usr/bin/env python3
"""Тело уплотнённого коммита: одна запись вместо склейки черновика.

Изменения попадают в общую ветку уплотнением (`docs/decisions/006`), и тело
такого коммита площадка собирает сама — склейкой ВСЕХ сообщений ветки. Пока
коммит один, это незаметно; на трёх коммитах получается три копии трейлеров
соавторства плюс своя от площадки. Замер на [#41](../../pull/41): три
`Co-Authored-By` в одном коммите.

Гейт атрибуции этим не ломается — он смотрит на наличие подписи, а не на
число, — но итоговая история становится черновиком, а не записью о работе:
«нашли», «починили», «подтянули базу» осмысленны внутри изменения и бесполезны
в общей ветке.

Поэтому тело собирается ЗДЕСЬ и передаётся площадке при слиянии:

* заголовки коммитов — списком, как в описании изменения;
* связи с задачами — по строке на задачу, разбором из общего модуля;
* снятые находки — там же и по тому же разбору;
* трейлеры соавторства — **один раз**, из последнего коммита: подпись у всех
  коммитов ветки одна и та же, и повторять её нечего.

Исходы (правило 039): ``0`` тело собрано · ``2`` собрать не из чего.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Final

import changerefs
import paths
import report

#: Трейлеры хвостового блока: соавторство и адрес окна. Читаются из последнего
#: коммита ветки — он же самый свежий, и подпись окна в нём та же.
TRAILER_RE: Final = re.compile(r"^(?:Co-Authored-By|Claude-Session):\s*\S", re.IGNORECASE)

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Собрать не из чего: третий исход, а не пустое тело."""


def git(*args: str) -> str:
    """Зовёт git, обращая отказ в третий исход."""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, check=True, text=True, encoding="utf-8"
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise NotRun(f"git {' '.join(args)} → {report.cut(str(detail))}") from exc


def trailers_of(text: str) -> list[str]:
    """Хвостовые трейлеры сообщения, без повторов и в порядке появления."""
    found: list[str] = []
    for line in text.splitlines():
        if TRAILER_RE.match(line.strip()) and line.strip() not in found:
            found.append(line.strip())
    return found


def compose(branch: str, base: str) -> str:
    """Собирает тело уплотнения из коммитов ветки."""
    merge_base = git("merge-base", f"origin/{base}", branch).strip()
    # `--no-merges`: служебное подтягивание базы в общей ветке не запись о
    # работе. Его заголовок в теле уплотнения только мешает читателю.
    log = git("log", "--reverse", "--no-merges", "--format=%s", f"{merge_base}..{branch}")
    subjects = [line for line in log.splitlines() if line]
    if not subjects:
        raise NotRun(f"в ветке {branch} нет коммитов сверх {base} — собирать нечего (075)")

    bodies = git("log", "--reverse", "--format=%B%x00", f"{merge_base}..{branch}").split("\0")
    links = changerefs.links_in_all(bodies)
    resolved = changerefs.resolved_in_all(bodies)
    # Трейлеры берутся из ПОСЛЕДНЕГО коммита: подпись у ветки одна, и повторять
    # её столько раз, сколько было коммитов, — это шум, а не атрибуция.
    trailers = trailers_of("\n".join(bodies))

    lines = [f"- {subject}" for subject in subjects]
    if links:
        lines += ["", *[str(link) for link in links]]
    if resolved:
        lines += ["", *[f"Разобрано: {mark}" for mark in resolved]]
    if trailers:
        lines += ["", *trailers]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает тело уплотнения для слияния."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True, help="ветка изменения")
    parser.add_argument("--base", default=paths.TRUNK, help="общая ветка")
    args = parser.parse_args(argv)

    try:
        print(compose(args.branch, args.base))
    except NotRun as exc:
        print(f"тело не собрано: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
