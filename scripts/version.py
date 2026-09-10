#!/usr/bin/env python3
"""Версия проекта считается, а не вписывается: MAJOR.MINOR из тега, PATCH — счёт.

МЕТОДИКА ВЗЯТА У ГРЕЙДЕРА, И ЭТО ОСОЗНАННЫЙ ПЕРЕНОС, А НЕ СОВПАДЕНИЕ. У соседа
она уже пережила два инцидента и подтверждена замерами; писать свою значило бы
пройти те же грабли заново
([162](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/162-a-gap-asks-the-neighbours-first.md)).
Что именно взято:

* **MAJOR.MINOR — из последнего РЕЛИЗНОГО тега** вида ``vX.Y.Z``. Маска строгая:
  рядом живут служебные теги, и наивное ``v*`` выбирало у соседа
  ``v-checkpoint-…`` наравне с релизным, роняя разбор;
* **PATCH — число ПРИНЯТЫХ ИЗМЕНЕНИЙ после тега**, а не патч-релиз: `X.Y.17`
  читается как «17 принятых изменений после тега `vX.Y.0`»;
* **считаются СУЩНОСТИ, А НЕ РЁБРА ГРАФА.** Изменение опознаётся по НОМЕРУ —
  ``(#N)`` в теме уплотнения либо ``Merge pull request #N``, — и номера
  складываются во множество. Поэтому счётчик не зависит ни от формы истории, ни
  от того, на сколько коммитов автор раздробил работу.

ПОЧЕМУ НЕ ТОПОЛОГИЯ. Формула по графу меряет ФОРМУ истории, а форма зависит от
окна: `git pull` мержем уводит пришедшее с площадки во второй родитель. У соседа
это замерено — ``--first-parent`` давал 2 вместо 3, ``--no-merges`` 6 вместо 4;
ни одна топологическая формула не даёт обе цифры разом.

ЧТО ЗДЕСЬ ИНАЧЕ, ЧЕМ У СОСЕДА, И ПОЧЕМУ. У него до первого тега MAJOR.MINOR
читаются из метаданных установленного пакета: он публикуется, версия собирается
`setuptools-scm`. Здесь пакета нет и не будет — версионируется КОНТРАКТ
механизмов, — поэтому запасной источник другой: файл `CONTRACT_VERSION`, единый
источник объявленной версии контракта
([035](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/035-version-is-never-edited-by-hand.md)).

КЛОН БЕЗ ТЕГОВ ВЕРСИЮ НЕ ВЫДУМЫВАЕТ. Так клонирует облачное окно и
`actions/checkout` без `fetch-depth: 0`: тегов не видно, и `0.0.N` выглядел бы
правдоподобно, будучи ложью. Такой заход говорит об этом вслух и подсказывает
`git fetch --tags`
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Исходы (правило 039): ``0`` версия посчитана · ``2`` шаг не отработал ·
``3`` посчитана неполно либо разошлась с объявленной — сказано, а не скрыто.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import paths

#: Релизный тег: строго `vX.Y.Z`. Маска для git и образец здесь — форма
#: проверяется дважды, потому что glob не отличает `v1.10.0` от `v1.10.0-rc`.
RELEASE_TAG_GLOB: Final = "v[0-9]*.[0-9]*.[0-9]*"
RELEASE_TAG_RE: Final = re.compile(r"^v\d+\.\d+\.\d+$")

#: Номер изменения в теме коммита. Две формы: уплотнение площадки дописывает
#: `(#N)` в конец темы, слияние мержем даёт `Merge pull request #N`. Обе ведут
#: к одному изменению и попадают в одно множество.
PR_NUMBER_RE: Final = re.compile(r"\(#(\d+)\)")
MERGE_PR_RE: Final = re.compile(r"^Merge pull request #(\d+)\b")

#: Коммит шага значков: он не изменение, а след сборки.
BADGE_COMMIT: Final = "факты и значок"
#: Склеивающий мерж `git pull`: сводит две копии ОДНОЙ ветки и своего изменения
#: не несёт. Мерж ветки-работы (`Merge branch 'feat'`) сюда не подпадает — в нём
#: и есть принятая работа.
SYNC_MERGE_RE: Final = re.compile(
    r"^Merge (?:remote-tracking )?branch '[^']+' of |^Merge remote-tracking branch '"
)

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_PARTIAL: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «версия 0.0.0»."""


