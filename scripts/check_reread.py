#!/usr/bin/env python3
"""Гейт: подпись под перечитыванием не едет одна.

Ответы проекта по правилам каталога сняты против ОПРЕДЕЛЁННОЙ выгрузки, и её
номер записан в `.rules/bindings.json` полем `answers_to`. Поднять номер значит
сказать «я перечитал ответы под новую выгрузку»
([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).

ПОДНЯТЫЙ НОМЕР БЕЗ ЕДИНОГО ТРОНУТОГО ОТВЕТА — ЭТО ПОДПИСЬ ПОД НЕСДЕЛАННЫМ.
Снаружи он неотличим от настоящего перечитывания: файл изменён, число выросло,
дрейф замолчал. А ответы остались под прежнюю выгрузку, и молчание дрейфа
теперь врёт — механическое поднятие числа гасит сигнал, ради которого число и
заведено.

ОБРАТНОЕ ЗАКОННО: ответ можно править и не двигая номер — починка одной
строки перечитыванием не является. Гейт судит одно направление, и это названо,
а не подразумевается
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

Исходы (правило 039): ``0`` подпись честна · ``1`` номер поднят в одиночку ·
``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Final

import paths
import report

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2

#: Поле, хранящее номер прочитанной выгрузки каталога.
READ_AT: Final = "answers_to"
#: Раздел с самими ответами.
ANSWERS: Final = "rules"


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «подпись честна»."""


def base_ref() -> str:
    """Общая ветка, относительно которой смотрится изменение."""
    return f"origin/{os.environ.get('GITHUB_BASE_REF') or paths.TRUNK}"


def at(ref: str, path: str) -> dict[str, Any]:
    """Файл ответов на названной ревизии.

    Отказ чтения — третий исход: без базы сравнивать не с чем, и молчаливое
    «изменений нет» было бы выводом из незнания
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    done = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True, encoding="utf-8"
    )
    if done.returncode != 0:
        raise NotRun(f"git show {ref}:{path}: {report.cut(done.stderr.strip())}")
    try:
        said: dict[str, Any] = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise NotRun(f"{ref}:{path} не разбирается: {exc}") from exc
    return said


def order(said: str) -> tuple[int, ...]:
    """Номер выгрузки числами — для сравнения «раньше/позже», а не по строке.

    По строке «1.10» младше «1.9», и гейт, сравнивающий текстом, объявил бы
    подъём понижением на первой же двузначной минорной.
    """
    return tuple(int(part) for part in re.findall(r"\d+", said))


def lonely(was: dict[str, Any], now: dict[str, Any]) -> str:
    """Пусто, если подпись честна; иначе — чем именно она неправда.

    СУДИТСЯ ОДНО НАПРАВЛЕНИЕ — ПОДЪЁМ, и теперь это не только написано, но и
    сделано. Прежде сравнение шло на неравенство: понижение номера отвергалось
    наравне с подъёмом, а сообщение всё равно говорило «поднят» — то есть гейт
    обвинял в том, чего не было, и сам себе противоречил. Нашёл внешний взгляд
    на #279.

    ПОНИЖЕНИЕ — ДРУГОЕ УТВЕРЖДЕНИЕ, и оно законно: им говорят «наши ответы
    сняты против выгрузки постарше, чем мы думали». Подписью под несделанным
    оно не является — наоборот, снимает её. Сосед у сужения назван
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    before, after = str(was.get(READ_AT) or ""), str(now.get(READ_AT) or "")
    if order(after) <= order(before):
        return ""
    if (was.get(ANSWERS) or {}) != (now.get(ANSWERS) or {}):
        return ""
    return (
        f"номер прочитанной выгрузки поднят {was.get(READ_AT)} → {now.get(READ_AT)}, "
        "а ни один ответ не тронут: это подпись под перечитыванием, которого не было. "
        "Либо перечитайте ответы, либо верните номер — молчание дрейфа после такого "
        "подъёма неправда"
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сравнивает подпись с работой и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="", help="ревизия базы; пусто — из окружения")
    args = parser.parse_args(argv)

    try:
        where = str(paths.BINDINGS)
        was = at(args.base or base_ref(), where)
        now = json.loads(paths.BINDINGS.read_text(encoding="utf-8"))
    except (NotRun, OSError, json.JSONDecodeError) as exc:
        print(f"гейт не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN

    said = lonely(was, now)
    if said:
        print(f"отвергнуто: {said}")
        return EXIT_REJECTED
    print("подпись под перечитыванием честна")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
