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
    assert module.stale("o/gone", "token") is None, "отказ — «не ответила», а не «совпало»"


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


def test_a_tree_that_agrees_with_the_platform_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Имена в дереве совпали с каноном — исход чистый.

    Прогонялись отказ и находка, а «чисто» у гейта объявлено и не проверялось
    ни разу
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    Сеть сюда не ходит: канон приходит окружением прогона, а редирект не
    спрашивается без токена.
    """
    root = repo_with(tmp_path, "см. https://github.com/o/name/blob/main/x\n")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/name")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert module.main(["--root", str(root)]) == module.EXIT_OK


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


def test_an_api_address_names_the_repository_not_repos(tmp_path: Path) -> None:
    """`api.github.com/repos/o/name` — имя `o/name`, а не владелец `repos` (#1065)."""
    root = repo_with(tmp_path, "GET https://api.github.com/repos/o/name/issues\n")
    found = module.mentions(root)
    assert "o/name" in found
    assert not [name for name in found if name.startswith("repos/")], found


def test_samples_in_tests_are_not_asked(tmp_path: Path) -> None:
    """Образцы в `tests/` — данные проверок: их не спрашивают у площадки (#1065).

    Вторая половина — то же имя вне `tests/` по-прежнему находится.
    """
    root = repo_with(tmp_path, "https://github.com/o/kept/x\n")
    (root / "tests").mkdir()
    (root / "tests" / "t.py").write_text('"https://github.com/o/sample/x"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    found = module.mentions(root)
    assert "o/kept" in found
    assert "o/sample" not in found


@pytest.mark.parametrize(
    "line",
    [
        "https://github.com/orgs/o/people",
        "https://github.com/users/o/projects",
        "https://github.com/user-attachments/assets/x.png",
        "https://github.com/apps/claude/installations",
    ],
)
def test_a_service_path_is_not_an_owner(tmp_path: Path, line: str) -> None:
    """Служебный сегмент пути площадки — не владелец репозитория (`6f964eb`)."""
    root = repo_with(tmp_path, line + "\n")
    assert module.mentions(root) == {}, module.mentions(root)


def test_an_uploads_address_names_the_repository(tmp_path: Path) -> None:
    """`uploads.github.com/repos/o/name` — имя `o/name`, как у адреса API."""
    root = repo_with(tmp_path, "POST https://uploads.github.com/repos/o/name/releases/1/assets\n")
    assert list(module.mentions(root)) == ["o/name"]


@pytest.mark.parametrize(
    "line",
    [
        "https://api.github.com/user/repos",
        "https://api.github.com/gists/abc123",
        "https://api.github.com/networks/o/r/events",
        "https://api.github.com/repositories/42/x",
        "https://api.github.com/app/installations",
        "https://api.github.com/repos/o",
    ],
)
def test_an_api_address_is_a_name_only_under_repos(tmp_path: Path, line: str) -> None:
    """У хостов API имя — только `/repos/<владелец>/<имя>`; иной корень — не имя (210, #1082)."""
    root = repo_with(tmp_path, line + "\n")
    assert module.mentions(root) == {}, module.mentions(root)


def test_an_unanswered_name_is_counted_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ площадки — «не ответила», и число таких печатается (взгляд на #1082)."""
    root = repo_with(tmp_path, "https://github.com/o/name/x\nhttps://github.com/gone/away/x\n")
    monkeypatch.setattr(module, "canon", lambda: ("o/name", True))
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "token")

    def answer(_method: str, path: str, *_: object, **__: object) -> dict[str, str]:
        if "gone" in path:
            raise module.ghrest.TransportError("404")
        return {"full_name": "o/name"}

    monkeypatch.setattr(module.ghrest, "request", answer)
    assert module.main(["--root", str(root)]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "не ответила на 1 из 2" in said and "спрошено 2" in said, said
