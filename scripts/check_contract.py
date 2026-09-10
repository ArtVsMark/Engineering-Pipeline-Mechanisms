#!/usr/bin/env python3
"""Гейт: правка поверхности контракта не проходит молча.

ЭТО ГЛАВНЫЙ ГЕЙТ ЗАДАЧИ #15, и он единственный настоящий. Всё остальное в
связи с потребителем держится внимательностью, а она кончается: переименовал
джоб — сломал чужую защиту ветки, снял вход у кнопки — сломал чужой вызов, и
узнаешь об этом от соседа, а не от себя.

ЧТО ТРЕБУЕТСЯ ОТ ИЗМЕНЕНИЯ, ТРОНУВШЕГО ПОВЕРХНОСТЬ: фрагмент журнала рода
`contract`. Не поднятие `CONTRACT_VERSION` — версию поднимает ВЫПУСК, а не
каждое изменение
([035](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/035-version-is-never-edited-by-hand.md)),
и требовать её здесь значило бы заставить каждое изменение выпускать проект.
Фрагмент же едет вместе с работой, называет словами, ЧТО именно в поверхности
изменилось, и попадает в раздел «Несовместимое» при сборке журнала — то есть в
то самое место, откуда потребитель узнаёт, что ему перечитывать
([030](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/030-changelog-from-fragments.md)).

ОБРАТНОЕ НЕ ТРЕБУЕТСЯ: фрагмент `contract` без видимой правки поверхности —
законен. Поверхность включает и поведение, на которое потребитель полагается —
заморозку, порядок очереди, предел попыток, — а его снимком с дерева не взять.
Краснеть на этом значило бы запрещать называть контрактным то, что механизму не
видно (046).

СРАВНИВАЕТСЯ РАЗОБРАННЫЙ СНИМОК, А НЕ ТЕКСТ ФАЙЛА. Перестановка ключей, правка
комментария и переформатирование поверхности не меняют; красное на них научило
бы обходить гейт, а не соблюдать его
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

Исходы (правило 039): ``0`` поверхность не тронута или названа фрагментом ·
``1`` тронута молча · ``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

import contract
import journal
import paths
import report

#: Род фрагмента, которым объявляется правка поверхности.
CONTRACT_KIND: Final = ".contract.md"

EXIT_CLEAN: Final = 0
EXIT_FINDINGS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «поверхность не тронута»."""


def base_tree(base: str, into: Path) -> Path:
    """Раскладывает дерево базы в отдельный каталог — снимок «до».

    Читается ДЕРЕВО базы, а не только изменённые файлы: поверхность собирается
    из всех прогонов разом, и по одному файлу её не восстановить.
    """
    done = subprocess.run(
        ["git", "archive", "--format=tar", base],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        raise NotRun(f"дерево базы «{base}» не прочитано: {report.cut(done.stderr.decode())}")
    unpack = subprocess.run(
        ["tar", "-x", "-C", str(into)], input=done.stdout, capture_output=True, check=False
    )
    if unpack.returncode != 0:
        raise NotRun(f"дерево базы не распаковалось: {report.cut(unpack.stderr.decode())}")
    return into


def untracked() -> list[str]:
    """Файлы, ещё не попавшие в индекс: их видит окно и не видит `git diff`.

    Нужны ровно для одного: свой прогон перед толчком идёт по НЕЗАКОММИЧЕННОМУ
    дереву, и гейт, смотрящий только внесённое, краснел бы там на здоровой
    работе. Ложное красное учит обходить гейт быстрее, чем настоящее учит его
    соблюдать
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    На площадке дерево чисто, и список пуст — поведение там не меняется.
    """
    done = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        return []
    return [line[3:].strip() for line in done.stdout.splitlines() if line[3:].strip()]


def declared(base: str) -> bool:
    """Есть ли во внесённом фрагмент рода `contract`."""
    names = [*journal.changed_files(base, alive_only=True), *untracked()]
    return any(
        name.startswith(f"{paths.FRAGMENTS}/") and name.endswith(CONTRACT_KIND) for name in names
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет поверхность с базой и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="", help="с чем сверять; по умолчанию база изменения")
    parser.add_argument("--show", action="store_true", help="напечатать снимок и выйти")
    args = parser.parse_args(argv)

    if args.show:
        print(contract.as_text(contract.surface()))
        return EXIT_CLEAN

    try:
        base = args.base or journal.base_from_env()
        with tempfile.TemporaryDirectory() as room:
            before = contract.surface(base_tree(base, Path(room)))
        after = contract.surface()
        changes = contract.differences(before, after)
    except journal.NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not changes:
        print("поверхность контракта не тронута")
        return EXIT_CLEAN

    print(f"поверхность контракта изменена ({len(changes)}):")
    for line in changes:
        print(f"  {line}")

    if declared(base):
        print("\nизменение объявило это фрагментом рода `contract` — так и надо")
        return EXIT_CLEAN

    print(
        "\nЭто видит потребитель: имена джобов попадают в его защиту ветки дословно,\n"
        "входы кнопки — в его вызовы, классы проверок — в его ответ. Изменение,\n"
        f"тронувшее поверхность, обязано нести фрагмент рода `contract` в\n"
        f"{paths.FRAGMENTS}/ и называть словами, ЧТО именно изменилось —\n"
        "не «обновите механизмы». Форма — changelog.d/README.md."
    )
    return EXIT_FINDINGS


if __name__ == "__main__":
    raise SystemExit(main())
