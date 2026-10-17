"""Каждый сценарий `run:` разбирается оболочкой, которой его исполнит площадка.

ЗАЧЕМ (находка взгляда на #1423). Шаг сверки архива переехал из `badges.yml`
в `step-facts.yml` без строки `esac`, и полный набор остался зелёным: ни одна
проверка не спрашивала у `bash`, разбирается ли сценарий вообще. Площадка
узнала бы об этом первым заходом с `archive: true` — и он не опубликовал бы
ни фактов, ни архива. Замер 16.10.2026: сценариев `bash` в дереве 207, не
разбирался ровно один — этот.

ГРАНИЦА НАЗВАНА (195). Проверяется только разбор (`bash -n`), а не исполнение;
выражения площадки `${{ … }}` заменяются словом, потому что их значение
известно только в прогоне. Сценарии с иной оболочкой (`shell: python` и
подобные) не проверяются — их в дереве нет, и это сверяет сам тест. Оболочка
берётся так же, как её берёт площадка: у шага, иначе из `defaults.run.shell`
джоба, иначе прогона (взгляд на #1423) — умолчание выше шага прежде не
читалось, и такой сценарий ушёл бы в `bash -n`.
"""

import re
import subprocess
from typing import Any

import yaml

from tests.conftest import ROOT, walk_deep

#: Выражение площадки: его значение известно только в прогоне.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def default_shell(holder: Any) -> str:
    """`defaults.run.shell` прогона или джоба; нет — пусто."""
    defaults = (holder or {}).get("defaults") if isinstance(holder, dict) else None
    run = (defaults or {}).get("run") if isinstance(defaults, dict) else None
    return str((run or {}).get("shell") or "") if isinstance(run, dict) else ""


def steps_with_shells(document: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Шаги с `run:` и оболочкой, которой их исполнит площадка: шаг → джоб → прогон."""
    found: list[tuple[dict[str, Any], str]] = []
    top = default_shell(document)
    for job in (document.get("jobs") or {}).values():
        own = default_shell(job) or top
        found += [
            (step, str(step.get("shell") or own or "bash"))
            for step in (job or {}).get("steps") or []
            if step.get("run")
        ]
    runs = document.get("runs")
    if isinstance(runs, dict):
        found += [
            (step, str(step.get("shell") or "bash"))
            for step in runs.get("steps") or []
            if step.get("run")
        ]
    return found


def scripts() -> list[tuple[str, str, str]]:
    """Сценарии `run:` всех прогонов и действий: файл, имя шага, оболочка."""
    found: list[tuple[str, str, str]] = []
    for path in walk_deep(ROOT / ".github", "*.yml"):
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for step, shell in steps_with_shells(document):
            name = f"{path.relative_to(ROOT)}: {step.get('name') or step.get('id') or '?'}"
            found.append((name, str(step["run"]), shell))
    return found


def test_the_shell_is_taken_where_the_platform_takes_it() -> None:
    """Оболочка — у шага, иначе умолчание джоба, иначе прогона (взгляд на #1423)."""
    document = {
        "defaults": {"run": {"shell": "pwsh"}},
        "jobs": {
            "a": {"defaults": {"run": {"shell": "python"}}, "steps": [{"run": "x"}]},
            "b": {"steps": [{"run": "y"}, {"run": "z", "shell": "bash"}]},
        },
    }
    assert [shell for _, shell in steps_with_shells(document)] == ["python", "pwsh", "bash"]
    assert [
        shell for _, shell in steps_with_shells({"jobs": {"c": {"steps": [{"run": "w"}]}}})
    ] == ["bash"]


def test_every_bash_script_parses() -> None:
    """`bash -n` разбирает каждый сценарий; незакрытый `case` или `if` — отказ."""
    found = scripts()
    assert found, "сценариев `run:` не нашлось — обход не туда (075)"
    others = sorted({shell for _, _, shell in found if not shell.startswith("bash")})
    assert not others, f"сценарии с иной оболочкой этот тест не проверяет: {others}"
    broken = []
    for name, body, _ in found:
        done = subprocess.run(
            ["bash", "-n"],
            input=EXPRESSION.sub("X", body),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if done.returncode:
            broken.append(f"{name} — {done.stderr.strip()}")
    assert not broken, "сценарий не разбирается оболочкой:\n" + "\n".join(broken)
