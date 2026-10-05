#!/usr/bin/env python3
"""База находок для анализа: SQLite, собранная из архива. Источник остаётся JSON.

РЕШЕНИЕ ВЛАДЕЛЬЦА 05.10.2026 (#1136, задача #1139). Архив находок
(`findings.json` на ветке `badges`) — единственный источник: один писатель,
история в git, чтение по ссылке без учётных данных. Вопросы анализа — какой
род повторяется у какой роли, какие места получают находки заход за заходом —
решались разовыми сценариями. Здесь они становятся запросами SQL к базе,
которая собирается из архива и НИКУДА НЕ КОММИТИТСЯ: второй источник тех же
записей разошёлся бы с первым молча (022).

ТОЛЬКО СТАНДАРТНАЯ БИБЛИОТЕКА (`sqlite3`). Новая зависимость потянула бы
границы версий в строки установки прогонов (073). DuckDB — необязательный
способ читать тот же JSON напрямую, без этой сборки.

НЕСКОЛЬКО АРХИВОВ — ОДНА БАЗА. У каждой записи столбец `repo` (из поля
`repo` архива), поэтому архивы соседей по семье ложатся рядом. Два архива
одного проекта — отказ: какой из них верен, сборка не решает.

СБОРКА ПОВТОРЯЕМА. База каждый раз собирается заново во временный файл и
подменяет прежнюю целиком: дублей от повторного захода нет, а сбой посередине
не оставляет полубазы.

Как собрать и спросить:

    git show origin/badges:.github/badges/findings.json > findings.json
    python scripts/findings_db.py --out findings.sqlite findings.json
    sqlite3 findings.sqlite "SELECT rod, role, count(*) FROM findings
        WHERE rod IS NOT NULL GROUP BY rod, role ORDER BY 3 DESC LIMIT 10"
    sqlite3 findings.sqlite "SELECT place, count(DISTINCT pr) FROM findings
        GROUP BY place HAVING count(DISTINCT pr) > 2 ORDER BY 2 DESC"
    sqlite3 findings.sqlite "SELECT fix_check, count(*) FROM resolutions GROUP BY 1"
    sqlite3 findings.sqlite "SELECT rule, rod, count(*) FROM finding_rules
        WHERE rule IS NOT NULL GROUP BY rule, rod ORDER BY 3 DESC"

ПРАВИЛО У НАХОДКИ — ЧЕРЕЗ ЕЁ РОД, И ЭТО ГРАНИЦА, А НЕ УПРОЩЕНИЕ (195).
Архив знает судьбу РОДА: ответ каталогу («есть» с номером правила,
«предложено» со слагом, «своё») и выросшие механизмы. Поле `правило` у
находки — копия судьбы её рода, и вторым столбцом в базу не кладётся.
Представление `finding_rules` связывает находку с правилом через род. Чего
оно НЕ говорит: что правило РОДИЛОСЬ из этих находок. «Есть» значит «род
держит правило N каталога», а родилось ли N здесь или стояло до рода, архив
не хранит — это знает только история `.rules/proposals.json`, и прозой.

В ПРЕДСТАВЛЕНИИ — КАЖДАЯ НАХОДКА С РОДОМ, И ТОЛЬКО ОНИ (взгляд на #1154,
`f86b56c`). Находка без рода в него не входит: правила у неё нет по
определению. Находка, чей род в разделе родов архива не записан (встреча
строкой «Род:», а род ещё не заведён), остаётся с пустыми `verdict` и
`rule`, а не выпадает молча: «род без ответа каталогу» и «находки нет» —
разные ответы.

Исходы (правило 039): ``0`` база собрана · ``2`` не собрана — архив не
прочитан, форма чужая или проект повторён; причина названа.
"""

import argparse
import os
import sqlite3
import sys
import tempfile
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any, Final

