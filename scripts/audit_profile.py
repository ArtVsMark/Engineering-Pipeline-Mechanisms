#!/usr/bin/env python3
"""Порядок перечитывания ответов: чем ответ дальше от своего правила, тем раньше.

Ответов у проекта больше двух сотен, и читать их подряд — проход, который не
кончается и не отчитывается. Нужен ПОРЯДОК, и он обязан быть замером, а не
интуицией: перечитывание идёт сверху вниз и останавливается, когда отдача пачки
упала
([207](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/207-a-reread-pass-is-ordered-and-stopped-by-measurement.md)).

ЧЕМ МЕРЯЕТСЯ ПОДОЗРЕНИЕ. Долей корней притязания правила, встреченных в тексте
ответа. Низкая доля означает, что ответ говорит НЕ О ТОМ, о чём правило: чаще
всего он отвечает на край притязания, а середину оставляет неназванной. Признак
грубый и назван таковым: он не судит верность ответа и не может — он лишь
ставит вперёд то, что стоит прочесть раньше.

ЗАМЕР 18.09.2026, РАДИ КОТОРОГО ПОРЯДОК И ЗАВЕДЁН. По полосам подозрения за одну
смену сверен 101 ответ из 207 — вдвое больше, чем накануне проходом по номерам
(41). Полоса 0–10 % дала семь правок из девяти прочитанных; полоса 10–20 % на
тридцати двух ответах — шесть новых гейтов и четыре механизма, поднятых с
внимательности до гейта. Два ответа оказались прямо ложными: они отрицали
предмет, который в дереве уже был.

ЧЕГО ЭТОТ МЕХАНИЗМ НЕ ДЕЛАЕТ. Он не читает ответы и не выносит вердикта — он
называет ПОРЯДОК и отмечает, что уже сверено. Сверенным считается ответ с датой
`analysed`: состояние берётся из живого артефакта, а не из отдельного списка,
который надо не забыть обновить
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

ПРОХОД БЫВАЕТ НЕ ПЕРВЫМ. Когда поднят контракт или назначен аудит (#829),
перечитать надо и уже сверенное: ответ, прочитанный 18.09.2026, не прочитан
под правила, принятые позже. Поэтому `--since ДАТА` считает сверенным только
ответ, чей `analysed` не раньше этой даты (157); без ключа — любой с датой.

Исходы (правило 039): ``0`` профиль построен · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Final

import catalogue
import finding_kinds
import paths

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Длина корня: слова короче отбрасываются целиком, длиннее — режутся до него.
#: Пять знаков выбраны потому, что русская словоформа расходится с основой
#: обычно в окончании, а не раньше; значение грубое и названо грубым.
STEM: Final = 5
#: Слова, которые есть в любом тексте и потому ни о чём не говорят. Список
#: закрытый: предикат по прозе иначе не построить (046). Держится СТРОКОЙ, а не
#: перечислением по элементу: семьдесят строк по слову — налог на чтение при
#: каждом заходе в модуль, и платит его читатель, которому до этого списка дела
#: нет (029).
_STOPWORDS_SAID: Final = """
и в на не с что а как из по для это его она они мы вы то же ни но или если так
там где тот та те был была были быть есть нет ее её их наш наша свой своя своё
при до от за над под через без про между уже ещё еще только даже всё все весь
вся может можно должен должна должно надо нужно чем чего чему кто кого чей
когда почему один одна одно два три оно об обо сам сама само себя себе тем том
тому этом этой этого
"""
STOPWORDS: Final = frozenset(_STOPWORDS_SAID.split())

WORD: Final = re.compile(r"[а-яёa-z]{4,}")


class NotRun(RuntimeError):
    """Механизм не отработал: третий исход, а не пустой профиль."""


#: ЧТО ПРОФИЛЬ ЧИТАЕТ — ЦЕЛИКОМ, А НЕ ПО ФОРМЕ ЗА РАЗ (210, третий заход по
#: месту: #900, #902 и поздний взгляд на #902). Из правила выгрузки: `id`
#: (любой, берётся строкой), `slug`, `claim.ru`, `title.ru` — строки. Из
#: ответа проекта: `status` — строка или его нет, `mechanism` — строка, пусто
#: или его нет, `analysed` — дата ГГГГ-ММ-ДД, пусто или его нет: сравнивается
#: она строкой с `--since`, и чужая форма («2026/09/01», число) засчитывалась бы
#: сверенной молча (поздний взгляд на #908). Остальные поля ответа
#: профиль читает лишь строками (`suspicion`) и форме их не подчиняет.
RULE_TEXT_FIELDS: Final = ("claim", "title")
#: Начала отказов по форме: тесты узнают их по константам, а не по буквам (209).
EXPORT_SHAPE_SAID: Final = "выгрузка каталога не той формы"
RULE_SHAPE_SAID: Final = "правило выгрузки не той формы"
ANSWER_SHAPE_SAID: Final = "ответ проекта не той формы"
UNPARSED_SAID: Final = "не разбирается"
SILENT_SAID: Final = "каталог молчит — выгрузку взять неоткуда"


def stems(text: str) -> set[str]:
    """Корни значимых слов текста — грубо, обрезкой до :data:`STEM` знаков."""
    return {word[:STEM] for word in WORD.findall(text.lower()) if word not in STOPWORDS}


def suspicion(rule: dict[str, Any], answer: dict[str, Any]) -> float:
    """Доля корней притязания, встреченных в ответе. Меньше — подозрительнее."""
    claim = stems(rule["claim"]["ru"]) | stems(rule["title"]["ru"])
    if not claim:
        raise NotRun(f"{rule['id']}: у правила пустое притязание — мерить нечем (075)")
    said = stems(" ".join(str(v) for v in answer.values() if isinstance(v, str)))
    return len(claim & said) / len(claim)


def export_rules(export: object) -> dict[str, dict[str, Any]]:
    """Правила выгрузки каталога по номеру; чужая форма — отказ `NotRun`, а не трасса.

    Путь выгрузки любой (`--export`), и форма проверяется ровно та, которой
    пользуется профиль (перечень — у `RULE_TEXT_FIELDS`): выгрузка — объект,
    `rules` — список, правило — объект с `id` и строками `slug`, `claim.ru`,
    `title.ru` (взгляды на #902 и поздний на #902: `"ru": null` ронял `stems`).
    """
    rules = export.get("rules") if isinstance(export, dict) else None
    if not isinstance(rules, list):
        raise NotRun(f"{EXPORT_SHAPE_SAID}: ожидался объект со списком rules (075)")
    found: dict[str, dict[str, Any]] = {}
    for one in rules:
        whole = (
            isinstance(one, dict)
            and "id" in one
            and isinstance(one.get("slug"), str)
            and all(
                isinstance(one.get(part), dict) and isinstance(one[part].get("ru"), str)
                for part in RULE_TEXT_FIELDS
            )
        )
        if not whole:
            raise NotRun(f"{RULE_SHAPE_SAID}: {str(one)[:80]} (075)")
        found[str(one["id"])] = one
    return found


def answers_whole(mine: dict[str, Any]) -> None:
    """Поля ответа, которые профиль печатает, — нужной формы; иначе отказ (поздний взгляд на #902).

    `status` печатается шириной и обязан быть строкой, `mechanism` — строкой или
    пустым: `None` в `status` ронял печать пачки трассой `TypeError`.
    """
    for number, answer in mine.items():
        status = answer.get("status", "")
        mechanism = answer.get("mechanism")
        if not isinstance(status, str) or not (mechanism is None or isinstance(mechanism, str)):
            raise NotRun(f"{ANSWER_SHAPE_SAID}: {number} — status/mechanism не строкой (075)")
        # НЕТ ПОЛЯ — ЭТО None ИЛИ "", а не любое ложное: `0`, `false` и `[]`
        # через `or ""` прошли бы без отказа (взгляд на #910).
        analysed = answer.get("analysed")
        if not (analysed in (None, "") or (isinstance(analysed, str) and is_iso_day(analysed))):
            raise NotRun(f"{ANSWER_SHAPE_SAID}: {number} — analysed не дата ГГГГ-ММ-ДД (075)")


def profile(export: dict[str, Any], mine: dict[str, Any], since: str = "") -> list[dict[str, Any]]:
    """Ответы, упорядоченные подозрением: самый дальний от своего правила первым.

    `since` — дата ISO: сверенным считается ответ, прочитанный не раньше неё.
    """
    rules = export_rules(export)
    if not rules:
        raise NotRun("в выгрузке каталога нет правил — предмет профиля не найден (075)")
    if not mine:
        raise NotRun("в ответах проекта нет записей — предмет профиля не найден (075)")
    answers_whole(mine)

    rows = [
        {
            "rule": number,
            "share": suspicion(rules[number], answer),
            "status": answer.get("status", ""),
            "mechanism": answer.get("mechanism") or "—",
            "looked": bool(answer.get("analysed")) and str(answer.get("analysed")) >= since,
            "slug": rules[number]["slug"],
        }
        for number, answer in mine.items()
        if number in rules
    ]
    if not rows:
        raise NotRun("ни один ответ не сошёлся с выгрузкой по номеру — сверять нечего (075)")
    rows.sort(key=lambda row: (row["share"], row["rule"]))
    return rows


def bands(rows: list[dict[str, Any]]) -> Counter[int]:
    """Сколько ответов в каждой десятипроцентной полосе подозрения."""
    return Counter(min(int(row["share"] * 10), 9) for row in rows)


def is_iso_day(said: str) -> bool:
    """Строка — дата строго ГГГГ-ММ-ДД. Одна проверка на обе стороны сравнения."""
    try:
        return date.fromisoformat(said).isoformat() == said
    except ValueError:
        return False


def iso_day(said: str) -> str:
    """Дата ключа `--since` строго ГГГГ-ММ-ДД: сравнивается она строкой.

    `2026/09/20` или `2026-9-20` строкой сравнились бы с `analysed` молча и
    дали неверный счёт сверенного — поэтому форма проверяется на входе. Та же
    проверка держит и `analysed` в ответе (`answers_whole`).
    """
    if not is_iso_day(said):
        raise argparse.ArgumentTypeError(f"не дата ГГГГ-ММ-ДД: {said!r}")
    return said


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает полосы и следующую пачку к разбору."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", default=None, help="ответы проекта; по умолчанию из дерева")
    parser.add_argument("--export", default=None, help="снятая выгрузка каталога вместо живой")
    parser.add_argument("--take", type=int, default=8, help="сколько несверенных показать")
    parser.add_argument(
        "--since",
        type=iso_day,
        default=None,
        help="ГГГГ-ММ-ДД: сверено только прочитанное не раньше этой даты",
    )
    args = parser.parse_args(argv)

    try:
        path = Path(args.answers) if args.answers else paths.BINDINGS
        if not path.is_file():
            raise NotRun(f"нет {path}: ответы проекта взять неоткуда (075)")
        # ПУТЬ ЛЮБОЙ, ПОЭТОМУ ФОРМА ПРОВЕРЯЕТСЯ: файл не из дерева `tests/test_bindings.py`
        # не держит, и на файле не той формы (`[]`, `rules` списком, запись не
        # объектом) профиль падал трассой, а не отказом (взгляды на #900, #902).
        # Пустой раздел отказом был и раньше — «нет записей» в `profile`.
        try:
            mine = finding_kinds.rule_answers(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise NotRun(f"{path} {UNPARSED_SAID}: {exc}") from exc
        # МОЛЧАНИЕ КАТАЛОГА — ОТКАЗ, А НЕ ТРАССА (взгляд на #908): `catalogue.read`
        # поднимает `Silent` от `RuntimeError`, и мимо `OSError`/`ValueError` он
        # падал трассой — тем же путём чтения, что и выгрузка чужой формы.
        try:
            export = (
                json.loads(Path(args.export).read_text(encoding="utf-8"))
                if args.export
                else catalogue.read(catalogue.EXPORT_URL)
            )
        except catalogue.Silent as exc:
            raise NotRun(f"{SILENT_SAID}: {exc}") from exc
        rows = profile(export, mine, args.since or "")
    except NotRun as refusal:
        print(f"профиль не построен: {refusal}", file=sys.stderr)
        return EXIT_BROKEN
    except (OSError, ValueError) as refusal:
        print(f"профиль не построен: {refusal} (075)", file=sys.stderr)
        return EXIT_BROKEN

    unread = [row for row in rows if not row["looked"]]
    print(f"ответов {len(rows)}, сверено {len(rows) - len(unread)}, осталось {len(unread)}")
    for band, count in sorted(bands(unread).items()):
        print(f"  полоса {band * 10:>2}–{band * 10 + 10:<3}% — {count}")
    if not unread:
        print("несверенных не осталось: проход закончен")
        return EXIT_OK
    print(f"\nследующая пачка ({min(args.take, len(unread))}):")
    for row in unread[: args.take]:
        print(
            f"  {row['share']:.2f}  {row['rule']}  {row['status']:<15}"
            f" {row['mechanism']:<10} {row['slug']}"
        )
    print("\nразобрав пачку, назовите её отдачу числом и решите, идти ли дальше (207)")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — точка входа процессом
    raise SystemExit(main())
