#!/usr/bin/env python3
"""Вход механизма: исключение — исход отказа, а не код 1 «нашёл» (#1720).

ЗАЧЕМ. Непойманное исключение Python выходит кодом 1, а у механизма с
объявленным исходом 1 это «нашёл»: отказ выдавался за находку (039, 045).
Замер 28.10.2026: механизмов с исходом 1 — 36, вход под защитой — один
(`headroom.guarded`, #1707), и поздний взгляд нашёл соседей — `stuck.py` и
`schedules_seen.py`. Защита — здесь одна, а не копией в каждом входе (214);
что всякий механизм с исходом 1 входит через неё, держит
`tests/test_main_guard.py`.

ГРАНИЦЫ НАЗВАНЫ. Отказ импорта из шапки модуля случается до входа и выходит
кодом 1: модуль ещё не загружен, звать нечего. `SystemExit` (выход `argparse`
и явный `sys.exit`) и `KeyboardInterrupt` не ловятся — они не `Exception`,
и их код — решение самого механизма или человека.
"""

import sys
import traceback
from collections.abc import Callable
from pathlib import Path


def run(main: Callable[[], int], broken: int, said: str = "") -> int:
    """Исход `main`; исключение — трасса, слова «не находка» и исход `broken`.

    `said` — что сказать вместо общих слов: имя механизма и чем отказ
    отличается от его находки. Пусто — имя запущенного файла.
    """
    try:
        return main()
    except Exception:
        traceback.print_exc()
        name = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "механизм"
        print(
            said or f"{name} не отработал: исключение выше — не находка (039)",
            file=sys.stderr,
        )
        return broken
