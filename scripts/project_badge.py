#!/usr/bin/env python3
"""Единый значок проекта в две строки: состояние сверху, правила и семья снизу.

ПЕРЕЕХАЛО ИЗ КАТАЛОГА (#1563, этап 3 ArtVsMark/Engineering-Incidents-Playbook#930).
Одна картинка вместо трёх (каталог, решение владельца 14.10). Код рисунка — у
механизмов, данные — у проекта: действие запускается в его репозитории, на его
дереве, и картинку публикует сам проект на своей ветке `badges`.

ЧТО В СТРОКАХ.
  строка 1 — зоны `python.svg`, которые тем же прогоном нарисовал
             `python_badge.py` и положил рядом в `python.zones.json`;
  строка 2 — `rules │ machine N/M · P% │ own │ taken` по ответу проекта
             каталогу `.rules/bindings.json` и `family │ сегменты`, `EIP · EPM`
             по разбору `family-check.json` от `family_check.py`.

ОПОРЫ СВОИ. Знаменатель — действующие правила выгрузки каталога, и читает их
общий `catalogue.active_rules` (тот же разбор статуса, что у замен в дрейфе).
У каталога выгрузка лежала в дереве действия; у механизмов её нет, и она
читается по адресу `catalogue.EXPORT_URL`. «Машиной» — механизмы
`kinds.MACHINE`, тот же набор, что считает факты проекта: у каталога это было
`gate` и `pipeline`, у нас ещё и `code`, и число на значке сходится с
фактами, а не с прежним рисовальщиком. «Взяты» — машинные с `origin_kind`
`called`, `copied` или `adapted`.

ОДНА ГРАНИЦА, ДАЛЬШЕ СВОБОДНО (каталог, владелец 16.10). Зона `rules`
кончается там же, где зона ОС первой строки; короткая сторона добирает разницу
поровну на все свои части. Ширины — общей `python_badge.part_width` (214).

ВТОРОГО РИСОВАЛЬЩИКА НЕТ (214). Обе строки рисует `python_badge.picture`,
вторая — со сдвигом вниз, а не трансформацией: вложенные `<svg>` и группа с
`transform` резали вторую строку в Chromium (каталог, проба 15.10). Зоны
семьи берутся у `family_check.zones`.

НЕТ ДАННЫХ — СЕРАЯ ЧАСТЬ С ПРИЧИНОЙ, А НЕ БИТАЯ КАРТИНКА (039).

Исходы:
  0 — значок собран из всех частей;
  2 — значок не собран: не записан файл;
  3 — значок собран, но часть данных не прочитана: серое с причиной названо.
Код 1 — трасса интерпретатора, а не исход: шаг фактов и действие значка его
не публикуют.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import catalogue
import family_check
import ghrest
import kinds
import main_guard
import paths
import pipeline_checks as policy
import python_badge

EXIT_OK: Final = 0
#: Серое — ТРИ, а не один (взгляд на #1576): Python сам выходит кодом 1 на любой
#: непойманной трассе, и при «сером» на единице шаг публиковал бы значок, которого
#: трасса не нарисовала (039).
EXIT_GREY: Final = 3
EXIT_BROKEN: Final = 2

#: Дерево проекта — рабочий каталог, как у прочих механизмов (096).
ROOT: Final = Path()
OUT: Final = paths.BADGES_DIR / "project.svg"
ANSWER: Final = paths.BINDINGS
#: Вид происхождения, который значит «механизм взят у другого проекта».
TAKEN: Final = frozenset({"called", "copied", "adapted"})
#: Высота строки и просвет между строками — тот же, что между зонами.
ROW: Final = 20
SPACE: Final = python_badge.GAP
#: Серый «не знаю» — тот же, что у семейного значка.
GREY: Final = family_check.COLOR["unknown"]
#: Зона первой строки, под концом которой кончается `rules`: ОС, вторая по
#: порядку у `python_badge.checks_zones` (CI │ Python, затем linux windows mac).
OS_ZONE: Final = 1

Zones = list[list[python_badge.Part]]


def share(n: int, m: int) -> str:
    """«n/m · p%», а без знаменателя «n/m · —»: процент о пустом утверждал бы неизвестное."""
    return f"{n}/{m} · {round(100 * n / m)}%" if m else f"{n}/{m} · —"


def share_color(n: int, m: int) -> str:
    """Красный ниже трети, жёлтый ниже двух третей, иначе зелёный; без знаменателя — серый."""
    if not m:
        return GREY
    part = n / m
    if part < 0.34:
        return "#cf222e"
    if part < 0.67:
        return "#bf8700"
    return python_badge.COVERAGE_COLORS["green"]


def grey(label: str, why: str) -> Zones:
    """Зона «не прочитано»: подпись и серая часть с причиной в подсказке."""
    return [[(label, python_badge.LABEL, ""), ("n/a", GREY, why)]]


def rules_zones(
    answer: object, active: set[str] | None, where: Path | str = ANSWER
) -> tuple[Zones, str]:
    """Зона «rules»: сколько действующих правил держится механизмом, из них свои и взятые.

    `active` None — выгрузка не прочитана, и зона серая с причиной. `where` —
    адрес, по которому ответ читался (таблица путей, #1632), а не умолчание.
    """
    rules = answer.get("rules") if isinstance(answer, dict) else None
    if not isinstance(rules, dict):
        why = f"ответа каталогу {where} нет или он не той формы"
        return grey("rules", why), why
    if active is None:
        why = "выгрузка каталога не прочитана — действующих не отличить"
        return grey("rules", why), why
    alive = [one for number, one in rules.items() if isinstance(one, dict) and number in active]
    machine = [one for one in alive if one.get("mechanism") in kinds.MACHINE]
    taken = sum(1 for one in machine if one.get("origin_kind") in TAKEN)
    return [
        [
            ("rules", python_badge.LABEL, ""),
            (
                f"machine {share(len(machine), len(alive))}",
                share_color(len(machine), len(alive)),
                "правил каталога держится механизмом",
            ),
            (f"own {len(machine) - taken}", python_badge.BLUE, "механизм свой"),
            (f"taken {taken}", python_badge.BLUE, "механизм взят у другого проекта"),
        ]
    ], ""


def family_zones(path: Path) -> tuple[Zones, str]:
    """Зоны семьи без просвета между подписью и сегментами (каталог, владелец 15.10)."""
    try:
        label, segments, *tail = family_check.zones(json.loads(path.read_text(encoding="utf-8")))
        return [label + segments, *tail], ""
    except (OSError, ValueError, KeyError, TypeError) as exc:
        why = f"разбор семьи {path.name} не прочитан: {exc}"
        return grey("family", why), why


def state_zones(path: Path) -> tuple[Zones, str]:
    """Зоны первой строки из `python.zones.json`, положенного `python_badge.py`."""
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
        if not (
            isinstance(said, list)
            and said
            and all(
                isinstance(zone, list)
                and zone
                and all(
                    isinstance(part, list)
                    and len(part) == 3
                    and all(isinstance(piece, str) for piece in part)
                    for part in zone
                )
                for zone in said
            )
        ):
            raise ValueError("не список зон")
        return [[(part[0], part[1], part[2]) for part in zone] for zone in said], ""
    except (OSError, ValueError) as exc:
        why = f"зоны строки состояния {path.name} не прочитаны: {exc}"
        return grey("CI", why), why


def widths(zones: Zones) -> list[int]:
    """Ширина каждой зоны без добавок — общей функцией ширины части."""
    return [sum(python_badge.part_width(text) for text, _, _ in zone) for zone in zones]


def align(top: Zones, bottom: Zones) -> tuple[dict[int, int], dict[int, int]]:
    """Растяжки зон: конец первой зоны второй строки — под концом ОС первой."""
    if len(top) <= OS_ZONE or not bottom:
        return {}, {}
    upper, lower = widths(top), widths(bottom)
    os_end = sum(upper[: OS_ZONE + 1]) + OS_ZONE * python_badge.GAP
    if lower[0] < os_end:
        return {}, {0: os_end - lower[0]}
    if lower[0] > os_end:
        return {OS_ZONE: lower[0] - os_end}, {}
    return {}, {}


def active_of(fetch: Callable[[str], dict[str, Any]]) -> set[str] | None:
    """Действующие правила выгрузки каталога; None — не прочитана или не той формы."""
    try:
        return catalogue.active_rules(fetch(catalogue.EXPORT_URL))
    except ghrest.TransportError, catalogue.BadExport:
        return None


def build(
    root: Path,
    python_zones: Path,
    family_json: Path,
    fetch: Callable[[str], dict[str, Any]] = ghrest.raw_json,
) -> tuple[str, list[str]]:
    """Картинка в две строки и причины серого."""
    top, why_top = state_zones(python_zones)
    # Битая таблица путей — серое С ЕЁ причиной, а не «ответа нет»: `BadPaths`
    # наследует `ValueError` и иначе растворился бы в отказе чтения (взгляд на
    # #1633, 045).
    try:
        where: Path | str = policy.project_path("bindings", root)
    except paths.BadPaths as exc:
        where = f"(таблица путей не разобрана: {exc})"
        answer: object = None
    else:
        try:
            answer = json.loads((root / where).read_text(encoding="utf-8"))
        except OSError, ValueError:
            answer = None
    rules, why_rules = rules_zones(answer, active_of(fetch), where)
    family, why_family = family_zones(family_json)
    bottom = rules + family
    stretch_top, stretch_bottom = align(top, bottom)
    bodies, hints = [], []
    for zones, shift, stretch in ((top, 0, stretch_top), (bottom, ROW + SPACE, stretch_bottom)):
        svg = python_badge.picture(zones, shift, stretch)
        bodies.append(svg[svg.find("</title>") + len("</title>") : svg.rfind("</svg>")])
        hints.append(svg[svg.find("<title>") + len("<title>") : svg.find("</title>")])
    width = max(
        sum(widths(zones)) + sum(stretch.values()) + (len(zones) - 1) * python_badge.GAP
        for zones, stretch in ((top, stretch_top), (bottom, stretch_bottom))
    )
    hint = "; ".join(hints)
    # Подсказки уже экранированы для текста; в атрибуте нужна ещё кавычка.
    attribute = hint.replace('"', "&quot;")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{2 * ROW + SPACE}" role="img" aria-label="{attribute}">'
        f"<title>{hint}</title>{bodies[0]}{bodies[1]}</svg>\n"
    )
    return svg, [one for one in (why_top, why_rules, why_family) if one]


#: Файлы частей в папке значков: картинка Python, её зоны, семейная и разбор.
PYTHON_SVG: Final = "python.svg"
FAMILY_SVG: Final = "family.svg"


def draw_parts(
    root: Path,
    folder: Path,
    python_argv: list[str],
    family_argv: list[str],
) -> tuple[int, int]:
    """Нарисовать части значка проекта в `folder`: (исход Python, исход семьи).

    ОДНА СКЛЕЙКА НА ДВУХ ЗОВУЩИХ. Действие `project-badge` и общий шаг фактов
    рисуют одно и то же; держи каждый свою оболочечную склейку из трёх вызовов,
    две копии разошлись бы на первой правке (071). Поэтому части рисуются
    здесь, тем же процессом, а зовущие передают только свои входы.
    """
    python_rc = python_badge.main(
        ["--root", str(root), "--out", str(folder / PYTHON_SVG), *python_argv]
    )
    family_rc = family_check.main(
        ["--root", str(root), "--out", str(folder / FAMILY_SVG), *family_argv]
    )
    return python_rc, family_rc


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собрать единый значок и назвать серое.

    С `--parts` сперва рисуются части — значок Python и семейный — в папку
    `--out`, и склейка берёт их оттуда; без него склеиваются готовые
    `--python-zones` и `--family-json`.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--python-zones", type=Path, help="зоны строки состояния")
    parser.add_argument("--family-json", type=Path, help="разбор семьи family-check.json")
    parser.add_argument(
        "--parts",
        action="store_true",
        help="сперва нарисовать части (python.svg, family.svg) в папку --out",
    )
    parser.add_argument("--repo", default="", help="владелец/имя проекта для сверки семьи")
    parser.add_argument("--family", default="", help="адрес или путь сводки семьи")
    args, python_argv = parser.parse_known_args(argv)
    folder = args.out.parent
    rcs = (EXIT_OK, EXIT_OK)
    if args.parts:
        family_argv = [*(["--repo", args.repo] if args.repo else [])]
        family_argv += ["--family", args.family] if args.family else []
        folder.mkdir(parents=True, exist_ok=True)
        rcs = draw_parts(args.root, folder, python_argv, family_argv)
        zones = folder / f"{Path(PYTHON_SVG).stem}{python_badge.ZONES}"
        family = folder / family_check.VERDICT.name
    elif python_argv:
        parser.error(f"неизвестные доводы без --parts: {' '.join(python_argv)}")
    elif args.python_zones is None or args.family_json is None:
        parser.error("без --parts нужны --python-zones и --family-json")
    else:
        zones, family = args.python_zones, args.family_json
    svg, greys = build(args.root, zones, family)
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(svg, encoding="utf-8")
    except OSError as exc:
        print(f"значок не собран: {args.out} не записан — {exc.strerror}", file=sys.stderr)
        return EXIT_BROKEN
    for one in greys:
        print(f"серое: {one}", file=sys.stderr)
    tail = f", серых частей {len(greys)}" if greys else ""
    print(f"единый значок записан: {args.out}{tail}")
    if EXIT_BROKEN in rcs:
        print(
            f"значок проекта не собран целиком: python {rcs[0]}, family {rcs[1]}", file=sys.stderr
        )
        return EXIT_BROKEN
    return EXIT_GREY if greys else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
