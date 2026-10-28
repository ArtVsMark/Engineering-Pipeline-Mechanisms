#!/usr/bin/env python3
"""Единый значок «CI │ Python 3.14 3.15 │ linux windows mac │ coverage │ release / PyPI │ version».

ПЕРЕЕХАЛО ИЗ КАТАЛОГА (#1563, этап 3 ArtVsMark/Engineering-Incidents-Playbook#930):
значки держат механизмы. Поведение — то же, что у `scripts/python_badge.py`
каталога на `353bf10`; имена переведены на латиницу. Заменены опоры, не ответы:
обращения к площадке — общим транспортом `ghrest` вместо `gh`
([001](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/001-transport-rest-not-graphql.md)),
работы файла CI — общим разбором YAML вместо построчного, версии прогонов —
`python_versions`, планка — `check_env.python_floor`: второго разбора одной
формы у механизмов нет
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ПРЕФИКС «CI» — ПОДПИСЬ ВСЕЙ КАРТИНКИ, А НЕ ЕЩЁ ОДИН СТАТУС (решение владельца
08.10, каталог #719). Первая зона окрашена исходом основного CI, но подписана
«Python», и снаружи читалась как «про версию». Префикс — серая часть В НАЧАЛЕ
ПЕРВОЙ ЗОНЫ, без просвета перед «Python»: так «CI» читается подписью именно
проверок, а цвет исхода остаётся у «Python». Префикс НЕ НАСТРАИВАЕТСЯ.

ЗОНЫ ВЫПУСКА (решение владельца 01.10). Покрытие и версия берутся из файлов
значков, которые проект уже собирает (`--coverage-json`, `--version-json`), а
не меряются второй раз (214); цвет покрытия — порогами `COVERAGE_THRESHOLDS`.
«release / PyPI» показывает старшие два числа выпуска: зелёный — номер на PyPI
совпадает с последним выпуском, красный — расходится (тогда видны оба:
`2.8 / 2.7`), серый — проект на PyPI не публикуется (`--pypi` пуст) или
выпусков нет. Версия — последней, синим: это счётчик, не проверка.

ЗОНА НАБОРОВ — ПОСЛЕ ОС (решение владельца 08.10, каталог #719). Набор — работа
основного CI, вход `--suites работа[:подпись],…`; цвет — исход этой работы в
решающем прогоне, та же лестница, что у ОС. ИМЯ РАБОТЫ СВЕРЯЕТСЯ С ФАЙЛОМ CI:
работа, которой там нет, — значок не собирается (код 2), а не рисуется серым
(005, 039). Наборов не больше ЧЕТЫРЁХ.

ЧАСТИ ПО ОС СТОЯТ ВСЕГДА, ВСЕ ТРИ. Цвет берётся у работ решающего прогона
основного CI: ОС красная, если на ней упала хоть одна работа, зелёная — если
работы на ней прошли, серая — если на ней не проверяли вовсе.

ТРИ ЦВЕТА, И ТРЕТИЙ — НЕ СЕРЕДИНА МЕЖДУ ДВУМЯ:
  • зелёный — последний прогон с вердиктом на `main` прошёл;
  • красный — последний прогон с вердиктом на `main` упал;
  • серый   — прогона с вердиктом на `main` нет вовсе: проверка не
    проводилась. Отменённый или пропущенный прогон вердиктом не считается и
    пропускается к предыдущему (039).

ВЕРСИИ БЕРУТСЯ У ПРОГОНОВ, А НЕ ПИШУТСЯ ЗДЕСЬ (005). Основные — каждая
`python-version` в основном прогоне (`--ci`), по возрастанию, первая — планка;
если версия там не читается — планка из `requires-python`. Основных может быть
несколько (решение владельца 14.10), и каждая окрашена своими работами — работа
с версией в имени отвечает за неё, без версии — за планку. Следующие — прогоны
с `allow-prereleases: true`; версия, сборки которой у setup-python ещё нет,
тёмно-серая со словами «сборки для CI ещё нет».

ЛЕСЕНКА СЕМЬИ — версии дерева, откуда исполняется скрипт: у соседа — дерево
механизмов на теге действия. Недостающая у проекта ступень — жёлтая
«проектом не проверяется» (решение владельца 16.10).

Исходы:
  0 — значок собран;
  2 — не собран: версий в прогонах не нашлось или площадка не ответила.
      Серым это НЕ рисуется: «не смогли спросить» и «не проводилась» — разные
      ответы, и подменять один другим значит соврать на картинке (039).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final
from xml.sax.saxutils import escape

import build_facts
import check_env
import ghrest
import main_guard
import paths
import pipeline_checks
import python_versions
import text_width
import version

#: Дерево проекта — рабочий каталог, как у прочих механизмов: вверх по дереву
#: настройка не ищется (096).
ROOT: Final = Path()
OUT: Final = paths.BADGES_DIR / "python.svg"
#: Основной прогон по умолчанию — тот же, что у фактов витрины (209).
CI: Final = build_facts.CI_FLOW.name

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Цвет и слово для каждого состояния. Слово уходит в подсказку картинки:
#: цвет без слова не читается ни скринридером, ни при слабом различении цветов.
#: ПАЛИТРА — GITHUB (решение владельца 01.10): те же цвета, которыми площадка
#: рисует свои ✓ и ✗ у проверок; замер контраста белого текста (WCAG) — в
#: истории каталога, выбран вид, а не порог 4,5:1.
STATES: Final[dict[str, tuple[str, str]]] = {
    "pass": ("#2da44e", "CI пройден"),
    "fail": ("#cf222e", "CI не пройден"),
    "none": ("#8c959f", "проверка не проводилась"),
    # Предварительная версия, сборки которой у площадки ещё нет: проверять
    # нечем, и это не «не проводилась» по нашей вине (решение владельца 14.10).
    # Тёмно-серый (владелец 16.10, вариант B): сборка появится сама.
    "unreleased": ("#57606a", "сборки для CI ещё нет"),
    # Версия лесенки семьи, которую проект не проверяет вовсе (владелец 16.10).
    # Жёлтый — отставание, которое чинится правкой проекта.
    "absent": ("#bf8700", "проектом не проверяется — версия лесенки семьи"),
}
#: Исходы прогона, которые вердикт. Прочие (cancelled, skipped, neutral,
#: stale, action_required) ничего не проверили и пропускаются к предыдущему.
PASSED: Final = frozenset({"success"})
FAILED: Final = frozenset({"failure", "timed_out", "startup_failure"})
#: События, прогон по которым говорит об ОБЩЕЙ ветке. `branch=main` у площадки —
#: это `head_branch`, а он равен `main` и у изменения из форка с веткой `main`.
OWN_EVENTS: Final = frozenset({"push", "schedule", "workflow_dispatch"})
#: Префикс метки раннера → имя ОС на значке. Порядок — порядок частей.
SYSTEMS: Final[dict[str, str]] = {"ubuntu": "linux", "windows": "windows", "macos": "mac"}
#: Лестница состояний частей: красное сильнее зелёного, зелёное — серого.
WEIGHT: Final[dict[str, int]] = {"none": 0, "pass": 1, "fail": 2}

Runs = Callable[[str], list[dict[str, Any]]]
Jobs = Callable[[int], list[dict[str, Any]]]
Builds = Callable[[], set[tuple[int, int]]]
#: Часть значка: надпись, цвет, слово для подсказки.
Part = tuple[str, str, str]


class NoAnswer(Exception):
    """Площадка не ответила — третий исход, а не серый цвет."""


def series(label: str) -> tuple[int, int]:
    """`3.14` → (3, 14): серия версии «X.Y», разрез по точке — не проза."""
    major, minor = label.split(".")[:2]
    return int(major), int(minor)


def versions(root: Path = ROOT, ci: str = CI) -> list[tuple[str, str]]:
    """(подпись версии, файл прогона): основные по возрастанию, следующие за ними.

    ОСНОВНЫХ МОЖЕТ БЫТЬ НЕСКОЛЬКО (решение владельца 14.10): с выходом 3.15
    планка осталась 3.14, а 3.15 стала обязательной проверкой — обе версии
    стоят в основном CI и обе держат слияние. Первая — планка.
    """
    # ОДИН РАЗБОР ПРОГОНОВ НА ВЫЗОВ (взгляд на #1565): основные, следующие и
    # отказы осей — из одного `read`, а не из трёх.
    declared, refused = python_versions.read(root)
    main_ones = sorted(
        {
            (f"{one.version[0]}.{one.version[1]}", one.flow)
            for one in declared
            if one.flow == ci and not one.preview
        },
        key=lambda one: series(one[0]),
    )
    if not main_ones and (root / python_versions.WORKFLOWS / ci).is_file():
        try:
            floor = check_env.python_floor(root)
        except check_env.NotRun:
            floor = None
        if floor:
            main_ones = [(f"{floor[0]}.{floor[1]}", ci)]
    upcoming = [(f"{one.version[0]}.{one.version[1]}", one.flow) for one in declared if one.preview]
    # Ось матрицы не разобралась — ячейки нет, но и молчания нет (каталог #926):
    # адрес уходит предупреждением в журнал шага.
    for refusal in refused:
        print(f"::warning::версия не прочитана — {refusal}", file=sys.stderr)
    return main_ones + sorted(set(upcoming), key=lambda one: (series(one[0]), one[1]))


def deciding(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Последний прогон С ВЕРДИКТОМ своей ветки; отменённые и пропущенные — мимо (039)."""
    for run in sorted(runs, key=lambda one: str(one.get("created_at") or ""), reverse=True):
        if run.get("event", "push") not in OWN_EVENTS:
            continue
        if run.get("conclusion") in PASSED | FAILED:
            return run
    return None


