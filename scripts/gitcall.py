"""Вызов git с выводом: один на механизмы, отказ — исключение вызывающего.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Замер 01.10.2026 (#999, правило 071): одно и то же
тело «позвать git, отказ обратить в третий исход» жило в шести модулях двумя
формами. Форма с `returncode` не ловила `OSError`: без git на пути механизм
падал трассой, а не говорил «не отработал» (039). Здесь — одна форма, строгая.

ТРЕТИЙ ИСХОД У КАЖДОГО СВОЙ. Модуль передаёт свой класс отказа, и его
`except NotRun` ловит ровно то, что ловил раньше: общим становится вызов, а не
смысл отказа.

ТЕМ ЖЕ ВЫЗОВОМ ИДУТ `release.git` (срезает вывод) и `window.git` (зовёт git в
названном каталоге): тела у них были другие, но беда та же — `OSError` не
ловился, и без git они падали трассой (взгляд на #1008).

СОСЕДИ ЗА ГРАНИЦЕЙ (195) — те, кто читает код выхода сам, а не отказывает
на любом ненуле, и потому зовёт git своей формой. Они ловят `OSError` у себя:
`version.git` отвечает `None` — версия без git законно неизвестна;
`journal.git` берёт команду целиком; `check_agent_silenced._git` различает
«пусто» по коду; `items_left.git` и `review_map.git` (взгляд на #1021).

СПИСОК ВЫШЕ — ТЕ, У КОГО ФОРМА СВОЯ, И ОН ДЕРЖИТСЯ ГЕЙТОМ, А НЕ ПАМЯТЬЮ.
`tests/test_git_refuses.py` требует от каждой функции `scripts/`, зовущей git,
поймать `OSError` у себя или идти этим вызовом. Замер 01.10.2026: таких мест
без поимки было 19 в 11 модулях; восемь сняты в #1021, одиннадцать — в #1027.
"""

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

import report

#: ДЕДЛАЙН ВЫЗОВА ПРОЦЕССА НАЗВАН ОДИН РАЗ (100, 220, #1439). Зависший git
#: держал гейт до предела площадки, и красное приходило причиной «превышено
#: время», а не названным отказом. Каждый вызов процесса в механизмах несёт
#: дедлайн и ловит его истечение — держит `tests/test_subprocess_deadline.py`.
#: Локальная команда — чтение истории, дерева, архива: секунды, предел с
#: запасом на большой репозиторий.
LOCAL: Final = 60
#: Команда, идущая по сети: толчок, клон, выборка.
NETWORK: Final = 300
#: Начало полного имени ветки.
BRANCH_REF: Final = "refs/heads/"


def cause(exc: Exception) -> str:
    """Причина отказа вызова процесса строкой: истёкший дедлайн назван дедлайном.

    `TimeoutExpired` несёт перехваченный вывод БАЙТАМИ при любом `text=True`
    (так в документации `subprocess`): разбор `exc.stderr` клал в отказ
    `b'…'`, а «не уложился» терял — находка `f767e24`. Отказ с кодом и без
    вывода называется самим исключением: код в нём есть.
    """
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"не уложился в дедлайн {exc.timeout:g} с"
    said = getattr(exc, "stderr", None)
    if isinstance(said, bytes):
        said = said.decode("utf-8", "replace")
    return said.strip() if isinstance(said, str) and said.strip() else str(exc)


def output(
    args: Sequence[str],
    refusal: Callable[[str], Exception],
    *,
    cwd: str | None = None,
    timeout: float = LOCAL,
) -> str:
    """Вывод `git <args>` в `cwd`; отказ, отсутствие или истёкший дедлайн — `refusal` (075)."""
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            timeout=timeout,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise refusal(f"git {' '.join(args)} → {report.cut(cause(exc))}") from exc


def branch(refusal: Callable[[str], Exception], *, cwd: str | None = None) -> str:
    """Имя текущей ветки; у отвязанной головы — `HEAD`; отказ git — `refusal`.

    ПОЛНЫМ ИМЕНЕМ, А НЕ `--abbrev-ref` (взгляд на #1513). При одноимённом теге
    короткое имя неоднозначно, и git отдаёт `heads/<имя>` — ветку, которой нет.
    Полное `refs/heads/<имя>` неоднозначным не бывает, и приставка снимается
    здесь, одним местом на всех спрашивающих (090).
    """
    said = output(["rev-parse", "--symbolic-full-name", "HEAD"], refusal, cwd=cwd).strip()
    return said.removeprefix(BRANCH_REF)


class _NoOrigin(RuntimeError):
    """Адрес `origin` не прочитан: для `own_repo` это «имя неизвестно», а не отказ."""


def own_repo(root: Path) -> str:
    """Имя `владелец/репозиторий` дерева `root`: `origin`, без него — площадка; пусто — неизвестно.

    ОДИН ОТВЕТ НА «КТО Я» ДЛЯ ГЕЙТОВ (#1624). Прежде он жил в
    `check_agent_silenced`; третий спрашивающий (`check_foreign_why`) сделал
    его общим (093). Признак широкий — две последние части адреса: ошибиться
    он может только в сторону «неизвестно», и тогда гейт судит как обычно.
    Соседние разборы `origin` с другим допуском ошибки — `onboard.repo_of`
    (узкий: имя уходит строкой в чужой README) и
    `check_branch_revival.repo_of` (отказывает: имя идёт запросом к
    площадке) — названы, а не слиты (195). `pipeline_checks.running_repo`
    отвечает на ДРУГОЙ вопрос — где идёт прогон, а не чьё дерево, — и потому
    читает текущую папку (взгляд на #1651, `903625b`).

    СПЕРВА `origin` САМОГО `root`, ПЛОЩАДКА — ЗАПАСНЫМ (взгляд на #1646,
    `effc300`). `GITHUB_REPOSITORY` — имя репозитория прогона, а не любого
    `root`: стоя первым, оно отвечало за `--root <чужое дерево>`, и дерево
    каталога в прогоне соседа выглядело бы соседом — ошибка в сторону тишины.
    В прогоне `actions/checkout` ставит `origin` на тот же репозиторий, так что
    своё дерево ответа не меняет. ГРАНИЦА НАЗВАНА: чужое дерево без `origin`
    (распакованный архив) по-прежнему получит имя прогона.
    """
    try:
        url = output(["remote", "get-url", "origin"], _NoOrigin, cwd=str(root))
    except _NoOrigin:
        url = ""
    parts = url.strip().removesuffix(".git").replace(":", "/").split("/")
    if len(parts) >= 2 and parts[-1] and parts[-2]:
        return f"{parts[-2]}/{parts[-1]}"
    return os.environ.get("GITHUB_REPOSITORY", "").strip()
