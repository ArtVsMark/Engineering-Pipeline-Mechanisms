"""Джоб ставит то, что импортируют его скрипты: без `pyyaml` они падают на импорте.

ЗАМЕР 25.10.2026: с #1641 `findings.py` импортирует `pipeline_checks`, а тот —
`yaml`. Джобы `map`, `findings`, `sweep` и `late-queue` общего шага взгляда и
`schedules-seen` ставили один транспорт и падали `ModuleNotFoundError` на первой
строке. Отказ шаг печатал предупреждением, прогон оставался зелёным, и реестр
находок сутки не пополнялся и не убирался — заметили по плану, а не по прогону.

СУДИТ ИСПОЛНЕНИЕ, А НЕ РАЗБОР: скрипт импортируется в отдельном процессе с
закрытым `yaml`. Разбор импортов по дереву объявил бы сломанным и ленивый
импорт внутри функции, которого рабочий путь не исполняет (`check_rulebook_fresh`).
"""

import re
import subprocess
import sys

import pytest
import yaml

from tests.conftest import ROOT

#: Скрипт, который зовёт шаг: из выкачки механизмов или из своего дерева.
CALLED_RE = re.compile(r"(?:\$MECHANISMS|\$\{\{ env\.MECHANISMS \}\})?/?scripts/(\w+)\.py")
#: Импорт скрипта при закрытом `yaml`: код 3 — упал именно на нём.
PROBE = """
import builtins, sys
sys.path[:0] = [{scripts!r}, {transport!r}]
real = builtins.__import__
def closed(name, *args, **kwargs):
    if name == "yaml" or name.startswith("yaml."):
        raise ModuleNotFoundError("No module named 'yaml'")
    return real(name, *args, **kwargs)
builtins.__import__ = closed
try:
    __import__({module!r})
except ModuleNotFoundError as exc:
    sys.exit(3 if "yaml" in str(exc) else 0)
"""


def jobs_without_yaml() -> list[tuple[str, str, str]]:
    """Пары «прогон · джоб · скрипт»: джоб ставит pip, но не `pyyaml`, и зовёт скрипт."""
    found: list[tuple[str, str, str]] = []
    for flow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        document = yaml.safe_load(flow.read_text(encoding="utf-8")) or {}
        for name, job in (document.get("jobs") or {}).items():
            text = yaml.safe_dump(job, allow_unicode=True)
            if "pip install" not in text or "pyyaml" in text:
                continue
            for script in sorted(set(CALLED_RE.findall(text))):
                if (ROOT / "scripts" / f"{script}.py").is_file():
                    found.append((flow.name, str(name), script))
    return found


def imports_yaml(module: str) -> bool:
    """Падает ли импорт скрипта без `yaml` — исполнением в отдельном процессе."""
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
    return done.returncode == 3


def test_the_probe_sees_a_script_that_needs_yaml() -> None:
    """Проба не слепа: `pipeline_checks` без `yaml` падает, транспорт — нет."""
    assert imports_yaml("pipeline_checks")
    assert not imports_yaml("ghrest")


@pytest.mark.parametrize(("flow", "job", "script"), jobs_without_yaml())
def test_a_job_installs_yaml_for_the_scripts_it_runs(flow: str, job: str, script: str) -> None:
    """Джоб без `pyyaml` в установке не зовёт скрипт, которому он нужен на импорте."""
    assert not imports_yaml(script), (
        f"{flow} · {job}: зовёт scripts/{script}.py, а `pyyaml` не ставит — "
        "скрипт падает на импорте, и шаг выходит отказом"
    )
