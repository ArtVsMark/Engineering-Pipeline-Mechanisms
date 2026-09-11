#!/usr/bin/env python3
"""Гейт правила 196: ссылка на производное не уезжает раньше самого производного.

ЧТО ЗДЕСЬ ПРЕДМЕТ. Производное — значок, картинка, отчёт — живёт ВНЕ общей
ветки: его рисует прогон и кладёт на свою ветку. Ссылка на него, приехавшая в
общую ветку первой, показывает читателю сломанную картинку и говорит неправду о
проекте ровно до первого прогона публикации, а бывает, что и дольше — прогон
может не пойти вовсе.

ПОЧЕМУ ЭТО НЕ ПРОВЕРЯЕТСЯ СУЩЕСТВОВАНИЕМ ФАЙЛА В ДЕРЕВЕ. Правило говорит прямо:
«проверкой „файл существует“ это не лечится: на изменении его и не должно быть».
Производное в дерево не коммитится — иначе оно конфликтует с источником на
каждом изменении. Спрашивать надо ПЛОЩАДКУ: нарисован ли артефакт на своей
ветке к тому моменту, когда ссылка на него въезжает в общую.

ПРЕДМЕТ — ТОЛЬКО ДОБАВЛЕННОЕ ЭТИМ ИЗМЕНЕНИЕМ. Правило о ПОРЯДКЕ, а не о
целости витрины: уже стоящие ссылки этот гейт не судит, иначе он краснел бы на
чужой работе и учил бы себя обходить (051). Ссылка на ЧУЖОЙ ресурс тоже не его
дело — там порядок не ваш
([194](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/194-a-name-is-not-proof-of-ownership.md)).

ПЛОЩАДКУ НЕ СПРОСИЛИ — ЭТО ТРЕТИЙ ИСХОД. «Не спросили» и «всё нарисовано»
снаружи одинаковы (045).

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Final

import ghrest

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Общая ветка: производное на ней не живёт по построению, и ссылки в неё —
#: обычные ссылки дерева, их держит гейт 022.
TRUNK: Final = "main"
#: Адреса производного у площадки. Форм две, и обе ведут к файлу на ветке.
DERIVED_RE: Final = re.compile(
    r"https://(?:raw\.githubusercontent\.com/(?P<rawrepo>[\w.-]+/[\w.-]+)/(?P<rawref>[\w.-]+)/(?P<rawpath>[\w./-]+)"
    r"|github\.com/(?P<repo>[\w.-]+/[\w.-]+)/(?:blob|raw)/(?P<ref>[\w.-]+)/(?P<path>[\w./-]+))"
)


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def _git(*args: str) -> str:
    """Запуск git; отказ — третий исход, а не пустой ответ."""
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def added_lines(base: str) -> list[str]:
    """Строки, которые это изменение ДОБАВИЛО: предмет правила о порядке."""
    spot = _git("merge-base", base, "HEAD").strip()
    if not spot:
        raise NotRun(f"общая точка с {base} не найдена")
    return [
        line[1:]
        for line in _git("diff", "--unified=0", f"{spot}...HEAD").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def ours(lines: list[str], repo: str) -> list[tuple[str, str]]:
    """Адреса СВОЕГО производного среди добавленного: ветка и путь на ней."""
    found: list[tuple[str, str]] = []
    for line in lines:
        for match in DERIVED_RE.finditer(line):
            where = match["rawrepo"] or match["repo"]
            ref = match["rawref"] or match["ref"]
            path = match["rawpath"] or match["path"]
            if where.lower() != repo.lower() or ref == TRUNK:
                continue
            if (ref, path) not in found:
                found.append((ref, path))
    return found


def drawn(repo: str, token: str, ref: str, path: str) -> bool:
    """Нарисован ли артефакт на своей ветке к этому моменту."""
    try:
        ghrest.request("GET", f"repos/{repo}/contents/{path}?ref={ref}", token)
    except ghrest.NotFound:
        return False
    except ghrest.TransportError as exc:
        raise NotRun(f"площадка не ответила про {ref}/{path}: {exc}") from exc
    return True


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет добавленные ссылки на производное с площадкой."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="владелец/имя")
    parser.add_argument("--base", default=None, help="точка сравнения; по умолчанию общая ветка")
    args = parser.parse_args(argv)
    base = args.base or f"origin/{os.environ.get('GITHUB_BASE_REF') or TRUNK}"

    if not args.repo:
        print(
            "гейт не отработал: репозиторий не назван: --repo или GITHUB_REPOSITORY",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    try:
        token = ghrest.token_from_env()
        added = ours(added_lines(base), args.repo)
    except (NotRun, ghrest.TransportError) as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not added:
        print("чисто: ссылок на своё производное это изменение не добавляет")
        return EXIT_OK

    try:
        missing = [(ref, path) for ref, path in added if not drawn(args.repo, token, ref, path)]
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not missing:
        print(f"чисто: производное нарисовано раньше ссылки; проверено {len(added)}")
        return EXIT_OK
    print(f"ссылок на ненарисованное производное: {len(missing)} из {len(added)}")
    for ref, path in missing:
        print(f"  {ref}/{path} — на площадке этого нет; ссылка едет ПОСЛЕ первого прогона")
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
