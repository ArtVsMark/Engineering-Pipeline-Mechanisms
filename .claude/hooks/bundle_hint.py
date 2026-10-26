#!/usr/bin/env python3
"""Режешь ветку `agent/…` — позван ли `bundle-the-work` в этой сессии (#1708).

ЗАЧЕМ. Свод называет триггер навыка `bundle-the-work`: «звать, когда берёшь
строку плана и режешь под неё ветку». Держит вызов только память окна, а навык
не краснеет: невызванный неотличим от вызванного (решение 031). Замер
26.10.2026 (#1708): окно нарезало три ветки `agent/…` и ни при одной не позвало
навык, а второй дефект раздела 3 и пять его соседей ушли бы отдельным кругом.

СПЕРВА СПРОСИЛИ СЕМЬЮ (162) — 26.10.2026, чтением клонов, без запуска: совета
о пачке при нарезке ветки нет ни у кого. У каталога хуки окна — страж толчка и
журнал навыков, а навыка пачки у него нет вовсе. У соседей хуки перед командой
оболочки держат толчок в чужую ветку и встроенный документ без кавычек, о
вызове навыка не спрашивает ни один. Приём «совет по журналу этой сессии» свой,
а разбор команды взят у нашего же стража толчка.

ПРИЗНАК — ЖУРНАЛ ВЫЗОВОВ ЭТОЙ СЕССИИ. Хук журнала (`skill_log.py`) пишет
каждый вызов навыка строкой с номером сессии; здесь читается он же, по тому же
номеру из события. Вызов есть — хук молчит; нет — говорит окну одной строкой.

СОВЕТ, А НЕ БЛОК (084, 051). Ветка под починку раздела 0 режется без пачки, и
судить это хуку нечем (057): нарезку он не держит никогда. Совет уходит модели
полем `additionalContext` события `PreToolUse`, без решения о разрешении —
вызов идёт обычным путём, разрешения хук не трогает. Код 1 модель не видит, а
код 2 заблокировал бы нарезку.

ЖУРНАЛ НЕ ЧИТАЕТСЯ — ПРИЧИНА, А НЕ СОВЕТ ВСЛЕПУЮ (045). Нет файла, нет номера
сессии в событии, файл не читается — совет «позовите навык» мог бы быть ложным,
поэтому окну говорится, что проверить нечем и почему, а нарезка идёт дальше.

РАЗБОР КОМАНДЫ — СТРАЖА ТОЛЧКА (`push_guard.commands_of`, `unwrap`), а не
второй рядом (214): кавычки, цепочки `&&`, обёртки `env` и `bash -c` он уже
знает, и тело встроенного документа для него — данные, а не команда.

ГРАНИЦЫ НАЗВАНЫ. Ловится нарезка `git checkout -b|-B|--orphan`, `git switch
-c|-C` (и длинные `--create`, `--force-create`) и `git worktree add -b|-B` с
именем `agent/…`; ветка, созданная `git branch` и потом взятая, — нет: она ещё
не работа. Короткий ключ читается и слитно (`-bagent/x`). Навык, прочитанный
файлом, а не позванный инструментом, журнал не видит, и совет тогда придёт —
это и есть цена самоотчёта. То же с навыком, который человек позвал сам
командой `/bundle-the-work`: если вызов прошёл мимо инструмента `Skill`, хук
журнала его не записал, и совет будет ложным — пропустите его.

Вход: JSON события PreToolUse на stdin. Выход: всегда 0; совет — JSON на stdout.
"""

import json
import os
import sys
from pathlib import Path
from typing import Final

import push_guard
import skill_log

#: Навык, вызов которого ищется.
SKILL: Final = "bundle-the-work"
#: Журнал вызовов — тот же, что пишет `skill_log.py`, относительно корня проекта.
JOURNAL: Final = Path(".claude") / "state" / "skill-runs.jsonl"
#: Корень проекта, если окно его не назвало: каталог, где хук запущен.
HERE: Final = "."
#: Ключи, создающие ветку: у `checkout` и у `switch`. Имя — следующее слово.
CREATE: Final[dict[str, frozenset[str]]] = {
    "checkout": frozenset({"-b", "-B", "--orphan"}),
    "switch": frozenset({"-c", "-C", "--create", "--force-create"}),
    # `git worktree add -b <ветка> <путь>` — подкоманда в два слова (взгляд на #1711).
    "worktree add": frozenset({"-b", "-B"}),
}
#: Больше этого журнал не читается: он копится за сессию, а нужен один признак.
LIMIT: Final = 4 * 1024 * 1024
#: Больше этого событие не разбирается: нужна одна команда (016).
EVENT_LIMIT: Final = 1024 * 1024


