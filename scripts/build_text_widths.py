#!/usr/bin/env python3
"""Таблица ширин знаков `fonts/text_widths.json` — замером файлов шрифта, а не рукой.

ПЕРЕЕХАЛО ИЗ КАТАЛОГА вместе с `text_width.py` (#1563): таблица, которой
считает ширину `text_width`, собирается этим сборщиком и больше ничем (214).
До него у каталога таблица Verdana была вписана рукой и «сверена с пятью
надписями»: 25 ширин из 95 расходились с файлом шрифта, `/` — на 28 %
(каталог, обзор #795).

Файлов шрифта в дереве нет и не будет: Verdana несвободна, и даже Inter
незачем возить ради сотни чисел. Поэтому в таблице записан ИСТОЧНИК — версия
из таблицы имён и начало sha256 файла, — по нему замер повторяется:

  python scripts/build_text_widths.py \\
      --verdana Verdana.TTF \\
      --inter /usr/share/fonts/opentype/inter

Verdana — `Verdana.TTF` из corefonts (`verdan32.exe`, cabextract). Inter —
Inter-{Regular,Medium,SemiBold,Bold,ExtraBold}.otf из пакета fonts-inter.
Нужен fontTools; в зависимости набора он не входит — сборщик зовут руками.

Исходы:
  0 — таблица записана (или совпала с записанной при --check);
  1 — --check: записанная таблица расходится с замером;
  2 — замер не сделан (нет fontTools, нет файла, нет начертания).
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import text_width

EXIT_OK: Final = 0
EXIT_DIFFERS: Final = 1
EXIT_BROKEN: Final = 2

#: Знаки, которые выводят надписи значков: печатная ASCII, кириллица, кавычки,
#: тире и значки вердиктов. Знак, которого нет в файле шрифта, в таблицу не
#: попадает — `text_width` даст ему ширину самого широкого (045).
SIGNS: Final = (
    "".join(map(chr, range(0x20, 0x7F)))
    + "ЁАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдежзийклмнопрстуфхцчшщъыьэюяё"
    + "«»·×–—…№→✓✗"
)

#: Файл начертания Inter по весу.
INTER: Final = {
    400: "Inter-Regular.otf",
    500: "Inter-Medium.otf",
    600: "Inter-SemiBold.otf",
    700: "Inter-Bold.otf",
    800: "Inter-ExtraBold.otf",
}

#: Пояснение в самой таблице: откуда она и чем собирается.
ABOUT: Final = (
    "Ширины знаков (advance width) в единицах кегля — источник истины для "
    "ширины надписей в SVG значков механизмов (каталог #792, переезд #1563). "
    "Собирается scripts/build_text_widths.py замером файлов шрифта, а не "
    "правится руками."
)


def widths(
    cmap: dict[int, str], advance: Callable[[str], int], signs: str = SIGNS
) -> dict[str, int]:
    """Ширина (advance width, hmtx) каждого знака, который есть в карте шрифта."""
    return {sign: advance(cmap[ord(sign)]) for sign in signs if ord(sign) in cmap}


def measure(path: Path) -> tuple[dict[str, int], int, str]:
    """Ширины знаков, единицы на кегль и источник одного файла шрифта."""
    from fontTools.ttLib import TTFont

    font = TTFont(path)
    metrics = font["hmtx"].metrics
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    source = f"{font['name'].getDebugName(5)} {path.name} sha256:{digest}"
    return (
        widths(font.getBestCmap(), lambda glyph: metrics[glyph][0]),
        int(font["head"].unitsPerEm),
        source,
    )


def build(verdana: Path, inter: Path) -> dict[str, Any]:
    """Таблица целиком: Verdana 400 и пять начертаний Inter."""
    signs_v, units_v, source_v = measure(verdana)
    weights: dict[str, dict[str, int]] = {}
    sources: list[str] = []
    units_i: set[int] = set()
    for weight, name in INTER.items():
        signs, units, source = measure(inter / name)
        weights[str(weight)] = signs
        sources.append(source)
        units_i.add(units)
    if len(units_i) != 1:
        raise ValueError(f"у начертаний Inter разные единицы: {sorted(units_i)}")
    return {
        "about": ABOUT,
        "fonts": {
            "Inter": {"source": "; ".join(sources), "units": units_i.pop(), "weights": weights},
            "Verdana": {"source": source_v, "units": units_v, "weights": {"400": signs_v}},
        },
    }


def render(table: dict[str, Any]) -> str:
    """Текст файла таблицы — одна форма для записи и для сверки."""
    return json.dumps(table, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает таблицу или сверяет записанную с замером."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--verdana", type=Path, required=True, help="Verdana.TTF")
    parser.add_argument("--inter", type=Path, required=True, help="каталог с Inter-*.otf")
    parser.add_argument(
        "--check", action="store_true", help="сверить записанную таблицу с замером, не записывая"
    )
    args = parser.parse_args(argv)
    try:
        table = build(args.verdana, args.inter)
    except ImportError:
        print(
            f"замер не сделан: {Path(__file__).name} нужен fontTools (pip install fonttools)",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    except (OSError, KeyError, ValueError) as exc:
        print(f"замер не сделан: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    text = render(table)
    target = text_width.TABLE
    if args.check:
        try:
            written = target.read_text(encoding="utf-8")
        except OSError as exc:
            # Нет записанной таблицы — тоже расхождение с замером, а не трасса
            # (взгляд на #1565): исход объявлен, и чинится он записью.
            print(f"{target} не прочитана — {exc.strerror}: с замером не сходится", file=sys.stderr)
            return EXIT_DIFFERS
        except UnicodeDecodeError as exc:
            # Сосед «нет таблицы»: таблица не в UTF-8 — тоже не то, что пишет
            # сборщик, и чинится той же записью, а не трассой (195).
            print(f"{target} не в UTF-8 — {exc.reason}: с замером не сходится", file=sys.stderr)
            return EXIT_DIFFERS
        if written != text:
            print(f"{target} расходится с замером шрифтов", file=sys.stderr)
            return EXIT_DIFFERS
        print(f"{target.name} совпадает с замером")
        return EXIT_OK
    target.write_text(text, encoding="utf-8")
    print(f"записано: {target.name}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
