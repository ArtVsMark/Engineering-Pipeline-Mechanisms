#!/usr/bin/env python3
"""Гейт: запись решения называет судьбу правила, а не молчит о ней.

ПРАВИЛА РОЖДАЮТСЯ ЗДЕСЬ, И КАНАЛ ДЛЯ ЭТОГО ЕСТЬ. `.rules/proposals.json` —
очередь на приём в общий каталог, и она РАБОТАЛА: 11.09.2026 каталог принял
четыре наших предложения, и они стали правилами 198–201.

ЧЕГО НЕТ — МОМЕНТА, В КОТОРЫЙ ВОПРОС ЗАДАЮТ. У всякой другой обязанности
проекта момент есть: слияние, расписание, прогон. А «не родилось ли здесь
правило» не спрашивается никогда и ни у кого — это решалось наитием.

ЗАМЕР 16.09.2026: записей решений в дереве 27, из них **16 появились после
12.09.2026**, и предложений каталогу за то же время — **ноль**. Число само по
себе ничего не доказывает: почти все те решения и правда свои. Доказывает
другое — пустая очередь НЕОТЛИЧИМА от «никто не спросил», а такое состояние
правило
[045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)
и запрещает. Сам файл объявляет пустоту законной — и законной она остаётся; речь
не о ней, а о том, что за ней не видно ответа.

ГЕЙТ НЕ РЕШАЕТ, ПРАВИЛО ЭТО ИЛИ НЕТ. Из дерева это не следует, и решать за
человека он не берётся
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
Он требует ОТВЕТА — любого из двух, — и отвергает молчание.

СУДИТ ТОЛЬКО ДОБАВЛЕННЫЕ ЗАПИСИ. Двадцать семь прежних строки не несут, и
требовать её от них значило бы переписывать принятые решения задним числом —
ровно то, что запрещает
[043](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/043-decisions-are-superseded-not-edited.md).
Тот же приём у гейта «новое приезжает со своим прогоном»: предмет — прирост, а не
дерево целиком.

Исходы (правило 039): ``0`` ответ есть у каждой новой записи · ``1`` запись
молчит · ``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import paths

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Строка ответа. Два вида, и оба названы: «предложено» несёт слаг предложения,
#: «своё» — причину, почему каталогу это не нужно. Третьего вида нет намеренно:
#: «потом посмотрим» — это и есть молчание, только записанное.
FATE_RE: Final = re.compile(
    r"^\*\*Каталогу:\*\*\s+(?P<kind>предложено|своё)\s+—\s+(?P<said>\S.*)$", re.M
)


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «ответ есть»."""


