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


def test_a_resolution_keeps_the_reason_it_was_written_with() -> None:
    """Причина снятия доезжает до общей ветки вместе с отпечатком.

    У СНЯТИЯ ДВА ИСХОДА: находка починена либо её премиса не подтвердилась, и
    второй закрывается «как неверная, с записью причины» — иначе она вернётся
    следующим обходом (044). Тело уплотнения собиралось из одних отпечатков, и
    причина, написанная автором в ветке, терялась: в истории оба исхода
    выглядели одной строкой (039). Замер 13.09.2026: в тридцати последних телах
    общей ветки — ни одной причины, только голые отпечатки.
    """
    тела = [
        "fix: род записи проверен\n\n"
        "Разобрано: a70f8f5 — премиса не подтвердилась: у 136 механизм уже был\n",
        "fix: и починка\n\nРазобрано: f9eb58d\n",
    ]
    said = body.changerefs.resolutions_in_all(тела)
    assert said == [
        "Разобрано: a70f8f5 — премиса не подтвердилась: у 136 механизм уже был",
        "Разобрано: f9eb58d",
    ]


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


def test_a_composed_body_is_printed_and_the_run_is_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Тело собралось — оно печатается, а исход чистый.

    Прогонялся только отказ: ветка без коммитов. «Чисто» у сборщика объявлено,
    но не проверялось ни разу
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    """

    def git(*args: str) -> str:
        if "--format=%s" in args:
            return "работа\n"
        if "--format=%B%x00" in args:
            return "работа\n\nRefs #7\n\x00"
        return "основание\n"

    monkeypatch.setattr(body, "git", git)
    assert body.main(["--branch", "agent/ветка"]) == body.EXIT_OK
    assert "работа" in capsys.readouterr().out


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
