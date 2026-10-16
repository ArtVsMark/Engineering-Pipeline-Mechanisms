#!/usr/bin/env python3
"""Гейт: в тексте, который агент читает как указание, нет невидимых символов.

Агент читает своды, навыки, задания взгляда и прогоны как указания. Невидимый
символ меняет прочитанное агентом, не меняя увиденного человеком:
двунаправленные управляющие переставляют текст на экране, символы-теги и
цепочки селекторов вариантов несут скрытую строку, символы нулевой ширины
прячут разрыв слова
([085](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/085-content-from-the-subject-is-untrusted-input-to-the-prompt.md)).
Мы поставщик: подмена в нашем навыке или задании уехала бы ко всей семье.

ЧТО СЧИТАЕТСЯ — КАТЕГОРИЯ, А НЕ ПЕРЕЧЕНЬ, КАК У КАТАЛОГА (его #873). Вся
категория формата `Cf` и знаки, которые рисуются пустотой: заполнители
хангыля и соединитель графем U+034F. Перечень кодовых точек устаревал бы с
каждой версией Unicode и пропускал соседа — так прошёл U+061C (взгляд на
#1437). Одно понимание с каталогом — по правилу семьи #1425.

ПРЕДМЕТ — ТЕКСТ-УКАЗАНИЕ: `.md`, `.yml`, `.yaml`, `.json` дерева без
игнорируемых, включая файлы вне индекса — предполётная видит их до толчка.
СОСЕД ЗА ГРАНИЦЕЙ НАЗВАН
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)):
код не судится. Замер 16.10.2026 по пяти проектам семьи: все места в коде
законны — фикстуры гейта каталога и `\\ufeff` в коде грейдера, снимающем
метку порядка байтов. Гейт по всему дереву покраснел бы у двух проектов из
пяти на исправном (107).

ЗАКОННОЕ НЕ КРАСНЕЕТ:

* метка порядка байтов первым символом файла — её ставят редакторы;
* соединитель нулевой ширины между двумя знаками эмодзи — составной эмодзи;
* ОДИН селектор варианта после знака, у которого варианты бывают: эмодзи,
  `0-9 # * © ® ™ ‼ ⁉ ℹ` и иероглиф. Селектор после буквы или два подряд —
  канал для скрытых данных, и он краснеет;
* символы-теги внутри флага-эмодзи по UTS #51: чёрный флаг U+1F3F4, теги
  U+E0020–U+E007E и завершающий U+E007F — так пишутся флаги Англии и
  Шотландии. Тег вне такой последовательности — скрытая строка, и он краснеет.

РАЗДЕЛИТЕЛИ СТРОКИ И АБЗАЦА (U+2028, U+2029, категории `Zl` и `Zp`) судятся
наравне с `Cf`: редактор показывает их пустотой, а читатель разбивает по ним
строку (взгляд на #1437, `36f8b72`).

Исходы (правило 039): ``0`` чисто · ``1`` найден невидимый символ ·
``2`` гейт не отработал.
"""

import argparse
import sys
import unicodedata
from pathlib import Path
from typing import Final

import gitcall
import report

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2

#: Текст, который агент читает как указание; код в предмет не входит.
JUDGED: Final = frozenset({".md", ".yml", ".yaml", ".json"})
#: Метка порядка байтов: законна только первым символом файла.
BOM: Final = "\ufeff"
#: Соединитель нулевой ширины: законен только внутри составного эмодзи.
ZWJ: Final = "\u200d"
#: Рисуются пустотой вне категорий `Cf`, `Zl`, `Zp`: заполнители хангыля,
#: соединитель графем и пустой знак Брайля U+2800 (взгляд на #1437, `36f8b72`).
BLANK: Final = frozenset(chr(one) for one in (0x115F, 0x1160, 0x3164, 0xFFA0, 0x034F, 0x2800))
#: Категории, которые судятся целиком: формат и разделители строки и абзаца.
CATEGORIES: Final = {
    "Cf": "",
    "Zl": "разделитель строки — перенос, которого редактор не показывает",
    "Zp": "разделитель абзаца — перенос, которого редактор не показывает",
}
#: Флаг-эмодзи с тегами (UTS #51): основа, теги спецификации и завершающий тег.
FLAG: Final = "\U0001f3f4"
TAG_SPEC: Final = (0xE0020, 0xE007E)
CANCEL_TAG: Final = "\U000e007f"
#: Знаки вне блоков эмодзи, у которых селектор варианта законен.
VARIED: Final = frozenset("0123456789#*\u00a9\u00ae\u2122\u203c\u2049\u2139")
#: Селекторы вариантов.
SELECTORS: Final[tuple[tuple[int, int], ...]] = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def selector(char: str) -> bool:
    """Селектор варианта — из какого бы блока он ни был."""
    code = ord(char)
    return any(low <= code <= high for low, high in SELECTORS)


