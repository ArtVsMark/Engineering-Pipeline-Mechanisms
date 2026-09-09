"""Гейт разметки: метки изменения и связь с задачей.

Правило 064: метки — вход механизма, а не украшение, поэтому они проверяются
машиной. Правило 068: список разрешительный — метка, которой нет в
``.github/labels.yml``, механизмом не читается, и стоять на изменении она не
должна: иначе появляется вторая, необъявленная классификация.

Связь с задачей обязательна: без неё задача не закроется при слиянии, а
приоритет очереди наследовать неоткуда.

Зона выводится из тронутых файлов по полю ``paths`` состава — но только для
зон, у которых оно есть. Зона без ``paths`` ставится человеком при разборе, и
требовать её машинно нечем; молчаливо считать такое изменение размеченным
нельзя, поэтому хотя бы одна зона обязана стоять всегда.

Исходы (правило 039): ``0`` разметка на месте · ``1`` изменение отвергнуто ·
``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

import changerefs
import ghrest
import labels

ZONE_PREFIX: Final = labels.ZONE_PREFIX

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «прошло»."""


def load_event() -> dict[str, Any]:
    """Читает событие площадки: предмет проверки — изменение, а не ветка."""
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not Path(path).is_file():
        raise NotRun("нет события площадки (GITHUB_EVENT_PATH) — предмет проверки не найден (075)")
    try:
        event = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotRun(f"событие не читается: {exc}") from exc
    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        raise NotRun("событие не об изменении — гейту нечего проверять")
    return pull


def fresh(pull: dict[str, Any], repo: str, token: str) -> dict[str, Any]:
    """Отдаёт изменение, каким оно ЕСТЬ, а не каким было в снимке события.

    Снимок события — это состояние на момент срабатывания, и на `opened` меток
    в нём нет по построению: их проставляет шаг открытия, и делает это через
    доли секунды ПОСЛЕ. Гейт, читающий снимок, выносит вердикт по прошлому:
    замер 09.09 — изменение #38 отвергнуто за «ни одной зоны», когда все три
    зоны на нём уже стояли.

    Без токена или номера остаётся снимок — и это объявлено, а не подменено
    тихо (045): вердикт по снимку возможен, просто он может отстать.
    """
    number = pull.get("number")
    if not token or not repo or not number:
        print(
            "состояние изменения не перечитано: нет токена или номера — вердикт по снимку\n"
            "события, и он может отставать от площадки",
            file=sys.stderr,
        )
        return pull
    try:
        current = ghrest.request("GET", f"repos/{repo}/pulls/{int(number)}", token)
    except ghrest.TransportError as exc:
        print(f"состояние изменения не перечитано: {exc} — вердикт по снимку", file=sys.stderr)
        return pull
    return current if isinstance(current, dict) else pull


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", default="", help="тронутые файлы через перевод строки")
    args = parser.parse_args(argv)

    try:
        pull = load_event()
        declared = labels.load()
    except (NotRun, labels.BadConfig) as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # Метки — вход механизма, и читать их надо у площадки, а не у снимка.
    pull = fresh(pull, os.environ.get("GITHUB_REPOSITORY", ""), ghrest.token_from_env())

    on_pr = {str(label["name"]) for label in pull.get("labels", [])}
    body = pull.get("body") or ""
    title = pull.get("title") or ""
    files = [line.strip() for line in args.files.splitlines() if line.strip()]

    problems: list[str] = []

    undeclared = sorted(on_pr - {label.name for label in declared})
    if undeclared:
        problems.append(
            "на изменении метки, которых не объявляет .github/labels.yml: "
            + ", ".join(undeclared)
            + " — список разрешительный (068)"
        )

    zones_on_pr = {name for name in on_pr if name.startswith(ZONE_PREFIX)}
    if not zones_on_pr:
        problems.append("не поставлена ни одна зона (area/*) — изменение не разобрано")

    expected = labels.zones_for(declared, files)
    missing = sorted(expected - zones_on_pr)
    if missing:
        problems.append(
            "тронуты файлы зон, которых нет на изменении: "
            + ", ".join(missing)
            + " — зона выведена из путей состава, а не угадана"
        )

    if not changerefs.has_link(f"{title}\n{body}"):
        problems.append(
            "нет связи с задачей: ни «Closes #N», ни «Refs #N» — "
            "без неё задача не закроется при слиянии, а приоритет очереди наследовать неоткуда"
        )

    if problems:
        print(f"отвергнуто ({len(problems)}):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return EXIT_REJECTED

    print(f"разметка на месте: {', '.join(sorted(on_pr)) or '—'}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
