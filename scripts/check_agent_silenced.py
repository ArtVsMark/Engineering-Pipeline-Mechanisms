#!/usr/bin/env python3
"""Предупреждение: правка файла прогона глушит агента НА ЭТОМ ЖЕ изменении.

ПЛОЩАДКА ОТКАЗЫВАЕТ ДЕЙСТВИЮ АГЕНТА, КОГДА ФАЙЛ ПРОГОНА РАСХОДИТСЯ С ОБЩЕЙ
ВЕТКОЙ. Её собственные слова в аннотации джоба: «Workflow validation failed. The
workflow file must exist and have identical content to the version on the
repository's default branch». Шаг при этом объявлен `continue-on-error`, поэтому
он ЗЕЛЁНЫЙ, джоб зелёный, а ответа нет вовсе — изменение уезжает в общую ветку
непросмотренным, и узнаётся это уже после слияния
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЗАМЕР 21–22.09.2026 ПО СТА СЛИТЫМ ИЗМЕНЕНИЯМ: такой файл трогали ДВАЖДЫ, и оба
раза взгляд на голове изменения промолчал. У #614 ответа не было совсем; у #563
ответ пришёл — но от ПОЗДНЕГО взгляда по общей ветке, через семь минут после
слияния (`late-look (563)`, прогон 35514042297), где файл уже совпадал.
Исключений в замере нет.

ФАЙЛЫ БЕРУТСЯ ИЗ ДЕРЕВА, А НЕ ПЕРЕЧИСЛЯЮТСЯ ЗДЕСЬ. Действие объявляют ТРИ
прогона — взгляд, ответ по оклику и разбор пунктов задачи, — и список именами
устарел бы молча при четвёртом
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md),
[206](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/206-a-form-the-gate-cannot-see-is-a-bypass.md)).

ЭТО ПРЕДУПРЕЖДЕНИЕ, А НЕ ЗАПРЕТ, и это выбор. Правка такого файла законна —
иначе их нельзя было бы менять вовсе. Отказ здесь запрещал бы работу, а не
ошибку; предупреждение называет цену и оставляет решение автору
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md),
[154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

ЧЕГО ЭТОТ ШАГ НЕ ДЕЛАЕТ. Он не различает причину тишины ПОСЛЕ факта — это
предмет реестра #89, и там решено называть видимое, а не выбирать между
причинами; прежняя попытка выбрать была отменена внешним взглядом на #180.
Здесь вопрос другой и задаётся РАНЬШЕ: не «почему промолчал», а «сейчас
промолчит».

Исходы (правило 039): ``0`` таких файлов изменение не трогает · ``1`` трогает,
и агент промолчит · ``2`` заход не отработал.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Final

import report

#: Чем объявлено действие агента в файле прогона. Признак — строка вызова, а не
#: имя файла: имя меняет автор, а вызов обязан остаться, иначе агента нет.
ACTION: Final = "anthropics/claude-code-action"

#: Где живут прогоны. Глубже площадка их не ищет, и здесь тоже незачем.
WORKFLOWS: Final = ".github/workflows/"

EXIT_OK: Final = 0
EXIT_SILENCED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не «чисто» (039, 045)."""


#: Исход `git grep`, означающий «совпадений нет». Он НЕ отказ, и разводить их
#: обязательно: пустой ответ — законный вход, а молчание git о беде — нет
#: ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
#: Заведено находкой собственного прогона: без этого дерево без носителей и
#: дерево без git давали одну ошибку.
GREP_FOUND_NOTHING: Final = 1