def git(*args: str, root: Path | None = None) -> str | None:
    """Ответ git без хвостового перевода строки; ``None`` — данных нет.

    ДЕРЕВО НАЗЫВАЕТСЯ, А НЕ ПОДРАЗУМЕВАЕТСЯ. Без этого версия считалась по
    ТЕКУЩЕМУ рабочему каталогу, каким бы дерево ни назвал зовущий: сборка
    фактов принимает корень и передаёт его во всё, кроме версии, — и получала
    число не о том дереве. Нашёл внешний взгляд на #106.

    Кодировка задана явно: темы коммитов проекта по-русски, а `text=True` без
    неё берёт кодовую страницу окружения. `errors="replace"` — потому что один
    коммит с иной кодировкой не должен ронять подсчёт версии: битый знак в теме
    максимум мешает распознать номер.
    """
    try:
        out = subprocess.check_output(
            ["git", *args],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.strip()


def subjects(span: str, root: Path | None = None, *, first_parent: bool = False) -> list[str]:
    """Темы коммитов диапазона; при `first_parent` — только по главной линии."""
    args = ["log", "--pretty=%s"]
    if first_parent:
        args.append("--first-parent")
    out = git(*args, span, root=root)
    return [line for line in (out or "").split("\n") if line]


def numbers_in(lines: list[str]) -> set[str]:
    """Номера изменений из тем: `(#N)` и `Merge pull request #N`."""
    found: set[str] = set()
    for line in lines:
        found.update(PR_NUMBER_RE.findall(line))
        merged = MERGE_PR_RE.match(line)
        if merged:
            found.add(merged.group(1))
    return found


def counts_alone(subject: str) -> bool:
    """Считать ли коммит БЕЗ номера отдельным принятым изменением.

    Не считаются след сборки значков и склеивающий мерж: первый не изменение,
    второй — не своё изменение. Всё прочее без номера — прямой коммит в общую
    ветку, и он реален.
    """
    return BADGE_COMMIT not in subject and not SYNC_MERGE_RE.match(subject)


def changes_in(span: str, root: Path | None = None) -> int:
    """Число принятых изменений в диапазоне: сущности, а не рёбра графа.

    Номера собираются по ВСЕЙ истории диапазона — при `git pull` мержем
    пришедшее с площадки лежит во втором родителе, — а множество гасит двойной
    учёт, если одно изменение попало в историю дважды.

    Коммиты БЕЗ номера берутся только с главной линии: иначе внутренние коммиты
    слитой ветки считались бы поштучно, и дробление работы завышало бы счёт.
    """
    numbered = numbers_in(subjects(span, root))
    alone = [
        subject
        for subject in subjects(span, root, first_parent=True)
        if not PR_NUMBER_RE.search(subject)
        and not MERGE_PR_RE.match(subject)
        and counts_alone(subject)
    ]
    return len(numbered) + len(alone)


def release_tag(root: Path | None = None) -> str | None:
    """Последний ВЫПУЩЕННЫЙ тег из достижимых или ``None``, если такого нет.

    ПРЕДРЕЛИЗНЫЙ ТЕГ БОЛЬШЕ НЕ ГЛОТАЕТ ОТВЕТ ЦЕЛИКОМ. Прежде спрашивался
    ближайший тег по образцу, и `v0.2.0-rc1` под образец подходит, а под
    строгую форму — нет: ответом становилось «выпусков не видно вовсе», хотя
    рядом лежал настоящий `v0.1.0`. Один предрелизный тег обнулял бы версию
    проекта и значок. Нашёл внешний взгляд на #106.

    Спрашиваются ДОСТИЖИМЫЕ теги: тег из чужой ветки выпуском этой истории не
    является, и считать от него было бы неверно.
    """
    out = git("tag", "--merged", "HEAD", "--list", RELEASE_TAG_GLOB, root=root)
    released = [line for line in (out or "").split("\n") if RELEASE_TAG_RE.match(line)]
    if not released:
        return None
    return max(released, key=lambda tag: tuple(int(part) for part in tag.lstrip("v").split(".")))


def declared(root: Path | None = None) -> str:
    """Объявленная версия контракта — единый источник MAJOR.MINOR до тега."""
    path = (root / paths.VERSION) if root else paths.VERSION
    if not path.is_file():
        raise NotRun(f"нет {path}: объявленную версию взять неоткуда (075)")
    value = path.read_text(encoding="utf-8").strip()
    if not RELEASE_TAG_RE.match(f"v{value}"):
        raise NotRun(f"{path}: «{value}» не версия вида X.Y.Z")
    return value


def version(root: Path | None = None) -> tuple[str, bool]:
    """Версия проекта и признак «посчитана полно».

    Неполно — это когда тегов не видно: MAJOR.MINOR берутся из объявленного
    файла, а он говорит о контракте, а не о выпущенном. Разницу надо назвать,
    а не спрятать за правдоподобным числом.
    """
    tag = release_tag(root)
    if tag is not None:
        major, minor, _ = tag.lstrip("v").split(".")
        return f"{major}.{minor}.{changes_in(f'{tag}..HEAD', root)}", True
    major, minor, _ = declared(root).split(".")
    return f"{major}.{minor}.{changes_in('HEAD', root)}", False


def agrees() -> str:
    """Расхождение объявленной версии с последним тегом; пусто — сошлись.

    Тег ставится ПО объявленной версии, поэтому MAJOR.MINOR у них обязаны
    совпадать. Разошлись — значит одно из двух правилось мимо другого, и
    какое именно, механизму знать неоткуда: он называет расхождение, а не
    выбирает победителя (154).
    """
    tag = release_tag()
    if tag is None:
        return ""
    theirs = ".".join(tag.lstrip("v").split(".")[:2])
    ours = ".".join(declared().split(".")[:2])
    return "" if theirs == ours else f"тег {tag} говорит {theirs}, CONTRACT_VERSION — {ours}"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает версию и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="сверить объявленное с тегом")
    args = parser.parse_args(argv)

    try:
        number, whole = version()
        divergence = agrees()
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    print(number)
    if not whole:
        print(
            "warning: релизных тегов не видно — MAJOR.MINOR взяты из CONTRACT_VERSION, "
            "и это объявленный контракт, а не выпущенное. Подтяните теги: git fetch --tags",
            file=sys.stderr,
        )
    if divergence:
        print(f"warning: объявленная версия разошлась с тегом — {divergence}", file=sys.stderr)
    if args.check and (divergence or not whole):
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
