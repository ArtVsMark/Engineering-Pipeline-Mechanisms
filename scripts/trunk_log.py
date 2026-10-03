"""История общей ветки: тела уплотнённых коммитов слитых изменений.

ОДНО ЧТЕНИЕ ИСТОРИИ НА ВСЕХ, КТО СЧИТАЕТ ПО НЕЙ. Прежде его держал архив
находок (`findings_archive`) один. С #1022 встречи родов находок едут
строкой `Род:` в теле коммита, и ту же историю читают ещё план работ и гейт
рождения правила. Чтение у архива значило бы круг импортов: архив зовёт
словарь родов, а словарь считал бы встречи через архив. Поэтому чтение
вынесено сюда, и архив берёт его отсюда же (022).

ОБРЕЗАННАЯ ИСТОРИЯ — ОТКАЗ, А НЕ МЕНЬШИЙ СЧЁТ. В мелком клоне `git log`
отдаёт один коммит, и встречи из всех прежних слияний пропали бы молча: род
выглядел бы встреченным реже, чем встречен, и порог повтора не наступал бы
(045). Решение владельца 03.10.2026 в #1022: мелкий клон — отказ.
"""

import re
from pathlib import Path
from typing import Final

import gitcall
import paths

#: Номер изменения в теме уплотнённого коммита: «Тема (#N)».
MERGED_SUBJECT_RE: Final = re.compile(r"\(#(\d+)\)$")
#: Разделители полей и записей в выводе `git log`.
FIELD: Final = "\x1f"
RECORD: Final = "\x00"
#: Чья история читается. ОБЩЕЙ ВЕТКИ, а не головы прогона: кнопка, нажатая на
#: другой ветке, иначе сняла бы находку её коммитом с «(#N)» и «Разобрано:».
#: Страж в `badges.yml` держит только перечитку, а история теперь читается
#: всегда (взгляд на #879); сверка по соседству идёт по той же ветке.
TRUNK_REF: Final = f"origin/{paths.TRUNK}"
#: Начало отказа на мелком клоне: тест узнаёт его по константе (209).
SHALLOW: Final = "история обрезана (мелкий клон)"


class NotRun(RuntimeError):
    """Историю прочитать не удалось: третий исход, а не «слияний нет»."""


def git_log(where: Path | None = None, ref: str = TRUNK_REF) -> str:
    """Темы и тела коммитов `ref` от старых к новым; по умолчанию — общая ветка."""
    return gitcall.output(
        ["log", "--reverse", "--format=%s%x1f%B%x00", ref],
        NotRun,
        cwd=str(where) if where else None,
    )


def merged_messages(log: str) -> list[tuple[int, str]]:
    """Номер изменения и тело его уплотнённого коммита — из вывода `git log`.

    Коммит без «(#N)» в теме слиянием изменения не считается и пропускается:
    снятие из него принадлежит не изменению, а прямой правке ветки.
    """
    out = []
    for record in log.split(RECORD):
        subject, _, body = record.strip("\n").partition(FIELD)
        said = MERGED_SUBJECT_RE.search(subject.strip())
        if said:
            out.append((int(said.group(1)), body))
    return out


def whole(where: Path | None = None) -> None:
    """Отказ, если история обрезана: по мелкому клону встречи недосчитаются."""
    said = gitcall.output(
        ["rev-parse", "--is-shallow-repository"], NotRun, cwd=str(where) if where else None
    )
    if said.strip() != "false":
        raise NotRun(f"{SHALLOW}: встречи родов по ней недосчитаются — нужен fetch-depth: 0")


def merged_bodies(where: Path | None = None, ref: str = TRUNK_REF) -> list[str]:
    """Тела уплотнённых коммитов `ref` от старых к новым; мелкий клон — отказ."""
    whole(where)
    return [body for _, body in merged_messages(git_log(where, ref))]


def branch_bodies(base: str, head: str = "HEAD", where: Path | None = None) -> list[str]:
    """Тела коммитов `base..head` от старых к новым — то, что уедет в тело уплотнения.

    Тело уплотнения `squash_body` собирает из этих же коммитов, поэтому
    строка `Род:`, названная здесь, — та, что дойдёт до истории общей ветки.
    """
    log = gitcall.output(
        ["log", "--reverse", "--format=%B%x00", f"{base}..{head}"],
        NotRun,
        cwd=str(where) if where else None,
    )
    return [body.strip("\n") for body in log.split(RECORD) if body.strip()]