def _git(root: Path, *args: str, empty: int | None = None) -> str:
    """Спрашивает git и отдаёт вывод; отказ — третий исход, а не пустота.

    `empty` называет исход, который у ЭТОЙ команды значит «ничего не нашлось»:
    у `grep` это единица, у прочих такого исхода нет вовсе.
    """
    # ИМЯ ПУТИ СПРАШИВАЕТСЯ НЕЭКРАНИРОВАННЫМ. По умолчанию git отдаёт не-ASCII
    # путь восьмеричными последовательностями — `"\321\201\320\276…"`, — и
    # предупреждение назвало бы файл так, что искать его пришлось бы вслепую
    # (154). Нашёл собственный прогон на имени с кириллицей.
    # ОТКАЗ ЗАПУСКА — ТОТ ЖЕ ТРЕТИЙ ИСХОД, А НЕ ОБВАЛ. Несуществующий каталог
    # роняет `subprocess` до всякого кода возврата, и без этого заход печатал
    # трассировку вместо объявленного исхода (039). Нашёл собственный прогон.
    try:
        said = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=root or None,
        )
    except OSError as exc:
        raise NotRun(f"git не запустился: {report.cut(str(exc))}") from exc
    if empty is not None and said.returncode == empty and not said.stderr.strip():
        return ""
    if said.returncode != 0:
        raise NotRun(
            f"git {' '.join(args)} — {report.cut(said.stderr.strip()) or f'код {said.returncode}'}"
        )
    return said.stdout


def carriers(root: Path, base: str) -> set[str]:
    """Файлы прогонов, объявляющие действие агента, — по ОБЩЕЙ ветке.

    СПРАШИВАЕТСЯ БАЗА, А НЕ РАБОЧЕЕ ДЕРЕВО. Предмет проверки — расхождение с
    общей веткой, и состав носителей берётся оттуда же: файл, заведённый самим
    изменением, на общей ветке ещё не объявлен, и площадке сравнивать его не с
    чем (049).
    """
    said = _git(root, "grep", "-l", ACTION, base, "--", WORKFLOWS, empty=GREP_FOUND_NOTHING)
    # РАЗБОР ПОСТРОЧНЫЙ, А НЕ ПО ПРОБЕЛАМ: `git grep -l` кладёт один путь на
    # строку, и путь с пробелом развалился бы надвое.
    return {line.split(":", 1)[1] for line in said.splitlines() if ":" in line}


def touched(root: Path, base: str) -> set[str]:
    """Файлы, которые изменение правит относительно общей ветки."""
    # СПИСОК ПУТЕЙ ЧИТАЕТСЯ ПО NUL, А НЕ ПО СТРОКАМ. Путь с переводом строки в
    # имени законен, и построчный разбор развалил бы его надвое; этого требует
    # `tests/test_source_hygiene.py` от всякого читателя списков git — и
    # поймал он здесь, а не чтение.
    said = _git(root, "diff", "-z", "--name-only", f"{base}...HEAD")
    return {one for one in said.split("\0") if one}


def look(root: Path, base: str) -> tuple[int, str]:
    """Вердикт: исход и что сказать автору."""
    несущие = carriers(root, base)
    if not несущие:
        raise NotRun(
            f"в «{base}» нет ни одного прогона с «{ACTION}» — предмета у проверки нет, "
            "и молчать об этом нельзя (075)"
        )
    задеты = sorted(несущие & touched(root, base))
    if not задеты:
        return EXIT_OK, "прогоны с действием агента не тронуты — взгляд на изменении будет"
    имена = ", ".join(f"«{one}»" for one in задеты)
    return EXIT_SILENCED, (
        f"изменение правит {имена} — площадка ОТКАЖЕТ действию агента на этой голове "
        "(файл прогона обязан совпадать с общей веткой), и внешнего взгляда на этой "
        "работе НЕ БУДЕТ. Шаг при этом зелёный, тишина не покраснеет нигде. "
        "Это цена правки, а не ошибка: если взгляд нужен, его зовут поздним заходом "
        "по общей ветке после слияния (реестр слитого без взгляда)"
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает вердикт и отдаёт исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="общая ветка")
    parser.add_argument("--root", default=".", help="корень дерева")
    args = parser.parse_args(argv)
    try:
        code, said = look(Path(args.root), args.base)
    except NotRun as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print(said)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
