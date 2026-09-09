"""Ответ каталогу проверяется на полноту формы, а не на наличие файла.

Правило 128: обязательное поле проверяется на полноту, а не на непустоту.
Правило 154: «не держится ничем» обязано назвать причину, иначе это молчание.

Отдельно проверяется, что адрес механизма **разрешим**: путь, который в дереве
не существует, — это ложный механизм. Ответ «держится гейтом по адресу X» при
отсутствующем X хуже отсутствия ответа: он выглядит выполненным.

Полноту относительно живого каталога держит не этот тест, а прогон
`rules-inbox`: число правил меняется в соседнем репозитории, и сверять его
дереву неоткуда.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
BINDINGS = ROOT / ".rules" / "bindings.json"
PROPOSALS = ROOT / ".rules" / "proposals.json"
# Поля, которые в предложении заполняет каталог при приёме, а не проект.
OWNED_BY_CATALOGUE = {"id", "number", "rule"}
STATUSES = {"active", "rejected", "not-applicable", "unreviewed"}
MECHANISMS = {"gate", "pipeline", "document", "none"}
# Похоже на адрес в этом дереве: с косой чертой или с расширением.
ADDRESS_RE = re.compile(r"[\w./*-]+\.(?:py|md|json|ya?ml)|[\w.-]+/[\w./*-]+")


def load() -> dict[str, Any]:
    """Читает ответ проекта каталогу."""
    document: dict[str, Any] = json.loads(BINDINGS.read_text(encoding="utf-8"))
    return document


def answers() -> dict[str, dict[str, str]]:
    """Отдаёт ответы по правилам."""
    rules: dict[str, dict[str, str]] = load()["rules"]
    return rules


def test_every_rule_has_an_answer() -> None:
    """Пустых записей нет: у каждого правила каталога есть свой ответ."""
    rules = answers()
    assert rules, "ответ пуст — предмет проверки не найден (075)"
    assert all(isinstance(item, dict) and item.get("status") for item in rules.values())


def test_statuses_are_from_the_contract() -> None:
    """Статус — из четырёх объявленных контрактом, а не произвольное слово."""
    assert {item["status"] for item in answers().values()} <= STATUSES


def test_active_names_its_mechanism_and_address() -> None:
    """У активного ответа названы механизм и адрес, а не только статус."""
    for number, item in answers().items():
        if item["status"] != "active":
            continue
        assert item.get("mechanism") in MECHANISMS, f"{number}: механизм не назван"
        if item["mechanism"] != "none":
            assert item.get("where"), f"{number}: механизм назван, адрес — нет"
        else:
            assert item.get("why"), f"{number}: механизма нет, причина не названа (154)"


def test_negative_answers_name_the_reason() -> None:
    """«Отвергнуто» и «не относится» обязаны назвать причину (154, 184)."""
    for number, item in answers().items():
        if item["status"] in {"rejected", "not-applicable"}:
            assert item.get("why"), f"{number}: отрицательный ответ без причины — это молчание"


@pytest.mark.parametrize(
    "number",
    sorted(
        n
        for n, i in answers().items()
        # У механизма «none» адреса нет по построению: правило признано
        # действующим и не держится ничем, причина названа в why. Такой ответ
        # проверяется правилом 154, а не адресом.
        if i["status"] == "active" and i.get("mechanism") != "none"
    ),
)
def test_declared_address_resolves(number: str) -> None:
    """Адрес механизма существует в дереве: иначе это ложный механизм."""
    where = answers()[number].get("where", "")
    candidates = [
        address
        for address in ADDRESS_RE.findall(where)
        # Чужие адреса — действие каталога, ссылки на его записи — здесь не
        # разрешаются намеренно: их владелец другой, и правит их он (185).
        if "@" not in address and not address.startswith(("ArtVsMark/", "http"))
    ]
    # Раньше набор без адреса молча зеленел, и ответ `"where": "."` прошёл
    # гейт 183 целиком: проверять было нечего, и «нечего проверять» считалось
    # «проверено». Гейт, не нашедший предмета, обязан падать (075).
    assert candidates, (
        f"{number}: механизм назван, а адреса в прозе нет — "
        f"проверять нечего, и это отказ, а не «зелено»: {where!r}"
    )
    resolved = [
        address for address in candidates if (ROOT / address).exists() or list(ROOT.glob(address))
    ]
    assert resolved, f"{number}: ни один адрес не разрешается: {candidates}"


def test_proposals_assign_no_numbers() -> None:
    """Номер правилу присваивает каталог при приёме, а не проект (185).

    Два проекта, выбравшие номер независимо, дают столкновение, которое уже
    нечем починить: номера не переиспользуются. Поэтому поля ``id``, ``number``
    и ``rule`` в предложении — ошибка, и это сказано гейтом, а не только прозой
    в самом файле. Пустой список — законное состояние («предлагать нечего»);
    отсутствие файла означает другое — «канал не подключён» (075).
    """
    assert PROPOSALS.exists(), "канал предложений не подключён: .rules/proposals.json нет"
    document: dict[str, Any] = json.loads(PROPOSALS.read_text(encoding="utf-8"))
    assert document.get("schema"), "след предложения без версии контракта"
    items = document.get("proposals")
    assert isinstance(items, list), "поле proposals — список, пустой в том числе"
    for item in items:
        assigned = OWNED_BY_CATALOGUE & set(item)
        assert not assigned, f"номер присваивает каталог, а не проект: {sorted(assigned)}"


def test_this_project_leans_on_gates() -> None:
    """Проект про механизмы: доля правил, держащихся гейтом, не должна быть мала.

    Несоответствие этому ожиданию само есть находка: правило про конвейер, у
    которого здесь нет механизма, — либо пробел, либо неверная область.
    """
    active = [item for item in answers().values() if item["status"] == "active"]
    gates = [item for item in active if item.get("mechanism") == "gate"]
    assert len(gates) >= len(active) // 4, "механизмов-гейтов подозрительно мало для этого проекта"
