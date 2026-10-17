#!/usr/bin/env python3
"""Гейт: сверка фактов с выпуском договора семьи проверена до слияния, а не после.

ЗАЧЕМ ОН, ЕСЛИ ШАГ УЖЕ СВЕРЯЕТ. Шаг «сверить факты с договором семьи» в
`step-facts.yml` скачивает `check_facts.py`, схему и номер договора с выпуска
каталога по тегу, сверяет их с прибитыми sha256 и исполняет проверку. Набор
гоняет этот шаг только на подделках `curl` и `python` (тестам сеть нельзя), и
настоящая проверка до слияния не исполнялась ни разу. Отсюда три находки
позднего взгляда на #1348 (#1380):

- неверное допущение о файлах выпуска или о строке «<repo>: расхождений N»
  сделало бы сверку мёртвой навсегда: каждый прогон кончался бы
  предупреждением «проверка не отработала», и ничего не краснело бы
  (`8dbfe69`, `dcf0b3f`);
- поднятый тег с устаревшим хешем заметили бы только на `main`, когда
  остановится публикация фактов (`eb04a3c`).

ЧТО ДЕЛАЕТ. Исполняет НАСТОЯЩИЙ шаг из `step-facts.yml`, без копии его текста,
дважды на фактах, собранных тем же `facts_common.py`, что у шага:

1. на годных фактах шаг обязан пройти молча — код 0, без `::error::` и без
   предупреждения о несверке;
2. на тех же фактах под чужим именем проекта проверка договора находит ровно
   одно расхождение («repo … а файл лежит у …»), и шаг обязан остановиться
   кодом 1 со строкой «<имя>: расхождений N».

Хеш не того файла останавливает уже первый заход. Предмет в дереве один: шаг
сверки в `step-facts.yml` — других мест, где прогон исполняет чужой выпуск по
хешу, нет (замер 15.10.2026: `grep -rn 'sha256sum --check' .github/`).

ЗОВЁТСЯ ТОЛЬКО ПО ПРЕДМЕТУ. С `--base` гейт сначала спрашивает дифф и идёт,
только если тронут его предмет (`subject`): иначе сеть оплачивалась бы на
каждом изменении. Без `--base` — идёт всегда (ручной прогон). Предмет
вычисляется по дереву, а не перечнем (взгляд на #1391): шаг, сам гейт со
своими модулями (`ghrest`, `gitcall` — разбор 404 у пробы), прогон, который
его зовёт, вызывающий шага (его `with:` — аргументы сборки) и
`facts_common.py` со всеми своими модулями, от которых зависит `facts.json`.

ФАКТЫ — С ТЕМИ ЖЕ АРГУМЕНТАМИ, ЧТО У ПУБЛИКАЦИИ: файл CI и матрицы берутся из
`with:` единственного вызывающего шага. Чего гейт не повторяет — артефакта
входов (`--extra`, `--coverage`): его кладёт соседний джоб прогона, и такие
показатели на заходе гейта уходят причинами в none (195).

Исходы: ``0`` сверка жива (или предмет не тронут) · ``1`` сверка мертва или
хеш не тот · ``2`` не отработал · ``4`` выпуск договора недоступен — отказ
канала, а не находка о дереве (084). Исход 4 не «чисто»: прогон называет его
предупреждением, а не молчит (045), но и красным не делает — дерево цело.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import facts_common
import ghrest
import gitcall
import paths
import pipeline_checks
import report

EXIT_OK: Final = 0
#: Код шага, не уложившегося в дедлайн, — тот же, что отдаёт `timeout(1)`.
STEP_TIMED_OUT: Final = 124
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2
EXIT_SILENT: Final = 4

FLOW: Final = paths.FACTS_STEP
#: Сборка фактов: её модули и сама она — предмет гейта. Имя модуля, а не путь:
#: где он лежит, знает якорь источников (`paths.SOURCES`).
BUILD: Final = facts_common.__name__
#: Сам гейт: правка его разбора меняет то, что он считает живой сверкой.
GATE: Final = Path(__file__).stem
#: Входы шага, которые вызывающий отдаёт сборке фактов, и их ключи у сборки.
BUILD_INPUTS: Final = {
    "ci-workflow": "--ci-workflow",
    "python-matrix": "--python-matrix",
    "python-next": "--python-next",
}
#: Признак шага сверки: он один исполняет проверку договора.
MARK: Final = "check_facts.py"
#: Чужое имя для второго захода: проверка договора находит у фактов чужой `repo`.
STRANGER: Final = "facts-contract/stranger"
#: Предупреждение шага, когда выпуск не скачан: канал — или адрес не тот.
UNFETCHED: Final = "не скачан"
#: Имя файла из предупреждения шага «<файл> выпуска <тег> не скачан».
UNFETCHED_FILE: Final = re.compile(r"(\S+) выпуска \S+ не скачан")
#: Файл выпуска, если предупреждение его не назвало.
PROBED: Final = "check_facts.py"


class NotRun(RuntimeError):
    """Гейт не отработал: предмета нет или вход не прочитан (075)."""


def contract_step(flow: dict[Any, Any]) -> dict[str, Any]:
    """Шаг сверки из разобранного `step-facts.yml`; нет его — отказ, а не «чисто»."""
    jobs = flow.get("jobs")
    found = [
        one
        for job in (jobs or {}).values()
        if isinstance(job, dict)
        for one in job.get("steps") or []
        if isinstance(one, dict) and MARK in str(one.get("run") or "")
    ]
    if len(found) != 1:
        raise NotRun(f"шагов сверки с {MARK} в {FLOW}: {len(found)}, ждали один (075)")
    return found[0]


def source_of(name: str, root: Path) -> Path | None:
    """Где лежит наш модуль `name` — по якорю источников; чужой — `None`."""
    for where in paths.SOURCES:
        candidate = where / f"{name.split('.')[0]}.py"
        if (root / candidate).is_file():
            return candidate
    return None


def module_closure(start: str, root: Path) -> set[Path]:
    """Модуль и все наши модули, которые он импортирует, — по дереву, а не перечнем."""
    found: set[Path] = set()
    todo = [start]
    while todo:
        path = source_of(todo.pop(), root)
        if path is None or path in found:
            continue
        found.add(path)
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        todo += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        todo += [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
    return found


def flows(root: Path) -> list[tuple[Path, dict[Any, Any]]]:
    """Прогоны дерева, разобранные общим разбором."""
    folder = root / paths.WORKFLOWS
    if not folder.is_dir():
        return []
    return [
        (paths.WORKFLOWS / one.name, pipeline_checks.run_of(one))
        for one in sorted(folder.glob("*.yml"))
    ]


def jobs_of(document: dict[Any, Any]) -> list[dict[str, Any]]:
    """Джобы прогона, которые словари."""
    return [job for job in (document.get("jobs") or {}).values() if isinstance(job, dict)]


def callers(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Вызовы шага фактов: файл прогона и его `with:`."""
    return [
        (path, dict(job.get("with") or {}))
        for path, document in flows(root)
        for job in jobs_of(document)
        if str(job.get("uses") or "").split("@")[0].endswith(FLOW.name)
    ]


