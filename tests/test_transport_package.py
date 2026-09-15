"""Общий низ конвейера — пакет, и проект его первый потребитель.

ЗАЧЕМ ПАКЕТ. Замер по пяти проектам семьи на 09.09.2026: у каждого своя копия
транспорта, и ни одна пара не совпала — `gh_rest.py` от 131 строки до 2436.
Общий модуль начинается с самого дешёвого и самого ценного куска (эпик #2, фаза 2),
и живёт он рядом с эталонным конвейером: потребители прибивают его к ТЕГУ выпуска,
а не к общей ветке. Разбор и отвергнутые варианты —
`docs/decisions/024-the-transport-is-a-package-pinned-by-a-tag.md`.

ОТВЕРГАЕМОЕ ЗДЕСЬ ТРОЙНОЕ:

* **вторая копия транспорта в дереве** — ровно то, от чего пакет и заводят;
* **джоб, который зовёт механизм и не ставит пакет** — заход упадёт на импорте, и
  причиной будет не поломка механизма, а незаявленное окружение;
* **версия, которой нет или которая не число** — потребитель прибивается к тегу, но
  установленный пакет обязан называть свою версию честно (164).
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT

PACKAGE: Final = ROOT / "packages" / "transport"
SCRIPTS: Final = ROOT / "scripts"
WORKFLOWS: Final = ROOT / ".github" / "workflows"
#: Модули общего низа: транспорт к площадке и обрезка вывода. Обрезка едет с
#: транспортом потому, что он сам её и зовёт, а вторая копия обрезки запрещена
#: правилом 016 — тем же, ради которого она одна на проект.
SHARED: Final = ("ghrest", "report")
#: Как джоб ставит пакет. Строка одна на все прогоны: второй способ разошёлся бы
#: с первым молча (090).
INSTALL: Final = "./packages/transport"


def manifest() -> dict[str, Any]:
    """Объявление пакета."""
    said: dict[str, Any] = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    return said


def imports_of(path: Path) -> set[str]:
    """Имена, которые модуль импортирует напрямую."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {one.name.split(".")[0] for one in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def scripts_needing_the_package() -> set[str]:
    """Механизмы, которым нужен общий низ, — включая тех, кто зовёт его через соседа.

    Считается ЗАМЫКАНИЕ импортов, а не первый слой: `debt` не знает про транспорт,
    но зовёт `findings`, который знает. Список, написанный рукой, отстал бы от
    первого же нового импорта (005).
    """
    graph = {path.stem: imports_of(path) for path in sorted(SCRIPTS.glob("*.py"))}
    need = {name for name, deps in graph.items() if deps & set(SHARED)}
    while True:
        grown = {name for name, deps in graph.items() if deps & need} | need
        if grown == need:
            return need
        need = grown


def jobs_running_scripts() -> list[tuple[str, str, str, str]]:
    """Джобы прогонов, зовущие механизмы: файл, имя джоба, команды, строки установки."""
    found: list[tuple[str, str, str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for key, body in (document.get("jobs") or {}).items():
            steps = [one for one in (body or {}).get("steps") or [] if isinstance(one, dict)]
            runs = "\n".join(str(one.get("run") or "") for one in steps)
            installs = "\n".join(line for line in runs.splitlines() if "pip install" in line)
            if "python scripts/" in runs:
                found.append((path.name, str(key), runs, installs))
    return found


def test_the_package_declares_the_shared_bottom() -> None:
    """Пакет объявляет ровно те модули, которые в нём лежат (075)."""
    said = manifest()
    tools = said.get("tool", {})
    declared = tuple((tools.get("setuptools") or {}).get("py-modules") or ())
    assert declared == SHARED, f"объявлено {declared}, а общий низ — {SHARED}"
    for name in SHARED:
        assert (PACKAGE / f"{name}.py").is_file(), f"{name}.py в пакете нет"
    project = said.get("project") or {}
    assert project.get("name") == "engineering-pipeline-transport"
    assert project.get("dynamic") == ["version"], "версия читается из источника, а не вписана"


def test_the_package_version_is_a_number_of_its_own() -> None:
    """У пакета своя версия: она о поверхности Python, а не о конвейере (164)."""
    said = (PACKAGE / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", said), f"версия пакета не вида МАЖОР.МИНОР.ПАТЧ: {said}"
    contract = (ROOT / "CONTRACT_VERSION").read_text(encoding="utf-8").strip()
    assert said != contract, (
        "версия пакета совпала с версией контракта: числа версионируют разное, и "
        "совпадение прочтётся как одно число в двух местах (022, 164)"
    )


def test_no_second_copy_of_the_shared_bottom_lives_in_the_tree() -> None:
    """Копии транспорта рядом с механизмами нет — ровно от неё и уезжали.

    Замер семьи: пять копий, ни одна не совпала. Копия в своём же дереве — тот же
    класс, только ближе.
    """
    for name in SHARED:
        assert not (SCRIPTS / f"{name}.py").exists(), (
            f"scripts/{name}.py вернулся: общий низ живёт в пакете, и второй копии быть не может"
        )


@pytest.mark.parametrize(
    "where",
    jobs_running_scripts(),
    ids=lambda one: f"{one[0]}:{one[1]}" if isinstance(one, tuple) else str(one),
)
def test_a_job_calling_a_mechanism_installs_the_package(where: tuple[str, str, str, str]) -> None:
    """Джоб, зовущий механизм из общего низа, ставит пакет.

    Список нужных считается ЗАМЫКАНИЕМ импортов, а не рукой: иначе первый же новый
    импорт вывел бы джоб из-под проверки молча (005, 090).
    """
    name, job, runs, installs = where
    called = set(re.findall(r"python scripts/([\w_]+)\.py", runs))
    if not called & scripts_needing_the_package():
        pytest.skip("этот джоб зовёт только механизмы без общего низа")
    assert INSTALL in installs, (
        f"{name}:{job} зовёт {sorted(called & scripts_needing_the_package())}, "
        f"а пакет не ставит: заход упал бы на импорте"
    )


def test_the_consumer_pin_is_written_down() -> None:
    """Форма прибивки названа там, где её ищет потребитель (113)."""
    said = (PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
    assert "#subdirectory=packages/transport" in said, "не сказано, как ставить пакет снаружи"
    assert "@v" in said, "не сказано, что прибиваются к ТЕГУ выпуска, а не к общей ветке"
