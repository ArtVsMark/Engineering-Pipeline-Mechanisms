#!/usr/bin/env python3
"""Гейт: `facts.json` сверяется со схемой витрины ДО публикации, а не у потребителя после.

РЕШЕНИЕ ВЛАДЕЛЬЦА 04.10.2026 (#1001, первый шаг). Договор фактов ведёт
витрина (`ArtVsMark/ArtVsMark`, `.rules/facts.schema.json`), и до этой
проверки расхождение узнавалось только у неё — после того, как файл уже лежал
на ветке `badges`. Так 02.10.2026 договор поднялся до 1.3, а мы ещё два дня
публиковали выпуск тегом `v1.3.0` вместо серии `1.3` (#1046).

СХЕМА ПРИБИТА КОММИТОМ, А НЕ ВЕТКОЙ (152). Тегов у витрины нет, поэтому адрес
несёт sha коммита, поднявшего договор до 1.3 (`SCHEMA_SHA`). Живая ветка
`main` сменила бы требование под нами молча: красное на изменении, которое
ничего не трогало, или зелёное на файле, которому витрина уже откажет.
Подъём договора — правка этой константы, видимая в дифе.

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо (046): он не знает, что витрина подняла
договор, — сверка идёт с прибитой версией. Сверку версии договора с живой
витриной даёт второй шаг #1001 (общий издатель); до него подъём узнаётся
извещением витрины. И он не повторяет правил витрины сверх схемы — например,
«версия начинается с выпуска и точки» живёт в её `check_facts.py`, а чужой код
в нашем прогоне не исполняется.

Исходы (правило 039): ``0`` файл отвечает схеме · ``1`` не отвечает — что
именно, названо · ``2`` гейт не отработал: схему или файл не прочитать.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

import ghrest
import jsonschema

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2

#: Коммит витрины, поднявший договор фактов до 1.3 (#265 у витрины, 02.10.2026).
SCHEMA_SHA: Final = "d223bb65599476f6796c856fae0094950d2a4fec"
#: Адрес схемы на этом коммите — сырой файл, без API и без токена.
SCHEMA_URL: Final = (
    f"https://raw.githubusercontent.com/ArtVsMark/ArtVsMark/{SCHEMA_SHA}/.rules/facts.schema.json"
)
#: Сколько ошибок печатать: остальные называются числом, а не теряются.
SHOWN: Final = 10


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «файл отвечает»."""


def read_schema(url: str = SCHEMA_URL) -> dict[str, Any]:
    """Схема витрины по прибитому адресу — общим транспортом, как каталог."""
    try:
        return ghrest.raw_json(url)
    except ghrest.TransportError as exc:
        raise NotRun(f"схема не прочитана ({url}): {exc}") from exc


def problems(facts: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Расхождения файла со схемой: путь поля и что не так, по порядку путей."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(facts), key=lambda error: list(error.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<корень>'}: {error.message}"
        for error in errors
    ]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: один файл фактов против прибитой схемы."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", type=Path, help="собранный facts.json")
    parser.add_argument("--schema", default=SCHEMA_URL, help="адрес схемы витрины")
    args = parser.parse_args(argv)
    try:
        try:
            facts = json.loads(args.facts.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NotRun(f"файл фактов не прочитан ({args.facts}): {exc}") from exc
        found = problems(facts, read_schema(args.schema))
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if found:
        print(
            f"facts.json не отвечает схеме витрины ({len(found)}), коммит {SCHEMA_SHA[:7]}:",
            file=sys.stderr,
        )
        for line in found[:SHOWN]:
            print(f"  {line}", file=sys.stderr)
        if len(found) > SHOWN:
            print(f"  …и ещё {len(found) - SHOWN}", file=sys.stderr)
        return EXIT_REJECTED
    print(f"facts.json отвечает схеме витрины: коммит {SCHEMA_SHA[:7]}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
