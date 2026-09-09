#!/usr/bin/env python3
"""Открывает изменение от лица владельца по ветке агентского окна.

Правило 131: операция, несущая личность человека, из агентского окна не
выполняется — на записи прокси подменяет учётные данные, и автором в общей
ветке становится приложение. Такая операция уходит в конвейер, и этот скрипт
и есть тот конвейер.

Решает **учётная запись, открывшая изменение**, а не подпись коммитов ветки:
после уплотнения авторство итогового коммита уже не поправить (123). Поэтому
токен здесь — владельца, а не прогона; на `GITHUB_TOKEN` скрипт молча не
переходит, иначе он делал бы ровно ту подмену, ради которой заведён.

Имя ветки — переключатель поведения (003): изменение открывается только для
объявленных приставок. Приставок две, и вторая не для красоты: в облачном окне
имя ветки назначает платформа, окно его не выбирает.

Идемпотентность обязательна: повторный толчок в ту же ветку не должен открывать
второе изменение — у соседнего проекта это уже случалось.

Исходы (правило 039): ``0`` открыто или уже есть · ``1`` не настроено ·
``2`` не отработало.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import urllib.parse
from typing import Final

import ghrest
import labels

PREFIXES: Final = ("agent/", "claude/")
TASK_RE: Final = re.compile(r"^(?:Closes|Fixes|Refs) #\d+$", re.MULTILINE)

EXIT_OK: Final = 0
EXIT_NOT_CONFIGURED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «открыто»."""


def git(*args: str) -> str:
    """Зовёт git, обращая отказ в третий исход."""
    try:
        return subprocess.run(["git", *args], capture_output=True, check=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise NotRun(f"git {' '.join(args)} → {str(detail).strip()[:300]}") from exc


def changed_files(branch: str, base: str) -> list[str]:
    """Файлы, тронутые веткой относительно базы."""
    merge_base = git("merge-base", f"origin/{base}", branch).strip()
    out = git("diff", "--name-only", f"{merge_base}...{branch}")
    return [line.strip() for line in out.splitlines() if line.strip()]


def describe(branch: str, base: str) -> tuple[str, str]:
    """Собирает заголовок и тело изменения из коммитов ветки."""
    merge_base = git("merge-base", f"origin/{base}", branch).strip()
    log = git("log", "--reverse", "--format=%s", f"{merge_base}..{branch}")
    subjects = [line for line in log.splitlines() if line]
    if not subjects:
        raise NotRun(f"в ветке {branch} нет коммитов сверх {base} — открывать нечего (075)")

    title = subjects[0] if len(subjects) == 1 else f"{subjects[0]} (+{len(subjects) - 1})"
    bodies = git("log", "--reverse", "--format=%B%n---", f"{merge_base}..{branch}")

    tasks = sorted(set(TASK_RE.findall(bodies)))
    lines = ["## Что в изменении", ""]
    lines += [f"- {subject}" for subject in subjects]
    if tasks:
        lines += ["", "## Связь с задачами", ""] + [f"{task}" for task in tasks]
    lines += [
        "",
        "---",
        "",
        "Изменение открыто конвейером от лица владельца: операция, несущая",
        "личность человека, из агентского окна не выполняется (правило 131).",
    ]
    return title, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--base", default="main")
    parser.add_argument("--dry-run", action="store_true", help="показать, но не открывать")
    args = parser.parse_args(argv)

    try:
        if not args.repo or not args.branch:
            raise NotRun("не названы репозиторий или ветка")

        if not args.branch.startswith(PREFIXES):
            print(
                f"ветка «{args.branch}» без объявленной приставки "
                f"({', '.join(PREFIXES)}) — изменение не открывается.\n"
                "Имя ветки здесь переключатель поведения (003), а не оформление."
            )
            return EXIT_OK

        token = os.environ.get("MERGE_QUEUE_TOKEN", "")
        if not token:
            print(
                "не настроено: нет токена владельца (MERGE_QUEUE_TOKEN).\n"
                "Изменение придётся открыть руками, и автором станет тот, кто открыл.\n"
                "На токен прогона шаг не переходит намеренно: это дало бы ровно ту\n"
                "подмену авторства, ради которой он заведён (131).",
                file=sys.stderr,
            )
            return EXIT_NOT_CONFIGURED

        owner = args.repo.split("/")[0]
        head = f"{owner}:{args.branch}"
        query = urllib.parse.urlencode({"head": head, "state": "open"})
        existing = ghrest.request("GET", f"repos/{args.repo}/pulls?{query}", token) or []
        if existing:
            number = existing[0]["number"]
            print(f"изменение для ветки уже открыто: #{number} — второе не заводится")
            return EXIT_OK

        title, body = describe(args.branch, args.base)
        if args.dry_run:
            print(f"открыло бы: {title}\n\n{body}")
            return EXIT_OK

        created = ghrest.request(
            "POST",
            f"repos/{args.repo}/pulls",
            token,
            {"title": title, "body": body, "head": args.branch, "base": args.base, "draft": False},
        )
        number = created["number"]
        print(f"открыто изменение #{number}: {created['html_url']}")

        # ЗОНЫ СТАВИТ ТОТ, КТО ОТКРЫЛ. Метка — вход механизма (064), и гейт
        # разметки требует зону; изменение, открытое без неё, конвейер тут же
        # отвергает за собственную недоработку. Ставятся только ЗОНЫ: они
        # выводятся из тронутых файлов машинно, а род задачи — суждение автора,
        # и угадывать его нечем.
        zones = sorted(labels.zones_for(labels.load(), changed_files(args.branch, args.base)))
        if zones:
            ghrest.request(
                "POST", f"repos/{args.repo}/issues/{number}/labels", token, {"labels": zones}
            )
            print(f"проставлены зоны: {', '.join(zones)}")
        else:
            print(
                "зоны не выведены: тронутое не покрыто путями состава — "
                "разметку поставит человек, и гейт об этом скажет"
            )
        print(
            "Проба, а не доверие (135): автор в общей ветке после слияния обязан\n"
            "стать человеком. Не стал — механизм неверен, и видно это сразу."
        )
        return EXIT_OK
    except (NotRun, labels.BadConfig, ghrest.TransportError) as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
