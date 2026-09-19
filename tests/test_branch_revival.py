"""Толчок в ветку, чьё изменение слито, отвергается ДО толчка.

19.09.2026 ветка воскресла толчком через пять минут после слияния, и открывшееся
по ней изменение удаляло чужую работу. Сторож перед git этот случай знает, но
признак у него ЛОКАЛЬНЫЙ и устаревает до первого фетча — в тот день он потому и
промолчал. Проверяется здесь то, без чего гейт был бы копией сторожа:

* предмет — СЛИТОЕ изменение по этой голове, а не отсутствие ветки:
  воскрешённая ветка существует и от живой неотличима;
* закрытое БЕЗ слияния предметом не является — по такой ветке работают дальше,
  и отказ был бы запретом верного (051);
* отсутствие токена — отдельный исход, а не «чисто» (045);
* отказ называет, ЧТО делать вместо толчка (104).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("check_branch_revival.py")

#: Ответ площадки об изменении: слитое несёт `merged_at`, закрытое — нет.
MERGED: Any = {"number": 509, "merged_at": "2026-09-19T08:38:37Z"}
CLOSED: Any = {"number": 513, "merged_at": None}
OPEN: Any = {"number": 514, "merged_at": None, "state": "open"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Дерево под git с адресом `origin` — имя репозитория берётся оттуда."""
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/o/r.git"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def answering(monkeypatch: pytest.MonkeyPatch, *changes: Any) -> None:
    """Площадка отвечает этими изменениями на вопрос о голове ветки."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: list(changes))


def test_a_branch_whose_change_is_merged_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Слитое изменение по этой голове — отказ, и это первый исход гейта."""
    answering(monkeypatch, MERGED)
    code, said = module.look(repo, "agent/работа")
    assert code == module.EXIT_REVIVED
    assert "#509" in said


def test_the_refusal_says_what_to_do_instead(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ называет выход, а не только запрет (104).

    Без этой половины сообщение читается как «нельзя» — и окно продолжает
    толкать в ту же ветку, потому что другого пути ему не назвали.
    """
    answering(monkeypatch, MERGED)
    _, said = module.look(repo, "agent/работа")
    assert "checkout -b" in said, "отказ не назвал, откуда резать новую ветку"
    assert "origin/main" in said


def test_a_change_closed_without_a_merge_is_not_the_subject(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Закрытое без слияния ветку не хоронит — по ней работают дальше (051).

    Вторая половина предиката. Без неё гейт неотличим от «по ветке было
    изменение»: такой запрещает продолжать работу после любого закрытого
    изменения, то есть отвергает верное.
    """
    answering(monkeypatch, CLOSED, OPEN)
    code, said = module.look(repo, "agent/работа")
    assert code == module.EXIT_OK, said


def test_a_fresh_branch_passes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ветка без изменений вовсе — чисто."""
    answering(monkeypatch)
    code, _ = module.look(repo, "agent/новая")
    assert code == module.EXIT_OK


def test_no_token_is_its_own_outcome(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Без токена гейт говорит «не спросили», а не «чисто» (045).

    Признак живёт только у площадки. Тихое зелёное здесь было бы запасным путём:
    снаружи оно неотличимо от проверенного.
    """
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    code, said = module.look(repo, "agent/работа")
    assert code == module.EXIT_UNASKED
    assert "НЕ ПРОВЕРЕНО" in said


@pytest.mark.parametrize("branch", ["", "HEAD"])
def test_a_name_that_is_not_a_branch_does_not_run(repo: Path, branch: str) -> None:
    """Оторванная голова и пустое имя — «не отработал», а не «чисто» (075)."""
    with pytest.raises(module.NotRun):
        module.look(repo, branch)


def test_a_tree_without_origin_does_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Спрашивать площадку не у кого — третий исход, а не молчание."""
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    with pytest.raises(module.NotRun):
        module.look(tmp_path, "agent/работа")


def test_the_question_is_about_the_head_not_the_base(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Спрашивается ГОЛОВА ветки, а не база: предмет — та ветка, куда толкают.

    Подмена `head` на `base` дала бы вопрос о слияниях В эту ветку — и гейт
    отвергал бы всё подряд на ветке по умолчанию, ничего не проверив.
    """
    asked: list[str] = []

    def remember(_method: str, path: str, _token: str) -> list[Any]:
        asked.append(path)
        return []

    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.ghrest, "request", remember)
    module.look(repo, "agent/работа")
    assert asked and "head=o:agent/работа" in asked[0], asked


