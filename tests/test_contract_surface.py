"""Поверхность контракта: что гейт обязан поймать и что обязан пропустить.

Оба вида ошибки здесь одинаково дороги. Пропущенная правка поверхности ломает
потребителя молча — он узнаёт об этом красной защитой ветки на своей стороне и
починить у себя не может. Лишнее красное на переставленном комментарии учит
обходить гейт, и тогда он не ловит уже ничего
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script

contract = load_script("contract.py")
policy = load_script("pipeline_checks.py")

WORKFLOW = """
name: ci
on:
  pull_request:
    types: [opened]
  workflow_dispatch:
    inputs:
      pr:
        description: "номер"
        required: true
        type: string
jobs:
  lint:
    name: lint
    steps: []
"""

ANSWER = 'schema: 3\ncontract: ">=0.1,<0.2"\nchecks:\n  lint: required\n'


def tree(root: Path, workflow: str = WORKFLOW, answer: str = ANSWER) -> Path:
    """Собирает дерево с одним прогоном и ответом проекта."""
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ci.yml").write_text(workflow, encoding="utf-8")
    (root / ".pipeline.yml").write_text(answer, encoding="utf-8")
    return root


def test_the_surface_is_taken_from_the_tree(tmp_path: Path) -> None:
    """Снимок собирается с дерева, а не ведётся списком руками.

    Список руками отстаёт молча: новый прогон добавляется файлом, и о нём никто
    не вспомнит (049).
    """
    shape = contract.surface(tree(tmp_path))
    assert shape["workflows"]["ci.yml"]["jobs"] == ["lint"]
    assert shape["answer"]["checks"] == {"lint": "required"}


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (lambda text: text.replace("name: lint", "name: linter"), "джоб"),
        (lambda text: text.replace("      pr:", "      number:"), "входы"),
        (lambda text: text.replace("required: true", "required: false"), "входы"),
        (
            lambda text: text.replace("    types: [opened]", "    types: [opened, closed]"),
            "события",
        ),
    ],
    ids=["имя джоба", "имя входа", "обязательность входа", "события"],
)
def test_a_visible_change_is_caught(tmp_path: Path, edit: Any, expected: str) -> None:
    """Правка того, что видит потребитель, считается изменением поверхности.

    Имя джоба уезжает в чужую защиту ветки дословно, вход кнопки — в чужой
    вызов, событие — в чужое понимание, когда шаг сработает.
    """
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(tree(tmp_path / "after", workflow=edit(WORKFLOW)))
    changes = contract.differences(before, after)
    assert changes, "правка поверхности не замечена"
    assert any(expected in line for line in changes), changes


@pytest.mark.parametrize(
    "edit",
    [
        lambda text: text.replace("jobs:", "# пояснение для читателя\njobs:"),
        lambda text: text.replace("    steps: []", "    steps: []\n    timeout-minutes: 10"),
        lambda text: text.replace('        description: "номер"', '        description: "иначе"'),
    ],
    ids=["комментарий", "предел времени", "описание входа"],
)
def test_an_internal_change_is_not_the_surface(tmp_path: Path, edit: Any) -> None:
    """Внутреннее меняется свободно: контракт от каждой правки не двигается.

    Предел времени, комментарий и описание входа потребителю не видны и в его
    вызовы не попадают. Красное на них научило бы обходить гейт.
    """
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(tree(tmp_path / "after", workflow=edit(WORKFLOW)))
    assert contract.differences(before, after) == []


def test_a_class_change_is_the_surface(tmp_path: Path) -> None:
    """Класс проверки — форма чужого ответа: его правка видна потребителю."""
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(
        tree(tmp_path / "after", answer=ANSWER.replace("required", "advisory"))
    )
    assert any("lint" in line for line in contract.differences(before, after))


def test_the_answer_schema_is_the_surface(tmp_path: Path) -> None:
    """Схема ответа — тоже поверхность: по ней потребитель пишет свой файл."""
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(
        tree(tmp_path / "after", answer=ANSWER.replace("schema: 3", "schema: 4"))
    )
    assert any("схема" in line for line in contract.differences(before, after))


# --- диапазон совместимости ---------------------------------------------------


@pytest.mark.parametrize(
    ("span", "version", "fits"),
    [
        (">=0.1,<0.2", "0.1.4", True),
        (">=0.1,<0.2", "0.1.99", True),
        (">=0.1,<0.2", "0.2.0", False),
        (">=0.1,<0.2", "0.0.9", False),
        (">=1.0,<2.0", "1.9.0", True),
    ],
)
def test_the_range_decides_by_major_minor(span: str, version: str, fits: bool) -> None:
    """Сравниваются MAJOR.MINOR: патч поверхности не трогает по построению.

    Требовать совпадения патча значило бы тревожить потребителя выпуском,
    который его не касается, — и канал перестали бы читать.
    """
    assert policy.compatible(span, version) is fits


@pytest.mark.parametrize(
    "span", [">=0.1", "0.1", ">=0.1,<=0.2", "любая", "", ">0.1,<0.2"], ids=lambda s: s or "пусто"
)
def test_a_range_without_an_upper_bound_is_refused(span: str) -> None:
    """Верхняя граница обязательна: без неё несовместимое применяется молча (073).

    Потребитель, объявивший только «не старше», однажды получает поверхность,
    о которой не знает, и узнаёт об этом красным на ровном месте.
    """
    with pytest.raises(policy.BadPolicy):
        policy.compatible(span, "0.1.4")


def test_an_answer_without_a_range_is_refused(tmp_path: Path) -> None:
    """Ответ без диапазона отвергается: «подходит любая» — молчание, а не состояние."""
    path = tmp_path / ".pipeline.yml"
    path.write_text("schema: 3\nchecks:\n  lint: required\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="диапазон"):
        policy.load(path)


def test_a_contract_outside_the_range_is_refused(tmp_path: Path) -> None:
    """Контракт вне диапазона — красное, и оно зовёт перечитать ответы (157).

    Не «подвинь границу»: механическое поднятие числа оставляет ненужный обход
    жить вечно, а смысл перечитывания ровно в том, чтобы его снять.
    """
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    path = tmp_path / ".pipeline.yml"
    path.write_text(ANSWER, encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="перечитайте ответы"):
        policy.load(path)


# --- сам гейт -----------------------------------------------------------------


def test_the_project_answer_declares_its_range() -> None:
    """Ответ САМОГО проекта несёт диапазон, а не только подделки (075)."""
    text = (ROOT / ".pipeline.yml").read_text(encoding="utf-8")
    assert "contract:" in text, "проект не объявил, с каким контрактом он совместим"


def test_the_gate_shows_the_surface(run_script: RunScript) -> None:
    """Снимок можно посмотреть глазами: иначе спор «что тут контрактного» нечем закрыть."""
    run = run_script("check_contract.py", "--show")
    assert run.code == 0, run.text
    assert "workflows" in run.text and "answer" in run.text


def test_the_gate_is_declared_required() -> None:
    """Гейт объявлен держащим слияние: правка поверхности ломает потребителя молча."""
    checks = policy.load()
    assert checks["contract"].klass == policy.REQUIRED
