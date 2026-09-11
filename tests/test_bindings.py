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


#: Поля, обязательные у предложения по контракту каталога (export/README.md).
#: Список закрытый и взят оттуда, а не придуман здесь: расхождение форм значило
#: бы, что предложение уедет и не будет принято (162).
PROPOSAL_FIELDS = ("slug", "claim", "incident", "trail")
#: Насколько подробным должен быть инцидент. Число не из вкуса: «что сломалось,
#: С КОНКРЕТИКОЙ» — требование контракта, а строка короче этого конкретики не
#: несёт и заставит каталог спрашивать заново.
INCIDENT_AT_LEAST = 200


def proposals() -> list[dict[str, Any]]:
    """Предложения проекта каталогу."""
    document: dict[str, Any] = json.loads(PROPOSALS.read_text(encoding="utf-8"))
    said = document.get("proposals")
    return list(said) if isinstance(said, list) else []


@pytest.mark.parametrize("item", proposals(), ids=lambda one: str(one.get("slug", "?")))
def test_a_proposal_carries_what_the_catalogue_asks(item: dict[str, Any]) -> None:
    """У предложения есть все поля контракта, и инцидент — с конкретикой.

    Потребитель шлёт ИНЦИДЕНТ, а не готовую запись: что сломалось, с числами и
    последовательностью событий. Предложение без этого каталог принять не может
    — ему придётся спрашивать заново, и правило, родившееся здесь, останется
    здесь (080).
    """
    for field in PROPOSAL_FIELDS:
        assert item.get(field), f"{item.get('slug', '?')}: поля «{field}» нет"
    assert len(str(item["incident"])) >= INCIDENT_AT_LEAST, (
        f"{item['slug']}: инцидент без конкретики — каталогу придётся спрашивать заново"
    )


@pytest.mark.parametrize("item", proposals(), ids=lambda one: str(one.get("slug", "?")))
def test_a_proposal_trail_resolves_in_the_tree(item: dict[str, Any]) -> None:
    """След предложения — артефакт ЭТОГО дерева, где поломка видна (044).

    Ссылка на то, чего нет, превращает инцидент в рассказ: проверить его
    каталог не сможет, а поверить ему — не должен.
    """
    said = str(item.get("trail") or "")
    assert (ROOT / said).exists(), f"{item.get('slug', '?')}: след «{said}» не разрешается"


def test_a_slug_is_shaped_as_the_catalogue_asks() -> None:
    """Слаг — короткое имя латиницей: по нему каталог отвечает по каждому."""
    for item in proposals():
        said = str(item.get("slug") or "")
        assert re.fullmatch(r"[a-z0-9-]+", said), f"слаг «{said}» не по форме контракта"


# --- контракт 1.3: у ответа «документом» назван предел ------------------------


def test_every_document_answer_names_its_limit() -> None:
    """У каждого `document` сказано, есть ли машинная половина вовсе.

    Контракт 1.3 расколол ответ «документом» надвое: `impossible` — машинной
    половины нет, документ и есть предел; `not-yet` — половина есть и не
    построена. Слово закрытое, потому что счётчику доли машинного соблюдения
    надо РАЗДЕЛИТЬ знаменатель, а прозу сложить нельзя.

    Требуется от ВСЕХ, а не только от новых: ревизия 11.09.2026 прочитала все
    28 ответов по букве и границе правила, и предел назван у каждого. Оставить
    часть без ответа значило бы сделать вид, что их не разбирали.
    """
    answers = load()["rules"]
    bare = [
        rule
        for rule, one in answers.items()
        if one.get("status") == "active"
        and one.get("mechanism") == "document"
        and one.get("document_reason") not in ("impossible", "not-yet")
    ]
    assert not bare, "ответ «документом» без названного предела: " + ", ".join(sorted(bare))


def test_a_named_limit_carries_its_reason() -> None:
    """Рядом с пределом стоит причина: значение из двух выбирается не думая.

    Причину не написать, не подумав, — этим она и держит выбор (154).
    """
    answers = load()["rules"]
    silent = [
        rule
        for rule, one in answers.items()
        if one.get("document_reason") and not str(one.get("why") or "").strip()
    ]
    assert not silent, "предел назван без причины: " + ", ".join(sorted(silent))
