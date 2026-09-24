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

ВТОРОЙ ПРЕДМЕТ — РОД НАХОДКИ У ПОРОГА ПОВТОРА (#650). Класс ошибки,
встреченный трижды, спрашивается о правиле в том изменении, которым дошёл до
порога; ответ живёт в самом роде (`.rules/finding-kinds.json`, поле
`каталогу`). ГРАНИЦА: инциденты источников 0–2 — краснота общей ветки,
конфликт и красное на своём изменении — живут в реестре красноты, а у его
записей нет рода: повтор там узнаётся по имени задания, и мигающее задание
уходит в список перезапуска со своей причиной (`.rules/rerun.json`).
Спрашивать правило у мигания площадки — не про то, и гейт этого не делает
(`d4ae968`).

Исходы (правило 039): ``0`` ответ есть у каждой новой записи и у каждого рода,
дошедшего до порога · ``1`` запись или род молчит · ``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import check_journal
import finding_kinds
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


#: Слаг ответа разбирает словарь родов — одна разборка на решения и роды (022).
#: История разборки переехала вместе с функцией: `finding_kinds.slug_of`.
slug_of = finding_kinds.slug_of


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


def kinds_at(base: str, root: Path = Path()) -> dict[str, Any]:
    """Роды находок на базе изменения; файла там нет — родов ещё не было."""
    where = paths.FINDING_KINDS.as_posix()
    try:
        done = subprocess.run(
            ["git", "show", f"{base}:{where}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise NotRun(f"роды на базе не прочитаны ({base}): {exc}") from exc
    if done.returncode != 0:
        # ФАЙЛА НЕТ НА БАЗЕ — ЭТО «РОДОВ НЕ БЫЛО», А НЕ ОТКАЗ. Всё прочее —
        # неизвестная база, битый клон — отказ: молча принять пустую базу
        # значило бы объявить новыми все роды разом. Формы отказа git берутся
        # у шага журнала, а не пишутся второй раз (`493815f`, `783fb08`).
        if any(said in done.stderr for said in check_journal.NO_SUCH_PATH):
            return {}
        raise NotRun(f"роды на базе не прочитаны ({base}): {done.stderr.strip()}")
    try:
        return dict(json.loads(done.stdout).get("kinds") or {})
    except (json.JSONDecodeError, AttributeError) as exc:
        raise NotRun(f"роды на базе не разбираются ({base}): {exc}") from exc


def crossed(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Роды, которые дошли до порога повтора ЭТИМ изменением.

    ВТОРОЙ МОМЕНТ ВОПРОСА, И ОН О ИНЦИДЕНТАХ (#650). Запись решения спрашивали
    о правиле с 16.09.2026, а класс ошибки, повторившийся трижды, — никогда:
    род чинили, закрывали механизмом, и на этом всё. Замер 23.09.2026: родов у
    порога восемь, ответа каталогу нет ни у одного. Спрашивается ПРИРОСТ, как и
    у решений: род, дошедший до порога раньше, требовать ответа задним числом
    не заставляет — его называет план, разделом 5.
    """
    at = finding_kinds.REPEATED_AT

    def times(kinds: dict[str, Any], name: str) -> int:
        return len((kinds.get(name) or {}).get("встречен") or [])

    return sorted(name for name in after if times(after, name) >= at > times(before, name))


def kinds_missing(names: list[str], after: dict[str, Any], queue: str) -> list[str]:
    """Роды у порога, чей ответ каталогу отсутствует или не сходится."""
    told: list[str] = []
    for name in names:
        problem = finding_kinds.answer_problem(after[name], queue)
        if problem is not None:
            told.append(f"  род «{name}» дошёл до порога: {problem}")
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
        queue = queued(args.root / paths.PROPOSALS)
        told = missing(new, queue, args.root)
        # РОДЫ ЧИТАЮТСЯ У ТОГО ЖЕ СОСТОЯНИЯ, ЧТО И ЗАПИСИ РЕШЕНИЙ: «до» — у
        # базы, «после» — у головы, обе через git. Прежде «после» читалось с
        # диска корня, а записи — диапазоном коммитов, и незакоммиченная правка
        # словаря судилась, а закоммиченная в другом коммите — нет (`c9a1c47`).
        # Словаря нет у головы — роды не ведутся, и это не отказ: шаг журнала
        # переносим, и у потребителя словаря может не быть вовсе.
        after = kinds_at(args.head, args.root)
        grown = crossed(kinds_at(args.base, args.root), after) if after else []
        told += kinds_missing(grown, after, queue)
    except (NotRun, finding_kinds.NotRun) as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # ЗАПИСЕЙ НЕ ДОБАВЛЕНО — ЗАКОННОЕ СОСТОЯНИЕ, И ТОЛЬКО ЗДЕСЬ. Изменение без
    # решения этому правилу не подчиняется; требовать предмета от него значило бы
    # красить исправную работу. Это НЕ тот случай, где пустота подозрительна: у
    # гейта есть свой прогон на подделках, и он держит оба отказа.
    if not new and not grown:
        print("записей решений не добавлено и порога род не перешёл — вопрос о правиле не встаёт")
        return EXIT_OK
    if told:
        print(
            f"новых записей решений: {len(new)}, родов у порога: {len(grown)}, "
            f"без ответа каталогу: {len(told)}",
            file=sys.stderr,
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
