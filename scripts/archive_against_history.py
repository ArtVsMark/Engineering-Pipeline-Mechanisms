#!/usr/bin/env python3
"""Архив находок сверяется с историей общей ветки — приёмка строже чинимого (193).

ЗАЧЕМ (#864). Перечитка архива (`findings_archive.py --reread`) — массовая
автоматическая починка данных: за один проход она дописала 107 снятий и
связей. Приёмка у неё была «тест на синтетике и второй проход с нулём». Второй
проход доказывает идемпотентность, но не верность: ошибись разбор строки
снятия — повторный проход тем же разбором тоже дал бы ноль.

КРИТЕРИЙ СТРОЖЕ — НЕЗАВИСИМЫЙ ЧИТАТЕЛЬ ТОГО ЖЕ ИСТОЧНИКА. Общий разбор снятий
(`changerefs.resolutions_parsed`) здесь не зовётся; общими остаются только
СЛОВА строки (`changerefs.RESOLVED_WORD`, `TWIN_WORD`), чтобы переименование
маркера не развело сверку с разбором молча (209). Сверка идёт по телам
коммитов общей ветки самым прямым способом —

* строкой снятия считается строка, начинающаяся со слова снятия с двоеточием,
  как у разбора: цитата синтаксиса внутри прозы снятием не является;
* снятие подтверждено, если отпечаток стоит в такой строке целым словом —
  семь знаков, не часть более длинного хеша;
* связь «A дубль B» подтверждена, если оба стоят в такой строке РЯДОМ и между
  ними только слово «дубль».

Правило смежности нарочно проще грамматики разбора: там, где они расходятся,
неправ может быть любой, и расхождение называется числом, а не сглаживается.

ЗАМЕР 26.09.2026 НА НАСТОЯЩЕМ АРХИВЕ (ветка `badges`): снятий 1255, без строки
в истории — 0; связей 107, не подтверждено 11. Все 11 — одна форма: строка
«A дубль B, C дубль D», которую общий разбор читает цепочкой через запятую и
приписывает двойника цели. Чинит это #872.

ПРИЁМКА НАБЛЮДАЕТ, А НЕ ОСТАНАВЛИВАЕТ, и это названо, а не скрыто. Неверная
перечитка публикуется всё равно; сверка кладёт в архив список неподтверждённого
(`unconfirmed`) и предупреждает только о НОВОМ по сравнению с прежним архивом —
иначе известные расхождения жгли бы предупреждение на каждом слиянии, и новое
стало бы лишь другим числом (051).

ПРЕДЕЛ НАЗВАН. Снятие проверкой починки (#848) строки снятия не имеет — его
источник лента изменения, а не история. Архив помечает его `fix_check`, и
сверка считает такие отдельной строкой, а не расхождением.

Исходы (правило 039): ``0`` нового расхождения нет · ``2`` не отработал ·
``3`` новое расхождение есть и названо.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import changerefs

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_DIFFERS: Final = 3

#: Сколько расхождений печатать поимённо: остальное — числом.
SHOWN: Final = 20
#: Поле архива, куда сверка кладёт неподтверждённое: следующая сверка сравнивает с ним.
UNCONFIRMED: Final = "unconfirmed"


class NotRun(RuntimeError):
    """Сверка не отработала: третий исход, а не «сходится»."""


def resolution_lines(log: str) -> list[str]:
    """Строки снятия всех тел — прямым чтением: слово снятия с двоеточием в начале строки."""
    head = changerefs.RESOLVED_WORD.lower()
    return [line for line in log.splitlines() if line.strip().lower().startswith(head)]


def mark_said(lines: str, mark: str) -> bool:
    """Стоит ли отпечаток в строках снятия целым словом, а не куском длинного хеша."""
    return re.search(rf"(?<![0-9a-f]){mark}(?![0-9a-f])", lines) is not None


#: Отпечаток строки снятия, как его пишут: семь знаков, возможно в кавычках.
MARK: Final = r"`?[0-9a-f]{7}(?![0-9a-f])`?"


def pairs_in(line: str) -> set[tuple[str, str]]:
    """Связи «источник → цель», которые строка называет, — прямым чтением.

    Цель — отпечаток сразу после слова «дубль». Источники — список сразу перед
    ним, с теми же разделителями, что у разбора: запятая, точка с запятой,
    пробел (`changerefs.MARK_RUN_RE`, взгляд на #876). Если список сам
    начинается сразу после «дубль», его первый отпечаток — цель предыдущей
    связи, а не источник; но одиночный отпечаток там источник цепочки
    («A дубль B дубль C»).
    """
    word = changerefs.TWIN_WORD
    found: set[tuple[str, str]] = set()
    pattern = re.compile(
        rf"(?P<pre>{word}\s+)?(?P<src>{MARK}(?:[\s,;]+{MARK})*)(?=\s+{word}\s+(?P<dst>{MARK}))",
        re.IGNORECASE,
    )
    for match in pattern.finditer(line):
        sources = changerefs.MARK_RE.findall(match["src"].lower())
        if match["pre"] and len(sources) > 1:
            sources = sources[1:]
        target = changerefs.MARK_RE.findall(match["dst"].lower())[0]
        found |= {(source, target) for source in sources}
    return found


def twin_said(lines: str, mark: str, twin: str) -> bool:
    """Называет ли какая-либо строка снятия связь «mark дубль twin»."""
    return any((mark, twin) in pairs_in(line) for line in lines.splitlines())


def check(archive: dict[str, Any], log: str) -> dict[str, list[str]]:
    """Расхождения архива с историей: снятия без строки и связи без пары."""
    text = "\n".join(resolution_lines(log))
    resolutions: dict[str, dict[str, Any]] = archive.get("resolutions") or {}
    from_history = {mark: said for mark, said in resolutions.items() if not said.get("fix_check")}
    unseen = sorted(mark for mark in from_history if not mark_said(text, mark))
    unpaired = sorted(
        f"{mark} {changerefs.TWIN_WORD} {said['twin_of']}"
        for mark, said in from_history.items()
        if said.get("twin_of") and not twin_said(text, mark, str(said["twin_of"]))
    )
    return {"без строки": unseen, "связь без пары": unpaired}


def fresh(found: dict[str, list[str]], before: list[str]) -> list[str]:
    """Расхождения, которых не было в прежнем архиве: о них и предупреждение."""
    known = set(before)
    return [item for items in found.values() for item in items if item not in known]


def trunk_log(ref: str) -> str:
    """Тела всех коммитов общей ветки."""
    done = subprocess.run(
        ["git", "log", ref, "--format=%B"], capture_output=True, text=True, encoding="utf-8"
    )
    if done.returncode != 0 or not done.stdout.strip():
        raise NotRun(f"история {ref} не прочитана: {done.stderr.strip() or 'пусто'} (075)")
    return done.stdout


def read(path: Path) -> dict[str, Any]:
    """Архив из файла; нет файла — отказ."""
    if not path.is_file():
        raise NotRun(f"архива {path} нет — сверять нечего (075)")
    said: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return said


def main(argv: list[str] | None = None) -> int:
    """Точка входа: счёт сверки, список в архив, аннотация о новом расхождении."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, help="findings.json архива; сюда же пишется")
    parser.add_argument("--previous", default="", help="прежний архив: с чем сравнивать новое")
    parser.add_argument("--ref", default="origin/main", help="общая ветка")
    args = parser.parse_args(argv)
    try:
        path = Path(args.archive)
        archive = read(path)
        if not archive.get("resolutions"):
            raise NotRun("в архиве нет снятий — пустой вход, а не «сходится» (075)")
        before: list[str] = []
        if args.previous and Path(args.previous).is_file():
            before = list(read(Path(args.previous)).get(UNCONFIRMED) or [])
        found = check(archive, trunk_log(args.ref))
    except (NotRun, OSError, ValueError) as refusal:
        print(f"сверка архива не отработала: {refusal}", file=sys.stderr)
        return EXIT_BROKEN
    resolutions = archive["resolutions"]
    twins = sum(1 for said in resolutions.values() if said.get("twin_of"))
    by_fix = sum(1 for said in resolutions.values() if said.get("fix_check"))
    print(
        f"снятий {len(resolutions)} (из них проверкой починки {by_fix}), без строки в "
        f"истории {len(found['без строки'])}; связей {twins}, без пары "
        f"{len(found['связь без пары'])}"
    )
    for kind, items in found.items():
        for item in items[:SHOWN]:
            print(f"  {kind}: {item}")
        if len(items) > SHOWN:
            print(f"  {kind}: ещё {len(items) - SHOWN}")
    archive[UNCONFIRMED] = sorted(item for items in found.values() for item in items)
    path.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    new = fresh(found, before)
    if not new:
        return EXIT_OK
    print(
        f"::warning title=архив находок: новое расхождение с историей (193)::"
        f"новых {len(new)}: {', '.join(new[:SHOWN])} — см. вывод шага"
    )
    return EXIT_DIFFERS


if __name__ == "__main__":
    raise SystemExit(main())
