#!/usr/bin/env python3
"""Архив находок внешнего взгляда: история, род и рождённое правило (#778).

ЗАЧЕМ. Реестр находок держит только НЕразобранное: снятая находка уходит из
него, а остальное лежит в лентах изменений и достаётся только разбором заново.
Однотипность ошибок искалась памятью окна или разовым замером, а связь «из
этого рода родилось такое-то правило» жила в словаре родов, но не у самой
находки. Решение владельца 24.09.2026: архив — в ветке `badges`, которую
`badges.yml` пересобирает после каждого слияния, по адресу семьи
`.github/badges/findings.json`.

АРХИВ ДОПИСЫВАЕТСЯ, А НЕ ПЕРЕСОБИРАЕТСЯ. Прежний файл прогон берёт из ветки
`badges` git-ом и передаёт сюда (`--previous`), и к нему добавляются слитые
изменения, которых в нём ещё нет, — не больше `--budget` за заход: первое
наполнение идёт несколькими заходами, а не одним, который съел бы квоту
площадки (058). Поля, выводимые из дерева, — род находки и его судьба у
каталога — пересчитываются каждый раз: словарь родов меняется, а история
находок нет.

УЧТЁННОЕ — МНОЖЕСТВО НОМЕРОВ, А НЕ ОТМЕТКА. Изменения сливаются не по порядку
номеров: #774 и #781 слиты позже #785. Отметка «до какого номера дописано»
отсекала бы такие изменения навсегда (взгляд на #788). Поэтому архив помнит,
какие изменения уже учтены, и берёт слитые по времени слияния, пропуская учтённые.

СНЯТИЕ МОЖЕТ ПРИЙТИ РАНЬШЕ НАХОДКИ. Строка `Разобрано:` лежит в теле слияния,
а находка — в ленте своего изменения, и учтены они бывают в любом порядке.
Поэтому снятия копятся отдельно (`resolutions`) и прикладываются к находке,
когда она появляется.

ИСТОРИЮ НЕЛЬЗЯ ПОТЕРЯТЬ ОТКАЗОМ ШАГА. Ветка `badges` перезаписывается целиком,
и упавший шаг снял бы архив с неё. А ответ верификатора у записей, уже
ушедших из реестра, из лент не восстанавливается — потеря была бы окончательной
(взгляд на #788). Поэтому при отказе прогон переносит прежний файл как есть, а
если прочитать ветку не удалось вовсе — не публикует её (см. `badges.yml`).

ЧЕГО АРХИВ НЕ ЗНАЕТ, ОН ГОВОРИТ САМ (`gaps`): сколько слитых изменений ещё не
учтено и что ответы верификатора до первого захода архива неизвестны.

РАЗБОР СТРОКИ НАХОДКИ — ТОТ ЖЕ, ЧТО У СБОРЩИКА РЕЕСТРА (`review_findings`),
место — тот же, что у замера цепочек (`finding_chains.place_of`): второй разбор
одной строки разошёлся бы с первым молча (022).

Исходы (правило 039): ``0`` архив собран · ``2`` не собран (нет токена или
репозитория, площадка не ответила, прежний архив не разбирается).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import finding_chains
import finding_kinds
import findings as registry
import ghrest
import review_findings

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Версия формы архива.
SCHEMA: Final = "2"
#: Что версия описывает: пояснение ставится рядом с номером (164).
SCHEMA_SAID: Final = (
    "версия формы архива: findings (отпечаток → запись), resolutions (снятия, в том "
    "числе ещё без находки), counted (учтённые изменения), kinds (род → встречи и "
    "судьба), gaps (чего архив не знает)"
)
#: Сколько слитых изменений дописывать за заход. Замер 24.09.2026: запрос ленты
#: и запрос коммита слияния на изменение — около двухсот запросов на заход при
#: квоте прогона в тысячу в час.
BUDGET: Final = 100
#: Граница, которую архив знает о себе всегда: ответ верификатора подхватывается
#: из живого реестра, пока запись в нём, и у ушедших раньше первого захода его нет.
VERIFIER_GAP: Final = (
    "ответы верификатора у находок, ушедших из реестра до первого захода архива, неизвестны"
)

#: Строка снятия находки в теле слитого изменения — тот же ключ, что у реестра.
RESOLVED_RE: Final = re.compile(
    r"^\s*Разобрано:\s*`?(?P<mark>[0-9a-f]{7})`?(?:\s+дубль\s+`?(?P<twin>[0-9a-f]{7})`?)?",
    re.M,
)


class NotRun(RuntimeError):
    """Архив не собран: третий исход, а не «находок нет»."""


def previous(path: Path | None) -> dict[str, Any]:
    """Прежний архив из файла, взятого прогоном с ветки; нет файла — начало с нуля."""
    if path is None:
        return {}
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotRun(f"прежний архив не разбирается — {exc}") from exc
    return data


def resolved_in(message: str) -> dict[str, str]:
    """Отпечаток → дубль из строк `Разобрано:`; у самостоятельной находки дубль пуст."""
    return {found["mark"]: found["twin"] or "" for found in RESOLVED_RE.finditer(message)}


def kinds_by_mark(kinds: dict[str, Any]) -> dict[str, str]:
    """Отпечаток встречи → имя рода, по полю «встречен» словаря родов."""
    found: dict[str, str] = {}
    for name, body in kinds.items():
        for met in body.get("встречен", []):
            mark = str(met).strip("`")
            if re.fullmatch(r"[0-9a-f]{7}", mark):
                found.setdefault(mark, name)
    return found


def rule_of(body: dict[str, Any]) -> dict[str, Any]:
    """Что род родил: ответ каталогу («предложено», «своё», «есть») и выросшее."""
    fate = finding_kinds.fate(body)
    return {
        "каталогу": {"вид": fate[0], "сказано": fate[1]} if fate else None,
        "породил": list(body.get(finding_kinds.BORN, [])),
    }


def add_change(
    archive: dict[str, Any], number: int, comments: list[dict[str, Any]], message: str
) -> None:
    """Дописывает находки одной ленты и снятия из тела её слияния."""
    findings: dict[str, dict[str, Any]] = archive["findings"]
    resolutions: dict[str, dict[str, Any]] = archive["resolutions"]
    for weight, title, kind, role in review_findings.found_in(comments):
        mark = review_findings.fingerprint(title)
        entry = findings.get(mark)
        if entry is None:
            findings[mark] = {
                "pr": number,
                "seen_on": [number],
                "weight": weight,
                "kind": kind,
                "role": role,
                "title": title,
                "place": finding_chains.place_of(title),
                "checked": "",
            }
        elif number not in entry["seen_on"]:
            entry["seen_on"] = sorted({*entry["seen_on"], number})
            entry["pr"] = min(entry["seen_on"])
    for mark, twin in resolved_in(message).items():
        resolutions.setdefault(mark, {"by": number, "twin_of": twin})


def settle(archive: dict[str, Any]) -> None:
    """Прикладывает снятия к находкам — в каком бы порядке они ни были учтены."""
    for mark, entry in archive["findings"].items():
        said = archive["resolutions"].get(mark)
        entry["resolved_by"] = said["by"] if said else None
        entry["twin_of"] = said["twin_of"] if said else ""


def with_kinds(findings: dict[str, dict[str, Any]], kinds: dict[str, Any]) -> dict[str, Any]:
    """Род и его судьба у каждой находки — из дерева, пересчётом, а не из прошлого архива."""
    by_mark = kinds_by_mark(kinds)
    for mark, entry in findings.items():
        name = by_mark.get(mark)
        entry["род"] = name
        entry["правило"] = rule_of(kinds[name]) if name else None
    return {
        name: {"встреч": sum(1 for one in by_mark.values() if one == name), **rule_of(body)}
        for name, body in kinds.items()
    }


def verdicts(repo: str, token: str) -> dict[str, str]:
    """Ответы верификатора из живого реестра: отпечаток → ответ о премисе.

    Реестр держит ответ, пока запись в нём; снятая запись уходит вместе с
    ответом. Архив подхватывает ответ на каждом заходе, пока он виден, и
    больше его не теряет: ответ о премисе — о находке, а не о дне её снятия.
    """
    _, body = registry.live_issue(repo, token)
    return {
        mark: entry.checked for mark, entry in registry.parse_entries(body).items() if entry.checked
    }


def merged_pending(repo: str, token: str, counted: set[int]) -> list[dict[str, Any]]:
    """Слитые, но ещё не учтённые изменения — по времени слияния, а не по номеру."""
    listed = ghrest.paginate(f"repos/{repo}/pulls?state=closed&sort=created&direction=asc", token)
    pending = [
        pull for pull in listed if pull.get("merged_at") and int(pull["number"]) not in counted
    ]
    return sorted(pending, key=lambda pull: (str(pull["merged_at"]), int(pull["number"])))


def build(
    repo: str, token: str, budget: int, kinds: dict[str, Any], before: dict[str, Any]
) -> dict[str, Any]:
    """Архив: прежний плюс слитое, которого в нём ещё нет, — не больше бюджета."""
    archive: dict[str, Any] = {
        "findings": dict(before.get("findings") or {}),
        "resolutions": dict(before.get("resolutions") or {}),
    }
    counted: set[int] = {int(one) for one in before.get("counted") or []}
    pending = merged_pending(repo, token, counted)
    for pull in pending[:budget]:
        number = int(pull["number"])
        comments = list(ghrest.paginate(f"repos/{repo}/issues/{number}/comments", token))
        sha = str(pull.get("merge_commit_sha") or "")
        message = ""
        if sha:
            commit = ghrest.request("GET", f"repos/{repo}/commits/{sha}", token) or {}
            message = str((commit.get("commit") or {}).get("message") or "")
        add_change(archive, number, comments, message)
        counted.add(number)
    for sign, said in verdicts(repo, token).items():
        entry = archive["findings"].get(sign)
        if entry is not None and not entry.get("checked"):
            entry["checked"] = said
    settle(archive)
    summary = with_kinds(archive["findings"], kinds)
    left = max(0, len(pending) - budget)
    gaps = [VERIFIER_GAP]
    if left:
        gaps.insert(0, f"наполнение не дошло до головы: не учтено слитых изменений — {left}")
    return {
        "schema": SCHEMA,
        "_schema": SCHEMA_SAID,
        "repo": repo,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counted": sorted(counted),
        "gaps": gaps,
        "findings": dict(sorted(archive["findings"].items())),
        "resolutions": dict(sorted(archive["resolutions"].items())),
        "kinds": summary,
    }


def main(argv: list[str] | None = None) -> int:
    """Точка входа: дописывает архив и кладёт его в каталог публикации."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--out", type=Path, required=True, help="куда положить архив")
    parser.add_argument("--previous", type=Path, default=None, help="прежний архив с ветки")
    parser.add_argument("--budget", type=int, default=BUDGET, help="слитых изменений за заход")
    args = parser.parse_args(argv)
    token = ghrest.token_from_env()
    if not token or not args.repo:
        print("архив не собран: нет токена или репозитория (045)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        archive = build(
            args.repo, token, args.budget, finding_kinds.read(), previous(args.previous)
        )
    except (NotRun, ghrest.TransportError, finding_kinds.NotRun) as exc:
        print(f"архив не собран: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    born = sum(1 for one in archive["findings"].values() if one["правило"])
    print(
        f"архив находок: {len(archive['findings'])} записей, учтено изменений — "
        f"{len(archive['counted'])}, с родом и судьбой у каталога — {born} → {args.out}"
    )
    for gap in archive["gaps"]:
        print(f"  не знает: {gap}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
