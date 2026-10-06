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
from datetime import UTC, datetime
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
#: Слияние площадки без уплотнения: «Merge pull request #N from …». Его тело —
#: не тело изменения: строки `Разобрано:` и `Род:` у такого слияния лежат в
#: коммитах ветки, и история их не отдаёт. Они считаются, а не угадываются.
UNSQUASHED_RE: Final = re.compile(r"^Merge pull request #\d+ from ")
#: Начало отказа на мелком клоне: тест узнаёт его по константе (209).
SHALLOW: Final = "история обрезана (мелкий клон)"


class NotRun(RuntimeError):
    """Историю прочитать не удалось: третий исход, а не «слияний нет»."""


def git_log(where: Path | None = None, ref: str = TRUNK_REF) -> str:
    """Темы, даты коммитера и тела коммитов `ref` от старых к новым; по умолчанию — общая ветка.

    Запись — «тема · дата · тело» через `FIELD`. Дата едет в том же выводе,
    чтобы даты слияний разбирались из одного прохода истории, а не из
    второго (взгляд на #1158); разбор (`fields`) принимает и запись без даты.
    """
    return gitcall.output(
        ["log", "--reverse", "--format=%s%x1f%cI%x1f%B%x00", ref],
        NotRun,
        cwd=str(where) if where else None,
    )


def fields(record: str) -> tuple[str, str, str]:
    """Тема, дата и тело одной записи `git_log`; запись в два поля — без даты."""
    parts = record.strip("\n").split(FIELD, 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return parts[0], "", parts[1] if len(parts) == 2 else ""


def merged_messages(log: str) -> list[tuple[int, str]]:
    """Номер изменения и тело его уплотнённого коммита — из вывода `git log`.

    Коммит без «(#N)» в теме слиянием изменения не считается и пропускается:
    снятие из него принадлежит не изменению, а прямой правке ветки.
    """
    out = []
    for record in log.split(RECORD):
        subject, _, body = fields(record)
        said = MERGED_SUBJECT_RE.search(subject.strip())
        if said:
            out.append((int(said.group(1)), body))
    return out


def unsquashed(log: str) -> int:
    """Сколько слияний площадки без уплотнения в истории — их тел счёт не видит (#879)."""
    return sum(1 for record in log.split(RECORD) if UNSQUASHED_RE.search(fields(record)[0].strip()))


def unseen(where: Path | None = None, ref: str = TRUNK_REF) -> int:
    """Слияний без уплотнения в истории `ref`: их строки `Род:` в счёт не попадают.

    ПРЕДЕЛ НАЗВАН ЧИСЛОМ, А НЕ МОЛЧАНИЕМ (045, взгляд на #1086). Замер
    04.10.2026: таких слияний 17, все — #1…#154, до уплотнения и задолго до
    строки `Род:`, то есть встреч в них нет. Новое такое слияние строки
    `Род:` своей ветки потеряло бы, и читатели счёта печатают это число.
    """
    return unsquashed(git_log(where, ref))


def whole(where: Path | None = None, lost: str = "встречи родов") -> None:
    """Отказ, если история обрезана; ``lost`` — что по ней недосчиталось бы.

    Предмет называет зовущий: у счёта родов это встречи, у предела окна — окна
    изменений (взгляд на #1094).
    """
    said = gitcall.output(
        ["rev-parse", "--is-shallow-repository"], NotRun, cwd=str(where) if where else None
    )
    if said.strip() != "false":
        raise NotRun(f"{SHALLOW}: {lost} по ней недосчитаются — нужен fetch-depth: 0")


def merge_dates(log: str) -> dict[int, str]:
    """Дата слияния каждого уплотнённого изменения — из того же вывода `git_log` (#1136).

    Дата — время коммитера уплотнённого коммита «Тема (#N)», в UTC: площадка
    ставит его в миг слияния. Слияние без уплотнения своего «(#N)» в теме не
    несёт и сюда не входит. Запись без даты (двухпольная) пропускается.

    ПОСЫЛКА ИЗМЕРЕНА, А НЕ ПРИНЯТА (044, поздние взгляды на #1162). Время
    коммитера сдвигает переписанная история — rebase, cherry-pick. Замер
    06.10.2026 по восьми последним слияниям (#1156–#1163): время коммитера
    на `main` совпадает с `merged_at` площадки до секунды, расходится только
    пояс. Переписать `main` не даёт защита ветки, а коммит выпуска — новый
    коммит, не перезапись. ГРАНИЦА (046): обход защиты владельцем с
    переписыванием истории сдвинул бы эти даты, и читатели (`verify_queue`,
    `findings_db`) этого не заметят.
    """
    out: dict[int, str] = {}
    for record in log.split(RECORD):
        subject, when, _ = fields(record)
        said = MERGED_SUBJECT_RE.search(subject.strip())
        if said and when.strip():
            stamp = datetime.fromisoformat(when.strip()).astimezone(UTC)
            out.setdefault(int(said.group(1)), stamp.isoformat(timespec="seconds"))
    return out


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
