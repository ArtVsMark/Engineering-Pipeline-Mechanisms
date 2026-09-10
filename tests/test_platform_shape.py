"""Подделка ответа площадки сверяется со снятым ответом, а не с разумением окна.

Правило каталога
[170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)
до этого гейта не держалось ничем. Подделки в наборе были — сборщик записи
проверки, свой сервер у транспорта, — но собраны они по документации и по
разумению окна. Зелёное на такой подделке доказывает согласованность кода с
НАШИМ представлением о площадке, а не с площадкой: разойдись они, набор
остался бы зелёным, и разошлись бы они молча.

Поэтому в дереве лежит снятый ответ — `tests/fixtures/check-runs.shape.json`.
Снята ФОРМА: ключи и типы. Идентификаторы, времена и адреса конкретного
прогона — наполнение, а не форма, и устарели бы к первому же прогону; хранить
их значило бы завести фикстуру, которую придётся обновлять из-за того, что
проверять никто не собирался.

ЧТО ГЕЙТ ЛОВИТ И ЧЕГО НЕ ЛОВИТ. Ловит: подделку с ключом, которого у площадки
нет, и с типом, которого у неё не бывает, — то есть набор, зелёный на том, чего
не бывает. Не ловит: изменение самой площадки — снимок стареет, и обновляют его
рукой. Это названо, а не выдано за полноту (046): снимок с датой лучше
представления без даты, но заменой живому прогону он не является.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests import test_automerge, test_gates_complete

ROOT = Path(__file__).resolve().parent.parent
CAPTURED = ROOT / "tests" / "fixtures" / "check-runs.shape.json"

#: Подделки записи проверки, живущие в наборе. Собираются вызовом, а не
#: перечислением ключей руками: список руками разошёлся бы с самой подделкой.
FAKES = {
    "test_gates_complete.run": test_gates_complete.run("lint"),
    "test_automerge.record": test_automerge.record("lint"),
}


def captured() -> dict[str, Any]:
    """Снятый ответ площадки: форма записи и конверта."""
    document: dict[str, Any] = json.loads(CAPTURED.read_text(encoding="utf-8"))
    return document


def type_name(value: Any) -> str:
    """Имя типа в том же виде, в каком оно записано в снимке."""
    return type(value).__name__


def test_the_captured_answer_is_in_the_tree() -> None:
    """Предмет сверки найден: снимок есть, датирован и не пуст (075).

    Фикстура без даты и без адреса, откуда она снята, — это то же разумение
    окна, только записанное в файл (185).
    """
    assert CAPTURED.is_file(), "снятого ответа площадки нет — сверять подделку не с чем"
    document = captured()
    assert document.get("_снято"), "снимок без даты: непонятно, чему он соответствовал"
    assert document.get("_откуда"), "снимок без адреса, откуда снят"
    assert document.get("check_run"), "снимок не описывает запись проверки"


def test_the_fakes_are_not_empty() -> None:
    """Подделки найдены: иначе гейт зелен на отсутствии предмета (075)."""
    assert FAKES and all(FAKES.values()), "подделок записи проверки в наборе не нашлось"


@pytest.mark.parametrize("name", sorted(FAKES), ids=lambda name: name)
def test_a_fake_uses_only_keys_the_platform_returns(name: str) -> None:
    """У подделки нет ключа, которого площадка не отдаёт.

    Ключ, которого у площадки нет, — это проверка поведения, которого не
    бывает: набор зеленеет, а механизм в жизни этого поля не увидит.
    """
    real = captured()["check_run"]
    stray = sorted(set(FAKES[name]) - set(real))
    assert not stray, (
        f"{name} подделывает ключи, которых у площадки нет: {stray} — "
        f"снимок от {captured()['_снято']}"
    )


@pytest.mark.parametrize("name", sorted(FAKES), ids=lambda name: name)
def test_a_fake_keeps_the_captured_types(name: str) -> None:
    """Тип поля в подделке — тот, что отдаёт площадка.

    ``conclusion`` у площадки бывает пустым, поэтому пустое значение здесь
    законно: механизмы обязаны его разбирать, и подделка обязана его давать.
    """
    real = captured()["check_run"]
    wrong = {
        key: (type_name(value), real[key])
        for key, value in FAKES[name].items()
        if value is not None and not isinstance(real[key], dict | list)
        if type_name(value) != real[key]
    }
    assert not wrong, f"{name}: тип поля разошёлся со снятым ответом: {wrong}"


def test_the_envelope_the_transport_reads_is_captured() -> None:
    """Конверт, по которому транспорт идёт постранично, снят вместе с записью.

    `ghrest.paginate` берёт список по имени поля; имя это — часть ответа
    площадки, и проверять его надо там же, где остальную форму.
    """
    envelope = captured()["envelope"]
    assert "check_runs" not in envelope, "поле со списком не должно лежать в конверте дважды"
    assert envelope.get("total_count") == "int", (
        "конверт без счётчика: транспорт читает страницу по нему"
    )
