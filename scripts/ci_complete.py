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

Опрашиваются не все проверки подряд, а **обязательные**: класс каждой объявлен
данными в `.pipeline.yml` и читается модулем ``pipeline_checks``. Совещательные
опрашиваются тоже, но слияния не держат — их красное печатается отдельно и
уходит адресату, переживающему слияние (142). Выключенные и неразобранные не
опрашиваются вовсе.

Класс — свойство потребителя: у одного проекта `e2e` обязателен, у другого
невозможен. Поэтому список обязательных здесь не зашит, а приходит из данных
проекта.

Исходы (правило 039): ``0`` все зелёные · ``1`` есть незелёные или отсутствующие
· ``2`` опрос не отработал.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Final

import ghrest
import pipeline_checks as policy

PENDING: Final = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})

EXIT_GREEN: Final = 0
EXIT_RED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Опрос не отработал: третий исход, а не «зелено»."""


def check_runs(repo: str, sha: str) -> list[dict[str, Any]]:
    """Отдаёт записи проверок на голове.

    filter=latest — только последняя запись на каждое имя. Без него повторный
    прогон на той же голове оставляет прошлые записи, и проверка «больше одной
    живой записи» краснела бы на здоровом.
    """
    path = f"repos/{repo}/commits/{sha}/check-runs?filter=latest"
    return list(ghrest.paginate(path, ghrest.token_from_env(), key="check_runs"))


def belongs_to(run: dict[str, Any], run_id: str) -> bool:
    """Отвечает, выдана ли запись этим же прогоном."""
    url = str(run.get("details_url") or run.get("html_url") or "")
    return f"/actions/runs/{run_id}/" in url


def verdict(
    runs: list[dict[str, Any]],
    required: list[str],
    selfname: str,
    run_id: str = "",
    *,
    strict_missing: bool = True,
) -> tuple[list[str], bool]:
    """Выносит вердикт по объявленным именам; вторым отдаёт «ещё идут».

    ``strict_missing`` разводит два класса. У обязательной проверки отсутствие
    записи — отказ: пустой список означает «прогон не стартовал», а не «зелено»
    (075). У совещательной оно законно: она могла не идти на этой голове вовсе,
    и краснеть на этом значило бы сделать её обязательной обходным путём.
    """
    problems: list[str] = []
    waiting = False

    for name in required:
        if name == selfname:
            continue
        found = [run for run in runs if run.get("name") == name]
        # Записи СВОЕГО прогона имеют преимущество. На одной голове легко
        # оказываются два прогона одного файла — например, толчок и снятие
        # черновика, — и тогда каждое имя представлено дважды, обе записи
        # здоровые. Считать это неоднозначностью значит краснеть на штатном
        # событии: замер 09.09 — снятие черновика уронило сводный гейт при
        # восьми зелёных соседях.
        #
        # Для имени, которого в своём прогоне нет вовсе, смотрятся остальные
        # записи: обязательное имя может выдавать и другой механизм.
        if run_id:
            mine = [run for run in found if belongs_to(run, run_id)]
            found = mine or found
        if not found:
            if strict_missing:
                problems.append(
                    f"{name}: записи нет на голове — прогон не стартовал, а не «зелено»"
                )
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

        # Две живые записи одного имени ПОСЛЕ отбора по своему прогону —
        # настоящая неоднозначность: обязательное имя выдают два разных
        # механизма, и какой из них решает, неизвестно.
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


def sources(policy_path: str, required_raw: str) -> tuple[list[str], list[str]]:
    """Отдаёт обязательные и совещательные имена из ЕДИНСТВЕННОГО источника.

    Источник ровно один: либо ответ проекта по классам проверок, либо явный
    список именами. Два списка одного и того же расходятся молча (022), поэтому
    оба ключа разом — ошибка входа, а не «возьмём тот, что подробнее».
    """
    if policy_path and required_raw:
        raise NotRun(
            "наполнение объявлено дважды: --policy и --required. "
            "Источник обязан быть один, иначе списки разойдутся молча (022)"
        )
    if policy_path:
        try:
            checks = policy.load(Path(policy_path))
        except policy.BadPolicy as exc:
            raise NotRun(str(exc)) from exc
        return policy.names_of(checks, policy.REQUIRED), policy.names_of(checks, policy.ADVISORY)

    names = [name.strip() for name in required_raw.split(",") if name.strip()]
    return names, []


def main(argv: list[str] | None = None) -> int:
    """Точка входа: опрашивает голову до вердикта и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--policy", default="", help="ответ проекта по классам проверок")
    parser.add_argument("--required", default="", help="имена джобов через запятую")
    parser.add_argument("--self-name", default="ci-complete", help="собственное имя, себя не ждём")
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID", ""),
        help="свой прогон: его записи имеют преимущество перед чужими на той же голове",
    )
    parser.add_argument("--timeout", type=int, default=900, help="сколько ждать соседей, секунд")
    parser.add_argument("--interval", type=int, default=20, help="пауза между опросами, секунд")
    args = parser.parse_args(argv)

    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo or not args.sha:
            raise NotRun("не названы репозиторий или голова изменения")

        required, advisory = sources(args.policy, args.required)
        if not required:
            raise NotRun("список обязательных имён пуст — предмет опроса не найден (075)")

        deadline = time.monotonic() + args.timeout
        while True:
            runs = check_runs(args.repo, args.sha)
            if not runs:
                raise NotRun(
                    f"на голове {args.sha[:8]} нет ни одной записи проверок — "
                    "это ошибка входа, а не «зелено» (075)"
                )
            problems, waiting = verdict(runs, required, args.self_name, args.run_id)
            # Совещательные опрашиваются, но их не ЖДУТ: слияния они не держат,
            # и ожидание сделало бы их обязательными обходным путём.
            advisory_problems, _ = verdict(
                runs, advisory, args.self_name, args.run_id, strict_missing=False
            )
            if not waiting:
                break
            if time.monotonic() >= deadline:
                problems.append(f"соседи не завершились за {args.timeout} с — вердикта нет")
                break
            print(f"ждём соседей на голове {args.sha[:8]}…", flush=True)
            time.sleep(args.interval)
    except (NotRun, ghrest.TransportError) as exc:
        print(f"опрос не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if advisory_problems:
        print(f"совещательные ({len(advisory_problems)}) — слияния не держат, но не молчат:")
        for problem in advisory_problems:
            print(f"  {problem}")
        # Обход назван, а не обойдён молча (154): адресат у совещательного
        # красного обязателен, и механизм для него уже есть — review_findings.
        # Подключение — второй этап #27, до него запись живёт в этом выводе.
        print("  адресат, переживающий слияние, подключается вторым этапом #27")

    if problems:
        print(f"красно ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")
        return EXIT_RED

    print(f"зелено: все объявленные проверки на голове {args.sha[:8]} пройдены")
    return EXIT_GREEN


if __name__ == "__main__":
    raise SystemExit(main())
