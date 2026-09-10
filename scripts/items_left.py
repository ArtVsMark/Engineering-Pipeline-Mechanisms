#!/usr/bin/env python3
"""Открытый пункт задачи, за которым, похоже, уже есть работа.

СЧЁТ ИДЁТ В ОДНУ СТОРОНУ, И ЭТО БЫЛО ПОЛОВИНОЙ КАРТИНЫ. `debt` называет
задачу, у которой все пункты закрыты, а сама она открыта. Обратное — пункт
открыт, а работа сделана — не видел никто, и именно оно копится: замер
10.09.2026 по четырём задачам с пунктами нашёл четыре таких пункта, старшему из
них шёл второй день.

ДВА ПРИЗНАКА, И ОНИ РАЗНОЙ СИЛЫ.

**Названное существует и появилось ПОСЛЕ постановки.** Пункт, называющий
исполняемое — путь к прогону, скрипту, тесту, данным, — сверяется с деревом.
Файл, которого на день постановки не было, а сейчас он есть, означает, что
работа по этому имени велась. Признак говорит по делу и врёт редко, но видит
только пункты, называющие исполняемое: «шаблон обращения трёх видов» им не
ловится вовсе.

**Задача давно не двигалась.** Открытые пункты есть, а событий по задаче нет
дольше срока. Признак покрывает всё и не отвечает ни на что: он не «сделано»,
а «посмотрите». Тем и полезен там, где первый слеп.

ВТОРОЙ МОЛЧИТ ТАМ, ГДЕ СРАБОТАЛ ПЕРВЫЙ. Один долг, названный дважды, читается
как два, а списки того же самого расходятся молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Сильный признак говорит, ЧТО именно найдено; слабому после этого сказать
нечего.

ЭТО СЧЁТ, А НЕ ПРИКАЗ. Механизм называет кандидата и не отмечает ничего:
«сделано» и «названо похоже» ему неразличимы, а отметка пункта — заявление о
работе
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
Отмечает пункт изменение — трейлером `Закрывает пункт:`, — и вот там оно
проверяемо.
"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple

#: Путь внутри дерева, названный прозой пункта. Расширение обязательно: без
#: него в улов попадает всякое слово с точкой, а `scripts/` без имени файла
#: ничего не доказывает.
PATH_RE: Final = re.compile(r"[\w][\w./-]*\.(?:py|yml|yaml|json|md|toml|cfg|txt)")

#: Имя теста: у нас оно всегда `test_<что_проверяется>` и всегда объявлено в
#: дереве. Имя джоба сюда не входит намеренно — оно короткое, часто совпадает с
#: обычным словом, и совпадений было бы больше, чем находок.
TEST_RE: Final = re.compile(r"\btest_[a-z0-9_]+\b")

#: Сколько дней без событий делает задачу с открытыми пунктами кандидатом на
#: взгляд. Величина объявлена здесь, а не выведена: она про внимание человека,
#: и меряется его смены, а не данными.
QUIET_AFTER: Final = 7


class Candidate(NamedTuple):
    """Открытый пункт и то, чем он выглядит сделанным."""

    number: int
    title: str
    item: str
    evidence: list[str]


class Quiet(NamedTuple):
    """Задача с открытыми пунктами, по которой давно ничего не происходило."""

    number: int
    title: str
    days: int
    left: int


def tracked(root: Path | None = None) -> set[str]:
    """Отслеживаемые файлы дерева.

    Берётся `git ls-files`, а не обход каталога: в кешах и виртуальных
    окружениях лежат тысячи чужих имён, и ни одного из них проект не правит.
    """
    done = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        return set()
    return {name for name in done.stdout.split("\0") if name}


def shallow(root: Path | None = None) -> bool:
    """Мелкий ли клон — то есть можно ли вообще спрашивать «когда появилось».

    ЭТО НЕ ПРЕДОСТОРОЖНОСТЬ, А ПОЧИНКА. В мелком клоне история обрезана до
    одного коммита, и `git log --diff-filter=A` показывает ВСЕ файлы
    добавленными в нём: дата появления любого файла становится датой захода.
    Сильный признак опирается на «появилось ПОСЛЕ постановки» — и срабатывал бы
    на каждом названном файле, то есть врал бы уверенно.

    Джоб `debt` берёт дерево `actions/checkout` без `fetch-depth`, а его
    умолчание — единица. Нашёл внешний взгляд на #149; на дереве окна клон
    полный, и локально это не воспроизводилось.
    """
    done = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return done.stdout.strip() == "true"


def born(path: str, root: Path | None = None) -> datetime | None:
    """Когда имя впервые появилось в истории. ``None`` — история недоступна."""
    if shallow(root):
        return None
    done = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%aI", "--", path],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        return None
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    return datetime.fromisoformat(lines[-1]).astimezone(UTC)


def born_symbol(name: str, root: Path | None = None) -> datetime | None:
    """Когда объявление с этим именем впервые вошло в дерево.

    Спрашивается объявление (`def <имя>`), а не любое упоминание: имя теста
    встречается и в прозе задачи, и в чужом сообщении коммита.
    """
    if shallow(root):
        return None
    done = subprocess.run(
        ["git", "log", "-S", f"def {name}", "--format=%aI", "--reverse"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        return None
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    return datetime.fromisoformat(lines[0]).astimezone(UTC)


def evidence(item: str, since: datetime, files: set[str], root: Path | None = None) -> list[str]:
    """Что из названного пунктом появилось в дереве ПОСЛЕ его постановки.

    «Появилось после» — вся сила признака. Файл, существовавший на день
    постановки, не доказывает ничего: пункт мог называть его как МЕСТО будущей
    работы, и «добавить счёт в `scripts/debt.py`» выглядело бы сделанным с
    первого дня.
    """
    found: list[str] = []
    for path in PATH_RE.findall(item):
        if path not in files:
            continue
        when = born(path, root)
        if when and when > since:
            found.append(path)
    for name in TEST_RE.findall(item):
        when = born_symbol(name, root)
        if when and when > since:
            found.append(f"{name}()")
    return found


def when_of(issue: dict[str, Any], key: str) -> datetime:
    """Отметка времени задачи в UTC."""
    return datetime.fromisoformat(str(issue[key]).replace("Z", "+00:00")).astimezone(UTC)


def look(
    issues: list[dict[str, Any]],
    open_items: Any,
    *,
    now: datetime | None = None,
    quiet_after: int = QUIET_AFTER,
    root: Path | None = None,
) -> tuple[list[Candidate], list[Quiet]]:
    """Оба счёта разом: сильный признак и слабый под ним.

    Второй список строится по задачам, которых НЕТ в первом: один долг,
    названный дважды, читается как два (022).
    """
    files = tracked(root)
    at = now or datetime.now(UTC)
    built: list[Candidate] = []
    named: set[int] = set()
    for issue in issues:
        number = int(issue["number"])
        title = str(issue.get("title") or "")
        since = when_of(issue, "created_at")
        for item in open_items(str(issue.get("body") or "")):
            found = evidence(item, since, files, root)
            if found:
                built.append(Candidate(number, title, item, found))
                named.add(number)

    quiet: list[Quiet] = []
    for issue in issues:
        number = int(issue["number"])
        if number in named:
            continue
        left = len(open_items(str(issue.get("body") or "")))
        if not left:
            continue
        days = (at - when_of(issue, "updated_at")).days
        if days >= quiet_after:
            quiet.append(Quiet(number, str(issue.get("title") or ""), days, left))
    return built, quiet
