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

**Приёмку пункта называет проверка, появившаяся ПОСЛЕ постановки.** Пункт,
сформулированный свойствами («строка без адреса — отказ сборки»), первым
признаком не ловится вовсе, а таких большинство (#648). Признак сверяет
основы слов пункта с первым абзацем докстроки и именем проверок набора,
родившихся после постановки задачи. Это слабее первого признака и потому
стоит под ним: он называет проверку, а не файл, и говорит «похоже».

ЗАМЕР ВОСПРОИЗВОДИТСЯ, А НЕ ПЕРЕПИСЫВАЕТСЯ: `python scripts/items_left.py
--measure` читает все задачи и печатает, сколько пунктов называют путь,
сколько сформулированы свойствами и сколько из них признак узнаёт — среди
закрытых пунктов и среди открытых пунктов открытых задач. Числа, на которых
выбран порог, записаны один раз — у `SAME_SUBJECT`.

ГРАНИЦА: открытые пункты ЗАКРЫТЫХ задач в мерку не берутся — задачу закрыли,
а галочки не поставили, и сделан ли пункт, по ним не узнать.

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

import argparse
import ast
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple

import findings
import ghrest
import items

#: Путь внутри дерева, названный прозой пункта. Расширение обязательно: без
#: него в улов попадает всякое слово с точкой, а `scripts/` без имени файла
#: ничего не доказывает.
PATH_RE: Final = re.compile(r"[\w][\w./-]*\.(?:py|yml|yaml|json|md|toml|cfg|txt)")

#: Имя теста: у нас оно всегда `test_<что_проверяется>` и всегда объявлено в
#: дереве. Имя джоба сюда не входит намеренно — оно короткое, часто совпадает с
#: обычным словом, и совпадений было бы больше, чем находок.
TEST_RE: Final = re.compile(r"\btest_[a-z0-9_]+\b")

#: Слово прозы, из которого берётся основа: короче пяти букв — предлоги и
#: связки, они совпадают у любых двух пунктов.
WORD_RE: Final = re.compile(r"[а-яёa-z]{5,}")

#: Длина основы: русское слово меняет окончание, а «проверка» и «проверки»
#: — одно слово.
STEM: Final = 6

#: Слова, которые есть почти в любом пункте и любой докстроке и потому
#: ничего не сближают.
STOP: Final = frozenset(
    {"который", "которые", "чтобы", "потому", "только", "теперь", "всегда", "нужно"}
    | {"проверка", "проверки", "задача", "пункт", "пункта", "изменение", "изменения"}
    | {"механизм", "механизма", "должен", "может", "между", "после", "перед", "через"}
    | {"каждый", "каждая", "одного", "своего", "этого"}
)

#: Стоп-слова сверяются ОСНОВОЙ, как и само сходство: словоформа «проверку»
#: иначе проходила бы мимо «проверка» и завышала долю (`62fae56`).
STOP_STEMS: Final = frozenset(word[:STEM] for word in STOP)

#: Какая доля основ пункта должна найтись у проверки. Не подобрана на глаз:
#: `python scripts/items_left.py --measure`, 24.09.2026 — закрытых пунктов 125,
#: свойствами 108; при 0.4 признак узнаёт 33 из 108 и ложно срабатывает на
#: одном открытом пункте открытых задач из 13; при 0.3 — 45 и два ложных, при
#: 0.5 — 17 и ни одного (#648).
SAME_SUBJECT: Final = 0.4

#: Пункт короче трёх основ сравнивать не с чем: любая проверка совпадёт.
MIN_STEMS: Final = 3

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

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


class Subject(NamedTuple):
    """Проверка набора как предмет: имя, основы её слов и дата рождения."""

    name: str
    stems: frozenset[str]
    born: datetime


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
    # ОТКАЗ GIT — НЕ ОТВЕТ «НЕ МЕЛКИЙ». Здесь исход не читался вовсе, и пустой
    # `stdout` при отказе давал `False`: «клон полный» вместо «спросить не
    # удалось». Дальше `born` шла по обрезанной истории и возвращала
    # правдоподобную, но неверную дату — ровно тот ложноположительный случай,
    # о котором предупреждает докстрока выше
    # ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    # Незнание трактуется как «мелкий»: сторону выбираем ту, где механизм
    # МОЛЧИТ, а не врёт уверенно. Нашёл внешний взгляд на #572.
    if done.returncode:
        return True
    return done.stdout.strip() == "true"


def born(path: str, root: Path | None = None) -> datetime | None:
    """Когда имя впервые появилось в истории. ``None`` — история недоступна."""
    if shallow(root):
        return None
    done = subprocess.run(
        # `--follow`: файл, переименованный после постановки задачи, иначе
        # получал дату переименования — и сильный признак счёл бы пункт с этим
        # путём сделанным (`fbe345c`). С `--follow` добавлением остаётся
        # только первое появление содержимого под любым прежним именем.
        ["git", "log", "--follow", "--diff-filter=A", "--format=%aI", "--", path],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        return None
    dates = [
        datetime.fromisoformat(line.strip()).astimezone(UTC)
        for line in done.stdout.splitlines()
        if line.strip()
    ]
    # Наименьшая дата, а не последняя строка: после rebase и cherry-pick
    # авторские даты идут не по порядку истории (`c37440f`).
    return min(dates, default=None)


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
    # Наименьшая дата, а не первая в порядке `--reverse` — как у `born` и
    # `tests_born`: после rebase и cherry-pick даты идут не по порядку истории
    # (`8c3fad9`).
    return min(
        (
            datetime.fromisoformat(line.strip()).astimezone(UTC)
            for line in done.stdout.splitlines()
            if line.strip()
        ),
        default=None,
    )


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


def stems(text: str) -> frozenset[str]:
    """Основы значимых слов текста."""
    found = {word[:STEM] for word in WORD_RE.findall(text.lower())}
    return frozenset(found - STOP_STEMS)


#: Строка диффа, добавляющая проверку.
DEF_RE: Final = re.compile(r"^\+\s*def (test_\w+)")


def tests_born(root: Path | None = None) -> dict[str, datetime]:
    """Когда каждое имя проверки впервые вошло в дерево — одним обходом истории.

    КЛЮЧ — ИМЯ, И ЭТО ВЫБОР СТОРОНЫ ОШИБКИ. Ключ «файл::имя» (`1ca2bb6`)
    принёс два дефекта: переименованный без правок файл терял все даты (дифф
    переименования не несёт строк `+def`), а проверка, перенесённая в другой
    файл, получала дату переноса и ложно выглядела рождённой после задачи
    (`b8cd638`, `58140c6`). Ключ по имени с САМОЙ РАННЕЙ датой ошибается в одну
    сторону: одноимённая проверка в другом файле получает более старую дату —
    и признак МОЛЧИТ, а не говорит неверно (051). Переименование и перенос он
    переживает: имя то же, дата первая.

    Мелкий клон — пусто: дата рождения там у всех одна, и признак молчал бы
    не хуже, чем врал бы (см. `shallow`).
    """
    if shallow(root):
        return {}
    done = subprocess.run(
        ["git", "log", "--reverse", "--format=@%aI", "-p", "--no-color", "--", "tests/"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        return {}
    found: dict[str, datetime] = {}
    when: datetime | None = None
    for line in done.stdout.splitlines():
        if line.startswith("@") and line[1:2].isdigit():
            when = datetime.fromisoformat(line[1:].strip()).astimezone(UTC)
            continue
        said = DEF_RE.match(line)
        # Наименьшая дата, а не первая в порядке `--reverse`: после rebase и
        # cherry-pick авторские даты идут не по порядку истории (`c37440f`).
        if said and when and (said[1] not in found or when < found[said[1]]):
            found[said[1]] = when
    return found


def subjects(root: Path | None = None) -> list[Subject]:
    """Проверки набора с основами первого абзаца докстроки и имени."""
    born = tests_born(root)
    if not born:
        return []
    found: list[Subject] = []
    for path in sorted((root or Path()).joinpath("tests").glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in born:
                continue
            first = (ast.get_docstring(node) or "").split("\n\n")[0]
            said = stems(f"{first} {node.name.replace('_', ' ')}")
            found.append(Subject(f"{path.name}::{node.name}", said, born[node.name]))
    return found


def subject_evidence(item: str, since: datetime, pool: list[Subject]) -> list[str]:
    """Проверка, родившаяся после постановки и называющая приёмку пункта, — если есть."""
    mine = stems(item)
    if len(mine) < MIN_STEMS:
        return []
    close = [(len(mine & one.stems) / len(mine), one.name) for one in pool if one.born > since]
    best = max(close, default=(0.0, ""))
    if best[0] < SAME_SUBJECT:
        return []
    return [f"{best[1]} — по свойству, сходство {best[0]:.2f}"]


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
    pool = subjects(root)
    at = now or datetime.now(UTC)
    built: list[Candidate] = []
    named: set[int] = set()
    for issue in issues:
        number = int(issue["number"])
        title = str(issue.get("title") or "")
        since = when_of(issue, "created_at")
        for item in open_items(str(issue.get("body") or "")):
            # Признак по свойству — ПОД признаком по пути: говорит, только
            # когда сильный промолчал (#648).
            found = evidence(item, since, files, root) or subject_evidence(item, since, pool)
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


class Measure(NamedTuple):
    """Замер признака по свойству: на чём выбран порог `SAME_SUBJECT`."""

    closed: int
    closed_named: int
    closed_found: int
    open_left: int
    open_found: int


def measure(issues: list[dict[str, Any]], root: Path | None = None) -> Measure:
    """Сколько пунктов называют путь и сколько узнаёт признак по свойству.

    Закрытые пункты — сделанная работа, открытые пункты ОТКРЫТЫХ задач — в
    основном несделанная; первое — доля узнанного, второе — ложные. Задачи,
    которые ведёт механизм (реестры, план), в счёт не идут: их тело
    пересобирается, и галочки там не о работе.
    """
    pool = subjects(root)
    closed = named = found = left = wrong = 0
    for issue in issues:
        body = str(issue.get("body") or "")
        if "pull_request" in issue or findings.is_kept_by_a_mechanism(body):
            continue
        if body.startswith(findings.PLAN_MARKER):
            continue
        since = when_of(issue, "created_at")
        for item in items.done_items(body):
            closed += 1
            if PATH_RE.search(item) or TEST_RE.search(item):
                named += 1
            elif subject_evidence(item, since, pool):
                found += 1
        if issue.get("state") != "open":
            continue
        for item in items.open_items(body):
            if PATH_RE.search(item) or TEST_RE.search(item):
                continue
            left += 1
            wrong += bool(subject_evidence(item, since, pool))
    return Measure(closed, named, found, left, wrong)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: замер признака по свойству по всем задачам."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measure", action="store_true", help="замер признака по свойству")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)
    if not args.measure:
        parser.error("назовите --measure: другого захода у модуля нет")
    try:
        if not args.repo:
            raise ghrest.TransportError("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        token = ghrest.token_from_env()
        issues = list(ghrest.paginate(f"repos/{args.repo}/issues?state=all", token))
    except ghrest.TransportError as exc:
        print(f"замер не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    said = measure(issues)
    props = said.closed - said.closed_named
    print(
        f"закрытых пунктов {said.closed}: называют путь или тест {said.closed_named}, "
        f"свойствами {props}, из них признак по свойству узнаёт {said.closed_found}"
    )
    print(
        f"открытых пунктов открытых задач свойствами {said.open_left}, "
        f"признак срабатывает на {said.open_found}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
