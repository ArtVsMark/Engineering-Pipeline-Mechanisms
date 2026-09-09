"""Тело уплотнения: одна запись о работе, а не склейка черновика.

Площадка собирает тело squash-коммита сама — конкатенацией всех сообщений
ветки. Замер на #41: три копии трейлера соавторства в одном коммите. Здесь
проверяется, что собранное нами тело этого не повторяет.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import RunScript, load_script

body = load_script("squash_body.py")


def test_trailers_appear_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подпись у ветки одна, сколько бы коммитов в ней ни было."""
    trailer = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"

    def git(*args: str) -> str:
        if "--format=%s" in args:
            return "первое\nвторое\n"
        if "--format=%B%x00" in args:
            return f"первое\n\nRefs #7\n{trailer}\n\x00второе\n\nRefs #7\n{trailer}\n\x00"
        return "основание\n"

    monkeypatch.setattr(body, "git", git)
    assembled = body.compose("agent/ветка", "main")
    assert assembled.count(trailer) == 1
    assert assembled.count("Refs #7") == 1


def test_service_merge_is_not_a_line_of_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подтягивание базы — не запись о работе, и в теле его нет.

    `git log --no-merges` отбрасывает такие коммиты; проверяется, что механизм
    просит именно это, а не фильтрует заголовки по тексту — текст подделывается.
    """
    asked: list[tuple[str, ...]] = []

    def git(*args: str) -> str:
        asked.append(args)
        if "--format=%s" in args:
            return "работа\n"
        if "--format=%B%x00" in args:
            return "работа\n\nRefs #7\n\x00"
        return "основание\n"

    monkeypatch.setattr(body, "git", git)
    body.compose("agent/ветка", "main")
    subjects_call = next(args for args in asked if "--format=%s" in args)
    assert "--no-merges" in subjects_call


def test_resolved_findings_travel_into_the_squash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Снятие находки переживает уплотнение: его читают в теле СЛИТОГО."""

    def git(*args: str) -> str:
        if "--format=%s" in args:
            return "починка\n"
        if "--format=%B%x00" in args:
            return "починка\n\nРазобрано: abc1234\n\nRefs #7\n\x00"
        return "основание\n"

    monkeypatch.setattr(body, "git", git)
    assert "Разобрано: abc1234" in body.compose("agent/ветка", "main")


def test_a_branch_without_commits_is_an_input_error(run_script: RunScript, tmp_path: Path) -> None:
    """Собирать нечего — третий исход, а не пустое тело (075)."""
    run = run_script("squash_body.py", "--branch", "нет-такой", "--base", "main")
    assert run.code == 2, run.text
