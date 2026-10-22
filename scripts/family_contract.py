#!/usr/bin/env python3
"""Форма контракта семьи: манифест проекта `contracts.json` и чем он не манифест.

ПЕРЕЕХАЛО ИЗ КАТАЛОГА (#1563, этап 3 ArtVsMark/Engineering-Incidents-Playbook#930)
под новым именем: у каталога это `family.py`, а `scripts/family.py` механизмов —
другой предмет, мерило общих механизмов. Имя на въезде меняется, чтобы два
предмета не делили одно (решение владельца 22.10).

МАНИФЕСТ (`.github/badges/contracts.json` на ветке `badges` каждого проекта):

  schema   — номер этого формата, FAMILY_SCHEMA;
  project  — `владелец/имя`;
  release  — последний выпуск: {"tag": "v1.10.0", "sha": "<40 знаков>"}
             или null, пока выпусков нет;
  gives    — что проект ОТДАЁТ: {имя контракта: номер};
  takes    — ПАРНЫЕ связи, которых не найти автоматически: [{"from":
             "владелец/имя", "contract": имя, "where": путь в своём дереве,
             "field": ключ с номером}];
  skips    — НЕОБЯЗАТЕЛЬНО, с 1.1: отказ от связи с издателем семьи,
             {"EPM": "причина"} — код или `владелец/имя`.

ПЕРЕЕХАЛА ФОРМА, А НЕ СБОР. Сводку семьи `export/family.json` собирает каталог
по своему реестру потребителей `.rules/consumers.json` — реестр и подключение
остаются у него (#1536). Сверке семьи здесь нужна только форма: судить свой
манифест и читать чужие из сводки. Граница названа: в переходный период форму
судят оба издателя, каталог — при сборе сводки, и номер формата у них общий.
"""

import json
from pathlib import Path
from typing import Any, Final

import paths

#: Номер формата манифеста и сводки семьи — один на оба: сводка есть список
#: манифестов, и разойтись им не в чем.
FAMILY_SCHEMA: Final = "1.2"
#: Где проект кладёт свой манифест — от корня его дерева.
MANIFEST: Final = paths.BADGES_DIR / "contracts.json"
#: Ключи манифеста и их тип. Форма проверяется этим, а не схемой JSON: ради
#: пяти ключей зависимость набору не заводится.
FORM: Final[dict[str, type | tuple[type, ...]]] = {
    "schema": str,
    "project": str,
    "release": (dict, type(None)),
    "gives": dict,
    "takes": list,
}


def form_flaw(doc: Any) -> str | None:
    """Чем манифест не похож на манифест; None — форма верна."""
    if not isinstance(doc, dict):
        return "манифест не объект JSON"
    for key, kind in FORM.items():
        if key not in doc:
            return f"нет ключа «{key}»"
        if not isinstance(doc[key], kind):
            return f"«{key}» не того типа"
    skips = doc.get("skips", {})
    if not isinstance(skips, dict) or not all(
        isinstance(key, str) and isinstance(why, str) and why.strip() for key, why in skips.items()
    ):
        return "«skips» — не объект «издатель: причина» с непустыми причинами"
    # не проза: номер формата «мажор.минор», сверяется мажор.
    if doc["schema"].split(".")[0] != FAMILY_SCHEMA.split(".")[0]:
        return f"формат {doc['schema']}, а читается {FAMILY_SCHEMA}"
    return None


def write(path: Path, doc: dict[str, Any]) -> None:
    """Записать документ контракта: JSON с отступом и переводом строки в конце."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
