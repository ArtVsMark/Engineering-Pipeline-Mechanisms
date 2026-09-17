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
    """Подпись у ветки одна, сколько бы коммитов в ней ни было.

    ФОРМА ТЕЛА ВЗЯТА У ЖИВОЙ ИСТОРИИ, А НЕ ПРИДУМАНА. Прежняя подделка клеила
    `Refs #7` к трейлерам одним абзацем — так в проекте не пишут: замер
    17.09.2026 по 300 телам показал, что у ВСЕХ 290 тел с трейлерами хвостовой
    блок состоит целиком из строк «Ключ: значение», а ссылка на задачу стоит
    своим абзацем выше. Подделка, умеющая то, чего не бывает, роняла бы разбор
    хвостового блока на форме, которой нет
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    trailer = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"

    def git(*args: str) -> str:
        if "--format=%s" in args:
            return "первое\nвторое\n"
        if "--format=%B%x00" in args:
            return f"первое\n\nRefs #7\n\n{trailer}\n\x00второе\n\nRefs #7\n\n{trailer}\n\x00"
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


def test_a_trailer_is_read_only_from_the_tail_block() -> None:
    """Прозаическое упоминание трейлера директивой не становится.

    Тело уплотнения уезжает в общую ветку, и подставленный так «соавтор»
    переписыванию уже не поддаётся. Прежний разбор брал строку по приставке
    имени трейлера из текста ВСЕХ коммитов, склеенных вместе.
    """
    тело = (
        "Правка подписи\n\n"
        "В своде сказано, что строка `Co-Authored-By: Кто-то <кто@то>` ставится\n"
        "в хвост, а не в середину. Вот пример того, как НЕ надо:\n"
        "Co-Authored-By: Самозванец <chuzhoy@example.com>\n\n"
        "Refs #243\n\n"
        "Co-Authored-By: Настоящий <real@example.com>\n"
    )
    assert body.trailers_of([тело]) == ["Co-Authored-By: Настоящий <real@example.com>"], (
        "прозаическое упоминание уехало в тело уплотнения настоящим трейлером"
    )


def test_a_trailer_from_an_earlier_commit_is_not_lost() -> None:
    """Блок читается у КАЖДОГО сообщения свой, а не один на склейку.

    У склейки хвостовой блок один — последний, — и соавтор, названный в первом
    коммите ветки, потерялся бы. Это второй конец: починка «читать только хвост»
    без этого ломала бы атрибуцию (051).
    """
    первый = "Первый шаг\n\nRefs #1\n\nCo-Authored-By: Первый <one@example.com>\n"
    второй = "Второй шаг\n\nRefs #1\n\nCo-Authored-By: Второй <two@example.com>\n"
    assert body.trailers_of([первый, второй]) == [
        "Co-Authored-By: Первый <one@example.com>",
        "Co-Authored-By: Второй <two@example.com>",
    ]


def test_a_paragraph_with_prose_in_it_is_not_a_tail_block() -> None:
    """Абзац, где есть хоть одна прозаическая строка, хвостовым блоком не считается.

    Так директива и отличается от рассказа о ней: положение задаёт смысл.
    """
    assert body.tail_block("Тема\n\nRefs #1\n\nCo-Authored-By: Кто <k@e.com>") == [
        "Co-Authored-By: Кто <k@e.com>",
    ], "хвостовой блок — последний абзац, а `Refs #1` стоит своим"
    assert body.tail_block("Тема\n\nRefs #1\nCo-Authored-By: Кто <k@e.com>") == [], (
        "абзац со строкой не вида «Ключ: значение» хвостовым блоком не является"
    )
    assert body.tail_block("Тема\n\nCo-Authored-By: Кто <k@e.com>\nи ещё пара слов") == []
    assert body.tail_block("Тема без хвоста вовсе") == []


def test_the_same_trailer_twice_is_written_once() -> None:
    """Подпись у ветки одна: повторять её по числу коммитов — шум, а не атрибуция."""
    один = "Шаг\n\nCo-Authored-By: Он <he@example.com>\n"
    assert body.trailers_of([один, один]) == ["Co-Authored-By: Он <he@example.com>"]
