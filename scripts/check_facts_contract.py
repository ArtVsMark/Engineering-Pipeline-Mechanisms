#!/usr/bin/env python3
"""Гейт: сверка фактов с выпуском витрины проверена до слияния, а не после.

ЗАЧЕМ ОН, ЕСЛИ ШАГ УЖЕ СВЕРЯЕТ. Шаг «сверить факты с договором витрины» в
`step-facts.yml` скачивает `check_facts.py`, схему и номер договора с выпуска
витрины по тегу, сверяет их с прибитыми sha256 и исполняет проверку. Набор
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
2. на тех же фактах под чужим именем проекта проверка витрины находит ровно
   одно расхождение («repo … а файл лежит у …»), и шаг обязан остановиться
   кодом 1 со строкой «<имя>: расхождений N».

Хеш не того файла останавливает уже первый заход. Предмет в дереве один: шаг
сверки в `step-facts.yml` — других мест, где прогон исполняет чужой выпуск по
хешу, нет (замер 15.10.2026: `grep -rn 'sha256sum --check' .github/`).

ЗОВЁТСЯ ТОЛЬКО ПО ПРЕДМЕТУ. С `--base` гейт сначала спрашивает дифф и идёт,
только если тронут шаг или сборка фактов (`SUBJECT`): иначе сеть оплачивалась
бы на каждом изменении. Без `--base` — идёт всегда (ручной прогон).

Исходы: ``0`` сверка жива (или предмет не тронут) · ``1`` сверка мертва или
хеш не тот · ``2`` не отработал · ``4`` выпуск витрины недоступен — отказ
канала, а не находка о дереве (084), и зелёным он не считается (045).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final

import facts_common
import gitcall
import yaml

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2
EXIT_SILENT: Final = 4

FLOW: Final = Path(".github/workflows/step-facts.yml")
#: Пути, правка которых меняет то, что сверка видит: сам шаг (тег, хеши, разбор
#: вердикта) и сборка фактов, которые он сверяет.
SUBJECT: Final = (FLOW.as_posix(), "scripts/facts_common.py")
#: Признак шага сверки: он один исполняет проверку витрины.
MARK: Final = "check_facts.py"
#: Чужое имя для второго захода: проверка витрины находит у фактов чужой `repo`.
STRANGER: Final = "facts-contract/stranger"
#: Предупреждение шага, когда выпуск не скачан: канал — или адрес не тот.
UNFETCHED: Final = "не скачан"
#: Файл выпуска, по которому спрашивают, есть ли тег: первый из скачиваемых.
PROBED: Final = "facts.version"


class NotRun(RuntimeError):
    """Гейт не отработал: предмета нет или вход не прочитан (075)."""


def contract_step(flow: str) -> dict[str, Any]:
    """Шаг сверки из текста `step-facts.yml`; нет его — отказ, а не «чисто»."""
    parsed = yaml.safe_load(flow)
    jobs = parsed.get("jobs") if isinstance(parsed, dict) else None
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


def touched(base: str, root: Path) -> bool:
    """Тронут ли предмет сверки изменением против `base`."""
    names = gitcall.output(["diff", "--name-only", f"{base}...HEAD"], NotRun, cwd=str(root))
    return any(name in SUBJECT for name in names.splitlines())


def run_step(step: dict[str, Any], temp: Path, repo: str) -> tuple[int, str]:
    """Исполняет шаг как площадка: `bash`, его `env`, `RUNNER_TEMP` и имя проекта."""
    env = {**os.environ, **{k: str(v) for k, v in (step.get("env") or {}).items()}}
    env.update({"RUNNER_TEMP": str(temp), "GITHUB_REPOSITORY": repo})
    done = subprocess.run(
        ["bash", "-c", str(step["run"])],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def release_missing(step: dict[str, Any]) -> bool:
    """Отвечает ли площадка «нет такого» на файл выпуска под прибитым тегом.

    НЕ СКАЧАН — ЕЩЁ НЕ «КАНАЛ МОЛЧИТ» (откат при сборке гейта, #1380). Опечатка
    в теге давала у шага то же «не скачан», что и упавшая сеть, и гейт называл
    её отказом канала: поднятый на несуществующий тег договор прошёл бы с
    одним предупреждением. Ответ 404 на адрес выпуска — находка о дереве;
    любой другой отказ — молчание канала.
    """
    env = step.get("env") or {}
    url = f"{env.get('RELEASES')}/{env.get('FACTS_CONTRACT')}/{PROBED}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30):
            return False
    except urllib.error.HTTPError as exc:
        return exc.code == 404
    except urllib.error.URLError, OSError:
        return False


def verdict(
    good: tuple[int, str], stranger: tuple[int, str], missing: bool = False
) -> tuple[int, str]:
    """Исход гейта по двум заходам шага: годному и под чужим именем.

    `missing` — площадка ответила «нет такого» на файл выпуска (`release_missing`).
    """
    rc, said = good
    if UNFETCHED in said:
        if missing:
            return EXIT_FOUND, "выпуска под прибитым тегом нет — тег или имя файла не те"
        return EXIT_SILENT, "выпуск витрины не скачан — сверка не проверена"
    if rc != 0 or "::error::" in said:
        return EXIT_FOUND, f"годные факты остановлены (код {rc}): {said.strip()[-300:]}"
    if "::warning::" in said:
        return EXIT_FOUND, f"сверка не отработала на годных фактах — мертва: {said.strip()[-300:]}"
    rc, said = stranger
    line = f"{STRANGER}: расхождений "
    if rc != 1 or line not in said:
        return EXIT_FOUND, (
            f"расхождение не остановило шаг (код {rc}, строки «{line}N» "
            f"{'нет' if line not in said else 'есть'}) — сверка мертва: {said.strip()[-300:]}"
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
            print(f"предмет не тронут ({', '.join(SUBJECT)}) — сверять нечего")
            return EXIT_OK
        if not args.repo:
            raise NotRun("не названо имя проекта (--repo или GITHUB_REPOSITORY)")
        step = contract_step((args.root / FLOW).read_text(encoding="utf-8"))
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
                ]
            )
            if built != facts_common.EXIT_OK:
                raise NotRun("факты не собраны — сверять нечего")
            json.loads((temp / "facts" / "facts.json").read_text(encoding="utf-8"))
            good = run_step(step, temp, args.repo)
            stranger = run_step(step, temp, STRANGER)
    except (NotRun, OSError, ValueError) as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    missing = UNFETCHED in good[1] and release_missing(step)
    code, said = verdict(good, stranger, missing)
    print(said)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
