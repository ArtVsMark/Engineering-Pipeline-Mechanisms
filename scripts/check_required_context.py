"""Сверяет обязательный контекст защиты ветки с тем, что выдаёт дерево.

Настройка защиты живёт **вне дерева**: её не видит ни ревью, ни прогон. Поэтому
расхождение между именем джоба и именем в списке обязательных не ловится ничем
и обнаруживается простоем — у соседнего проекта защита требовала контекста,
которого не выдавал ни один прогон, и не сливалось ничего при зелёных
проверках.

Что проверяется:

* в списке обязательных **ровно одно** имя — список, перечисляющий матрицу,
  ломается при добавлении версии;
* это имя выдаёт джоб, объявленный в ``ci.yml``;
* матричные имена в список не попали.

Прав на чтение защиты у токена прогона нет, и это не поломка, а
ненастроенность: без токена владельца сверка не выполняется и говорит об этом
(исход 1), вместо того чтобы молча зеленеть.

Исходы (правило 039): ``0`` совпадает · ``1`` расхождение или сверка не
настроена · ``2`` не отработало.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final

import yaml

API_ROOT: Final = "https://api.github.com"
GATES_FILE: Final = Path(".github/workflows/ci.yml")

EXIT_OK: Final = 0
EXIT_FINDINGS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Сверка не отработала: третий исход, а не «совпадает»."""


def declared_context(summary_job: str) -> str:
    """Отдаёт имя контекста, которое выдаст сводный джоб дерева."""
    if not GATES_FILE.is_file():
        raise NotRun(f"нет описания гейтов: {GATES_FILE}")
    document = yaml.safe_load(GATES_FILE.read_text(encoding="utf-8"))
    jobs = (document or {}).get("jobs") or {}
    if summary_job not in jobs:
        raise NotRun(f"в {GATES_FILE} нет джоба «{summary_job}» — предмет сверки не найден (075)")
    job = jobs[summary_job] or {}
    if "strategy" in job:
        raise NotRun(
            f"джоб «{summary_job}» матричный: матричные имена в список обязательных "
            "не попадают никогда"
        )
    # Имя контекста — это `name:` джоба, а если его нет, идентификатор джоба.
    return str(job.get("name") or summary_job)


def protection(repo: str, branch: str, token: str) -> list[str]:
    """Читает список обязательных контекстов защиты ветки."""
    url = f"{API_ROOT}/repos/{repo}/branches/{branch}/protection/required_status_checks"
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload: dict[str, Any] = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 401):
            raise NotRun(
                f"нет прав читать защиту ветки ({exc.code}) — нужен токен владельца"
            ) from exc
        if exc.code == 404:
            return []
        raise NotRun(f"GET {url} → {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise NotRun(f"GET {url} → площадка недоступна: {exc.reason}") from exc

    contexts = payload.get("contexts")
    if contexts is None:
        contexts = [check["context"] for check in payload.get("checks", [])]
    return [str(name) for name in contexts]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", default="main")
    parser.add_argument("--summary-job", default="gates-complete")
    args = parser.parse_args(argv)

    try:
        expected = declared_context(args.summary_job)
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    token = os.environ.get("MERGE_QUEUE_TOKEN") or ""
    if not token:
        print(
            f"не настроено: дерево выдаёт контекст «{expected}», но защиту ветки без\n"
            "токена владельца не прочитать. Сверка не выполнена — и это сказано,\n"
            "а не зазеленено: настройка живёт вне дерева, и её расхождение с ним\n"
            "не ловится ничем другим.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    try:
        actual = protection(args.repo, args.branch, token)
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not actual:
        print(
            f"находка: у ветки «{args.branch}» нет обязательных контекстов.\n"
            f"Дерево выдаёт «{expected}» — поставьте его единственным обязательным.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    if actual != [expected]:
        print(
            f"находка: защита требует {actual}, а дерево выдаёт «{expected}».\n"
            "В списке обязано быть ровно одно имя, и это имя сводного джоба:\n"
            "перечисление матрицы ломается при добавлении версии, а имя, которого\n"
            "не выдаёт никто, оставляет изменение в вечном ожидании.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    print(f"совпадает: защита «{args.branch}» требует ровно «{expected}»")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
