#!/usr/bin/env python3
"""Будильник сводного гейта: `ci` завершился — сводка, вынесенная раньше, перезапускается.

РЕШЕНИЕ ВЛАДЕЛЬЦА 04.10.2026 (#1007, вариант 2). Сводный гейт `ci-complete`
ждёт соседей с коротким сроком. Под очередью площадки соседи кончаются позже
срока, и сводка краснеет «соседи не завершились» при полностью зелёной голове.
Замер 01.10.2026: шесть таких падений за час, и сама она не пересобирается.
Срок не поднимается: сводка держала бы исполнителя всё ожидание, а при очереди
дольше срока беда та же.

ПЕРЕЗАПУСК, А НЕ НОВАЯ ЗАПИСЬ. Прогон по `workflow_run` вешает свои записи на
голову ОБЩЕЙ ветки, а не изменения, и защита ветки их не увидит. Перезапуск
прогона `ci-complete` идёт на его собственном событии изменения, и вердикт
ложится на ту голову, которую ждёт защита. Приём — тот же, что у очереди с
пропущенным взглядом (`automerge.call_the_owed_look`).

ЧЬЯ СВОДКА ПЕРЕЗАПУСКАЕТСЯ. Последняя на голове, завершённая красным и
завершённая НЕ ПОЗЖЕ, чем кончился `ci`: её вердикт вынесен, пока соседи ещё
шли. Идущую не трогают — она дождётся сама. Отменённую тоже: её отменил более
новый заход на той же голове. Красное, вынесенное после конца `ci`, —
настоящее, и перезапуск его не перекрасит.

ГРАНИЦА НАЗВАНА (195). Красное по существу, вынесенное раньше конца `ci`, —
например, обязательная проверка упала, пока совещательные ещё шли, — тоже
попадает под перезапуск. Он вынесет тот же вердикт: цена — один лишний
прогон сводки на одно завершение `ci`, и предел попыток (`MAX_ATTEMPTS`)
держит её конечной.

Исходы (правило 039): ``0`` перезапущено или перезапускать нечего — что
именно, названо · ``2`` будильник не отработал.
"""

import argparse
import os
import sys
from typing import Any, Final

import ghrest
import report

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Файл прогона сводного гейта: его прогоны на голове и перезапускаются.
SUMMARY_FLOW: Final = "ci-complete.yml"
#: Сколько попыток у прогона сводки, после которых будильник его не зовёт. Три:
#: два завершения `ci` на одной голове (прогон и его перезапуск) плюс запас.
#: Держится номером попытки у площадки, а не памятью будильника (049).
MAX_ATTEMPTS: Final = 3


class NotRun(RuntimeError):
    """Будильник не отработал: третий исход, а не «перезапускать нечего»."""


def stale_summary(runs: list[dict[str, Any]], ci_done_at: str) -> dict[str, Any] | None:
    """Прогон сводки, чей красный вердикт вынесен раньше конца `ci`; нет такого — ``None``.

    Берётся ПОСЛЕДНИЙ прогон головы: прежние заменены им, и перезапуск
    старого вынес бы вердикт рядом с новым. Время — ISO 8601 площадки в одной
    зоне, и строки сравниваются как время.
    """
    if not runs:
        return None
    last = max(runs, key=lambda run: str(run.get("created_at") or ""))
    if last.get("status") != "completed" or last.get("conclusion") != "failure":
        return None
    if str(last.get("updated_at") or "") > ci_done_at:
        return None
    if int(last.get("run_attempt") or 1) >= MAX_ATTEMPTS:
        return None
    return last


def summary_runs(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
    """Прогоны сводного гейта на голове — только на событии изменения."""
    return list(
        ghrest.paginate(
            f"repos/{repo}/actions/workflows/{SUMMARY_FLOW}/runs?head_sha={sha}&event=pull_request",
            token,
            key="workflow_runs",
        )
    )


def wake(repo: str, sha: str, ci_done_at: str, token: str, *, dry_run: bool) -> str:
    """Перезапускает устаревшую сводку на голове; возвращает, что сделано, словами."""
    runs = summary_runs(repo, sha, token)
    if not runs:
        return f"на голове {sha[:8]} прогонов сводки нет — будить нечего"
    stale = stale_summary(runs, ci_done_at)
    if stale is None:
        return (
            f"сводка на голове {sha[:8]} не устарела — "
            "идёт, зелёная, отменена или исчерпала попытки"
        )
    run = stale["id"]
    if dry_run:
        return f"{report.DRY} перезапустил бы сводку {run} на голове {sha[:8]}"
    try:
        ghrest.request("POST", f"repos/{repo}/actions/runs/{run}/rerun", token)
    except ghrest.TransportError as exc:
        raise NotRun(f"сводка {run} не перезапущена: {exc}") from exc
    return f"сводка {run} на голове {sha[:8]} перезапущена: её вердикт вынесен раньше конца ci"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: одна голова, одно завершение `ci`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument(
        "--ci-done-at",
        default=os.environ.get("CI_DONE_AT", ""),
        help="когда кончился прогон ci, ISO 8601 площадки",
    )
    parser.add_argument("--dry-run", action="store_true", help="назвать, не перезапуская")
    args = parser.parse_args(argv)
    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo or not args.sha or not args.ci_done_at:
            raise NotRun("не названы репозиторий, голова или время конца ci")
        print(wake(args.repo, args.sha, args.ci_done_at, token, dry_run=args.dry_run))
    except (NotRun, ghrest.TransportError) as exc:
        print(f"будильник не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
