#!/usr/bin/env python3
"""Свой прогон перед толчком: красное чинится здесь, а не по логам площадки.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ СТРОКА В СВОДЕ. Правило без механизма — пожелание
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
Строка «прогоните проверки перед толчком» держится памятью окна, а память —
первое, что теряется к концу смены. Цена красного толчка названа прямо: цикл
площадки и доверие ревьюера; один проверенный толчок дешевле трёх пробных.

ЧТО ЗАПУСКАЕТСЯ, БЕРЁТСЯ ИЗ ДЕРЕВА, А НЕ ПЕРЕЧИСЛЯЕТСЯ ЗДЕСЬ ЗАНОВО. Команды
читаются из шагов `ci.yml`: второй список тех же команд разошёлся бы с первым
молча, и разошёлся бы незаметно — обе стороны выглядели бы правдоподобно
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Поэтому добавленный в прогон гейт появляется здесь сам, а не через полгода.

ГРАНИЦА НАЗВАНА, А НЕ СГЛАЖЕНА. Часть проверок без площадки невыполнима:
атрибуция считается по истории относительно базы, разметка изменения читается у
площадки, внешний взгляд идёт чужим прогоном. Объявить их «пройденными
локально» значило бы завести тихий запасной путь
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Невыполнимое здесь называется НЕВЫПОЛНЕННЫМ и печатается списком — это не
«пропущено», а «проверит площадка».

Исходы (правило 039): ``0`` всё зелено · ``2`` шаг не отработал ·
``3`` есть красное, толкать рано.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import agent_pr
import check_env
import paths
import report
import yaml

CI: Final = paths.WORKFLOWS / "ci.yml"

#: Команда шага прогона: строка, начинающаяся с зовомого инструмента. Читается
#: список РАЗРЕШЁННОГО (068): что не узнано, то не запускается, а называется.
RUNNABLE: Final = ("ruff ", "mypy ", "pytest", "python scripts/")
#: Подстановка площадки. Блок с ней локально не раскрывается, и запускать его
#: значит проверять не ту команду.
PLATFORM_MARK: Final = "${{"
#: Шаги, отложенные разбором с названной причиной. Заполняется КАЖДЫМ чтением
#: заново и печатается вместе с прочим невыполнимым: пропуск без имени
#: неотличим от «шага не было» (046).
#:
#: Прежде словарь копился между вызовами в одном процессе и требовал ручной
#: очистки в тесте — то есть механизм отвечал не про то дерево, которое у него
#: спросили, а про все, что он видел за жизнь процесса. Нашёл внешний взгляд
#: на #101.
UNRUNNABLE: Final[dict[str, str]] = {}
#: Шаги, которым нужна площадка: их команды сюда не берутся, а перечисляются
#: как невыполнимые. Ключ — начало команды, значение — почему.
NEEDS_PLATFORM: Final = {
    "python scripts/check_pr_meta.py": "разметку изменения читает площадка",
    "python scripts/debt.py": "долг читается из задач площадки",
    "python scripts/ci_complete.py": "опрашивает записи проверок на голове у площадки",
    # ФЕТЧ ДЕЛАЕТ СОСЕДНЯЯ СТРОКА ШАГА, А НЕ САМ СКРИПТ, и разница не
    # придирка: блок шага несёт `git fetch` с записью в
    # `refs/remotes/origin/<база>`, и запускать локально надо не скрипт, а
    # блок — то есть правку чужого дерева. Сам гейт поверхности прогоняется
    # руками (`python scripts/check_contract.py`) и базу берёт ту, что уже
    # есть. Прежняя запись приписывала фетч скрипту; нашёл внешний взгляд
    # на #123, а разбор самого шага — на #108.
    "python scripts/check_contract.py": "фетч базы делает соседняя строка шага, а не скрипт",
    # Локально канон берётся у `origin`, а он хранит написание клонировавшего:
    # регистр там не сверить, и половина гейта была бы вхолостую.
    "python scripts/check_own_name.py": "каноничное имя знает только площадка",
    # Имена правил читаются из выгрузки каталога по сети: локально её может не
    # быть, и падение говорило бы о канале, а не о ссылках.
    "python scripts/check_rule_links.py": "имена правил берутся из выгрузки каталога",
    # Нарисован ли артефакт на своей ветке, знает только площадка: в дереве его
    # нет и быть не должно — ровно в этом предмет правила 196.
    "python scripts/check_derived_refs.py": "нарисовано ли производное, знает площадка",
}


@dataclass(frozen=True, slots=True)
class Step:
    """Одна команда прогона: чем названа и что запускает."""

    name: str
    command: str


#: Проверки ПЕРЕД ТОЛЧКОМ, которых нет шагом прогона ни у кого. Это не второй
#: список тех же команд (022): в `ci.yml` их нет вовсе, потому что предмет у
#: них — ветка до открытия изменения. Приставка ветки и связь с задачей видны
#: на дереве целиком, а ловились до сих пор отказом `agent-pr` — то есть уже
#: после толчка. Замер 10.09.2026: три ветки подряд ушли без связи, и каждая
#: вернулась ни с чем: изменение не открылось, красного тоже не было.
BEFORE_PUSH: Final = (Step("ветка откроет изменение", "python scripts/agent_pr.py --dry-run"),)

#: Проверки прогона, у которых здесь нет команды вовсе: они живут не шагом с
#: командой, а действием площадки или чужим прогоном.
ELSEWHERE: Final = {
    "attribution": "считается по истории относительно базы изменения",
    "ci-complete": "опрашивает записи проверок на голове у площадки",
    "review": "идёт отдельным прогоном и чужим исполнителем",
    "automerge": "это само слияние, а не проверка перед ним",
}

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RED: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «всё зелено»."""


