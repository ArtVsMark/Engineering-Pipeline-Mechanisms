"""Факты о проекте и их публикация проверяются отказом, а не осмотром.

Предмет двойной: числа обязаны приходить из источников (иначе значок врёт
уверенно), а производное обязано оставаться вне общей ветки (иначе оно там
протухает молча). Проверяется и то, и другое.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script

facts = load_script("build_facts.py")

WORKFLOW = ROOT / ".github" / "workflows" / "badges.yml"
CHECKS = 'schema: 3\ncontract: ">=9.9,<9.10"\nchecks:\n  lint: required\n'


def bindings(**rules: dict[str, Any]) -> str:
    """Ответ каталогу в том виде, в каком его читает механизм."""
    return json.dumps({"schema": "1.0", "rules": rules}, ensure_ascii=False)


def tree(root: Path, answer: str) -> Path:
    """Собирает дерево-источник: версия, ответ каталогу, ответ по проверкам."""
    (root / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    (root / ".rules").mkdir(exist_ok=True)
    (root / ".rules" / "bindings.json").write_text(answer, encoding="utf-8")
    (root / ".pipeline.yml").write_text(CHECKS, encoding="utf-8")
    return root


def test_numbers_come_from_the_sources(tmp_path: Path) -> None:
    """Каждое число собрано из источника, а не вписано в механизм."""
    tree(
        tmp_path,
        bindings(
            **{
                "001": {"status": "active", "mechanism": "gate", "where": "тут"},
                "002": {"status": "active", "mechanism": "document", "where": "там"},
                "003": {"status": "unreviewed"},
                "004": {"status": "rejected", "why": "не наш предмет"},
            }
        ),
    )
    collected = facts.collect(tmp_path, "голова")
    assert collected["contract"] == FAKE_VERSION
    assert collected["rules"]["total"] == 4
    assert collected["rules"]["answered"] == 3
    assert collected["rules"]["by_mechanism"] == {"document": 1, "gate": 1}
    assert collected["checks"]["required"] == 1
    assert collected["generated"]["sha"] == "голова"


def test_unknown_status_is_refused(tmp_path: Path) -> None:
    """Статус вне схемы — дефект ответа, а не новая тонкость (068)."""
    tree(tmp_path, bindings(**{"001": {"status": "почти"}}))
    with pytest.raises(facts.NotRun, match="статус"):
        facts.collect(tmp_path, "")


def test_active_without_a_mechanism_is_refused(tmp_path: Path) -> None:
    """«Действует» без названного механизма — обещание, а не ответ (002)."""
    tree(tmp_path, bindings(**{"001": {"status": "active"}}))
    with pytest.raises(facts.NotRun, match="чем — не сказано"):
        facts.collect(tmp_path, "")


def test_empty_answer_is_an_input_error(tmp_path: Path) -> None:
    """Пустой ответ каталогу — ошибка входа, а не «правил нет» (075)."""
    tree(tmp_path, bindings())
    with pytest.raises(facts.NotRun):
        facts.collect(tmp_path, "")


def test_missing_version_is_an_input_error(tmp_path: Path) -> None:
    """Без версии контракта факты не собираются: публиковать нечего."""
    tree(tmp_path, bindings(**{"001": {"status": "unreviewed"}}))
    (tmp_path / "CONTRACT_VERSION").unlink()
    with pytest.raises(facts.NotRun):
        facts.collect(tmp_path, "")


def test_badge_shows_the_number_it_measured() -> None:
    """Значок несёт то же число, что и факты: второго источника у него нет."""
    drawn = facts.rules_badge({"rules": {"total": 195, "answered": 66}})
    assert "66/195" in drawn
    assert "правил держится" in drawn


def test_badge_colour_follows_the_share() -> None:
    """Цвет говорит о доле, а не о настроении: три доли — три цвета."""
    low = facts.rules_badge({"rules": {"total": 100, "answered": 10}})
    mid = facts.rules_badge({"rules": {"total": 100, "answered": 50}})
    high = facts.rules_badge({"rules": {"total": 100, "answered": 90}})
    assert len({low.split('fill="')[2], mid.split('fill="')[2], high.split('fill="')[2]}) == 3


def test_derived_output_is_not_in_the_shared_branch() -> None:
    """Производного нет в дереве: оно живёт в ветке `badges` (125).

    Гейт написан на ИМЕНА вывода, а не на его содержимое: файл, случайно
    закоммиченный рядом с источником, выглядит безобидно ровно до того дня,
    когда число в нём разойдётся с источником.
    """
    for name in (facts.FACTS, facts.BADGE):
        assert not list(ROOT.glob(f"**/{name}")), f"{name} лежит в общей ветке рядом с источником"


def push_command(step: str) -> str:
    """Склеивает команду толчка вместе с её переносами строк."""
    joined = step.replace("\\\n", " ")
    commands = [line for line in joined.splitlines() if "git push" in line]
    assert commands, "шаг публикации ничего не толкает — предмет проверки не найден (075)"
    return commands[0]


def test_publication_writes_only_to_the_derived_branch() -> None:
    """Прогон толкает в `badges`, и никуда больше.

    Право на запись у этого прогона единственное во всём конвейере, поэтому
    проверяется не намерение, а сама команда: имя общей ветки в ней означало бы
    механизм, способный переписать источник своим же выводом.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    command = push_command(document["jobs"]["badges"]["steps"][-1]["run"])
    assert command.rstrip().endswith("badges"), f"толчок идёт не в производную ветку: {command}"
    assert "main" not in command, "шаг публикации называет общую ветку"


def test_publication_is_not_a_check_on_a_change() -> None:
    """Публикация не идёт на изменении: она не проверка и вердикта не выносит."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "pull_request" not in document[True]


def test_build_refuses_to_write_next_to_the_sources(run_script: RunScript) -> None:
    """Каталог вывода обязателен: умолчания «рядом с источником» нет."""
    run = run_script("build_facts.py")
    assert run.code != 0, run.text
    assert "--out-dir" in run.text


def test_the_facts_carry_the_computed_version() -> None:
    """Факты несут ПОСЧИТАННУЮ версию рядом с объявленным контрактом.

    Числа разные и оба нужны: контракт объявляет поверхность механизмов и
    поднимается решением человека, версия проекта считается по истории —
    «столько изменений принято после выпуска». Свести их в одно значило бы либо
    скрыть работу, либо объявить выпуском каждое изменение (035).
    """
    collected = facts.collect(ROOT, "abc1234")
    assert collected["contract"], "объявленный контракт исчез из фактов"
    assert collected["version"], "посчитанной версии в фактах нет"
    assert collected["version"] != collected["contract"] or collected["version"].endswith(".0")


def test_the_facts_say_whether_the_version_is_whole() -> None:
    """Неполнота названа рядом с числом, а не выброшена.

    Клон без тегов даёт правдоподобное число: MAJOR.MINOR берутся из
    объявленного контракта вместо выпущенного. Потребитель фактов должен видеть
    это в данных, а не догадываться (046).
    """
    assert "version_whole" in facts.collect(ROOT, "abc1234")


def test_the_badge_run_fetches_the_tags() -> None:
    """Прогон значков берёт всю историю и теги — иначе версия считается ложно."""
    text = (ROOT / ".github" / "workflows" / "badges.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in text
    assert "fetch-tags: true" in text
