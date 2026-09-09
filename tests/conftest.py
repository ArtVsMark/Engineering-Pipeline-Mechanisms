"""Общее для тестов: корень репозитория и запуск скриптов как процессов."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Run:
    """Результат прогона скрипта: код возврата и оба потока."""

    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        """Оба потока разом — исход печатается в любой из них."""
        return self.out + self.err


RunScript = Callable[..., "Run"]


@pytest.fixture
def run_script() -> RunScript:
    """Запускает скрипт проекта отдельным процессом, как это делает прогон."""

    def _run(
        script: str,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> Run:
        environment = dict(os.environ)
        if env is not None:
            for key, value in env.items():
                if value == "":
                    environment.pop(key, None)
                else:
                    environment[key] = value
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *args],
            capture_output=True,
            text=True,
            cwd=cwd or ROOT,
            env=environment,
        )
        return Run(completed.returncode, completed.stdout, completed.stderr)

    return _run


def load_script(name: str) -> ModuleType:
    """Импортирует скрипт проекта как модуль, чтобы проверять его логику прямо.

    Скрипты живут в `scripts/` и пакета не образуют: каждый запускается сам по
    себе. Общее у них всё же есть — транспорт `ghrest` и состав меток
    `labels`, — и остальные их импортируют, иначе обвязка расползается копиями.
    Отсюда и добавление пути ниже: без него импорт общего модуля не найдётся.
    """
    path = ROOT / "scripts" / name
    # Механизмы делят общий транспорт (`ghrest`), и при запуске файла его
    # находит сам интерпретатор: каталог скрипта попадает в путь первым. При
    # импорте отсюда этого не происходит, поэтому путь добавляется явно —
    # тест обязан видеть модуль ровно так же, как его видит прогон.
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не собрать модуль из {path}")
    module = importlib.util.module_from_spec(spec)
    # Модуль кладётся в sys.modules ДО исполнения — ровно так же, как это делает
    # сам интерпретатор. Без этого dataclass со `slots=True` не собирается:
    # `dataclasses` ищет модуль класса по имени, чтобы разобрать отложенные
    # аннотации (`from __future__ import annotations`), не находит его и падает
    # на пустом месте. Тест обязан видеть модуль так же, как прогон.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
