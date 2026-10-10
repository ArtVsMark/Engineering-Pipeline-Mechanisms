#!/usr/bin/env python3
"""Общие факты семьи: то, что из любого дерева выводится одинаково (#1001, шаг 2).

РЕШЕНИЕ ВЛАДЕЛЬЦА 04.10 и 06.10.2026. Генератор `facts.json` был у каждого из
пяти проектов свой, и они разъехались — 20 расхождений с договором витрины
(замер 01.10.2026). Издатель теперь один: общий шаг `step-facts.yml` зовёт этот
модуль, проект отдаёт ему свои числа файлом `extra-facts`, а публикует шаг.
Общая утилита поднимается выше подсистем, а не копируется вбок
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ОБЩЕЕ — ТО, ЧТО ВЫВОДИТСЯ ИЗ ДЕРЕВА БЕЗ ЗНАНИЯ ПРОЕКТА: версия формата, о ком
файл, когда и на каком коммите собран, прогон CI, версии Python из матрицы,
версия головы и выпуск по тегам, доля покрытия из отчёта прогона, счёт ответа
каталогу `.rules/bindings.json` (#1282: у потребителя исполняется только этот
модуль, и «держится машиной» иначе посчитать было бы нечем). Наш
`build_facts.py` берёт эти значения ОТСЮДА, а не считает второй раз (022):
значения у нас при выносе не изменились.

ЗНАЧЕНИЕ ИЛИ ПРИЧИНА, ТРЕТЬЕГО НЕТ (договор фактов с 1.2). Показатель договора,
который ни общая часть, ни проект не дали, уходит причиной в `none` с именем
того, кто должен был его дать, — а не пропадает молча.

СВОЁ ПРОЕКТА НЕ ПЕРЕКРЫВАЕТ ОБЩЕГО. Ключ `extra-facts`, совпавший с общим, —
отказ, а не перезапись: иначе проект вернул бы себе свой генератор того же
числа, и разнобой, от которого издатель заведён, вернулся бы молча (045).

Исходы (правило 039): ``0`` собрано · ``2`` не собрать: вход не прочитан,
прогона CI нет, свой ключ перекрывает общий.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import kinds
import paths
import pipeline_checks as policy
import version

#: Версия формата — СТРОКОЙ, как требует контракт: число не различает `1.0` и
#: `1.10`. Мажор — контракта семьи, а не наш.
SCHEMA: Final = "1.3"
SCHEMA_OF: Final = (
    "контракт фактов витрины семьи: "
    "https://github.com/ArtVsMark/ArtVsMark/blob/main/.rules/facts-contract.md"
)
#: Показатели договора, у которых обязано быть значение или причина в `none`:
#: ключи `none` схема витрины перечисляет закрытым списком, и это он.
CONTRACT_METRICS: Final = (
    "version",
    "release",
    "coverage_percent",
    "tests",
    "python",
    "checks_per_pr",
)
#: Ключи, которые даёт общая часть: свой файл проекта их не перекрывает.
COMMON_KEYS: Final = frozenset(
    {
        "schema",
        "schema_of",
        "repo",
        "generated_at",
        "commit",
        "ci",
        "python",
        "version",
        "version_whole",
        "release",
        "coverage",
        "coverage_percent",
        "rules",
    }
)
#: Поставщик не назван — машинные ответы по происхождению не разделить:
#: взятое у него от взятого у других не отличить, и «свои/взяты» были бы ложью.
NO_SUPPLIER: Final = "поставщик механизмов не назван (--supplier) — «свои/взяты» не разделить"
#: Список разрешённого (068): статус, которого здесь нет, — это дефект ответа,
#: а не новая тонкость, о которой механизм обязан догадаться.
STATUSES: Final = ("active", "rejected", "not-applicable", "unreviewed")
#: `origin_kind`, которого ответ не назвал: форма до 1.9 его не требовала.
UNNAMED_KIND: Final = "не названо"
#: Причина для показателя, которого никто не дал: названо, кто должен был.
NOT_GIVEN: Final = "проект не отдал показатель во входе extra-facts общего шага step-facts"
NO_MATRIX: Final = "матрица версий Python не названа входом шага — версии не названы, а не пусты"
#: Матрица названа, но не прочитана: причина для читателя витрины, а не трасса.
UNREAD_MATRIX: Final = "матрица версий Python в {} не прочитана — версии не названы, а не пусты"
NO_VERSION: Final = "версия не выводится: в дереве нет ни тега выпуска, ни объявленной версии"

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Сборка не отработала: третий исход, а не пустые факты."""


