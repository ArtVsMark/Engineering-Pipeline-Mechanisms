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
не опубликовано: ветка не прочитана, git отказал.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import paths

#: Что шаг кладёт на ветку `badges` — путь от корня ветки. Ветку держит этот
#: перечень: `build_facts.SHARED_STEP` обязан ему равняться, и это сверяет тест.
PUBLISHES: Final = ((paths.BADGES_DIR / "facts.json").as_posix(),)
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
            ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
        )
    except OSError as exc:
        raise NotPublished(f"git не запустился: {exc}") from exc


def checkout(workdir: Path) -> None:
    """Рабочее дерево ветки `badges` в `workdir`: поверх неё или сиротой, если её нет."""
    if git("fetch", "--quiet", "origin", BRANCH).returncode == 0:
        added = git("worktree", "add", "--quiet", "--detach", str(workdir), "FETCH_HEAD")
    else:
        remote = git("ls-remote", "--exit-code", "--heads", "origin", BRANCH).returncode
        if remote != NO_SUCH_BRANCH:
            raise NotPublished(
                f"ветка {BRANCH} не прочитана (ls-remote код {remote}) — "
                "публиковать поверх нечего, и затирать её нельзя"
            )
        added = git("worktree", "add", "--quiet", "--orphan", "-b", f"{BRANCH}-first", str(workdir))
    if added.returncode != 0:
        raise NotPublished(f"рабочее дерево ветки не создано: {added.stderr.strip()}")


def publish(source: Path, workdir: Path, *, sha: str) -> bool:
    """Кладёт `source` по каждому пути `PUBLISHES` и толкает; ``False`` — изменений нет."""
    checkout(workdir)
    # СБОЙ ДИСКА И ОТСУТСТВИЕ ФАКТОВ — ТОЖЕ «НЕ ОПУБЛИКОВАНО», а не трейсбек с
    # кодом 1: шапка обещает исходы 0 и 2 и `::error::` (039, взгляд на #1233).
    try:
        for target in PUBLISHES:
            (workdir / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, workdir / target)
    except OSError as exc:
        raise NotPublished(f"факты не положены в дерево ветки: {exc}") from exc
    # ПОДПИСЬ ПРОВЕРЯЕТСЯ: у оболочки `set -e` останавливал шаг на отказе
    # `git config`, а без проверки коммит ушёл бы под подписью окружения
    # (взгляд на #1233).
    for key, value in (("user.name", BOT_NAME), ("user.email", BOT_EMAIL)):
        signed = git("config", key, value, cwd=workdir)
        if signed.returncode != 0:
            raise NotPublished(f"подпись публикации не записана ({key}): {signed.stderr.strip()}")
    if git("add", "--", *PUBLISHES, cwd=workdir).returncode != 0:
        raise NotPublished("файлы фактов не добавлены в коммит")
    if git("diff", "--cached", "--quiet", cwd=workdir).returncode == 0:
        return False
    for step in (
        ("commit", "-q", "-m", f"факты на {sha}"),
        # Ветка выбирается целиком, без --depth; БЕЗ --force: чужое не затирается.
        ("push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}"),
    ):
        done = git(*step, cwd=workdir)
        if done.returncode != 0:
            raise NotPublished(f"git {step[0]} отказал: {done.stderr.strip()}")
    return True


def main(argv: list[str] | None = None) -> int:
    """Точка входа: публикует собранный `facts.json` на ветку `badges`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="собранный facts.json")
    parser.add_argument("--workdir", type=Path, required=True, help="где поднять дерево ветки")
    parser.add_argument("--sha", required=True, help="голова, на которой собраны факты")
    parser.add_argument("--repo", required=True, help="имя проекта у площадки: владелец/репо")
    args = parser.parse_args(argv)
    try:
        changed = publish(args.source, args.workdir, sha=args.sha)
    except NotPublished as exc:
        print(f"::error::факты не опубликованы: {exc}")
        return EXIT_BROKEN
    if not changed:
        print("факты не изменились — коммита нет")
        return EXIT_OK
    for target in PUBLISHES:
        print(f"опубликовано: https://raw.githubusercontent.com/{args.repo}/{BRANCH}/{target}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
