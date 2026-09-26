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

from tests.conftest import Run, RunScript, load_script

edit = load_script("check_decisions_edit.py")

RECORD = """# 007. Заголовок записи

> **Читатель:** тот, кто ведёт конвейер.

**Статус:** принято · **Дата:** 2026-09-11 · **Задача:** [#7](../../../issues/7)

## Контекст

Было два пути, и оба с ценой. Договор — [`pipeline.md`](../pipeline.md).

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


def replaced(repo: Path, run_script: RunScript, old: str, new: str, said: str) -> Run:
    """Заменяет текст в записи, закрепляет правку и прогоняет гейт (093: третий случай)."""
    path = only(repo)
    text = path.read_text(encoding="utf-8")
    assert old in text, f"в записи нет «{old}» — правка ничего бы не проверила"
    path.write_text(text.replace(old, new), "utf-8")
    commit(repo, said)
    return run_script("check_decisions_edit.py", "--base", "main", cwd=repo)


def test_rewritten_decision_is_caught(repo: Path, run_script: RunScript) -> None:
    """Переписанный раздел «Решение» — находка, а не молчание."""
    done = replaced(repo, run_script, "Взят первый.", "Взят второй.", "актуализировал решение")
    assert done.code == edit.EXIT_FOUND, done.text
    assert "«Решение» переписан" in done.text, done.text


def test_rewritten_alternatives_are_caught(repo: Path, run_script: RunScript) -> None:
    """Отвергнутые варианты — часть решения: их правка задним числом тоже находка."""
    done = replaced(
        repo, run_script, "дороже переключение", "проще, но медленнее", "поправил формулировку"
    )
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
    done = replaced(
        repo,
        run_script,
        "**Статус:** принято",
        "**Статус:** заменено записью 008",
        "запись заменена новой",
    )
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


def test_a_moved_link_target_is_not_a_rewrite(repo: Path, run_script: RunScript) -> None:
    """Перевести цель ссылки на переехавший документ — не переписать решение (#840)."""
    done = replaced(
        repo, run_script, "](../pipeline.md)", "](../use/pipeline.md)", "ссылка на новом месте"
    )
    assert done.code == edit.EXIT_OK, done.text


def test_the_link_text_is_still_content(repo: Path, run_script: RunScript) -> None:
    """Текст ссылки остаётся содержанием: его правка — переписывание."""
    done = replaced(
        repo, run_script, "[`pipeline.md`]", "[`use/pipeline.md`]", "текст ссылки переписан"
    )
    assert done.code == edit.EXIT_FOUND, done.text