def gate_runs(root: Path) -> set[Path]:
    """Прогоны, чей шаг зовёт этот гейт."""
    return {
        path
        for path, document in flows(root)
        for job in jobs_of(document)
        for step in job.get("steps") or []
        if isinstance(step, dict) and f"{GATE}.py" in str(step.get("run") or "")
    }


def subject(root: Path) -> set[str]:
    """Пути, правка которых меняет то, что сверка видит или как гейт её судит."""
    found = {FLOW} | module_closure(BUILD, root) | gate_runs(root)
    found |= module_closure(GATE, root)
    found |= {path for path, _ in callers(root)}
    return {path.as_posix() for path in found}


def touched(base: str, root: Path) -> bool:
    """Тронут ли предмет сверки изменением против `base`."""
    names = gitcall.output(["diff", "--name-only", "-z", f"{base}...HEAD"], NotRun, cwd=str(root))
    mine = subject(root)
    return any(name in mine for name in names.split("\0"))


def build_args(root: Path) -> list[str]:
    """Аргументы сборки фактов из `with:` единственного вызывающего шага (взгляд на #1391)."""
    found = callers(root)
    if len(found) != 1:
        raise NotRun(f"вызовов {FLOW.name} в прогонах: {len(found)}, ждали один (075)")
    given = found[0][1]
    defaults = (
        (pipeline_checks.run_of(root / FLOW).get("on") or {}).get("workflow_call") or {}
    ).get("inputs") or {}
    args: list[str] = []
    for name, key in BUILD_INPUTS.items():
        value = given.get(name, (defaults.get(name) or {}).get("default", ""))
        args += [key, str(value)]
    return args


