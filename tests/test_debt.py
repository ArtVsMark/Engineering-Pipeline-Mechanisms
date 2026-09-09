"""Долг перед планом: находки и незакрытая работа по правилам.

Шаг совещательный, поэтому проверяется не «краснеет ли он», а два свойства:
числа он ЧИТАЕТ, а не считает заново, и непрочитанное не выдаёт за пустое.
Второе важнее: остаток, показанный нулём вместо «неизвестно», — тихий
запасной путь (045).
"""

from __future__ import annotations

import pytest

from tests.conftest import ROOT, RunScript, load_script

debt = load_script("debt.py")

INBOX = """## Ступень 0 — незакрытая работа по правилам

**Задач по правилам: 3. Правил без ответа или «не рассмотрено»: 129.
Признано действующими, но держится ничем: 7.**

⚠️ **Контракт разошёлся.** формат ответа объявлен как 1.0, каталог ждёт 1.2 —
ответы перечитываются под новый контракт
"""


def test_three_numbers_are_read_from_the_inbox() -> None:
    """Три числа правила 177 читаются из задачи, которую ведёт каталог."""
    assert debt.rules_debt(INBOX) == (3, 129, 7)


@pytest.mark.parametrize("body", ["", "задача есть, а строки счёта нет", "Задач по правилам: 3."])
def test_a_missing_count_is_not_zero(body: str) -> None:
    """Нет строки счёта — «неизвестно», а не «долга нет».

    Ноль вместо неизвестности читается как «всё разобрано» и снимает
    приоритет с источника, который никто не проверял.
    """
    assert debt.rules_debt(body) is None


def test_a_diverged_contract_is_reported() -> None:
    """Расхождение контракта — третий вид долга по 177, и он назван словами."""
    note = debt.contract_note(INBOX)
    assert note is not None and "1.2" in note


def test_no_contract_note_when_it_matches() -> None:
    """Сошедшийся контракт молчит: пустое состояние не выдумывается."""
    assert debt.contract_note("**Задач по правилам: 0. …**") is None


def test_the_step_does_not_count_rules_itself() -> None:
    """Гейт на дрейф: числа читаются, а не считаются вторым разом (022).

    Свой счёт по `.rules/bindings.json` разошёлся бы с каталогом молча —
    оба числа выглядят одинаково правдоподобно, а спорят они между собой.
    """
    source = (ROOT / "scripts" / "debt.py").read_text(encoding="utf-8")
    assert "bindings.json" not in source, "шаг завёл второй счёт того же"


def test_unread_debt_is_not_reported_as_none(run_script: RunScript) -> None:
    """Без токена долг НЕИЗВЕСТЕН, и шаг говорит это словами."""
    run = run_script("debt.py", env={"GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""})
    assert run.code == 3, run.text
    assert "не прочитан" in run.text


def test_the_step_names_where_the_order_is_written(run_script: RunScript) -> None:
    """Вывод ведёт к договору и к правилу, а не пересказывает их (029)."""
    run = run_script("debt.py", env={"GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""})
    assert "behaviour.md" in run.text or "177" in run.text


def test_the_order_puts_debts_before_the_plan() -> None:
    """Договор ставит находки и правила выше плана, а не рядом с ним.

    Гейт на согласованность документа: по этому порядку окно выбирает работу,
    и перестановка строк меняет поведение проекта.
    """
    text = (ROOT / "docs" / "behaviour.md").read_text(encoding="utf-8")
    findings_at = text.index("находки внешнего взгляда, пережившие слияние")
    rules_at = text.index("незакрытая работа по правилам каталога")
    plan_at = text.index("задача из трекера и план автора")
    assert findings_at < rules_at < plan_at


def test_the_charter_cites_the_rule_behind_the_order() -> None:
    """Приоритет правил — требование каталога, а не местное изобретение."""
    text = (ROOT / "docs" / "behaviour.md").read_text(encoding="utf-8")
    assert "177-unfinished-rule-work-comes-first" in text


def test_the_step_is_declared_advisory() -> None:
    """Класс шага объявлен данными: долг не держит слияние, но виден."""
    answer = (ROOT / ".pipeline.yml").read_text(encoding="utf-8")
    assert "debt:" in answer and "advisory" in answer
