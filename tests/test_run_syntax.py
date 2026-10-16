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
подобные) не проверяются — их в дереве нет, и это сверяет сам тест.
"""

import re
import subprocess
from typing import Any

import yaml

from tests.conftest import ROOT, walk_deep

#: Выражение площадки: его значение известно только в прогоне.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def scripts() -> list[tuple[str, str, str]]:
    """Сценарии `run:` всех прогонов и действий: файл, имя шага, оболочка."""
    found: list[tuple[str, str, str]] = []
    for path in walk_deep(ROOT / ".github", "*.yml"):
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        steps: list[Any] = []
        for job in (document.get("jobs") or {}).values():
            steps += (job or {}).get("steps") or []
        runs = document.get("runs")
        if isinstance(runs, dict):
            steps += runs.get("steps") or []
        for step in steps:
            if step.get("run"):
                name = f"{path.relative_to(ROOT)}: {step.get('name') or step.get('id') or '?'}"
                found.append((name, str(step["run"]), str(step.get("shell") or "bash")))
    return found


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
