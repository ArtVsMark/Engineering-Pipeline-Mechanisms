#!/usr/bin/env python3
"""Имя нового окна: `[<окружение>] <проект> · <ДД.ММ>` — собранное, а не придуманное.

ЗАЧЕМ ЭТО СКРИПТ, А НЕ СТРОКА В НАВЫКЕ (#1703). Приставку окружения требует
правило [038](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/038-window-name-declares-its-environment.md),
краткое имя проекта решил владелец 26.10.2026. Окно, собирающее имя по памяти,
пишет `EPM` у соседа и `[Web]` вместо `[WEB]`: имя перестаёт искаться тем, кто
ищет окно по проекту.

ТАБЛИЦА ОДНА — У ПОСТАВЩИКА. Потребитель зовёт скрипт запускателем
(`.claude/mechanisms.sh`), то есть из выкачки механизмов по тегу: таблица
`.rules/window-names.json` приезжает рядом со скриптом, а репозиторий берётся
из `origin` клона, в котором окно работает. Копии у потребителя нет — вторая
разошлась бы с первой молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

ПРОЕКТ ВНЕ ТАБЛИЦЫ — НЕ ПРИДУМЫВАЕТСЯ. Имя из двух последних частей адреса
было бы правдоподобным и неверным; скрипт называет, чего нет, и куда дописать
строку ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Исходы (правило 039): ``0`` имя собрано · ``2`` таблица негодна или довод
неверен · ``3`` имя не собрать — клон не называет репозиторий площадки или его
нет в таблице.
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Final

import onboard
import paths

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_UNJUDGED: Final = 3

#: Окружения окна по правилу 038 — разрешительным перечнем (068).
ENVIRONMENTS: Final = ("WEB", "LOCAL", "CLI")
#: Краткое имя: заглавная латиница, две–пять букв.
SHORT: Final = re.compile(r"^[A-Z]{2,5}$")
#: Таблица поставщика — в той же выкачке, что скрипт, а не в дереве окна. Свой
#: корень выводится из якоря (`paths.SCRIPTS`), а не ходом вверх: предмет гейта
#: поиска вверх — розыск настройки, а здесь вычисляется собственный корень, как у
#: предполётной (115).
HERE: Final = Path(__file__).resolve().parent
TABLE: Final = Path(*HERE.parts[: -len(paths.SCRIPTS.parts)]) / paths.WINDOW_NAMES


class BadTable(ValueError):
    """Таблица кратких имён не читается или нарушает свою форму."""


def names(table: Path = TABLE) -> dict[str, str]:
    """Репозиторий → краткое имя; форма и единственность имён проверяются при чтении."""
    try:
        raw = json.loads(table.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BadTable(f"{table} не прочитана: {exc}") from exc
    found = raw.get("names") if isinstance(raw, dict) else None
    if not isinstance(found, dict) or not found:
        raise BadTable(f"{table}: нет непустого раздела `names`")
    seen: dict[str, str] = {}
    for repo, short in found.items():
        if not isinstance(short, str) or not SHORT.match(short):
            raise BadTable(f"{table}: имя «{short}» у {repo} — не 2–5 заглавных латинских букв")
        if short in seen:
            raise BadTable(f"{table}: имя «{short}» у {repo} уже занято {seen[short]}")
        seen[short] = repo
    return {repo.lower(): short for repo, short in found.items()}


def compose(env: str, short: str, day: datetime.date) -> str:
    """Имя окна из трёх частей."""
    return f"[{env}] {short} · {day:%d.%m}"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает имя окна для клона в рабочем каталоге."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, help="окружение окна: " + ", ".join(ENVIRONMENTS))
    parser.add_argument("--root", default=".", help="клон, в котором работает окно")
    args = parser.parse_args(argv)
    env = args.env.upper()
    if env not in ENVIRONMENTS:
        print(f"окружение «{args.env}» не из {', '.join(ENVIRONMENTS)} (038)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        table = names()
    except BadTable as exc:
        print(f"имя окна не собрано: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    repo = onboard.repo_of(Path(args.root))
    if not repo:
        print("имя окна не собрано: `origin` клона не называет репозиторий площадки")
        return EXIT_UNJUDGED
    short = table.get(repo.lower())
    if short is None:
        print(
            f"имя окна не собрано: у {repo} нет краткого имени — строка дописывается "
            f"поставщиком в `{paths.WINDOW_NAMES}` (#1703)"
        )
        return EXIT_UNJUDGED
    print(compose(env, short, datetime.date.today()))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
