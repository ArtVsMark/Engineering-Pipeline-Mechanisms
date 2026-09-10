#!/usr/bin/env python3
"""Гейт: своё имя берётся у площадки, а не из памяти дерева.

ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ВНИМАНИЕ. Имя репозитория записано в дереве в нескольких
местах — значок в витрине, ответ каталогу, ссылки в документах, — и живёт оно
там до первого переименования. После него ссылки ведут в никуда, а гейты
остаются зелёными: ни один из них имя не сверяет. Замер соседа, у которого
правило родилось: после трёх переименований 28 ссылок устарели, и все восемь
гейтов прошли.

КАНОН — У ПЛОЩАДКИ, И ТОЛЬКО У НЕЁ
([172](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/172-own-name-comes-from-origin.md)).
В прогоне это `GITHUB_REPOSITORY`, локально — адрес `origin`. Реестр имён,
ведомый руками, разошёлся бы с площадкой на первом же переименовании — то есть
ровно тогда, когда он нужен.

РЕГИСТР СВЕРЯЕТСЯ, А НЕ ИГНОРИРУЕТСЯ. Площадка отвечает по адресу в любом
регистре, поэтому расхождение не ломает ссылку сразу — и живёт незамеченным.
Но `full_name` у неё один, и написанное иначе однажды перестанет совпадать при
машинном сравнении: у нас самих `origin` записан строчными, а дерево несёт
`Engineering-Pipeline-Mechanisms`. Гейт называет это словом, а не молчит (045).

ЧУЖИЕ ИМЕНА — НЕ ПРЕДМЕТ. Каталог, соседи по семье и действия площадки
называются своими адресами намеренно; их переименование — не наша забота и
здесь не ловится. Предмет — имена, указывающие на НАС.

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import ghrest

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Адрес вида `owner/repo` в тексте. Годится и для ссылки, и для строки данных:
#: имя ищется одним образцом, а не тремя по видам файлов (090).
NAME_RE: Final = re.compile(
    r"(?:github\.com|githubusercontent\.com)/(?P<owner>[A-Za-z0-9][\w.-]*)/(?P<repo>[A-Za-z0-9][\w.-]*)"
)
#: Расширения, которые читаются. Двоичное сюда не попадает: имя в нём не
#: правится, а разбор упал бы на первой же картинке.
SUFFIXES: Final = frozenset({".py", ".yml", ".yaml", ".md", ".json", ".txt", ".toml"})


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def canon() -> tuple[str, bool]:
    """Каноничное имя и признак «точно по регистру».

    ДВА ИСТОЧНИКА, И ОНИ РАЗНОГО КАЧЕСТВА. `GITHUB_REPOSITORY` в прогоне —
    это `full_name` площадки: он точен целиком, включая регистр. Адрес `origin`
    хранит то, что записал клонировавший: у нас самих там строчные буквы, тогда
    как площадка отвечает `ArtVsMark/Engineering-Pipeline-Mechanisms`.

    Поэтому локальный заход сверяет имя, но НЕ регистр, и говорит об этом. Иначе
    гейт краснел бы у каждого, кто склонировал по строчному адресу, — то есть
    учил бы не смотреть на красное (045).
    """
    said = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if said:
        return said, True
    found = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if found.returncode != 0:
        raise NotRun("имя взять неоткуда: нет GITHUB_REPOSITORY и нет origin (075)")
    url = found.stdout.strip().removesuffix(".git")
    parts = url.replace(":", "/").split("/")
    if len(parts) < 2:
        raise NotRun(f"адрес origin не разбирается: {url}")
    return f"{parts[-2]}/{parts[-1]}", False


def tracked(root: Path) -> list[Path]:
    """Файлы, которые ведёт git. Кеши и окружения сюда не попадают.

    Обход всего дерева читал бы `.venv` и кеши сборки — там имён репозиториев
    тысячи, и ни одно из них проект не правит. Приём тот же, что у гейта версии.
    """
    found = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if found.returncode != 0:
        raise NotRun(f"список файлов не получен: {found.stderr.strip()}")
    return [root / name for name in found.stdout.split("\0") if name]


def mentions(root: Path) -> dict[str, list[tuple[Path, int]]]:
    """Перепись: какое имя репозитория в каких местах записано.

    Своё и чужое собираются вместе намеренно: переименование чужого ломает
    ссылку так же, как своё, а разбирать их по принадлежности здесь нечем —
    это делает площадка ниже.
    """
    found: dict[str, list[tuple[Path, int]]] = {}
    for path in tracked(root):
        if path.suffix not in SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in NAME_RE.finditer(line):
                said = f"{match['owner']}/{match['repo']}"
                found.setdefault(said, []).append((path.relative_to(root), number))
    return found


def stale(said: str, token: str) -> str:
    """Каким именем площадка отвечает на это; пусто — совпало или не спросить.

    ПОЧЕМУ У ПЛОЩАДКИ, А НЕ СРАВНЕНИЕМ С КАНОНОМ. Переименованный репозиторий
    отвечает по СТАРОМУ адресу — площадка держит редирект, — и снаружи ссылка
    выглядит рабочей. Сравнить старое имя с новым нечем: они не похожи. Зато
    площадка в ответе называет `full_name`, и расхождение с записанным и есть
    устаревшее имя. Приём взят у соседа, у которого правило родилось: после трёх
    переименований 28 ссылок устарели, а все гейты остались зелёными (162).
    """
    try:
        answer = ghrest.request("GET", f"repos/{said}", token) or {}
    except ghrest.TransportError:
        # Отказ на ОДНОМ имени не роняет гейт: чужой репозиторий бывает закрыт
        # или удалён, и это не наша находка. Молчание тут — не «совпало», а
        # «не спросили», и об этом говорит счёт неспрошенных в выводе.
        return ""
    full = str(answer.get("full_name") or "")
    return full if full and full != said else ""


def main(argv: list[str] | None = None) -> int:
    """Точка входа: перепись имён в дереве против канона площадки."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    try:
        repo, exact = canon()
        written = mentions(args.root)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not written:
        print("гейт не отработал: имён репозиториев в дереве не нашлось (075)", file=sys.stderr)
        return EXIT_BROKEN

    problems: list[str] = []
    named: set[str] = set()
    # СВОЁ ИМЯ СВЕРЯЕТСЯ БЕЗ СЕТИ: канон уже назван площадкой через окружение
    # прогона. Регистр здесь и решает — площадка отвечает по любому, и
    # расхождение живёт незамеченным до первого машинного сравнения.
    for said, places in sorted(written.items()):
        if said.lower() != repo.lower() or said == repo or not exact:
            continue
        where = ", ".join(f"{path}:{number}" for path, number in places[:3])
        problems.append(f"«{said}» — площадка зовёт себя «{repo}»: {where}")
        named.add(said)

    token = ghrest.token_from_env()
    asked = 0
    if token:
        # ПЕРЕИМЕНОВАННОЕ ЛОВИТСЯ ТОЛЬКО ЗДЕСЬ. Старое имя не похоже на новое, и
        # сравнить их нечем; площадка же держит редирект и в ответе называет
        # `full_name`.
        for said, places in sorted(written.items()):
            asked += 1
            # Уже названное по регистру не повторяется редиректом: находка одна,
            # и два сообщения о ней читаются как две разные (154).
            if said in named:
                continue
            now = stale(said, token)
            if not now:
                continue
            where = ", ".join(f"{path}:{number}" for path, number in places[:3])
            problems.append(f"«{said}» переименован в «{now}»: {where}")

    if problems:
        print(f"устаревших имён: {len(problems)}")
        for said in problems:
            print(f"  {said}")
        print("Имя берётся у площадки, а не из памяти дерева (172).")
        return EXIT_FOUND

    said_names = f"имён в дереве: {len(written)}"
    if not token:
        print(f"чисто по своему имени; {said_names}. Редиректы не спрошены: нет токена")
    elif not exact:
        print(f"чисто; {said_names}, спрошено {asked}. Регистр не сверялся: канон из origin")
    else:
        print(f"чисто: имена совпадают с площадкой; {said_names}, спрошено {asked}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
