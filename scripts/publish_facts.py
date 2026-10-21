#!/usr/bin/env python3
"""Публикация фактов коммитом поверх ветки `badges` — скриптом, а не оболочкой.

РЕШЕНИЕ ВЛАДЕЛЬЦА 08.10.2026 (#639). Запись жила в сценарии шага
`step-facts.yml`, и гейт «ветка держит файлы шага» узнавал публикуемое разбором
оболочки. Три захода взгляда подряд (#1217, #1223, #1227) находили новую форму
записи — `git -C`, `&&`, `/usr/bin/git`, `"$GIT"`, `sh -c`, `git commit -a`,
тело heredoc, — и по 210 круг рвёт не ещё одна форма, а смена подхода: что
публикуется, названо константой `PUBLISHES`, и гейт читает её импортом.

ПОВЕРХ, А НЕ ПЕРЕЗАПИСЬЮ (вариант 1 решения 06.10.2026). Кладётся только
`PUBLISHES`; свои значки и файлы потребителя на ветке живут. Толчок без
`--force`: отказ гонки — красное, а не перезапись чужого. Ветки ещё нет —
первая публикация начинает её сиротой; ветку, которую не удалось прочитать по
другой причине, затирать нельзя.

Исходы (правило 039): ``0`` опубликовано или публиковать нечего · ``2``
не опубликовано: ветка не прочитана, git отказал (любой шаг — с кодом и
`stderr`, через `reason`), фактов нет или сбой диска, подпись не записана. Все
отказы — `NotPublished`.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import gitcall
import paths

#: Что шаг кладёт на ветку `badges` — путь от корня ветки. Ветку держит этот
#: перечень: `build_facts.SHARED_STEP` обязан ему равняться, и это сверяет тест.
#: Значок проекта едет тем же коммитом, что факты, по которым он нарисован
#: (#1282, решение владельца 12.10.2026): число на значке и в файле витрины не
#: расходятся ни на одно мгновение.
PUBLISHES: Final = (
    (paths.BADGES_DIR / "facts.json").as_posix(),
    (paths.BADGES_DIR / "project.svg").as_posix(),
    (paths.BADGES_DIR / "family-check.json").as_posix(),
)
#: Значок проекта рисует действие каталога `project-badge` (#1422), и не
#: собрать его оно вправе: площадка не ответила о прогонах, сводка семьи не
#: прочитана. Тогда факты всё равно едут, а на ветке остаётся ПРЕЖНИЙ значок —
#: так решает каталог для своего исхода 2 («прежний значок лучше не трогать»).
PICTURE: Final = PUBLISHES[1]
#: Разбор семьи, который собирает то же действие рядом со значком: по нему
#: каталог считает `uptake` семьи (`РАЗБОР_АДРЕС` в `scripts/family.py`
#: каталога), и без него у всей семьи «не прочитано» (#1532). Едет и не едет
#: вместе со значком: один заход действия даёт оба.
FAMILY_CHECK: Final = PUBLISHES[2]
#: Что кладётся, только если лежит рядом с фактами, — выход действия каталога.
BESIDE: Final = (PICTURE, FAMILY_CHECK)
#: Архив находок взгляда: кладётся тем же коммитом, только если шаг позван с
#: входом `archive` (#1414). В `PUBLISHES` его нет намеренно: без входа шаг
#: его не трогает, и чужой файл с этим путём на ветке потребителя живёт.
ARCHIVE: Final = (paths.BADGES_DIR / "findings.json").as_posix()
#: Ветка публикации — производная, не общая.
BRANCH: Final = "badges"
#: `git ls-remote --exit-code` отвечает этим кодом, когда ветки нет вовсе.
NO_SUCH_BRANCH: Final = 2
#: Подпись коммита публикации: производное пишет прогон, а не человек.
BOT_NAME: Final = "github-actions[bot]"
BOT_EMAIL: Final = "41898282+github-actions[bot]@users.noreply.github.com"
EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


class NotPublished(Exception):
    """Публикация не состоялась: причина названа, ветка не тронута."""


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Вызов git с захватом вывода; код решает вызывающий, отсутствие git — отказ.

    Форма своя, а не `gitcall.output`: публикации нужен код выхода — «ветки
    нет» у `ls-remote` и «изменений нет» у `diff --quiet` — а не отказ на
    любом ненуле. `OSError` ловится здесь же (039, `tests/test_git_refuses.py`).
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            # Здесь и выборка, и толчок ветки `badges`: предел сетевой.
            timeout=gitcall.NETWORK,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotPublished(f"git не запустился: {exc}") from exc


def reason(done: subprocess.CompletedProcess[str]) -> str:
    """Причина отказа git: код и `stderr`, если git его сказал.

    ОДНА ФОРМА НА ВСЕ ШАГИ, а не своя у каждого (210). Причину чинили по шагу
    за заход — `add`, затем `diff`, затем `fetch` и `ls-remote` (взгляды на
    #1233 и #1249), — и каждый следующий взгляд находил соседа без неё.
    Тест сверяет, что отказ каждого вызова `git` в модуле несёт эту причину:
    вызов различается подкомандой и флагами, так что оба пути `worktree add`
    прогоняются порознь (взгляд на #1257).
    """
    said = done.stderr.strip()
    return f"код {done.returncode}: {said}" if said else f"код {done.returncode}"


def checkout(workdir: Path) -> None:
    """Рабочее дерево ветки `badges` в `workdir`: поверх неё или сиротой, если её нет."""
    fetched = git("fetch", "--quiet", "origin", BRANCH)
    if fetched.returncode == 0:
        added = git("worktree", "add", "--quiet", "--detach", str(workdir), "FETCH_HEAD")
    else:
        # ОТКАЗ `fetch` — НЕ ПРИГОВОР: ветки может не быть вовсе, и это решает
        # `ls-remote`. Но если ветка есть и не прочитана, причина `fetch` и
        # есть ответ «почему», и терять её нельзя (взгляд на #1249).
        remote = git("ls-remote", "--exit-code", "--heads", "origin", BRANCH)
        if remote.returncode != NO_SUCH_BRANCH:
            raise NotPublished(
                f"ветка {BRANCH} не прочитана (fetch {reason(fetched)}; "
                f"ls-remote {reason(remote)}) — публиковать поверх нечего, и затирать её нельзя"
            )
        added = git("worktree", "add", "--quiet", "--orphan", "-b", f"{BRANCH}-first", str(workdir))
    if added.returncode != 0:
        raise NotPublished(f"рабочее дерево ветки не создано: {reason(added)}")


def targets(source: Path, *, archive: bool) -> tuple[str, ...]:
    """Что кладётся на ветку этим заходом: факты всегда; значок, разбор семьи и архив — если рядом.

    Архив — только по входу `archive`. Чего рядом нет, то на ветке остаётся
    прежним: отсутствие называет `publish` предупреждением, а не молчит.
    """
    beside = source.parent
    said = [PUBLISHES[0]]
    said += [one for one in BESIDE if (beside / Path(one).name).is_file()]
    said += [ARCHIVE] if archive and (beside / Path(ARCHIVE).name).is_file() else []
    return tuple(said)


def publish(source: Path, workdir: Path, *, sha: str, archive: bool = False) -> bool:
    """Кладёт `source` и его соседей по `targets` и толкает; ``False`` — изменений нет.

    `source` — собранный `facts.json`, первая запись перечня; остальные файлы
    берутся РЯДОМ с ним по имени. Сам `source` по имени не ищется: иначе
    названный, но несуществующий файл подменил бы соседний `facts.json`
    молча. Нет фактов — отказ, а не публикация части (045).
    """
    # АРХИВА ИЛИ ЗНАЧКА НЕТ — ФАКТЫ ВСЁ РАВНО ЕДУТ (взгляды на #1423, #1422).
    # Первый заход без прежнего архива и с упавшим дописыванием архива не
    # оставляет; несобранный значок каталога — тоже: отказ всей публикации
    # из-за них оставил бы витрину со вчерашними фактами. Пропуск называется,
    # а краснеет на нём свой шаг.
    chosen = targets(source, archive=archive)
    for wanted in (*BESIDE, *([ARCHIVE] if archive else [])):
        if wanted not in chosen:
            print(f"::warning::рядом с фактами нет {Path(wanted).name} — на ветке остаётся прежний")
    checkout(workdir)
    # СБОЙ ДИСКА И ОТСУТСТВИЕ ФАКТОВ — ТОЖЕ «НЕ ОПУБЛИКОВАНО», а не трейсбек с
    # кодом 1: шапка обещает исходы 0 и 2 и `::error::` (039, взгляд на #1233).
    try:
        for target in chosen:
            (workdir / target).parent.mkdir(parents=True, exist_ok=True)
            given = source if target == PUBLISHES[0] else source.parent / Path(target).name
            shutil.copyfile(given, workdir / target)
    except OSError as exc:
        raise NotPublished(f"факты не положены в дерево ветки: {exc}") from exc
    # ПОДПИСЬ ПРОВЕРЯЕТСЯ: у оболочки `set -e` останавливал шаг на отказе
    # `git config`, а без проверки коммит ушёл бы под подписью окружения
    # (взгляд на #1233).
    for key, value in (("user.name", BOT_NAME), ("user.email", BOT_EMAIL)):
        signed = git("config", key, value, cwd=workdir)
        if signed.returncode != 0:
            raise NotPublished(f"подпись публикации не записана ({key}): {reason(signed)}")
    # КАЖДЫЙ ВЫЗОВ GIT ВЕДЁТ СВОЮ ПРИЧИНУ ОДНОЙ ФОРМОЙ — `reason`. `diff --quiet`
    # отвечает 0 «нечего» и 1 «есть»; иной код — отказ git, а не «есть изменения».
    added = git("add", "--", *chosen, cwd=workdir)
    if added.returncode != 0:
        raise NotPublished(f"git add отказал: {reason(added)}")
    staged = git("diff", "--cached", "--quiet", cwd=workdir)
    if staged.returncode == 0:
        return False
    if staged.returncode != 1:
        raise NotPublished(f"git diff не ответил, есть ли что публиковать: {reason(staged)}")
    for step in (
        ("commit", "-q", "-m", f"факты на {sha}"),
        # Ветка выбирается целиком, без --depth; БЕЗ --force: чужое не затирается.
        ("push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}"),
    ):
        done = git(*step, cwd=workdir)
        if done.returncode != 0:
            raise NotPublished(f"git {step[0]} отказал: {reason(done)}")
    return True


def main(argv: list[str] | None = None) -> int:
    """Точка входа: публикует собранный `facts.json` и значок рядом на ветку `badges`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="собранный facts.json")
    parser.add_argument("--workdir", type=Path, required=True, help="где поднять дерево ветки")
    parser.add_argument("--sha", required=True, help="голова, на которой собраны факты")
    parser.add_argument("--repo", required=True, help="имя проекта у площадки: владелец/репо")
    parser.add_argument(
        "--archive", action="store_true", help="положить и архив находок рядом с фактами"
    )
    args = parser.parse_args(argv)
    try:
        changed = publish(args.source, args.workdir, sha=args.sha, archive=args.archive)
    except NotPublished as exc:
        print(f"::error::факты не опубликованы: {exc}")
        return EXIT_BROKEN
    if not changed:
        print("факты не изменились — коммита нет")
        return EXIT_OK
    for target in targets(args.source, archive=args.archive):
        print(f"опубликовано: https://raw.githubusercontent.com/{args.repo}/{BRANCH}/{target}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
