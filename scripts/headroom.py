#!/usr/bin/env python3
"""Запас работ против их предела: медленнейший прогон ряда назван до отказа.

ЗАМЕР 26.10.2026, ИЗ-ЗА КОТОРОГО ЭТО ЕСТЬ (#1697). `main` покраснел на
`ceacf7c` (#1692): ячейка `test-matrix (3.14)` отменена пределом работы 10
минут на 99% набора — провала теста нет. Тем же утром та же ячейка шла 5:36,
а соседняя 3.15 на `ceacf7c` — 8:52. Набор растёт с каждым изменением, раннер
плавает почти вдвое, и о нехватке запаса узнали по красному `main`, то есть
поздно. Предел подняли до 15 минут — это починка, а сторож говорит, когда
запас снова на исходе.

СПЕРВА СПРОСИЛИ СЕМЬЮ (162). Каталог (`check_workflows.py`) и витрина
(`check_mechanisms.py`) проверяют, что предел у работы СТОИТ, а не сколько от
него занято на деле; сторожа запаса ни у кого нет — ни у каталога, ни у
витрины, ни у счётчика токенов. Строим своё, рядом с рядом прогонов: он уже
ходит за прогонами раз в сутки и раздаётся потребителю шагом.

ЧТО СУДИТСЯ. Работы из объявления (поле `jobs` ключа `headroom` в `.rules/series.json`),
их предел — `timeout-minutes` в прогоне (поле `workflow`), а длительность
— у площадки: последние `runs` завершённых заходов прогона на общей
ветке, по каждой ячейке матрицы. Медленнейшая ячейка дольше доли предела
(поле `share`) — находка с ячейкой, длительностью, пределом и долей.
Отменённая по пределу ячейка тоже в ряду: её длительность и есть предел.

ПРЕДЕЛ ЧИТАЕТСЯ ИЗ ПРОГОНА, А НЕ ВПИСЫВАЕТСЯ ВТОРЫМ ЧИСЛОМ: второе разошлось
бы с первым при следующем подъёме (022).

СОВЕЩАТЕЛЬНО. Сторож предела не поднимает и набор не ускоряет — называет:
красное за медленный раннер чинилось бы не правкой изменения (051). Ускорение
набора и раздел его на ячейки — решение владельца по сигналу сторожа (#1697).

ГРАНИЦЫ НАЗВАНЫ (046, 195): работы с пределом, которых нет в объявлении, не
судятся — у сетевых сверок предел ставится от зависания, а не от длины
набора; общий предел прогона без `timeout-minutes` у работы сторож не
выводит — площадка держит свои шесть часов, и это не запас, а его отсутствие,
о котором сказано строкой.

Исходы (правило 039): ``0`` запас есть · ``1`` запас мал · ``2`` не отработал
— объявление или прогон не читаются, площадка не ответила · ``3`` не судится —
ряд мал (завершённых заходов меньше объявленного) или сторож не объявлен вовсе.

НЕОБЪЯВЛЕННЫЙ СТОРОЖ — НЕ ОТКАЗ. Заготовка потребителя ключа не несёт: имена
его работ и их пределы знает он, а не мы, и угадывать их значило бы судить
чужой прогон своим (154). Без ключа сторож говорит, что не судит, и почему.
"""

import argparse
import json
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import ghrest
import onboard
import paths
import pipeline_checks as policy
import yaml

EXIT_OK: Final = 0
EXIT_LOW: Final = 1
EXIT_BROKEN: Final = 2
EXIT_UNJUDGED: Final = 3

#: Ключ объявления сторожа в `.rules/series.json`.
KEY: Final = "headroom"
#: Исходы работы, у которых длительность — замер: прошла, упала, отменена
#: (отмена по пределу и есть случай сторожа). Пропущенная не шла вовсе.
TIMED: Final = frozenset({"success", "failure", "cancelled", "timed_out"})
#: Заходов за один запрос площадки (`per_page`) — и потолок объявленного ряда.
RUNS_CAP: Final = 100
#: Заголовок раздела в отчёте ряда.
HEAD: Final = "## Запас работ против их предела"


class NotRun(RuntimeError):
    """Заход не отработал: второй исход, а не «запас есть»."""


