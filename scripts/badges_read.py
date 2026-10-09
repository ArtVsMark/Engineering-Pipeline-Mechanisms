#!/usr/bin/env python3
"""Чтение производного с ветки `badges` — API площадки с токеном, а не прямой ссылкой.

ПРЯМАЯ ССЫЛКА БЕЗ ТОКЕНА В ПРИВАТНОМ РЕПОЗИТОРИИ ВСЕГДА 404 (взгляд на #1158,
#1162). Архив находок у верификатора и `facts.json` у ряда прогонов читались
`raw.githubusercontent.com` без токена: у приватного потребителя память дат и
покрытие были бы «не прочитано» всегда. Читатель один на оба механизма, а не
копия в каждом
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

СОДЕРЖИМОЕ БЕРЁТСЯ БЛОБОМ. Ответ `contents` не отдаёт файлы больше мегабайта,
а архив находок больше; `sha` он называет и тогда, и блоб читается по нему.

Отказ — `ghrest.TransportError`, а не пустой словарь: пустое читалось бы как
«фактов нет», то есть тихий запасной ответ на месте поломки (045).
"""

import base64
import binascii
import json
from typing import Any, Final

import ghrest
import paths

#: Ветка производного (125): начата сиротой, ведётся коммитами поверх, без `--force` (#1001).
BRANCH: Final = "badges"


def by_api(repo: str, name: str, token: str) -> dict[str, Any]:
    """JSON-файл `name` из `.github/badges/` ветки `badges` — через API с токеном."""
    where = (paths.BADGES_DIR / name).as_posix()
    meta = ghrest.request("GET", f"repos/{repo}/contents/{where}?ref={BRANCH}", token) or {}
    sha = str(meta.get("sha") or "") if isinstance(meta, dict) else ""
    if not sha:
        raise ghrest.TransportError(f"{name}: площадка не назвала блоб")
    blob = ghrest.request("GET", f"repos/{repo}/git/blobs/{sha}", token) or {}
    try:
        said = json.loads(base64.b64decode(str(blob.get("content") or "")))
    except (binascii.Error, ValueError) as exc:
        raise ghrest.TransportError(f"{name} не разбирается: {exc}") from exc
    if not isinstance(said, dict):
        raise ghrest.TransportError(f"{name} не словарь: читать нечего")
    return said
