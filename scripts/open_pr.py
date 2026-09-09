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
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Final

API_ROOT: Final = "https://api.github.com"
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


def api(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    """Один запрос к REST площадки — самый дешёвый транспорт для этой операции (001)."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise NotRun(f"{method} {url} → {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise NotRun(f"{method} {url} → площадка недоступна: {exc.reason}") from exc


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

        token = os.environ.get("OWNER_TOKEN", "")
        if not token:
            print(
                "не настроено: нет токена владельца (OWNER_TOKEN).\n"
                "Изменение придётся открыть руками, и автором станет тот, кто открыл.\n"
                "На токен прогона шаг не переходит намеренно: это дало бы ровно ту\n"
                "подмену авторства, ради которой он заведён (131).",
                file=sys.stderr,
            )
            return EXIT_NOT_CONFIGURED

        owner = args.repo.split("/")[0]
        head = f"{owner}:{args.branch}"
        query = urllib.parse.urlencode({"head": head, "state": "open"})
        existing = api("GET", f"{API_ROOT}/repos/{args.repo}/pulls?{query}", token) or []
        if existing:
            number = existing[0]["number"]
            print(f"изменение для ветки уже открыто: #{number} — второе не заводится")
            return EXIT_OK

        title, body = describe(args.branch, args.base)
        if args.dry_run:
            print(f"открыло бы: {title}\n\n{body}")
            return EXIT_OK

        created = api(
            "POST",
            f"{API_ROOT}/repos/{args.repo}/pulls",
            token,
            {"title": title, "body": body, "head": args.branch, "base": args.base, "draft": False},
        )
        print(f"открыто изменение #{created['number']}: {created['html_url']}")
        print(
            "Проба, а не доверие (135): автор в общей ветке после слияния обязан\n"
            "стать человеком. Не стал — механизм неверен, и видно это сразу."
        )
        return EXIT_OK
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
