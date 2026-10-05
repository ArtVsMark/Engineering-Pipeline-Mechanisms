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

ВЫЗОВ — НЕ ТОЛЬКО СТРОКА `run:` (#1143, находка `efeeee5`). Интерпретатор
выбирается и там, где слова python в строке оболочки нет:

* `shell: python…` — шаг целиком исполняется интерпретатором;
* шаг агента (`claude-code-action`) — агент зовёт `python3 -m pytest` и
  скрипты из ТЕКСТА ЗАДАНИЯ, и какой python он найдёт, решает порядок
  шагов. Замер 05.10.2026: таких шагов 5, у всех `setup-python` раньше —
  но держалось это порядком, а не проверкой;
* составное действие из дерева (`uses: ./…`) — судится по шагам своего
  `action.yml`; файл не найден — вызов считается состоявшимся: неизвестное
  не доказывает отсутствия python (045). Замер: составных из дерева 0.
"""

import re
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, walk

#: Голый вызов интерпретатора или установщика командой оболочки.
CALL: Final = re.compile(r"(?<![\w./$-])(?:python[0-9.]*|pip[0-9.]*)(?=[\s;|&)]|$)", re.M)
#: Шаг установки интерпретатора.
SETUP: Final = "actions/setup-python"
#: Действие агента: исполняет команды из текста задания, python в том числе.
AGENT: Final = "claude-code-action"
#: Признак составного действия из своего дерева.
LOCAL_ACTION: Final = "./"


def calls_python(step: dict[str, Any], root: Path = ROOT) -> bool:
    """Выберет ли шаг интерпретатор: строкой `run:`, оболочкой, агентом или составным действием."""
    if str(step.get("shell") or "").startswith("python"):
        return True
    uses = str(step.get("uses") or "")
    if AGENT in uses:
        return True
    if uses.startswith(LOCAL_ACTION):
        return local_action_calls_python(root / uses.removeprefix(LOCAL_ACTION), root)
    lines = str(step.get("run") or "").splitlines()
    code = [line for line in lines if not line.lstrip().startswith("#")]
    return any(CALL.search(line) for line in code)


def local_action_calls_python(where: Path, root: Path) -> bool:
    """Составное действие из дерева зовёт python своими шагами; файла нет — считается, что зовёт."""
    for name in ("action.yml", "action.yaml"):
        if (where / name).is_file():
            action = yaml.safe_load((where / name).read_text(encoding="utf-8")) or {}
            steps = (action.get("runs") or {}).get("steps") or []
            return any(calls_python(step, root) for step in steps)
    return True


def calls_before_setup(steps: list[dict[str, Any]], root: Path = ROOT) -> list[str]:
    """Шаги, выбирающие python раньше `setup-python`; строки-комментарии не в счёт."""
    found, ready = [], False
    for number, step in enumerate(steps, start=1):
        # Установка — ровно это действие, а не подстрока имени: `setup-pythonX`
        # или чужое `…/actions/setup-python` установкой не считаются.
        if str(step.get("uses") or "").split("@")[0] == SETUP:
            ready = True
        elif not ready and calls_python(step, root):
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
        ([{"name": "a", "uses": "anthropics/claude-code-action@x"}, {"uses": f"{SETUP}@x"}], ["a"]),
        ([{"uses": "actions/setup-pythonX@x"}, {"name": "a", "run": "python x.py"}], ["a"]),
        ([{"uses": f"{SETUP}@x"}, {"name": "a", "uses": "anthropics/claude-code-action@x"}], []),
        ([{"name": "a", "shell": "python {0}", "run": "print(1)"}], ["a"]),
        ([{"name": "a", "uses": "./.github/actions/нет"}], ["a"]),
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
        "агент-до-установки",
        "похожее-имя",
        "агент-после-установки",
        "shell-python",
        "составное-не-найдено",
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


def test_a_local_action_is_judged_by_its_own_steps(tmp_path: Path) -> None:
    """Составное действие из дерева судится по шагам своего `action.yml` (#1143)."""
    calling, quiet = tmp_path / "calling", tmp_path / "quiet"
    for where, run in ((calling, "python x.py"), (quiet, "echo ok")):
        where.mkdir()
        (where / "action.yml").write_text(
            yaml.safe_dump(
                {"runs": {"using": "composite", "steps": [{"run": run, "shell": "bash"}]}}
            ),
            encoding="utf-8",
        )
    assert calls_before_setup([{"name": "a", "uses": "./calling"}], tmp_path) == ["a"]
    assert calls_before_setup([{"name": "a", "uses": "./quiet"}], tmp_path) == []


def test_every_agent_step_comes_after_its_setup() -> None:
    """Предмет агентской половины есть: шаги агента в дереве, и все — после установки (#1143)."""
    agents = [
        name
        for name, steps in jobs_with_steps().items()
        if any(AGENT in str(step.get("uses") or "") for step in steps)
    ]
    assert agents, "шагов агента в дереве нет — агентская половина гейта судит пустоту (075)"