def release_series(tag: str | None) -> str:
    """Выпуск в форме договора фактов 1.3 — серия `X.Y`, а не тег; выпуска нет — пусто.

    РЕШЕНИЕ ВЛАДЕЛЬЦА 02.10.2026 (#1046, договор фактов 1.3). Третья цифра
    тега выпуска всегда 0 и смысла не несёт, буква `v` — запись тега, а не
    выпуска. Версия головы (`version`, `X.Y.Z`) начинается с серии и точки —
    это сверяет витрина. Разбор — `version.digits`, а не нарезка по точке (214).
    """
    if not tag:
        return ""
    major, minor, _ = version.digits(version.bare(tag))
    return f"{major}.{minor}"


def coverage_facts(path: Path | None) -> dict[str, Any]:
    """Покрытие строк из отчёта счётчика; без отчёта — «не прочитано».

    ЧИСЛО ПРИХОДИТ ИЗ ПРОГОНА, А НЕ СЧИТАЕТСЯ ЗДЕСЬ: покрытие — про исполнение,
    а не про текст. Отчёта нет — так и говорится; ноль вместо незнания читался
    бы как «ничего не покрыто» (045).

    ДОЛЯ ЕДЕТ ВМЕСТЕ С ДВУМЯ ЧИСЛАМИ, ИЗ КОТОРЫХ СДЕЛАНА
    ([041](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/041-two-honest-numbers-beat-one-averaged.md)):
    та же доля у дерева в сто строк и в десять тысяч значит разное. Отчёт без
    этих чисел — отказ: форма чужого отчёта изменилась (045).
    """
    if path is None or not path.is_file():
        return {"read": False}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise NotRun(f"отчёт покрытия не разобрался: {exc}") from exc
    totals = report.get("totals") or {}
    percent = totals.get("percent_covered")
    if percent is None:
        raise NotRun(f"{path}: в отчёте нет доли покрытия — форма ответа изменилась")
    covered, lines = totals.get("covered_lines"), totals.get("num_statements")
    if covered is None or lines is None:
        raise NotRun(
            f"{path}: в отчёте нет чисел, из которых сделана доля — форма ответа изменилась"
        )
    return {
        "read": True,
        "percent": round(float(percent), 1),
        "covered": int(covered),
        "lines": int(lines),
    }


def contract_coverage(said: dict[str, Any]) -> dict[str, Any]:
    """Покрытие в форме контракта: доля — наверху, слагаемые — в `coverage`.

    Не прочитано — ключа `coverage_percent` нет вовсе, а причина стоит в
    `none.coverage_percent` (договор фактов с 1.2, #1001): ноль читался бы как
    ответ.
    """
    parts = {key: value for key, value in said.items() if key != "percent"}
    if not said.get("read"):
        why = "отчёт покрытия этого прогона не прочитан — доля не мерилась, а не равна нулю"
        return {"coverage": parts, "none": {"coverage_percent": why}}
    return {"coverage": parts, "coverage_percent": said["percent"]}


def python_facts(
    flow: Path, job: str, next_flow: Path | None = None, next_job: str = ""
) -> dict[str, list[str]]:
    """Версии Python из матрицы CI, а не по памяти; пробные — своей матрицей рядом (#1018).

    Матрица называется входом: имена джобов у проектов разные, и угадывать их
    значило бы назвать версии чужого джоба. Матрицу читает `pipeline_checks` —
    читатель прогонов один; не прочитано — `policy.BadPolicy` с причиной.
    """
    supported, first = policy.matrix_axis(flow, job, "python")
    images = {first}
    said: dict[str, list[str]] = {"supported": supported}
    if next_flow is not None and next_job:
        later, second = policy.matrix_axis(next_flow, next_job, "python")
        said["experimental"] = later
        images.add(second)
    said["os"] = sorted(images)
    return said


def matrix_at(root: Path, said: str) -> tuple[Path, str]:
    """Матрица, названная `<файл прогона>:<джоб>`, — путь прогона и джоб."""
    flow, _, job = said.partition(":")
    if not flow or not job:
        raise NotRun(f"матрица названа «{said}», а не «<файл прогона>:<джоб>»")
    return root / paths.WORKFLOWS / flow, job


def ci_facts(
    root: Path, ci_workflow: str, python_matrix: str = "", python_next: str = ""
) -> tuple[dict[str, Any], dict[str, str]]:
    """Разделы `ci` и `python` договора — и причины в `none` для непрочитанного.

    `ci` договор требует всегда, а в `none` его не положить: прогона, которого
    нет в дереве, файл фактов не называет, и сборка отказывает (045). Матрица
    не названа или не прочитана — раздела `python` нет, причина для читателя
    витрины стоит в `none.python`, подробность — в поток диагностики
    (взгляд на #1004).
    """
    if not (root / paths.WORKFLOWS / ci_workflow).is_file():
        raise NotRun(
            f"нет прогона CI {paths.WORKFLOWS / ci_workflow}: договор фактов требует "
            "ci.workflow, а назвать нечего"
        )
    run: dict[str, Any] = {"ci": {"workflow": ci_workflow}}
    if not python_matrix:
        return run, {"python": NO_MATRIX}
    flow, job = matrix_at(root, python_matrix)
    later, later_job = matrix_at(root, python_next) if python_next else (None, "")
    try:
        run["python"] = python_facts(flow, job, later, later_job)
    except policy.BadPolicy as exc:
        print(f"warning: {exc}", file=sys.stderr)
        return run, {"python": UNREAD_MATRIX.format(flow.name)}
    return run, {}


