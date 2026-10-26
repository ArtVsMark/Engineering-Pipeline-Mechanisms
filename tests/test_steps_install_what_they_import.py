"""Джоб ставит то, что импортируют его скрипты: без `pyyaml` они падают на импорте.

ЗАМЕР 25.10.2026: с #1641 `findings.py` импортирует `pipeline_checks`, а тот —
`yaml`. Джобы `map`, `findings`, `sweep` и `late-queue` общего шага взгляда и
`schedules-seen` ставили один транспорт и падали `ModuleNotFoundError` на первой
строке. Отказ шаг печатал предупреждением, прогон оставался зелёным, и реестр
находок сутки не пополнялся и не убирался — заметили по плану, а не по прогону.

СУДИТСЯ ПОРЯДОК, А НЕ ДЖОБ ЦЕЛИКОМ (#1671, находка `91fa9dc`). Первая
редакция снимала проверку со всего джоба, если `pyyaml` стоял в любом его шаге,
и пропустила джоб `map`: `review_map.py` звался до шага, ставившего `pyyaml`.
Теперь строки `run:` джоба читаются по порядку, и скрипт, позванный раньше
строки установки с `pyyaml`, судится. Замер 26.10.2026: таких вызовов в дереве
семь, импорт без `yaml` роняет один — `review_map` в `step-review.yml · map`.

СУДИТ ИСПОЛНЕНИЕ, А НЕ РАЗБОР: скрипт импортируется в отдельном процессе с
закрытым `yaml`. Разбор импортов по дереву объявил бы сломанным и ленивый
импорт внутри функции, которого рабочий путь не исполняет (`check_rulebook_fresh`).
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, walk

#: Скрипт, который зовёт шаг: из выкачки механизмов или из своего дерева.
CALLED_RE = re.compile(r"(?:\$MECHANISMS|\$\{\{ env\.MECHANISMS \}\})?/?scripts/(\w+)\.py")
#: Импорт скрипта при закрытом `yaml`: код 3 — упал именно на нём, код 4 —
#: упал на другом, и судить о `yaml` проба не смогла (039).
PROBE = """
import builtins, sys
sys.path[:0] = [{scripts!r}, {transport!r}]
real = builtins.__import__
def closed(name, *args, **kwargs):
    if name == "yaml" or name.startswith("yaml."):
        raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
    return real(name, *args, **kwargs)
builtins.__import__ = closed
try:
    __import__({module!r})
except ModuleNotFoundError as exc:
    if exc.name == "yaml" or (exc.name or "").startswith("yaml."):
        sys.exit(3)
    print(f"{{type(exc).__name__}}: {{exc}}", file=sys.stderr)
    sys.exit(4)
except Exception as exc:
    print(f"{{type(exc).__name__}}: {{exc}}", file=sys.stderr)
    sys.exit(4)
"""
#: Коды пробы: импорт прошёл без `yaml` · упал на `yaml`.
WITHOUT_YAML, NEEDS_YAML = 0, 3


def called_before_yaml(job: dict[str, Any]) -> list[str]:
    """Скрипты, которые строки `run:` джоба зовут РАНЬШЕ установки `pyyaml`, — по порядку.

    Джоб без `pip install` вовсе не судится: ему ставит окружение, а не он.
    """
    lines = [
        line for step in job.get("steps") or [] for line in str(step.get("run") or "").splitlines()
    ]
    if not any("pip install" in line for line in lines):
        return []
    called: list[str] = []
    for line in lines:
        if "pip install" in line and "pyyaml" in line:
            break
        called += [one for one in CALLED_RE.findall(line) if one not in called]
    return called


def jobs_without_yaml() -> list[tuple[str, str, str]]:
    """Тройки «прогон · джоб · скрипт»: джоб зовёт скрипт до того, как поставил `pyyaml`."""
    found: list[tuple[str, str, str]] = []
    for flow in walk(ROOT / ".github" / "workflows", "*.yml"):
        document = yaml.safe_load(flow.read_text(encoding="utf-8")) or {}
        for name, job in (document.get("jobs") or {}).items():
            for script in called_before_yaml(job):
                if (ROOT / "scripts" / f"{script}.py").is_file():
                    found.append((flow.name, str(name), script))
    return found


def imports_yaml(module: str) -> bool:
    """Падает ли импорт скрипта без `yaml` — исполнением в отдельном процессе.

    Импорт, упавший не на `yaml`, — третий исход, а не «`yaml` не нужен»:
    скрипт, упавший раньше, гейт иначе пропустил бы молча (взгляд на #1671).
    """
    probe = PROBE.format(
        scripts=str(ROOT / "scripts"),
        transport=str(ROOT / "packages" / "transport"),
        module=module,
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert done.returncode in (WITHOUT_YAML, NEEDS_YAML), (
        f"проба не смогла судить scripts/{module}.py: импорт упал не на `yaml` — "
        f"{done.stderr.strip()[-300:]}"
    )
    return done.returncode == NEEDS_YAML


def test_the_probe_sees_a_script_that_needs_yaml() -> None:
    """Проба не слепа: `pipeline_checks` без `yaml` падает, транспорт — нет."""
    assert imports_yaml("pipeline_checks")
    assert not imports_yaml("ghrest")


def test_a_probe_that_cannot_judge_says_so() -> None:
    """Импорт, упавший не на `yaml`, — отказ пробы, а не зелёное (039)."""
    with pytest.raises(AssertionError, match="не смогла судить"):
        imports_yaml("нет_такого_скрипта")


@pytest.mark.parametrize(
    ("runs", "called"),
    [
        (
            ["pip install x", "python scripts/a.py", "pip install pyyaml", "python scripts/b.py"],
            ["a"],
        ),
        (["pip install pyyaml x", "python scripts/a.py"], []),
        (["python scripts/a.py"], []),
    ],
    ids=["до-установки", "после-установки", "без-pip"],
)
def test_a_call_before_yaml_is_judged_by_order(runs: list[str], called: list[str]) -> None:
    """Судится вызов ДО строки с `pyyaml`; после неё и в джобе без pip — нет."""
    job = {"steps": [{"run": one} for one in runs]}
    assert called_before_yaml(job) == called


def test_a_module_with_yaml_in_its_name_is_not_yaml(tmp_path: Path) -> None:
    """Проба узнаёт `yaml` по имени модуля исключения, а не подстрокой текста."""
    (tmp_path / "yaml_tools.py").write_text("import nothing_here_yaml_tools\n", encoding="utf-8")
    probe = PROBE.format(scripts=str(tmp_path), transport=str(tmp_path), module="yaml_tools")
    done = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert done.returncode == 4, done.stderr


@pytest.mark.parametrize(("flow", "job", "script"), jobs_without_yaml())
def test_a_job_installs_yaml_for_the_scripts_it_runs(flow: str, job: str, script: str) -> None:
    """Джоб без `pyyaml` в установке не зовёт скрипт, которому он нужен на импорте."""
    assert not imports_yaml(script), (
        f"{flow} · {job}: зовёт scripts/{script}.py, а `pyyaml` не ставит — "
        "скрипт падает на импорте, и шаг выходит отказом"
    )
