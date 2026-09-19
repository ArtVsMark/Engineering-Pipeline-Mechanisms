#!/usr/bin/env python3
"""Роды находок: что повторяется и чем это закрыто.

Находка разбирается поштучно и уходит из реестра вместе с починкой — а КЛАСС
ошибки остаётся и приходит снова под другим адресом. Третий случай одного рода
неотличим от первого, пока роды живут в памяти окна
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

ПОЧЕМУ РОД НАЗЫВАЕТ ЧЕЛОВЕК, А НЕ РАЗБОР. Классификатор пробовался и ОТВЕРГНУТ
замером 18.09.2026: из 73 находок на 60 слитых изменениях разбор по словам
опознал 21, по адресу файла — 32 при наибольшем повторе 4. Механизм на таком
признаке угадывал бы, а проверка, отвергающая верное, не держит ничего
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
Род называет тот, кто разобрал находку; здесь считаются повторы и проверяется
форма.

ВСТРЕЧА НАЗЫВАЕТ СВОЁ ПРОИСХОЖДЕНИЕ, и это не украшение счёта. Отпечаток —
находка внешнего взгляда: род ДОШЁЛ до общей ветки. Запись «окно: <адрес>» —
тот же род, пойманный собственным откатом до толчка. Совокупности разные, и
слитые в одно число они врут в обе стороны: до 18.09.2026 поле принимало только
отпечатки, то есть род, дважды пойманный в окне, выглядел встреченным ноль раз
и порога не достигал никогда.

К ПОРОГУ ИДУТ ОБЕ, А СОСТАВ ПЕЧАТАЕТСЯ. Порог отвечает на вопрос «род жив и не
держится ничем», а не «род проскочил ревью»: пойманный в окне стоит работы
каждый раз, и держит его дисциплина, то есть человек, — ровно то состояние,
которое правило 002 называет правилом без механизма. Но и уравнивать их нельзя:
род, встречаемый только в окне, до общей ветки не доходил ни разу, и это меняет
срочность, а не наличие долга. Поэтому счёт один, а состав виден.

ПРОШЛЫЕ ВСТРЕЧИ В ОКНЕ НЕ ВОССТАНАВЛИВАЮТСЯ. Их след живёт в памяти окна, а не
в дереве, и выписать их «по воспоминанию» значит вписать число, которого никто
не мерил
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
Счёт таких встреч начат днём, когда форма их приняла.

ЧТО СЧИТАЕТСЯ ДОЛГОМ. Род, встреченный **трижды и чаще** и не закрытый
механизмом, — вход в гейт или в предложение правила каталогу. Механизм его
НАЗЫВАЕТ и не краснеет: решение, строить ли гейт, остаётся человеку, а проверка,
краснеющая на законном, приучает себя обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

Исходы (правило 039): ``0`` роды названы · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

import paths

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Со скольких встреч род считается повторяющимся. Два — совпадение, три — ряд:
#: то же число, которым проект отделяет случай от повадки в разборе миганий.
REPEATED_AT: Final = 3
#: Слово, которым род говорит «механизма нет». Причина обязательна рядом (154).
NO_MECHANISM: Final = "нет"
#: Приставка встречи, пойманной в окне до толчка. Отпечатка у неё нет и быть не
#: может: находка внешнего взгляда живёт в реестре #23 и опознаётся хешем, а эта
#: до общей ветки не дошла. Вместо хеша — адрес места, где род себя показал.
IN_WINDOW: Final = "окно: "
#: Поле «что из рода ВЫРОСЛО»: заведённый гейт, предложенное правило, навык.
#: Отдельно от «чем закрыт»: род бывает закрыт чужим, давно стоявшим механизмом,
#: а бывает — тем, который из него и родился. Разница видна только если её
#: записать: иначе повторный род выглядит бесплодным, хотя из него вышло правило.
BORN: Final = "породил"


class NotRun(RuntimeError):
    """Механизм не отработал: третий исход, а не «родов нет»."""


def read(path: Path | None = None) -> dict[str, Any]:
    """Объявленные роды находок."""
    where = path or paths.FINDING_KINDS
    if not where.is_file():
        raise NotRun(f"нет {where}: роды находок взять неоткуда (075)")
    said = json.loads(where.read_text(encoding="utf-8"))
    kinds = said.get("kinds")
    if not kinds:
        raise NotRun(f"{where}: раздел kinds пуст — предмет счёта не найден (075)")
    return dict(kinds)


def origins(body: dict[str, Any]) -> tuple[int, int]:
    """Состав встреч рода: сколько пришло взглядом, сколько поймано в окне.

    Считается СЛОЖЕНИЕМ из самих записей, а не вторым списком рядом: два списка
    одного разошлись бы молча
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    met = [str(one) for one in (body.get("встречен") or [])]
    in_window = sum(1 for one in met if one.startswith(IN_WINDOW))
    return len(met) - in_window, in_window


