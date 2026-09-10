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


def pending(run: dict[str, Any]) -> bool:
    """Идёт ли проверка ещё — по ИСХОДУ, а не только по состоянию.

    Площадка выставляет исход, когда запись завершилась, но состояние у неё
    остаётся не всегда согласованным: погашенный группой отмены прогон
    оставляет на голове запись со `status: in_progress` и уже проставленным
    `conclusion`. Такая запись завершена — ждать её нечего, и ждали бы её
    вечно.

    Замер 09.09.2026: очередь встала на изменении #73 при девяти зелёных
    записях, потому что рядом лежала одна запись-зомби `pipeline` —
    `in_progress` с исходом `success`. Ни одного нового события у изменения
    больше не было, и сдвинуть её было нечем.

    Поэтому «идёт» означает: состояние переходное И исхода ещё нет.
    """
    return str(run.get("status")) in PENDING and run.get("conclusion") is None


def on_the_shared_branch(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставляет записи, которые на общей ветке вообще что-то значат.

    ПОЧЕМУ ПРОПУСК ЗДЕСЬ НЕ ОТКАЗ, ХОТЯ НА ГОЛОВЕ ИЗМЕНЕНИЯ — ОТКАЗ. Предмет у
    части проверок — изменение, а не общая ветка: разметка, фрагмент журнала и
    авторство коммитов на `main` проверять не на чем. Такие джобы объявлены
    change-only условием `if: github.event_name != 'push'` и на общей ветке
    кладут запись с исходом `skipped`. Считать её отказом — значит объявить
    общую ветку красной ВСЕГДА.

    Цена ошибки была ровно такой: замер 09.09.2026 — очередь на первом живом
    прогоне сообщила «общая ветка красна» по трём пропускам и не сдвинулась.
    Нашёл это прогон, а не набор — механизм подтверждается прогоном, а не чтением
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

    Послабление держится не обещанием: то, что change-only джобы объявлены
    условием, а не выключены руками, проверяет
    `tests/test_gates_contract.py::test_change_only_jobs_do_not_run_on_the_shared_branch`.
    Пропуск на голове ИЗМЕНЕНИЯ остаётся отказом (040) — здесь другая ветка и
    другой предмет.
    """
    return [run for run in runs if run.get("conclusion") != "skipped"]


def severity(run: dict[str, Any]) -> int:
    """Насколько плоха одна запись. Больше — хуже; отменённая ниже любой живой."""
    conclusion = run.get("conclusion")
    # «Идёт» решается общим разбором, а не своим: запись со `status:
    # in_progress` и уже проставленным исходом завершена, и ждать её вечно.
    if pending(run):
        return 1
    if conclusion == "cancelled":
        return -1
    if conclusion == "success":
        return 0
    if conclusion == "skipped":
        return 2
    return 3


def started(run: dict[str, Any]) -> str:
    """Когда запись началась. Пустое значение — самое старое из возможных."""
    return str(run.get("started_at") or "")


def worst_per_name(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставляет по одной, САМОЙ ПЛОХОЙ записи на имя.

    ПОЧЕМУ НЕ «НЕОДНОЗНАЧНОСТЬ». Сводный гейт, увидев две живые записи одного
    имени, объявляет вердикт неоднозначным — и правильно делает: он опрашивает
    голову изнутри своего же прогона и различает своё от чужого по номеру
    прогона. У очереди своего прогона среди них нет: она приходит снаружи и
    видит два прогона `ci` на одной голове — штатное следствие двух событий
    (толчок и навешенная метка), а не спор механизмов. Замер 09.09.2026: на
    первом живом заходе очередь отвергла изменение #57 с шестью зелёными
    именами, потому что каждое было представлено дважды.

    ПОЧЕМУ ХУДШАЯ, А НЕ ЛЮБАЯ. Взять первую попавшуюся значило бы иногда
    сливать красное: из двух записей одного имени зелёная попадалась бы
    первой. Худшая делает разбор строже сводного гейта, а не мягче, — и это
    единственная сторона, в которую здесь можно ошибаться
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

    Отменённая запись ниже любой живой: она пройденной не считается, но и
    отказом становится только тогда, когда живой у имени нет вовсе.
    """
    best: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = str(run.get("name", ""))
        current = best.get(name)
        if current is None:
            best[name] = run
            continue
        # ЖИВАЯ ЗАПИСЬ ВЫШЕ ОТМЕНЁННОЙ, И ЭТО ПЕРВЫЙ КЛЮЧ. Отмена — штатное
        # следствие группы отмены: новый толчок гасит прогон на той же голове,
        # и его записи остаются лежать рядом с живыми. Вердикта в них нет
        # никакого, поэтому свежесть между ними не решает: отменённая запись
        # 07:51 не отменяет зелёной 07:50. Замер 10.09.2026 — изменение #109 при
        # семи прогонах подряд получило «все записи отменены» и метку источника
        # 2, имея зелёный вердикт того же имени.
        #
        # Если ЖИВОЙ записи у имени нет вовсе, отмена доезжает до вердикта: она
        # пройденной не считается, и молчаливое «зелено» здесь было бы ложью.
        #
        # СВЕЖЕСТЬ РЕШАЕТ ВТОРОЙ, ТЯЖЕСТЬ — ТРЕТЬЕЙ. Записи одного имени бывают
        # не только от одновременных прогонов, но и от ПОСЛЕДОВАТЕЛЬНЫХ: новый
        # толчок гасит прежний прогон, и его записи остаются лежать на голове
        # рядом с живыми. Прежняя редакция брала худшую из всех — и красная
        # запись вытесненного прогона делала голову красной НАВСЕГДА: новых
        # событий у изменения больше нет, а зелёное живого прогона проигрывало
        # мёртвому. Замер 10.09.2026: #102, агрегат `test` — `failure` в 06:27:23
        # у погашенного прогона и `success` в 06:27:57 у живого.
        #
        # Тяжесть остаётся вторым ключом, и это по-прежнему нужно: у записей,
        # начатых В ОДНУ секунду (два прогона одного файла от двух событий),
        # ошибаться можно только в сторону строгости (051).
        alive = (run.get("conclusion") != "cancelled", started(run), severity(run))
        stands = (
            current.get("conclusion") != "cancelled",
            started(current),
            severity(current),
        )
        if alive > stands:
            best[name] = run
    return list(best.values())


def own_jobs(repo: str, run_id: str, token: str) -> dict[str, str]:
    """Джобы СВОЕГО прогона: имя → состояние. Пусто — спросить не у кого.

    Нужны они ради одного различия, которое иначе не сделать. Джоб, ждущий
    зависимости (`needs`), записи проверки на голове ещё не имеет — он не
    стартовал. Снаружи это выглядит точно так же, как «прогон не стартовал
    вовсе», а значит совсем другое: первый обязательно стартует, второго не
    будет никогда. Прежде оба читались как отказ, и сводный гейт краснел на
    здоровом прогоне.

    ЗАМЕР 10.09.2026: агрегат `test` ждёт матрицу версий, а сводный гейт
    опрашивает голову раньше и объявляет «прогон не стартовал». Изменение #102
    при полностью зелёных проверках получило красный обязательный контекст.
    """
    if not repo or not run_id:
        return {}
    try:
        payload = ghrest.request("GET", f"repos/{repo}/actions/runs/{run_id}/jobs", token) or {}
    except ghrest.TransportError:
        # Не спросили — значит различить нечем, и молчаливой поблажки быть не
        # должно: разбор вернётся к прежней строгости (045).
        return {}
    return {
        str(job.get("name", "")): str(job.get("status", ""))
        for job in payload.get("jobs", [])
        if isinstance(job, dict)
    }


def verdict(
    runs: list[dict[str, Any]],
    required: list[str],
    selfname: str,
    run_id: str = "",
    *,
    strict_missing: bool = True,
    mine: dict[str, str] | None = None,
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
            ours = [run for run in found if belongs_to(run, run_id)]
            found = ours or found
        if not found:
            # Джоб, который ЕЩЁ не стартовал, — это ожидание, а не отказ. Его
            # отличает наличие среди джобов своего прогона в незавершённом
            # состоянии: он объявлен, поставлен в очередь и обязательно
            # доедет. Без этого различия гейт краснел бы на всяком джобе с
            # `needs` — то есть на здоровом прогоне.
            queued = (mine or {}).get(name, "")
            if queued and queued != "completed":
                waiting = True
                continue
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
            if pending(run):
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
            mine = own_jobs(args.repo, args.run_id, token)
            problems, waiting = verdict(runs, required, args.self_name, args.run_id, mine=mine)
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
