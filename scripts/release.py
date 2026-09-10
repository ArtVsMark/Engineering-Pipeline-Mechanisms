#!/usr/bin/env python3
"""Выпуск: необратимый шаг проверяется ДО прогона, а не прогоном.

Порядок выпуска записан в `docs/release.md` с самого начала, а механизма под ним
не было: путь ни разу не проходили целиком, и «работает» держалось тем, что его
никто не пробовал
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

ТЕГ НЕ ПЕРЕСТАВЛЯЕТСЯ, И ЭТО ОПРЕДЕЛЯЕТ ВСЮ ФОРМУ. Шаг, который нельзя
отменить, получает собственную проверку ПЕРЕД собой, а не разбор последствий
после
([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)).
Поэтому заход разделён надвое: сначала все условия проверяются на сухую и
печатаются, и лишь потом — с ключом `--apply` — делается то, что откатить
нельзя.

РАЗРЯД НОМЕРА НЕ ВЫДУМЫВАЕТСЯ, А ЧИТАЕТСЯ У ФРАГМЕНТОВ. Род `contract` среди
них означает, что поверхность тронута, — такой выпуск не может быть патчем.
Механизм не выбирает разряд за человека: он отвергает номер, который
фрагментам противоречит
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

МАЖОР ДО ЕДИНИЦЫ ПОДНИМАЕТ НЕ ВЫПУСК, А ПЕРВЫЙ ПОТРЕБИТЕЛЬ. `0.x` означает
ровно одно: поверхность ещё никому не обещана. Это записано в `docs/release.md`
до первого потребителя и задним числом не вводится
([113](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/113-a-contract-states-how-it-may-change.md)),
поэтому переход `0.y → 1.0` механизм требует объявить отдельно — ключом
`--first-consumer` с именем того, кто прибился.

Исходы (правило 039): ``0`` выпуск готов либо сделан · ``1`` условия не
сошлись · ``2`` шаг не отработал.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import build_changelog
import paths
import report
import version as project_version

VERSION_RE: Final = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
#: Род фрагмента, объявляющий правку поверхности контракта.
CONTRACT_KIND: Final = ".contract.md"

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «выпускать нечего»."""


def git(*args: str) -> str:
    """Ответ git; отказ — это отказ входа, а не пустая строка."""
    done = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if done.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {report.cut(done.stderr.strip())}")
    return done.stdout.strip()


def fragments() -> list[Path]:
    """Фрагменты, ожидающие выпуска."""
    return sorted(p for p in paths.FRAGMENTS.glob("*.md") if p.name != "README.md")


def touches_contract(waiting: list[Path]) -> list[str]:
    """Фрагменты, объявившие правку поверхности."""
    return [p.name for p in waiting if p.name.endswith(CONTRACT_KIND)]


def declared_version() -> str:
    """Объявленная версия контракта — то, от чего считается следующая."""
    return paths.VERSION.read_text(encoding="utf-8").strip()


def next_after(current: str, *, contract: bool) -> str:
    """Какой номер выпуска ожидается после текущего.

    МИНОР растёт ВСЕГДА при постановке тега — схема семьи держит инвариант
    «каждый тег вида `vX.Y.0`», и патч-тегов не существует. Правка поверхности
    при этом не поднимает мажор сама: `0.x` живёт до первого потребителя.
    """
    found = VERSION_RE.match(current)
    if found is None:
        raise NotRun(f"объявленная версия «{current}» не вида МАЖОР.МИНОР.ПАТЧ")
    major, minor = int(found.group(1)), int(found.group(2))
    return f"{major}.{minor + 1}.0"


def refusals(wanted: str, *, first_consumer: str) -> list[str]:
    """Все причины НЕ выпускать — списком, а не первой попавшейся.

    Списком потому, что выпуск делают редко и по одной причине за раз чинить
    его дороже: человек должен увидеть сразу всё, что мешает.
    """
    problems: list[str] = []
    if VERSION_RE.match(wanted) is None:
        return [f"версия «{wanted}» не вида МАЖОР.МИНОР.ПАТЧ"]

    waiting = fragments()
    if not waiting:
        problems.append("ни одного фрагмента — это ошибка входа, а не пустой выпуск (075)")

    if git("status", "--porcelain"):
        problems.append("дерево грязно: выпуск делается с чистого дерева, иначе тег врёт")

    tags = git("tag", "--list", f"v{wanted}")
    if tags:
        problems.append(f"тег v{wanted} уже стоит — тег не переставляется (074)")

    current = declared_version()
    expected = next_after(current, contract=bool(touches_contract(waiting)))
    major_now = int(VERSION_RE.match(current).group(1))  # type: ignore[union-attr]
    major_wanted = int(VERSION_RE.match(wanted).group(1))  # type: ignore[union-attr]

    if major_wanted > major_now and not first_consumer:
        problems.append(
            f"мажор {major_now} → {major_wanted} поднимает не выпуск, а появление первого "
            "потребителя: «0.x» значит «поверхность ещё никому не обещана» (docs/release.md). "
            "Назовите его: --first-consumer <владелец/репозиторий>"
        )
    elif major_wanted == major_now and wanted != expected:
        problems.append(
            f"ожидается {expected}, а названо {wanted}: минор растёт при каждой постановке "
            "тега — схема держит инвариант «каждый тег вида vX.Y.0»"
        )
    return problems


def announce(wanted: str, *, first_consumer: str) -> None:
    """Печатает, из чего собран выпуск: человек читает это перед необратимым."""
    waiting = fragments()
    contract = touches_contract(waiting)
    print(f"выпуск {wanted}: фрагментов {len(waiting)}, из них о поверхности {len(contract)}")
    for name in contract:
        print(f"  поверхность: {name}")
    number, whole = project_version.version()
    print(
        f"версия проекта на этой голове: {number}" + ("" if whole else " (неполна: тегов не видно)")
    )
    if first_consumer:
        print(f"первый потребитель: {first_consumer} — им и поднимается мажор")


def do_release(wanted: str) -> None:
    """Необратимая часть: журнал, версия, коммит, тег.

    Порядок ровно тот, что записан в `docs/release.md`, и он часть проверки, а
    не соглашение: тег ставится последним, когда всё остальное уже в коммите.
    """
    build_changelog.do_release(wanted)
    paths.VERSION.write_text(f"{wanted}\n", encoding="utf-8")
    build_changelog.main([])
    git("add", "-A")
    git("commit", "-m", f"release: {wanted}")
    git("tag", "-a", f"v{wanted}", "-m", f"v{wanted}")
    print(f"выпуск {wanted} собран и помечен тегом v{wanted}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сухая проверка, а по ключу — необратимый шаг."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="номер выпуска; по умолчанию следующий")
    parser.add_argument("--apply", action="store_true", help="сделать необратимое")
    parser.add_argument(
        "--first-consumer",
        default="",
        help="владелец/репозиторий того, кто прибился: только им поднимается мажор",
    )
    args = parser.parse_args(argv)

    try:
        wanted = args.version or next_after(
            declared_version(), contract=bool(touches_contract(fragments()))
        )
        problems = refusals(wanted, first_consumer=args.first_consumer)
        announce(wanted, first_consumer=args.first_consumer)
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if problems:
        print(f"\nвыпускать нельзя ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")
        return EXIT_REFUSED

    if not args.apply:
        print("\nусловия сошлись. Необратимое делается ключом --apply")
        return EXIT_OK

    try:
        do_release(wanted)
    except (NotRun, build_changelog.NotRun) as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