import finding_kinds
import findings
import findings_archive

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Формы архива, которые сборка понимает. Версию держит сборщик архива, и
#: здесь она не пишется второй раз: поднял форму там — сборка откажет, пока её
#: не научат новой, а не соберёт молча то, чего не знает (045).
SUPPORTED: Final = frozenset({findings_archive.SCHEMA})
#: ФОРМА ПРОВЕРЯЕТСЯ ЦЕЛИКОМ, ПО ПЕРЕЧНЮ, А НЕ ПОЛЕ ЗА ПОЛЕМ (210, взгляд на
#: #1154): у сборщика архива та же сверка чинилась трижды по одному полю
#: (#830), и здесь она взята оттуда же — `findings_archive.misshapen`, а форма
#: снятия — его `RESOLUTION_SHAPE` (022). Перечни ниже — поля, которые
#: ложатся в столбцы, с типами; замер 05.10.2026 по живому архиву: 2166
#: находок, 2347 снятий, 22 рода — у всех ровно эти типы.
#: Части архива: каждая обязана быть словарём записей.
PARTS: Final = ("findings", "resolutions", "kinds")
#: Находка: поля со своим типом.
FINDING_SHAPE: Final[dict[str, type]] = {
    "pr": int,
    "seen_on": list,
    "weight": str,
    "kind": str,
    "role": str,
    "title": str,
    "place": str,
    "checked": str,
    "twin_of": str,
}
#: Род: поля со своим типом.
KIND_SHAPE: Final[dict[str, type]] = {"встреч": int, "породил": list}
#: Поля, которые бывают `null`: ключ обязан стоять, значение — тип или `null`.
NULLABLE: Final[dict[str, dict[str, type]]] = {
    "findings": {"resolved_by": int, "род": str},
    "resolutions": {},
    "kinds": {"каталогу": dict},
}
SHAPES: Final[dict[str, dict[str, type]]] = {
    "findings": FINDING_SHAPE,
    "resolutions": findings_archive.RESOLUTION_SHAPE,
    "kinds": KIND_SHAPE,
}
#: Таблицы базы, по которым печатается счёт строк.
TABLE_NAMES: Final = ("projects", "findings", "seen_on", "resolutions", "kinds", "kind_spawned")
#: Схема базы. Ключи составные: отпечаток уникален внутри проекта, а не семьи.
TABLES: Final = """
CREATE TABLE projects (
    repo TEXT PRIMARY KEY, schema TEXT NOT NULL, generated_at TEXT NOT NULL
);
CREATE TABLE findings (
    repo TEXT NOT NULL, mark TEXT NOT NULL, pr INTEGER, weight TEXT, kind TEXT,
    role TEXT, title TEXT, place TEXT, checked TEXT, resolved_by INTEGER,
    twin_of TEXT, rod TEXT, PRIMARY KEY (repo, mark)
);
CREATE TABLE seen_on (
    repo TEXT NOT NULL, mark TEXT NOT NULL, pr INTEGER NOT NULL,
    PRIMARY KEY (repo, mark, pr)
);
CREATE TABLE resolutions (
    repo TEXT NOT NULL, mark TEXT NOT NULL, by_pr INTEGER, twin_of TEXT,
    fix_check INTEGER NOT NULL, PRIMARY KEY (repo, mark)
);
CREATE TABLE kinds (
    repo TEXT NOT NULL, name TEXT NOT NULL, meetings INTEGER, verdict TEXT,
    rule TEXT, said TEXT, PRIMARY KEY (repo, name)
);
CREATE TABLE kind_spawned (
    repo TEXT NOT NULL, kind TEXT NOT NULL, mechanism TEXT NOT NULL,
    PRIMARY KEY (repo, kind, mechanism)
);
CREATE VIEW finding_rules AS
    SELECT f.repo, f.mark, f.pr, f.role, f.weight, f.rod, k.verdict, k.rule
    FROM findings AS f LEFT JOIN kinds AS k ON k.repo = f.repo AND k.name = f.rod
    WHERE f.rod IS NOT NULL;
"""


class NotRun(RuntimeError):
    """База не собрана: третий исход, а не пустая база."""


def checked_archive(path: Path) -> dict[str, Any]:
    """Архив с диска, сверенный по форме, которую сборка понимает."""
    try:
        archive = findings.read_archive(path)
    except ValueError as exc:
        raise NotRun(f"{path}: {exc}") from exc
    schema = archive.get("schema")
    if schema not in SUPPORTED:
        raise NotRun(
            f"{path}: форма архива {schema!r} не знакома сборке "
            f"(понимает {', '.join(sorted(SUPPORTED))})"
        )
    for key in ("repo", "generated_at", *PARTS):
        if key not in archive:
            raise NotRun(f"{path}: в архиве нет ключа {key!r}")
    for part in PARTS:
        if not isinstance(archive[part], dict):
            raise NotRun(f"{path}: `{part}` не словарь записей")
        for mark, entry in archive[part].items():
            if said := misshapen_record(entry, SHAPES[part], NULLABLE[part]):
                raise NotRun(f"{path}: {part} {mark} — {said}")
    return archive


