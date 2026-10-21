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

Без `CONTRACT_VERSION` дерево читается всё равно: маркер контракта без
источника — находка, а рукописное число без источника сверить не с чем, и это
говорится, а не выдаётся за «чисто» (взгляд на #1192).

Исходы (правило 039): ``0`` чисто, либо гейт неприменим — нет `CONTRACT_VERSION`
и нет маркеров, причина напечатана (#1187) · ``1`` есть находки · ``2`` не
отработал.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import gitcall
import paths
import version as project_version

#: Половины маркера — по частям: целиком строка в этом файле была бы маркером,
#: и гейт нашёл бы его в себе (так он и поймал себя при первом прогоне).
OPENING: Final = "<!--m:" + "contract-->"
CLOSING: Final = "<!--/m:" + "contract-->"
MARKER_RE: Final = re.compile(r"<!--m:contract-->(?P<value>[^<]*)<!--/m:contract-->")

# Производные и служебные файлы: версия попадает в них сборкой, а не руками.
#
# ОБА ИМЕНИ БЕРУТСЯ У КАНОНА (#591). Здесь стояли литералы рядом со вторым
# написанием того же `paths.VERSION`: разъехаться им ничто не мешало (022, 090).
ALLOWED: Final = frozenset({str(paths.VERSION), str(paths.CHANGELOG)})
ALLOWED_PREFIXES: Final = ("changelog.d/released/",)
BINARY_SUFFIXES: Final = frozenset({".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip"})

EXIT_CLEAN: Final = 0
EXIT_FINDINGS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def tracked_files() -> list[Path]:
    """Файлы под учётом И ещё не внесённые; отсутствие предмета — отказ (075).

    Ключ `--others` не украшение. Гейт, видящий только внесённое, пропускает
    ровно тот файл, который окно пишет прямо сейчас, — а свой прогон перед
    толчком идёт по рабочему дереву. Замер 10.09.2026: новый тест с примером
    версии прошёл `preflight` зелёным и покраснел на площадке сразу после
    коммита. Гейт, не видящий предмета в момент проверки, зелен на том, чего
    не смотрел
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
            timeout=gitcall.LOCAL,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise NotRun(f"список файлов не получен: {exc}") from exc

    files = [Path(name) for name in out.split("\0") if name]
    if not files:
        raise NotRun("под учётом нет ни одного файла — это ошибка входа, а не «чисто»")
    return files


def texts(files: list[Path]) -> list[tuple[str, str]]:
    """Тексты проверяемых файлов по имени; охват печатается числом, пустота — отказ.

    Охват называется числом: проверка, читающая список путей, без него
    неотличима от чистого результата — слепота выглядит как «чисто» (165).
    """
    found: list[tuple[str, str]] = []
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
            found.append((name, path.read_text(encoding="utf-8")))
        except OSError, UnicodeDecodeError:
            skipped += 1
    print(f"просмотрено файлов: {len(found)}, пропущено: {skipped}")
    if not found:
        raise NotRun("не просмотрено ни одного файла — предмет проверки не найден (075)")
    return found


def check(version: str, files: list[Path]) -> list[str]:
    """Ищет рукописные вхождения версии и расхождения внутри маркеров."""
    found = texts(files)
    return stale_markers(version, found) + literals(version, found)


def stale_markers(version: str, found: list[tuple[str, str]]) -> list[str]:
    """Маркеры контракта, в которых стоит не `version`: сборка их не переписала."""
    return [
        f"{name}: в маркере стоит «{match['value'].strip()}», а источник даёт «{version}» — "
        "маркер есть, а выпуск его не переписал"
        for name, text in found
        for match in MARKER_RE.finditer(text)
        if match["value"].strip() != version
    ]


def literals(version: str, found: list[tuple[str, str]]) -> list[str]:
    """Рукописные вхождения `version` вне маркера — с адресом строки.

    Отдельно от маркеров, потому что выпуск спрашивает только это (#1516):
    маркеры он переписывает сам (`rewrite_markers`), а литерал будущей версии
    переписать нечем.
    """
    # Границы вокруг числа: «1.2.3» не должно совпадать с «11.2.3» или «1.2.30».
    # Точка рядом с числом — граница, только если по ту её сторону цифра
    # («1.2.3.4», «0.1.2.3»): точка конца предложения после версии и точка
    # сокращения перед ней («см.1.2.3») версию не прячут (замер 17.10.2026 при
    # ответе на 222; зеркальный случай — взгляд на #1472).
    loose = re.compile(rf"(?<!\d)(?<!\d\.){re.escape(version)}(?!\d|\.\d)")
    findings: list[str] = []
    for name, text in found:
        stripped = MARKER_RE.sub("", text)
        for number, line in enumerate(stripped.splitlines(), start=1):
            if loose.search(line):
                findings.append(
                    f"{name}:{number}: версия «{version}» вписана вне источника и вне маркера"
                )
    return findings


def rewrite_markers(version: str, files: list[Path]) -> list[str]:
    """Переписывает число в каждом маркере контракта на `version`; отдаёт тронутые файлы.

    ЭТО ТА САМАЯ СБОРКА, КОТОРУЮ ОБЕЩАЕТ ДОГОВОР (`docs/dev/release.md`, «Маркер
    в прозе»; поздний взгляд на #1525 и взгляд на #1537). Прежде её не было
    вовсе: маркер с нынешним числом после подъёма контракта становился
    устаревшим, а выпуск не мог ни переписать его, ни пройти. Зовёт её выпуск
    тем же коммитом, что пишет `CONTRACT_VERSION`.
    """
    touched: list[str] = []
    for name, text in texts(files):
        after = MARKER_RE.sub(lambda _: f"{OPENING}{version}{CLOSING}", text)
        if after != text:
            try:
                Path(name).write_text(after, encoding="utf-8")
            except OSError as exc:
                raise NotRun(f"{name}: маркер не переписан — {exc}") from exc
            touched.append(name)
    return touched


def orphan_markers(files: list[Path]) -> list[str]:
    """Маркеры контракта в дереве без источника: переписать их сборке нечем."""
    return [
        f"{name}: маркер контракта «{match['value'].strip()}» стоит, а {paths.VERSION} нет — "
        "сборке переписать его нечем"
        for name, text in texts(files)
        for match in MARKER_RE.finditer(text)
    ]


#: Почему гейт неприменим в дереве без источника версии: причина названа (154).
NO_SOURCE: Final = (
    f"неприменимо: в корне нет {paths.VERSION} и маркеров контракта — проект не "
    "объявляет версию контракта; рукописное число без источника сверить не с чем (#1187)"
)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код.

    НЕТ ИСТОЧНИКА ВЕРСИИ — ГЕЙТ НЕПРИМЕНИМ, А НЕ СЛОМАН. Решение владельца
    07.10.2026 по #1187, вариант 2: у потребителя общего шага `journal` своей
    версии контракта может не быть, и красное «не отработал» на каждом его
    изменении наказывало бы за то, чего он не обязан вести. Неприменимость
    называется с причиной (154), а не молчит. Испорченный источник — по-
    прежнему отказ: файл есть, а версии в нём нет. У поставщика файл держит
    `tests/test_version.py`: его пропажа у нас не спрячется за этим исходом.
    """
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    # СПИСОК ФАЙЛОВ — ПЕРВЫМ, до вопроса об источнике (взгляд на #1192):
    # вне репозитория гейт обязан сказать «не отработал», а не «неприменимо».
    try:
        files = tracked_files()
        if not paths.VERSION.is_file():
            findings = orphan_markers(files)
            if not findings:
                print(NO_SOURCE)
                return EXIT_CLEAN
            version = ""
        else:
            version = project_version.declared()
            findings = check(version, files)
    except (NotRun, project_version.NotRun) as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if findings:
        print(f"находки ({len(findings)}):")
        for finding in findings:
            print(f"  {finding}")
        print(
            "\nВерсия живёт в CONTRACT_VERSION и больше нигде. Уберите число или\n"
            "оберните его маркером контракта, который переписывает сборка.\n"
            f"Формат маркера — {paths.RELEASE_DOC}, раздел «Маркер в прозе».\n\n"
            "Пример маркера здесь не приводится намеренно: гейт ищет маркеры во\n"
            "всём дереве и на собственной подсказке нашёл бы сам себя. Это не\n"
            "придирка — так он и был пойман при первом же прогоне."
        )
        return EXIT_FINDINGS

    print(f"чисто: версия {version} нигде не продублирована руками")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
