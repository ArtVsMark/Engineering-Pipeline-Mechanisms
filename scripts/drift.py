#!/usr/bin/env python3
"""Дрейф: мир сдвинулся, а дерево не менялось.

ЧЕГО НЕ ВИДИТ НИ ОДИН ГЕЙТ. Проверка на изменении смотрит дерево и диф, и
этого хватает, пока красное приходит от НАШЕЙ правки. Но часть входов лежит
снаружи: каталог правил движется, его выгрузка меняет схему, сводка семьи
стареет, действие выпускает новую версию. Такое красное не приходит никогда —
не потому, что его нет, а потому, что никто не спрашивает.

ПОЧЕМУ НЕ «ГОНЯТЬ ВСЕ ГЕЙТЫ ПО РАСПИСАНИЮ». Гейт, читающий только дерево,
детерминирован: между изменениями он даёт тот же ответ, и заход по расписанию
— холостая работа. Замер соседа, из-за которого очередь двигает только голову:
21 холостой прогон против 12 полезных на шести изменениях. Здесь спрашивается
ровно то, чей вход СНАРУЖИ, и каждая проверка называет, откуда её вход.

ПОЧЕМУ СОВЕЩАТЕЛЬНЫЙ, А НЕ ОБЯЗАТЕЛЬНЫЙ. Дрейф — это источник работы, а не
здоровье общей ветки: каталог, выпустивший новое правило, ничего у нас не
сломал. Держать слияние за движение соседа значило бы заморозить работу по
чужому расписанию
([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
Критичное станет обязательным поимённо и внутри сводного гейта, а не новым
именем в защите ветки: имена в защите — договор с потребителем, и каждое
лишнее однажды даёт вечное ожидание.

У НАХОДКИ ЕСТЬ АДРЕСАТ, ПЕРЕЖИВАЮЩИЙ ЗАХОД
([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)).
Красное по расписанию без адресата — это шум, который учат пролистывать. Записи
идут в живую задачу тем же механизмом, что и находки внешнего взгляда: свой
маркер, одно тело, снятие строкой в изменении.

Исходы (правило 039): ``0`` дрейфа нет · ``2`` шаг не отработал · ``3`` дрейф
записан.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Final

import findings
import ghrest
import paths
import report

MARKER: Final = "<!-- drift: не удаляйте, по этой строке задача находится снова -->"
TITLE: Final = "Дрейф: внешнее состояние сдвинулось"

EXIT_NOTHING: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RECORDED: Final = 3

#: Выгрузка каталога и сводка потребителей. Оба — СНИМКИ: каталог собирает их
#: своим прогоном, и читаются они по сети, а не из дерева. В этом весь предмет
#: механизма: дерево не менялось, а снимок — да.
EXPORT_URL: Final = (
    "https://raw.githubusercontent.com/ArtVsMark/Engineering-Incidents-Playbook"
    "/main/export/rules.json"
)
WHERE_URL: Final = (
    "https://raw.githubusercontent.com/ArtVsMark/Engineering-Incidents-Playbook"
    "/badges/export/where.json"
)
CATALOGUE: Final = "ArtVsMark/Engineering-Incidents-Playbook"

#: Механизмами считаются эти три рода ответа. Тот же состав, что у разреза
#: семьи: два понимания слова «держится машиной» разошлись бы молча (090).
MACHINE: Final = frozenset({"gate", "pipeline", "code"})


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «дрейфа нет»."""


@dataclass(frozen=True, slots=True)
class Drift:
    """Одна находка дрейфа: чей вход сдвинулся, что видно и что делать."""

    #: Короткое имя источника — по нему запись узнаётся снова и снимается.
    source: str
    #: Что именно разошлось, числами: «было X, стало Y», а не «устарело».
    said: str
    #: Что с этим делать. Без этого запись — сообщение о погоде (142).
    next_step: str

    def __str__(self) -> str:
        """Строка записи ровно того вида, который читает разбор тела задачи."""
        return f"- `{self.source}` — {self.said} · **что делать:** {self.next_step}"


#: Чтение чужого снимка — общим транспортом, а не своим. Второй транспорт
#: вырастает из фразы «мне нужен всего один запрос», и гейт `test_ghrest.py`
#: поймал здесь ровно это (090).
fetch = ghrest.raw_json


def ours() -> dict[str, Any]:
    """Наш живой ответ каталогу — из дерева, а не из чужого снимка."""
    path = paths.BINDINGS
    if not path.is_file():
        raise NotRun(f"нет {path}: сверять снимок не с чем (075)")
    answer = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(answer, dict):
        raise NotRun(f"{path}: ответ каталогу не словарь")
    return answer


