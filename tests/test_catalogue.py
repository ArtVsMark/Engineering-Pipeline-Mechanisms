"""Канал к каталогу: один адрес, одно чтение, два различимых состояния.

Выгрузку каталога читают четверо — сверка ссылок, сверка чужого разбора, дрейф
и карта ревью. Адрес у них один (022), и ЧТЕНИЕ теперь тоже одно: «каталог
ответил» и «каталог не ответил» — разные состояния, и прежде они сливались в
одно красное.

ЗАМЕР 16.09.2026, голова #370: обязательная `journal` дала зелёное, красное и
снова зелёное на ОДНОМ дереве — упал шаг на чтении выгрузки, а общая ветка за те
три минуты не двигалась. Разбор — `docs/decisions/027-a-silent-catalogue-is-its-own-outcome.md`.
"""

import ast
from typing import Any

import pytest

from tests.conftest import ROOT, load_script, walk

module = load_script("catalogue.py")


def test_a_reachable_catalogue_gives_its_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каталог ответил — снимок отдаётся как есть, без разбора.

    Что делать с прочитанным, решает читатель: сведение этого в «общий разбор»
    связало бы разные предметы одной формой.
    """
    monkeypatch.setattr(module.ghrest, "raw_json", lambda url: {"rules": [{"id": "001"}]})
    assert module.read(module.EXPORT_URL) == {"rules": [{"id": "001"}]}


def test_a_silent_catalogue_raises_its_own_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """Молчание канала поднимается СВОИМ классом, а не общим отказом чтения.

    «Канал молчит» и «в выгрузке нет предмета» дают одинаковое бездействие и
    значат разное: первое — состояние сети, второе — поломка договора с
    каталогом, и краснеть обязано только второе (039).
    """

    def broken(*_: object, **__: object) -> object:
        raise module.ghrest.TransportError("сеть не ответила")

    monkeypatch.setattr(module.ghrest, "raw_json", broken)
    with pytest.raises(module.Silent) as fell:
        module.read(module.EXPORT_URL)
    assert "каталог не ответил" in str(fell.value)
    assert module.EXPORT_URL in str(fell.value), "адрес не назван — чинить негде (154)"
    assert "сеть не ответила" in str(fell.value), "причина отказа потеряна"


def test_the_silent_class_is_not_the_transport_error() -> None:
    """`Silent` — не отказ транспорта, и ловить их врозь обязано.

    Наследуйся он от `TransportError`, всякий `except TransportError` выше по
    стеку проглотил бы его вместе с обычным отказом — и различие, ради которого
    класс заведён, исчезло бы молча.
    """
    assert not issubclass(module.Silent, module.ghrest.TransportError)
    assert issubclass(module.Silent, RuntimeError)


def test_every_address_of_the_catalogue_is_one_repository() -> None:
    """Все адреса собраны из одного имени репозитория (022).

    Второе написание имени пережило бы переезд каталога молча: часть адресов
    уехала бы, часть осталась.
    """
    addresses = [
        value
        for name, value in vars(module).items()
        if name.endswith("_URL") and isinstance(value, str)
    ]
    assert addresses, "адресов каталога не найдено — предмета нет (075)"
    for one in addresses:
        assert module.REPO in one, f"адрес мимо объявленного репозитория: {one}"


# --- статус правила выгрузки: одно чтение на всех (#1563) --------------------


def test_the_pre_1_9_export_is_read_by_its_link() -> None:
    """До выгрузки 1.9 слова нет: заменено то, у чего есть `superseded_by`."""
    export = {
        "rules": [
            {"id": "002", "superseded_by": "224"},
            {"id": "003"},
            {"id": "005", "superseded_by": ""},
            "не правило",
        ]
    }
    assert module.replacements(export) == {"002": "224"}


def test_the_status_word_is_stronger_than_the_link() -> None:
    """С 1.9 решает слово: `active` со ссылкой действует, `superseded` без ссылки — не замена."""
    export = {
        "rules": [
            {"id": "010", "status": "active", "superseded_by": "220"},
            {"id": "011", "status": "superseded"},
            {"id": "012", "status": "superseded", "superseded_by": "221"},
        ]
    }
    assert [module.rule_status(rule) for rule in module.rules_of(export)] == [
        module.ACTIVE,
        module.SUPERSEDED,
        module.SUPERSEDED,
    ]
    assert module.replacements(export) == {"012": "221"}


@pytest.mark.parametrize("export", [{}, {"rules": None}, {"rules": "список"}, []])
def test_an_export_without_a_rule_list_is_refused(export: Any) -> None:
    """Списка правил нет — `BadExport`, а не «действующих ноль» (075)."""
    with pytest.raises(module.BadExport, match="rules"):
        module.replacements(export)


def test_a_broken_export_is_neither_silence_nor_transport() -> None:
    """Сломанный договор выгрузки — не молчание канала: ловится врозь и краснеет (039)."""
    assert not issubclass(module.BadExport, module.Silent)
    assert not issubclass(module.BadExport, module.ghrest.TransportError)


def reads_field(node: ast.AST, field: str) -> bool:
    """Узел читает поле записи: `rule["field"]` или `rule.get("field")` — разбором, не образцом."""
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == field
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == field
    )


@pytest.mark.parametrize(
    ("source", "reads"),
    [
        ('rule["superseded_by"]', True),
        ('rule.get("superseded_by")', True),
        ('rule.get("superseded_by", "")', True),
        ('"superseded_by"', False),
        ('rule.get("status")', False),
    ],
)
def test_the_field_reader_is_told_by_the_syntax_tree(source: str, reads: bool) -> None:
    """Чтение поля узнаётся по дереву разбора: строка в тексте — ещё не чтение (210)."""
    assert any(reads_field(node, "superseded_by") for node in ast.walk(ast.parse(source))) is reads


def test_the_rule_status_has_one_reader() -> None:
    """Поле `superseded_by` выгрузки читает только `catalogue.py` — второго читателя нет (214).

    Дрейф читал его сам, без слова `status` выгрузки 1.9, а значок каталога —
    слово: два чтения одного поля разошлись бы молча (#1563).
    """
    readers = [
        path.name
        for path in walk(ROOT / "scripts", "*.py")
        if any(
            reads_field(node, "superseded_by")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    ]
    assert readers == ["catalogue.py"], f"поле superseded_by читают: {readers}"


def test_the_rule_status_reads_the_word_then_the_link() -> None:
    """`rule_status`: слово, если есть; без слова — ссылка решает, заменено ли."""
    assert module.rule_status({"status": "superseded"}) == module.SUPERSEDED
    assert module.rule_status({"status": "active", "superseded_by": "220"}) == module.ACTIVE
    assert module.rule_status({"superseded_by": "220"}) == module.SUPERSEDED
    assert module.rule_status({}) == module.ACTIVE


def test_the_rules_of_an_export_skip_what_is_not_a_record() -> None:
    """`rules_of`: записи-словари из списка, прочее пропускается; списка нет — отказ."""
    assert module.rules_of({"rules": [{"id": "001"}, "не правило", 7]}) == [{"id": "001"}]
    with pytest.raises(module.BadExport):
        module.rules_of({"rules": {}})
