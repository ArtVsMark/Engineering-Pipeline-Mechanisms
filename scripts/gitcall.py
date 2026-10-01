"""Вызов git с выводом: один на механизмы, отказ — исключение вызывающего.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Замер 01.10.2026 (#999, правило 071): одно и то же
тело «позвать git, отказ обратить в третий исход» жило в шести модулях двумя
формами. Форма с `returncode` не ловила `OSError`: без git на пути механизм
падал трассой, а не говорил «не отработал» (039). Здесь — одна форма, строгая.

ТРЕТИЙ ИСХОД У КАЖДОГО СВОЙ. Модуль передаёт свой класс отказа, и его
`except NotRun` ловит ровно то, что ловил раньше: общим становится вызов, а не
смысл отказа.

СОСЕДИ ЗА ГРАНИЦЕЙ (195) — тела у них другие, и гейт `tests/test_one_body.py`
их не видит: `version.git` отвечает `None` вместо отказа, `journal.git` берёт
команду целиком, `release.git` срезает вывод, `window.git` и
`check_agent_silenced._git` зовут git в названном каталоге.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

import report


def output(args: Sequence[str], refusal: Callable[[str], Exception]) -> str:
    """Вывод `git <args>`; отказ git или его отсутствие — `refusal`, а не пустой ответ (075)."""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, check=True, text=True, encoding="utf-8"
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise refusal(f"git {' '.join(args)} → {report.cut(str(detail))}") from exc
