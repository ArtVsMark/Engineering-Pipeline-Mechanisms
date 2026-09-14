#!/usr/bin/env python3
"""След окна в истории: чем окно называется и сколько оно живёт.

СЛЕД ОКНА В ДЕРЕВЕ ЕСТЬ, И ЭТО ЗАМЕР, А НЕ ДОПУЩЕНИЕ. Трейлер
``Claude-Session`` несёт номер живой сессии и едет в общую ветку вместе с
работой: замер 14.09.2026 по полной истории — 309 коммитов из 340 несут его,
различных окон три, и на окно приходится 6, 44 и 258 изменений. Ответ проекта по
правилу
[006](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/006-window-lifetime.md)
до 14.09.2026 утверждал обратное — «в дереве следа окна нет вовсе», — и стоял на
замере, которого дерево не подтверждает. Разбор — в задаче
[#23](../../issues/23), находка `51a6454`.

ВЕЛИЧИНА, РАСТУЩАЯ ВМЕСТЕ С ОКНОМ, ТОЖЕ ЕСТЬ. Первый коммит окна и последний
задают срок его жизни: у трёх окон замера — 2 часа, 7 часов и 4 суток 13 часов.
Последнее — внутри объявленного правилом срока «три–пять дней» и у его верхней
границы, то есть величина не только измерима, но и легла ровно туда, где правило
её нормирует.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ВТОРАЯ КОПИЯ ОБРАЗЦА. Разбор трейлера уже жил в
``scripts/hail.py`` — оклик берёт из него адрес окна. Второй образец того же
разошёлся бы с первым молча: правка формата в одном месте из двух выглядит
полной, и ни одна сторона не сверяется с другой
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
Тот же приём, что у ``scripts/kinds.py``: общее уходит вверх, а не в сторону.

ОБРЕЗАННАЯ ИСТОРИЯ — НЕ НАЧАЛО ОКНА, И РАЗЛИЧАЕТ ИХ МЕХАНИЗМ. В мелком клоне
самый старый доступный коммит выглядит первым коммитом окна, и срок выходит
короче настоящего. Прочитать это как «окно молодое» значило бы выводить ответ из
незнания
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)):
здесь такой случай называется отдельным словом, а не округляется до чистого.
Пробел, из которого это выросло, назвал внешний взгляд той же находкой
`51a6454`: числовую премису, которую мелкий клон не даёт перепроверить, брали на
веру.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

#: Адрес окна в трейлере коммита. Читается номер, а не ссылка целиком: ссылка —
#: способ открыть, номер — то, чем окно называется.
SESSION_RE: Final = re.compile(r"^Claude-Session:\s*\S*?(session_[A-Za-z0-9]+)", re.MULTILINE)

#: Соавтор-окно в трейлере. По нему правило 006 и применимо: где окна не было,
#: там и срока его жизни нет, а требовать след от руки человека значило бы
#: краснеть на законном отсутствии предмета (075 — про предмет, а не про руку).
COAUTHOR_RE: Final = re.compile(r"^Co-Authored-By:\s*(?P<who>.+)$", re.MULTILINE | re.IGNORECASE)

#: Почта соавтора-окна. Сверяется почта, а не имя: имя подставляет окружение и
#: оно меняется, почта же опознаёт сторону — тот же выбор, что в
#: `.github/authors.txt`.
WINDOW_MAIL: Final = "noreply@anthropic.com"

#: Предел из правила 006: окно живёт три–пять дней. Верхняя граница и есть
#: предел, нижняя — повод предупредить. Величина ОБЪЯВЛЕНА правилом, а не
#: выведена из ряда: выводить её из трёх окон значило бы назначить порог по
#: одной точке замера (050) — ровно то, от чего проект отказался у покрытия.
LIMIT_DAYS: Final = 5
#: С этого срока срок называется вслух, но красным не становится: вероятное
#: предупреждает, верное держит (051).
WARN_DAYS: Final = 3


class NotRun(RuntimeError):
    """Механизм не отработал: третий исход, а не «чисто»."""


def git(*args: str, cwd: str | None = None) -> str:
    """Зовёт git и отдаёт вывод; отказ — третий исход, а не пустая строка."""
    found = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
    )
    if found.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {found.stderr.strip()}")
    return found.stdout


def session_of(message: str) -> str | None:
    """Номер окна из сообщения коммита; ``None`` — следа окна в нём нет."""
    found = SESSION_RE.search(message)
    return found.group(1) if found else None


def made_by_window(message: str) -> bool:
    """Работало ли над коммитом окно — по объявленному соавтору.

    Признак берётся у соавторства, а не у трейлера сессии: соавтора держит гейт
    `attribution`, а трейлер сессии не требует никто. Иначе «окно не подписалось»
    и «человек работал руками» слились бы в одно состояние, и механизм чинил бы
    не то (045).
    """
    return any(WINDOW_MAIL.lower() in who.lower() for who in COAUTHOR_RE.findall(message))


@dataclass(frozen=True)
class Commit:
    """Коммит в том виде, в каком его читает этот модуль."""

    sha: str
    when: datetime
    message: str

    @property
    def session(self) -> str | None:
        """Окно, сделавшее коммит."""
        return session_of(self.message)


#: Разделитель записей в выводе `git log`. Заведомо чужой для сообщения коммита:
#: перенос строки разделителем быть не может — тело многострочно.
SEP: Final = "\x1e"


def commits(*revs: str, cwd: str | None = None) -> list[Commit]:
    """Коммиты указанного диапазона, от старых к новым.

    Дата берётся АВТОРСКАЯ, а не коммитерская. Уплотнение и перенос ветки
    переписывают вторую, и срок жизни окна тогда считался бы от дня слияния —
    то есть мерил бы очередь, а не окно.
    """
    out = git("log", "--reverse", f"--pretty=format:{SEP}%H%x00%aI%x00%B", *revs, cwd=cwd)
    found: list[Commit] = []
    for record in out.split(SEP):
        if not record.strip():
            continue
        sha, when, message = record.split("\x00", 2)
        found.append(Commit(sha=sha, when=datetime.fromisoformat(when), message=message))
    return found


def is_shallow(cwd: str | None = None) -> bool:
    """Обрезана ли история. По ней «начало окна» читать нельзя."""
    return git("rev-parse", "--is-shallow-repository", cwd=cwd).strip() == "true"


@dataclass(frozen=True)
class Lifetime:
    """Сколько живёт окно и чем этот ответ подтверждён."""

    session: str
    first: Commit
    last: Commit
    #: Уверенность в НАЧАЛЕ: в обрезанной истории первый найденный коммит окна
    #: может быть не первым его коммитом, а первым видимым.
    whole: bool

    @property
    def age(self) -> timedelta:
        """Срок жизни окна между крайними его коммитами."""
        return self.last.when - self.first.when

    @property
    def over_limit(self) -> bool:
        """Пережило ли окно объявленный правилом 006 предел."""
        return self.age > timedelta(days=LIMIT_DAYS)

    @property
    def near_limit(self) -> bool:
        """Подошло ли к пределу — повод сказать, а не покраснеть."""
        return not self.over_limit and self.age >= timedelta(days=WARN_DAYS)


def said_age(age: timedelta) -> str:
    """Срок словами: сутки и часы, а не доля дня."""
    hours = age.days * 24 + age.seconds // 3600
    return f"{age.days} сут {hours % 24} ч"


def lifetime(session: str, history: str, head: Commit, *, cwd: str | None = None) -> Lifetime:
    """Срок жизни окна: от первого его коммита в истории до данной головы.

    ``history`` — что считать историей: обычно общая ветка. Начало ищется в ней,
    а не в ветке изменения: окно живёт дольше одной своей работы, и по ветке
    виден лишь её кусок.
    """
    seen = [commit for commit in commits(history, cwd=cwd) if commit.session == session]
    if not seen:
        # Окно в истории ещё не отметилось: первая его работа. Начало — голова
        # же, и срок нулевой. Это не пробел, а законное состояние.
        return Lifetime(session=session, first=head, last=head, whole=True)
    first = seen[0]
    whole = True
    if is_shallow(cwd=cwd):
        # Граница обрезки неотличима от начала окна: если первый видимый коммит
        # окна и есть самый старый доступный, раньше могло быть ещё.
        oldest = commits(history, "--max-parents=0", cwd=cwd) or commits(history, cwd=cwd)[:1]
        whole = bool(oldest) and first.sha != oldest[0].sha
    return Lifetime(session=session, first=first, last=head, whole=whole)
