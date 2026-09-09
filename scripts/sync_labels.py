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
import os
import sys
from pathlib import Path
from typing import Any, Final

import ghrest
import labels

EXIT_CLEAN: Final = 0
EXIT_BROKEN: Final = 2
#: Единицу отдаёт сам Python при необработанном сбое, поэтому объявленным
#: состоянием она быть не может: иначе сломанный механизм читается как
#: работающий. Объявленные исходы — 0, 2 и 3; всё прочее отказ (068).
EXIT_FINDINGS: Final = 3


class NotRun(RuntimeError):
    """Проверка не отработала: третий исход, а не находка."""


def differs(label: labels.Label, actual: dict[str, Any]) -> bool:
    """Отвечает, расходится ли метка площадки с объявленной."""
    return (actual.get("color") or "").lower() != label.color.lower() or (
        actual.get("description") or ""
    ) != label.description


def sync(repo: str, token: str, declared: list[labels.Label], dry_run: bool) -> int:
    """Применяет объявленный состав и возвращает код исхода."""
    existing = {item["name"]: item for item in ghrest.paginate(f"repos/{repo}/labels", token)}
    created: list[str] = []
    updated: list[str] = []

    for label in declared:
        actual = existing.get(label.name)
        body = {"name": label.name, "color": label.color, "description": label.description}
        if actual is None:
            created.append(label.name)
            if not dry_run:
                ghrest.request("POST", f"repos/{repo}/labels", token, body)
        elif differs(label, actual):
            updated.append(label.name)
            if not dry_run:
                path = f"repos/{repo}/labels/{ghrest.quote(label.name)}"
                ghrest.request("PATCH", path, token, body)

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
    parser.add_argument("--config", type=Path, default=labels.DEFAULT_PATH, help="состав меток")
    parser.add_argument(
        "--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="владелец/имя"
    )
    parser.add_argument("--dry-run", action="store_true", help="показать разницу, не применяя её")
    args = parser.parse_args(argv)

    try:
        token = ghrest.token_from_env()
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")

        declared = labels.load(args.config)
        if not token:
            raise NotRun(
                f"объявлено в файле: {len(declared)}, но состояние площадки не прочитано — "
                "нет токена. Это третий исход, а не «чисто»"
            )
        return sync(args.repo, token, declared, args.dry_run)
    except (NotRun, labels.BadConfig, ghrest.TransportError) as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
