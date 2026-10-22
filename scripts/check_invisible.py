#!/usr/bin/env python3
"""Гейт: в тексте, который агент читает как указание, нет невидимых символов.

Агент читает своды, навыки, задания взгляда и прогоны как указания. Невидимый
символ меняет прочитанное агентом, не меняя увиденного человеком:
двунаправленные управляющие переставляют текст на экране, символы-теги и
цепочки селекторов вариантов несут скрытую строку, символы нулевой ширины
прячут разрыв слова
([085](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/085-content-from-the-subject-is-untrusted-input-to-the-prompt.md)).
Мы поставщик: подмена в нашем навыке или задании уехала бы ко всей семье.

ЧТО СЧИТАЕТСЯ — СВОЙСТВА UNICODE, А НЕ ПЕРЕЧЕНЬ, КАК У КАТАЛОГА (его #873).
Судятся: вся категория формата `Cf`; разделители строки и абзаца U+2028,
U+2029 (`Zl`, `Zp`) и управляющие `Cc`, кроме табуляции, перевода строки и
возврата каретки перед ним; все точки свойства `Default_Ignorable_Code_Point`,
назначены они или нет, — заполнители хангыля, соединитель графем U+034F,
скрытые гласные кхмерского U+17B4–U+17B5, неназначенные диапазоны и блок
тегов целиком; сверх свойства — пустой знак Брайля U+2800. Редактор
показывает всё это пустотой, а читатель режет по разделителям строку
(взгляды на #1437 и #1444). Перечень кодовых точек устаревал бы с каждой
версией Unicode и пропускал соседа — так прошёл U+061C (взгляд на #1437).

ПОНИМАНИЕ С КАТАЛОГОМ НЕ ОДНО, И РАСХОЖДЕНИЕ НАЗВАНО (195). Сверено чтением его
разбора (`scripts/invisible.py`, 911bd4b), а не исполнением, 18.10.2026. Каталог
строже: соединитель нулевой ширины и теги у него — `Cf` без исключений, то есть
составной эмодзи и флаги RGI краснеют; идеографический селектор красен всегда;
JSON он судит и после разбора, поэтому экранированный `\\u200b` в строке JSON
у него краснеет, а здесь не виден — это сосед за нашей границей. Каталог мягче:
`Zl`, `Zp`, `Cc` и одиночный возврат каретки он не судит, монгольские
селекторы и игнорируемые точки вне `Cf`, кроме заполнителей хангыля, — тоже, а
U+FE0E и U+FE0F законны у него после любого знака `So`. Выровнять понимание —
дело правила семьи #1425, а не этой проверки.

ДАННЫЕ — ВЫДЕРЖКИ UNICODE 16.0.0 В `scripts/unicode/`, А НЕ ПАМЯТЬ (210). По
месту «что считается» было три находки подряд — список эмодзи, перечень
вместо `Cf`, хангыль, — и каждая починка дописывала перечень рукой. Теперь
игнорируемые точки, знаки эмодзи и пары вариантов читаются из файлов
стандарта: адрес источника, хеш и команда выдержки — в шапке каждого. Модуль
`unicodedata` этих свойств не отдаёт. Совпадение версии данных с базой
интерпретатора держит тест.

ПРЕДМЕТ — ТЕКСТ-УКАЗАНИЕ: `.md`, `.yml`, `.yaml`, `.json` дерева без
игнорируемых, включая файлы вне индекса — предполётная видит их до толчка.
СОСЕД ЗА ГРАНИЦЕЙ НАЗВАН
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)):
код не судится. Замер 16.10.2026 по пяти проектам семьи: все места в коде
законны — фикстуры гейта каталога и `\\ufeff` в коде грейдера, снимающем
метку порядка байтов. Гейт по всему дереву покраснел бы у двух проектов из
пяти на исправном (107). Но текст заданий взгляда живёт и в строках `.py` —
`review_map.MARK_SAID` уходит агенту дословно, — и этот сосед у себя судится:
тест `test_our_code_carries_no_invisible` обходит `.py` нашего дерева тем же
`hidden`. Замер 18.10.2026 тем же `hidden` по `git ls-tree origin/main`: в
`.py` нашего дерева находок 0, у каталога 20 — все в тестах, у грейдера 6 —
четыре в коде снятия BOM, две в тестах, у Usage-Token 0.

ЗАКОННОЕ НЕ КРАСНЕЕТ:

* метка порядка байтов первым символом файла — её ставят редакторы;
* возврат каретки перед переводом строки — пара CRLF. Одиночный возвращает
  печать к началу строки, и «видимое\\rскрытое» терминал выводит поверх;
* соединитель нулевой ширины внутри составного эмодзи (UAX #29, правило
  GB11): слева знак `Extended_Pictographic`, его селектор U+FE0F или тон кожи
  (`Emoji_Modifier`), справа — знак `Extended_Pictographic`. Стрелка, буква и
  цифра так не соединяются: «→», U+200D, «→» — скрытый разрыв;
* ОДИН селектор варианта после основы его рода: стандартный и эмодзи
  (U+FE00–U+FE0F) — только в паре из `StandardizedVariants.txt` или
  `emoji-variation-sequences.txt`; идеографический (U+E0100–U+E01EF) — после
  знака со свойством `Unified_Ideograph`; монгольский свободный (U+180B–U+180D,
  U+180F) — после монгольской буквы или знака, письмо `Mongolian` и категория
  буквы или метки. Основы — данными (`selector-bases.txt`), а не именем знака:
  двенадцать унифицированных иероглифов блока совместимости (U+FA0E …
  U+FA29) именем «CJK COMPATIBILITY IDEOGRAPH» не узнать (поздний взгляд на
  #1510). Селектор после чужой основы или два подряд — канал для скрытых
  данных, и он краснеет;
* символы-теги внутри флага-эмодзи из перечня RGI — Англии, Шотландии и
  Уэльса (`RGI_TAG_FLAGS`). Иная строка тегами — скрытая, даже внутри флага.

ГРАНИЦЫ, И ОНИ НАЗВАНЫ.

* Идеографический селектор сверяется с основой по роду, а не по реестру IVD:
  реестр в данных не лежит, и селектор после иероглифа без зарегистрированной
  пары пройдёт.
* Монгольский — тоже по роду: `StandardizedVariants.txt` называет лишь часть
  монгольских пар (замер 18.10.2026 по выдержке: U+180B — 40, U+180C — 14,
  U+180D — 6, U+180F — 0), и точные пары краснили бы законный монгольский
  текст.
* Данные — версии 16.0.0, базы Python 3.14, которым гейт исполняет шаг
  конвейера. Интерпретатор с базой новее (3.15 — Unicode 17.0.0) знает знаки,
  которых выдержка не знает: соединитель после нового эмодзи покраснеет, пока
  выдержки не подняты. Тест версии требует совпадения на интерпретаторе шага, а
  на прочих — что данные не новее базы.

Исходы (правило 039): ``0`` чисто · ``1`` найден невидимый символ ·
``2`` гейт не отработал.
"""

