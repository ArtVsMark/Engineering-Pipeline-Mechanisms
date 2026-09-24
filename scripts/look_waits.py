#!/usr/bin/env python3
"""Взгляд — последним: ждёт вердикта обязательных проверок головы.

РЕШЕНИЕ ВЛАДЕЛЬЦА 24.09.2026 (#762): внешний взгляд запускается последним —
когда обязательные проверки головы зелёные. На красной голове он не гоняется:
изменение всё равно не сольётся, а после починки следующий толчок позовёт
взгляд заново.

ПОЧЕМУ ОЖИДАНИЕ ВНУТРИ ЗАДАНИЯ, А НЕ ДРУГОЕ СОБЫТИЕ. Запуск по `workflow_run`
брал бы файл прогона из общей ветки и терял бы контекст изменения, на котором
держится весь `review.yml`. Главное же — запись проверки `review` появляется
на голове сразу, толчком, как и прежде: очередь ждёт взгляда с первой секунды
(#654), и щели «проверки зелёные, а взгляда ещё нет» не возникает.

ЧТО СЧИТАЕТСЯ ВЕРДИКТОМ. Запись `ci-complete` на голове — сводный гейт
обязательных проверок (`docs/pipeline.md`). Совещательных он не ждёт, и взгляда
тоже: взаимного ожидания нет.

ТРИ ОТВЕТА, И ТРЕТИЙ НЕ ПРИТВОРЯЕТСЯ ПЕРВЫМ (045). Зелёная — взгляду идти;
красная или снятая — не идти, и это названо; вердикта не дождались или не
прочитали — взгляду ИДТИ, как было до #762: молчание гейта не отменяет
взгляд.

Исходы (правило 039): ``0`` ответ дан (записан в `$GITHUB_OUTPUT` строкой
``run=yes|no``) · ``2`` не отработал — нет токена, головы или репозитория.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Final

import ghrest

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Сводный гейт обязательных проверок: его вердикт и ждёт взгляд.
GATE: Final = "ci-complete"

#: Ответы: взгляду идти или нет.
GREEN: Final = "green"
RED: Final = "red"
SILENT: Final = "silent"


def gate_verdict(repo: str, sha: str, token: str) -> str | None:
    """Вердикт сводного гейта на голове; ``None`` — ещё не завершён или записи нет."""
    runs = list(
        ghrest.paginate(
            f"repos/{repo}/commits/{sha}/check-runs?check_name={GATE}&filter=latest",
            token,
            key="check_runs",
        )
    )
    done = [run for run in runs if run.get("status") == "completed"]
    if not done:
        return None
    return GREEN if all(run.get("conclusion") == "success" for run in done) else RED


def wait(repo: str, sha: str, token: str, timeout: float, interval: float) -> str:
    """Ждёт вердикта гейта до срока: зелёный, красный или «не дождались»."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            said = gate_verdict(repo, sha, token)
        except ghrest.TransportError as exc:
            print(f"вердикт гейта не прочитан: {exc}", flush=True)
            said = None
        if said is not None:
            return said
        if time.monotonic() >= deadline:
            return SILENT
        print(f"ждём вердикта «{GATE}» на голове {sha[:8]}…", flush=True)
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: ждёт гейт и пишет, идти ли взгляду."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default="", help="голова изменения")
    parser.add_argument("--timeout", type=float, default=1500.0, help="сколько ждать, секунд")
    parser.add_argument("--interval", type=float, default=20.0, help="шаг опроса, секунд")
    args = parser.parse_args(argv)
    token = ghrest.token_from_env()
    if not token or not args.repo or not args.sha:
        print("ожидание не отработало: нет токена, репозитория или головы (045)", file=sys.stderr)
        return EXIT_BROKEN
    said = wait(args.repo, args.sha, token, args.timeout, args.interval)
    run = "no" if said == RED else "yes"
    if said == RED:
        print(
            f"«{GATE}» на голове {args.sha[:8]} красный — взгляд не нужен: изменение не "
            "сольётся, а после починки следующий толчок позовёт его заново (#762)"
        )
    elif said == SILENT:
        print(
            f"вердикта «{GATE}» не дождались — взгляд идёт, как до #762: молчание его не отменяет"
        )
    else:
        print(f"«{GATE}» на голове {args.sha[:8]} зелёный — взгляд идёт последним")
    out = os.environ.get("GITHUB_OUTPUT", "")
    if out:
        with open(out, "a", encoding="utf-8") as sink:
            sink.write(f"run={run}\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