def emoji(char: str) -> bool:
    """Знак эмодзи: между такими соединитель нулевой ширины строит составной."""
    code = ord(char)
    return code >= 0x1F000 or 0x2190 <= code <= 0x2BFF or selector(char)


def varied(char: str) -> bool:
    """Знак, у которого селектор варианта бывает законно: эмодзи, иероглиф, `VARIED`."""
    return (
        (emoji(char) and not selector(char))
        or char in VARIED
        or unicodedata.name(char, "").startswith("CJK")
    )


def always(char: str) -> str:
    """Чем символ невидим, если он краснеет вне законных форм; иначе пусто."""
    if char in BLANK:
        return "рисуется пустотой"
    category = unicodedata.category(char)
    if category in CATEGORIES:
        return CATEGORIES[category] or unicodedata.name(char, "символ формата без имени")
    return ""


def flag_tags(text: str) -> set[int]:
    """Места тегов, законных внутри флага-эмодзи: основа, теги, завершающий тег.

    Последовательность без завершающего тега или без основы законной не
    считается: оборванная цепочка тегов — та же скрытая строка.
    """
    legal: set[int] = set()
    at = text.find(FLAG)
    while at != -1:
        end = at + 1
        while end < len(text) and TAG_SPEC[0] <= ord(text[end]) <= TAG_SPEC[1]:
            end += 1
        if end > at + 1 and end < len(text) and text[end] == CANCEL_TAG:
            legal.update(range(at + 1, end + 1))
        at = text.find(FLAG, end)
    return legal


def hidden(text: str) -> list[tuple[int, int, str]]:
    """Невидимые символы текста: строка, столбец и что это за символ."""
    found: list[tuple[int, int, str]] = []
    flags = flag_tags(text)
    line, column = 1, 0
    for at, char in enumerate(text):
        column += 1
        if char == "\n":
            line, column = line + 1, 0
            continue
        if at in flags:
            continue
        before = text[at - 1] if at > 0 else ""
        after = text[at + 1] if at + 1 < len(text) else ""
        said = always(char)
        if char == BOM:
            said = "" if at == 0 else "метка порядка байтов не в начале файла"
        elif char == ZWJ:
            ok = before and after and emoji(before) and emoji(after)
            said = "" if ok else "соединитель нулевой ширины вне составного эмодзи"
        elif selector(char):
            if not before or selector(before):
                said = "селекторы вариантов подряд"
            elif not varied(before):
                said = "селектор варианта после знака без вариантов"
        if said:
            found.append((line, column, f"U+{ord(char):04X} — {said}"))
    return found


def tracked(root: Path) -> list[str]:
    """Файлы дерева без игнорируемых; отказ git — «не отработал» (075)."""
    listed = gitcall.output(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], NotRun, cwd=str(root)
    )
    return [one for one in listed.split("\0") if one]


def look(root: Path) -> list[str]:
    """Все находки по дереву строками «файл:строка:столбец: что»."""
    said: list[str] = []
    for name in tracked(root):
        path = root / name
        if path.suffix not in JUDGED or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError, OSError:
            continue
        said += [f"{name}:{line}:{column}: {what}" for line, column, what in hidden(text)]
    return said


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обходит дерево и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)
    try:
        found = look(args.root)
    except NotRun as exc:
        print(f"гейт не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    if found:
        print(f"отвергнуто: невидимых символов {len(found)} — человек их не видит, агент читает")
        for one in found:
            print(f"  {one}")
        print("Удалите символ или замените видимым; составной эмодзи и BOM в начале законны.")
        return EXIT_REJECTED
    print("невидимых символов в дереве нет")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
