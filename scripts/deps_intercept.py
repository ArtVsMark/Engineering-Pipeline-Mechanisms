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
заголовок «Bump <действие> from <старая> to <новая>», с необязательной
приставкой `<тип>(<область>)!: ` и словом `Bump` или `bump` — так бот пишет
его в истории conventional commits (#1751). Код из ветки бота не
читается и не исполняется: правку делает этот скрипт на `origin/main`.

1. Тег новой версии и его коммит спрашиваются у площадки (`v<версия>` или
   `<версия>`): пин по sha получает sha этого коммита и комментарий с тегом,
   пин по тегу — тег.
2. Поднимаются ВСЕ строки `uses:` этого действия в прогонах разом: гейт
   «одна версия механизма на дерево» иначе покраснел бы на половинном
   подъёме. Адрес общей ветки (`@main`) не трогается — это не версия.
3. У действий каталога в том же коммите правится `origin` в
   `.rules/bindings.json`: тег вызова и тег в ответе сверяет набор. У действия
   со слежкой (`.rules/vendor-watch.json`, #1522) прежде подъёма сравнивается
   объявленный файл поставщика между `read_at` и новым коммитом: не тронут —
   `read_at` сдвигается тем же коммитом, тронут — отказ с адресом файла. У
   слежки с `ignore` (#1689) тронутый файл сверяется на обоих коммитах без
   строк-шума: разошлись только они — файл считается не тронутым.
4. Фрагмент журнала, коммит (автор — владелец токена, соавтор — подпись
   механизма, как у выпуска; связь — план работ проекта, найденный по
   маркеру), толчок ветки `agent/deps-…` тем же токеном: её изменение
   открывает `agent-pr`.

ИДЁТ И У ПОТРЕБИТЕЛЯ (#1387, решение владельца 17.10.2026): общим шагом
`step-deps-intercept.yml`. Поэтому ни номера задачи, ни имени владельца в коде
перехвата нет — оба спрашиваются у площадки того проекта, где идёт заход.
5. Изменение бота закрывается со ссылкой на ветку. Эту версию бот больше не
   предлагает, следующую — предложит.

Повтор безопасен: ветка уже есть на площадке — подъём не повторяется, изменение
бота только закрывается.

РЕЖИМ `--self <тег>` — ТОТ ЖЕ ПОДЪЁМ, НО СИГНАЛ — ТЕГ ВЫПУСКА (#1387). Его зовёт
`step-release.yml` последним шагом: все вызовы своих же шагов по тегу
поднимаются до нового тега веткой `agent/deps-self-<тег>`. Dependabot ссылки
репозитория на самого себя не предлагает. Исходы режима: ``0`` поднято или
нечего · ``2`` не отработал (дерево с незакоммиченными правками — тоже: заход
переключает ветку и стёр бы их).

Исходы: ``0`` перехвачено или нечего · ``1`` изменение бота не разобрано
(заголовок не той формы, тега нет, строк нет) — находка для человека:
изменение бота остаётся открытым, а прогон краснеет, и его видит `main-red`
(взгляд на #1397) · ``2`` не отработал.
"""

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import drift
import findings
import ghrest
import gitcall
import main_guard
import paths
import pipeline_checks as policy
import report

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Чьи изменения перехватываются.
BOT: Final = "dependabot[bot]"
#: Заголовок изменения бота по умолчанию — единственное, что из него берётся.
#: ПРИСТАВКА НЕОБЯЗАТЕЛЬНА (#1751): бот подстраивает заголовок под историю
#: коммитов репозитория и пишет `build(deps): Bump …` там, где история в стиле
#: conventional commits. Замер 29.10.2026: заголовок #1740 пришёл с ней, и
#: перехват отказал «не той формы».
TITLE_RE: Final = re.compile(
    r"^(?:\w+(?:\([\w.-]+\))?!?: )?"
    r"[Bb]ump (?P<dep>[\w.-]+/[\w.-]+)(?:/\S+)? from (?P<old>\S+) to (?P<new>\S+)$"
)
#: Ссылка на версию, которую поднимают: тег вида `v1`, `v1.2`, `1.2.3`.
VERSION_RE: Final = re.compile(r"^v?\d+(?:\.\d+){0,2}$")
#: Пин по коммиту — образец один на проект, у дрейфа, который сверяет те же пины (214).
SHA_RE: Final = drift.HASH_RE
#: Подпись механизма — та же, что у коммита выпуска, и объявлена в `paths.AUTHORS`.
CO_AUTHOR: Final = "Engineering Pipeline Mechanisms <noreply@github.com>"
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
        rf"(?P<head>{policy.USES_HEAD}{re.escape(dep)}(?:/[^@\s\"']*)?@)"
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


def uses_lines(root: Path, dep: str) -> int:
    """Сколько строк `uses:` этого действия в прогонах дерева — поднятых или нет."""
    found = uses_re(dep)
    return sum(
        1
        for path in sorted((root / WORKFLOWS).glob("*.yml"))
        for line in path.read_text(encoding="utf-8").split("\n")
        if found.search(line)
    )


def at_root(key: str, root: Path) -> Path:
    """Путь данных проекта по таблице дерева `root` (#1632); битый раздел — `NotRun`."""
    try:
        return policy.project_path(key, root)
    except paths.BadPaths as exc:
        raise NotRun(str(exc)) from exc


def plan(root: Path, dep: str, tag: str, sha: str) -> dict[Path, str]:
    """Подъём действия во всём дереве: файл от корня → новый текст. Дерево не трогается."""
    planned: dict[Path, str] = {}
    for path in sorted((root / WORKFLOWS).glob("*.yml")):
        before = path.read_text(encoding="utf-8")
        after = bump_text(before, dep, tag, sha)
        if after != before:
            planned[path.relative_to(root)] = after
    answer = at_root("bindings", root)
    bindings = root / answer
    if planned and bindings.is_file():
        before = bindings.read_text(encoding="utf-8")
        after = bump_origins(before, dep, tag)
        if after != before:
            planned[answer] = after
    return planned


#: Сколько файлов площадка отдаёт в ответе `compare`: дальше список обрезан
#: молча, и отсутствие пути в нём «не тронут» уже не доказывает.
COMPARE_FILES: Final = 300
#: Исходы `compare`, которые площадка объявляет; иной — ответ не разобран.
COMPARE_STATES: Final = frozenset({"identical", "ahead", "behind", "diverged"})


def watches(root: Path, dep: str) -> list[dict[str, Any]]:
    """Слежки за файлами поставщика у этого действия; файла объявлений нет — пусто.

    У потребителя файла нет, и подъём идёт как прежде: слежку объявляет тот,
    у кого есть знание, снятое с кода поставщика.
    """
    watch = at_root("vendor-watch", root)
    path = root / watch
    if not path.is_file():
        return []
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotRun(f"{watch}: не читается — {exc}") from exc
    found = said.get("watched") if isinstance(said, dict) else None
    if not isinstance(found, list) or not all(isinstance(one, dict) for one in found):
        raise NotRun(f"{watch}: `watched` — не список записей")
    return [one for one in found if str(one.get("dep") or "").lower() == dep.lower()]


def touched(dep: str, since: str, sha: str, token: str) -> set[str]:
    """Файлы поставщика, тронутые от `since` до `sha`, — по `compare` площадки, только чтением.

    ТРИ ИСХОДА, А НЕ ДВА (075). Новый коммит не потомок прежнего — что тронуто,
    сравнением не узнать, и это находка для человека. Ответ без списка файлов
    или со списком на пределе — заход не отработал: «пути в списке нет» там
    не значит «не тронут».
    """
    try:
        said = ghrest.request("GET", f"repos/{dep}/compare/{since}...{sha}", token) or {}
    except ghrest.NotFound as exc:
        raise Refused(
            f"{dep}: сравнить {since[:7]}...{sha[:7]} нечем — коммита у поставщика нет"
        ) from exc
    except ghrest.TransportError as exc:
        raise NotRun(f"{dep}: сравнение {since[:7]}...{sha[:7]} не прочитано — {exc}") from exc
    status = said.get("status") if isinstance(said, dict) else None
    if status not in COMPARE_STATES:
        raise NotRun(f"{dep}: сравнение {since[:7]}...{sha[:7]} без исхода («{status}»)")
    if status == "identical":
        return set()
    if status != "ahead":
        raise Refused(
            f"{dep}: {sha[:7]} не потомок {since[:7]} (исход «{status}») — "
            "что тронуто у поставщика, сравнением не узнать"
        )
    files = said.get("files")
    if not isinstance(files, list) or len(files) >= COMPARE_FILES:
        raise NotRun(
            f"{dep}: список файлов {since[:7]}...{sha[:7]} неполон — «не тронут» не доказан"
        )
    if not all(isinstance(one, dict) for one in files):
        raise NotRun(f"{dep}: список файлов {since[:7]}...{sha[:7]} не той формы")
    return {
        str(name)
        for one in files
        for name in (one.get("filename"), one.get("previous_filename"))
        if name
    }


def vendor_text(dep: str, path: str, ref: str, token: str) -> str:
    """Файл поставщика на коммите `ref` — по `contents` площадки, только чтением.

    Ответ без текста — файл больше предела площадки, каталог, не той формы —
    это «не прочитано», а не пустой файл: пустота совпала бы с чем угодно (039).
    Путь экранируется по звеньям, `ref` — целиком: `#`, `?` или пробел в них
    давали ложный «не отработал» вместо чтения (взгляд на #1693, `25dd0f2`).
    """
    where = "/".join(ghrest.quote(one) for one in path.split("/"))
    try:
        said = ghrest.request("GET", f"repos/{dep}/contents/{where}?ref={ghrest.quote(ref)}", token)
    except ghrest.NotFound as exc:
        raise Refused(f"{dep}: файла {path} на {ref[:7]} у поставщика нет") from exc
    except ghrest.TransportError as exc:
        raise NotRun(f"{dep}: {path} на {ref[:7]} не прочитан — {exc}") from exc
    if not isinstance(said, dict) or said.get("encoding") != "base64":
        raise NotRun(f"{dep}: {path} на {ref[:7]} — ответ без текста файла")
    try:
        return base64.b64decode(str(said.get("content") or ""), validate=False).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise NotRun(f"{dep}: {path} на {ref[:7]} не разобран — {exc}") from exc


def ignored_pattern(one: dict[str, Any], watch: Path) -> re.Pattern[str] | None:
    """Образец строк-шума слежки (#1689); поля нет — `None`, негодное — заход не отработал."""
    said = one.get("ignore")
    if said is None:
        return None
    if not isinstance(said, str) or not said:
        raise NotRun(f"{watch}: у слежки {one.get('path')} `ignore` — не строка образца")
    try:
        return re.compile(said)
    except re.error as exc:
        raise NotRun(f"{watch}: у слежки {one.get('path')} `ignore` не разобран — {exc}") from exc


def only_noise(
    dep: str, path: str, since: str, sha: str, noise: re.Pattern[str], token: str
) -> bool:
    """Разошлись ли версии файла ТОЛЬКО строками-шумом (#1689).

    Сравнивается файл целиком без строк, совпавших с образцом, — а не одни
    строки предмета: условие вызова может не нести его имени, и слежка за
    именем пропустила бы смену условия. Образец, не нашедший ни одной строки
    ни в одной версии, — отказ: поле мертво, и «совпало» ничего не доказывает (075).
    """
    before = vendor_text(dep, path, since, token).splitlines()
    after = vendor_text(dep, path, sha, token).splitlines()
    if not any(noise.search(line) for line in (*before, *after)):
        raise Refused(
            f"{dep}: образец `ignore` слежки {path} не нашёл ни одной строки на "
            f"{since[:7]} и {sha[:7]} — перечитать слежку"
        )
    kept = [[line for line in lines if not noise.search(line)] for lines in (before, after)]
    return kept[0] == kept[1]


def follow(root: Path, dep: str, sha: str, token: str) -> dict[Path, str]:
    """Слежки этого действия: файл не тронут — `read_at` сдвигается до `sha`, тронут — отказ.

    Отдаёт правку файла объявлений для плана подъёма; слежки нет или она уже
    на `sha` — пусто. У слежки с `ignore` тронутый файл сверяется без
    строк-шума (`only_noise`, #1689): разошлись только они — файл не тронут.

    СНАЧАЛА СУДЯТСЯ ВСЕ СЛЕЖКИ, ПОТОМ СДВИГАЕТСЯ (взгляд на #1524). Слежки
    одного действия с одним `read_at` естественны — знания сняты с одного
    закрепления, — и сдвиг по первой убирал строку второй: она падала «сдвигать
    нечего». Теперь `compare` спрашивается один раз на `read_at`, а сдвиг идёт,
    только когда не тронут ни один файл.
    """
    watch = at_root("vendor-watch", root)
    found = watches(root, dep)
    if not found:
        return {}
    seen: dict[str, set[str]] = {}
    for one in found:
        since, path = str(one.get("read_at") or ""), str(one.get("path") or "")
        if not SHA_RE.match(since) or not path:
            raise NotRun(f"{watch}: у слежки {dep} нет `read_at` по sha или `path`")
        if since == sha:
            continue
        if since not in seen:
            seen[since] = touched(dep, since, sha, token)
        noise = ignored_pattern(one, watch)
        if path in seen[since] and not (
            noise is not None and only_noise(dep, path, since, sha, noise, token)
        ):
            raise Refused(
                f"{dep}: между {since[:7]} и {sha[:7]} у поставщика тронут {path} — "
                f"перечитать {one.get('by')} по https://github.com/{dep}/blob/{sha}/{path} "
                f"и сдвинуть `read_at` в {watch}"
            )
    before = (root / watch).read_text(encoding="utf-8")
    after = before
    for since in seen:
        old, new = f'"read_at": "{since}"', f'"read_at": "{sha}"'
        if old not in after:
            raise NotRun(f"{watch}: строки {old} нет — сдвигать нечего")
        after = after.replace(old, new)
    return {watch: after} if after != before else {}


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


def plan_number(repo: str, token: str) -> int:
    """Номер плана работ проекта — по его маркеру: к плану привязан каждый подъём.

    НЕ ЛИТЕРАЛОМ (#1387, решение владельца 17.10.2026): перехват стал общим
    шагом, и номер нашего плана у потребителя назвал бы его чужую задачу. План
    ищется тем же маркером, по которому его находит сборщик плана. Плана нет —
    «не отработал», а не подъём без связи: связь с задачей обязательна
    (`pr-meta`), и такой подъём покраснел бы уже после толчка.
    """
    try:
        number, _ = findings.live_issue(repo, token, findings.PLAN_MARKER)
    except ghrest.TransportError as exc:
        raise NotRun(f"план работ не прочитан: {exc}") from exc
    if number is None:
        raise NotRun(
            "плана работ нет — подъёму не к чему привязаться; план заводит прогон work-plan"
        )
    return number


def identity(token: str) -> tuple[str, str]:
    """Имя и почта владельца токена — ими подписан коммит подъёма (131).

    Прежде прогон вписывал владельца буквами, и у потребителя автором стал бы
    чужой человек. Спрашивается сам токен: он владельца, и толкает им же.
    Почта — служебная почта площадки, той же формы, что у выпуска.
    """
    try:
        said = ghrest.request("GET", "user", token) or {}
    except ghrest.TransportError as exc:
        raise NotRun(f"владелец токена не назван: {exc}") from exc
    login, number = said.get("login"), said.get("id")
    if not isinstance(login, str) or not login or not isinstance(number, int):
        raise NotRun("площадка не назвала владельца токена — подписать подъём некем")
    return login, f"{number}+{login}@users.noreply.github.com"


def fragment(dep: str, tag: str, number: int, plan: int) -> str:
    """Фрагмент журнала подъёма; ссылка — на план работ проекта."""
    return (
        f"### Поднят `{dep}` до `{tag}`\n\n"
        f"Закреплённое действие поднято до новой версии во всём дереве разом. "
        f"Сигнал — изменение Dependabot #{number}, подъём сделал перехват "
        f"механизмов на общей ветке.\n\n#{plan}\n"
    )


def message(dep: str, tag: str, number: int, plan: int) -> str:
    """Тело коммита подъёма: что, откуда сигнал, связь с планом и подпись механизма."""
    return (
        f"Поднят {dep} до {tag}\n\n"
        f"Сигнал — изменение Dependabot #{number}; оно закрыто, подъём идёт этим\n"
        f"изменением обычным путём. Подняты все строки uses: этого действия разом.\n\n"
        f"Refs #{plan}\n\nCo-Authored-By: {CO_AUTHOR}\n"
    )


def git(root: Path, *args: str) -> str:
    """git в корне дерева; отказ — «не отработал»."""
    return gitcall.output(args, NotRun, cwd=str(root))


def switch_clean(root: Path, branch: str) -> None:
    """Режет ветку от общей, если в дереве нечего стереть; иначе — отказ.

    Оба захода, режущих ветку, — перехват и подъём своих шагов — идут и на
    машине человека, поэтому проверка у них одна, а не у каждого своя
    (`7f52cb1`, правило 195). ПЕРЕКЛЮЧЕНИЕ БЕЗ `--force` (взгляд на #1434):
    третья находка по одному месту — сносу правок сменой ветки — чинится
    классом, а не очередным вызовом (210). Чистому дереву `--force` не нужен, а
    правку, которую проверка выше не увидела, git при смене ветки откажется
    стирать сам. Принудительную смену ветки в любом механизме судит
    `tests/test_git_keeps_the_tree.py`.
    """
    if git(root, "status", "--porcelain").strip():
        raise NotRun("в дереве незакоммиченные правки — заход переключает ветку и стёр бы их")
    git(root, "checkout", "--quiet", "-B", branch, f"origin/{paths.TRUNK}")


def intercept(
    root: Path,
    repo: str,
    token: str,
    bump: Bump,
    *,
    dry_run: bool,
    plan_issue: int,
    who: tuple[str, str] | None = None,
) -> str:
    """Один перехват: подъём веткой `agent/` и закрытие изменения бота. Отдаёт ветку.

    `plan_issue` — номер плана работ (`plan_number`), `who` — подпись коммита
    (`identity`); без неё заход с записью не идёт.
    """
    tag, sha = resolve(bump.dep, bump.new, token)
    branch = branch_of(bump.dep, tag)
    if git(root, "ls-remote", "--heads", "origin", branch).strip():
        print(f"#{bump.number}: ветка {branch} уже есть — подъём не повторяется")
    else:
        # Сухой заход считает подъём по дереву как есть и ничего не переключает:
        # на машине человека смена ветки была бы правкой, которой не просили.
        if not dry_run:
            git(root, "fetch", "--quiet", "origin", paths.TRUNK)
            switch_clean(root, branch)
        planned = plan(root, bump.dep, tag, sha)
        if not planned:
            # Пустой план — два разных случая (взгляд на #1397): строк нет вовсе,
            # или они уже на этой версии — ветку подъёма слили, а сигнал открыт.
            lines = uses_lines(root, bump.dep)
            why = (
                f"строки `uses:` {bump.dep} в дереве есть ({lines}), но поднимать нечего: "
                f"они уже на {tag} или прибиты не версией"
                if lines
                else f"строк `uses:` {bump.dep} в дереве нет — поднимать нечего"
            )
            raise Refused(f"#{bump.number}: {why}")
        planned.update(follow(root, bump.dep, sha, token))
        note = paths.FRAGMENTS / f"deps-{slug(bump.dep)}-{slug(tag)}.changed.md"
        planned[note] = fragment(bump.dep, tag, bump.number, plan_issue)
        print(f"#{bump.number}: {bump.dep} → {tag} ({sha[:7]}), файлов: {len(planned)}")
        if dry_run:
            return branch
        if who is None:
            raise NotRun("подписи коммита нет — подъём с записью без владельца не идёт (131)")
        for path, text in planned.items():
            (root / path).write_text(text, encoding="utf-8")
        git(root, "add", "--", *[str(path) for path in planned])
        name, email = who
        git(
            root,
            "-c",
            f"user.name={name}",
            "-c",
            f"user.email={email}",
            "commit",
            "--quiet",
            "-m",
            message(bump.dep, tag, bump.number, plan_issue),
        )
        git(root, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
    if not dry_run:
        said = (
            f"Подъём перехвачен конвейером: ветка `{branch}`, изменение по ней откроет "
            "`agent-pr`. Этот сигнал закрывается — подъём идёт обычным путём."
        )
        ghrest.request("POST", f"repos/{repo}/issues/{bump.number}/comments", token, {"body": said})
        ghrest.request("PATCH", f"repos/{repo}/pulls/{bump.number}", token, {"state": "closed"})
    return branch


#: Ветка подъёма своих шагов после выпуска: имя по предмету, а не по
#: адресу репозитория — адрес длинный и у потребителя свой (189).
SELF_BRANCH: Final = "agent/deps-self-{tag}"


def self_fragment(tag: str, touched: list[Path], plan_issue: int) -> str:
    """Фрагмент журнала подъёма своих шагов: тронутое — по плану подъёма, ссылка — план работ."""
    names = ", ".join(f"`{one.as_posix()}`" for one in sorted(touched))
    return (
        f"> **Потребителю безразлично:** поднята прибивка своих шагов в прогонах "
        f"поставщика ({names}) до `{tag}`; отдаваемые шаги не тронуты.\n\n"
        f"### Свои шаги подняты до `{tag}`\n\n"
        f"Выпуск `{tag}` сам поднял вызовы своих шагов по тегу: Dependabot ссылки "
        f"репозитория на самого себя не предлагает.\n\n#{plan_issue}\n"
    )


def calls_itself(root: Path, repo: str) -> bool:
    """Зовёт ли общая ветка свои шаги по адресу репозитория — до переключения ветки.

    `git grep` отвечает кодом: 0 — нашлось, 1 — нет, прочее — отказ. Код читается
    здесь, поэтому форма своя, а не `gitcall.output` (тот отказывает на любом
    ненуле); отсутствие git — третий исход, а не «не зовёт».
    """
    try:
        said = subprocess.run(
            [
                "git",
                "grep",
                "-q",
                "-i",
                "-F",
                f"{repo}/",
                f"origin/{paths.TRUNK}",
                "--",
                WORKFLOWS.as_posix(),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=gitcall.LOCAL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotRun(f"git не запустился: {exc}") from exc
    if said.returncode not in (0, 1):
        raise NotRun(f"git grep не ответил (код {said.returncode}): {said.stderr.strip()}")
    return said.returncode == 0


def self_bump(root: Path, repo: str, tag: str, *, dry_run: bool, token: str = "") -> str:
    """Подъём своих шагов до тега выпуска веткой `agent/`. Отдаёт ветку; пусто — нечего.

    ЗАЧЕМ (#1387). Проба передачи зовёт наши шаги по тегу, как потребитель.
    Dependabot подъёма ссылок репозитория на самого себя не предлагает: замер
    15–16.10.2026 — сутки после `v1.6.0`, сигнала нет. Решение владельца
    16.10.2026: пробу поднимает сам выпуск, тем же путём, что перехват, —
    веткой `agent/` и обычной очередью.

    ФОРК ПОСТАВЩИКА — ТОЖЕ НОЛЬ, И ЭТО ВЕРНО (взгляд на #1421). Его проба зовёт
    верхний репозиторий, а не себя: теги, к которым она прибита, — выпуски
    верхнего, и поднимать их выпуском форка значило бы прибить пробу к тегу,
    которого у верхнего нет.

    У ПОТРЕБИТЕЛЯ ЭТО НОЛЬ, А НЕ ОТКАЗ. Свой репозиторий по тегу он не зовёт —
    его вызовы ведут к поставщику, — и строк к подъёму нет. Это законная
    пустота, и выпуск потребителя от неё не краснеет (154).
    """
    branch = SELF_BRANCH.format(tag=slug(tag))
    if git(root, "ls-remote", "--heads", "origin", branch).strip():
        print(f"ветка {branch} уже есть — подъём не повторяется")
        return branch
    sha = git(root, "rev-list", "-n", "1", tag).strip()
    if not dry_run:
        # ВЕТКА ПЕРЕКЛЮЧАЕТСЯ, ТОЛЬКО КОГДА ЕСТЬ ЧТО ПОДНИМАТЬ И НЕЧЕГО СТЕРЕТЬ
        # (взгляд на #1421). Ручная доводка идёт на машине человека: `--force`
        # молча снёс бы его незакоммиченные правки, а у потребителя, которому
        # поднимать нечего, ещё и переключил бы ветку без нужды.
        git(root, "fetch", "--quiet", "origin", paths.TRUNK)
        if not calls_itself(root, repo):
            print(f"своих шагов по тегу общая ветка не зовёт — поднимать до {tag} нечего")
            return ""
        # План спрашивается ДО смены ветки и только когда есть что поднимать:
        # у потребителя, которому поднимать нечего, плана может не быть вовсе.
        if not token:
            raise NotRun("токена нет — план работ, к которому привязан подъём, спросить нечем")
        plan_issue = plan_number(repo, token)
        switch_clean(root, branch)
    planned = plan(root, repo, tag, sha)
    if not planned:
        print(f"своих шагов по тегу дерево не зовёт — поднимать до {tag} нечего")
        return ""
    note = paths.FRAGMENTS / f"deps-self-{slug(tag)}.internal.md"
    print(f"свои шаги → {tag} ({sha[:7]}), файлов: {len(planned) + 1}")
    if dry_run:
        return branch
    planned[note] = self_fragment(tag, list(planned), plan_issue)
    for path, text in planned.items():
        (root / path).write_text(text, encoding="utf-8")
    git(root, "add", "--", *[str(path) for path in planned])
    git(
        root,
        "commit",
        "--quiet",
        "-m",
        f"Проба передачи поднята до {tag}\n\nВыпуск {tag} сам поднял прибивку своих шагов:\n"
        f"Dependabot ссылки репозитория на самого себя не предлагает.\n\n"
        f"Refs #{plan_issue}\n\nCo-Authored-By: {CO_AUTHOR}\n",
    )
    git(root, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
    return branch


#: Начало полного имени ветки: место дерева на ветке пишется так, а не коротко.
BRANCH_REF: Final = gitcall.BRANCH_REF


def spot(root: Path) -> str:
    """Где стоит дерево: полное имя ветки, а у отвязанного — полный sha.

    ПОЛНОЕ ИМЯ, А НЕ КОРОТКОЕ (взгляд на #1474). Короткое `--abbrev-ref` при
    одноимённом теге отдаёт `heads/<имя>`, и возврат по нему оставлял дерево
    отвязанным, а не на ветке, где его застал. Полное `refs/heads/<имя>`
    неоднозначным не бывает.
    """
    name = git(root, "rev-parse", "--symbolic-full-name", "HEAD").strip()
    return name if name.startswith(BRANCH_REF) else git(root, "rev-parse", "HEAD").strip()


def restore(root: Path, start: str) -> None:
    """Вернуть дерево туда, где заход его застал, — если сдвинул, и не стирая правок.

    Прежде возврат шёл `checkout --force` и после ОТКАЗА `switch_clean`: правки,
    ради которых отказ и был, стирались здесь же (`4885891`). Дерево с правками
    теперь не трогается и называется; чистое возвращается без `--force`.

    ВОЗВРАТ — ТУДА, ГДЕ ЗАСТАЛ, И ТОЛЬКО ЕСЛИ СДВИНУЛ (взгляд на #1468). Прежде
    возврат шёл на отвязанную общую ветку после каждого захода, а заход ветку
    меняет не всегда: подъёму, которому нечего поднимать или чья ветка уже есть,
    переключать нечего (#1421), но возврат всё равно снимал человека с его ветки.
    Это вторая находка по возврату, поэтому чинится классом (210): заход
    запоминает место до работы, и любой исход, не сдвинувший дерево, — отказ до
    переключения, пустой план, готовая ветка — возврата не делает вовсе.

    ЧЬИ ПРАВКИ — НЕ УГАДЫВАЕТСЯ, А НАЗЫВАЕТСЯ ОБА СЛУЧАЯ (взгляд на #1441).
    После отказа `switch_clean` это правки человека, а после записи подъёма,
    которому не дали закоммититься или толкнуться, — недописанный подъём самого
    захода. Отличить их по дереву нечем, поэтому сказаны оба и ветка, на которой
    дерево осталось.
    """
    now = spot(root)
    if now == start:
        return
    if git(root, "status", "--porcelain").strip():
        print(
            f"в дереве незакоммиченные правки, ветка {now.removeprefix(BRANCH_REF)} — "
            f"на {start.removeprefix(BRANCH_REF)} не возвращаю: "
            "после отказа переключения это правки человека, после записи подъёма — "
            "недописанный подъём этого захода; дерево оставлено как есть"
        )
        return
    # Ветка возвращается `switch` — он берёт только ветки, и одноимённый тег его
    # не собьёт; отвязанное — `--detach` на свой коммит.
    if start.startswith(BRANCH_REF):
        git(root, "switch", "--quiet", start.removeprefix(BRANCH_REF))
    else:
        git(root, "checkout", "--quiet", "--detach", start)


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
    parser.add_argument(
        "--self",
        dest="own_tag",
        metavar="ТЕГ",
        help="поднять свои шаги до тега выпуска, а не разбирать сигналы бота",
    )
    args = parser.parse_args(argv)
    if args.own_tag:
        if not args.repo:
            print("не отработал: нет имени проекта", file=sys.stderr)
            return EXIT_BROKEN
        report.announce(not args.apply)
        failed = ""
        try:
            start = spot(args.root)
        except (NotRun, OSError) as exc:
            print(f"не отработал: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        try:
            self_bump(
                args.root,
                args.repo,
                args.own_tag,
                dry_run=not args.apply,
                token=ghrest.token_from_env(),
            )
        except (NotRun, OSError) as exc:
            failed = str(exc)
        # Подъём своих шагов режет ветку так же, как перехват, и возвращается
        # так же — прежде дерево оставалось на `agent/deps-self-…` (взгляд на #1441).
        if args.apply:
            try:
                restore(args.root, start)
            except (NotRun, OSError) as exc:
                failed = failed or (
                    f"дерево на {start.removeprefix(BRANCH_REF)} не возвращено: {exc}"
                )
        if failed:
            print(f"не отработал: {failed}", file=sys.stderr)
            return EXIT_BROKEN
        return EXIT_OK
    token = ghrest.token_from_env()
    if not args.repo or not token:
        print("не отработал: нет имени проекта или токена", file=sys.stderr)
        return EXIT_BROKEN
    report.announce(not args.apply)
    refused: list[str] = []
    try:
        start = spot(args.root)
        found = signals(args.repo, token)
        print(f"сигналов {BOT}: {len(found)}")
        # План и подпись спрашиваются ОДИН раз и только при сигнале: заход без
        # сигналов к площадке за ними не ходит.
        plan_issue = plan_number(args.repo, token) if found else 0
        who = identity(token) if found and args.apply else None
        for change in found:
            try:
                intercept(
                    args.root,
                    args.repo,
                    token,
                    parse(change),
                    dry_run=not args.apply,
                    plan_issue=plan_issue,
                    who=who,
                )
            except Refused as exc:
                refused.append(str(exc))
                print(f"не разобрано: {exc}")
            finally:
                if args.apply:
                    restore(args.root, start)
    except (NotRun, ghrest.TransportError, OSError) as exc:
        print(f"не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_FOUND if refused else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