import argparse
import sys
import unicodedata
from dataclasses import dataclass
from functools import cache
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
#: Данные Unicode, из которых выводится, что невидимо и что законно, — почему
#: данные, а не перечень, сказано в разделе «ДАННЫЕ» докстроки модуля.
UNICODE: Final = Path(__file__).resolve().parent / "unicode"
#: Версия данных; совпадение с базой интерпретатора шага конвейера держит тест.
UNICODE_VERSION: Final = "16.0.0"
#: Откуда взяты данные: копия базы консорциума в его же репозитории.
UNICODE_SOURCE: Final = (
    "https://raw.githubusercontent.com/unicode-org/unicodetools/main/unicodetools/data/ucd/"
    + UNICODE_VERSION
)
#: Дословные копии файлов стандарта — адрес и хеш. Выдержки называют источник
#: своей шапкой, а копия шапки не имеет; совпадение хеша держит тест, и файл
#: рукой не правится.
VERBATIM: Final = {
    "emoji-variation-sequences.txt": (
        f"{UNICODE_SOURCE}/emoji/emoji-variation-sequences.txt",
        "71d93ec015011371a027ba2bc0a63155d381c6e0b94a586c1a88a49400cd6864",
    ),
    "StandardizedVariants.txt": (
        f"{UNICODE_SOURCE}/StandardizedVariants.txt",
        "36e799b2c5d902af094b4dd2cb60622bffc079824bfd0bf62e3a636d698b3fb5",
    ),
}
#: Пустой знак Брайля: свойства «рисуется пустотой» у Unicode нет, а
#: `Default_Ignorable_Code_Point` его не включает — это пустой глиф, а не
#: игнорируемая точка (`36f8b72`). Единственный знак сверх данных.
BRAILLE_BLANK: Final = "\u2800"
#: Категории, которые судятся целиком: формат, разделители строки и абзаца и
#: управляющие. Из управляющих (`Cc`) законны только табуляция и перевод строки
#: с возвратом каретки; NEL U+0085, `\v`, `\f` и U+001C–U+001E режут строку
#: там, где редактор разрыва не показывает (`str.splitlines`, YAML 1.1) — взгляд
#: на #1444.
CATEGORIES: Final = {
    "Cf": "",
    "Zl": "разделитель строки — перенос, которого редактор не показывает",
    "Zp": "разделитель абзаца — перенос, которого редактор не показывает",
    "Cc": "управляющий символ — редактор его не показывает",
}
#: Управляющие, которые законны: табуляция и перевод строки. Возврат каретки
#: законен только перед переводом строки — в паре CRLF.
PLAIN_CONTROLS: Final = frozenset("\t\n")
#: Возврат каретки: одиночный возвращает печать к началу строки, и терминал
#: выводит следующее поверх — «видимое\rскрытое» человек видит иначе, чем
#: читает агент (взгляд на #1444).
CR: Final = "\r"
#: Флаг-эмодзи с тегами (UTS #51): основа, теги спецификации и завершающий тег.
FLAG: Final = "\U0001f3f4"
CANCEL_TAG: Final = "\U000e007f"
#: ЗАКОННЫ ТОЛЬКО ФЛАГИ ИЗ ПЕРЕЧНЯ RGI (emoji-test.txt, Unicode 16.0), а не
#: любая цепочка тегов: тегами пишется любой ASCII-текст, и «флаг» с
#: произвольной строкой внутри был бы той же скрытой строкой (взгляд на #1444).
RGI_TAG_FLAGS: Final = frozenset({"gbeng", "gbsct", "gbwls"})
#: Селекторы вариантов по родам — свойство `Variation_Selector` (PropList.txt).
#: Род решает, после какой основы селектор законен (взгляд на #1444): свободные
#: монгольские — после монгольской буквы, идеографические — после иероглифа,
#: стандартные — только в паре из данных Unicode. Монгольский род — диапазон
#: U+180B–U+180F, но U+180E внутри него — разделитель гласных `Cf`: селектором
#: его не считает `SELECTORS`, и судится он как формат.
MONGOLIAN_SELECTORS: Final = (0x180B, 0x180F)
IDEOGRAPHIC_SELECTORS: Final = (0xE0100, 0xE01EF)
STANDARD_SELECTORS: Final = (0xFE00, 0xFE0F)
SELECTORS: Final[tuple[tuple[int, int], ...]] = (
    STANDARD_SELECTORS,
    IDEOGRAPHIC_SELECTORS,
    (0x180B, 0x180D),
    (0x180F, 0x180F),
)


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