def test_the_entry_point_returns_broken_when_it_cannot_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Вход возвращает «не отработал», а не ноль: исход объявлен — значит прогнан (145).

    Снаружи `2` от `0` отличается только кодом возврата, и необъявленный вслух
    отказ читается зовущим как «чисто» (045).
    """
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    code = module.main(["--branch", "agent/работа", "--root", str(tmp_path)])
    assert code == module.EXIT_BROKEN
    assert "не отработал" in capsys.readouterr().err


def test_a_platform_refusal_is_broken_not_clean(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Площадка не ответила — «не отработал», а не «толчок безопасен» (045)."""

    def broken(*_: object, **__: object) -> Any:
        raise module.ghrest.TransportError("502")

    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.ghrest, "request", broken)
    assert module.main(["--branch", "agent/работа", "--root", str(repo)]) == module.EXIT_BROKEN
    assert "площадка не ответила" in capsys.readouterr().err


def test_an_answer_that_is_not_a_list_is_broken(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ответ не того вида — отказ входа, а не пустой список изменений (075).

    Площадка отвечает объектом-ошибкой на тот же адрес: `{"message": "..."}`
    перебором дал бы ноль слитых изменений, то есть тихое «чисто».
    """
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"message": "Not Found"})
    with pytest.raises(module.NotRun):
        module.look(repo, "agent/работа")


def test_the_repo_name_comes_from_origin(repo: Path) -> None:
    """Имя репозитория берётся у `origin`, а не из памяти: дерево знает своё (049)."""
    assert module.repo_of(repo) == "o/r"


@pytest.mark.parametrize("url", ["git@github.com:o/r.git", "https://github.com/o/r"])
def test_both_written_forms_of_the_address_are_read(tmp_path: Path, url: str) -> None:
    """Адрес читается обеими записями — по ssh и по https.

    Окно клонирует по https, человек — чаще по ssh. Разбор, знающий одну форму,
    у второго отвечал бы «спрашивать не у кого» и уходил бы в отказ входа (045).
    """
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=tmp_path, check=True)
    assert module.repo_of(tmp_path) == "o/r"


def test_an_unparsable_address_does_not_run(tmp_path: Path) -> None:
    """Адрес без `владелец/имя` — отказ входа, а не имя, склеенное как вышло."""
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "мусор"], cwd=tmp_path, check=True)
    with pytest.raises(module.NotRun):
        module.repo_of(tmp_path)


def test_only_merged_changes_are_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Перебор ответа отбирает СЛИТЫЕ и отдаёт их номера — предмет гейта."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: [MERGED, CLOSED, OPEN])
    assert module.merged_changes_of("o/r", "agent/работа", "токен") == [509]


def test_the_owner_of_the_head_is_taken_from_the_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Владелец в `head=` берётся из имени репозитория, а не пишется руками.

    Вопрос `head=<ветка>` без владельца площадка понимает иначе и отвечает
    пустым списком — то есть гейт зеленел бы всегда, ничего не спросив.
    """
    asked: list[str] = []

    def remember(_method: str, path: str, _token: str) -> list[Any]:
        asked.append(path)
        return []

    monkeypatch.setattr(module.ghrest, "request", remember)
    module.merged_changes_of("чужой/дерево", "agent/работа", "токен")
    assert asked == ["repos/чужой/дерево/pulls?head=чужой:agent/работа&state=all&per_page=100"]