def misshapen_record(entry: Any, shape: dict[str, type], nullable: dict[str, type]) -> str:
    """Чем запись расходится с формой части; пустая строка — не расходится.

    Обязательные поля судит `findings_archive.misshapen`; поле из `nullable`
    обязано стоять, а значение — быть своего типа или `null`.
    """
    if said := findings_archive.misshapen(entry, shape):
        return said
    for field, kind in nullable.items():
        if field not in entry:
            return f"нет поля `{field}`"
        value = entry[field]
        if value is not None and (not isinstance(value, kind) or isinstance(value, bool)):
            return f"`{field}` не {kind.__name__} и не null"
    return ""


def fate_row(body: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Ответ рода каталогу столбцами: вид, номер правила, сказанное.

    Номер берётся тем же разбором, что у словаря родов
    (`finding_kinds.RULE_NUMBER_RE`, три цифры первым словом), и только у вида
    «есть»: у «предложено» номера ещё нет — его присваивает каталог при приёме.
    """
    fate = body.get("каталогу")
    if not isinstance(fate, dict):
        return None, None, None
    verdict, said = fate.get("вид"), str(fate.get("сказано") or "")
    number = finding_kinds.RULE_NUMBER_RE.match(said) if verdict == "есть" else None
    return verdict, number.group() if number else None, said or None


def fill(db: sqlite3.Connection, archive: dict[str, Any]) -> None:
    """Кладёт один архив в базу; проект, уже лежащий в ней, — отказ."""
    repo = str(archive["repo"])
    try:
        db.execute(
            "INSERT INTO projects VALUES (?, ?, ?)",
            (repo, archive["schema"], archive["generated_at"]),
        )
    except sqlite3.IntegrityError as exc:
        raise NotRun(f"проект {repo} передан дважды — какой архив верен, сборка не решает") from exc
    entries = archive["findings"]
    db.executemany(
        "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                repo,
                mark,
                one["pr"],
                one["weight"],
                one["kind"],
                one["role"],
                one["title"],
                one["place"],
                one["checked"],
                one["resolved_by"],
                one["twin_of"],
                one["род"],
            )
            for mark, one in entries.items()
        ],
    )
    db.executemany(
        "INSERT OR IGNORE INTO seen_on VALUES (?, ?, ?)",
        [(repo, mark, pr) for mark, one in entries.items() for pr in one["seen_on"]],
    )
    db.executemany(
        "INSERT INTO resolutions VALUES (?, ?, ?, ?, ?)",
        [
            (repo, mark, one.get("by"), one.get("twin_of"), int(bool(one.get("fix_check"))))
            for mark, one in archive["resolutions"].items()
        ],
    )
    db.executemany(
        "INSERT INTO kinds VALUES (?, ?, ?, ?, ?, ?)",
        [(repo, name, one.get("встреч"), *fate_row(one)) for name, one in archive["kinds"].items()],
    )
    db.executemany(
        "INSERT OR IGNORE INTO kind_spawned VALUES (?, ?, ?)",
        [
            (repo, name, str(mechanism))
            for name, one in archive["kinds"].items()
            for mechanism in one.get("породил") or []
        ],
    )


def build(archives: Iterable[Path], out: Path) -> dict[str, int]:
    """Собирает базу заново и подменяет `out` целиком; отдаёт счёт строк по таблицам."""
    read = [checked_archive(path) for path in archives]
    out.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(suffix=".sqlite", dir=out.parent)
    os.close(handle)
    try:
        # `closing` закрывает и на отказе; сам `with` соединения только
        # фиксирует транзакцию и файл оставляет открытым.
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript(TABLES)
            for archive in read:
                fill(db, archive)
            counts = {
                table: int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                for table in TABLE_NAMES
            }
        os.replace(temporary, out)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return counts


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает базу и печатает, сколько строк легло в каждую таблицу."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path, help="архивы findings.json")
    parser.add_argument("--out", type=Path, required=True, help="куда положить базу SQLite")
    args = parser.parse_args(argv)
    try:
        counts = build(args.archives, args.out)
    except (NotRun, sqlite3.Error, OSError) as exc:
        print(f"база не собрана: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print(f"база собрана: {args.out}")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
