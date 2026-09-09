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
import re
import sys
from pathlib import Path
from typing import Any, Final

import changerefs
import ghrest
import labels

ZONE_PREFIX: Final = labels.ZONE_PREFIX
#: Незакрытый пункт чек-листа задачи в её теле.
OPEN_ITEM_RE: Final = re.compile(r"^\s*[-*]\s*\[ \]\s*(\S.*?)\s*$", re.MULTILINE)

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


def open_items(body: str) -> list[str]:
    """Незакрытые пункты чек-листа задачи, как они в ней записаны."""
    return [item.strip() for item in OPEN_ITEM_RE.findall(body or "")]


def premature(repo: str, token: str, links: list[Any], declared: list[str]) -> list[str]:
    """Задачи, которые изменение закрывает целиком, не доделав.

    ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ВНИМАНИЕ АВТОРА. Площадка умеет только полное
    закрытие: `Closes #N` закрывает задачу вместе с несделанными этапами, и
    они теряются молча — задача уходит из списка открытых, и туда больше никто
    не смотрит. Проверка полноты, а не непустоты (128), на новом предмете.

    Пункт, названный закрытым в теле самого изменения, из счёта уходит: иначе
    последний этап закрыть было бы нечем — отметить его до слияния негде, а
    после слияния задача уже закрыта.

    Задача БЕЗ чек-листа проходит: отмечать в ней нечего, и требовать список
    там, где этап один, значило бы заводить ритуал (154). Требование к
    заведению задачи с этапами записано в AGENTS.md.
    """
    problems: list[str] = []
    for link in links:
        if not link.closes:
            continue
        try:
            issue = ghrest.request("GET", f"repos/{repo}/issues/{link.number}", token) or {}
        except ghrest.TransportError as exc:
            raise NotRun(f"задача #{link.number} не прочитана: {exc}") from exc
        left = [
            item
            for item in open_items(str(issue.get("body") or ""))
            if changerefs.normalise(item) not in declared
        ]
        if left:
            problems.append(
                f"#{link.number} закрывается целиком, а в ней осталось незакрытых пунктов: "
                f"{len(left)} — первый «{left[0]}». Либо связь «Refs», либо строка "
                "«Закрывает пункт: <текст>» на каждый доделанный"
            )
    return problems


def read_files(inline: str, from_path: str) -> list[str]:
    """Читает список тронутых путей: из файла по NUL либо из строки по строкам.

    Путь с пробелом или не-ASCII git без `-z` отдаёт экранированным, и такой
    путь молча выпадает из отбора зон: метка не выставится, а гейт останется
    зелёным. Поэтому прогон передаёт список ФАЙЛОМ (`--files-from`), а не
    строкой: оболочка вырезает NUL из подстановки.
    """
    if from_path:
        raw = Path(from_path).read_bytes().decode("utf-8")
        return [name for name in raw.split("\0") if name]
    return [line.strip() for line in inline.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", default="", help="тронутые файлы через перевод строки")
    parser.add_argument(
        "--files-from",
        default="",
        help="файл со списком тронутых путей, разделённых NUL (git diff -z)",
    )
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
    files = read_files(args.files, args.files_from)
    # Охват печатается всегда: проверка, читающая список путей, без числа
    # неотличима от чистого результата — слепота выглядит как «нечего держать»
    # (165).
    print(f"тронутых путей прочитано: {len(files)}")

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

    text = f"{title}\n{body}"
    token = ghrest.token_from_env()
    if token and os.environ.get("GITHUB_REPOSITORY"):
        problems += premature(
            os.environ["GITHUB_REPOSITORY"],
            token,
            changerefs.links_in(text),
            changerefs.closed_items_in(text),
        )

    if not changerefs.has_link(text):
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