def added(base: str, head: str = "HEAD") -> list[str]:
    """Записи решений, ДОБАВЛЕННЫЕ этим изменением.

    Список путей читается по NUL: без него git экранирует имена с не-ASCII, и
    такой путь молча выпадает из отбора
    ([165](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/165-git-file-list-needs-nul.md)).
    """
    try:
        done = subprocess.run(
            ["git", "diff", "--diff-filter=A", "--name-only", "-z", f"{base}..{head}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NotRun(f"состав изменения не прочитан ({base}..{head}): {exc}") from exc
    return [
        path
        for path in done.stdout.split("\0")
        if path.startswith(f"{paths.DECISIONS}/") and path.endswith(".md") and "README" not in path
    ]


def fate(text: str) -> tuple[str, str] | None:
    """Ответ записи о судьбе правила: вид и сказанное; ``None`` — ответа нет."""
    found = FATE_RE.search(text)
    return (found["kind"], found["said"].strip()) if found else None


def queued(where: Path | None = None) -> str:
    """Очередь предложений одной строкой — в ней и ищется слаг.

    Ищется ВХОЖДЕНИЕМ, а не разбором поля: форму записи задаёт контракт
    КАТАЛОГА (`export/README.md`), а не мы, и свой разбор его полей разошёлся бы
    с ним молча — это уже случалось, когда набор искал вердикты под чужим ключом
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    path = where or paths.PROPOSALS
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotRun(f"очередь предложений не прочитана ({path}): {exc}") from exc


#: Оформление вокруг слага: обратные кавычки, кавычки-ёлочки и знак конца
#: предложения. Снимается ДО сверки с очередью.
AROUND_SLUG: Final = "`\"'«».,;:()[]"


def slug_of(said: str) -> str:
    """Слаг из строки ответа — без оформления вокруг него.

    ГЕЙТ СУДИТ СУЩЕСТВО, А НЕ РАЗМЕТКУ. Первое слово строки бралось целиком, и
    слаг, записанный в обратных кавычках — то есть ровно так, как имя пишут в
    документе этого проекта повсюду, — не сходился с очередью: гейт видел
    «`имя`.» и честного ответа не признавал. Красное на законном учит обходить
    красное
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Поймано 17.09.2026 на ПЕРВОЙ же записи с ответом «предложено» — до неё у
    этой ветки разбора не было живого предмета вовсе.
    """
    first = said.split()[0] if said.split() else ""
    return first.strip(AROUND_SLUG)


def missing(paths_: list[str], queue: str, root: Path = Path()) -> list[str]:
    """Записи, чей ответ отсутствует или не сходится с очередью."""
    told: list[str] = []
    for one in paths_:
        try:
            text = (root / one).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise NotRun(f"{one} не прочитан: {exc}") from exc
        said = fate(text)
        if said is None:
            told.append(
                f"  {one}: нет строки «**Каталогу:** предложено — <слаг>» "
                "или «**Каталогу:** своё — <причина>»"
            )
            continue
        kind, what = said
        if kind != "предложено":
            continue
        slug = slug_of(what)
        # ПУСТОЙ СЛАГ — НЕ СОВПАДЕНИЕ, А ОТСУТСТВИЕ ИМЕНИ. Сверка идёт вхождением
        # в текст очереди, а пустая строка входит в ЛЮБОЙ текст: ответ
        # «предложено — ``» проходил гейт целиком. Нашёл внешний взгляд на #428;
        # соседний тест даже держал, что `slug_of("``")` даёт пустую строку, —
        # и последствия этого не замечал.
        if not slug:
            told.append(
                f"  {one}: ответ «предложено», а имени предложения нет — "
                "пустое имя совпадает с любой очередью и потому не ответ (045)"
            )
        elif slug not in queue:
            told.append(
                f"  {one}: назван слаг «{slug}», а в очереди предложений "
                f"({paths.PROPOSALS}) его нет — ответ обещает то, чего не отправили"
            )
    return told


def main(argv: list[str] | None = None) -> int:
    """Точка входа: у каждой новой записи решения назван ответ каталогу."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="база изменения")
    parser.add_argument("--head", default="HEAD", help="голова изменения")
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    try:
        new = added(args.base, args.head)
        told = missing(new, queued(args.root / paths.PROPOSALS), args.root)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # ЗАПИСЕЙ НЕ ДОБАВЛЕНО — ЗАКОННОЕ СОСТОЯНИЕ, И ТОЛЬКО ЗДЕСЬ. Изменение без
    # решения этому правилу не подчиняется; требовать предмета от него значило бы
    # красить исправную работу. Это НЕ тот случай, где пустота подозрительна: у
    # гейта есть свой прогон на подделках, и он держит оба отказа.
    if not new:
        print("записей решений не добавлено — вопрос о правиле не встаёт")
        return EXIT_OK
    if told:
        print(
            f"новых записей решений: {len(new)}, без ответа каталогу: {len(told)}", file=sys.stderr
        )
        for one in told:
            print(one, file=sys.stderr)
        print(
            "\nОтвет обязан быть любым из двух, но обязан быть: правило либо "
            "предложено общему каталогу, либо объявлено своим с причиной. Гейт не "
            "решает, какое из двух, — он не даёт промолчать (154).",
            file=sys.stderr,
        )
        return EXIT_FOUND
    print(f"новых записей решений: {len(new)}, у каждой назван ответ каталогу")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
