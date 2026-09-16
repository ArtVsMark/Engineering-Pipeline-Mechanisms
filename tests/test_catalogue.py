"""Канал к каталогу: один адрес, одно чтение, два различимых состояния.

Выгрузку каталога читают четверо — сверка ссылок, сверка чужого разбора, дрейф
и карта ревью. Адрес у них один (022), и ЧТЕНИЕ теперь тоже одно: «каталог
ответил» и «каталог не ответил» — разные состояния, и прежде они сливались в
одно красное.

ЗАМЕР 16.09.2026, голова #370: обязательная `journal` дала зелёное, красное и
снова зелёное на ОДНОМ дереве — упал шаг на чтении выгрузки, а общая ветка за те
три минуты не двигалась. Разбор — `docs/decisions/027-a-silent-catalogue-is-its-own-outcome.md`.
"""

from __future__ import annotations

import pytest

from tests.conftest import load_script

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