def created(command: str) -> list[str]:
    """Ветки `agent/…`, которые команда создаёт; не разобрать — пусто.

    Неразобранная команда здесь не причина для слов: совет — необязательный
    канал, и о слепоте разбора говорит страж толчка, если это толчок.
    """
    try:
        parts = push_guard.commands_of(command)
    except ValueError:
        return []
    found: list[str] = []
    for part in parts:
        segments, blind = push_guard.unwrap(part, push_guard.DEPTH)
        if blind:
            continue
        for segment in segments:
            if not segment or not push_guard.is_git(segment[0]):
                continue
            rest = segment[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in push_guard.GLOBAL_WITH_VALUE else rest[1:]
            if rest[:2] == ["worktree", "add"]:
                rest = ["worktree add", *rest[2:]]
            if not rest or rest[0] not in CREATE:
                continue
            flags = CREATE[rest[0]]
            words = rest[1:]
            for at, word in enumerate(words):
                name = ""
                if word in flags and at + 1 < len(words):
                    name = words[at + 1]
                elif word.startswith("--") and "=" in word and word.split("=", 1)[0] in flags:
                    name = word.split("=", 1)[1]
                elif not word.startswith("--") and len(word) > 2 and word[:2] in flags:
                    # Слитная короткая форма `-bagent/x`: git её принимает, и
                    # ветка резалась молча (поздний взгляд на #1711).
                    name = word[2:]
                if name.startswith(push_guard.AGENT_PREFIX):
                    found.append(name)
    return found


def invoked(journal: Path, session: str) -> bool:
    """Позван ли навык в этой сессии; журнал не читается — `OSError`/`ValueError`.

    ЧИТАЕТСЯ ХВОСТ, А НЕ НАЧАЛО (взгляд на #1711). `skill_log.py` только
    дописывает в конец и журнал не чистит, и строки нынешней сессии лежат
    последними: чтение первых `LIMIT` байт за предел журнала давало бы ложный
    совет без причины. Первая строка хвоста, обрезанная посередине, отброшена.
    """
    with journal.open("rb") as raw:
        size = raw.seek(0, os.SEEK_END)
        start = max(0, size - LIMIT)
        raw.seek(start)
        text = raw.read().decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start:
        lines = lines[1:]
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("session") != session:
            continue
        skill = row.get("skill")
        if isinstance(skill, str) and skill.rsplit(":", 1)[-1] == SKILL and row.get("outcome") == "ok":
            return True
    return False


def advice(event: object, root: Path) -> str:
    """Что сказать окну: пусто — молчать."""
    tool = event.get("tool_input") if isinstance(event, dict) else None
    command = tool.get("command") if isinstance(tool, dict) else None
    if not isinstance(command, str) or push_guard.AGENT_PREFIX not in command:
        return ""
    branches = created(command)
    if not branches:
        return ""
    named = ", ".join(f"`{one}`" for one in branches)
    session = event.get("session_id") if isinstance(event, dict) else None
    if not isinstance(session, str) or not session:
        return (
            f"bundle_hint: режется ветка {named}, но номера сессии в событии нет — "
            f"позван ли `{SKILL}`, проверить нечем (045)."
        )
    # НОМЕР СЕССИИ — ТОЙ ФОРМЫ, ЧТО ПИШЕТ ЖУРНАЛ (взгляд на #1711, 214): номер
    # вне `skill_log.NAME_RE` журнал пишет пустым, и вызов навыка под ним не
    # нашёлся бы никогда — совет был бы ложным, а не честным «проверить нечем».
    if not skill_log.NAME_RE.fullmatch(session):
        return (
            f"bundle_hint: режется ветка {named}, а номер сессии не той формы, что пишет "
            f"журнал навыков, — позван ли `{SKILL}`, проверить нечем (045)."
        )
    journal = root / JOURNAL
    try:
        if invoked(journal, session):
            return ""
    except FileNotFoundError:
        return (
            f"bundle_hint: режется ветка {named}, а журнала вызовов навыков ({JOURNAL}) нет — "
            f"позван ли `{SKILL}`, проверить нечем; хук журнала — `skill_log.py` (045)."
        )
    except (OSError, ValueError) as exc:
        return (
            f"bundle_hint: режется ветка {named}, а журнал вызовов навыков не читается "
            f"({exc.__class__.__name__}) — позван ли `{SKILL}`, проверить нечем (045)."
        )
    return (
        f"Режется ветка {named}, а навык `{SKILL}` в этой сессии не позван: "
        "позовите его до первого коммита — соседи по файлам, цепочке и предмету едут "
        "одним изменением (AGENTS.md, «Открытая работа»). Ветка под починку раздела 0 "
        "режется и без пачки — тогда совет пропустите."
    )


def main() -> int:
    """Точка входа: совет — полем `additionalContext`, код — всегда 0."""
    try:
        event: object = json.loads(sys.stdin.read(EVENT_LIMIT))
    except ValueError:
        return 0
    try:
        said = advice(event, Path(os.environ.get("CLAUDE_PROJECT_DIR") or HERE))
    except Exception as exc:
        # Совет — необязательный канал (084): сбой разбора не роняет нарезку, но
        # и не молчит — модель видит, что совета не было и почему (045).
        said = f"bundle_hint: совет не собран — {push_guard.cut(repr(exc))}"
    if said:
        print(
            json.dumps(
                {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": said}},
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