def state(runs: list[dict[str, Any]]) -> str:
    """Цвет по последнему прогону с вердиктом; без вердикта — серый."""
    run = deciding(runs)
    if run is None:
        return "none"
    return "pass" if run["conclusion"] in PASSED else "fail"


def outcome(job: dict[str, Any]) -> str:
    """Состояние одной работы: упала, прошла или ничего не проверила."""
    said = job.get("conclusion")
    return "fail" if said in FAILED else "pass" if said in PASSED else "none"


def by_system(jobs: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(ОС, состояние) для всех трёх ОС; без работ на ОС — серый.

    Приоритет fail > pass > none и от порядка работ не зависит: пропущенная
    работа не делает серой ОС, на которой проверки прошли (каталог, обзор #649).
    """
    total: dict[str, str] = {}
    for job in jobs:
        marks = job.get("labels") or []
        system = next(
            (
                name
                for prefix, name in SYSTEMS.items()
                if any(str(m).startswith(prefix) for m in marks)
            ),
            None,
        )
        if system is None:
            continue
        said = outcome(job)
        if WEIGHT[said] >= WEIGHT[total.get(system, "none")]:
            total[system] = said
    return [(name, total.get(name, "none")) for name in SYSTEMS.values()]


def ladder(known: list[tuple[str, str]] | None = None) -> list[str]:
    """Версии лесенки семьи — те, что проверяет само дерево механизмов.

    Берутся тем же `versions()`, что рисует значок механизмов: второй записи
    лесенки нет (214). Решение владельца 16.10: у всех один набор версий.
    У соседа дерево механизмов — выкачка общего шага `$MECHANISMS`, а не его
    рабочий каталог; без неё — само дерево, где скрипт исполняется.

    `known` — версии того же дерева, уже прочитанные вызывающим: второй разбор
    одних прогонов печатал бы каждое предупреждение об оси дважды (взгляд на
    #1565). Вызывающий отдаёт их, только когда дерево то же.
    """
    if known is not None:
        return [label for label, _ in known]
    return [label for label, _ in versions(mechanisms_tree())]


def mechanisms_tree() -> Path:
    """Дерево механизмов: выкачка общего шага `$MECHANISMS`, без неё — рабочий каталог."""
    return pipeline_checks.supplier_of() or ROOT


def on_ladder(
    parts: list[tuple[str, str]],
    steps: list[str],
    released: set[tuple[int, int]] | None = None,
) -> list[tuple[str, str]]:
    """Версии проекта и недостающие ступени лесенки, по возрастанию.

    Недостающая ступень — `absent`, если сборка серии есть, и `unreleased`, если
    её нет: невышедшую не проверяет никто, и отставанием это не является.
    `released` не задан — все недостающие считаются вышедшими.
    """
    own = {label for label, _ in parts}

    def missing(label: str) -> str:
        return "unreleased" if released is not None and series(label) not in released else "absent"

    added = [(label, missing(label)) for label in steps if label not in own]
    return sorted([*parts, *added], key=lambda one: series(one[0]))


def by_version(labels: list[str], jobs: list[dict[str, Any]]) -> dict[str, str]:
    """Состояние каждой основной версии по её работам в решающем прогоне.

    Работа, в имени которой стоит подпись версии (`тесты на 3.15`), отвечает за
    эту версию; работа без версии в имени — за первую, то есть за планку.
    """
    total = {label: "none" for label in labels}
    for job in jobs:
        name = str(job.get("name") or "")
        target = next((label for label in labels[1:] if label in name), labels[0])
        said = outcome(job)
        if WEIGHT[said] >= WEIGHT[total[target]]:
            total[target] = said
    return total


#: Манифест сборок, из которого setup-python ставит интерпретатор. Версия,
#: которой в нём нет, не вышла вовсе: её тёмно-серый — «сборки ещё нет».
BUILDS_MANIFEST: Final = (
    "https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json"
)
#: Сколько прогонов спрашивается одной страницей.
LIMIT: Final = 30


def platform_builds() -> set[tuple[int, int]]:
    """Серии `X.Y`, у которых в манифесте setup-python есть хоть одна сборка."""
    try:
        manifest = json.loads(ghrest.raw_text(BUILDS_MANIFEST))
    except (ghrest.TransportError, ValueError) as exc:
        raise NoAnswer(f"манифест сборок {BUILDS_MANIFEST}: {exc}") from exc
    if not isinstance(manifest, list):
        raise NoAnswer(f"манифест сборок {BUILDS_MANIFEST}: не список")
    found = set()
    for entry in manifest:
        if isinstance(entry, dict) and (
            match := re.match(r"(\d+)\.(\d+)", str(entry.get("version", "")))
        ):
            found.add((int(match[1]), int(match[2])))
    return found


def _repo() -> tuple[str, str]:
    """Репозиторий и токен прогона: значок спрашивает площадку о своём проекте."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise NoAnswer("не задан GITHUB_REPOSITORY — чей проект спрашивать, неизвестно")
    return repo, ghrest.token_from_env()


def platform_runs(flow: str) -> list[dict[str, Any]]:
    """Завершённые прогоны файла на `main`, от новых; одна страница — предел `LIMIT`."""
    repo, token = _repo()
    path = (
        f"repos/{repo}/actions/workflows/{flow}/runs?branch=main&status=completed&per_page={LIMIT}"
    )
    try:
        said = ghrest.request("GET", path, token) or {}
    except ghrest.TransportError as exc:
        raise NoAnswer(str(exc)) from exc
    return list(said.get("workflow_runs") or [])


def platform_jobs(run_id: int) -> list[dict[str, Any]]:
    """Все работы прогона — постранично, до конца (212)."""
    repo, token = _repo()
    try:
        return list(ghrest.paginate(f"repos/{repo}/actions/runs/{run_id}/jobs", token, key="jobs"))
    except ghrest.TransportError as exc:
        raise NoAnswer(str(exc)) from exc


#: Поле части по каждую сторону надписи, как у shields: 5 px.
FIELD: Final = 5


def part_width(text: str) -> int:
    """Ширина части: надпись Verdana 11px по таблице знаков и поля (каталог #792)."""
    return round(text_width.width(text)) + 2 * FIELD


LABEL: Final = "#444d56"
BLUE: Final = "#0969da"
#: Пороги цвета покрытия, процент → имя цвета shields. Нижняя граница названа
#: явно: значок, зелёный при любом числе, перестают читать (каталог,
#: `coverage_badge.COLORS`; своего значка покрытия у механизмов нет).
COVERAGE_THRESHOLDS: Final = (
    (90, "brightgreen"),
    (75, "green"),
    (50, "yellow"),
    (25, "orange"),
    (0, "red"),
)
#: Имя цвета порога → цвет на картинке (контраст белого текста — в истории каталога).
COVERAGE_COLORS: Final[dict[str, str]] = {
    "brightgreen": "#1a7f37",
    "green": "#2da44e",
    "yellow": "#bf8700",
    "orange": "#bc4c00",
    "red": "#cf222e",
}
#: Зазор между зонами: внутри зоны части разделены тонкой линией, а зоны —
#: просветом, чтобы «проверки», «покрытие» и «выпуск» читались порознь.
GAP: Final = 4
#: Зоны картинки рядом с ней: `python.svg` → `python.zones.json`.
ZONES: Final = ".zones.json"


def coverage_color(percent: float) -> str:
    """Имя цвета порога, под который попадает процент покрытия."""
    return next(name for threshold, name in COVERAGE_THRESHOLDS if percent >= threshold)


def picture(zones: list[list[Part]], shift: int = 0, stretch: dict[int, int] | None = None) -> str:
    """Картинка из зон: каждая зона — скруглённая полоса своих частей.

    `shift` опускает полосу на столько точек вниз — так значок проекта кладёт
    вторую строку под первую без трансформаций: обрезки в сдвинутой группе
    Chromium толковал не в той системе координат (проба каталога 15.10). При
    нуле картинка та же байт в байт.

    `stretch` — сколько точек добавить зоне по её номеру, поровну на каждую её
    часть: так значок проекта ставит конец `rules` под конец ОС (владелец 16.10).
    """
    y = f' y="{shift}"' if shift else ""
    hint = "; ".join(f"{text}: {word}" for zone in zones for text, _, word in zone if word)
    # Имена обрезок уникальны для содержимого: две картинки на одной странице
    # (вставленные в HTML, а не через <img>) иначе делят id и режут друг друга.
    mark = hashlib.sha1(repr(zones).encode("utf-8")).hexdigest()[:8]
    x = 0
    clips, rects, borders, texts = [], [], [], []
    for number, zone in enumerate(zones):
        start = x
        share, rest = divmod((stretch or {}).get(number, 0), len(zone))
        for index, (text, color, _) in enumerate(zone):
            # Остаток — последним частям: сумма добавок равна растяжке зоны.
            w = part_width(text) + share + (1 if index >= len(zone) - rest else 0)
            rects.append(
                f'<rect x="{x}"{y} width="{w}" height="20" fill="{color}" '
                f'clip-path="url(#z{mark}{number})"/>'
            )
            if index:
                # Разделитель частей: при трёх зелёных цвет их не различает.
                borders.append(
                    f'<rect x="{x - 1}"{y} width="1" height="20" fill="#fff" fill-opacity=".7"/>'
                )
            middle = x + w / 2
            texts.append(
                f'<text x="{middle}" y="{15 + shift}" fill="#010101" fill-opacity=".3">'
                f"{escape(text)}</text>"
                f'<text x="{middle}" y="{14 + shift}">{escape(text)}</text>'
            )
            x += w
        clips.append(
            f'<clipPath id="z{mark}{number}"><rect{y} width="{x - start}" height="20" '
            f'rx="3" x="{start}"/></clipPath>'
        )
        x += GAP
    total = x - GAP
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{20 + shift}" '
        f'role="img" aria-label="{escape(hint)}">'
        f"<title>{escape(hint)}</title>{''.join(clips)}"
        f"<g>{''.join(rects)}{''.join(borders)}</g>"
        '<g fill="#fff" text-anchor="middle" '
        'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f"{''.join(texts)}</g></svg>\n"
    )


#: Сколько наборов умещается в значок, который ещё читается.
SUITES_AT_MOST: Final = 4


def ci_jobs(text: str, where: str = "файл CI") -> dict[str, str]:
    """Работы файла CI: ключ → имя, которым площадка называет работу.

    Тем же разбором YAML, что весь конвейер (`pipeline_checks.run_text`):
    комментарии, кавычки и порядок ключей решает разбор, а не отступы (каталог
    читал построчно и ловил хвостовой комментарий в имени, обзор #725). Имя —
    поле `name:` работы, а без него — сам ключ; у матрицы площадка дописывает
    «(значения)», это учитывает `by_suite`. Имя-выражение (`${{ … }}`) вернётся
    как есть, и сверка его отвергнет: предсказать его нечем.
    """
    jobs = pipeline_checks.run_text(text, where).get("jobs") or {}
    return {
        str(key): str((body or {}).get("name") or key) if isinstance(body, dict) else str(key)
        for key, body in (jobs.items() if isinstance(jobs, dict) else [])
    }


def suites(given: str) -> list[tuple[str, str]]:
    """`работа[:подпись],…` → [(работа, подпись)]; без подписи — имя работы."""
    found = []
    for piece in given.split(","):
        if not piece.strip():
            continue
        job, _, label = piece.strip().partition(":")
        found.append((job.strip(), label.strip() or job.strip()))
    return found


def check_suites(asked: list[tuple[str, str]], jobs: dict[str, str]) -> str | None:
    """Что не так с наборами; None — все работы есть в файле CI и их не больше предела."""
    if len(asked) > SUITES_AT_MOST:
        return (
            f"наборов {len(asked)}, а значок читается с {SUITES_AT_MOST} — "
            "отбор наборов решает проект"
        )
    for job, _ in asked:
        if job not in jobs:
            return (
                f"работы «{job}» в файле CI нет (есть: {', '.join(sorted(jobs))}) — "
                "переименованная работа посерела бы молча (005)"
            )
        if "${{" in jobs[job]:
            return f"у работы «{job}» имя задано выражением ({jobs[job]}) — сверять исход не с чем"
    return None


def by_suite(
    asked: list[tuple[str, str]], jobs: dict[str, str], ran: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """(подпись, состояние) каждого набора по работам решающего прогона.

    Работа матрицей у площадки — «имя (значения)»; совпадают и она, и точное
    имя. Имя другой работы файла — не матрица этой: `e2e (smoke)` как отдельная
    работа иначе читалась бы ячейкой матрицы `e2e` (каталог, обзор #725).
    """
    others = set(jobs.values())
    total = []
    for job, label in asked:
        name = jobs[job]
        said = "none"
        for one in ran:
            title = str(one.get("name") or "")
            if title != name and (not title.startswith(name + " (") or title in others):
                continue
            if WEIGHT[outcome(one)] > WEIGHT[said]:
                said = outcome(one)
        total.append((label, said))
    return total


def suites_zone(states: list[tuple[str, str]]) -> list[Part]:
    """Части наборов; без наборов — зоны нет вовсе, а не серая пустышка."""
    return [(label, STATES[said][0], STATES[said][1]) for label, said in states]


#: Подпись всей картинки — серой частью в начале первой зоны (каталог #719).
PREFIX: Final = "CI"


def checks_zones(parts: list[tuple[str, str]], overall: str) -> list[list[Part]]:
    """Зона «CI Python и версии» и зона ОС; «CI» — серой частью первой зоны."""

    def part(label: str, said: str) -> Part:
        return (label, STATES[said][0], STATES[said][1])

    pythons = [part(label, said) for label, said in parts if label not in SYSTEMS.values()]
    systems = [part(label, said) for label, said in parts if label in SYSTEMS.values()]
    zones = [[(PREFIX, LABEL, ""), part("Python", overall), *pythons]]
    if systems:
        zones.append(systems)
    return zones


# ── зоны выпуска: покрытие, релиз / PyPI, версия ───────────────────────────


def from_badge(path: Path | None) -> str | None:
    """`message` из файла значка shields (endpoint): None — вход не задан.

    ЗАДАННЫЙ, НО ОТСУТСТВУЮЩИЙ ИЛИ БИТЫЙ файл — не «не измерено», а «не
    прочитали»: упал шаг, который его пишет. Серым это не рисуется — третий
    исход, и на ветке остаётся прежний значок (039).
    """
    if path is None:
        return None
    try:
        message = str(json.loads(path.read_text(encoding="utf-8")).get("message") or "")
    except (OSError, ValueError, AttributeError) as exc:
        raise NoAnswer(f"файл значка {path} не прочитан — {exc}") from exc
    if not message.strip():
        raise NoAnswer(f"в файле значка {path} пустой message — ответа нет")
    return message


def _percent(message: str | None) -> str | None:
    found = re.match(r"\s*(\d+(?:\.\d+)?)", message or "")
    return found.group(1) if found else None


def coverage_zone(message: str | None, everywhere: str | None = None) -> list[Part]:
    """Покрытие основного замера и — если проект его отдаёт — по всем ОС (`72% / 85%`).

    Цвет — по основному замеру: он и есть обещание проекта.
    """
    main_one = _percent(message)
    if main_one is None:
        return [("coverage", LABEL, ""), ("—", STATES["none"][0], "покрытие не измерено")]
    color = COVERAGE_COLORS[coverage_color(float(main_one))]
    every = _percent(everywhere)
    if every is None or every == main_one:
        return [("coverage", LABEL, ""), (f"{main_one}%", color, f"покрытие {main_one}%")]
    return [
        ("coverage / all (os)", LABEL, ""),
        (f"{main_one}% / {every}%", color, f"покрытие {main_one}%, по всем ОС {every}%"),
    ]


def version_zone(said: str | None) -> list[Part]:
    """Версия последней, синим: счётчик, а не проверка."""
    if not said:
        return [("version", LABEL, ""), ("—", STATES["none"][0], "версия не собрана")]
    return [("version", LABEL, ""), (said, BLUE, f"версия {said}")]


def short(said: str) -> str:
    """`v1.5.0` → `1.5`: на значке хватает старших двух чисел."""
    found = re.match(r"v?(\d+)\.(\d+)", said)
    return f"{found.group(1)}.{found.group(2)}" if found else said.lstrip("v")


def release_zone(release: str | None, pypi: str | None, declared: bool) -> list[Part]:
    """«release / PyPI»: зелёный — совпадают, красный — расходятся, серый — PyPI нет.

    Сравниваются те же два числа, что на значке: третье — счётчик версии, не
    выпуска (решение владельца 01.10), и красного над `2.8 / 2.8` не бывает.
    """
    grey = STATES["none"][0]
    label = ("release / PyPI", LABEL, "")
    if release is None:
        return [label, ("—", grey, "выпусков нет")]
    if not declared:
        return [label, (short(release), grey, f"выпуск {release}, на PyPI не публикуется")]
    if pypi is not None and short(release) == short(pypi):
        return [label, (short(release), STATES["pass"][0], f"выпуск {release} совпадает с PyPI")]
    there = short(pypi) if pypi else "—"
    return [
        label,
        (
            f"{short(release)} / {there}",
            STATES["fail"][0],
            f"выпуск {release}, на PyPI {pypi or 'пакета нет'}",
        ),
    ]


def platform_release() -> str | None:
    """Старший выпуск ПРОЕКТА — тег `vX.Y.Z`; None — таких выпусков нет.

    НЕ `releases/latest`: «последний» у площадки — самая свежая страница
    выпуска, чей бы тег она ни несла (каталог 15.10: договор фактов
    `facts-v2.0.0` встал вместо `v1.13.0`). Выпуском считается только тег
    `version.is_release_tag`; список читается до конца (212), черновики и
    предварительные выпуски не в счёт.
    """
    repo, token = _repo()
    try:
        pages = list(ghrest.paginate(f"repos/{repo}/releases", token))
    except ghrest.TransportError as exc:
        raise NoAnswer(str(exc)) from exc
    return newest_release(
        str(one.get("tag_name") or "")
        for one in pages
        if not one.get("draft") and not one.get("prerelease")
    )


def newest_release(tags: Any) -> str | None:
    """Старший тег выпуска проекта из списка тегов: числом, а не строкой."""
    own = [tag for tag in tags if version.is_release_tag(tag)]
    return max(own, key=lambda tag: version.digits(version.bare(tag))) if own else None


def pypi_version(package: str) -> str | None:
    """Последняя версия пакета на PyPI; None — пакета там нет.

    «Пакета нет» узнаётся по КОДУ ответа (404 у `HTTPError`), а не подстрокой
    «404», которая встретилась бы и в порте, и в адресе (каталог, обзор #653).
    """
    try:
        data = json.loads(ghrest.raw_text(f"https://pypi.org/pypi/{package}/json"))
    except ghrest.TransportError as exc:
        cause = exc.__cause__
        if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
            return None
        raise NoAnswer(f"PyPI: {exc}") from exc
    except ValueError as exc:
        raise NoAnswer(f"PyPI: ответ не разбирается — {exc}") from exc
    return str(((data or {}).get("info") or {}).get("version") or "") or None


def main(
    argv: list[str] | None = None,
    runs: Runs = platform_runs,
    jobs: Jobs = platform_jobs,
    builds: Builds | None = None,
    release: Callable[[], str | None] | None = None,
    pypi: Callable[[str], str | None] | None = None,
) -> int:
    """Точка входа: собирает значок и его зоны или называет, почему не собран."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--ci", default=CI, help="файл основного CI в .github/workflows")
    parser.add_argument(
        "--coverage-json", type=Path, help="файл значка покрытия (shields endpoint)"
    )
    parser.add_argument(
        "--coverage-all-json",
        type=Path,
        help="файл значка покрытия, сведённого по всем ОС; есть — в зоне покрытия второе число",
    )
    parser.add_argument("--version-json", type=Path, help="файл значка версии (shields endpoint)")
    parser.add_argument(
        "--suites",
        default="",
        help="наборы проверок основного CI: работа[:подпись],… — работы сверяются с файлом CI",
    )
    parser.add_argument("--pypi", default="", help="имя пакета на PyPI; пусто — не публикуется")
    args = parser.parse_args(argv)

    try:
        pairs = versions(args.root, args.ci)
    except pipeline_checks.BadPolicy as exc:
        print(f"значок не собран: прогон не разобран — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not pairs:
        print(
            f"значок не собран: в {args.root}/.github/workflows нет ни {args.ci} с "
            "python-version, ни предварительного прогона — подписывать нечего (075)",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    if args.ci not in {flow for _, flow in pairs}:
        # Без основного CI «Python» и ОС красить нечем: серый сказал бы «не
        # проводилась» о прогоне, которого не спрашивали (039).
        print(
            f"значок не собран: у {args.ci} не нашлось версии — ни python-version "
            "числом, ни requires-python в pyproject.toml. «Python» и ОС красятся "
            "основным CI, и без него значок врал бы серым (039)",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    asked = suites(args.suites)
    ci_file = args.root / python_versions.WORKFLOWS / args.ci
    try:
        file_jobs = ci_jobs(ci_file.read_text(encoding="utf-8"), str(ci_file)) if asked else {}
    except pipeline_checks.BadPolicy as exc:
        print(f"значок не собран: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if asked and (why := check_suites(asked, file_jobs)):
        print(f"значок не собран: {why}. Серым это не рисуется (039)", file=sys.stderr)
        return EXIT_BROKEN
    parts: list[tuple[str, str]] = []
    systems = by_system([])
    suite_states = [(label, "none") for _, label in asked]
    overall = "none"
    main_ones = [label for label, flow in pairs if flow == args.ci]
    per_version: dict[str, str] = {}
    read: dict[str, list[dict[str, Any]]] = {}
    released: set[tuple[int, int]] | None = None
    for label, flow in pairs:
        try:
            if flow not in read:
                got = runs(flow)
                if deciding(got) is None and len(got) >= LIMIT:
                    # Страница полна, а вердикта на ней нет: за краем он может
                    # быть. Серый здесь сказал бы «не проводилась» о том, чего
                    # не спросили (039, каталог, обзор #649).
                    raise NoAnswer(
                        f"в последних {LIMIT} прогонах нет вердикта, а глубже не спрашивали"
                    )
                read[flow] = got
                if flow == args.ci:
                    overall = state(got)
                    run = deciding(got)
                    if run is not None:
                        ran = jobs(int(run["id"]))
                        systems = by_system(ran)
                        suite_states = by_suite(asked, file_jobs, ran)
                        if len(main_ones) > 1:
                            per_version = by_version(main_ones, ran)
            got = read[flow]
            if flow == args.ci:
                parts.append((label, per_version.get(label, state(got))))
                continue
            if released is None:
                released = (builds or platform_builds)()
            parts.append((label, state(got) if series(label) in released else "unreleased"))
        except (NoAnswer, ValueError, KeyError) as exc:
            print(
                f"значок не собран: прогоны {flow} у площадки не прочитаны — {exc}. Серым "
                "это не рисуется: «не спросили» не значит «не проводилась» (039)",
                file=sys.stderr,
            )
            return EXIT_BROKEN
    # Своими `pairs` лесенка берётся, только когда они и есть `versions()` дерева
    # механизмов: то же дерево И тот же основной CI. С другим `--ci` у того же
    # дерева `pairs` — версии чужого прогона, и недостающие ступени семьи
    # пропали бы с картинки (взгляд на #1565, сосед «тот же каталог»).
    same = mechanisms_tree().resolve() == args.root.resolve() and args.ci == CI
    steps = ladder(pairs if same else None)
    if released is None and set(steps) - {label for label, _ in parts}:
        try:
            released = (builds or platform_builds)()
        except NoAnswer as exc:
            print(f"значок не собран: {exc}. Серым это не рисуется (039)", file=sys.stderr)
            return EXIT_BROKEN
    parts = on_ladder(parts, steps, released) + systems
    try:
        tag = (release or platform_release)()
        on_pypi = (pypi or pypi_version)(args.pypi) if args.pypi and tag else None
        coverage = from_badge(args.coverage_json)
        coverage_all = from_badge(args.coverage_all_json)
        own_version = from_badge(args.version_json)
        for path, message in (
            (args.coverage_json, coverage),
            (args.coverage_all_json, coverage_all),
        ):
            if message is not None and _percent(message) is None:
                # «n/a» или «unknown» — замер не дал числа; серый сказал бы «не
                # измерено» о том, что измерить пытались (039).
                raise NoAnswer(f"в файле значка {path} нет числа покрытия — «{message}»")
    except NoAnswer as exc:
        print(f"значок не собран: {exc}. Серым это не рисуется (039)", file=sys.stderr)
        return EXIT_BROKEN
    zones = checks_zones(parts, overall)
    if suite_states:
        # Порядок зон — решение владельца: проверки, ОС, наборы (каталог #719),
        # покрытие, выпуск, версия последней.
        zones.append(suites_zone(suite_states))
    zones += [
        coverage_zone(coverage, coverage_all),
        release_zone(tag, on_pypi, bool(args.pypi)),
        version_zone(own_version),
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(picture(zones), encoding="utf-8")
    # Зоны рядом с картинкой: значок проекта рисует эту строку заново в общей
    # сетке со второй, не спрашивая площадку второй раз.
    args.out.with_name(args.out.stem + ZONES).write_text(
        json.dumps(zones, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        "значок: "
        + "; ".join(f"{text} — {word}" for zone in zones for text, _, word in zone if word)
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
