#!/usr/bin/env python3
"""Сводный гейт: опрашивает проверки на голове изменения.

Правило 168 запрещает собирать сводный гейт через ``needs``: агрегатор на
зависимостях при падении соседа не краснеет, а **пропускается**, — а
пропущенную запись защита ветки засчитывает за пройденную (187). То есть в
норме он зелёный и ничего не решает, а в аварии разрешает слияние ровно тогда,
когда обязан запретить.

Правильная форма — одна работа с постоянным именем, которая **сама спрашивает
у площадки** проверки на голове и доходит до вердикта при любом исходе
соседей. Она и реализована здесь.

Что считается отказом, кроме красного:

* объявленный джоб **отсутствует** на голове — пустой список означает «прогон
  не стартовал», а не «зелено» (075);
* джоб **пропущен**: ``skipped`` у того, кто обязан был идти, засчитывается за
  отказ, иначе выключение шага становится способом обойти гейт;
* джоб **отменён**: отменённая запись не является пройденной.

Исходы (правило 039): ``0`` все зелёные · ``1`` есть незелёные или отсутствующие
· ``2`` опрос не отработал.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Final

API_ROOT: Final = "https://api.github.com"
PENDING: Final = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})

EXIT_GREEN: Final = 0
EXIT_RED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Опрос не отработал: третий исход, а не «зелено»."""


def api(url: str, token: str) -> Any:
    """Читает REST площадки — самый дешёвый транспорт для опроса (001)."""
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise NotRun(f"GET {url} → {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise NotRun(f"GET {url} → площадка недоступна: {exc.reason}") from exc


def check_runs(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
    """Отдаёт записи проверок на голове, включая повторы имён."""
    runs: list[dict[str, Any]] = []
    page = 1
    while True:
        # filter=latest — только последняя запись на каждое имя. Без него
        # повторный прогон на той же голове оставляет прошлые записи, и
        # проверка «больше одной живой записи» краснела бы на здоровом.
        url = (
            f"{API_ROOT}/repos/{repo}/commits/{sha}/check-runs"
            f"?per_page=100&page={page}&filter=latest"
        )
        payload = api(url, token)
        chunk = payload.get("check_runs", [])
        runs.extend(chunk)
        if len(chunk) < 100:
            return runs
        page += 1


def verdict(
    runs: list[dict[str, Any]], required: list[str], selfname: str
) -> tuple[list[str], bool]:
    """Выносит вердикт по объявленным именам; вторым отдаёт «ещё идут»."""
    problems: list[str] = []
    waiting = False

    for name in required:
        if name == selfname:
            continue
        found = [run for run in runs if run.get("name") == name]
        if not found:
            problems.append(f"{name}: записи нет на голове — прогон не стартовал, а не «зелено»")
            continue

        # Отменённые записи отбрасываются, ЕСЛИ у имени есть неотменённая.
        # Отмена — штатное следствие группы отмены: новый толчок или новая
        # метка гасят прогон на той же голове, и его записи остаются лежать
        # рядом с живыми. Считать их отказом значит краснеть на здоровом —
        # ровно это и случилось в первом прогоне на площадке, и `filter=latest`
        # от этого НЕ спасает: записи разных прогонов приходят обе.
        #
        # Если же отменены ВСЕ записи имени, отказ остаётся отказом: живого
        # вердикта у этого шага нет, а отменённая запись пройденной не является.
        live = [run for run in found if run.get("conclusion") != "cancelled"]
        if not live:
            problems.append(f"{name}: все записи отменены — пройденной ни одна не считается")
            continue

        # Две НЕотменённые записи с одним именем — настоящая неоднозначность:
        # одно обязательное имя выдают два разных прогона, и какой из них
        # решает, неизвестно.
        if len(live) > 1:
            problems.append(
                f"{name}: на голове {len(live)} живых записей с одним именем — вердикт неоднозначен"
            )
        for run in live:
            status = run.get("status")
            conclusion = run.get("conclusion")
            if status in PENDING:
                waiting = True
            elif conclusion == "success":
                continue
            elif conclusion == "skipped":
                problems.append(f"{name}: пропущен, а обязан был идти — это отказ, а не «зелено»")
            else:
                problems.append(f"{name}: {conclusion or status}")
    return problems, waiting


def main(argv: list[str] | None = None) -> int:
    """Точка входа: опрашивает голову до вердикта и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--required", required=True, help="имена джобов через запятую")
    parser.add_argument("--self-name", default="ci-complete", help="собственное имя, себя не ждём")
    parser.add_argument("--timeout", type=int, default=900, help="сколько ждать соседей, секунд")
    parser.add_argument("--interval", type=int, default=20, help="пауза между опросами, секунд")
    args = parser.parse_args(argv)

    try:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo or not args.sha:
            raise NotRun("не названы репозиторий или голова изменения")

        required = [name.strip() for name in args.required.split(",") if name.strip()]
        if not required:
            raise NotRun("список обязательных имён пуст — предмет опроса не найден (075)")

        deadline = time.monotonic() + args.timeout
        while True:
            runs = check_runs(args.repo, args.sha, token)
            if not runs:
                raise NotRun(
                    f"на голове {args.sha[:8]} нет ни одной записи проверок — "
                    "это ошибка входа, а не «зелено» (075)"
                )
            problems, waiting = verdict(runs, required, args.self_name)
            if not waiting:
                break
            if time.monotonic() >= deadline:
                problems.append(f"соседи не завершились за {args.timeout} с — вердикта нет")
                break
            print(f"ждём соседей на голове {args.sha[:8]}…", flush=True)
            time.sleep(args.interval)
    except NotRun as exc:
        print(f"опрос не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if problems:
        print(f"красно ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")
        return EXIT_RED

    print(f"зелено: все объявленные проверки на голове {args.sha[:8]} пройдены")
    return EXIT_GREEN


if __name__ == "__main__":
    raise SystemExit(main())
