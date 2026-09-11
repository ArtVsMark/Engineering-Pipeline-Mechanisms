#!/usr/bin/env python3
"""Собирает `CHANGELOG.md` из фрагментов.

Правило 030: журнал собирается из фрагментов, а не правится общим файлом. Два
файла с разными именами не конфликтуют никогда, а на конфликтном изменении
площадка не создаёт проверок вовсе.

Правило 125: генератор читает **источники, а не свой вывод**. Поэтому выпущенные
фрагменты не исчезают в собранный файл, а переезжают в
``changelog.d/released/<версия>/`` и остаются источником. `CHANGELOG.md`
производный целиком: его можно удалить и собрать заново, ничего не потеряв.

СОБРАННЫЙ ЖУРНАЛ — ДЕЛО ВЫПУСКА, А НЕ КАЖДОГО ИЗМЕНЕНИЯ
([030](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/030-changelog-from-fragments.md)):
«запись приезжает вместе с изменением, отдельным файлом; сборка — при выпуске».
Инцидент, записанный в самом правиле, мы успели повторить: общий файл, который
трогает каждая ветка, даёт конфликт на каждом втором изменении — за десять
минут 9 сентября он случился дважды.

Поэтому на изменении проверяются ФРАГМЕНТЫ (``--fragments``): имя разбирается,
тело не пусто, ссылка на задачу последней строкой. Совпадение собранного файла
со сборкой (``--check``) остаётся, но спрашивают его при выпуске.

Исходы (правило 039): ``0`` собрано · ``1`` собранное расходится с файлом на
диске при ``--check`` · ``2`` собрать не удалось.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import journal
import paths

FRAGMENTS: Final = paths.FRAGMENTS
RELEASED: Final = paths.RELEASED
OUTPUT: Final = paths.CHANGELOG
VERSION_FILE: Final = paths.VERSION
VERSION_RE: Final = re.compile(r"^\d+\.\d+\.\d+$")
LINK_LINE_RE: Final = journal.LINK_LINE_RE

KINDS: Final = journal.KINDS

#: Сколько ВЫПУСКОВ разворачивается в собранном журнале. Остальные остаются
#: источником и называются ссылкой на каталог выпуска.
#:
#: ПОЧЕМУ ПРЕДЕЛ ЕСТЬ. Вышедшее из окна переезжает дословно и не сокращается —
#: фрагменты уходят в `changelog.d/released/<версия>/` целиком. Но собранный
#: файл читает человек, и без предела он растёт линейно по числу выпусков:
#: к сотому читатель ищет свежее прокруткой. Предел — у ПРЕДСТАВЛЕНИЯ, не у
#: источника: ни одна запись не пропадает, она перестаёт быть развёрнутой.
#:
#: ПОЧЕМУ ПЯТЬ. Столько помещается на экран, и столько же держит соседний
#: проект семьи. Число небольшое намеренно: предел, выбранный «с запасом»,
#: не срабатывает годами и потому не проверен ничем.
UNFOLDED_RELEASES: Final = 5

FRAGMENT_RE: Final = journal.NAME_RE

EXIT_OK: Final = 0
EXIT_DIFFERS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Сборка не отработала: третий исход, а не пустой журнал."""


@dataclass(frozen=True, slots=True)
class Fragment:
    """Один фрагмент журнала: род, слаг имени, текст.

    Поле звалось `task` от прежнего правила именования — по номеру задачи.
    Правило снято вместе с потерянной записью, и имя поля шло за ним следом:
    слаг говорит, ЧТО изменилось, а не какая задача.
    """

    kind: str
    slug: str
    body: str


def read_fragments(directory: Path) -> list[Fragment]:
    """Читает ВСЕ фрагменты каталога: предмет выпуска, а не изменения."""
    if not directory.is_dir():
        return []
    return parse_fragments(sorted(directory.glob("*.md")))