def catalogue_moved(export: dict[str, Any], mine: dict[str, Any]) -> list[Drift]:
    """Каталог сдвинулся: новые правила или новая версия выгрузки.

    Отставание версии выгрузки — не про формат: подъём контракта означает, что
    ответы стоит ПЕРЕЧИТАТЬ, а не только починить схему (157). Первая редакция
    нашего ответа объявила схему по памяти, и расхождение всплыло только на
    чужом прогоне — то есть у соседа, а не у нас.
    """
    found: list[Drift] = []
    contracts = export.get("contracts") or {}
    theirs, said_ours = str(contracts.get("export") or ""), str(mine.get("answers_to") or "")
    if theirs and said_ours and theirs != said_ours:
        found.append(
            Drift(
                "export-contract",
                f"выгрузка каталога поднялась до {theirs}, ответы построены по {said_ours}",
                "перечитать ответы под новую выгрузку, затем поднять `answers_to` (157)",
            )
        )
    bindings, mine_schema = str(contracts.get("bindings") or ""), str(mine.get("schema") or "")
    if bindings and mine_schema and bindings != mine_schema:
        found.append(
            Drift(
                "bindings-schema",
                f"каталог ждёт схему ответа {bindings}, у нас {mine_schema}",
                "привести `.rules/bindings.json` к схеме каталога",
            )
        )
    theirs_count = export.get("count")
    answered = len(mine.get("rules") or {})
    if isinstance(theirs_count, int) and theirs_count != answered:
        found.append(
            Drift(
                "rules-count",
                f"правил в каталоге {theirs_count}, ответов у нас {answered}",
                "ответить по новым правилам — очередь разбора, а не молчание (129)",
            )
        )
    return found


def snapshot_is_stale(where: dict[str, Any], mine: dict[str, Any], project: str) -> list[Drift]:
    """Сводка семьи показывает нас не тем, чем мы стали.

    Это не косметика: по этой сводке соседи выбирают, у кого перенимать
    механизм, а разрез приоритета — наш собственный — считает по ней же. Замер
    10.09.2026: снимок семичасовой давности показывал шесть правил документами,
    когда они уже держались гейтами, и разрез назвал их «долгом», которого нет.
    """
    us = next(
        (
            consumer
            for consumer in where.get("consumers") or []
            if str(consumer.get("repo") or "").endswith(project.split("/")[-1])
        ),
        None,
    )
    if us is None:
        return [
            Drift(
                "family-snapshot",
                "нас нет в сводке семьи вовсе",
                "проверить, читает ли каталог наш ответ: `.rules/bindings.json` и его `project`",
            )
        ]
    shown = {
        rule: (answer or {}).get("mechanism")
        for rule, answer in (us.get("holds") or {}).items()
        if isinstance(answer, dict)
    }
    live = {
        rule: (answer or {}).get("mechanism") for rule, answer in (mine.get("rules") or {}).items()
    }
    behind = sorted(
        rule
        for rule, mechanism in live.items()
        if mechanism in MACHINE and shown.get(rule) not in MACHINE
    )
    if not behind:
        return []
    said = ", ".join(behind[:6]) + ("…" if len(behind) > 6 else "")
    return [
        Drift(
            "family-snapshot",
            f"сводка показывает {len(behind)} наших правил документами, "
            f"а они уже механизмы: {said}",
            "дождаться ночного прогона каталога либо позвать его кнопкой; "
            "до тех пор разрез приоритета по этой сводке врёт",
        )
    ]


