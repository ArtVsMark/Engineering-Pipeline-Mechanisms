"""Карта взгляда: куда смотреть, потому что машина туда не смотрит.

Проверяется не «механизм читает JSON», а три свойства, без которых карта
вредит больше, чем помогает:

* карта берётся с ОБЩЕЙ ветки — иначе её подделает то самое изменение;
* отвергнутое и неприменимое в неё не попадает: взгляд не зовут на отсутствие;
* заголовки не пришли — сказано вслух, а не подменено молчанием.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("review_map.py")


def test_a_machine_held_rule_is_not_sent_to_the_eyes() -> None:
    """Правило с механизмом уходит в машинную половину, а не в список для глаз."""
    answer = {
        "rules": {
            "001": {"status": "active", "mechanism": "gate"},
            "002": {"status": "active", "mechanism": "pipeline"},
            "003": {"status": "active", "mechanism": "document"},
        }
    }
    machine, eyes = module.split(answer)
    assert machine == ["001", "002"]
    assert eyes == ["003"]


def test_a_rule_without_a_subject_is_in_neither_half() -> None:
    """Отвергнутое и неприменимое не зовёт взгляд: у него нет предмета (154)."""
    answer = {
        "rules": {
            "001": {"status": "not-applicable"},
            "002": {"status": "rejected", "why": "предмета нет"},
            "003": {"status": "active", "mechanism": "none"},
        }
    }
    machine, eyes = module.split(answer)
    assert machine == []
    assert eyes == ["003"], "правило, не держащееся ничем, глазам показать надо"


def test_the_map_names_where_the_machine_is_absent() -> None:
    """В карте названо, сколько правил без машины и какие именно."""
    text = module.render(["001"], ["003"], {"003": "Заголовок правила"}, touched=False)
    assert "003" in text and "Заголовок правила" in text
    assert "Машина держит 1" in text


def test_missing_titles_are_said_not_hidden() -> None:
    """Заголовки не пришли — карта говорит об этом, а не молчит (045)."""
    text = module.render(["001"], ["003"], {}, touched=False)
    assert "не пришли" in text
    assert "003" in text, "без заголовков остаются номера, а не пустота"


def test_touching_the_answer_is_flagged_to_the_reviewer() -> None:
    """Изменение правит сам ответ каталогу — ревьюеру об этом сказано.

    Карта взята с общей ветки и правки не видит; молчание об этом дало бы
    ревьюеру уверенность, которой у него нет (085).
    """
    text = module.render(["001"], ["003"], {"003": "Правило"}, touched=True)
    assert "правит сам ответ" in text


def test_the_answer_is_read_from_the_base_not_the_worktree(tmp_path: Path) -> None:
    """Ответ читается из названной ревизии, а не из рабочего дерева.

    Проверяется на настоящем репозитории: голова объявляет всё машинным, база —
    нет. Механизм обязан увидеть базу.
    """

    def run(*args: str) -> None:
        subprocess.run(
            args, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=True
        )

    run("git", "init", "--quiet", "-b", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Тест")
    answer = tmp_path / module.ANSWER
    answer.parent.mkdir(parents=True, exist_ok=True)
    base = {"rules": {"003": {"status": "active", "mechanism": "document"}}}
    answer.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "--quiet", "-m", "база")
    forged = {"rules": {"003": {"status": "active", "mechanism": "gate"}}}
    answer.write_text(json.dumps(forged, ensure_ascii=False), encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "--quiet", "-m", "голова объявляет всё машинным")

    here = Path.cwd()
    try:
        os.chdir(tmp_path)
        machine, eyes = module.split(module.from_base("HEAD~1"))
    finally:
        os.chdir(here)
    assert eyes == ["003"], "подделанная голова победила базу"
    assert machine == []


def test_an_unreadable_base_is_the_third_outcome(tmp_path: Path) -> None:
    """Базы нет — шаг не отработал, а не «карта пуста» (075)."""
    with pytest.raises(module.NotRun):
        module.from_base("нет-такой-ревизии")


def test_a_bilingual_title_takes_the_project_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заголовок каталога двуязычный — берётся русский, язык этого проекта."""

    def export(_: str) -> dict[str, Any]:
        return {"rules": [{"id": "003", "title": {"ru": "По-русски", "en": "In English"}}]}

    monkeypatch.setattr(module.ghrest, "raw_json", export)
    assert module.titles() == {"003": "По-русски"}
