"""Порядок сбора замеряется на КАЖДОМ прогоне, а не однажды руками.

Связанность тестов видна только другим порядком. Прежде набор ходил
единственным — прямым, — и связанность такого рода находилась замером руками:
обратный порядок файлов нашёл двойную личность модулей за один заход (#285).
Держать это было нечем.

ПОЧЕМУ НЕ ВТОРОЙ ЗАХОД. Второй полный прогон на каждом изменении удваивает
время набора, а заход по расписанию требует адресата, переживающего прогон, —
реестра под такую находку у проекта нет
([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)).
Случайный порядок не стоит ничего и адресата не требует: связанность становится
СВОИМ красным на изменении, у которого адресат уже есть — оклик.

ЗЕРНО — НОМЕР ПРОГОНА, А НЕ ЧАСЫ. Логи прогонов из части окон не читаются
вовсе, и напечатанное в них зерно пропало бы вместе с логом; номер прогона виден
в его адресе, то есть порядок воспроизводим снаружи
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).
"""

from __future__ import annotations

import re
from typing import Final

import pytest
import yaml

from tests.conftest import ROOT

CI: Final = ROOT / ".github" / "workflows" / "ci.yml"
#: Джобы, которые гоняют набор. Перечислены, а не выведены: список
#: разрешённого, и новый прогонщик набора обязан попасть сюда осознанно (068).
RUNNERS: Final = ("test-matrix", "test-next")


def steps_of(job: str) -> list[dict[str, object]]:
    """Шаги названного джоба прогона гейтов."""
    document = yaml.safe_load(CI.read_text(encoding="utf-8"))
    jobs = document.get("jobs") or {}
    assert job in jobs, f"в прогоне нет джоба {job} — предмет проверки не найден (075)"
    steps = (jobs[job] or {}).get("steps") or []
    return [step for step in steps if isinstance(step, dict)]


def suite_step(job: str) -> dict[str, object]:
    """Шаг, который запускает набор."""
    found = [step for step in steps_of(job) if "pytest " in str(step.get("run") or "")]
    assert len(found) == 1, f"{job}: шагов с набором не один, а {len(found)}"
    return found[0]


@pytest.mark.parametrize("job", RUNNERS)
def test_the_suite_runs_in_a_random_order(job: str) -> None:
    """Набор идёт случайным порядком: связанность иначе не всплывает."""
    run = str(suite_step(job).get("run") or "")
    assert "--randomly-seed" in run, f"{job}: порядок сбора снова единственный"


@pytest.mark.parametrize("job", RUNNERS)
def test_the_seed_comes_from_the_run_number(job: str) -> None:
    """Зерно берётся у номера прогона — иначе порядок не воспроизвести.

    Зерно, напечатанное только в логе, пропадает вместе с ним: логи прогонов из
    части окон не читаются. Номер прогона виден в адресе прогона.
    """
    step = suite_step(job)
    env = step.get("env") or {}
    assert isinstance(env, dict), f"{job}: у шага набора нет окружения с зерном"
    said = " ".join(str(value) for value in env.values())
    assert "github.run_id" in said, f"{job}: зерно не привязано к номеру прогона"


@pytest.mark.parametrize("job", RUNNERS)
def test_the_seed_is_passed_by_environment_not_substitution(job: str) -> None:
    """Подстановка площадки в тело команды не идёт, и это не вкус.

    Блок с `${{` свой прогон не раскрывает и считает требующим площадки — то
    есть шаг набора перестал бы проверяться до толчка. Тот же приём, что у
    соседних шагов файла: ввод идёт окружением.
    """
    run = str(suite_step(job).get("run") or "")
    assert "${{" not in run, f"{job}: подстановка площадки внутри команды набора"


@pytest.mark.parametrize("job", RUNNERS)
def test_the_plugin_is_declared_where_the_run_installs_it(job: str) -> None:
    """Плагин объявлен строкой установки прогона — там же, где прочие границы.

    Второй список тех же версий разошёлся бы с первым молча (022); сверку
    окружения с деревом ведёт `check_env.py`, читая ровно эти строки.
    """
    installs = [
        str(step.get("run") or "")
        for step in steps_of(job)
        if "pip install" in str(step.get("run") or "")
    ]
    assert installs, f"{job}: шага установки не нашлось"
    said = " ".join(installs)
    assert re.search(r'"pytest-randomly>=\d+,<\d+"', said), (
        f"{job}: плагин случайного порядка не объявлен с границами версий (073)"
    )
