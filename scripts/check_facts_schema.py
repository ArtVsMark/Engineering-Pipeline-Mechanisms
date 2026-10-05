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

КОММИТ ПРОВЕРЯЕТСЯ НА ПРИНАДЛЕЖНОСТЬ ВИТРИНЕ (взгляд на #1112). Адрес
`raw.githubusercontent.com/<витрина>/<sha>` отдаёт и коммит из форка той же
сети: sha сам по себе не доказывает, что договор подняла витрина. Поэтому
перед чтением схемы гейт спрашивает площадку, лежит ли `SCHEMA_SHA` в
истории `main` витрины (`compare`), и коммит вне её — отказ, а не сверка.

ЧЕРНОВИК СХЕМЫ — ИЗ САМОЙ СХЕМЫ. Проверяльщик берётся по её `$schema`
(`validator_for`), а не прибит к одному черновику: иначе смысл ключей
разошёлся бы с витриной молча. Схема без `$schema` читается как 2020-12 —
это умолчание названо здесь. Испорченная схема — неизвестный `$schema`,
неизвестный тип, неразрешимая `$ref` — «не отработал», а не «отклонён»
(взгляды на #1112 и #1116).

`format` ПРОВЕРЯЕТСЯ НЕ ВЕСЬ, И ГРАНИЦА НАЗВАНА (195). Шаг ставит
`jsonschema` без дополнений, и проверяются форматы, которым внешние
библиотеки не нужны (`date`, `email`, `ipv4`, …). Форматы с библиотекой
(`date-time`, `uri`, …) проходят непроверенными. Схема витрины на прибитом
коммите `format` не использует вовсе (замер:
`git show <SCHEMA_SHA>:.rules/facts.schema.json` — ключа нет), поэтому
граница сегодня ничего не пропускает; поднял договор с форматом — ставьте
`jsonschema[format]`.

НЕПРЕДВИДЕННЫЙ СБОЙ — «НЕ ОТРАБОТАЛ» (взгляды на #1116). Трассировка Python
выходит кодом 1, а код 1 здесь — «отказ», и шаг публикации остановился бы
из-за ошибки гейта. Поэтому `main` переводит любое необработанное
исключение в исход 2 и называет его. Сбой ДО `main` — на импорте модуля —
так не поймать, и это соседний случай: поэтому шаг публикации останавливает
не код 1, а вердикт `VERDICT_REJECTED` в файле `--verdict`. Пишет его только
`main`, и только на отказе; любой другой ненулевой код — предупреждение.
ПРЕДЕЛ ЗАМЫСЛА НАЗВАН (195, взгляд на #1120): отказ, вердикт которого не
записался, снаружи неотличим от сбоя до `main` и публикацию не держит. Он
не молчит — вывод называет его «отклонена, но вердикт не записан», и шаг
публикации поднимает предупреждение с кодом 1, — но и не останавливает.

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо (046): он не знает, что витрина подняла
договор, — сверка идёт с прибитой версией. Сверку версии договора с живой
витриной даёт второй шаг #1001 (общий издатель); до него подъём узнаётся
извещением витрины. И он не повторяет правил витрины сверх схемы — например,
«версия начинается с выпуска и точки» живёт в её `check_facts.py`, а чужой код
в нашем прогоне не исполняется.

Исходы (правило 039): ``0`` файл отвечает схеме · ``1`` не отвечает — что
именно, названо, — или коммит схемы не из истории витрины · ``2`` гейт не
отработал: схему, файл или историю витрины не прочитать, схема испорчена.
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Final

import ghrest
import jsonschema
from referencing.exceptions import Unresolvable

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2

#: Репозиторий витрины: договор фактов ведёт он.
SHOWCASE: Final = "ArtVsMark/ArtVsMark"
#: Коммит витрины, поднявший договор фактов до 1.3 (#265 у витрины, 02.10.2026).
SCHEMA_SHA: Final = "d223bb65599476f6796c856fae0094950d2a4fec"
#: Адрес схемы на этом коммите — сырой файл, без API и без токена.
SCHEMA_URL: Final = (
    f"https://raw.githubusercontent.com/{SHOWCASE}/{SCHEMA_SHA}/.rules/facts.schema.json"
)
#: Сколько ошибок печатать: остальные называются числом, а не теряются.
SHOWN: Final = 10


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «файл отвечает»."""


class Foreign(ValueError):
    """Прибитый коммит не лежит в истории витрины: сверять не с чем."""


#: Ответы `compare` площадки, при которых коммит — предок `main` витрины.
ON_TRUNK: Final = frozenset({"ahead", "identical"})
#: Ответы, при которых коммита в истории `main` нет. Список разрешительный
#: (068): отказ — только на названном статусе; ответ без статуса, пустой или с
#: незнакомым словом — «не прочитали», а не «чужой» (взгляд на #1116).
OFF_TRUNK: Final = frozenset({"diverged", "behind"})
#: Слово вердикта отказа в файле `--verdict`: останавливает публикацию оно, а не
#: код выхода — код 1 даёт и трассировка, упавшая до `main` (взгляд на #1116).
VERDICT_REJECTED: Final = "rejected"


def pinned_on_trunk(sha: str, token: str) -> None:
    """Коммит лежит в истории `main` витрины; нет — `Foreign`, не спросить — `NotRun`.

    `compare <sha>...main` отвечает «ahead», когда `main` ушёл вперёд от
    коммита, и «identical», когда это он и есть. Коммит из форка той же сети
    площадка тоже находит, но отвечает «diverged»: в истории `main` его нет.
    """
    if not token:
        raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN — историю витрины не спросить")
    try:
        said = ghrest.request("GET", f"repos/{SHOWCASE}/compare/{sha}...main", token) or {}
    except ghrest.TransportError as exc:
        raise NotRun(f"история витрины не прочитана: {exc}") from exc
    if not isinstance(said, dict):
        raise NotRun(f"история витрины прочитана не словарём: {type(said).__name__}")
    status = str(said.get("status") or "")
    if status in ON_TRUNK:
        return
    if status not in OFF_TRUNK:
        raise NotRun(
            f"история витрины не прочитана: compare ответил статусом {status or 'никаким'!r}"
        )
    raise Foreign(
        f"коммит {sha[:7]} не лежит в истории main витрины {SHOWCASE} "
        f"(compare: {status}) — договор поднимала не она"
    )


def read_schema(url: str = SCHEMA_URL) -> dict[str, Any]:
    """Схема витрины по прибитому адресу — общим транспортом, как каталог."""
    try:
        return ghrest.raw_json(url)
    except ghrest.TransportError as exc:
        raise NotRun(f"схема не прочитана ({url}): {exc}") from exc


def draft_of(schema: dict[str, Any]) -> Any:
    """Проверяльщик по `$schema` схемы; без `$schema` — 2020-12, неизвестный — `NotRun`."""
    declared = schema.get("$schema")
    if declared is None:
        return jsonschema.Draft202012Validator
    with warnings.catch_warnings():
        # Неизвестный `$schema` библиотека называет предупреждением и отдаёт
        # умолчание. Здесь умолчание — отказ: узнаётся он тем, что объявленное
        # не совпало с метасхемой отданного проверяльщика.
        warnings.simplefilter("ignore", DeprecationWarning)
        kind = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    meta = kind.META_SCHEMA
    if str(meta.get("$id", meta.get("id", ""))).rstrip("#") != str(declared).rstrip("#"):
        raise NotRun(f"черновик схемы витрины неизвестен: $schema {declared!r}")
    return kind


def problems(facts: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Расхождения файла со схемой: путь поля и что не так, по порядку путей.

    Черновик — по `$schema` самой схемы; испорченная схема — `NotRun`.
    """
    kind = draft_of(schema)
    try:
        kind.check_schema(schema)
        validator = kind(schema, format_checker=kind.FORMAT_CHECKER)
        errors = sorted(validator.iter_errors(facts), key=lambda error: list(error.absolute_path))
    except jsonschema.exceptions.SchemaError as exc:
        raise NotRun(f"схема витрины испорчена: {exc.message}") from exc
    except Unresolvable as exc:
        raise NotRun(f"ссылка в схеме витрины не разрешилась: {exc}") from exc
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<корень>'}: {error.message}"
        for error in errors
    ]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: один файл фактов против прибитой схемы."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", type=Path, help="собранный facts.json")
    parser.add_argument("--schema", default=SCHEMA_URL, help="адрес схемы витрины")
    parser.add_argument(
        "--verdict", type=Path, help=f"файл, куда на отказе пишется «{VERDICT_REJECTED}»"
    )
    args = parser.parse_args(argv)
    try:
        outcome = judge(args.facts, args.schema)
    # Непредвиденный сбой гейта — не «отказ» (1), а исход 2: см. докстроку модуля.
    except Exception as exc:
        print(
            f"сверка не отработала: непредвиденный сбой {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    if outcome == EXIT_REJECTED and args.verdict:
        # Вердикт не записался — отказ называется вслух, а не тонет в общем
        # перехвате под видом «непредвиденного сбоя» (взгляд на #1120).
        try:
            args.verdict.write_text(VERDICT_REJECTED, encoding="utf-8")
        except OSError as exc:
            print(
                f"сверка отклонена, но вердикт не записан в {args.verdict}: {exc}", file=sys.stderr
            )
    return outcome


def judge(facts_path: Path, schema_url: str) -> int:
    """Сверка одного файла: исход по правилу 039; непредвиденное ловит `main`."""
    try:
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NotRun(f"файл фактов не прочитан ({facts_path}): {exc}") from exc
        # Принадлежность проверяется у прибитого адреса: чужой `--schema`
        # называет себя сам и коммитом витрины не прикрывается.
        if schema_url == SCHEMA_URL:
            pinned_on_trunk(SCHEMA_SHA, ghrest.token_from_env())
        found = problems(facts, read_schema(schema_url))
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except Foreign as exc:
        print(f"сверка отклонена: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    against = f"коммит {SCHEMA_SHA[:7]}" if schema_url == SCHEMA_URL else schema_url
    if found:
        print(f"facts.json не отвечает схеме витрины ({len(found)}), {against}:", file=sys.stderr)
        for line in found[:SHOWN]:
            print(f"  {line}", file=sys.stderr)
        if len(found) > SHOWN:
            print(f"  …и ещё {len(found) - SHOWN}", file=sys.stderr)
        return EXIT_REJECTED
    print(f"facts.json отвечает схеме витрины: {against}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
