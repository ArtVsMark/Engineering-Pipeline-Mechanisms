#!/usr/bin/env python3
"""Новое приезжает со своим прогоном: добавленное имя названо набором.

ПОЧЕМУ НЕ ПРОЦЕНТ ПОКРЫТИЯ. Замер 12.09.2026 по одиннадцати настоящим дефектам
смены: покрытие поймало бы **два**, и оба одного класса — «новая функция, у
которой тестов нет ВООБЩЕ». Остальные девять — верно работающий покрытый код с
неверной премисой, и никакое число процентов их не видит.

Само число к тому же врёт: гейты этого проекта испытываются ОТДЕЛЬНЫМ
процессом, а счётчик покрытия подпроцессы не считает. Четыре модуля показывали
ноль при семнадцати вызовах из набора. Строить порог на таком числе значило бы
строить на непроверенном замере
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

ПРЕДМЕТ — ТОЛЬКО ДОБАВЛЕННОЕ ЭТИМ ИЗМЕНЕНИЕМ. В дереве 75 имён из 327 не
названы ни одним тестом; судить их этим гейтом значило бы краснеть на чужой
работе и учить себя обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Долг называется числом в шаге `debt`, а не красным на каждом изменении.

ДВА СПОСОБА БЫТЬ НАЗВАННЫМ, И ОБА ЗАКОННЫ. Набор либо зовёт имя напрямую, либо
запускает модуль отдельным процессом — так проверяются гейты, и внутренних имён
такой тест не знает. Поэтому `main` засчитывается упоминанием ФАЙЛА модуля:
требовать от него другого значило бы требовать переписать способ проверки
гейтов ради формы этой проверки.

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import paths

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Где живут механизмы и где живёт набор. Пара, а не одна папка: предмет гейта
#: — отношение между ними.
SOURCES: Final = "scripts/"
TESTS: Final = "tests"

#: Имя точки входа. Засчитывается упоминанием файла модуля: тест гейта зовёт
#: его отдельным процессом и внутренних имён не видит.
ENTRY: Final = "main"


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «нового нет»."""


def base_ref() -> str:
    """Общая ветка, относительно которой смотрится изменение."""
    return f"origin/{os.environ.get('GITHUB_BASE_REF') or paths.TRUNK}"


def _git(*args: str) -> str:
    """Запуск git; отказ — третий исход, а не пустой ответ."""
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def touched(base: str) -> list[str]:
    """Модули механизмов, тронутые изменением.

    Список путей читается по NUL: без него git экранирует имена с не-ASCII, и
    такой путь молча выпадает из отбора
    ([165](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/165-git-file-list-needs-nul.md)).
    """
    spot = _git("merge-base", base, "HEAD").strip()
    if not spot:
        raise NotRun(f"общая точка с {base} не найдена")
    fields = [
        one for one in _git("diff", "--name-status", "-z", f"{spot}...HEAD").split("\0") if one
    ]
    found: list[str] = []
    while fields:
        state = fields.pop(0)[:1]
        if not fields:
            break
        path = fields.pop(0)
        if state == "R" and fields:
            path = fields.pop(0)
        if state != "D" and path.startswith(SOURCES) and path.endswith(".py"):
            found.append(path)
    return found


