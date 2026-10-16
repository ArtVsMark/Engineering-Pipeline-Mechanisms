#!/usr/bin/env python3
"""Гейт: в дереве нет символов, которые человек на ревью не видит.

Агент читает своды, навыки и задания взгляда как указания. Невидимый символ
меняет прочитанное агентом, не меняя увиденного человеком: двунаправленные
управляющие переставляют текст на экране, символы-теги и цепочки селекторов
вариантов несут скрытую строку, символы нулевой ширины прячут разрыв слова
([085](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/085-content-from-the-subject-is-untrusted-input-to-the-prompt.md)).
Мы поставщик: подмена в нашем навыке или задании уехала бы ко всей семье.

ПРЕДМЕТ — ВСЕ ТЕКСТОВЫЕ ФАЙЛЫ ДЕРЕВА, КРОМЕ ИГНОРИРУЕМЫХ, а не список
«того, что читает агент». Новый файл, ещё не добавленный в индекс, судится
тоже: предполётная окна видит его до толчка, как соседние гейты. Список
разошёлся бы с деревом первым же новым навыком, а замер 16.10.2026 по всему
дереву дал ноль мест: шире предмета гейт не краснеет.
Файл, который не читается как UTF-8, гейтом не судится — это не текст.

ЗАКОННОЕ НЕ КРАСНЕЕТ, И ГРАНИЦА НАЗВАНА
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)):

* метка порядка байтов в самом начале файла — её ставят редакторы;
* соединитель нулевой ширины между двумя знаками эмодзи — так пишутся
  составные эмодзи;
* ОДИН селектор варианта после знака — так эмодзи получает цвет. Два подряд —
  уже канал для скрытых данных, и он краснеет.

Исходы (правило 039): ``0`` чисто · ``1`` найден невидимый символ ·
``2`` гейт не отработал.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

import gitcall
import report

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2

#: Метка порядка байтов: законна только первым символом файла.
BOM: Final = "\ufeff"
#: Соединитель нулевой ширины: законен только внутри составного эмодзи.
ZWJ: Final = "\u200d"

#: Диапазоны, которые краснеют всегда, с именем класса для отказа.
ALWAYS: Final[tuple[tuple[int, int, str], ...]] = (
    (0x200B, 0x200C, "нулевой ширины"),
    (0x200E, 0x200F, "направления"),
    (0x202A, 0x202E, "двунаправленный управляющий"),
    (0x2060, 0x2064, "невидимый оператор"),
    (0x2066, 0x2069, "двунаправленный изолятор"),
    (0x00AD, 0x00AD, "мягкий перенос"),
    (0x180E, 0x180E, "монгольский разделитель гласных"),
    (0xE0000, 0xE007F, "символ-тег"),
)
#: Селекторы вариантов: один после знака законен, два подряд — нет.
SELECTORS: Final[tuple[tuple[int, int], ...]] = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def selector(char: str) -> bool:
    """Селектор варианта — из какого бы блока он ни был."""
    code = ord(char)
    return any(low <= code <= high for low, high in SELECTORS)


def emoji(char: str) -> bool:
    """Знак, между которыми соединитель нулевой ширины строит составной эмодзи."""
    code = ord(char)
    return code >= 0x1F000 or 0x2600 <= code <= 0x27BF or selector(char)


def always(char: str) -> str:
    """Имя класса, если символ краснеет всегда; иначе пусто."""
    code = ord(char)
    return next((name for low, high, name in ALWAYS if low <= code <= high), "")


def hidden(text: str) -> list[tuple[int, int, str]]:
    """Невидимые символы текста: строка, столбец и что это за символ."""
    found: list[tuple[int, int, str]] = []
    line, column = 1, 0
    for at, char in enumerate(text):
        column += 1
        if char == "\n":
            line, column = line + 1, 0
            continue
        said = always(char)
        if char == BOM and at > 0:
            said = "метка порядка байтов не в начале файла"
        elif char == ZWJ and not (
            0 < at < len(text) - 1 and emoji(text[at - 1]) and emoji(text[at + 1])
        ):
            said = "соединитель нулевой ширины вне составного эмодзи"
        elif selector(char) and at > 0 and selector(text[at - 1]):
            said = "селекторы вариантов подряд"
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
        if not path.is_file():
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
