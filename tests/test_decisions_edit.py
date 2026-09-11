"""Гейт 043 проверяется отказом, а не зелёным на чистом дереве.

Гейт, который видели только зелёным, доказывает ровно одно: он отработал. Что
он ловит предмет, показывает подделанное нарушение (140). Здесь оно строится
настоящим репозиторием: у гейта вход — история, и подменять её объектами
значило бы проверять не то, что пойдёт в прогоне.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import RunScript, load_script

edit = load_script("check_decisions_edit.py")

RECORD = """# 007. Заголовок записи

> **Читатель:** тот, кто ведёт конвейер.

**Статус:** принято · **Дата:** 2026-09-11 · **Задача:** [#7](../../../issues/7)

## Контекст

Было два пути, и оба с ценой.

## Решение

Взят первый.

## Отвергнутые варианты

Второй: дороже переключение.

## Последствия

Шаг конвейера стал обязательным.
"""


def _git(where: Path, *args: str) -> None:
    """Команда git в подготовленном дереве; отказ виден сразу."""
    subprocess.run(
        ["git", *args], cwd=where, check=True, capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Дерево с одной принятой записью на общей ветке и веткой изменения."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "them@example.com")
    _git(tmp_path, "config", "user.name", "Кто-то")
    records = tmp_path / "docs" / "decisions"
    records.mkdir(parents=True)
    (records / "007-a-record.md").write_text(RECORD, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "решение записью")
    _git(tmp_path, "checkout", "-q", "-b", "change")
    return tmp_path


def only(repo: Path) -> Path:
    """Единственная запись решения в подготовленном дереве."""
    return repo / "docs" / "decisions" / "007-a-record.md"


def commit(repo: Path, said: str) -> None:
    """Закрепляет правку в ветке изменения."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", said)


def test_rewritten_decision_is_caught(repo: Path, run_script: RunScript) -> None:
    """Переписанный раздел «Решение» — находка, а не молчание."""
    path = only(repo)
    path.write_text(
        path.read_text(encoding="utf-8").replace("Взят первый.", "Взят второй."), "utf-8"
    )
    commit(repo, "актуализировал решение")
    done = run_script("check_decisions_edit.py", "--base", "main", cwd=repo)
    assert done.code == edit.EXIT_FOUND, done.text
    assert "«Решение» переписан" in done.text, done.text


def test_rewritten_alternatives_are_caught(repo: Path, run_script: RunScript) -> None:
    """Отвергнутые варианты — часть решения: их правка задним числом тоже находка."""
    path = only(repo)
    path.write_text(
        path.read_text(encoding="utf-8").replace("дороже переключение", "проще, но медленнее"),
        "utf-8",
    )
    commit(repo, "поправил формулировку")
    done = run_script("check_decisions_edit.py", "--base", "main", cwd=repo)
    assert done.code == edit.EXIT_FOUND, done.text


def test_appended_consequences_are_allowed(repo: Path, run_script: RunScript) -> None:
    """Последствия копятся после решения — дописывать их не значит его править."""
    path = only(repo)
    path.write_text(
        path.read_text(encoding="utf-8") + "\nШаг 8 получил тот же механизм.\n", "utf-8"
    )
    commit(repo, "последствие дописано")
    done = run_script("check_decisions_edit.py", "--base", "main", cwd=repo)
    assert done.code == edit.EXIT_OK, done.text


def test_marking_superseded_is_allowed(repo: Path, run_script: RunScript) -> None:
    """Строка статуса меняется: ею запись и помечается заменённой."""
    path = only(repo)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "**Статус:** принято", "**Статус:** заменено записью 008"
        ),
        "utf-8",
    )
    commit(repo, "запись заменена новой")
    done = run_script("check_decisions_edit.py", "--base", "main", cwd=repo)
    assert done.code == edit.EXIT_OK, done.text


def test_a_new_record_is_not_an_edit(repo: Path, run_script: RunScript) -> None:
    """Новая запись — это и есть объявленный способ пересмотра."""
    (repo / "docs" / "decisions" / "008-supersedes-007.md").write_text(
        RECORD.replace("007", "008"), encoding="utf-8"
    )
    commit(repo, "пересмотр новой записью")
    done = run_script("check_decisions_edit.py", "--base", "main", cwd=repo)
    assert done.code == edit.EXIT_OK, done.text


def test_deleted_record_is_caught(repo: Path, run_script: RunScript) -> None:
    """Удалённая запись — тот же подлог, только полный: заменять нечем."""
    only(repo).unlink()
    commit(repo, "убрал запись")
    done = run_script("check_decisions_edit.py", "--base", "main", cwd=repo)
    assert done.code == edit.EXIT_FOUND, done.text
    assert "заменять нечем" in done.text, done.text


def test_unreachable_base_is_the_third_outcome(repo: Path, run_script: RunScript) -> None:
    """База не пришла — это «не отработал», а не «чисто» (045)."""
    done = run_script("check_decisions_edit.py", "--base", "origin/nowhere", cwd=repo)
    assert done.code == edit.EXIT_BROKEN, done.text
    assert "не отработал" in done.text, done.text


def test_frozen_sections_are_named_not_guessed() -> None:
    """Заморожен состав решения, а не весь документ: последствия сюда не входят."""
    parts = edit.frozen(RECORD)
    assert set(parts) == {"Контекст", "Решение", "Отвергнутые варианты"}, parts
