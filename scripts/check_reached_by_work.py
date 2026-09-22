#!/usr/bin/env python3
"""Добавленное зовёт РАБОЧИЙ путь, а не только прогон набора.

ПАРА К `check_new_is_tested`, И ИМЕННО ЕЁ ОТСУТСТВИЕ СТОИЛО ШЕСТИ СЛУЧАЕВ.
Сосед требует, чтобы добавленное имя звал хотя бы один прогон набора. Обратного
— чтобы его звал хотя бы один рабочий путь — не было, и механизм, до которого
не доходит управление, выглядел здоровее непроверенного: у него ЕСТЬ зелёный
прогон. Дифф при этом показывает исправный код: обрыв лежит не в нём, а между
ним и зовущим.

ЗАМЕР 21–22.09.2026, РАДИ КОТОРОГО ГЕЙТ ЗАВЕДЁН. Шесть случаев за двое суток:
`SERVICE_STEPS` объявлен и не вызывался (#607); `whose` сводил счёт и не
доходил до отчёта (#611); предупреждение о тишине взгляда вызывалось только при
`--push` (#616); приёмка к нему звала функцию напрямую и не видела, зовут ли её
(#618); две функции осиротели от постройки соседа, делающего то же и больше, —
одна в `runs_series`, другая в `changerefs` (обе найдены замером, сняты в #628
и следом). Четыре из шести нашёл
внешний взгляд, два — нарочный замер, НОЛЬ — чтение или зелёный набор.
Предложение каталогу: `.rules/proposals.json`, слаг
`a-mechanism-is-alive-only-if-a-working-path-reaches-it`.

ПРЕДМЕТ — ТОЛЬКО ДОБАВЛЕННОЕ ЭТИМ ИЗМЕНЕНИЕМ, и по той же причине, что у
соседа: в дереве есть стоящие сироты, и краснеть на чужой работе значит учить
себя обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

ЗНАЧЕНИЯ ЭТОТ ГЕЙТ НЕ СУДИТ, И ЭТО ЗАМЕР, А НЕ ОСТОРОЖНОСТЬ. Предикат
«объявлено и рабочим кодом не достижимо» по 66 модулям дал семь имён: два
вызываемых — настоящие сироты, и ПЯТЬ значений — законные. Это закрытые
росписи, заведённые ДЛЯ набора (`findings.CHECKED`, `unlooked.STATES`,
`paths.ALL`, `kinds.DOCUMENT` — их полноту приёмка и проверяет), и предел
`findings.SAID_LIMIT`, адресованный человеку прямой оговоркой в докстроке.
Судить их значило бы краснеть на пяти законных ради двух находок, а
разрешительный список для них вышел бы длиннее предмета
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
Сосед `check_new_is_tested` сузился так же и по своему поводу — «константы этот
гейт не судит вовсе».

РАЗБОР ДОБАВЛЕННОГО БЕРЁТСЯ У СОСЕДА, А НЕ ПИШЕТСЯ ЗАНОВО. «Что считается
добавленным именем» — один вопрос, и два ответа на него разошлись бы молча:
переехавший файл, переименование, формы вызова
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено:

* **достижимость на ВСЕХ путях.** Имя, которое зовут из одной ветки из двух,
  гейт считает достигнутым — а случай #616 был именно такой. Здесь предмет
  грубее: «зовут ли вообще». Половину, которую машина не берёт, держит навык
  проверки гейтов откатом
  ([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md));
* **сироту, возникшую от постройки СОСЕДА.** Обе снятые сироты осиротели не тем
  изменением, которое их добавило, — их добавленными именами они давно не
  являлись. Такую находит замер по дереву, а не гейт изменения.

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Final

import check_new_is_tested as neighbour
import paths

#: Отказ гейта. Имя объявлено СВОИМ, а не взято у соседа: исходы у них разные
#: по смыслу, и общая константа связала бы два договора в один (022).
EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Где живёт рабочий код и где прогоны площадки — АДРЕСА БЕРУТСЯ У ЯКОРЯ, а не
#: пишутся здесь вторым написанием. Набор в рабочий код не входит по построению:
#: в этом весь предмет — прогон набора достижимостью НЕ является.
#: Гейт второго якоря поймал здесь ровно это (022, 090).
#:
#: ИСТОЧНИКОВ ДВА, А НЕ ОДИН, И ЗДЕСЬ СТОЯЛ `SCRIPTS`. Судится всё, что отбирает
#: `neighbour.touched`, а он идёт по `paths.SOURCES` — скрипты И пакет
#: транспорта. Достижимость же считалась по одним скриптам: имя, добавленное в
#: `packages/transport` и вызванное там же, объявлялось сиротой ЛОЖНО. Замер
#: пробой 22.09.2026: две добавленные в транспорт функции, одна зовёт другую, —
#: гейт назвал сиротами ОБЕИХ. Гейт, краснеющий на исправном, учит себя обходить
#: ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
#: Нашёл внешний взгляд на #623; тот же перенос транспорта наружу однажды уже
#: ослепил соседний гейт, и `paths.SOURCES` заведён ровно поэтому (090).
WORK: Final = paths.SOURCES
RUNS: Final = paths.WORKFLOWS

#: Имя точки входа. Её зовёт площадка строкой запуска модуля, и искать её
#: вызов среди питона бессмысленно — тем же послаблением, что у соседа.
ENTRY: Final = "main"

NotRun = neighbour.NotRun


def mentioned(roots: tuple[Path, ...] = WORK) -> Counter[str]:
    """Сколько раз рабочий код ОБРАЩАЕТСЯ к каждому имени. Объявление не в счёт.

    РАЗБОР ЗДЕСЬ ПО ДЕРЕВУ КОДА, А НЕ ПО ТЕКСТУ, И ЭТО НЕ ВТОРОЕ ПОНИМАНИЕ
    СОСЕДСКОГО. Вопросы разные по существу: сосед спрашивает у НАБОРА, «прогнали
    ли имя», и разбирает текст, потому что в тесте имя ходит и в прозе, и в
    данных — там нужен признак «зовут или отдают». Здесь вопрос структурный —
    «доходит ли до имени управление», — и дерево кода отвечает на него точно:
    обращение есть узел, а объявление узлом обращения не является.

    ПЕРВАЯ РЕДАКЦИЯ БРАЛА ТЕКСТ И ИСКЛЮЧАЛА СВОЙ МОДУЛЬ ЦЕЛИКОМ — иначе
    `def имя(` засчитывалось за вызов. Проверка на настоящей истории дала ТРИ
    находки, и все три были ложными: `say_the_look_is_silenced`, `carriers` и
    `bare_lines` зовутся из своего же модуля, а тот начинается точкой входа.
    Гейт, краснеющий на исправном, учит себя обходить
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    seen: Counter[str] = Counter()
    for path in sorted(one for root in roots for one in root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise NotRun(f"{path} не разбирается: {exc}") from exc
        for node in ast.walk(tree):
            # ПРИСВАИВАНИЕ ОБРАЩЕНИЕМ НЕ СЧИТАЕТСЯ. У функции объявление узлом
            # обращения не является вовсе, а у значения — является: `ИМЯ = …`
            # кладёт `ast.Name` с `ctx=Store`, и без этой развилки всякое
            # объявленное значение читалось бы достигнутым САМИМ СОБОЙ. Сегодня
            # значения не судятся, и потому последствий у этого нет; докстрока
            # же обещала «объявление не в счёт» — обещание было шире кода.
            # Нашёл откат, оставшийся зелёным (навык `build-a-gate`, шаг 6).
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
                seen[node.id] += 1
            elif isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Store):
                seen[node.attr] += 1
    return seen