@dataclass(frozen=True)
class Tables:
    """Свойства Unicode, прочитанные из `UNICODE`."""

    #: `Default_Ignorable_Code_Point` — назначенные и нет.
    ignorable: frozenset[int]
    #: `Extended_Pictographic`: между такими соединитель строит составной эмодзи.
    pictographic: frozenset[int]
    #: `Emoji_Modifier` — тон кожи: стоит между эмодзи и соединителем.
    modifiers: frozenset[int]
    #: Пары «основа, селектор» стандартных вариантов и вариантов эмодзи.
    variants: frozenset[tuple[int, int]]
    #: `Unified_Ideograph` — основы идеографического селектора.
    ideographs: frozenset[int]
    #: Письмо `Mongolian` — из него основы монгольского селектора.
    mongolian: frozenset[int]


def codes(field: str) -> range:
    """Точки поля данных Unicode: `00AD` или `115F..1160`."""
    low, _, high = field.strip().partition("..")
    return range(int(low, 16), int(high or low, 16) + 1)


def data_lines(name: str) -> list[list[str]]:
    """Строки данных файла `UNICODE` — поля до комментария; отказ чтения — «не отработал»."""
    try:
        text = (UNICODE / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise NotRun(f"данные Unicode {name} не прочитаны: {exc}") from exc
    rows = [line.split("#", 1)[0].split(";") for line in text.splitlines()]
    return [[one.strip() for one in row] for row in rows if len(row) > 1]


def property_codes(name: str, wanted: str) -> frozenset[int]:
    """Точки свойства `wanted` из файла данных `name`."""
    try:
        return frozenset(
            code for row in data_lines(name) if row[1] == wanted for code in codes(row[0])
        )
    except ValueError as exc:
        raise NotRun(f"данные Unicode {name} не разобраны: {exc}") from exc


def sequence_pairs(name: str) -> frozenset[tuple[int, int]]:
    """Пары «основа, селектор» из файла последовательностей вариантов."""
    try:
        pairs = [row[0].split() for row in data_lines(name)]
        return frozenset((int(base, 16), int(mark, 16)) for base, mark in pairs)
    except ValueError as exc:
        raise NotRun(f"данные Unicode {name} не разобраны: {exc}") from exc


@cache
def tables() -> Tables:
    """Свойства Unicode из `UNICODE`, прочитанные один раз за прогон."""
    return Tables(
        ignorable=property_codes("default-ignorable.txt", "Default_Ignorable_Code_Point"),
        pictographic=property_codes("pictographic.txt", "Extended_Pictographic"),
        modifiers=property_codes("pictographic.txt", "Emoji_Modifier"),
        variants=sequence_pairs("StandardizedVariants.txt")
        | sequence_pairs("emoji-variation-sequences.txt"),
        ideographs=property_codes("selector-bases.txt", "Unified_Ideograph"),
        mongolian=property_codes("selector-bases.txt", "Mongolian"),
    )


def within(code: int, span: tuple[int, int]) -> bool:
    """Точка лежит в диапазоне `span` включительно."""
    return span[0] <= code <= span[1]


def selector(char: str) -> bool:
    """Селектор варианта — из какого бы блока он ни был."""
    return any(within(ord(char), span) for span in SELECTORS)


def emoji(char: str) -> bool:
    """Знак `Extended_Pictographic`: между такими соединитель строит составной эмодзи."""
    return ord(char) in tables().pictographic


def joins(text: str, at: int) -> bool:
    """Соединитель на месте `at` строит составной эмодзи (UAX #29, правило GB11).

    Слева — эмодзи, за которым может стоять его тон кожи и селектор U+FE0F,
    справа — эмодзи. Селектор и тон проходятся назад до самой основы: «1»,
    U+FE0F, U+200D — не эмодзи слева. Стрелка, буква и цифра соединителем не
    соединяются: «→», U+200D, «→» — скрытый разрыв.
    """
    spot = at - 1
    if spot >= 0 and text[spot] == "\ufe0f":
        spot -= 1
    if spot >= 0 and ord(text[spot]) in tables().modifiers:
        spot -= 1
    after = at + 1
    return spot >= 0 and after < len(text) and emoji(text[spot]) and emoji(text[after])


def fits(base: str, mark: str) -> bool:
    """Селектор `mark` законен после `base`: род селектора сверен с основой по данным.

    Монгольская основа — знак письма `Mongolian` категории буквы (`L*`) или
    метки (`Mn`), но не сам селектор: это ровно те знаки, что зовутся
    «MONGOLIAN LETTER …», без цифр и пунктуации письма.
    """
    code, at = ord(mark), ord(base)
    if within(code, MONGOLIAN_SELECTORS):
        mongolian = at in tables().mongolian and not selector(base)
        return mongolian and unicodedata.category(base)[0] in "LM"
    if within(code, IDEOGRAPHIC_SELECTORS):
        return at in tables().ideographs
    return (at, code) in tables().variants


def always(char: str) -> str:
    """Чем символ невидим, если он краснеет вне законных форм; иначе пусто."""
    if char == BRAILLE_BLANK:
        return "рисуется пустотой"
    if char in PLAIN_CONTROLS or char == CR:
        return ""
    category = unicodedata.category(char)
    if ord(char) in tables().ignorable and category != "Cf" and not selector(char):
        return "игнорируемая точка Unicode — рисуется пустотой"
    if category in CATEGORIES:
        return CATEGORIES[category] or unicodedata.name(char, "символ формата без имени")
    return ""


def flag_tags(text: str) -> set[int]:
    """Места тегов, законных внутри флага-эмодзи: основа, теги, завершающий тег.

    Законна только последовательность флага из `RGI_TAG_FLAGS`. Оборванная
    цепочка, теги без основы и флаг с иной строкой законными не считаются:
    это та же скрытая строка.
    """
    legal: set[int] = set()
    for name in RGI_TAG_FLAGS:
        sequence = FLAG + "".join(chr(0xE0000 + ord(one)) for one in name) + CANCEL_TAG
        at = text.find(sequence)
        while at != -1:
            legal.update(range(at + 1, at + len(sequence)))
            at = text.find(sequence, at + len(sequence))
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
        elif char == CR:
            said = "" if after == "\n" else "возврат каретки без перевода строки — печать поверх"
        elif char == ZWJ:
            said = "" if joins(text, at) else "соединитель нулевой ширины вне составного эмодзи"
        elif selector(char):
            if not before or selector(before):
                said = "селекторы вариантов подряд"
            elif not fits(before, char):
                said = "селектор варианта, которого у этой основы нет"
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
            # Переводы строк — как в файле: чтение по умолчанию сводит `\r` и
            # `\r\n` к `\n`, и одиночный возврат каретки не дошёл бы до разбора.
            text = path.read_text(encoding="utf-8", newline="")
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
