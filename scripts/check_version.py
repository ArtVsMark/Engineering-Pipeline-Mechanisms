#!/usr/bin/env python3
"""Гейт: версия контракта не правится руками нигде, кроме своего источника.

Правило 035: версия живёт в одном источнике — `CONTRACT_VERSION`. Правило 005:
число, вписанное в прозу руками, устаревает молча. Правило 127: число в прозе
допустимо только внутри маркера, который переписывает сборка.

Что ловится:

* версия встретилась в дереве **вне** источника и вне маркера — рукописное
  число, которое разойдётся с источником;
* внутри маркера стоит **не** текущая версия — маркер есть, сборка его не
  переписала.

Чего гейт не ловит намеренно: маркер, удалённый **вместе** с числом. Числа не
осталось, расходиться нечему; опасен обратный случай — маркер сняли, число
оставили, — и он ловится.

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import paths

VERSION_FILE: Final = paths.VERSION
VERSION_RE: Final = re.compile(r"^\d+\.\d+\.\d+$")
MARKER_RE: Final = re.compile(r"<!--m:contract-->(?P<value>[^<]*)<!--/m:contract-->")

# Производные и служебные файлы: версия попадает в них сборкой, а не руками.
ALLOWED: Final = frozenset({"CONTRACT_VERSION", "CHANGELOG.md"})
ALLOWED_PREFIXES: Final = ("changelog.d/released/",)
BINARY_SUFFIXES: Final = frozenset({".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip"})

EXIT_CLEAN: Final = 0
EXIT_FINDINGS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def tracked_files() -> list[Path]:
    """Отдаёт файлы под учётом; отсутствие предмета проверки — отказ (075)."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NotRun(f"список файлов не получен: {exc}") from exc

    files = [Path(name) for name in out.split("\0") if name]
    if not files:
        raise NotRun("под учётом нет ни одного файла — это ошибка входа, а не «чисто»")
    return files


def read_version() -> str:
    """Читает версию контракта из единственного источника."""
    if not VERSION_FILE.is_file():
        raise NotRun(f"нет источника версии: {VERSION_FILE}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not VERSION_RE.match(version):
        raise NotRun(f"версия «{version}» не вида МАЖОР.МИНОР.ПАТЧ")
    return version


def check(version: str, files: list[Path]) -> list[str]:
    """Ищет рукописные вхождения версии и расхождения внутри маркеров."""
    # Границы вокруг числа: «0.1.0» не должно совпадать с «10.1.0» или «0.1.02».
    loose = re.compile(rf"(?<![\d.]){re.escape(version)}(?![\d.])")
    findings: list[str] = []
    scanned = 0
    skipped = 0

    for path in files:
        name = path.as_posix()
        if name in ALLOWED or name.startswith(ALLOWED_PREFIXES):
            skipped += 1
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            skipped += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped += 1
            continue
        scanned += 1

        for match in MARKER_RE.finditer(text):
            value = match["value"].strip()
            if value != version:
                findings.append(
                    f"{name}: в маркере стоит «{value}», а источник даёт «{version}» — "
                    "маркер есть, сборка его не переписала"
                )

        stripped = MARKER_RE.sub("", text)
        for number, line in enumerate(stripped.splitlines(), start=1):
            if loose.search(line):
                findings.append(
                    f"{name}:{number}: версия «{version}» вписана вне источника и вне маркера"
                )

    # Охват называется числом: проверка, читающая список путей, без него
    # неотличима от чистого результата — слепота выглядит как «чисто» (165).
    print(f"просмотрено файлов: {scanned}, пропущено: {skipped}")
    if scanned == 0:
        raise NotRun("не просмотрено ни одного файла — предмет проверки не найден (075)")
    return findings


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        version = read_version()
        findings = check(version, tracked_files())
    except NotRun as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if findings:
        print(f"находки ({len(findings)}):")
        for finding in findings:
            print(f"  {finding}")
        print(
            "\nВерсия живёт в CONTRACT_VERSION и больше нигде. Уберите число или\n"
            "оберните его маркером контракта, который переписывает сборка.\n"
            "Формат маркера — docs/release.md, раздел «Маркер в прозе».\n\n"
            "Пример маркера здесь не приводится намеренно: гейт ищет маркеры во\n"
            "всём дереве и на собственной подсказке нашёл бы сам себя. Это не\n"
            "придирка — так он и был пойман при первом же прогоне."
        )
        return EXIT_FINDINGS

    print(f"чисто: версия {version} нигде не продублирована руками")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
