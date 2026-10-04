#!/usr/bin/env python3
"""Гейт: своё имя берётся у площадки, а не из памяти дерева.

ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ВНИМАНИЕ. Имя репозитория записано в дереве в нескольких
местах — значок в витрине, ответ каталогу, ссылки в документах, — и живёт оно
там до первого переименования. После него ссылки ведут в никуда, а гейты
остаются зелёными: ни один из них имя не сверяет. Замер соседа, у которого
правило родилось: после трёх переименований 28 ссылок устарели, и все восемь
гейтов прошли.

КАНОН — У ПЛОЩАДКИ, И ТОЛЬКО У НЕЁ
([172](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/172-a-shim-you-cannot-decline-needs-an-inventory.md)).
В прогоне это `GITHUB_REPOSITORY`, локально — адрес `origin`. Реестр имён,
ведомый руками, разошёлся бы с площадкой на первом же переименовании — то есть
ровно тогда, когда он нужен.

РЕГИСТР СВЕРЯЕТСЯ, А НЕ ИГНОРИРУЕТСЯ. Площадка отвечает по адресу в любом
регистре, поэтому расхождение не ломает ссылку сразу — и живёт незамеченным.
Но `full_name` у неё один, и написанное иначе однажды перестанет совпадать при
машинном сравнении: у нас самих `origin` записан строчными, а дерево несёт
`Engineering-Pipeline-Mechanisms`. Гейт называет это словом, а не молчит (045).

ЧУЖОЕ ПЕРЕИМЕНОВАНИЕ ЛОВИТСЯ ТОЖЕ, И ЭТО СКАЗАНО, А НЕ УМОЛЧАНО. Прежде здесь
стояло «чужие имена — не предмет, их переименование здесь не ловится», а второй
проход спрашивал площадку обо ВСЕХ именах дерева — то есть переименованный
каталог краснил бы гейт вопреки написанному. Прозу и поведение развели в пользу
поведения: ссылка на переименованный чужой репозиторий ломается ровно так же,
как на свой, чинится она у нас и нами, а значит это наша находка. Нашёл внешний
взгляд на #130.

РЕГИСТР — ТОЛЬКО ПРО СВОЁ. Чужое написание нам не принадлежит, и требовать от
него точного совпадения значило бы краснеть на чужой свободе (185). Поэтому
сверка регистра идёт по своему имени, а редирект — по всем.

В ВЫВОДЕ СВОЁ И ЧУЖОЕ НАЗВАНЫ ПОРОЗНЬ: чинятся они одинаково, а вот отвечает
за них разное — своё переименование сделали мы, чужое случилось с нами (154).

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Final

import ghrest
import gitcall

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Адрес вида `owner/repo` в тексте. Годится и для ссылки, и для строки данных:
#: имя ищется одним образцом, а не тремя по видам файлов (090). Поиск берёт
#: САМОЕ ЛЕВОЕ совпадение, поэтому хост `api.`/`uploads.` узнаётся целиком, а
#: не хвостом `github.com` (находка `5408fc8` на #1082).
NAME_RE: Final = re.compile(
    r"(?P<host>(?:api\.|uploads\.)?github\.com|githubusercontent\.com)"
    r"/(?P<owner>[A-Za-z0-9][\w.-]*)/(?P<repo>[A-Za-z0-9][\w.-]*)"
    r"(?:/(?P<more>[A-Za-z0-9][\w.-]*))?"
)
#: У хостов API именем репозитория считается ТОЛЬКО путь `/repos/<владелец>/<имя>`
#: (210, взгляды на #1082). Три находки по одному образцу дописывали служебные
#: сегменты по одному — `user`, `gists`, `networks` были бы следующими. Строгое
#: правило рвёт круг: всё прочее на хостах API — не имя, и площадку о нём не
#: спрашивают.
API_HOSTS: Final = frozenset({"api.github.com", "uploads.github.com"})
API_REPOS: Final = "repos"
#: Первые сегменты пути площадки, которые не владелец: страницы организаций и
#: людей, вложения, приложения. Площадка не даёт заводить учётные записи с
#: такими именами, поэтому `github.com/orgs/X` — не репозиторий «orgs/X».
#: Список назван, а не замерен целиком, и граница сказана: неизвестный здесь
#: служебный сегмент стоит один запрос к площадке, а её отказ гейт считает
#: «не ответила» и печатает числом (`stale`), — ложного красного он не даёт.
NOT_AN_OWNER: Final = frozenset(
    {
        "orgs",
        "users",
        "user-attachments",
        "apps",
        "settings",
        "sponsors",
        "marketplace",
        "topics",
        "features",
        "notifications",
        "login",
        "search",
        "collections",
        "enterprises",
    }
)
#: Каталоги образцов: имена в них — данные проверок (`o/r`, `someone/…`), а не
#: ссылки дерева. Спрашивать о них площадку — запрос квоты на каждое: замер
#: 03.10.2026 (#1065) — из 18 имён 12 жили только в `tests/`, и все двенадцать
#: были образцами. Граница названа: реальное имя, записанное ТОЛЬКО в тесте,
#: гейт не спросит; живое имя дерева стоит и в рабочем коде, и в документах.
SAMPLES: Final = ("tests/",)
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
    try:
        found = gitcall.output(["remote", "get-url", "origin"], NotRun)
    except NotRun as exc:
        raise NotRun(
            f"имя взять неоткуда: нет GITHUB_REPOSITORY и нет origin (075): {exc}"
        ) from exc
    url = found.strip().removesuffix(".git")
    parts = url.replace(":", "/").split("/")
    if len(parts) < 2:
        raise NotRun(f"адрес origin не разбирается: {url}")
    return f"{parts[-2]}/{parts[-1]}", False


def tracked(root: Path) -> list[Path]:
    """Файлы, которые ведёт git. Кеши и окружения сюда не попадают.

    Обход всего дерева читал бы `.venv` и кеши сборки — там имён репозиториев
    тысячи, и ни одно из них проект не правит. Приём тот же, что у гейта версии.
    """
    found = gitcall.output(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], NotRun, cwd=str(root)
    )
    return [root / name for name in found.split("\0") if name]


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
        if path.relative_to(root).as_posix().startswith(SAMPLES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in NAME_RE.finditer(line):
                said = name_of(match)
                if not said:
                    continue
                found.setdefault(said, []).append((path.relative_to(root), number))
    return found


def name_of(match: re.Match[str]) -> str:
    """Имя `владелец/репозиторий` из совпадения; пусто — адрес не о репозитории."""
    if match["host"] in API_HOSTS:
        if match["owner"] != API_REPOS or not match["more"]:
            return ""
        return f"{match['repo']}/{match['more']}"
    if match["owner"] in NOT_AN_OWNER:
        return ""
    return f"{match['owner']}/{match['repo']}"


def stale(said: str, token: str) -> str | None:
    """Каким именем площадка отвечает на это; пусто — совпало, ``None`` — не ответила.

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
        # «не ответила», и счёт таких печатается отдельно (взгляд на #1082).
        return None
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
    unanswered = 0
    if token:
        # ПЕРЕИМЕНОВАННОЕ ЛОВИТСЯ ТОЛЬКО ЗДЕСЬ. Старое имя не похоже на новое, и
        # сравнить их нечем; площадка же держит редирект и в ответе называет
        # `full_name`.
        for said, places in sorted(written.items()):
            # Уже названное по регистру не повторяется редиректом: находка одна,
            # и два сообщения о ней читаются как две разные (154).
            if said in named:
                continue
            asked += 1
            now = stale(said, token)
            if now is None:
                unanswered += 1
                continue
            if not now:
                continue
            where = ", ".join(f"{path}:{number}" for path, number in places[:3])
            whose = "своё" if said.lower() == repo.lower() else "чужое"
            problems.append(f"«{said}» переименован в «{now}» ({whose}): {where}")

    if problems:
        print(f"устаревших имён: {len(problems)}")
        for said in problems:
            print(f"  {said}")
        print("Имя берётся у площадки, а не из памяти дерева (172).")
        return EXIT_FOUND

    said_names = f"имён в дереве: {len(written)}"
    if unanswered:
        said_names += f"; площадка не ответила на {unanswered} из {asked} — они не сверены"
    if not token:
        print(f"чисто по своему имени; {said_names}. Редиректы не спрошены: нет токена")
    elif not exact:
        print(f"чисто; {said_names}, спрошено {asked}. Регистр не сверялся: канон из origin")
    else:
        print(f"чисто: имена совпадают с площадкой; {said_names}, спрошено {asked}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