def parse_fragments(paths: list[Path]) -> list[Fragment]:
    """Разбирает названные файлы, отвергая неразбираемые имена и пустые.

    Разбор один на оба читателя — выпуск и гейт изменения. Двумя копиями он
    разошёлся бы молча: один принял бы фрагмент, который второй отвергает
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    fragments: list[Fragment] = []
    unnamed: list[str] = []
    for path in paths:
        if path.name == "README.md" or not path.is_file():
            continue
        match = FRAGMENT_RE.match(path.name)
        if match is None:
            unnamed.append(path.name)
            continue
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            unnamed.append(f"{path.name} (пустой)")
            continue
        if not LINK_LINE_RE.match(body.splitlines()[-1].strip()):
            unnamed.append(f"{path.name} (ссылка на задачу не последней строкой)")
            continue
        # Причина у `internal` проверяется ЗДЕСЬ, а не у гейта изменения: разбор
        # фрагментов один на обоих читателей, и вторая копия правила разошлась
        # бы с первой молча (090).
        if match["kind"] == journal.INTERNAL and not journal.REASON_LINE_RE.match(
            body.splitlines()[0].strip()
        ):
            unnamed.append(f"{path.name} (род `internal` без причины первой строкой)")
            continue
        fragments.append(Fragment(match["kind"], match["slug"], body))

    if unnamed:
        raise NotRun(
            "фрагменты с неразбираемым именем, пустые или без ссылки в конце:\n  "
            + "\n  ".join(unnamed)
            + "\n\nИмя: <слаг-по-смыслу>.<род>.md, род — "
            + " · ".join(KINDS)
            + "\nПоследняя строка — ссылка на задачу: «#12» или «#12 #13»"
            + "\nУ рода `internal` ПЕРВАЯ строка — причина: "
            + "«> **Потребителю безразлично:** …» (154)"
        )
    return fragments


def fragments_of(paths: list[str]) -> list[Fragment]:
    """Разбирает фрагменты, которые тронуло ИЗМЕНЕНИЕ, и только их.

    Берутся все `.md` под `changelog.d/`, а не только правильно названные:
    иначе файл с негодным именем выпал бы из отбора ровно потому, что негоден,
    и гейт зазеленел бы на том, что обязан отвергнуть (075).
    """
    touched = [
        FRAGMENTS / name.rsplit("/", 1)[-1]
        for name in paths
        if name.startswith(f"{FRAGMENTS}/") and name.endswith(".md") and name.count("/") == 1
    ]
    return parse_fragments(touched)


def render_section(title: str, fragments: list[Fragment]) -> str:
    """Собирает один раздел журнала, группируя фрагменты по роду."""
    lines = [f"## {title}", ""]
    if not fragments:
        lines += ["Пусто.", ""]
        return "\n".join(lines)

    for kind, heading in KINDS.items():
        chosen = [f for f in fragments if f.kind == kind]
        if not chosen:
            continue
        lines += [f"### {heading}", ""]
        for fragment in chosen:
            lines += [fragment.body, ""]
    return "\n".join(lines)


def render(version: str) -> str:
    """Собирает журнал целиком: не выпущенное, затем выпуски от новых к старым."""
    parts = [
        "# Журнал изменений",
        "",
        "> Файл производный: собирается `scripts/build_changelog.py` из фрагментов",
        "> в `changelog.d/`. Руками не правится — правка потеряется при следующей",
        "> сборке (правило 125).",
        "",
        f"Версия контракта — `{version}`, источник `CONTRACT_VERSION`. Что означают",
        "разряды и что делает потребитель — [`docs/release.md`](docs/release.md).",
        "",
        render_section("Не выпущено", read_fragments(FRAGMENTS)),
    ]

    released = releases()
    for directory in released[:UNFOLDED_RELEASES]:
        parts.append(render_section(directory.name, read_fragments(directory)))

    folded = released[UNFOLDED_RELEASES:]
    if folded:
        parts.append(render_folded(folded))

    return "\n".join(parts).rstrip() + "\n"


def releases() -> list[Path]:
    """Каталоги выпусков от новых к старым."""
    if not RELEASED.is_dir():
        return []
    return sorted(
        (p for p in RELEASED.iterdir() if p.is_dir()),
        key=lambda p: [int(x) for x in p.name.split(".")] if VERSION_RE.match(p.name) else [0],
        reverse=True,
    )


def render_folded(directories: list[Path]) -> str:
    """Свёрнутые выпуски: строка со ссылкой на источник, а не пропажа.

    Запись не исчезает и не сокращается — она остаётся в каталоге выпуска
    целиком. Свёрнуто только представление, и сказано об этом прямо: раздел,
    молча оборванный на пятом выпуске, читался бы как «раньше ничего не было».
    """
    lines = [
        f"## Выпуски раньше {directories[0].name}",
        "",
        "Записи не сокращены: каждая лежит в своём каталоге выпуска целиком.",
        f"Развёрнутыми здесь собираются {UNFOLDED_RELEASES} последних — предел у",
        "представления, а не у источника.",
        "",
    ]
    lines += [
        f"- [{directory.name}]({directory.as_posix()}/) — записей: {len(read_fragments(directory))}"
        for directory in directories
    ]
    return "\n".join(lines) + "\n"


def read_version() -> str:
    """Читает версию контракта из единственного источника."""
    if not VERSION_FILE.is_file():
        raise NotRun(f"нет источника версии: {VERSION_FILE}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not VERSION_RE.match(version):
        raise NotRun(f"версия «{version}» не вида МАЖОР.МИНОР.ПАТЧ")
    return version


def do_release(version: str) -> None:
    """Переносит текущие фрагменты в каталог выпуска, оставляя их источником."""
    if not VERSION_RE.match(version):
        raise NotRun(f"версия выпуска «{version}» не вида МАЖОР.МИНОР.ПАТЧ")
    target = RELEASED / version
    if target.exists():
        raise NotRun(f"выпуск {version} уже собран: {target}")

    moving = [p for p in FRAGMENTS.glob("*.md") if p.name != "README.md"]
    if not moving:
        raise NotRun("выпускать нечего: ни одного фрагмента — это ошибка входа, а не пустой выпуск")

    target.mkdir(parents=True)
    for path in moving:
        shutil.move(str(path), str(target / path.name))
    print(f"в выпуск {version} перенесено фрагментов: {len(moving)}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает журнал, сверяет его или закрывает выпуск."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="сверить, не записывая")
    parser.add_argument(
        "--fragments",
        action="store_true",
        help="проверить только фрагменты: имя, непустоту, ссылку в конце",
    )
    parser.add_argument("--release", metavar="ВЕРСИЯ", help="закрыть выпуск: перенести фрагменты")
    parser.add_argument("--base", default="", help="ветка сравнения для --fragments")
    args = parser.parse_args(argv)

    try:
        if args.fragments:
            # ПРЕДМЕТ ПРОВЕРКИ — ТО, ЧТО ПРИЕЗЖАЕТ С ИЗМЕНЕНИЕМ, и раньше это
            # было сказано комментарием, а сделано наоборот: разбирался весь
            # каталог целиком. Разница не отвлечённая. Выпуск переносит
            # фрагменты в `changelog.d/released/`, и сразу после него каталог
            # пуст — гейт валился третьим исходом на первом же изменении, хотя
            # своё оно принесло. Ни версия, ни собранный файл здесь не нужны:
            # их спрашивает выпуск, а изменение отвечает за свой фрагмент.
            mine = fragments_of(journal.changed_files(journal.base_from_env(args.base)))
            if not mine:
                # Законное состояние, а не «нечего проверять»: нужен ли
                # изменению фрагмент вообще, решает `check_journal.py` — он и
                # отвергает изменение без него. Краснеть здесь вторым разом
                # значило бы завести второй источник того же решения (022).
                print("изменение не несёт фрагментов — их наличие спрашивает check_journal")
                return EXIT_OK
            print(f"фрагменты изменения разбираются: {len(mine)}")
            return EXIT_OK

        if args.release:
            do_release(args.release)
        version = read_version()
        assembled = render(version)

        if args.check:
            current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
            if current != assembled:
                print(
                    f"{OUTPUT} расходится со сборкой из фрагментов.\n"
                    "Соберите заново: python scripts/build_changelog.py",
                    file=sys.stderr,
                )
                return EXIT_DIFFERS
            print(f"{OUTPUT} совпадает со сборкой")
            return EXIT_OK

        OUTPUT.write_text(assembled, encoding="utf-8")
        print(f"{OUTPUT} собран, версия контракта {version}")
        return EXIT_OK
    except (NotRun, journal.NotRun) as exc:
        print(f"сборка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
