#!/usr/bin/env python3
"""Архив находок внешнего взгляда: история, род и рождённое правило (#778).

ЗАЧЕМ. Реестр находок держит только НЕразобранное: снятая находка уходит из
него, а остальное лежит в лентах изменений и достаётся только разбором заново.
Однотипность ошибок искалась памятью окна или разовым замером, а связь «из
этого рода родилось такое-то правило» жила в словаре родов, но не у самой
находки. Решение владельца 24.09.2026: архив — в ветке `badges`, которую
`badges.yml` пересобирает после каждого слияния, по адресу семьи
`.github/badges/findings.json`.

АРХИВ ДОПИСЫВАЕТСЯ, А НЕ ПЕРЕСОБИРАЕТСЯ. Прежний файл читается с ветки
`badges`, и к нему добавляются слитые изменения после его отметки `last_pr` —
не больше `--budget` за заход: первое наполнение идёт несколькими заходами, а
не одним, который съел бы квоту площадки (058). Поля, выводимые из дерева, —
род находки и его судьба у каталога — пересчитываются каждый раз: словарь
родов меняется, а история находок нет.

ПРОЧИТАТЬ ПРЕЖНИЙ АРХИВ НЕ УДАЛОСЬ — ОТКАЗ, А НЕ ЧИСТЫЙ ЛИСТ. Архива ещё нет
(404) — законное начало с нуля. Любой другой отказ площадки значил бы, что
история есть, но не прочитана, и опубликовать вместо неё свежий архив значило бы
выдать пустоту за историю (045). Потеря не окончательна — ленты изменений на
месте, и архив восстанавливается повторным наполнением, — но молча её не
допускают.

РАЗБОР СТРОКИ НАХОДКИ — ТОТ ЖЕ, ЧТО У СБОРЩИКА РЕЕСТРА (`review_findings`),
место — тот же, что у замера цепочек (`finding_chains.place_of`): второй разбор
одной строки разошёлся бы с первым молча (022).

Исходы (правило 039): ``0`` архив собран · ``2`` не собран (нет токена или
репозитория, площадка не ответила, прежний архив не прочитан).
"""

from __future__ import annotations

import argparse
import base64
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
import paths
import review_findings

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Имя архива внутри каталога производного семьи.
NAME: Final = "findings.json"
#: Версия формы архива.
SCHEMA: Final = "1"
#: Что версия описывает: пояснение ставится рядом с номером (164).
SCHEMA_SAID: Final = (
    "версия формы архива: findings (отпечаток → запись), kinds (род → встречи и "
    "судьба), last_pr — до какого изменения дописано"
)
#: Сколько слитых изменений дописывать за заход. Замер 24.09.2026: запрос ленты
#: и запрос коммита слияния на изменение — около двухсот запросов на заход при
#: квоте прогона в тысячу в час.
BUDGET: Final = 100

#: Строка снятия находки в теле слитого изменения — тот же ключ, что у реестра.
RESOLVED_RE: Final = re.compile(
    r"^\s*Разобрано:\s*`?(?P<mark>[0-9a-f]{7})`?(?:\s+дубль\s+`?(?P<twin>[0-9a-f]{7})`?)?",
    re.M,
)


class NotRun(RuntimeError):
    """Архив не собран: третий исход, а не «находок нет»."""


def previous(repo: str, token: str) -> dict[str, Any] | None:
    """Прежний архив с ветки `badges`; ``None`` — архива ещё нет (404)."""
    where = f"repos/{repo}/contents/{paths.BADGES_DIR / NAME}?ref=badges"
    try:
        said = ghrest.request("GET", where, token) or {}
    except ghrest.TransportError as exc:
        if "404" in str(exc):
            return None
        raise NotRun(f"прежний архив не прочитан — {exc}") from exc
    try:
        data: dict[str, Any] = json.loads(base64.b64decode(str(said.get("content") or "")))
    except (ValueError, json.JSONDecodeError) as exc:
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
    findings: dict[str, dict[str, Any]], number: int, comments: list[dict[str, Any]], message: str
) -> None:
    """Дописывает находки одной ленты и снятия из тела её слияния."""
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
                "resolved_by": None,
                "twin_of": "",
                "checked": "",
            }
        elif number not in entry["seen_on"]:
            entry["seen_on"] = sorted({*entry["seen_on"], number})
    for mark, twin in resolved_in(message).items():
        if mark in findings and findings[mark]["resolved_by"] is None:
            findings[mark]["resolved_by"] = number
            findings[mark]["twin_of"] = twin


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


def merged_after(repo: str, token: str, mark: int, budget: int) -> list[dict[str, Any]]:
    """Слитые изменения с номером больше отметки — по возрастанию, не больше бюджета."""
    taken: list[dict[str, Any]] = []
    listed = ghrest.paginate(f"repos/{repo}/pulls?state=closed&sort=created&direction=asc", token)
    for pull in listed:
        if int(pull["number"]) <= mark or not pull.get("merged_at"):
            continue
        taken.append(pull)
        if len(taken) >= budget:
            break
    return taken


def build(repo: str, token: str, budget: int, kinds: dict[str, Any]) -> dict[str, Any]:
    """Архив: прежний с ветки плюс слитое после его отметки."""
    before = previous(repo, token) or {}
    findings: dict[str, dict[str, Any]] = dict(before.get("findings") or {})
    mark = int(before.get("last_pr") or 0)
    for pull in merged_after(repo, token, mark, budget):
        number = int(pull["number"])
        comments = list(ghrest.paginate(f"repos/{repo}/issues/{number}/comments", token))
        sha = str(pull.get("merge_commit_sha") or "")
        message = ""
        if sha:
            commit = ghrest.request("GET", f"repos/{repo}/commits/{sha}", token) or {}
            message = str((commit.get("commit") or {}).get("message") or "")
        add_change(findings, number, comments, message)
        mark = max(mark, number)
    for sign, said in verdicts(repo, token).items():
        if sign in findings and not findings[sign].get("checked"):
            findings[sign]["checked"] = said
    summary = with_kinds(findings, kinds)
    return {
        "schema": SCHEMA,
        "_schema": SCHEMA_SAID,
        "repo": repo,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_pr": mark,
        "findings": dict(sorted(findings.items())),
        "kinds": summary,
    }


def main(argv: list[str] | None = None) -> int:
    """Точка входа: дописывает архив и кладёт его в каталог публикации."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--out", type=Path, required=True, help="куда положить архив")
    parser.add_argument("--budget", type=int, default=BUDGET, help="слитых изменений за заход")
    args = parser.parse_args(argv)
    token = ghrest.token_from_env()
    if not token or not args.repo:
        print("архив не собран: нет токена или репозитория (045)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        archive = build(args.repo, token, args.budget, finding_kinds.read())
    except (NotRun, ghrest.TransportError, finding_kinds.NotRun) as exc:
        print(f"архив не собран: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    born = sum(1 for one in archive["findings"].values() if one["правило"])
    print(
        f"архив находок: {len(archive['findings'])} записей, дописано до #{archive['last_pr']}, "
        f"с родом и судьбой у каталога — {born} → {args.out}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
