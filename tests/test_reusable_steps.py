"""Вынесенные шаги: дубль шапки объявлен намеренным — и потому держится.

Площадка требует от переиспользуемого прогона ОТДЕЛЬНОГО ФАЙЛА, и пояснение в
их шапках неизбежно одно на всех: вынести его нечем — комментарий не
подключается, а прогон зовут по адресу файла. Намеренный дубль законен, когда
объявлен
([071](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/071-deliberate-duplication-is-signed.md)),
но объявление без механизма — обещание: копии расходятся молча, и узнают об
этом по разному поведению двух шагов, а не по красному
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЧТО ЗДЕСЬ ДЕРЖИТСЯ: что шапки СОВПАДАЮТ дословно, что каждая объявляет дубль
намеренным, и что каждый вынесенный шаг — действительно вызываемый. Чего НЕ
держится: полезности самого пояснения — это суждение о смысле (057).
"""

from __future__ import annotations

from typing import Final

import pytest
import yaml

from tests.conftest import ROOT, load_script, walk

policy = load_script("pipeline_checks.py")

STEPS: Final = ROOT / ".github" / "workflows"
#: Приставка вынесенного шага.
PREFIX: Final = "step-"
#: Слова, которыми дубль объявляется намеренным. Не «похоже на объявление», а
#: ровно эта строка: признак, принимающий любую прозу о дублях, принял бы и
#: рассуждение о них (166).
DECLARED: Final = "ДУБЛЬ ЭТОЙ ШАПКИ НАМЕРЕННЫЙ"
#: Где кончается общая шапка и начинается своё: строка имени прогона.
UNTIL: Final = "name: "


def steps() -> dict[str, str]:
    """Вынесенные шаги дерева: имя файла → его текст."""
    return {path.name: path.read_text(encoding="utf-8") for path in walk(STEPS, f"{PREFIX}*.yml")}


def head_of(said: str) -> str:
    """Общая шапка: всё до строки имени прогона."""
    return said.split(f"\n{UNTIL}", 1)[0]


def test_the_steps_exist() -> None:
    """Вынесенные шаги в дереве есть — иначе проверка держит пустоту (075)."""
    assert steps(), "вынесенных шагов нет ни одного — сверять нечего"


@pytest.mark.parametrize("name", sorted(steps()), ids=lambda one: one)
def test_every_step_declares_its_duplication(name: str) -> None:
    """Каждый шаг объявляет дубль шапки намеренным (071).

    Необъявленный дубль неотличим от копипасты, и следующая правка починит
    один файл из девяти.
    """
    assert DECLARED in head_of(steps()[name]), f"{name}: дубль шапки не объявлен намеренным"


def test_all_the_heads_are_the_same() -> None:
    """Шапки совпадают ДОСЛОВНО: объявленный дубль обязан быть дублем.

    Объявить дубль и дать копиям разойтись — хуже, чем не объявлять: читатель
    первой копии считает, что прочёл все девять
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    heads = {name: head_of(said) for name, said in steps().items()}
    first = sorted(heads)[0]
    apart = sorted(name for name, said in heads.items() if said != heads[first])
    assert not apart, (
        f"шапки разошлись с «{first}»: {apart} — объявленный дубль перестал быть дублем"
    )


@pytest.mark.parametrize("name", sorted(steps()), ids=lambda one: one)
def test_every_step_is_actually_callable(name: str) -> None:
    """Файл с приставкой шага — действительно ВЫЗЫВАЕМЫЙ прогон.

    Приставка имени — объявление, а не свойство: прогон без `workflow_call`
    площадка звать откажется, и узнает об этом потребитель, а не мы (045).
    """
    said = yaml.safe_load(steps()[name])
    events = said.get("on", said.get(True)) or {}
    names = set(events) if isinstance(events, dict) else set(events or [])
    assert policy.CALLED in {str(one) for one in names}, (
        f"{name}: приставка обещает вызываемый прогон, а события «{policy.CALLED}» нет"
    )
