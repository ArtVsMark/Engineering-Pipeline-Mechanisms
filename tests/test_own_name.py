"""Своё имя берётся у площадки, а не из памяти дерева.

Правило 172 родилось у соседа так: после трёх переименований 28 ссылок
устарели, и все восемь его гейтов остались зелёными — имя не сверял ни один.
Проверяется здесь то, без чего перенос был бы копией имени функции:

* переименованное ловится через ОТВЕТ площадки, а не сравнением с каноном:
  старое имя не похоже на новое, и сравнить их нечем;
* локальный заход не краснеет на регистре: `origin` хранит то, что записал
  клонировавший, и каноном не является;
* перепись идёт по отслеживаемым файлам: в кешах имён тысячи, и ни одно из них
  проект не правит.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("check_own_name.py")


def repo_with(tmp_path: Path, text: str) -> Path:
    """Дерево под git с одним файлом: перепись читает только отслеживаемое."""
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "a.md").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_a_name_is_found_inside_a_link(tmp_path: Path) -> None:
    """Имя ловится в ссылке — там оно и живёт."""
    root = repo_with(tmp_path, "см. https://github.com/o/name/blob/main/x\n")
    assert "o/name" in module.mentions(root)


def test_a_raw_link_counts_too(tmp_path: Path) -> None:
    """Значок приходит с `raw.githubusercontent.com`, и это тот же адрес."""
    root = repo_with(tmp_path, "![з](https://raw.githubusercontent.com/o/name/badges/x.svg)\n")
    assert "o/name" in module.mentions(root)


def test_an_untracked_file_is_not_read(tmp_path: Path) -> None:
    """Неотслеживаемое из-под `.gitignore` не читается.

    Обход всего дерева читал бы `.venv` и кеши сборки: живой замер 10.09.2026 —
    там нашлось больше двухсот чужих имён, включая 1450 упоминаний одного
    индекса пакетов. Ни одно из них проект не правит.
    """
    root = repo_with(tmp_path, "https://github.com/o/tracked/x\n")
    (root / ".gitignore").write_text("hidden.md\n", encoding="utf-8")
    (root / "hidden.md").write_text("https://github.com/o/hidden/x\n", encoding="utf-8")
    found = module.mentions(root)
    assert "o/tracked" in found
    assert "o/hidden" not in found


def test_a_renamed_repo_is_caught_by_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переименованное ловится ответом площадки, а не сравнением имён.

    Старое имя отвечает по редиректу и снаружи выглядит рабочим; сравнить его с
    новым нечем — они не похожи. Зато площадка называет `full_name`.
    """
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"full_name": "o/new"})
    assert module.stale("o/old", "token") == "o/new"


def test_a_name_that_agrees_is_not_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Совпало — находки нет."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"full_name": "o/same"})
    assert module.stale("o/same", "token") == ""


def test_a_refusal_on_one_name_is_not_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Чужой репозиторий закрыт или удалён — это не наша находка (084).

    Отказ на одном имени не роняет гейт и не выдаётся за расхождение: «не
    спросили» и «совпало» — разные вещи, и счёт спрошенных печатается рядом.
    """

    def broken(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("404")

    monkeypatch.setattr(module.ghrest, "request", broken)
    assert module.stale("o/gone", "token") == ""


def test_the_platform_name_beats_the_origin_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """`GITHUB_REPOSITORY` точен по регистру, `origin` — нет.

    У нас самих `origin` записан строчными, а площадка отвечает
    `ArtVsMark/Engineering-Pipeline-Mechanisms`. Краснеть на этом значило бы
    краснеть у каждого, кто склонировал по строчному адресу (045).
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/Name")
    assert module.canon() == ("o/Name", True)
    monkeypatch.delenv("GITHUB_REPOSITORY")
    name, exact = module.canon()
    assert exact is False, "имя из origin выдано за точное"
    assert "/" in name


def test_an_empty_tree_is_the_third_outcome(tmp_path: Path) -> None:
    """Имён в дереве нет — гейт падает, а не проходит вхолостую (075)."""
    root = repo_with(tmp_path, "ни одного адреса\n")
    assert module.mentions(root) == {}
    assert module.main(["--root", str(root)]) == module.EXIT_BROKEN


def test_a_foreign_rename_is_caught_and_named_as_foreign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Чужое переименование ловится и НАЗЫВАЕТСЯ чужим (находка #130).

    Прежде докстрока обещала, что чужие имена не предмет, а второй проход
    спрашивал площадку обо всех — переименованный каталог краснил бы гейт
    вопреки написанному. Ссылка чинится у нас и нами, поэтому находка наша; но
    кто переименовался — своё или чужое — читателю сказано (154).
    """
    root = repo_with(tmp_path, "https://github.com/other/catalogue/x\n")
    monkeypatch.setattr(module, "canon", lambda: ("o/name", True))
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "token")
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"full_name": "other/renamed"})
    code = module.main(["--root", str(root)])
    said = capsys.readouterr().out
    assert code == module.EXIT_FOUND, said
    assert "other/renamed" in said and "чужое" in said, said


def test_our_own_rename_is_named_as_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Своё переименование названо своим: отвечает за него не тот, кто за чужое."""
    root = repo_with(tmp_path, "https://github.com/o/name/x\n")
    monkeypatch.setattr(module, "canon", lambda: ("o/name", True))
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "token")
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"full_name": "o/new"})
    code = module.main(["--root", str(root)])
    said = capsys.readouterr().out
    assert code == module.EXIT_FOUND, said
    assert "своё" in said, said
