"""Наши виды механизмов — виды договора ответа каталога (#1566).

Виды определяет издатель договора, каталог; `kinds.py` их читает и цитирует с
названного тега. Проверяется, что цитата снята с того тега, к которому прибит
наш вызов каталога, и что наши виды в неё входят: расхождение с издателем
иначе не краснеет никогда (022, 090).
"""

import re

import pytest
import yaml

from tests.conftest import ROOT, load_script

kinds = load_script("kinds.py")

#: Прибивка действия ответа каталога в нашем `ci.yml`.
ANSWER_PIN = re.compile(r"Engineering-Incidents-Playbook/\.github/actions/answer@(v[\d.]+)$")


def pinned_answer_tag() -> str:
    """Тег, к которому прибит вызов проверки ответа каталога."""
    flow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    found = {
        hit[1]
        for job in (flow.get("jobs") or {}).values()
        for step in (job or {}).get("steps") or []
        if (hit := ANSWER_PIN.search(str((step or {}).get("uses") or "")))
    }
    assert len(found) == 1, f"прибивок действия ответа каталога не одна: {sorted(found)}"
    return found.pop()


def test_the_contract_quote_is_taken_at_the_pinned_tag() -> None:
    """Цитата видов снята с того тега, к которому прибит вызов каталога.

    Поднял прибивку — перечитай `answer_form.MECHANISMS` и `МАШИННЫЕ` на новом
    теге и подними `CONTRACT_AT`: иначе цитата молча описывает прежний договор.
    """
    assert pinned_answer_tag() == kinds.CONTRACT_AT


def flaws(
    machine: frozenset[str], contract_kinds: frozenset[str], contract_machine: frozenset[str]
) -> list[str]:
    """Расхождения наших видов с цитатой договора; пусто — сходятся."""
    found = []
    ours = {*machine, kinds.DOCUMENT, kinds.SKILL, kinds.PROCESS_STEP}
    if not ours <= contract_kinds:
        found.append(f"виды не из договора: {sorted(ours - contract_kinds)}")
    if machine != contract_machine:
        found.append(f"машинные {sorted(machine)} не машинные договора {sorted(contract_machine)}")
    if not contract_machine <= contract_kinds:
        found.append(
            f"машинные договора не виды договора: {sorted(contract_machine - contract_kinds)}"
        )
    if kinds.PROCESS_STEP in machine:
        found.append("устаревший шаг процесса машиной не держит")
    return found


def test_our_kinds_are_the_contracts_kinds() -> None:
    """Каждый наш вид — вид договора, а машинные совпадают с машинными договора."""
    assert flaws(kinds.MACHINE, kinds.CONTRACT_KINDS, kinds.CONTRACT_MACHINE) == []


@pytest.mark.parametrize("where", ["MACHINE", "CONTRACT_MACHINE"])
def test_a_returned_code_kind_is_refused_wherever_it_is_written(where: str) -> None:
    """Откат — вернуть `code` — краснеет, куда бы его ни вписали (взгляд на #1577).

    Сегодня `MACHINE` присвоен цитате, и равенство их истинно по построению.
    Поэтому откат проверяется двумя путями: `code` литералом в `MACHINE`
    рвёт равенство, а `code` в цитату машинных — вложенность в виды договора.
    """
    machine, contract_machine = kinds.MACHINE, kinds.CONTRACT_MACHINE
    if where == "MACHINE":
        machine = machine | {"code"}
    else:
        machine = contract_machine = contract_machine | {"code"}
    assert flaws(machine, kinds.CONTRACT_KINDS, contract_machine)