def steps(path: Path = CI) -> list[Step]:
    """Команды прогона, выполнимые без площадки, — в порядке объявления.

    Разбор идёт по ДЕРЕВУ, а не по строкам, и это не вкус. Команда шага живёт в
    блоке `run:` вместе с оболочечной обвязкой — `set -euo pipefail`,
    подготовкой базы, `git fetch`, — и строка, выдернутая из середины такого
    блока, запускается без неё. Итог выглядит как проверка, а проверяет другое:
    зелёное там, где площадка краснеет, и наоборот
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Замер — находка ревью по #94.

    Поэтому берётся ВЕСЬ блок шага, и берётся он целиком либо не берётся вовсе.
    """
    if not path.is_file():
        raise NotRun(f"нет {path}: список проверок взять неоткуда (075)")

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc
    if not isinstance(document, dict):
        raise NotRun(f"{path}: ожидалось отображение, пришло {type(document).__name__}")

    # Чтение начинается с чистого листа: отложенное относится к ЭТОМУ дереву.
    UNRUNNABLE.clear()
    found: list[Step] = []
    seen: set[str] = set()
    for job in (document.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            command = str((step or {}).get("run") or "").strip()
            name = str((step or {}).get("name") or "").strip()
            if not command or command in seen:
                continue
            if not any(line.strip().startswith(RUNNABLE) for line in command.splitlines()):
                continue
            # Площадка нужна блоку целиком, если её требует ХОТЯ БЫ одна его
            # строка: запустить остальное без неё значит проверить половину и
            # назвать это проверкой.
            if any(
                line.strip().startswith(prefix)
                for line in command.splitlines()
                for prefix in NEEDS_PLATFORM
            ):
                continue
            if PLATFORM_MARK in command:
                # Подстановка площадки локально не раскрывается: запустить блок
                # с ней значит проверить не ту команду. Названо, а не выкинуто
                # молча (046) — такие шаги перечисляет `report_gaps`.
                UNRUNNABLE[name or command] = "в команде подстановка площадки"
                continue
            seen.add(command)
            found.append(Step(name or command.splitlines()[0], command))

    if not found:
        raise NotRun(f"{path}: ни одной выполнимой команды не нашлось — предмет не найден (075)")
    return found


def environment() -> dict[str, str]:
    """Окружение прогона: инструменты берутся оттуда же, откуда запущен механизм.

    Иначе `pytest` и `ruff` придут из системного пути — то есть с ДРУГИМ
    интерпретатором, чем тот, на котором окно собиралось их гонять. Ровно этот
    разрыв и ловит `check_env.py`, и повторять его внутри своего же прогона
    значило бы проверять не то окружение (022).
    """
    where = str(Path(sys.executable).parent)
    room = dict(os.environ)
    room["PATH"] = where + os.pathsep + room.get("PATH", "")
    return room


def run(step: Step, root: Path) -> tuple[int, str]:
    """Запускает команду шага и отдаёт код с выводом."""
    done = subprocess.run(
        step.command,
        shell=True,
        # ОБОЛОЧКА ТА ЖЕ, ЧТО У ПЛОЩАДКИ. Умолчание `shell=True` — `/bin/sh`, а
        # площадка запускает шаги в bash: `set -o pipefail` в sh не понят, и
        # здоровый шаг краснел здесь с «Illegal option». Прогон, идущий другой
        # оболочкой, проверяет не то, что проверит площадка (022).
        executable="/bin/bash",
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment(),
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def report_gaps() -> None:
    """Называет то, что здесь проверить нечем, — списком, а не молчанием."""
    print("\nчего этот прогон не проверяет (проверит площадка):")
    for name, why in UNRUNNABLE.items():
        print(f"  {name} — {why}")
    for command, why in NEEDS_PLATFORM.items():
        print(f"  {command} — {why}")
    for check, why in ELSEWHERE.items():
        print(f"  {check} — {why}")


def branch_now(root: Path) -> str:
    """Имя текущей ветки — из дерева, а не из памяти зовущего."""
    said = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root or None,
    )
    if said.returncode != 0:
        raise NotRun(f"ветка не прочитана: {report.cut(said.stderr.strip())}")
    return said.stdout.strip()


def push_branch(root: Path) -> int:
    """Толкает текущую ветку — и зовётся ТОЛЬКО после зелёного вердикта.

    ВЕРДИКТ, КОТОРЫЙ ЧИТАЕТ ТОТ ЖЕ, КТО ДЕЙСТВУЕТ, — НЕ МЕХАНИЗМ, А
    НАПОМИНАНИЕ. Проверка перед толчком считала своё дело сделанным, напечатав
    «толкать рано»: держать толчок ей было нечем, а толкал тот же, кто её и
    запускал. Замер 17.09.2026: за смену ТРИ толчка из примерно пятнадцати ушли
    при красном вердикте — и каждый раз вердикт был напечатан на экран тем же
    заходом, что и толчок. Вреда не вышло только потому, что ветки были новыми,
    и каждый раз это ловил человек, а не механизм.

    ЗДЕСЬ ПРОВЕРКА И ДЕЙСТВИЕ СТАЛИ ОДНИМ ЗАХОДОМ. Красное просто не доходит до
    этой строки: толкать нечем, а не «не следует».

    ЧЕГО ЭТО НЕ ДЕЛАЕТ: не мешает толкнуть руками. Запретить `git push` проект
    не может и не должен — обход законен, когда он назван (154), а неназванный
    обход стоил ровно тех трёх раз.
    """
    branch = branch_now(root)
    # ПРИСТАВКА — ПЕРЕКЛЮЧАТЕЛЬ, И ПРОВЕРЯЕТСЯ ОНА, А НЕ ДВА ИМЕНИ. Первая
    # редакция отвергала `main` и `HEAD` — и пропускала всё остальное, включая
    # `claude/<окно>`, ветку, которую окну выдаёт площадка. Толчок туда
    # изменения НЕ ОТКРОЕТ: приставку читает `agent-pr`, — то есть работа
    # уезжала в никуда, а заход рапортовал успех. Сообщение при этом ссылалось
    # на 003 и проверяло не то, о чём 003 говорит. Нашёл внешний взгляд на #433.
    #
    # СПИСОК ПРИСТАВОК БЕРЁТСЯ У ТОГО, КТО ПО НЕМУ И РЕШАЕТ (`agent_pr`), а не
    # пишется здесь второй копией: разъехавшись, они дали бы худший из отказов —
    # толчок прошёл, изменение не открылось, красного нет нигде (022, 090).
    if not branch.startswith(agent_pr.PREFIXES):
        print(
            f"толчок не сделан: ветка «{branch}» без приставки "
            f"{' или '.join(agent_pr.PREFIXES)} — изменения по ней не откроется (003)",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    said = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root or None,
    )
    print(said.stdout.rstrip() or said.stderr.rstrip())
    if said.returncode != 0:
        print(f"толчок не прошёл: {report.cut(said.stderr.strip())}", file=sys.stderr)
        return EXIT_BROKEN
    print(f"толкнуто: {branch}")
    return EXIT_OK


def environment_gap(root: Path) -> list[str]:
    """Чем окружение окна расходится с тем, что ставит прогон, — или пусто.

    ШОВ ЗДЕСЬ ЗАВЕДЁН НАРОЧНО, наравне с `steps` и `run`: прогоны вердикта
    подменяют соседей и судят ОТНОШЕНИЕ «красное → не толкаем», а не состав
    чужой машины. Без шва три таких прогона стали бы зависеть от того, стоит ли
    у запустившего `mypy`, — и краснели бы на матричной ячейке площадки, где его
    нет
    ([150](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/150-a-test-asks-the-mechanism-not-its-condition.md)).

    СВЕРКА ИДЁТ ТОЛЬКО ДЛЯ СВОЕГО ДЕРЕВА. Она отвечает на вопрос «предскажет ли
    зелёное площадку», а площадка есть у ОДНОГО дерева — того, в котором лежит
    сама предполётная. На синтетическом корне сверка сравнивала бы установленное
    у запустившего с объявлениями чужого дерева
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

    СВОЁ ДЕРЕВО УЗНАЁТСЯ ЧЕРЕЗ ЯКОРЬ, а не ходом вверх: `.parent.parent` краснел
    бы у гейта поиска вверх по дереву — и краснел бы ЛОЖНО, потому что предмет
    того гейта розыск настройки, а тут вычисляется собственный корень. Обходить
    чужой гейт формулировкой нельзя, поэтому ход вверх снят вовсе (115, 051).
    """
    here = Path(__file__).resolve().parent
    if not any((root / where).resolve() == here for where in paths.SOURCES):
        # МОЛЧАТЬ ОБ ЭТОМ НЕЛЬЗЯ: пропущенная сверка и сошедшаяся снаружи
        # одинаковы, и зелёное ниже говорит тогда меньше, чем кажется (045).
        print(
            f"окружение НЕ сверено: корень {root} — не то дерево, в котором лежит"
            " предполётная, и объявления в нём про чужую площадку",
            file=sys.stderr,
        )
        return []
    try:
        return check_env.survey(root).problems
    except (check_env.NotRun, OSError, ValueError) as exc:
        # Дерево без строк установки бывает: так выглядит синтетический корень.
        print(f"окружение НЕ сверено: {exc}", file=sys.stderr)
        print(
            "  зелёное ниже говорит только о дереве, но не о том, что площадка скажет то же.",
            file=sys.stderr,
        )
        return []


def main(argv: list[str] | None = None) -> int:
    """Точка входа: прогоняет проверки дерева и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--list", action="store_true", help="только показать, что будет запущено")
    parser.add_argument(
        "--push",
        action="store_true",
        help="толкнуть текущую ветку, ЕСЛИ зелено: проверка и действие одним заходом",
    )
    args = parser.parse_args(argv)

    # ОКРУЖЕНИЕ СВЕРЯЕТСЯ ДО ВСЕГО, И ЭТО НЕ ФОРМАЛЬНОСТЬ. Зелёная предполётная
    # обещает ровно одно: «площадка скажет то же». Обещание держится, пока
    # инструменты окна тех же версий, что ставит прогон, — иначе проверено было
    # ДРУГОЕ, и зелёное здесь ничего не предсказывает
    # ([073](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/073-tool-version-from-one-source-with-an-upper-bound.md)).
    #
    # ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ШАГ И ПОЯВИЛСЯ: окно гоняло mypy 2.3.1
    # при объявленных `>=1.11,<2`, предполётная давала «зелено: 18», а площадка
    # краснела на шаге типов. Сверка окружения лежала рядом (`check_env.py`) и
    # не звалась ничем — то есть существовала, а работала по памяти (002).
    if not args.list:
        gap = environment_gap(args.root)
        if gap:
            print("окружение окна расходится с тем, что ставит прогон:")
            for line in gap:
                print(f"  {line}")
            print(
                "\nпредполётная НЕ ЗАПУЩЕНА: её зелёное предсказывало бы площадку"
                " только на тех же версиях."
                "\nПоставьте объявленные границы — `python scripts/check_env.py`"
                " печатает команду — и повторите."
            )
            return EXIT_BROKEN

    try:
        # Проверки ветки идут ПЕРВЫМИ: их предмет — то, откроется ли изменение
        # вообще, и красное здесь делает остальное бессмысленным.
        found = [*BEFORE_PUSH, *steps(args.root / CI)]
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if args.list:
        for step in found:
            print(f"{step.name}: {step.command}")
        report_gaps()
        return EXIT_OK

    red: list[Step] = []
    for step in found:
        code, output = run(step, args.root)
        print(f"{'✓' if code == 0 else '✗'} {step.name}: {step.command}")
        if code != 0:
            red.append(step)
            print(output.rstrip())

    report_gaps()
    if red:
        print(f"\nкрасных проверок: {len(red)} — толкать рано, чинится здесь:")
        for step in red:
            print(f"  {step.name}: {step.command}")
        return EXIT_RED
    print(f"\nзелено: {len(found)} проверок дерева прошли")
    if args.push:
        return push_branch(args.root)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
