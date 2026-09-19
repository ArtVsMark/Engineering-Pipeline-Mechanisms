"""Общий низ конвейера — пакет, и проект его первый потребитель.

ЗАЧЕМ ПАКЕТ. Замер по пяти проектам семьи на 09.09.2026: у каждого своя копия
транспорта, и ни одна пара не совпала — `gh_rest.py` от 131 строки до 2436.
Общий модуль начинается с самого дешёвого и самого ценного куска (эпик #2, фаза 2),
и живёт он рядом с эталонным конвейером: потребители прибивают его к ТЕГУ выпуска,
а не к общей ветке. Разбор и отвергнутые варианты —
`docs/decisions/024-the-transport-is-a-package-pinned-by-a-tag.md`.

ОТВЕРГАЕМОЕ ЗДЕСЬ ТРОЙНОЕ:

* **вторая копия транспорта в дереве** — ровно то, от чего пакет и заводят;
* **шаг, который зовёт механизм РАНЬШЕ установки пакета или мимо её условия** —
  заход упадёт на импорте, и причиной будет не поломка механизма, а незаявленное
  окружение. Наличия строки где-нибудь в джобе НЕДОСТАТОЧНО, и это замер: в
  `task-items.yml` установка стояла ниже трёх зовущих шагов и под условием «секрет
  есть», гейт молчал, а джоб краснел трижды подряд с падением
  `ModuleNotFoundError: ghrest` (15.09.2026). Проверка, которая смотрит только на
  наличие, не ловит порядок — а порядок здесь и есть предмет (195);
* **версия, которой нет или которая не число** — потребитель прибивается к тегу, но
  установленный пакет обязан называть свою версию честно (164).
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, walk

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
    graph = {path.stem: imports_of(path) for path in walk(SCRIPTS, "*.py")}
    need = {name for name, deps in graph.items() if deps & set(SHARED)}
    while True:
        grown = {name for name, deps in graph.items() if deps & need} | need
        if grown == need:
            return need
        need = grown


#: Шаги, чьё условие ВЛЕЧЁТ условие установки, — и почему именно влечёт.
#: Список разрешительный, и у каждой строки своя причина (068, 154). Вычислять
#: следование одного выражения площадки из другого гейт не берётся: это был бы
#: свой толкователь `if`, который разойдётся с площадкой молча. Поэтому
#: расхождение он НАЗЫВАЕТ, а снимается оно строкой здесь — видимой и
#: перечитываемой, в отличие от догадки внутри разбора (051, 195).
IMPLIED: Final = {
    "review.yml:late-look:ответ позднего взгляда получает адресата": (
        "шаг идёт по `steps.late.outcome == 'success'`, а сам `late` стоит под тем же "
        "условием, что установка: пропущенный шаг даёт `skipped`, а не `success`, "
        "то есть успех `late` уже означает, что установка случилась"
    ),
}
#: Слово, которым разбор называет расхождение по условию. Отдельной строкой,
#: потому что по ней исключение и узнаётся: два написания разошлись бы молча.
BY_GUARD: Final = "установка стоит под условием"

#: Как шаг зовёт механизм. Имя механизма — вторая группа.
CALLS: Final = re.compile(r"python[0-9.]*\s+(scripts/([\w_]+)\.py)")


@dataclass(frozen=True, slots=True)
class Call:
    """Место, где шаг зовёт механизм, и что к этому моменту стоит."""

    where: str
    """Файл и джоб: `task-items.yml:task-items`."""
    step: str
    """Имя зовущего шага — им же называется и отказ."""
    names: tuple[str, ...]
    """Механизмы, которые шаг зовёт и которым нужен общий низ."""
    why: str
    """Почему окружения нет; пустая строка — есть."""


def steps_of(body: Any) -> list[dict[str, Any]]:
    """Шаги джоба В ПОРЯДКЕ ОБЪЯВЛЕНИЯ — порядок здесь и есть предмет."""
    return [one for one in (body or {}).get("steps") or [] if isinstance(one, dict)]


def calls_in(document: Any, name: str, need: set[str]) -> list[Call]:
    """Вызовы механизмов в прогоне, с разбором окружения на момент вызова.

    Разбор идёт ПО ШАГАМ, а не по склейке всех команд джоба: склейка отвечает
    «строка установки где-то есть», а спрашивают у неё «окружение к этому моменту
    стоит». Это разные утверждения, и они разошлись
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

    Условие шага установки учитывается: установка под `if`, которого у зовущего
    шага нет, на его заходе просто не случится. Годной считается установка БЕЗ
    условия или с дословно тем же условием — узко и проверяемо, в отличие от
    попытки вычислить, следует ли одно условие из другого.
    """
    found: list[Call] = []
    if not isinstance(document, dict):
        return found
    for key, body in (document.get("jobs") or {}).items():
        #: Условие шага, который поставил пакет; `None` — установки ещё не было.
        put: str | None = None
        for step in steps_of(body):
            runs = str(step.get("run") or "")
            called = tuple(sorted({m.group(2) for m in CALLS.finditer(runs)} & need))
            # УСТАНОВКА В ТОМ ЖЕ БЛОКЕ СЧИТАЕТСЯ, ЕСЛИ СТОИТ ВЫШЕ ВЫЗОВА.
            # Прежде разбор смотрел только на ПРЕДЫДУЩИЕ шаги, и шаг вида
            # «поставить и тут же позвать» объявлялся непрогнанным — ложная
            # находка, которая учит дробить шаг ради гейта (051). Граница была
            # объявлена и оставлена наблюдением; внешний взгляд назвал её
            # находкой `ca78822` на #369, и закрывается она дешевле, чем
            # объясняется.
            if called and INSTALL in runs and "pip install" in runs:
                at_install = runs.index(INSTALL)
                if all(m.start() > at_install for m in CALLS.finditer(runs) if m.group(2) in need):
                    put = str(step.get("if") or "")
            if called:
                guard = str(step.get("if") or "")
                if put is None:
                    why = "установки пакета до этого шага в джобе нет"
                elif put and put != guard:
                    why = f"установка стоит под условием «{put}», которого у шага нет"
                else:
                    why = ""
                where = f"{name}:{key}"
                found.append(Call(where, str(step.get("name") or runs[:40]), called, why))
            # Установка учитывается ПОСЛЕ разбора вызовов того же шага: шаг,
            # который ставит пакет и тут же зовёт механизм, — законный случай,
            # но своим вызовам он предшествовать не может.
            if INSTALL in runs and "pip install" in runs:
                put = str(step.get("if") or "")
    return found


def all_calls() -> list[Call]:
    """Все вызовы механизмов во всех прогонах дерева."""
    need = scripts_needing_the_package()
    found: list[Call] = []
    for path in walk(WORKFLOWS, "*.y*ml"):
        found += calls_in(yaml.safe_load(path.read_text(encoding="utf-8")), path.name, need)
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


@pytest.mark.parametrize("call", all_calls(), ids=lambda one: f"{one.where}:{one.step}")
def test_a_step_calling_a_mechanism_has_the_package_already(call: Call) -> None:
    """Шаг, зовущий механизм из общего низа, застаёт пакет уже поставленным.

    Предмет — ПОРЯДОК, а не наличие. Прежняя проверка склеивала команды джоба и
    искала строку установки где угодно: она отвечала «строка есть», а спрашивали у
    неё «окружение стоит». В `task-items.yml` разошлось ровно здесь — установка
    ниже трёх зовущих шагов и под чужим условием.

    Список нужных считается ЗАМЫКАНИЕМ импортов, а не рукой: иначе первый же новый
    импорт вывел бы шаг из-под проверки молча (005, 090).
    """
    known = IMPLIED.get(f"{call.where}:{call.step}", "")
    if call.why.startswith(BY_GUARD) and known:
        pytest.skip(f"условие установки влечётся: {known}")
    assert not call.why, f"{call.where} «{call.step}» зовёт {list(call.names)}: {call.why}"


def test_every_declared_implication_is_still_needed() -> None:
    """Объявленное исключение обязано на кого-то указывать (075, 050).

    Исключение, которому больше нечего разрешать, — не «прошло», а мусор: оно
    останется прикрывать шаг, который завтра встанет на то же имя.
    """
    said = {f"{one.where}:{one.step}": one.why for one in all_calls()}
    for key, why in IMPLIED.items():
        assert key in said, f"исключение указывает на несуществующий шаг: {key}"
        assert said[key].startswith(BY_GUARD), (
            f"исключение «{key}» больше не нужно — расхождения по условию нет; "
            f"строку надо убрать, иначе она прикроет следующего молча. Причина была: {why}"
        )


def test_the_gate_catches_an_install_that_comes_too_late() -> None:
    """Установка ПОСЛЕ вызова гейтом отвергается (140).

    Форма — дословно та, на которой он молчал: зовущий шаг впереди, установка
    позади. Без этого разбора обе формы читались одинаково.
    """
    need = scripts_needing_the_package()
    late = {
        "jobs": {
            "job": {
                "steps": [
                    {"name": "зовёт", "run": "python scripts/task_items.py --fate"},
                    {"name": "ставит", "run": f"python -m pip install {INSTALL}"},
                ]
            }
        }
    }
    found = calls_in(late, "выдумка.yml", need)
    assert len(found) == 1, f"вызов не найден вовсе: {found}"
    assert found[0].why == "установки пакета до этого шага в джобе нет"


def test_the_gate_catches_an_install_under_a_condition_of_its_own() -> None:
    """Установка под условием, которого у зовущего шага нет, не считается (045).

    Она просто не случится на его заходе, и отказ придёт с чужим именем — падением
    на импорте вместо «окружение не заявлено».
    """
    need = scripts_needing_the_package()
    guarded = {
        "jobs": {
            "job": {
                "steps": [
                    {
                        "name": "ставит под своим условием",
                        "if": "steps.token.outputs.present == 'yes'",
                        "run": f"python -m pip install {INSTALL}",
                    },
                    {"name": "зовёт без него", "run": "python scripts/task_items.py --sweep"},
                ]
            }
        }
    }
    found = calls_in(guarded, "выдумка.yml", need)
    assert len(found) == 1, f"вызов не найден вовсе: {found}"
    assert "под условием" in found[0].why, found[0].why


def test_an_install_and_a_call_in_one_block_are_accepted() -> None:
    """Шаг, который ставит пакет и тут же зовёт механизм, — законный случай.

    Прежде разбор смотрел только на ПРЕДЫДУЩИЕ шаги, и такой шаг объявлялся
    непрогнанным: ложная находка, которая учит дробить шаг ради гейта (051).
    Граница была объявлена в разборе и оставлена наблюдением; внешний взгляд
    назвал её находкой `ca78822` на #369.
    """
    need = scripts_needing_the_package()
    together = {
        "jobs": {
            "job": {
                "steps": [
                    {
                        "name": "поставить и позвать",
                        "run": f"python -m pip install {INSTALL}\npython scripts/main_red.py",
                    }
                ]
            }
        }
    }
    found = calls_in(together, "выдумка.yml", need)
    assert len(found) == 1 and not found[0].why, found


def test_a_call_above_the_install_in_one_block_is_refused() -> None:
    """Порядок внутри блока решает: вызов ВЫШЕ установки — по-прежнему отказ.

    Иначе закрытие границы превратилось бы в разрешение «где-то в том же шаге»,
    то есть вернуло бы ровно ту слепоту к порядку, ради которой гейт и заведён.
    """
    need = scripts_needing_the_package()
    wrong = {
        "jobs": {
            "job": {
                "steps": [
                    {
                        "name": "позвать и поставить",
                        "run": f"python scripts/main_red.py\npython -m pip install {INSTALL}",
                    }
                ]
            }
        }
    }
    found = calls_in(wrong, "выдумка.yml", need)
    assert len(found) == 1 and found[0].why, "порядок внутри блока перестал решать"


def test_the_gate_lets_the_same_condition_through() -> None:
    """Дословно то же условие у установки и у вызова — законный случай (039).

    Иначе гейт краснел бы на исправном джобе, где оба шага стоят под одним `if`.
    """
    need = scripts_needing_the_package()
    same = {
        "jobs": {
            "job": {
                "steps": [
                    {"if": "x == 'y'", "run": f"python -m pip install {INSTALL}"},
                    {"if": "x == 'y'", "run": "python scripts/task_items.py --sweep"},
                ]
            }
        }
    }
    found = calls_in(same, "выдумка.yml", need)
    assert len(found) == 1 and not found[0].why, found


def test_the_gate_has_a_subject_at_all() -> None:
    """Вызовы в дереве вообще находятся: проверка без предмета не «прошла» (075)."""
    calls = all_calls()
    assert len(calls) >= 10, f"вызовов механизмов найдено {len(calls)} — разбор не видит дерева"
    assert any("task-items" in one.where for one in calls), "джоб разбора задач не найден"


def test_the_consumer_pin_is_written_down() -> None:
    """Форма прибивки названа там, где её ищет потребитель (113)."""
    said = (PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
    assert "#subdirectory=packages/transport" in said, "не сказано, как ставить пакет снаружи"
    assert "@v" in said, "не сказано, что прибиваются к ТЕГУ выпуска, а не к общей ветке"
