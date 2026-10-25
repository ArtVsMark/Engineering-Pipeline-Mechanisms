#!/usr/bin/env python3
"""Карта гейтов семьи: правило × проект → чем держится, и три очереди кандидатов.

РЕШЕНИЕ ВЛАДЕЛЬЦА 16.10.2026 И 25.10.2026 (#1425, вариант А). Главное правило
проекта — всё наше уходит семье, настраиваемо и универсально, а доработанное
соседом возвращается к нам. Обход семьи знал, КТО взял наш шаг
(`family_uptake`), но не разрез по правилу: у кого какое правило держится каким
механизмом и чей механизм сильнее. Карта — этот разрез, а очереди — работа из
него, которую владелец раскладывает по выпускам.

ИСТОЧНИК — СВОДКА КАТАЛОГА, А НЕ КЛОНЫ (`export/where.json`, её же читает
`family`). Каждый проект там отвечает по правилу: вид механизма, адрес и с
формы 1.6 — происхождение (`origin`, `origin_kind`). Код соседа карта не
читает и не исполняет; карта называет, а не решает: брать ли кандидата —
слово владельца.

КЛЕТКА — ОДИН ИЗ СЕМИ ИСХОДОВ (`HELD`): наш механизм без переделки (вызов
или копия — `family.TAKEN_KINDS`); наш механизм, переписанный к себе
(`family.ADAPTED_KIND`); наш, но вид взятия не объявлен; свой механизм
проекта; прозой; никак; неприменимо. Происхождение читается ТОЛЬКО у машинного
ответа (`family.KINDS`), как у `family.origins`: документ с нашим `origin`
механизмом не держится (взгляд на #1346, на #1668).

ОЧЕРЕДИ (`QUEUES`):

1. **доработать у нас** — сосед переписал наш механизм к себе: доработку
   забираем входом шага, и он переходит на вызов;
2. **раздать в выпуске** — свой гейт соседа там, где у нас машины нет:
   обобщаем и раздаём шагом;
3. **предложить каталогу** — правило, которое машиной не держит никто в
   семье: кандидат на новый общий гейт.

Исходы (правило 039): ``0`` карта собрана · ``2`` не отработал.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

import family
import family_uptake
import kinds

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Версия формы файла карты.
SCHEMA: Final = "1.0"
#: Исходы клетки — в порядке силы держания для печати.
TAKEN: Final = "наш механизм без переделки"
REWRITTEN: Final = "наш механизм, переписан к себе"
#: Вид взятия не назван: «не объявлено», а не «взято» и не «переписано» (045).
UNDECLARED: Final = "наш механизм, вид взятия не объявлен"
OWN: Final = "свой механизм"
PROSE: Final = "прозой"
NOTHING: Final = "никак"
INAPPLICABLE: Final = "неприменимо"
HELD: Final = (TAKEN, REWRITTEN, UNDECLARED, OWN, PROSE, NOTHING, INAPPLICABLE)
#: Исходы, при которых правило держит машина.
BY_MACHINE: Final = frozenset({TAKEN, REWRITTEN, UNDECLARED, OWN})
#: Виды, которые держат правило прозой: документ и навык — их исполняет чтение.
PROSE_KINDS: Final = frozenset({kinds.DOCUMENT, kinds.SKILL})
#: Очереди кандидатов: ключ файла → что с ней делать.
QUEUES: Final = {
    "rework": "доработать у нас: сосед переписал наш механизм к себе",
    "spread": "раздать в выпуске: свой гейт соседа там, где у нас машины нет",
    "propose": "предложить каталогу: правило машиной не держит никто в семье",
}


def held(answer: dict[str, Any], status: str) -> str:
    """Исход клетки по ответу проекта: у машинного ответа происхождение сильнее вида."""
    if status == "not-applicable":
        return INAPPLICABLE
    mechanism = str(answer.get("mechanism") or "")
    if mechanism in family.KINDS:
        origin = str(answer.get("origin") or "")
        if not origin.casefold().startswith(family.OURS_ORIGIN.casefold()):
            return OWN
        how = answer.get("origin_kind")
        if how == family.ADAPTED_KIND:
            return REWRITTEN
        return TAKEN if how in family.TAKEN_KINDS else UNDECLARED
    if mechanism in PROSE_KINDS:
        return PROSE
    return NOTHING


def cells(summary: dict[str, Any]) -> dict[str, dict[str, dict[str, str]]]:
    """Карта: правило → проект → исход, вид механизма и адрес."""
    found: dict[str, dict[str, dict[str, str]]] = {}
    for consumer in summary.get("consumers") or []:
        repo = str(consumer.get("repo") or "")
        statuses = consumer.get("rules") or {}
        for number, answer in sorted((consumer.get("holds") or {}).items()):
            if not isinstance(answer, dict):
                continue
            found.setdefault(str(number), {})[repo] = {
                "held": held(answer, str(statuses.get(number) or "")),
                "mechanism": str(answer.get("mechanism") or ""),
                "where": str(answer.get("where") or ""),
                "origin": str(answer.get("origin") or ""),
            }
        # «НЕПРИМЕНИМО» ЖИВЁТ В `rules`, А НЕ В `holds`: держания у него нет, и
        # без этого обхода клетка пропала бы, а правило выглядело бы неотвеченным.
        for number, status in sorted(statuses.items()):
            if status == "not-applicable":
                found.setdefault(str(number), {}).setdefault(
                    repo, {"held": INAPPLICABLE, "mechanism": "", "where": "", "origin": ""}
                )
    return found


def queues(found: dict[str, dict[str, dict[str, str]]], mine: str) -> dict[str, list[Any]]:
    """Три очереди кандидатов из карты; `mine` — наш репозиторий."""
    ours = mine.casefold()
    rework: list[dict[str, str]] = []
    spread: list[dict[str, str]] = []
    propose: list[str] = []
    for number, row in sorted(found.items()):
        here = next((cell for repo, cell in row.items() if repo.casefold() == ours), None)
        ours_machine = here is not None and here["held"] in BY_MACHINE
        for repo, cell in sorted(row.items()):
            if repo.casefold() == ours:
                continue
            said = {"rule": number, "repo": repo, "where": cell["where"]}
            if cell["held"] == REWRITTEN:
                rework.append({**said, "origin": cell["origin"]})
            elif cell["held"] == OWN and not ours_machine:
                spread.append(said)
        active = [cell for cell in row.values() if cell["held"] != INAPPLICABLE]
        if active and not any(cell["held"] in BY_MACHINE for cell in active):
            propose.append(number)
    return {"rework": rework, "spread": spread, "propose": propose}


def document(summary: dict[str, Any], mine: str) -> dict[str, Any]:
    """Файл карты: форма, источник, счёт исходов, карта и очереди.

    НАС В СВОДКЕ НЕТ — ОТКАЗ, А НЕ ОЧЕРЕДЬ (взгляд на #1668): без своей строки
    каждый свой гейт соседа ушёл бы в «раздать» правдоподобным списком (039).
    """
    repos = {str(one.get("repo") or "").casefold() for one in summary.get("consumers") or []}
    if mine.casefold() not in repos:
        raise family.NotRun(f"«{mine}» в сводке семьи нет — очереди не из чего сравнить")
    found = cells(summary)
    counted = {name: 0 for name in HELD}
    for row in found.values():
        for cell in row.values():
            counted[cell["held"]] += 1
    return {
        "schema": SCHEMA,
        "source": {"summary": family.schema_of(summary), "at": summary.get("generated_at")},
        "held": counted,
        "queues_meaning": QUEUES,
        "queues": queues(found, mine),
        "rules": found,
    }


def main(argv: list[str] | None = None) -> int:
    """Точка входа: карта по сводке семьи — в файл `--out`."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="сводка каталога where.json")
    parser.add_argument("--out", type=Path, required=True, help="куда положить карту")
    parser.add_argument("--repo", default=family_uptake.OURS, help="наш репозиторий")
    args = parser.parse_args(argv)
    try:
        said = document(family.load(args.summary), args.repo)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(said, ensure_ascii=False, indent=2) + "\n", "utf-8")
    except (family.NotRun, OSError) as exc:
        print(f"карта гейтов семьи не собрана: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    line = ", ".join(f"{name} {count}" for name, count in said["held"].items())
    print(f"карта гейтов семьи: правил {len(said['rules'])}; {line}")
    print(", ".join(f"{key} {len(rows)}" for key, rows in said["queues"].items()))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
