#!/usr/bin/env python3
"""Собирает факты о проекте и один значок для ветки `badges`.

Факты о проекте публикует сам проект
([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)):
соседу, каталогу правил и витрине нужно знать, на какой версии контракта стоит
проект и сколько правил он держит, — и узнавать это чтением его дерева никто не
обязан.

ПРОИЗВОДНОЕ НЕ ЖИВЁТ РЯДОМ С ИСТОЧНИКОМ
([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-derived-file-is-not-a-store.md)).
Вывод этого механизма уезжает в отдельную ветку `badges` и там перезаписывается
целиком: его можно удалить и собрать заново, ничего не потеряв. В общей ветке
он протухал бы молча — и число из него разошлось бы с источником на первой же
правке
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

Числа берутся из источников, а не из памяти: `CONTRACT_VERSION`,
`.rules/bindings.json`, `.pipeline.yml`. Источник у каждого числа один
([035](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/035-version-is-never-edited-by-hand.md)).

Исходы: ``0`` собрано · ``2`` не собрать. Третьего здесь нет, и это названо, а
не пропущено: состояние «собрано, но с находками» у сборки фактов отсутствует —
источники проверяют их собственные гейты, а этот механизм либо прочитал их и
собрал, либо не смог. Правило 039 требует, чтобы исходы были объявлены и
различались, а не чтобы их было ровно три
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import paths
import pipeline_checks as policy

VERSION_FILE: Final = paths.VERSION
BINDINGS: Final = paths.BINDINGS
FACTS: Final = "facts.json"
BADGE: Final = "rules.svg"

#: Список разрешённого (068): статус, которого здесь нет, — это дефект ответа,
#: а не новая тонкость, о которой механизм обязан догадаться.
STATUSES: Final = ("active", "rejected", "not-applicable", "unreviewed")

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Сборка не отработала: третий исход, а не пустые факты."""


def contract_version(path: Path = VERSION_FILE) -> str:
    """Читает версию контракта из единственного её источника."""
    if not path.is_file():
        raise NotRun(f"нет версии контракта: {path}")
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise NotRun(f"{path} пуст — это ошибка входа, а не «версии нет» (075)")
    return version


def rules_facts(path: Path = BINDINGS) -> dict[str, Any]:
    """Считает ответ проекта по правилам каталога.

    Считается не «сколько правил хороших», а чем они держатся: механизм и
    документ — оба законные ответы, и разница между ними видна только числом.
    """
    if not path.is_file():
        raise NotRun(f"нет ответа каталогу: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc

    rules = document.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise NotRun(f"{path}: раздел rules пуст — предмет счёта не найден (075)")

    statuses: Counter[str] = Counter()
    mechanisms: Counter[str] = Counter()
    for number, answer in rules.items():
        if not isinstance(answer, dict):
            raise NotRun(f"{path}: ответ по правилу {number} не отображение")
        status = str(answer.get("status", "")).strip()
        if status not in STATUSES:
            raise NotRun(f"{path}: правило {number} несёт статус «{status}», которого нет в схеме")
        statuses[status] += 1
        if status == "active":
            mechanism = str(answer.get("mechanism", "")).strip()
            if not mechanism:
                raise NotRun(f"{path}: правило {number} действует, но чем — не сказано")
            mechanisms[mechanism] += 1

    return {
        "total": len(rules),
        "answered": len(rules) - statuses["unreviewed"],
        "by_status": {status: statuses[status] for status in STATUSES},
        "by_mechanism": dict(sorted(mechanisms.items())),
    }


def checks_facts(path: Path = policy.DEFAULT_PATH) -> dict[str, int]:
    """Считает классы проверок из ответа проекта."""
    try:
        checks = policy.load(path)
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc
    return {klass: len(policy.names_of(checks, klass)) for klass in policy.CLASSES}


def collect(root: Path, sha: str) -> dict[str, Any]:
    """Собирает все факты о проекте в одно отображение."""
    return {
        "schema": 1,
        "contract": contract_version(root / VERSION_FILE),
        "rules": rules_facts(root / BINDINGS),
        "checks": checks_facts(root / policy.DEFAULT_PATH),
        "generated": {
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha": sha,
        },
    }


def badge(label: str, value: str, color: str) -> str:
    """Рисует значок сам, без обращения к чужой службе.

    Значок с чужого сервиса — это внешняя зависимость витрины: она отвалится
    молча и оставит вместо числа пустое место, которое читается как «всё в
    порядке». Здесь SVG собирается из своих же чисел и лежит рядом с ними.
    """
    # Ширина считается по числу знаков: точной метрики шрифта у нас нет, а
    # приблизительная лучше, чем обрезанный текст.
    left = 8 * len(label) + 12
    right = 8 * len(value) + 12
    width = left + right
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" '
        f'role="img" aria-label="{label}: {value}">'
        f"<title>{label}: {value}</title>"
        f'<rect width="{left}" height="20" fill="#555"/>'
        f'<rect x="{left}" width="{right}" height="20" fill="{color}"/>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{left / 2}" y="14">{label}</text>'
        f'<text x="{left + right / 2}" y="14">{value}</text>'
        f"</g></svg>"
    )


def rules_badge(facts: dict[str, Any]) -> str:
    """Значок один: сколько правил каталога проект уже держит.

    Выбрано это число, а не «сборка зелёная»: зелёная сборка говорит о
    последнем прогоне, а доля разобранных правил — о том, где проект стоит, и
    она движется медленно и честно.
    """
    rules = facts["rules"]
    total = int(rules["total"])
    answered = int(rules["answered"])
    share = answered / total if total else 0.0
    color = "#e05d44" if share < 0.34 else "#dfb317" if share < 0.67 else "#4c1"
    return badge("правил держится", f"{answered}/{total}", color)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает факты и значок в каталог вывода."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="корень дерева, откуда читаются источники")
    parser.add_argument("--out-dir", required=True, help="куда положить производное")
    parser.add_argument("--sha", default="", help="голова, на которой собрано")
    args = parser.parse_args(argv)

    try:
        facts = collect(Path(args.root), args.sha)
    except NotRun as exc:
        print(f"факты не собраны: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / FACTS).write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (out / BADGE).write_text(rules_badge(facts) + "\n", encoding="utf-8")

    rules = facts["rules"]
    print(
        f"собрано: контракт {facts['contract']}, "
        f"правил {rules['answered']} из {rules['total']}, "
        f"проверок обязательных {facts['checks']['required']}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
