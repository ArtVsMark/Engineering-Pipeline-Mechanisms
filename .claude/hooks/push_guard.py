#!/usr/bin/env python3
"""Толчок не туда отвергается ДО вызова git, а не ловится после.

Держит два критических запрета свода, и адреса у них разные. «НЕ писать в main
напрямую» опирается на 131: операция, которая должна нести личность человека, из
агентского окна не выполняется — прокси подменяет учётные данные НА ЗАПИСИ, и
прямой толчок в общую ветку ровно такая операция. «НЕ пушить в ветку чужого
изменения» — из 012, и правило 131 к нему отношения не имеет: там речь не об
авторстве, а о том, что ветку ведёт своё окно. Общая ссылка «(012, 131)» на оба
запрета сразу приписывала 131 то, чего в нём нет; нашёл внешний взгляд на #143.

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
#: Обёртки, за которыми команда идёт СЛЕДУЮЩИМ словом. Список закрытый и
#: каждая названа: «похоже на обёртку» пропустило бы и то, что обёрткой не
#: является (068). `env` перед командой несёт ещё и присваивания `VAR=value` —
#: они пропускаются отдельно.
WRAPPERS: Final = frozenset({"env", "command", "nice", "nohup", "stdbuf", "time"})
#: Обёртки, которые принимают СКРИПТ строкой: `bash -c "git push …"`. Их
#: содержимое разбирается заново, как отдельная команда.
SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
#: Насколько глубоко сторож идёт внутрь вложенных оболочек. Предел нужен:
#: `bash -c "bash -c …"` без него ушёл бы в бесконечность, а не в отказ.
DEPTH: Final = 4


def is_git(word: str) -> bool:
    """Слово вызывает git — под любым написанием пути.

    Сторож ловил только буквальное `git`, и `/usr/bin/git push` проходил мимо
    целиком. Признак — ИМЯ программы, а не строка вызова: путь до неё дело
    окружения, а не намерения. Нашёл внешний взгляд на #143.
    """
    return word.rsplit("/", 1)[-1] == "git"


def unwrap(segment: list[str], depth: int) -> list[list[str]]:
    """Снимает обёртки и раскрывает `bash -c «…»`; отдаёт команды к разбору.

    ОБЁРТКА — НЕ МАСКИРОВКА, И СПИСОК ЕЁ ЗАКРЫТ. `env git push`, `nohup git
    push`, `bash -c "git push …"` — законные написания того же действия, и
    сторож, смотрящий только на первое слово, пропускал их все. Список
    разрешительный: что не названо обёрткой, обёрткой не считается (068).
    """
    if depth <= 0 or not segment:
        return [segment]
    first = segment[0].rsplit("/", 1)[-1]
    # `VAR=value git push` — присваивания перед командой, своё написание того же.
    if "=" in first and not first.startswith("=") and len(segment) > 1:
        return unwrap(segment[1:], depth - 1)
    if first in WRAPPERS and len(segment) > 1:
        return unwrap(segment[1:], depth - 1)
    if first in SHELLS:
        found: list[list[str]] = []
        for place, word in enumerate(segment[1:], start=1):
            if word == "-c" and place + 1 < len(segment):
                try:
                    inner = shlex.split(segment[place + 1])
                except ValueError:
                    break
                for part in segments(inner):
                    found.extend(unwrap(part, depth - 1))
                break
        return found or [segment]
    return [segment]


def push_targets(command: str) -> list[str] | None:
    """Имена веток, названные в `git push`; ``None`` — это не толчок.

    Разбор по СЛОВАМ: подстрока `git push` встречается и в тексте документа, и
    в сообщении коммита, а действие — только у разобранной команды.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    for part in segments(words):
        for segment in unwrap(part, DEPTH):
            if not segment or not is_git(segment[0]):
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


def head() -> tuple[str, str]:
    """Текущая ветка и причина, по которой её не узнать.

    ДВА ОТВЕТА, А НЕ ОДИН, и разница здесь стоит половины сторожа. Прежде отказ
    `git rev-parse` отдавался пустой строкой — той же, что и отсоединённая
    голова, — и половина проверки («толчок мимо своей ветки») исчезала МОЛЧА.
    Докстрока при этом уверяла, что пусто бывает только при отсоединённой
    голове; на деле пусто бывает и когда git не нашёлся, и когда каталог не
    репозиторий. Нашёл внешний взгляд на #143.

    Отсоединённая голова даёт `HEAD` и код 0 — это не отказ, и сюда не
    попадает.
    """
    said = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if said.returncode != 0:
        return "", said.stderr.strip() or f"git rev-parse вернул {said.returncode}"
    return said.stdout.strip(), ""


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
    current, broken = head()
    # ЗАПРЕТ НА ОБЩУЮ ВЕТКУ ГОЛОВЫ НЕ ТРЕБУЕТ, и спрашивается он первым: его
    # причина точнее, чем «сторож ослеп», и читателю нужна именно она (154).
    shared = refused(targets, "")
    if shared:
        print(f"Толчок отвергнут до вызова git: {shared}", file=sys.stderr)
        return 2
    if broken:
        # СТОРОЖ, КОТОРЫЙ НЕ СМОГ ПРОВЕРИТЬ, НЕ МАШЕТ РУКОЙ. Толчок необратим:
        # отправленную ветку окно удалить не может, и цена этого уже оплачена
        # (#116, воскрешённая ветка после слияния). Пропустить здесь значило бы
        # завести тихий запасной ответ ровно в том месте, ради которого сторож
        # и стоит (045).
        print(
            "Толчок отвергнут до вызова git: сторож не смог узнать текущую ветку — "
            f"{broken}. Проверка «толчок мимо своей ветки» не выполнена, а не пройдена. "
            "Почините git в этом каталоге и повторите.",
            file=sys.stderr,
        )
        return 2
    why = refused(targets, current)
    if not why:
        return 0
    print(f"Толчок отвергнут до вызова git: {why}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
