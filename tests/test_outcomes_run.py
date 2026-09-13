"""Реестр: у каждого объявленного исхода механизма есть прогон (145).

ЧТО ЗДЕСЬ ПРЕДМЕТ. Механизм объявляет исходы константами `EXIT_*` и обещает
ими поведение: ноль — чисто, находка — своим числом, третий — «не отработал».
Объявление поведением не является. Прогон, которого нет, не расходится с
обещанием вслух: он молчит, и расхождение находит потребитель.

ПОЧЕМУ ЭТОГО НЕ ЛОВИЛА РОСПИСЬ ОТКАЗОВ. `test_gates_reject.py` спрашивает
одно: есть ли у гейта прогон ТОГО, ЧТО ОН ОБЯЗАН ОТВЕРГНУТЬ. Предмет там —
файлы с приставкой `check_`, а исход — только отказ. За границей остались и
механизмы без приставки (`stuck.py`, `drift.py`, `hail.py`), и два других
исхода у самих гейтов. Замер 13.09.2026: из 102 объявленных исходов **35** не
прогонялись ни разу, и большинство — третий, который снаружи неотличим от
«чисто»
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ПОЧЕМУ ДОЛГ ОБЪЯВЛЕН, А НЕ ЗАКРЫТ ОДНИМ ЗАХОДОМ. Тридцать пять прогонов в
одном изменении — это тридцать пять новых разборов за раз, и читателю столько
за раз не понять (`docs/decisions/008`). Пробел назван поимённо в
`.rules/outcomes.json` и может только убывать; ровнять его молчанием было бы
хуже неполноты
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import json
from typing import Final

from tests import outcomes
from tests.conftest import ROOT

REGISTRY: Final = ROOT / ".rules" / "outcomes.json"


def debt() -> dict[str, list[str]]:
    """Объявленный долг: механизм → имена исходов без прогона."""
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {str(k): [str(one) for one in v] for k, v in doc["долг"].items()}


def test_the_registry_names_why_and_how_it_shrinks() -> None:
    """У реестра есть причина и правило сокращения — молчание не состояние (154)."""
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for key in ("почему", "как сокращается"):
        assert doc.get(key, "").strip(), f"в реестре исходов нет поля «{key}»"


def test_the_subject_is_found() -> None:
    """Механизмы с объявленными исходами в дереве есть — иначе реестр пуст (075)."""
    said = outcomes.with_outcomes()
    assert said, "ни один механизм не объявляет исходов — предмет реестра не найден"


def test_the_debt_names_only_real_outcomes() -> None:
    """Каждая строка долга указывает на существующий исход существующего механизма.

    Строка про снятый механизм или переименованную константу — это долг,
    который никогда не закроется и никого ни к чему не обязывает.
    """
    said = outcomes.with_outcomes()
    for script, names in debt().items():
        assert script in said, (
            f"долг называет «{script}», а такого механизма с объявленными исходами нет: "
            "строка не закроется никогда — вычеркните её"
        )
        for name in names:
            assert name in said[script], (
                f"долг называет исход «{name}» у {script}, а тот его не объявляет"
            )


def test_the_debt_has_no_closed_lines() -> None:
    """Прогнанный исход из долга вычеркнут: реестр, ничего не держащий, красен.

    Пока закрытая строка лежит в списке, реестр показывает долг, которого нет,
    и следующий заход верит числу, а не дереву
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    gaps = outcomes.gaps()
    closed = {
        script: sorted(set(names) - set(gaps.get(script, []))) for script, names in debt().items()
    }
    closed = {script: names for script, names in closed.items() if names}
    assert not closed, (
        "эти исходы уже прогоняются, а в долге ещё числятся: "
        + "; ".join(f"{script}: {', '.join(names)}" for script, names in sorted(closed.items()))
        + " — вычеркните их из .rules/outcomes.json"
    )


def test_no_outcome_stays_unrun_outside_the_debt() -> None:
    """Новый объявленный исход приезжает со своим прогоном, а не в долг.

    Долг — это хвост, снятый замером один раз, а не место, куда дописывают
    свежее. Механизм, объявивший исход и не прогнавший его, обещает поведение,
    которого никто не проверял
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    """
    known = debt()
    fresh = {
        script: sorted(set(names) - set(known.get(script, [])))
        for script, names in outcomes.gaps().items()
    }
    fresh = {script: names for script, names in fresh.items() if names}
    assert not fresh, (
        "исходы объявлены, но не прогоняются и в долге не числятся: "
        + "; ".join(f"{script}: {', '.join(names)}" for script, names in sorted(fresh.items()))
        + " — прогоните их, а не дописывайте в .rules/outcomes.json"
    )
