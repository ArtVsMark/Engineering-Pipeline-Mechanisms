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

import subprocess
from collections.abc import Callable, Sequence
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
