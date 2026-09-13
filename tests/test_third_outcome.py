"""Третий исход прогоняется, а не только объявляется (145).

ЧТО ЗДЕСЬ ПРЕДМЕТ. «Не отработал» — самый опасный из трёх исходов: снаружи он
неотличим от «чисто», и гейт, у которого этот путь ни разу не проходили,
обещает поведение, которого никто не видел
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Замер 13.09.2026 (`.rules/outcomes.json`): третий исход не прогонялся у
семнадцати механизмов.

КАК ОН ДОСТИГАЕТСЯ. У гейтов, читающих дерево и площадку, — пустым входом:
дерева нет, базы нет, репозиторий не назван. Это не выдуманная поломка, а
ровно то, что случается на обрезанном чекауте и в чужом каталоге.

Исход спрашивается У ГЕЙТА — по его собственной константе, а не назначается
числом: у части механизмов объявленные числа другие, и назначенное ожидание
«чинило» бы исправное
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from tests import outcomes
from tests.conftest import RunScript

#: Гейты, чей третий исход достигается ПУСТЫМ входом. Список разрешительный
#: ([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)):
#: механизм, которому для отказа нужен другой вход, сюда не дописывается — ему
#: нужен свой прогон, а не общий.
WITHOUT_INPUT: Final = (
    "check_contract.py",
    "check_derived_refs.py",
    "check_env.py",
    "check_new_is_tested.py",
    "check_required_context.py",
    "check_reread.py",
    "check_rule_links.py",
)

#: Чем окружение подсказало бы гейту вход, которого в пустом каталоге нет.
#: Пустая строка у `run_script` значит «убрать ключ», а не «задать пустым».
NO_HINTS: Final = {
    "GITHUB_REPOSITORY": "",
    "GITHUB_BASE_REF": "",
    "GH_TOKEN": "",
    "GITHUB_TOKEN": "",
}


@pytest.mark.parametrize("gate", WITHOUT_INPUT)
def test_a_gate_without_input_says_it_did_not_run(
    run_script: RunScript, tmp_path: Path, gate: str
) -> None:
    """Пустой вход — это «не отработал», а не «чисто» и не находка."""
    result = run_script(gate, cwd=tmp_path, env=dict(NO_HINTS))
    assert result.code == outcomes.declared(gate)["EXIT_BROKEN"], (
        f"{gate} на пустом входе ответил {result.code}, а объявил "
        f"{outcomes.declared(gate)['EXIT_BROKEN']}: вывод — {result.text.strip()[:200]}"
    )
    assert "не отработал" in result.text, (
        f"{gate} назвал третий исход, но не сказал этого словами — "
        "красное, не называющее своей причины, учит не смотреть на красное"
    )
