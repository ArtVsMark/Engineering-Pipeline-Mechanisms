"""Наши виды механизмов — виды договора ответа каталога (#1566).

Виды определяет издатель договора, каталог; `kinds.py` их читает и цитирует с
названного тега. Проверяется, что цитата снята с того тега, к которому прибит
наш вызов каталога, и что наши виды в неё входят: расхождение с издателем
иначе не краснеет никогда (022, 090).
"""

import re

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


def test_our_kinds_are_the_contracts_kinds() -> None:
    """Каждый наш вид — вид договора, а машинные совпадают с машинными договора."""
    ours = {*kinds.MACHINE, kinds.DOCUMENT, kinds.SKILL, kinds.PROCESS_STEP}
    assert ours <= kinds.CONTRACT_KINDS, (
        f"виды не из договора: {sorted(ours - kinds.CONTRACT_KINDS)}"
    )
    assert kinds.MACHINE == kinds.CONTRACT_MACHINE
    assert kinds.CONTRACT_MACHINE <= kinds.CONTRACT_KINDS
    assert kinds.PROCESS_STEP not in kinds.MACHINE, "устаревший шаг процесса машиной не держит"
