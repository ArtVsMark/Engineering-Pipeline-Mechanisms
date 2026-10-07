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
версия головы и выпуск по тегам, доля покрытия из отчёта прогона. Наш
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

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
    }
)
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


def common(
    root: Path,
    *,
    sha: str,
    repo: str,
    ci_workflow: str,
    python_matrix: str = "",
    python_next: str = "",
    coverage: Path | None = None,
) -> dict[str, Any]:
    """Общие факты: минимум договора, CI, Python, версия, выпуск, покрытие — и `none`."""
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
