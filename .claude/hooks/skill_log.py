"""Каждый вызов навыка — строка журнала: невызванный навык становится виден (#1449).

ЗАЧЕМ. Навыки держат правила каталога, у части правил навык — единственное, чем
они держатся. Но навык не краснеет: невызванный неотличим от вызванного (решение
031). Журнал вызовов делает второе наблюдаемым, а сводка `skill_runs.py`
называет навык, которого не зовут вовсе.

СПЕРВА СПРОСИЛИ СЕМЬЮ (162): хук журнала есть у каталога с 16.10.2026 —
`ArtVsMark/Engineering-Incidents-Playbook:.claude/hooks/skill_log.py`, сводки
нет ни у кого. Приём и форма строки взяты у каталога своим файлом, а не копией
(153). Форма — та же поле в поле: «у каждого своя сводка, но механизм общий,
чтобы данные можно было свести в единый» (решение владельца 17.10.2026, #1449),
и журнал каталога сводка читает без переписывания. Своё здесь одно: вызов,
чьё имя не прочитано, пишется строкой с `"skill": null`, а не пропадает молча
(045). Хук стоит на событии с отбором `Skill`, поэтому событие — всегда вызов
навыка, даже если разобрать его нечем.

ЧТО ПИШЕТСЯ. Время, имя навыка, исход и номер сессии — и ничего из текста
запроса: доводы навыка несут слова владельца. Имя и номер сессии —
идентификаторы, и всё, что на идентификатор не похоже, не пишется как есть.

КУДА. `.claude/state/skill-runs.jsonl` в корне проекта (`CLAUDE_PROJECT_DIR`),
под `.gitignore`: журнал — данные окна, а не дерева.

ЧЕМ ИСПОЛНЯЕТСЯ. Обёртка `skill_log.sh` зовёт интерпретатор планки тем же
приёмом, что у стража толчка (217).

НЕОБЯЗАТЕЛЬНЫЙ КАНАЛ (084), НО НЕ МОЛЧАЛИВЫЙ (045). Журнал вызова навыка не
держит: кода 2 хук не ставит никогда. Записано — код 0. Не записано — код 1:
площадка считает его неблокирующей ошибкой, показывает причину человеку, и
работа идёт дальше. Stderr при коде 0 человек не видит, поэтому отказ записи
кодом 0 был бы тихим пропуском. Каталог здесь выходит 0 всегда, и это
единственное расхождение с ним: форма строки от кода выхода не зависит.

ГРАНИЦЫ, И ОНИ НАЗВАНЫ. Облачное окно эфемерно: журнал умирает с контейнером,
а писать из облака в трекер нельзя (131). Поэтому журнал копится на локальной
машине, и сводку в трекер отправляет локальное окно. Журнал лежит в корне ТОГО
дерева, где идёт окно: у каждого git worktree свой, и удалённое рабочее дерево
уносит свой журнал. Сводка читает журнал одного корня — журнал другого дерева
ей называют ключом `--journal`. Навык, который окно прочитало файлом, а не
позвало инструментом, журнал не видит.

Вход: JSON события PostToolUse или PostToolUseFailure на stdin; первый довод —
`ok` или `fail` — называет событие.
"""

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

#: Журнал — относительно корня проекта.
JOURNAL: Final = Path(".claude") / "state" / "skill-runs.jsonl"
#: Имя навыка и номер сессии — идентификатор: `плагин:навык`, буквы, цифры, `-_./`.
#: Тот же образец, что у каталога: строки семьи обязаны читаться одним разбором.
NAME_RE: Final = re.compile(r"[\w.:/-]{1,100}")
#: Больше этого вход не разбирается: событие несёт ответ навыка и бывает велико,
#: а журналу нужно одно поле (016). Неразобранный вход — строка без имени.
LIMIT: Final = 1024 * 1024
#: Исходы — имена событий: вызов прошёл или навык отказал. Довод хука обязан
#: быть одним из них: незнакомый не подменяется «ok» (045).
OUTCOMES: Final = ("ok", "fail")
#: Сколько знаков незнакомого довода называет отказ.
SHOWN: Final = 40
#: Записано — и вызов без прочитанного имени тоже: строка есть, сводка её назовёт.
RECORDED: Final = 0
#: Не записано: площадка покажет причину человеку, не останавливая работу.
NOT_RECORDED: Final = 1
#: Корень проекта, если окно его не назвало: каталог, где хук запущен. Окно
#: зовёт хук из корня проекта, так что это то же место, а не догадка.
HERE: Final = "."


def line_of(event: object, outcome: str, now: datetime) -> dict[str, str | None] | None:
    """Строка журнала из события; `None` — событие не о навыке, писать нечего.

    Событие не словарь или имя не той формы — строка с `"skill": null`: отбор
    хука уже сказал, что это вызов навыка, и терять его нельзя (045).
    """
    if isinstance(event, dict) and event.get("tool_name", "Skill") != "Skill":
        return None
    given = event.get("tool_input") if isinstance(event, dict) else None
    name = given.get("skill") if isinstance(given, dict) else None
    session = event.get("session_id") if isinstance(event, dict) else None
    return {
        "ts": now.isoformat(timespec="seconds"),
        "skill": name if isinstance(name, str) and NAME_RE.fullmatch(name) else None,
        "outcome": outcome,
        "session": session
        if isinstance(session, str) and NAME_RE.fullmatch(session)
        else None,
    }


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    """Пишет вызов навыка; не записанный — причина в stderr и код 1, а не тишина."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in OUTCOMES:
        # Опечатка в команде хука засчитала бы отказы навыка вызовами молча —
        # поэтому вызов не пишется, а причина видна человеку (045).
        said = f"«{argv[0][:SHOWN]}»" if argv else "не назван"
        print(
            f"журнал навыков: исход события {said}, а ждут {' или '.join(OUTCOMES)} — "
            "вызов не записан; поправьте команду хука в .claude/settings.json",
            file=sys.stderr,
        )
        return NOT_RECORDED
    outcome = argv[0]
    raw = sys.stdin.read(LIMIT + 1)
    event: object = None
    if len(raw) > LIMIT:
        print(
            "журнал навыков: вход больше предела — вызов записан без имени",
            file=sys.stderr,
        )
    else:
        try:
            event = json.loads(raw)
        except ValueError:
            print(
                "журнал навыков: вход не JSON — вызов записан без имени",
                file=sys.stderr,
            )
    line = line_of(event, outcome, now or datetime.now(UTC))
    if line is None:
        return RECORDED
    where = Path(os.environ.get("CLAUDE_PROJECT_DIR") or HERE) / JOURNAL
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        with where.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"журнал навыков: {where} не записан — {exc.strerror}", file=sys.stderr)
        return NOT_RECORDED
    return RECORDED


if __name__ == "__main__":
    raise SystemExit(main())
