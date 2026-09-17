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
* трейлеры соавторства — **один раз**, и читаются они из ХВОСТОВОГО БЛОКА
  КАЖДОГО сообщения: последнего абзаца, состоящего целиком из строк
  «Ключ: значение». Подпись у коммитов ветки одна и та же, повторять её нечего,
  а прозаическое упоминание трейлера директивой не становится (156).

  ЗДЕСЬ СТОЯЛО «из последнего коммита», и это было неверно: строка бралась по
  приставке имени из склейки ВСЕХ сообщений. Утверждение пережило починку —
  правку внесли в тело функции, а шапку не перечитали, и обещание осталось
  описывать снятое поведение. Нашёл внешний взгляд, и назвал дважды.

Исходы (правило 039): ``0`` тело собрано · ``2`` собрать не из чего.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from typing import Final

import changerefs
import paths
import report

#: Трейлеры, которые тело уплотнения переносит: соавторство и адрес окна.
TRAILER_RE: Final = re.compile(r"^(?:Co-Authored-By|Claude-Session):\s*\S", re.IGNORECASE)
#: Строка вида «Ключ: значение» — из таких целиком состоит хвостовой блок.
KEY_VALUE: Final = re.compile(r"^[A-Za-z][\w-]*:\s*\S")

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


def tail_block(text: str) -> list[str]:
    """Хвостовой блок сообщения: последний абзац, ЦЕЛИКОМ из «Ключ: значение».

    Абзац, в котором есть хоть одна прозаическая строка, хвостовым блоком не
    является — и это не придирка: именно так отличается директива от рассказа о
    ней.
    """
    строки = [line.rstrip() for line in text.strip().splitlines()]
    хвост: list[str] = []
    for line in reversed(строки):
        if not line.strip():
            break
        хвост.append(line.strip())
    хвост.reverse()
    if not хвост or not all(KEY_VALUE.match(line) for line in хвост):
        return []
    return хвост


def trailers_of(bodies: Iterable[str]) -> list[str]:
    """Трейлеры из ХВОСТОВЫХ БЛОКОВ сообщений, без повторов и по порядку.

    ЧИТАЕТСЯ ХВОСТОВОЙ БЛОК КАЖДОГО СООБЩЕНИЯ, А НЕ СТРОКА ГДЕ УГОДНО В СКЛЕЙКЕ.
    Прежняя редакция брала строку по приставке имени трейлера из текста ВСЕХ
    коммитов, склеенных вместе, — то есть принимала за директиву прозаическое
    упоминание. Тело уплотнения уезжает в общую ветку, и подставленный так
    «соавтор» переписыванию уже не поддаётся
    ([156](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/156-trailers-live-in-the-tail-not-in-the-prose.md)).

    ЗАМЕР 17.09.2026 по 500 телам коммитов: строк-трейлеров 866, и ШЕСТЬ из них
    стояли вне хвостового блока. Вреда пока не вышло — все шесть настоящие, —
    но предмет живой, а разбор его не различал.

    БЛОК ЧИТАЕТСЯ У КАЖДОГО СООБЩЕНИЯ СВОЙ, А НЕ ОДИН НА СКЛЕЙКУ: у склейки
    хвостовой блок один — последний, — и соавтор, названный в первом коммите
    ветки, потерялся бы. Два ложных утверждения стояли рядом: комментарий
    обещал «трейлеры берутся из последнего коммита», а брались они из всех
    сразу.
    """
    found: list[str] = []
    for body in bodies:
        for line in tail_block(body):
            if TRAILER_RE.match(line) and line not in found:
                found.append(line)
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
    # СТРОКИ СНЯТИЯ ПЕРЕНОСЯТСЯ, А НЕ СОБИРАЮТСЯ ЗАНОВО. Прежде тело строилось
    # из одних отпечатков, и причина — «премиса не подтвердилась, потому что…» —
    # терялась по дороге в общую ветку: два разных исхода снятия становились
    # там одной строкой (039, 044).
    resolved = changerefs.resolutions_in_all(bodies)
    # Трейлеры берутся из хвостового блока КАЖДОГО коммита и склеиваются без
    # повторов: подпись у ветки одна, повторять её по числу коммитов — шум.
    trailers = trailers_of(bodies)

    lines = [f"- {subject}" for subject in subjects]
    if links:
        lines += ["", *[str(link) for link in links]]
    if resolved:
        lines += ["", *resolved]
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
