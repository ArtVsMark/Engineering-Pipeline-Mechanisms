"""Механизм, читающий площадку, обязан получить от прогона токен.

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ ГЕЙТ. Отсутствие токена здесь не роняет шаг: разбор
отказа сведён в транспорт, и механизм честно говорит «состояние не перечитано,
вердикт по снимку» и работает дальше. Свойство хорошее — необязательный канал
не роняет основную работу (084), — но у него есть цена: **забытый токен
выглядит как рабочий шаг**. Механизм при этом делает не то, ради чего написан.

ЗАМЕР, ИЗ-ЗА КОТОРОГО ГЕЙТ НАПИСАН. `scripts/check_pr_meta.py` умеет
перечитывать изменение у площадки с первого дня: снимок события — состояние на
момент срабатывания, а метки проставляет шаг открытия долями секунды позже.
Умение было, а токена шагу в `ci.yml` не передали — и гейт полгода выносил
вердикт по снимку. Всплыло 09.09 на изменении #55: четыре зоны навесились
четырьмя событиями подряд, выживший прогон унёс снимок с частью из них, и
изменение отвергли за «тронуты файлы зон, которых нет на изменении».

Проверяется не намерение, а проводка: если скрипт зовёт
``ghrest.token_from_env()``, то у шага, который его запускает, обязан стоять
``GH_TOKEN`` или ``GITHUB_TOKEN``
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
WORKFLOWS = ROOT / ".github" / "workflows"

#: Имена, под которыми транспорт ищет токен прогона (`ghrest.token_from_env`).
TOKEN_NAMES = {"GH_TOKEN", "GITHUB_TOKEN"}
#: Вызов скрипта в шаге прогона: имя файла берётся из строки запуска.
CALL_RE = re.compile(r"python3?\s+scripts/([\w-]+\.py)")


def reads_the_platform() -> set[str]:
    """Скрипты, которым нужен токен прогона, — по коду, а не по списку руками."""
    found = set()
    for path in SCRIPTS.glob("*.py"):
        if path.name == "ghrest.py":
            continue
        if "token_from_env" in path.read_text(encoding="utf-8"):
            found.add(path.name)
    return found


def steps() -> list[tuple[str, str, dict[str, Any]]]:
    """Все шаги всех прогонов: файл, имя шага и его тело."""
    collected: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for job in (document.get("jobs") or {}).values():
            for step in (job or {}).get("steps") or []:
                if isinstance(step, dict):
                    collected.append((path.name, str(step.get("name") or ""), step))
    return collected


def calls() -> list[tuple[str, str, str, dict[str, Any]]]:
    """Шаги, запускающие скрипт проекта: прогон, шаг, скрипт и тело шага."""
    wanted = reads_the_platform()
    found: list[tuple[str, str, str, dict[str, Any]]] = []
    for workflow, name, step in steps():
        for script in CALL_RE.findall(str(step.get("run") or "")):
            if script in wanted:
                found.append((workflow, name, script, step))
    return found


def test_the_gate_found_its_subject() -> None:
    """Предмет проверки найден: иначе гейт зелен на пустоте (075)."""
    assert reads_the_platform(), "ни один скрипт не читает площадку — предмет не найден"
    assert calls(), "ни один шаг прогона не запускает такой скрипт — предмет не найден"


@pytest.mark.parametrize(
    ("workflow", "name", "script", "step"),
    calls(),
    ids=lambda item: item if isinstance(item, str) else "",
)
def test_a_step_reading_the_platform_gets_a_token(
    workflow: str, name: str, script: str, step: dict[str, Any]
) -> None:
    """У шага, запускающего читателя площадки, объявлен токен прогона.

    Забытый токен не краснеет сам: механизм скажет «вердикт по снимку» и
    продолжит. Поэтому его ловит гейт, а не прогон.
    """
    declared = set(step.get("env") or {})
    assert declared & TOKEN_NAMES, (
        f"{workflow}, шаг «{name}»: {script} читает площадку, а токена у шага нет — "
        "механизм молча вернётся к снимку и вынесет вердикт по прошлому (049)"
    )
