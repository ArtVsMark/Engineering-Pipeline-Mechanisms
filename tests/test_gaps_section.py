"""Раздел «чего ещё нет» — утверждение о действительности, а не оборот речи.

Проза целиком непроверяема, и гейт её трогать не должен. Но у неё есть
подкласс, который рассыхается молча и выглядит при этом осознанным решением, —
СЧЁТ. Число в строке «ответа по N записям каталога» стареет каждой пачкой
разбора, и заметить это нечем: раздел никто не пересчитывает.

Правила каталога: 175 (утверждение «предмета нет», опровергаемое одной
командой, обязано быть гейтом), 005 и 127 (число в прозе без маркера и сборки
рассыхается).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARTER = ROOT / "AGENTS.md"
BINDINGS = ROOT / ".rules" / "bindings.json"
HEADING = "## 🕳 Чего в проекте ещё нет"
SECRETS_HEADING = "## 🔑 Секреты"
# Имя секрета в прозе: заглавные латиницей с подчёркиваниями, в обратных кавычках.
SECRET_RE = re.compile(r"`([A-Z][A-Z0-9_]{5,})`")


def gaps_rows() -> list[str]:
    """Строки таблицы пробелов — без шапки и разделителя."""
    text = CHARTER.read_text(encoding="utf-8")
    start = text.index(HEADING)
    section = text[start:].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return rows[2:]


def test_the_section_has_a_subject() -> None:
    """Таблица пробелов не пуста: иначе гейт зелен на отсутствии предмета (075)."""
    assert gaps_rows(), f"в {CHARTER.name} не нашлось таблицы пробелов — предмет проверки не найден"


def test_no_row_carries_a_count() -> None:
    """Ни один пробел не называется числом: счёт двигает механизм, а не рука.

    Число живёт там, где считается, — шаг `debt` печатает его на каждом
    изменении, `facts.json` в ветке `badges` публикует наружу. Вписанное сюда,
    оно расходится с деревом на первой же разобранной записи и продолжает
    выглядеть решением.
    """
    with_counts = [row for row in gaps_rows() if re.search(r"\d", row.split("|")[1])]
    assert not with_counts, f"число вписано в пробел прозой: {with_counts}"


def unreviewed() -> int:
    """Сколько записей каталога ещё без ответа — по дереву, а не по памяти."""
    rules = json.loads(BINDINGS.read_text(encoding="utf-8"))["rules"]
    return sum(1 for answer in rules.values() if answer["status"] == "unreviewed")


def test_the_catalogue_gap_matches_the_answer() -> None:
    """Пробел «ответа по записям каталога нет» опровергается одной командой (175).

    Ровно тот подкласс прозы, который сводится к наличию объекта: очередь либо
    есть в `.rules/bindings.json`, либо её нет. Пока строка стояла на памяти,
    она успела разойтись с деревом на 71 запись и продолжала выглядеть решением.
    """
    claims = [
        row
        for row in gaps_rows()
        if "каталог" in row.split("|")[1] and "ответа" in row.split("|")[1]
    ]
    if unreviewed():
        assert claims, "очередь без ответа есть, а пробел в своде не назван (046)"
    else:
        assert not claims, f"ответ каталогу полон, а свод всё ещё называет это пробелом: {claims}"


def secrets_rows() -> list[str]:
    """Строки таблицы секретов — того, что у проекта ЕСТЬ и кем продлевается."""
    text = CHARTER.read_text(encoding="utf-8")
    start = text.index(SECRETS_HEADING)
    section = text[start:].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return rows[2:]


def test_the_two_tables_do_not_contradict_each_other() -> None:
    """Секрет не может числиться и заведённым, и отсутствующим разом.

    Две таблицы одного файла: одна называет, чем механизм держится и кто
    продлевает секрет, другая — чего у проекта нет. Секрет, попавший в обе,
    означает, что одна из них не обновлена, — и снаружи это неотличимо от
    осознанного решения
    ([175](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/175-a-claim-of-absence-must-be-a-gate.md)).

    Замер, из-за которого проверка написана: `CLAUDE_CODE_OAUTH_TOKEN` стоял в
    таблице секретов с продлевающим и одновременно в пробелах как «секрета
    нет». Ревью при этом работало на каждом изменении.
    """
    declared = {name for row in secrets_rows() for name in SECRET_RE.findall(row)}
    assert declared, "таблица секретов пуста — предмет сверки не найден (075)"
    claimed_missing = {
        name
        for row in gaps_rows()
        if "секрет" in row.split("|")[1].lower()
        for name in SECRET_RE.findall(row.split("|")[1])
    }
    both = sorted(declared & claimed_missing)
    assert not both, f"секрет объявлен заведённым и отсутствующим сразу: {both}"