def run_step(step: dict[str, Any], temp: Path, repo: str) -> tuple[int, str]:
    """Исполняет шаг как площадка: `bash`, его `env`, `RUNNER_TEMP` и имя проекта."""
    env = {**os.environ, **{k: str(v) for k, v in (step.get("env") or {}).items()}}
    env.update({"RUNNER_TEMP": str(temp), "GITHUB_REPOSITORY": repo})
    try:
        done = subprocess.run(
            ["bash", "-c", str(step["run"])],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=gitcall.NETWORK,
        )
    except OSError as exc:
        # Шаг не запустился — гейт не отработал (2), а не «не уложился»: ко
        # времени это отношения не имеет (находка `673fef5`).
        raise NotRun(f"шаг не запустился: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        # Шаг ходит к площадке за выпуском: сетевой предел, а истёкший — свой
        # код, как у `timeout(1)`, и причина, а не трасса (039). Судит его
        # `verdict` молчанием канала, а не мёртвой сверкой.
        return STEP_TIMED_OUT, f"шаг {gitcall.cause(exc)}"
    return done.returncode, done.stdout + done.stderr


def release_missing(step: dict[str, Any], named: str = PROBED) -> bool:
    """Отвечает ли площадка «нет такого» на файл выпуска под прибитым тегом.

    НЕ СКАЧАН — ЕЩЁ НЕ «КАНАЛ МОЛЧИТ» (откат при сборке гейта, #1380). Опечатка
    в теге давала у шага то же «не скачан», что и упавшая сеть, и гейт называл
    её отказом канала: поднятый на несуществующий тег договор прошёл бы с
    одним предупреждением. Ответ 404 на адрес выпуска — находка о дереве;
    любой другой отказ — молчание канала.

    Спрашивается тот файл, который назвало предупреждение шага (`named`), а не
    любой из выпуска: тег есть, а переименован один файл — 404 только у него
    (взгляд на #1391).
    """
    env = step.get("env") or {}
    url = f"{env.get('RELEASES')}/{env.get('FACTS_CONTRACT')}/{named}"
    try:
        ghrest.raw_text(url)
    except ghrest.TransportError as exc:
        cause = exc.__cause__
        return isinstance(cause, urllib.error.HTTPError) and cause.code == 404
    return False


def unfetched(said: str) -> str | None:
    """Файл выпуска, который шаг не скачал, — по его предупреждению; скачал всё — `None`."""
    if UNFETCHED not in said:
        return None
    named = UNFETCHED_FILE.search(said)
    return named.group(1) if named else PROBED


def verdict(
    good: tuple[int, str],
    stranger: tuple[int, str],
    missing: Callable[[str], bool] = lambda named: False,
) -> tuple[int, str]:
    """Исход гейта по двум заходам шага: годному и под чужим именем.

    ОТКАЗ КАНАЛА СУДИТСЯ ПО ОБОИМ ЗАХОДАМ, И КАЖДЫЙ — В СВОЙ ЧЕРЁД (взгляды на
    #1391 и #1395, правило 210). Прежде «не скачан» проверялся только у первого
    захода: отказ сети на втором читался как «расхождение не остановило шаг».
    Но и судить канал обоих заходов раньше всего нельзя: годный, скачавший
    выпуск и показавший мёртвую сверку, — окончательный ответ, и мигнувшая на
    втором заходе сеть его не отменяет. Порядок:

    1. годный заход не уложился в сетевой дедлайн — молчание канала (4); не
       скачал выпуск — канал: «нет такого» у названного файла (`missing`) —
       находка о теге (1), иначе молчание канала (4);
    2. годный заход остановлен или сказал о несверке — сверка мертва (1);
    3. чужой заход не уложился или не скачал выпуск — канал, как в п. 1;
    4. чужой заход не остановлен своей строкой — сверка мертва (1);
    5. иначе — сверка жива (0).

    ИСТЁКШИЙ ДЕДЛАЙН — КАНАЛ, А НЕ МЁРТВАЯ СВЕРКА (находка `c91b22a`). Прежде
    код `STEP_TIMED_OUT` шёл в п. 2 как любой ненулевой, и зависшая сеть
    читалась находкой о дереве. Предел назван: код 124 от самого шага
    (`timeout(1)` внутри него) судится так же — это тоже истёкший дедлайн.
    """

    def channel(rc: int, said: str) -> tuple[int, str] | None:
        """Исход канала у захода: истёк дедлайн — 4, не скачал выпуск — 1 или 4; иначе `None`."""
        if rc == STEP_TIMED_OUT:
            return EXIT_SILENT, f"{report.tail(said)} — канал молчит, сверка не проверена"
        named = unfetched(said)
        if named is None:
            return None
        if missing(named):
            return EXIT_FOUND, f"выпуска «{named}» под прибитым тегом нет — тег или имя файла не те"
        return EXIT_SILENT, f"«{named}» выпуска договора не скачан — сверка не проверена"

    rc, said = good
    if (judged := channel(rc, said)) is not None:
        return judged
    if rc != 0 or "::error::" in said:
        return EXIT_FOUND, f"годные факты остановлены (код {rc}): {report.tail(said)}"
    if "::warning::" in said:
        return EXIT_FOUND, f"сверка не отработала на годных фактах — мертва: {report.tail(said)}"
    rc, said = stranger
    if (judged := channel(rc, said)) is not None:
        return judged
    line = f"{STRANGER}: расхождений "
    if rc != 1 or line not in said:
        return EXIT_FOUND, (
            f"расхождение не остановило шаг (код {rc}, строки «{line}N» "
            f"{'нет' if line not in said else 'есть'}) — сверка мертва: {report.tail(said)}"
        )
    return EXIT_OK, "сверка жива: годные факты прошли, расхождение остановило шаг"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: исполняет шаг сверки дважды и судит, жива ли она."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--base", default="", help="база изменения; пусто — идти всегда")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="имя проекта у площадки: владелец/репо",
    )
    args = parser.parse_args(argv)
    try:
        if args.base and not touched(args.base, args.root):
            print(f"предмет не тронут ({', '.join(sorted(subject(args.root)))}) — сверять нечего")
            return EXIT_OK
        if not args.repo:
            raise NotRun("не названо имя проекта (--repo или GITHUB_REPOSITORY)")
        step = contract_step(pipeline_checks.run_of(args.root / FLOW))
        sha = gitcall.output(["rev-parse", "HEAD"], NotRun, cwd=str(args.root)).strip()
        with tempfile.TemporaryDirectory() as raw:
            temp = Path(raw)
            built = facts_common.main(
                [
                    "--root",
                    str(args.root),
                    "--out",
                    str(temp / "facts" / "facts.json"),
                    "--sha",
                    sha,
                    "--repo",
                    args.repo,
                    "--supplier",
                    args.repo,
                    *build_args(args.root),
                ]
            )
            if built != facts_common.EXIT_OK:
                raise NotRun("факты не собраны — сверять нечего")
            json.loads((temp / "facts" / "facts.json").read_text(encoding="utf-8"))
            good = run_step(step, temp, args.repo)
            stranger = run_step(step, temp, STRANGER)
    except (NotRun, pipeline_checks.BadPolicy, OSError, ValueError) as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    code, said = verdict(good, stranger, lambda named: release_missing(step, named))
    print(said)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
