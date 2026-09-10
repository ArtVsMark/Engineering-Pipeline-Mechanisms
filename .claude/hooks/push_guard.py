#!/usr/bin/env python3
"""Толчок не туда отвергается ДО вызова git, а не ловится после.

Держит два критических запрета свода: «НЕ писать в main напрямую» и «НЕ пушить
в ветку чужого изменения — её ведёт своё окно» (012, 131).

ПОЧЕМУ ХУК, А НЕ ГЕЙТ. Конвейер видит АРТЕФАКТ, а не действие: к запуску
прогона толчок уже состоялся, и ветка уже сдвинута. Отвергать надо до вызова
git — единственное место, где это возможно, стоит перед инструментом.

ПРИЗНАК ВЫБРАН ДОСТУПНЫЙ, А НЕ ЖЕЛАЕМЫЙ. «Чужая ветка» машине недоступна: чья
она, знает человек. Зато доступен признак, которым пользуются все три соседа:
имя ветки в команде не совпадает с текущей головой. Промах пальцем,
скопированная из передачи строка, старое имя из прошлой смены — все три дают
одно наблюдаемое: содержимое уезжает не туда, куда смотрит окно.

ИНЦИДЕНТ, ИЗ-ЗА КОТОРОГО СТОРОЖ ЗАВЕДЁН, СВОЙ. 10.09.2026 окно, стоя на ветке
`agent/items-sweep`, толкнуло в `agent/marking-moves-out-of-the-queue`. Обе
свои, обе законные — а следствие такое же, как у чужой: конвейер открыл ВТОРОЕ
изменение на ту же работу (#116), его пришлось закрывать руками, и ветка
осталась висеть, потому что прав удалить её у окна нет.

ЧТО РАЗРЕШЕНО. Толчок без имени ветки (`git push`) и толчок текущей ветки под
её собственным именем. Всё остальное с явным именем отвергается — включая
`HEAD:<другая-ветка>`: «своя голова под чужим именем» и есть форма инцидента
#116, а не исключение из него. Общая ветка отвергается всегда: писать в неё
напрямую нельзя ни из какой головы.

Законный случай «работа должна уехать под другим именем» решается переходом на
эту ветку, а не толчком мимо головы: тогда окно и конвейер смотрят на одно.

ТЕЛО ДОКУМЕНТА НА ВХОДЕ — ДАННЫЕ, А НЕ КОМАНДА. `cat > файл <<'EOF' … EOF`
пишет файл, и `git push` внутри него — текст. Сторож смотрит на действие:
разбор идёт по словам команды, а не поиском подстроки.

Приём взят у соседей (162), файл — нет: у них запреты свои и собраны под их
конвейеры.

Вход: JSON события PreToolUse на stdin. Выход: 0 — пропустить, 2 — отвергнуть
с причиной в stderr.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from typing import Final

#: Ветка, в которую писать напрямую нельзя ни из какой головы (131).
SHARED: Final = "main"
#: Ключи `git push`, за которыми идёт значение, а не имя ветки.
WITH_VALUE: Final = frozenset({"--repo", "-o", "--push-option", "--exec", "--receive-pack"})
#: Глобальные ключи самого git со значением: `git -C путь push`. Отделять их
#: нужно, потому что подкоманда — первое слово без ключа.
GLOBAL_WITH_VALUE: Final = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)
#: Приставка ссылки: в `refs/heads/agent/x` предметом сверки служит имя ветки.
REF_PREFIX: Final = "refs/heads/"


def push_targets(command: str) -> list[str] | None:
    """Имена веток, названные в `git push`; ``None`` — это не толчок.

    Разбор по СЛОВАМ: подстрока `git push` встречается и в тексте документа, и
    в сообщении коммита, а действие — только у разобранной команды.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    for segment in segments(words):
        if not segment or segment[0] != "git":
            continue
        rest = segment[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in GLOBAL_WITH_VALUE else rest[1:]
        if rest and rest[0] == "push":
            return named_branches(rest[1:])
    return None


def segments(words: list[str]) -> list[list[str]]:
    """Части составной строки: `cd … && git push …` — это две команды.

    Без разбиения вызов git, стоящий не первым, проходил мимо сторожа: живой
    промах при постройке — `cd x && git push origin main` не отвергался.
    """
    found: list[list[str]] = [[]]
    for word in words:
        if word in {"&&", "||", ";", "|", "&"}:
            found.append([])
            continue
        found[-1].append(word)
    return found


def named_branches(arguments: list[str]) -> list[str]:
    """Ветки-цели из аргументов `git push`, кроме первого (удалённого имени)."""
    found: list[str] = []
    skip = False
    seen_remote = False
    for word in arguments:
        if skip:
            skip = False
            continue
        if word in WITH_VALUE:
            skip = True
            continue
        if word.startswith("-"):
            continue
        if not seen_remote:
            seen_remote = True
            continue
        found.append(word)
    return found


def head() -> str:
    """Текущая ветка; пусто — головы нет (отсоединённое состояние)."""
    said = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return said.stdout.strip() if said.returncode == 0 else ""


def refused(targets: list[str], current: str) -> str:
    """Причина отказа; пусто — толчок разрешён."""
    for target in targets:
        # У формы `откуда:куда` предмет — правая часть: именно её имя получит
        # площадка, и именно по нему конвейер откроет изменение.
        if ":" in target:
            target = target.split(":", 1)[1]
        target = target.removeprefix(REF_PREFIX)
        if target == SHARED:
            return (
                f"«{SHARED}» — общая ветка: писать в неё напрямую нельзя, только изменением "
                "через ветку (критический запрет свода)"
            )
        if current and target != current:
            return (
                f"толчок в «{target}», а голова стоит на «{current}». Ветку изменения ведёт "
                "своё окно (012). Если это ваша работа — перейдите на неё, иначе конвейер "
                "откроет второе изменение на ту же работу: 10.09.2026 так и вышло с #116"
            )
    return ""


def main() -> int:
    """Точка входа: читает событие, решает, пускать ли команду."""
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Событие не разобралось — сторож молчит: ронять чужой инструмент из-за
        # своего разбора хуже, чем пропустить одну команду (084).
        return 0
    command = str(((event or {}).get("tool_input") or {}).get("command") or "")
    targets = push_targets(command)
    if not targets:
        return 0
    why = refused(targets, head())
    if not why:
        return 0
    print(f"Толчок отвергнут до вызова git: {why}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