def said_no(held: str) -> bool:
    """Говорит ли поле «закрыт» слово «нет» — ЦЕЛЫМ словом, а не приставкой.

    `startswith("нет")` читает «нетронутый» и «нетривиально» как объявление
    отсутствия механизма: род с живым механизмом ушёл бы в долг по первой букве.
    «Нет-нет» в этот список НЕ входит — там первое слово и есть «нет», то есть
    отказ настоящий; разделитель слов здесь дефис, и разбор обязан его знать
    ([141](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/141-a-marker-is-matched-whole-not-by-prefix.md)).
    """
    first = re.split(r"[^\w]+", held.strip().lower(), maxsplit=1)[0]
    return first == NO_MECHANISM


def repeated(kinds: dict[str, Any]) -> list[tuple[str, int]]:
    """Роды, встреченные не реже :data:`REPEATED_AT` раз, — от частых к редким."""
    counted = [(name, len(body.get("встречен") or [])) for name, body in kinds.items()]
    return sorted(
        ((name, times) for name, times in counted if times >= REPEATED_AT),
        key=lambda one: (-one[1], one[0]),
    )


def unheld(kinds: dict[str, Any]) -> list[tuple[str, int]]:
    """Повторяющиеся роды, которые не закрыты механизмом, — это и есть долг."""
    return [
        (name, times)
        for name, times in repeated(kinds)
        if said_no(str(kinds[name].get("закрыт", "")))
    ]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает роды, повторы и долг."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kinds", default=None, help="объявление родов вместо дерева")
    args = parser.parse_args(argv)
    try:
        kinds = read(Path(args.kinds) if args.kinds else None)
    except NotRun as refusal:
        print(f"роды не сосчитаны: {refusal}", file=sys.stderr)
        return EXIT_BROKEN
    except ValueError as refusal:
        print(f"роды не сосчитаны: {refusal} (075)", file=sys.stderr)
        return EXIT_BROKEN

    meetings = sum(len(body.get("встречен") or []) for body in kinds.values())
    print(f"родов {len(kinds)}, встреч {meetings}")
    for name, body in sorted(kinds.items(), key=lambda one: -len(one[1].get("встречен") or [])):
        times = len(body.get("встречен") or [])
        held = str(body.get("закрыт", "")).strip()
        mark = "—" if said_no(held) else "держится"
        born = [str(one) for one in (body.get(BORN) or [])]
        seen, caught = origins(body)
        split = f" (взгляд {seen}, окно {caught})" if caught else ""
        print(f"  {times:>2}  {name}{split}  [{mark}]")
        if born:
            print(f"      породил: {'; '.join(born)}")

    debt = unheld(kinds)
    if not debt:
        print(f"\nповторяющихся родов без механизма нет (порог — {REPEATED_AT} встречи)")
        return EXIT_OK
    print(f"\nПОВТОРЯЕТСЯ И НЕ ДЕРЖИТСЯ НИЧЕМ (от {REPEATED_AT} встреч):")
    for name, times in debt:
        seen, caught = origins(kinds[name])
        split = f" (взгляд {seen}, окно {caught})" if caught else ""
        print(f"  {times}× {name}{split}")
        print(f"      {kinds[name].get('признак', '')}")
    print(
        "\nТакой род — вход в гейт или в предложение правила каталогу."
        "\nРешение за человеком: механизм называет величину и не краснеет (051)."
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — точка входа процессом
    raise SystemExit(main())
