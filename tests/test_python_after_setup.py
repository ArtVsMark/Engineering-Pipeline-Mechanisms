"""Работа прогона зовёт python только после `setup-python` (217).

Правило 217 считает переезд на версию сделанным, когда на ней исполняется ВСЁ.
Работа, которая зовёт `python` раньше шага установки, исполняется системным
интерпретатором раннера: числа версии в ней нет, и гейт версий
(`tests/test_declared_versions.py`) сверять её не с чем. Так у каталога три
работы звали `python3` без `setup-python` (#672), и это было не видно.

ЗАМЕР 05.10.2026: работ со шагами 41, зовут python или pip 37, раньше установки
— ни одна. Гейт держит форму на будущее: прошлых нарушений нет.

ГРАНИЦА НАЗВАНА (195). Работа без шагов (`uses:` общего шага) здесь не
судится — её шаги судятся в файле общего шага. Действие каталога ставит свой
интерпретатор само и вызовом python не считается. Явный путь к интерпретатору
(`.venv/bin/python`) — не голый вызов: он называет интерпретатор сам.
"""

import re
from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, walk

#: Голый вызов интерпретатора или установщика командой оболочки.
CALL: Final = re.compile(r"(?<![\w./$-])(?:python[0-9.]*|pip[0-9.]*)(?=[\s;|&)]|$)", re.M)
#: Шаг установки интерпретатора.
SETUP: Final = "actions/setup-python"


def calls_before_setup(steps: list[dict[str, Any]]) -> list[str]:
    """Шаги, зовущие python раньше `setup-python`; строки-комментарии не в счёт."""
    found, ready = [], False
    for number, step in enumerate(steps, start=1):
        if SETUP in str(step.get("uses") or ""):
            ready = True
        lines = str(step.get("run") or "").splitlines()
        code = [line for line in lines if not line.lstrip().startswith("#")]
        if not ready and any(CALL.search(line) for line in code):
            found.append(str(step.get("name") or f"шаг {number}"))
    return found


def jobs_with_steps() -> dict[str, list[dict[str, Any]]]:
    """Работы всех прогонов дерева, у которых есть свои шаги."""
    found = {}
    for path in walk(ROOT / ".github" / "workflows", "*.y*ml"):
        flow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (flow.get("jobs") or {}).items():
            if job.get("steps"):
                found[f"{path.name}:{name}"] = job["steps"]
    return found


@pytest.mark.parametrize(
    ("steps", "off"),
    [
        ([{"uses": "actions/setup-python@x"}, {"name": "a", "run": "python x.py"}], []),
        ([{"name": "a", "run": "python x.py"}, {"uses": "actions/setup-python@x"}], ["a"]),
        ([{"name": "a", "run": "set -e\npython3 -m pip install x"}], ["a"]),
        ([{"name": "a", "run": "pip install x"}], ["a"]),
        ([{"name": "a", "run": "cd d && python -m y"}], ["a"]),
        ([{"name": "a", "run": "# python не зовётся\necho ok"}], []),
        ([{"name": "a", "run": ".venv/bin/python x.py"}], []),
        ([{"name": "a", "run": "echo setup-python python-version"}], []),
        ([{"name": "a", "run": "git log"}], []),
    ],
    ids=[
        "после-установки",
        "до-установки",
        "python3",
        "pip",
        "после-и",
        "комментарий",
        "явный-путь",
        "имя-в-слове",
        "без-python",
    ],
)
def test_a_call_before_the_setup_is_named(steps: list[dict[str, Any]], off: list[str]) -> None:
    """Обе половины: вызов до установки назван; после установки и не-вызов — чисто."""
    assert calls_before_setup(steps) == off


def test_the_subject_of_this_gate_exists() -> None:
    """Предмет есть: в дереве есть работы, зовущие python (075)."""
    calling = [
        name
        for name, steps in jobs_with_steps().items()
        if any(CALL.search(str(step.get("run") or "")) for step in steps)
    ]
    assert len(calling) > 10, f"работ, зовущих python, подозрительно мало: {calling}"


def test_no_job_calls_python_before_its_setup() -> None:
    """В дереве ни одна работа не зовёт python раньше `setup-python` (217)."""
    off = {
        name: found
        for name, steps in jobs_with_steps().items()
        if (found := calls_before_setup(steps))
    }
    assert not off, f"python зовётся до установки интерпретатора: {off}"