def names_in(source: str) -> set[str]:
    """Имена верхнего уровня модуля: функции и классы, кроме внутренних.

    Внутренние (`_имя`) сюда не входят намеренно: их зовут соседние строки того
    же модуля, и требовать им отдельного прогона значило бы проверять форму, а
    не работу.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise NotRun(f"модуль не разобрался: {exc}") from exc
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not node.name.startswith("_")
    }


def at(ref: str, path: str) -> str:
    """Содержимое файла на названной стороне; отсутствующий — пустая строка."""
    try:
        return _git("show", f"{ref}:{path}")
    except NotRun:
        # Файла на базе нет — модуль новый целиком, и это не отказ.
        return ""


def added_names(base: str, path: str) -> set[str]:
    """Имена, которых на базе не было, а в голове есть."""
    return names_in(at("HEAD", path)) - names_in(at(base, path))


def told_by_tests(name: str, module: str, tests: str) -> bool:
    """ЗОВЁТ ли набор это имя — или запускает модуль процессом.

    УПОМИНАНИЕ НЕ ПРОГОН, и это оказалось главной слабостью первой редакции.
    Она искала имя отдельным словом где угодно в наборе — и короткие, обычные
    имена засчитывались сами собой: `at` и `touched` встречаются в чужой прозе
    и в чужих данных, и обе функции гейт объявил проверенными, не имея по ним
    ни одного прогона. Нашёл внешний взгляд на #225.

    Теперь предмет — ВЫЗОВ: `имя(` или `.имя(`. Класс тоже вызывается при
    создании, а константы этот гейт не судит вовсе. Имя, лишь названное в
    докстроке, прогоном не считается — иначе достаточно было бы про него
    написать
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

    ВЫЗОВ БЫВАЕТ НЕ СКОБКАМИ, И СОСЕД НАЗВАН. Функция, переданная как значение
    — обработчик, ключ сортировки, декоратор, подмена в стенде, — вызывается
    НЕ здесь, а тем, кому её отдали, и скобок рядом с её именем нет. Сужение до
    `имя(` объявляло такое непрогнанным: ложная находка, которая учит обходить
    гейт
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Нашёл внешний взгляд на #227.

    ИМЯ ОТДАЮТ — ЗНАЧИТ ОНО СТОИТ НА МЕСТЕ ЗНАЧЕНИЯ: после `=`, `,`, `(` или
    `[` и перед `)`, `,`, `]` либо концом строки. Знак идёт ПЕРЕД именем, а не
    после: перед — «имя отдают», после — «имени присваивают», и это
    противоположные вещи (нашёл внешний взгляд на #247). Одиночный `=` при этом
    отличается от хвоста сравнения: `x == имя` передачей не является (нашёл
    внешний взгляд на #249).

    Формы перечислены СПИСКОМ, а не выведены, и каждая держится своим случаем
    в наборе
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    Упоминание в прозе не проходит: у имени обязан быть знак, которым его зовут
    или отдают.
    """
    bare = re.escape(name)
    # ЗВАТЬ — ЭТО СКОБКА СРАЗУ ЗА ИМЕНЕМ.
    if re.search(rf"(?<![\w.]){bare}\s*\(|\.{bare}\s*\(", tests):
        return True
    # ОТДАВАТЬ — ЭТО ИМЯ НА МЕСТЕ ЗНАЧЕНИЯ, то есть ПОСЛЕ `=`, `,`, `(` или
    # `[`: `key=имя`, `setattr(x, "y", имя)`, `[имя]`.
    #
    # ПОРЯДОК ЗНАКА РЕШАЕТ ВСЁ, и на этом я ошибся. Первая редакция искала знак
    # ПОСЛЕ имени (`имя=`) и потому засчитывала `имя = 5` — присваивание,
    # которое прогоном не является вовсе. Нашёл внешний взгляд на #247. Знак
    # перед именем говорит «имя отдают», знак после — «имени присваивают», и
    # это противоположные вещи
    # ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    # РАВНО БЫВАЕТ ХВОСТОМ ЧУЖОГО ЗНАКА, и это четвёртая редакция признака.
    # Отвергаются два семейства сразу: сравнения (`x == имя`, `!=`, `>=`, `<=`)
    # и составные присваивания (`x += имя`, `*=`, `>>=`, `//=`). В обоих имя
    # стоит после `=`, но передачей это не является: сравнение его не зовёт, а
    # арифметика берёт его ЗНАЧЕНИЕ, не вызывая.
    #
    # Правило простое и полное: перед `=` не должно стоять НИ ОДНОГО знака
    # операции. Исключать их поштучно («сначала сравнения, потом составные»)
    # значит чинить по одному найденному случаю — так этот признак уже дважды и
    # чинился. Нашли внешние взгляды на #249 и #251.
    handed = r"(?:(?<![=!<>+\-*/%&|^@~])=|[,(\[])"
    if re.search(rf"{handed}\s*{bare}\s*(?=[),\]]|$)", tests, re.MULTILINE):
        return True
    # ДЕКОРАТОР — тоже передача, только записанная иначе.
    if re.search(rf"@\s*{bare}\b", tests):
        return True
    return name == ENTRY and Path(module).name in tests


def tests_text(root: Path = Path(TESTS)) -> str:
    """Весь набор одной строкой: предмет — «названо хоть где-то»."""
    found = sorted(root.glob("*.py"))
    if not found:
        raise NotRun(f"набора нет: {root} — предмет проверки не найден (075)")
    return "\n".join(one.read_text(encoding="utf-8") for one in found)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает находки и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="", help="общая ветка; по умолчанию — origin/main")
    args = parser.parse_args(argv)

    try:
        base = args.base or base_ref()
        modules = touched(base)
        if not modules:
            print("изменение не трогает механизмов — проверять нечего")
            return EXIT_OK
        tests = tests_text()
        naked: list[str] = []
        for path in modules:
            for name in sorted(added_names(base, path)):
                if not told_by_tests(name, path, tests):
                    naked.append(f"{path}:{name}")
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if naked:
        print(f"добавленное, которого не зовёт ни один прогон ({len(naked)}):")
        for one in naked:
            print(f"  {one}")
        print(
            "\nНовое приезжает со своим прогоном. Дважды за смену дефект жил ровно\n"
            "в таком имени: путь отказа у состояния приёмки и разбор миганий на\n"
            "изменении — оба нашёл внешний взгляд, а не набор."
        )
        return EXIT_FOUND
    print(f"добавленные имена названы набором; модулей тронуто {len(modules)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