def pinned_tag_moved(repo: str, token: str) -> list[Drift]:
    """Действие каталога подключено тегом, а у каталога вышел новый выпуск.

    Тег здесь оставлен намеренно (закрепление по SHA — для того, что приходит
    со стороны), но «намеренно» не значит «навсегда»: выпуск каталога может
    нести починку гейта, которым мы держим своё правило.
    """
    used: set[str] = set()
    for path in sorted(paths.WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            mark = f"{CATALOGUE}/"
            if mark in line and "@v" in line:
                used.add(line.rsplit("@", 1)[1].strip().split()[0])
    if not used:
        return []
    latest = ghrest.request("GET", f"repos/{CATALOGUE}/releases/latest", token) or {}
    newest = str(latest.get("tag_name") or "")
    behind = sorted(tag for tag in used if newest and tag != newest)
    if not behind:
        return []
    return [
        Drift(
            "catalogue-action",
            f"подключено {', '.join(behind)}, у каталога выпущен {newest}",
            f"прочитать журнал выпуска и поднять тег, если он нас касается: "
            f"https://github.com/{CATALOGUE}/releases/tag/{newest}",
        )
    ]


def render_body(found: list[Drift], silent: list[str] | None = None) -> str:
    """Тело живой задачи: записи, неопрошенные источники и как это снимается."""
    lines = [
        MARKER,
        "",
        "> **Читатель:** окно, берущее работу. Дрейф — это источник работы, а не",
        "> красное: сдвинулся ВНЕШНИЙ вход, дерево не менялось.",
        "",
        "Запись снимается сама, когда расхождения больше нет: тело переписывается",
        "на каждом заходе целиком, и ведётся не руками, а механизмом (049).",
        "",
        "## Сдвинулось",
        "",
    ]
    if found:
        lines.extend(str(one) for one in found)
    else:
        lines.append("Пусто — внешние входы сошлись с деревом.")
    if silent:
        # Неопрошенный источник называется здесь же: без этого пустой список
        # читался бы как «всё сошлось», а он значит «половину не спросили».
        lines += [
            "",
            "## Не спрошено на последнем заходе",
            "",
            *(f"- {name}" for name in silent),
        ]
    return "\n".join(lines) + "\n"


def save(repo: str, token: str, found: list[Drift], silent: list[str], *, apply: bool) -> None:
    """Записывает живую задачу: обновляет по месту или заводит одну.

    Отказ записи шага не роняет: дрейф — совещательный канал, и потерять о нём
    сообщение хуже, чем не иметь его вовсе (084).
    """
    body = render_body(found, silent)
    number, current = findings.live_issue(repo, token, MARKER)
    if not apply:
        print(f"(пробный заход) {'обновил бы' if number else 'завёл бы'} задачу дрейфа")
        return
    try:
        if number is None:
            if not found:
                # Заводить пустую задачу незачем: пустого адресата никто не
                # читает, а его существование выглядит работой.
                return
            fresh = ghrest.request(
                "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
            )
            print(f"заведена задача дрейфа #{(fresh or {}).get('number')}")
            return
        if current.strip() == body.strip():
            print(f"задача дрейфа #{number} уже описывает это состояние")
            return
        ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
        print(f"задача дрейфа #{number} обновлена")
    except ghrest.TransportError as exc:
        print(f"::warning::Дрейф не записан: {report.cut(str(exc))}", file=sys.stderr)


#: Источники дрейфа: имя и то, как его спросить. Списком, а не цепочкой
#: вызовов, потому что источники НЕЗАВИСИМЫ: недоступный каталог не отменяет
#: устаревшей сводки семьи. Отказ одного источника печатается и заход идёт
#: дальше; молча пропущенный источник выглядел бы как «дрейфа нет» (045).
SOURCES: Final = ("каталог", "сводка семьи", "выпуск каталога")


def look(repo: str, token: str, mine: dict[str, Any]) -> tuple[list[Drift], list[str]]:
    """Спрашивает все источники; отдаёт находки и имена тех, кто не ответил."""
    found: list[Drift] = []
    silent: list[str] = []
    asks: tuple[tuple[str, Any], ...] = (
        ("каталог", lambda: catalogue_moved(fetch(EXPORT_URL), mine)),
        (
            "сводка семьи",
            lambda: snapshot_is_stale(fetch(WHERE_URL), mine, str(mine.get("project") or repo)),
        ),
        ("выпуск каталога", lambda: pinned_tag_moved(repo, token)),
    )
    for name, ask in asks:
        try:
            found.extend(ask())
        except (NotRun, ghrest.TransportError) as exc:
            silent.append(name)
            print(
                f"::warning::Источник «{name}» не ответил: {report.cut(str(exc))}", file=sys.stderr
            )
    return found, silent


def main(argv: list[str] | None = None) -> int:
    """Точка входа: спрашивает внешние входы и записывает расхождения."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="записать, а не показать")
    args = parser.parse_args(argv)

    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        mine = ours()
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    found, silent = look(args.repo, token, mine)
    # Молчание ВСЕХ источников — это поломка захода, а не сошедшееся состояние:
    # «дрейфа нет» и «спросить не удалось» снаружи одинаковы (045).
    if len(silent) == len(SOURCES):
        print("шаг не отработал: ни один источник не ответил", file=sys.stderr)
        return EXIT_BROKEN

    for one in found:
        print(str(one))
    save(args.repo, token, found, silent, apply=args.apply)
    if not found:
        print("дрейфа нет: внешние входы сошлись с деревом")
        return EXIT_NOTHING
    print(f"сдвинулось внешних входов: {len(found)}")
    return EXIT_RECORDED


if __name__ == "__main__":
    raise SystemExit(main())