def runs_text(root: Path = RUNS) -> str:
    """Все прогоны площадки одной строкой; их нет — законное состояние."""
    if not root.is_dir():
        return ""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.glob("*.y*ml")))


def reached(name: str, work: Counter[str], runs: str) -> bool:
    """Доходит ли до имени рабочий путь."""
    if name == ENTRY:
        return True
    if work[name]:
        return True
    # ИМЯ, НАЗВАННОЕ ШАГОМ ПЛОЩАДКИ, ДОСТИГНУТО. Прогон зовёт модуль строкой
    # запуска, и питона рядом с этим именем нет вовсе (045).
    return re.search(rf"\b{re.escape(name)}\b", runs) is not None


def findings(base: str) -> list[str]:
    """Добавленные имена, до которых не доходит ни один рабочий путь."""
    naked: list[str] = []
    runs, work = runs_text(), mentioned()
    for path, was in neighbour.touched(base):
        for name in sorted(neighbour.added_names(base, path, was)):
            if not reached(name, work, runs):
                naked.append(f"{path}:{name}")
    return naked


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает находки и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="", help="общая ветка; по умолчанию — origin/main")
    args = parser.parse_args(argv)

    try:
        base = args.base or neighbour.base_ref()
        modules = neighbour.touched(base)
        if not modules:
            print("изменение не трогает механизмов — проверять нечего")
            return EXIT_OK
        naked = findings(base)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if naked:
        print(f"добавленное, до чего не доходит ни один рабочий путь ({len(naked)}):")
        for one in naked:
            print(f"  {one}")
        print(
            "\nЗелёный прогон не доказывает, что механизм зовут: приёмка зовёт его\n"
            "напрямую и остаётся зелёной, когда до него не доходит никто. Позовите\n"
            "добавленное из рабочего пути — или снимите его, если оно не нужно."
        )
        return EXIT_FOUND
    print(f"добавленное зовёт рабочий путь; модулей тронуто {len(modules)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