@dataclass(frozen=True, slots=True)
class Watch:
    """Объявление сторожа: что судить и с каким порогом."""

    workflow: str
    jobs: tuple[str, ...]
    share: float
    runs: int

    @classmethod
    def read(cls, path: Path) -> Watch | None:
        """Читает объявление; ключа нет — `None` (не объявлен), битое — отказ (045)."""
        try:
            whole = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NotRun(f"{path} не прочитан: {exc}") from exc
        if not isinstance(whole, dict) or KEY not in whole:
            return None
        try:
            said = whole[KEY]
            watch = cls(
                workflow=str(said["workflow"]),
                jobs=tuple(str(one) for one in said["jobs"]),
                share=float(said["share"]),
                runs=int(said["runs"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NotRun(f"объявление сторожа «{KEY}» в {path} не прочитано: {exc}") from exc
        # БОЛЬШЕ СТРАНИЦЫ — НИКОГДА НЕ СУДИТСЯ (взгляд на #1700): площадка отдаёт
        # не больше `RUNS_CAP` заходов за запрос, `read < runs` было бы вечным, и
        # сторож молча отвечал бы «ряд мал». Предел назван отказом объявления.
        if not watch.jobs or not 0 < watch.share <= 1 or not 1 <= watch.runs <= RUNS_CAP:
            raise NotRun(
                f"объявление сторожа в {path} пусто или противоречиво: работ "
                f"{len(watch.jobs)}, доля {watch.share}, заходов {watch.runs} "
                f"(от 1 до {RUNS_CAP}, 075)"
            )
        return watch


def limits(workflow_text: str, jobs: tuple[str, ...]) -> dict[str, int]:
    """Предел в минутах у каждой объявленной работы — по её имени у площадки."""
    try:
        tree = yaml.safe_load(workflow_text) or {}
    except yaml.YAMLError as exc:
        raise NotRun(f"прогон не разобран: {exc}") from exc
    declared = tree.get("jobs") if isinstance(tree, dict) else None
    if not isinstance(declared, dict):
        raise NotRun("в прогоне нет раздела jobs")
    found: dict[str, int] = {}
    for key, job in declared.items():
        if not isinstance(job, dict):
            continue
        name = str(job.get("name") or key)
        if name not in jobs and key not in jobs:
            continue
        minutes = job.get("timeout-minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            raise NotRun(
                f"у работы «{name}» нет числового timeout-minutes — запас не от чего мерить"
            )
        found[name] = minutes
    missing = sorted(set(jobs) - set(found) - {str(key) for key in declared})
    if missing or not found:
        raise NotRun(f"объявленных работ нет в прогоне: {missing or list(jobs)}")
    return found


def shape_of(name: str) -> re.Pattern[str]:
    """Имя работы как образец записи площадки: выражение `${{ … }}` — любое значение.

    ИМЯ С ВЫРАЖЕНИЕМ ПЛОЩАДКА ПОДСТАВЛЯЕТ (взгляд на #1700): объявлено
    `test (${{ matrix.py }})`, а приходит `test (3.14)`, и сравнение строк не
    совпадало ни с одной записью — сторож навсегда отвечал «не судится», не
    назвав причины.
    """
    # Выражение узнаёт один образец — `onboard.EXPRESSION` (214).
    pattern, last = "", 0
    for found in onboard.EXPRESSION.finditer(name):
        pattern += re.escape(name[last : found.start()]) + ".+?"
        last = found.end()
    return re.compile(pattern + re.escape(name[last:]))


def owner_of(job_name: str, watched: dict[str, int]) -> str:
    """Какой объявленной работе принадлежит запись площадки; пусто — ничьей.

    Ячейка матрицы приходит как «имя (значение)»: `test-matrix (3.14)` — так
    площадка дописывает значения матрицы к имени без выражения.
    """
    for name in watched:
        if job_name == name or job_name.startswith(f"{name} ("):
            return name
        if onboard.EXPRESSION.search(name) and shape_of(name).fullmatch(job_name):
            return name
    return ""


def seconds_of(job: dict[str, Any]) -> int | None:
    """Длительность работы у площадки; `None` — не замер (не шла, время не сказано)."""
    if job.get("conclusion") not in TIMED:
        return None
    began, done = ghrest.moment(job.get("started_at")), ghrest.moment(job.get("completed_at"))
    if began is None or done is None:
        return None
    return max(0, int((done - began).total_seconds()))


def slowest(
    jobs_by_run: list[list[dict[str, Any]]], watched: dict[str, int]
) -> dict[str, tuple[str, int]]:
    """Медленнейшая ячейка каждой работы по ряду: работа → (ячейка, секунды)."""
    found: dict[str, tuple[str, int]] = {}
    for jobs in jobs_by_run:
        for job in jobs:
            name = str(job.get("name") or "")
            whose = owner_of(name, watched)
            spent = seconds_of(job)
            if not whose or spent is None:
                continue
            if whose not in found or spent > found[whose][1]:
                found[whose] = (name, spent)
    return found


def clock(seconds: int) -> str:
    """Секунды как «м:сс»."""
    return f"{seconds // 60}:{seconds % 60:02d}"


def verdict(
    watch: Watch, watched: dict[str, int], worst: dict[str, tuple[str, int]], read: int
) -> tuple[int, list[str]]:
    """Исход и строки отчёта; ряд короче объявленного — «судить не по чему»."""
    if read < watch.runs:
        return EXIT_UNJUDGED, [
            f"Ряд мал: завершённых заходов `{watch.workflow}` на общей ветке {read} "
            f"из {watch.runs} объявленных — запас не судится (039)."
        ]
    # ИСХОД — ПО СТАРШИНСТВУ, А НЕ ПО ЧИСЛУ: «запас мал» сильнее «не судится».
    # Числом 3 больше 1, и работа без замера глушила бы предупреждение о
    # соседней, у которой запас на исходе (взгляд на #1700).
    low_any = unjudged = False
    lines: list[str] = []
    for name, minutes in sorted(watched.items()):
        if name not in worst:
            unjudged = True
            lines.append(f"`{name}`: в {read} заходах ни одного замера — запас не судится.")
            continue
        cell, spent = worst[name]
        share = spent / (minutes * 60)
        low = share >= watch.share
        low_any = low_any or low
        mark = "⚠️ запас мал" if low else "запас есть"
        lines.append(
            f"{mark}: `{cell}` — медленнейший {clock(spent)} при пределе {minutes}:00 "
            f"({share:.0%}, порог {watch.share:.0%}, заходов {read})"
        )
    code = EXIT_LOW if low_any else EXIT_UNJUDGED if unjudged else EXIT_OK
    return code, lines


def jobs_of_runs(repo: str, token: str, watch: Watch) -> list[list[dict[str, Any]]]:
    """Работы последних завершённых заходов прогона на общей ветке."""
    path = (
        f"repos/{repo}/actions/workflows/{watch.workflow}/runs"
        f"?branch={paths.TRUNK}&event=push&status=completed&per_page={watch.runs}"
    )
    said = ghrest.request("GET", path, token) or {}
    runs = [one for one in said.get("workflow_runs") or [] if one.get("id")][: watch.runs]
    return [
        list(ghrest.paginate(f"repos/{repo}/actions/runs/{one['id']}/jobs", token, "jobs"))
        for one in runs
    ]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: судит запас и дописывает раздел в отчёт ряда."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="владелец/имя")
    parser.add_argument("--root", default=".", help="дерево, чьё объявление и прогон судятся")
    parser.add_argument("--report", default="", help="отчёт, в который дописать раздел")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        try:
            where = root / policy.project_path("series", root)
        except paths.BadPaths as exc:
            raise NotRun(f"объявление сторожа не найдено: {exc}") from exc
        watch = Watch.read(where)
        if watch is None:
            print(f"сторож запаса не объявлен (`{KEY}` в {where}) — запас не судится")
            return EXIT_UNJUDGED
        flow = root / paths.WORKFLOWS / watch.workflow
        try:
            text = flow.read_text(encoding="utf-8")
        except OSError as exc:
            raise NotRun(f"прогон {flow} не прочитан: {exc}") from exc
        watched = limits(text, watch.jobs)
        runs = jobs_of_runs(args.repo, ghrest.token_from_env(), watch)
    except NotRun as exc:
        print(f"сторож запаса не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except (ghrest.TransportError, ValueError) as exc:
        # ВСЁ, ЧТО НЕ ПОЙМАНО, ВЫШЛО БЫ КОДОМ 1 — «ЗАПАС МАЛ» (039). Разбор
        # ответа площадки роняет `ValueError`, и находка без замера была бы
        # ложной — поэтому он здесь, рядом с отказом транспорта.
        print(f"сторож запаса не отработал: площадка не ответила — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    code, lines = verdict(watch, watched, slowest(runs, watched), len(runs))
    print("\n".join(lines))
    if args.report:
        try:
            with Path(args.report).open("a", encoding="utf-8") as report:
                report.write("\n" + HEAD + "\n\n" + "".join(f"- {one}\n" for one in lines))
        except OSError as exc:
            print(
                f"сторож запаса не отработал: отчёт {args.report} не дописан — {exc}",
                file=sys.stderr,
            )
            return EXIT_BROKEN
    return code


def guarded(argv: list[str] | None = None) -> int:
    """`main` с исходом отказа на любое исключение: трасса — не «запас мал».

    КЛАСС, А НЕ ФОРМА (взгляд на #1700, 210). Непойманное исключение Python
    выходит кодом 1, а 1 у сторожа — «запас мал»: отказ выдавался за находку.
    Перечень ловимых (`TransportError`, `ValueError`) чинил форму и пропускал
    следующую — `AttributeError` пустого ответа, `KeyError` записи площадки.
    Здесь любое исключение после загрузки модуля — исход 2 с трассой (039).
    Граница: отказ ИМПОРТА (`yaml`) случается до этой функции и выходит кодом 1;
    его держит гейт установки шагов (`tests/test_steps_install_what_they_import.py`).
    """
    try:
        return main(argv)
    except Exception:
        traceback.print_exc()
        print("сторож запаса не отработал: исключение выше — не находка о запасе", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    sys.exit(guarded())
