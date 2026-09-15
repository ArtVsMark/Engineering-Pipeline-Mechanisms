"""Сверяет обязательный контекст защиты ветки с тем, что выдаёт дерево.

Настройка защиты живёт **вне дерева**: её не видит ни ревью, ни прогон. Поэтому
расхождение между именем джоба и именем в списке обязательных не ловится ничем
и обнаруживается простоем — у соседнего проекта защита требовала контекста,
которого не выдавал ни один прогон, и не сливалось ничего при зелёных
проверках.

Что проверяется:

* в списке обязательных **ровно одно** имя — список, перечисляющий матрицу,
  ломается при добавлении версии;
* это имя выдаёт джоб, объявленный в дереве прогонов;
* матричные имена в список не попали;
* способ слияния ограничен уплотнением — решение ``006``, а держится оно тоже
  настройкой вне дерева.

ПРО СПОСОБ СЛИЯНИЯ — ЭТО ВТОРАЯ НАСТРОЙКА ТОГО ЖЕ РОДА, И МЕСТО ЕЙ ЗДЕСЬ.
Проект решил сливать уплотнением (``docs/decisions/006-merge-by-squash.md``), а
площадка по-прежнему разрешает merge-коммит и перестановку. Гейт
``tests/test_squash_only.py`` ловит нарушение ПОСЛЕ слияния — по истории общей
ветки, когда чинить уже нечем. Дешёвый способ предотвратить его вместо того,
чтобы ловить повторение, — снять лишние кнопки в настройках; сделать это может
только владелец, а увидеть разрыв — эта сверка. Нашёл внешний взгляд на #167.

Прав на чтение защиты у токена прогона нет, и это не поломка, а
ненастроенность: без токена владельца сверка не выполняется и говорит об этом
(исход 1), вместо того чтобы молча зеленеть.

Исходы (правило 039): ``0`` совпадает · ``1`` расхождение или сверка не
настроена · ``2`` не отработало.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Final

import ghrest
import paths
import protection
import yaml

#: Где живёт сводный джоб. Файл НЕ назван одним именем намеренно: 11.09.2026
#: гейт переехал из `ci.yml` в собственный прогон, чтобы группа отмены `ci` не
#: гасила обязательный контекст, — и сверка, прибитая к имени файла, сломалась
#: бы этим переездом. Ищется джоб по ИМЕНИ во всех прогонах: имя и есть предмет
#: договора с защитой ветки, а файл — его адрес, и адрес вправе меняться (168).
GATES_DIR: Final = paths.WORKFLOWS

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
#: Единицу отдаёт сам Python при необработанном сбое, поэтому объявленным
#: состоянием она быть не может: иначе сломанный механизм читается как
#: работающий. Объявленные исходы — 0, 2 и 3; всё прочее отказ (068).
EXIT_FINDINGS: Final = 3


class NotRun(RuntimeError):
    """Сверка не отработала: третий исход, а не «совпадает»."""


def declared_context(summary_job: str) -> str:
    """Отдаёт имя контекста, которое выдаст сводный джоб дерева.

    Джоб ищется ПО ИМЕНИ во всех прогонах, а не по адресу файла: имя — предмет
    договора с защитой ветки, файл — его адрес, и адрес вправе меняться. Найтись
    он обязан ровно в одном месте: два джоба с именем обязательного контекста
    дали бы на голове две записи, и защита ветки зачла бы любую из них (187).
    """
    if not GATES_DIR.is_dir():
        raise NotRun(f"нет каталога прогонов: {GATES_DIR}")
    found: list[tuple[Path, Any]] = []
    for path in sorted(GATES_DIR.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        jobs = document.get("jobs") or {}
        if summary_job in jobs:
            found.append((path, jobs[summary_job] or {}))
    if not found:
        raise NotRun(
            f"ни один прогон в {GATES_DIR} не объявляет джоба «{summary_job}» — "
            "предмет сверки не найден (075)"
        )
    if len(found) > 1:
        where = ", ".join(path.name for path, _ in found)
        raise NotRun(
            f"джоб «{summary_job}» объявлен дважды ({where}): на голове окажутся две "
            "записи с именем обязательного контекста, и защита зачтёт любую (187)"
        )
    job = found[0][1]
    if "strategy" in job:
        raise NotRun(
            f"джоб «{summary_job}» матричный: матричные имена в список обязательных "
            "не попадают никогда"
        )
    # Имя контекста — это `name:` джоба, а если его нет, идентификатор джоба.
    return str(job.get("name") or summary_job)


def live_contexts(repo: str, branch: str, token: str) -> tuple[list[str], bool]:
    """Обязательные контексты ветки и признак «защита есть, но другой формы».

    ЧИТАЕТСЯ ТАМ, ГДЕ ЗАЩИТА ЖИВЁТ. Прежде здесь спрашивалась КЛАССИЧЕСКАЯ
    защита (`branches/<ветка>/protection/...`), а проект защищён НАБОРОМ ПРАВИЛ —
    и та же настройка по второму адресу выглядела отсутствующей. Первый же
    настоящий заход сверки объявил находку «у ветки нет обязательных контекстов»
    на здоровой настройке. Разбор и общее чтение — `scripts/protection.py` (090).

    Пустой набор правил на ЗАЩИЩЁННОЙ ветке — это «защита другой формы», а не
    «защиты нет»: у соседей по семье защита классическая, и выдать одно за другое
    значило бы отправить человека чинить не то
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md),
    [154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    try:
        rules = protection.live(repo, branch, token)
        if rules:
            return protection.contexts(rules), False
        return [], protection.guarded(repo, branch, token)
    except protection.NotRead as exc:
        raise NotRun(str(exc)) from exc


#: Способ слияния, объявленный решением 006. Остальные кнопки площадки лишние:
#: пока они включены, слить мимо очереди можно одним щелчком, и гейт узнает об
#: этом по истории, а не до неё.
MERGE_WAYS: Final = {
    "allow_merge_commit": "merge-коммит",
    "allow_rebase_merge": "перестановка",
}


def merge_ways(repo: str, token: str) -> list[str]:
    """Лишние способы слияния, оставшиеся включёнными у площадки."""
    try:
        answer = ghrest.request("GET", f"repos/{repo}", token) or {}
    except ghrest.TransportError as exc:
        raise NotRun(f"настройки репозитория не прочитаны: {exc}") from exc
    return [said for key, said in MERGE_WAYS.items() if answer.get(key)]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", default=paths.TRUNK)
    parser.add_argument("--summary-job", default="ci-complete")
    args = parser.parse_args(argv)

    try:
        expected = declared_context(args.summary_job)
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # ТОКЕН — ЛЮБОЙ, КАКОЙ ЕСТЬ У ЗАХОДА. Набор правил и настройки слияния
    # площадка отдаёт публично (замер 15.09.2026: оба адреса прочитаны вообще без
    # токена), поэтому прав владельца здесь больше не требуется — это и был весь
    # пробел «без токена владельца сверка не выполняется».
    token = os.environ.get("MERGE_QUEUE_TOKEN") or ghrest.token_from_env()

    try:
        actual, guarded_otherwise = live_contexts(args.repo, args.branch, token)
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not actual and guarded_otherwise:
        print(
            f"находка: ветка «{args.branch}» защищена, но не набором правил — эта сверка\n"
            "читает набор правил и о классической защите сказать ничего не может.\n"
            "Либо переведите защиту в набор правил, либо научите сверку второй форме:\n"
            "молча зеленеть на непрочитанном она не будет.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    if not actual:
        print(
            f"находка: у ветки «{args.branch}» нет обязательных контекстов.\n"
            f"Дерево выдаёт «{expected}» — поставьте его единственным обязательным.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    if actual != [expected]:
        print(
            f"находка: защита требует {actual}, а дерево выдаёт «{expected}».\n"
            "В списке обязано быть ровно одно имя, и это имя сводного джоба:\n"
            "перечисление матрицы ломается при добавлении версии, а имя, которого\n"
            "не выдаёт никто, оставляет изменение в вечном ожидании.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    print(f"совпадает: защита «{args.branch}» требует ровно «{expected}»")

    try:
        extra = merge_ways(args.repo, token)
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if extra:
        print(
            f"находка: площадка разрешает {', '.join(extra)} — а решение 006 говорит\n"
            "сливать уплотнением. Пока кнопки включены, слить мимо очереди можно одним\n"
            "щелчком, и гейт узнает об этом по истории общей ветки, когда чинить уже\n"
            "нечем. Снимите лишние способы в настройках репозитория.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    print("способ слияния ограничен уплотнением — как и решено в 006")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
