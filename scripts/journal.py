"""Форма записи журнала: один словарь родов на все механизмы.

Роды читали двое и по-разному: сборка знала свой список, гейт изменения — свой,
и списки эти были копиями. Достаточно добавить род в одном месте, чтобы второй
механизм перестал видеть законный фрагмент, — и разошлись бы они молча, как уже
расходились состав меток и связь с задачей.

Роды взяты у соседей по семье (Keep a Changelog), плюс свой `contract`: здесь
версионируется контракт механизмов, и несовместимое изменение поверхности
обязано быть видно отдельно, а не тонуть в «изменено».
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Final

import report

KINDS: Final = {
    "contract": "Несовместимое: поверхность контракта",
    "added": "Добавлено",
    "changed": "Изменено",
    "fixed": "Исправлено",
    "removed": "Удалено",
    "internal": "Внутреннее",
}

#: Имя фрагмента: слаг по смыслу, род, `.md`. Слаг — не номер задачи: по имени
#: должно быть видно, о чём запись, иначе при сборке выпуска их три десятка
#: одинаковых.
NAME_RE: Final = re.compile(r"^(?P<slug>[\w.-]+)\.(?P<kind>" + "|".join(KINDS) + r")\.md$")
#: Тот же образец, но для пути в списке тронутых файлов.
PATH_RE: Final = re.compile(r"^changelog\.d/[\w.-]+\.(?:" + "|".join(KINDS) + r")\.md$")
#: Слаг из одних цифр — имя по задаче, а не по смыслу. Одна задача живёт дольше
#: одного изменения, и второй заход молча переписывает первый: `12.fix.md`
#: завели дважды, и запись об исправлении атрибуции исчезла без следа и без
#: выпуска. Конфликта при этом не возникает — побеждает последний, — поэтому
#: ловить это обязан гейт, а не внимательность (075).
DIGITS_ONLY_RE: Final = re.compile(r"^\d+$")
#: Ссылка на задачу — последней строкой записи.
LINK_LINE_RE: Final = re.compile(r"^#\d+(?: #\d+)*$")


class NotRun(RuntimeError):
    """Читать нечего: третий исход, а не пустой список.

    Живёт здесь вместе с чтением дифа: механизм, поймавший этот отказ, обязан
    объявить его своим третьим исходом, а не выдать за «проверено».
    """


def base_from_env(given: str = "") -> str:
    """База сравнения: переданная зовущим либо выведенная из окружения прогона.

    Площадка отдаёт базу коротким именем («main»), а в дереве прогона она
    существует как `origin/main`. Приставка ставится ТОЛЬКО к умолчанию:
    переданное ключом имя — это то, что имел в виду зовущий, и молча
    переписывать его нельзя. Ровно на этом гейт упал в первом прогоне на
    площадке: локально переменной нет, и расхождение не воспроизводилось.
    """
    if given:
        return given
    from_env = os.environ.get("GITHUB_BASE_REF")
    return f"origin/{from_env}" if from_env else "origin/main"


def git(args: list[str]) -> str:
    """Зовёт git, обращая любой отказ в третий исход."""
    try:
        return subprocess.run(
            args, capture_output=True, check=True, text=True, encoding="utf-8"
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise NotRun(f"{' '.join(args)} → {report.cut(str(detail))}") from exc


def changed_files(base: str) -> list[str]:
    """Файлы, тронутые изменением относительно общего предка с базой.

    `-z` обязателен: без него git экранирует имена с пробелами и не-ASCII, и
    такой путь молча выпадает из отбора
    ([165](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/165-git-path-lists-are-read-by-nul.md)).
    """
    merge_base = git(["git", "merge-base", base, "HEAD"]).strip()
    if not merge_base:
        raise NotRun(f"общий предок с «{base}» не найден")
    out = git(["git", "diff", "--name-only", "-z", f"{merge_base}...HEAD"])
    files = [name for name in out.split("\0") if name]
    if not files:
        raise NotRun(
            f"относительно «{base}» изменений нет — гейту нечего проверять, "
            "и это ошибка входа, а не «прошло» (075)"
        )
    return files
