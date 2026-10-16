#!/usr/bin/env python3
"""Перехват подъёма закреплённого действия: Dependabot — датчик, конвейер — исполнитель (#1387).

ЗАЧЕМ ПЕРЕХВАТ, А НЕ ИЗМЕНЕНИЕ БОТА. Замер 15.10.2026: изменение Dependabot
конвейер напрямую не пропускает — `pr-meta` (нет зоны и связи), `journal`
(нет фрагмента), `attribution` (автор `dependabot[bot]` не объявлен, коммит
бота остаётся в диапазоне, что бы ни положили поверх), а у действий каталога
ещё и `test` (`origin` в `.rules/bindings.json` не поднят). Пропустить бота
значило бы ослабить три обязательных гейта ради чужого формата. Решение
владельца 15.10.2026: изменение бота — только сигнал «вышла версия»; подъём
делает этот механизм на свежей общей ветке, и он идёт обычным путём —
веткой `agent/`, очередью, гейтами и взглядом, без единого исключения.

ЧТО ДЕЛАЕТ. Берёт открытые изменения `dependabot[bot]`, из каждого — ТОЛЬКО
заголовок «Bump <действие> from <старая> to <новая>». Код из ветки бота не
читается и не исполняется: правку делает этот скрипт на `origin/main`.

1. Тег новой версии и его коммит спрашиваются у площадки (`v<версия>` или
   `<версия>`): пин по sha получает sha этого коммита и комментарий с тегом,
   пин по тегу — тег.
2. Поднимаются ВСЕ строки `uses:` этого действия в прогонах разом: гейт
   «одна версия механизма на дерево» иначе покраснел бы на половинном
   подъёме. Адрес общей ветки (`@main`) не трогается — это не версия.
3. У действий каталога в том же коммите правится `origin` в
   `.rules/bindings.json`: тег вызова и тег в ответе сверяет набор.
4. Фрагмент журнала, коммит (автор — владелец, соавтор — подпись механизма,
   как у выпуска), толчок ветки `agent/deps-…` токеном владельца: её
   изменение открывает `agent-pr`.
5. Изменение бота закрывается со ссылкой на ветку. Эту версию бот больше не
   предлагает, следующую — предложит.

Повтор безопасен: ветка уже есть на площадке — подъём не повторяется, изменение
бота только закрывается.

Исходы: ``0`` перехвачено или нечего · ``1`` изменение бота не разобрано
(заголовок не той формы, тега нет, строк нет) — находка для человека:
изменение бота остаётся открытым, а прогон краснеет, и его видит `main-red`
(взгляд на #1397) · ``2`` не отработал.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import drift
import ghrest
import gitcall
import paths
import report

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Чьи изменения перехватываются.
BOT: Final = "dependabot[bot]"
#: Заголовок изменения бота по умолчанию — единственное, что из него берётся.
TITLE_RE: Final = re.compile(
    r"^Bump (?P<dep>[\w.-]+/[\w.-]+)(?:/\S+)? from (?P<old>\S+) to (?P<new>\S+)$"
)
#: Ссылка на версию, которую поднимают: тег вида `v1`, `v1.2`, `1.2.3`.
VERSION_RE: Final = re.compile(r"^v?\d+(?:\.\d+){0,2}$")
#: Пин по коммиту — образец один на проект, у дрейфа, который сверяет те же пины (214).
SHA_RE: Final = drift.HASH_RE
#: Подпись механизма — та же, что у коммита выпуска, и объявлена в `paths.AUTHORS`.
CO_AUTHOR: Final = "Engineering Pipeline Mechanisms <noreply@github.com>"
#: Задача, к которой привязан каждый подъём: план работ, он открыт всегда.
REFS: Final = "Refs #639"
#: Где лежат строки `uses:` — прогоны. Своих действий (`.github/actions`) в
#: дереве нет; появятся — их каталог добавится сюда, а не поиском вниз.
WORKFLOWS: Final = paths.WORKFLOWS


class NotRun(RuntimeError):
    """Механизм не отработал: площадка или git отказали (075)."""


class Refused(RuntimeError):
    """Изменение бота не разобрано — находка для человека, а не поломка механизма."""


@dataclass(frozen=True, slots=True)
class Bump:
    """Сигнал бота: какое действие и до какой версии поднять."""

    number: int
    dep: str
    old: str
    new: str


def parse(change: dict[str, Any]) -> Bump:
    """Сигнал из изменения бота — по одному заголовку; иная форма — отказ с причиной."""
    title = str(change.get("title") or "").strip()
    found = TITLE_RE.match(title)
    if not found or not VERSION_RE.match(found["new"]):
        raise Refused(
            f"#{change.get('number')}: заголовок «{title}» не той формы — разбирать нечего"
        )
    return Bump(int(change["number"]), found["dep"], found["old"], found["new"])


def slug(text: str) -> str:
    """Часть имени ветки: строчные латинские буквы, цифры и дефисы."""
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")


def branch_of(dep: str, tag: str) -> str:
    """Ветка подъёма: имя — по предмету, приставка `agent/` — переключатель конвейера (003)."""
    return f"agent/deps-{slug(dep)}-{slug(tag)}"


def uses_re(dep: str) -> re.Pattern[str]:
    """Строка `uses:` этого действия: адрес, ссылка и хвост строки."""
    return re.compile(
        rf"(?P<head>uses:\s*[\"']?{re.escape(dep)}(?:/[^@\s\"']*)?@)"
        rf"(?P<ref>[^\s\"'#]+)(?P<tail>[\"']?.*)$",
        re.IGNORECASE,
    )


def bump_line(line: str, dep: str, tag: str, sha: str) -> str:
    """Строка с поднятой ссылкой; ссылка не версия и не sha (`@main`) — строка как была."""
    found = uses_re(dep).search(line)
    if not found:
        return line
    ref = found["ref"]
    if SHA_RE.match(ref):
        tail = re.sub(r"#\s*\S+", f"# {tag}", found["tail"], count=1)
        return line[: found.start()] + found["head"] + sha + tail
    if VERSION_RE.match(ref):
        return line[: found.start()] + found["head"] + tag + found["tail"]
    return line


def bump_text(text: str, dep: str, tag: str, sha: str) -> str:
    """Текст файла с поднятыми строками `uses:` этого действия."""
    return "\n".join(bump_line(line, dep, tag, sha) for line in text.split("\n"))


def bump_origins(text: str, dep: str, tag: str) -> str:
    """Ответы каталога: тег в `origin` вызванного действия этого репозитория."""
    pattern = re.compile(rf"(\"origin\":\s*\"{re.escape(dep)}:[^\"@]*@)([^\"]+)(\")", re.IGNORECASE)
    return pattern.sub(lambda found: found[1] + tag + found[3], text)


def plan(root: Path, dep: str, tag: str, sha: str) -> dict[Path, str]:
    """Подъём действия во всём дереве: файл от корня → новый текст. Дерево не трогается."""
    planned: dict[Path, str] = {}
    for path in sorted((root / WORKFLOWS).glob("*.yml")):
        before = path.read_text(encoding="utf-8")
        after = bump_text(before, dep, tag, sha)
        if after != before:
            planned[path.relative_to(root)] = after
    bindings = root / paths.BINDINGS
    if planned and bindings.is_file():
        before = bindings.read_text(encoding="utf-8")
        after = bump_origins(before, dep, tag)
        if after != before:
            planned[paths.BINDINGS] = after
    return planned


def resolve(dep: str, new: str, token: str) -> tuple[str, str]:
    """Тег новой версии и sha его коммита — у площадки; тега нет — отказ с причиной."""
    # Сначала с `v`: так помечены выпуски почти у всех действий, а голый номер
    # у площадки бывает и именем ветки.
    for tag in dict.fromkeys([new if new.startswith("v") else f"v{new}", new.removeprefix("v")]):
        try:
            said = ghrest.request("GET", f"repos/{dep}/commits/{tag}", token) or {}
        except ghrest.NotFound:
            continue
        except ghrest.TransportError as exc:
            raise NotRun(f"{dep}@{tag}: площадка не ответила — {exc}") from exc
        sha = str(said.get("sha") or "")
        if SHA_RE.match(sha):
            return tag, sha
    raise Refused(f"{dep}: тега версии «{new}» у площадки нет — поднимать не на что")


def fragment(dep: str, tag: str, number: int) -> str:
    """Фрагмент журнала подъёма."""
    return (
        f"### Поднят `{dep}` до `{tag}`\n\n"
        f"Закреплённое действие поднято до новой версии во всём дереве разом. "
        f"Сигнал — изменение Dependabot #{number}, подъём сделал перехват "
        f"`scripts/deps_intercept.py` на общей ветке.\n\n#1387\n"
    )


def message(dep: str, tag: str, number: int) -> str:
    """Тело коммита подъёма: что, откуда сигнал, связь и подпись механизма."""
    return (
        f"Поднят {dep} до {tag}\n\n"
        f"Сигнал — изменение Dependabot #{number}; оно закрыто, подъём идёт этим\n"
        f"изменением обычным путём. Подняты все строки uses: этого действия разом.\n\n"
        f"{REFS}\n\nCo-Authored-By: {CO_AUTHOR}\n"
    )


def git(root: Path, *args: str) -> str:
    """git в корне дерева; отказ — «не отработал»."""
    return gitcall.output(args, NotRun, cwd=str(root))


def intercept(root: Path, repo: str, token: str, bump: Bump, *, dry_run: bool) -> str:
    """Один перехват: подъём веткой `agent/` и закрытие изменения бота. Отдаёт ветку."""
    tag, sha = resolve(bump.dep, bump.new, token)
    branch = branch_of(bump.dep, tag)
    if git(root, "ls-remote", "--heads", "origin", branch).strip():
        print(f"#{bump.number}: ветка {branch} уже есть — подъём не повторяется")
    else:
        # Сухой заход считает подъём по дереву как есть и ничего не переключает:
        # на машине человека смена ветки была бы правкой, которой не просили.
        if not dry_run:
            git(root, "fetch", "--quiet", "origin", paths.TRUNK)
            git(root, "checkout", "--quiet", "--force", "-B", branch, f"origin/{paths.TRUNK}")
        planned = plan(root, bump.dep, tag, sha)
        if not planned:
            raise Refused(
                f"#{bump.number}: строк `uses:` {bump.dep} в дереве нет — поднимать нечего"
            )
        note = paths.FRAGMENTS / f"deps-{slug(bump.dep)}-{slug(tag)}.changed.md"
        planned[note] = fragment(bump.dep, tag, bump.number)
        print(f"#{bump.number}: {bump.dep} → {tag} ({sha[:7]}), файлов: {len(planned)}")
        if dry_run:
            return branch
        for path, text in planned.items():
            (root / path).write_text(text, encoding="utf-8")
        git(root, "add", "--", *[str(path) for path in planned])
        git(root, "commit", "--quiet", "-m", message(bump.dep, tag, bump.number))
        git(root, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
    if not dry_run:
        said = (
            f"Подъём перехвачен конвейером: ветка `{branch}`, изменение по ней откроет "
            "`agent-pr`. Этот сигнал закрывается — подъём идёт обычным путём (#1387)."
        )
        ghrest.request("POST", f"repos/{repo}/issues/{bump.number}/comments", token, {"body": said})
        ghrest.request("PATCH", f"repos/{repo}/pulls/{bump.number}", token, {"state": "closed"})
    return branch


def signals(repo: str, token: str) -> list[dict[str, Any]]:
    """Открытые изменения бота."""
    return [
        change
        for change in ghrest.paginate(f"repos/{repo}/pulls?state=open", token)
        if str((change.get("user") or {}).get("login") or "") == BOT
    ]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: перехватывает каждый сигнал бота по очереди."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="толкнуть ветку и закрыть сигнал")
    args = parser.parse_args(argv)
    token = ghrest.token_from_env()
    if not args.repo or not token:
        print("не отработал: нет имени проекта или токена", file=sys.stderr)
        return EXIT_BROKEN
    report.announce(not args.apply)
    refused: list[str] = []
    try:
        found = signals(args.repo, token)
        print(f"сигналов {BOT}: {len(found)}")
        for change in found:
            try:
                intercept(args.root, args.repo, token, parse(change), dry_run=not args.apply)
            except Refused as exc:
                refused.append(str(exc))
                print(f"не разобрано: {exc}")
            finally:
                if args.apply:
                    git(
                        args.root,
                        "checkout",
                        "--quiet",
                        "--force",
                        "--detach",
                        f"origin/{paths.TRUNK}",
                    )
    except (NotRun, ghrest.TransportError, OSError) as exc:
        print(f"не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_FOUND if refused else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
