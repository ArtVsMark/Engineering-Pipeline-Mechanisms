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
  но держалось это порядком, а не проверкой.

СОСТАВНОЕ ДЕЙСТВИЕ ИЗ ДЕРЕВА И `defaults.run.shell` — НЕ РАЗБИРАЮТСЯ, А
ЗАПРЕЩЕНЫ (210: второй заход взгляда на одно место — строгое правило вместо
новых форм; взгляд на #1149). Разбор составного действия требовал своего
порядка установки внутри, защиты от цикла ссылок и `defaults` на трёх
уровнях — три формы ради того, чего в дереве нет. Замер 05.10.2026: шагов
`uses: ./…` — 0, `defaults:` — 0. Поэтому проверка по дереву краснеет на
ЛЮБОМ из них с причиной: появится нужда — гейт сначала научат, а не
пропустят молча (`test_no_flow_uses_what_the_gate_does_not_parse`).

УСТАНОВКА И АГЕНТ УЗНАЮТСЯ ПО ИМЕНИ ДЕЙСТВИЯ, А НЕ ПОДСТРОКОЙ — и с разной
строгостью в сторону красного. Установка — ровно `actions/setup-python`:
чужое действие, принятое за установку, гасило бы красное. Агент — по имени
действия без владельца (`…/claude-code-action`): форк агента, не узнанный
агентом, тоже гасил бы красное.
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
#: Имя действия агента без владельца: агент исполняет команды из текста
#: задания, python в том числе.
AGENT: Final = "claude-code-action"
#: Признак составного действия из своего дерева: гейт его не разбирает.
LOCAL_ACTION: Final = "./"


def action_name(step: dict[str, Any]) -> str:
    """Имя действия шага без версии: `владелец/имя` или путь в дереве."""
    return str(step.get("uses") or "").split("@")[0].strip()


def calls_python(step: dict[str, Any]) -> bool:
    """Выберет ли шаг интерпретатор: строкой `run:`, оболочкой или агентом."""
    if str(step.get("shell") or "").startswith("python"):
        return True
    if action_name(step).rsplit("/", 1)[-1] == AGENT:
        return True
    lines = str(step.get("run") or "").splitlines()
    code = [line for line in lines if not line.lstrip().startswith("#")]
    return any(CALL.search(line) for line in code)


def unparsed(flow: dict[str, Any]) -> list[str]:
    """Что в прогоне гейт не разбирает: составные действия из дерева и `defaults.run.shell`."""
    found = []
    if ((flow.get("defaults") or {}).get("run") or {}).get("shell"):
        found.append("defaults.run.shell прогона")
    for name, job in (flow.get("jobs") or {}).items():
        if ((job.get("defaults") or {}).get("run") or {}).get("shell"):
            found.append(f"{name}: defaults.run.shell работы")
        for number, step in enumerate(job.get("steps") or [], start=1):
            if action_name(step).startswith(LOCAL_ACTION):
                found.append(f"{name}: {step.get('name') or f'шаг {number}'} — составное действие")
    return found


def calls_before_setup(steps: list[dict[str, Any]]) -> list[str]:
    """Шаги, выбирающие python раньше `setup-python`; строки-комментарии не в счёт."""
    found, ready = [], False
    for number, step in enumerate(steps, start=1):
        # Установка — ровно это действие, а не подстрока имени: `setup-pythonX`
        # или чужое `…/actions/setup-python` установкой не считаются.
        if action_name(step) == SETUP:
            ready = True
        elif not ready and calls_python(step):
            found.append(str(step.get("name") or f"шаг {number}"))
    return found


def flows() -> dict[str, dict[str, Any]]:
    """Прогоны дерева по имени файла."""
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for path in walk(ROOT / ".github" / "workflows", "*.y*ml")
    }


def jobs_with_steps() -> dict[str, list[dict[str, Any]]]:
    """Работы всех прогонов дерева, у которых есть свои шаги."""
    found = {}
    for file, flow in flows().items():
        for name, job in (flow.get("jobs") or {}).items():
            if job.get("steps"):
                found[f"{file}:{name}"] = job["steps"]
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
        ([{"name": "a", "uses": "someone/claude-code-action@x"}], ["a"]),
        ([{"name": "a", "uses": "anthropics/claude-code-action-notes@x"}], []),
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
        "агент-форк",
        "агент-похожее-имя",
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


def test_what_the_gate_does_not_parse_is_named() -> None:
    """Составное действие и `defaults.run.shell` на обоих уровнях названы, обычный шаг — нет."""
    flow = {
        "defaults": {"run": {"shell": "python {0}"}},
        "jobs": {
            "j": {
                "defaults": {"run": {"shell": "bash"}},
                "steps": [{"name": "a", "uses": "./.github/actions/x"}, {"run": "echo ok"}],
            },
            "k": {"steps": [{"uses": f"{SETUP}@x"}, {"uses": "./y@v1"}]},
        },
    }
    assert unparsed(flow) == [
        "defaults.run.shell прогона",
        "j: defaults.run.shell работы",
        "j: a — составное действие",
        "k: шаг 2 — составное действие",
    ]
    assert unparsed({"jobs": {"j": {"steps": [{"uses": f"{SETUP}@x"}, {"run": "x"}]}}}) == []


def test_no_flow_uses_what_the_gate_does_not_parse() -> None:
    """В дереве нет того, что гейт не разбирает: появится — гейт учат, а не пропускают (210)."""
    off = {file: found for file, flow in flows().items() if (found := unparsed(flow))}
    assert not off, (
        f"гейт «python не раньше setup-python» этого не разбирает: {off} — научите его "
        "(порядок установки внутри составного, цикл ссылок, defaults) или уберите"
    )


def test_agent_steps_exist_in_the_tree() -> None:
    """Предмет агентской половины есть: шаги агента в дереве (075, #1143).

    Порядок их относительно установки держит `test_no_job_calls_python_before_its_setup`.
    """
    agents = [
        name
        for name, steps in jobs_with_steps().items()
        if any(action_name(step).rsplit("/", 1)[-1] == AGENT for step in steps)
    ]
    assert agents, "шагов агента в дереве нет — агентская половина гейта судит пустоту (075)"