def taken_from(origin: str, supplier: str) -> bool:
    """`origin` формы `<владелец>/<репозиторий>:<путь>@<версия>` ведёт к поставщику.

    Регистр имени площадка не различает — сравнение без него.
    """
    return origin.split(":", 1)[0].strip().casefold() == supplier.casefold()


def rules_facts(path: Path, supplier: str = "") -> dict[str, Any]:
    """Считает ответ проекта по правилам каталога.

    Считается не «сколько правил хороших», а чем они держатся: механизм и
    документ — оба законные ответы, и разница между ними видна только числом.

    МАШИННЫЕ ОТВЕТЫ — ЕЩЁ И ПО ПРОИСХОЖДЕНИЮ (#1282): `own` — без `origin`,
    `taken` — `origin` ведёт к поставщику, `elsewhere` — к кому-то ещё
    (например, действие каталога). Третье число на значок не идёт, но лежит
    здесь: без него сумма не сходилась бы с «машиной», и пропажа была бы не
    видна (045).

    ПОСТАВЩИК — ВХОДОМ, А НЕ БУКВАМИ. Общий шаг знает, чей код он выкачал
    (`job.workflow_repository`), и имя у соседа то же, откуда он шаг позвал;
    литерал прибил бы модуль к нашему проекту (инвентарь переносимого). Не
    назван — разбивка говорит «не прочитано» своей формой, а не делит наугад.
    """
    if not path.is_file():
        raise NotRun(f"нет ответа каталогу: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc

    rules = document.get("rules") if isinstance(document, dict) else None
    if not isinstance(rules, dict) or not rules:
        raise NotRun(f"{path}: раздел rules пуст — предмет счёта не найден (075)")

    statuses: Counter[str] = Counter()
    mechanisms: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    origin_kinds: Counter[str] = Counter()
    for number, answer in rules.items():
        if not isinstance(answer, dict):
            raise NotRun(f"{path}: ответ по правилу {number} не отображение")
        status = str(answer.get("status", "")).strip()
        if status not in STATUSES:
            raise NotRun(f"{path}: правило {number} несёт статус «{status}», которого нет в схеме")
        statuses[status] += 1
        if status != "active":
            continue
        mechanism = str(answer.get("mechanism", "")).strip()
        if not mechanism:
            raise NotRun(f"{path}: правило {number} действует, но чем — не сказано")
        mechanisms[mechanism] += 1
        if mechanism not in kinds.MACHINE:
            continue
        origin = str(answer.get("origin") or "").strip()
        taken = bool(origin and supplier and taken_from(origin, supplier))
        sources["taken" if taken else "elsewhere" if origin else "own"] += 1
        origin_kinds[str(answer.get("origin_kind") or "").strip() or UNNAMED_KIND] += 1

    return {
        "read": True,
        "total": len(rules),
        "answered": len(rules) - statuses["unreviewed"],
        "by_status": {status: statuses[status] for status in STATUSES},
        "by_mechanism": dict(sorted(mechanisms.items())),
        "machine": {
            **{source: sources[source] for source in ("own", "taken", "elsewhere")},
            "by_origin_kind": dict(sorted(origin_kinds.items())),
        }
        if supplier
        else {"read": False, "why": NO_SUPPLIER},
    }


def rules_said(root: Path, supplier: str = "") -> dict[str, Any]:
    """Счёт ответа каталогу или его отсутствие с причиной — третий исход, а не отказ шага.

    Причина — формой раздела `{"read": false, "why": …}`, а не в `none`: ключи
    `none` схема витрины перечисляет закрытым списком, и `rules` в нём нет.
    Потребитель без ответа каталогу законен — значок скажет «не прочитано», а
    не ноль (045).
    """
    try:
        return rules_facts(root / paths.BINDINGS, supplier)
    except NotRun as exc:
        return {"read": False, "why": str(exc)}


def common(
    root: Path,
    *,
    sha: str,
    repo: str,
    ci_workflow: str,
    python_matrix: str = "",
    python_next: str = "",
    coverage: Path | None = None,
    supplier: str = "",
) -> dict[str, Any]:
    """Общие факты: минимум договора, CI, Python, версии, покрытие, ответ каталогу — и `none`.

    `supplier` — чей код конвейера исполняется (`job.workflow_repository` у
    общего шага): по нему машинные ответы делятся на свои и взятые (#1282).
    """
    run, none = ci_facts(root, ci_workflow, python_matrix, python_next)
    said: dict[str, Any] = {
        # МИНИМУМ КОНТРАКТА СЕМЬИ: версия формата строкой, о ком файл и когда
        # собран — с поясом, чтобы витрина могла сказать «факты устарели» (#759).
        "schema": SCHEMA,
        "schema_of": SCHEMA_OF,
        "repo": repo,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": sha,
        # Статус CI витрина спрашивает у площадки по имени файла (договор с 1.2).
        **run,
        "rules": rules_said(root, supplier),
    }
    # ВЕРСИЯ ГОЛОВЫ И ВЫПУСК — РАЗНЫЕ ЧИСЛА (договор фактов 1.3, #1046): голова
    # уходит вперёд каждым изменением, потребитель живёт на выпущенном.
    try:
        number, whole = version.version(root)
    except version.NotRun as exc:
        print(f"warning: {exc}", file=sys.stderr)
        none["version"] = NO_VERSION
    else:
        said["version"] = number
        # Неполнота названа рядом с числом: клон без тегов даёт правдоподобное
        # число, которое ложь (045).
        said["version_whole"] = whole
    said["release"] = release_series(version.release_tag(root))
    covered = contract_coverage(coverage_facts(coverage))
    none.update(covered.pop("none", {}))
    said.update(covered)
    if none:
        said["none"] = none
    return said


def merge(shared: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Общие факты и свои числа проекта — без перекрытия; недостающему — причина.

    Свой `none` проекта вливается в общий; показатель, у которого есть и
    значение, и причина, — отказ: третьего исхода у договора нет, и двух
    ответов сразу тоже.
    """
    overlap = sorted((set(extra) - {"none"}) & COMMON_KEYS)
    if overlap:
        raise NotRun(
            f"extra-facts перекрывает общие показатели: {', '.join(overlap)} — "
            "их считает общий издатель, свой генератор того же числа вернул бы разнобой"
        )
    said = {**shared, **{key: value for key, value in extra.items() if key != "none"}}
    none = {**shared.get("none", {}), **extra.get("none", {})}
    both = sorted(key for key in none if key in said)
    if both:
        raise NotRun(f"у показателя и значение, и причина в none: {', '.join(both)}")
    for key in CONTRACT_METRICS:
        if key not in said and key not in none:
            none[key] = NOT_GIVEN
    said.pop("none", None)
    if none:
        said["none"] = dict(sorted(none.items()))
    return said


def read_extra(path: Path | None) -> dict[str, Any]:
    """Свой файл проекта: объект JSON; не назван — пусто, не разобран — отказ."""
    if path is None:
        return {}
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotRun(f"extra-facts {path} не прочитан: {exc}") from exc
    if not isinstance(said, dict):
        raise NotRun(f"extra-facts {path}: не объект JSON")
    return said


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает `facts.json` из общей части и своих чисел проекта."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева проекта")
    parser.add_argument("--out", type=Path, required=True, help="куда положить facts.json")
    parser.add_argument("--sha", required=True, help="голова, на которой собрано")
    parser.add_argument("--repo", required=True, help="имя проекта у площадки: владелец/репо")
    parser.add_argument("--ci-workflow", default="ci.yml", help="файл прогона CI проекта")
    parser.add_argument("--python-matrix", default="", help="матрица версий: <файл>:<джоб>")
    parser.add_argument("--python-next", default="", help="пробные версии: <файл>:<джоб>")
    parser.add_argument("--coverage", type=Path, default=None, help="отчёт покрытия coverage.json")
    parser.add_argument("--extra", type=Path, default=None, help="свои числа проекта, JSON")
    parser.add_argument(
        "--supplier", default="", help="поставщик кода конвейера: владелец/репо — для «свои/взяты»"
    )
    args = parser.parse_args(argv)
    if not args.repo:
        print("факты не собраны: не названо имя проекта — минимум договора (#759)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        shared = common(
            args.root,
            sha=args.sha,
            repo=args.repo,
            ci_workflow=args.ci_workflow,
            python_matrix=args.python_matrix,
            python_next=args.python_next,
            coverage=args.coverage,
            supplier=args.supplier,
        )
        facts = merge(shared, read_extra(args.extra))
    except NotRun as exc:
        print(f"факты не собраны: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"собрано: {args.out} — показателей {len(facts)}, причин {len(facts.get('none', {}))}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
