#!/usr/bin/env python3
"""Приводит метки репозитория к объявленному составу `.github/labels.yml`.

Правило 064: метка — вход механизма, а не украшение, поэтому её состав задаётся
файлом в дереве, а не действием в интерфейсе. Правило 068: список
разрешительный — метка, которой в файле нет, механизмом не читается.

Три исхода, а не два (правило 039):

* ``0`` — чисто: объявленное применено, незаявленных меток в репозитории нет;
* ``1`` — есть находка: в репозитории метки, которых файл не объявляет. Это
  не поломка: удаление метки снимает её со всех задач разом и решается
  человеком, а не синхронизатором;
* ``2`` — проверка не отработала: нет файла, нет токена, площадка ответила
  отказом. Отличается от «чисто» наличием результата, а не кодом возврата
  (правило 039), поэтому итог печатается всегда.

Транспорт — REST, самый дешёвый из доступных для этой операции (правило 001).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterator

import yaml

API_ROOT: Final = "https://api.github.com"
COLOR_RE: Final = re.compile(r"^[0-9a-fA-F]{6}$")
DEFAULT_CONFIG: Final = Path(".github/labels.yml")

EXIT_CLEAN: Final = 0
EXIT_FINDINGS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Проверка не отработала: третий исход, а не находка."""


@dataclass(frozen=True, slots=True)
class Label:
    """Объявленная метка: имя, цвет, описание и пути зоны."""

    name: str
    color: str
    description: str
    paths: tuple[str, ...] = ()

    def differs_from(self, actual: dict[str, Any]) -> bool:
        """Отвечает, расходится ли метка площадки с объявленной."""
        return (
            (actual.get("color") or "").lower() != self.color.lower()
            or (actual.get("description") or "") != self.description
        )


def load_declared(path: Path) -> list[Label]:
    """Читает состав меток, падая на любом дефекте входа (правило 075)."""
    if not path.is_file():
        raise NotRun(f"состав меток не найден: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise NotRun(f"состав меток не разбирается: {exc}") from exc

    if not isinstance(raw, list) or not raw:
        raise NotRun(f"состав меток пуст: {path} — это ошибка входа, а не «чисто»")

    labels: list[Label] = []
    problems: list[str] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            problems.append(f"запись {index}: не отображение")
            continue
        name = str(item.get("name", "")).strip()
        color = str(item.get("color", "")).strip().lstrip("#")
        description = str(item.get("description", "")).strip()
        paths = item.get("paths", []) or []
        if not name:
            problems.append(f"запись {index}: пустое имя")
        if not COLOR_RE.match(color):
            problems.append(f"{name or index}: цвет «{color}» не шесть шестнадцатеричных цифр")
        if not description:
            problems.append(f"{name or index}: пустое описание — метка без описания нечитаема")
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            problems.append(f"{name or index}: paths — не список строк")
            paths = []
        if not problems:
            labels.append(Label(name, color, description, tuple(paths)))

    if problems:
        raise NotRun("состав меток не проходит проверку:\n  " + "\n  ".join(problems))

    names = [label.name for label in labels]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise NotRun(f"имя метки объявлено дважды: {', '.join(duplicates)}")

    return labels


def api(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    """Один запрос к REST площадки; любой отказ — третий исход."""
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


def fetch_existing(repo: str, token: str) -> Iterator[dict[str, Any]]:
    """Отдаёт метки репозитория постранично."""
    page = 1
    while True:
        chunk = api("GET", f"{API_ROOT}/repos/{repo}/labels?per_page=100&page={page}", token)
        if not chunk:
            return
        yield from chunk
        if len(chunk) < 100:
            return
        page += 1


def sync(repo: str, token: str, declared: list[Label], dry_run: bool) -> int:
    """Применяет объявленный состав и возвращает код исхода."""
    existing = {item["name"]: item for item in fetch_existing(repo, token)}
    created: list[str] = []
    updated: list[str] = []

    for label in declared:
        actual = existing.get(label.name)
        body = {"name": label.name, "color": label.color, "description": label.description}
        if actual is None:
            created.append(label.name)
            if not dry_run:
                api("POST", f"{API_ROOT}/repos/{repo}/labels", token, body)
        elif label.differs_from(actual):
            updated.append(label.name)
            if not dry_run:
                url = f"{API_ROOT}/repos/{repo}/labels/{urllib.parse.quote(label.name)}"
                api("PATCH", url, token, body)

    undeclared = sorted(set(existing) - {label.name for label in declared})

    prefix = "будет заведено" if dry_run else "заведено"
    print(f"{prefix}: {', '.join(created) if created else '—'}")
    prefix = "будет поправлено" if dry_run else "поправлено"
    print(f"{prefix}: {', '.join(updated) if updated else '—'}")
    print(f"объявлено в файле: {len(declared)}")

    if undeclared:
        print(
            "\nнаходка: в репозитории есть метки, которых файл не объявляет —\n  "
            + "\n  ".join(undeclared)
            + "\n\nЛибо вписать их в .github/labels.yml с причиной, либо снять в\n"
            "репозитории. Синхронизатор их не удаляет: снятие метки трогает все\n"
            "задачи разом и решается человеком."
        )
        return EXIT_FINDINGS

    print("\nчисто: незаявленных меток нет")
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    """Точка входа: разбирает ключи, печатает исход, возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="состав меток")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="владелец/имя")
    parser.add_argument("--dry-run", action="store_true", help="показать разницу, не применяя её")
    args = parser.parse_args(argv)

    try:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")

        declared = load_declared(args.config)
        if not token:
            raise NotRun(
                f"объявлено в файле: {len(declared)}, но состояние площадки не прочитано — "
                "нет токена. Это третий исход, а не «чисто»"
            )
        return sync(args.repo, token, declared, args.dry_run)
    except NotRun as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
