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

СПИСОК ВЫШЕ НЕ ПОЛОН, И ЭТО ЗАМЕР, А НЕ ОБЕЩАНИЕ. Обход `scripts/` 01.10.2026:
функций с вызовом git без `OSError` было 19 в 11 модулях. Восемь из них —
`items_left` и `review_map` — сняты здесь, остальные одиннадцать — работа гейта
по правилу 210, а не следующей правки по одному (#1027).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

import report


def output(
    args: Sequence[str], refusal: Callable[[str], Exception], *, cwd: str | None = None
) -> str:
    """Вывод `git <args>` в `cwd`; отказ git или его отсутствие — `refusal` (075)."""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, check=True, text=True, encoding="utf-8", cwd=cwd
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise refusal(f"git {' '.join(args)} → {report.cut(str(detail))}") from exc
