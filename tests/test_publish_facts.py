"""Публикация фактов на ветку `badges` проверяется прогоном на настоящем git.

Прежде публикация жила сценарием оболочки, и гейт узнавал публикуемое разбором
этого сценария; три захода взгляда подряд находили новую форму записи (решение
владельца 08.10.2026, #639). Теперь запись — `scripts/publish_facts.py`, и
проверяется её поведение: что легло на ветку, что на ней уцелело, куда и как
ушёл толчок.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("publish_facts.py")


def git(*args: str, cwd: Path) -> str:
    """Вызов git в каталоге стенда; отказ — падение теста."""
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout


@pytest.fixture
def stand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Голый удалённый репозиторий, клон потребителя и собранный facts.json."""
    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    clone = tmp_path / "clone"
    git("init", "-q", "-b", "main", str(clone), cwd=tmp_path)
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        git("config", key, value, cwd=clone)
    (clone / "x").write_text("x", encoding="utf-8")
    git("add", "x", cwd=clone)
    git("commit", "-q", "-m", "x", cwd=clone)
    git("remote", "add", "origin", str(remote), cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    source = tmp_path / "facts.json"
    source.write_text('{"a": 1}\n', encoding="utf-8")
    monkeypatch.chdir(clone)
    return {"remote": remote, "clone": clone, "source": source, "tmp": tmp_path}


#: Ветка и путь, куда публикация ОБЯЗАНА писать, — литералами вне модуля. Сверка со
#: своей же константой `publish_facts.BRANCH` проверяла намерение, а не факт:
#: `BRANCH = "main"` проходил бы зелёным (взгляд на #1233), и то же с путём
#: `PUBLISHES` (взгляд на #1240).
PUBLISHED_TO = "badges"
PUBLISHED_PATH = ".github/badges/facts.json"


def on_branch(remote: Path, path: str) -> str:
    """Содержимое файла на ветке `badges` удалённого репозитория."""
    return git("show", f"{PUBLISHED_TO}:{path}", cwd=remote)


def test_the_first_publication_starts_the_branch(stand: dict[str, Path]) -> None:
    """Ветки нет — публикация начинает её сиротой и кладёт ровно `PUBLISHES`."""
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    assert module.PUBLISHES == (PUBLISHED_PATH,)
    assert on_branch(stand["remote"], PUBLISHED_PATH) == '{"a": 1}\n'


def test_a_publication_lays_over_and_keeps_the_rest(stand: dict[str, Path]) -> None:
    """Поверх ветки: свой файл потребителя на ней уцелел, факты обновились."""
    module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    other = stand["tmp"] / "other"
    git("clone", "-q", "-b", PUBLISHED_TO, str(stand["remote"]), str(other), cwd=stand["tmp"])
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        git("config", key, value, cwd=other)
    (other / "own.svg").write_text("<svg/>", encoding="utf-8")
    git("add", "own.svg", cwd=other)
    git("commit", "-q", "-m", "свой значок", cwd=other)
    git("push", "-q", "origin", PUBLISHED_TO, cwd=other)
    stand["source"].write_text('{"a": 2}\n', encoding="utf-8")
    assert module.publish(stand["source"], stand["tmp"] / "w2", sha="def")
    assert on_branch(stand["remote"], "own.svg") == "<svg/>"
    assert on_branch(stand["remote"], PUBLISHED_PATH) == '{"a": 2}\n'


def test_unchanged_facts_make_no_commit(stand: dict[str, Path]) -> None:
    """Те же факты — коммита нет, и это не отказ."""
    module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    assert not module.publish(stand["source"], stand["tmp"] / "w2", sha="abc")


def test_an_unreadable_branch_is_not_overwritten(stand: dict[str, Path]) -> None:
    """Ветка не прочитана не потому, что её нет, — отказ, а не сирота поверх."""
    git("remote", "set-url", "origin", str(stand["tmp"] / "нет.git"), cwd=stand["clone"])
    with pytest.raises(module.NotPublished, match="не прочитана"):
        module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")


def test_a_racing_branch_is_refused_not_overwritten(
    stand: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ветка сдвинулась между выборкой и толчком — толчок без `--force` отказан."""
    module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    real = module.checkout

    def checkout_then_race(workdir: Path) -> None:
        real(workdir)
        other = stand["tmp"] / "racer"
        git("clone", "-q", "-b", PUBLISHED_TO, str(stand["remote"]), str(other), cwd=stand["tmp"])
        for key, value in (("user.name", "t"), ("user.email", "t@t")):
            git("config", key, value, cwd=other)
        (other / "race").write_text("r", encoding="utf-8")
        git("add", "race", cwd=other)
        git("commit", "-q", "-m", "гонка", cwd=other)
        git("push", "-q", "origin", PUBLISHED_TO, cwd=other)

    monkeypatch.setattr(module, "checkout", checkout_then_race)
    stand["source"].write_text('{"a": 3}\n', encoding="utf-8")
    with pytest.raises(module.NotPublished, match="push"):
        module.publish(stand["source"], stand["tmp"] / "w2", sha="ghi")
    assert on_branch(stand["remote"], "race") == "r", "толчок затёр чужое"


def test_the_exit_names_the_refusal(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ — код 2 и `::error::` с причиной; успех — код 0 и адрес файла."""
    argv = [
        str(stand["source"]),
        "--workdir",
        str(stand["tmp"] / "w1"),
        "--sha",
        "a",
        "--repo",
        "o/r",
    ]
    assert module.main(argv) == module.EXIT_OK
    assert (
        "raw.githubusercontent.com/o/r/badges/.github/badges/facts.json" in capsys.readouterr().out
    )
    git("remote", "set-url", "origin", str(stand["tmp"] / "нет.git"), cwd=stand["clone"])
    argv[2] = str(stand["tmp"] / "w2")
    assert module.main(argv) == module.EXIT_BROKEN
    assert "::error::факты не опубликованы" in capsys.readouterr().out


def test_a_missing_source_is_a_refusal_not_a_traceback(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Нет `facts.json` — код 2 и `::error::`, а не трейсбек с кодом 1 (039, взгляд на #1233)."""
    argv = [str(stand["tmp"] / "нет.json"), "--workdir", str(stand["tmp"] / "w1")]
    argv += ["--sha", "a", "--repo", "o/r"]
    assert module.main(argv) == module.EXIT_BROKEN
    assert "::error::факты не опубликованы" in capsys.readouterr().out


def test_a_refused_signature_is_a_refusal(
    stand: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отказ `git config` — «не опубликовано», а не коммит под чужой подписью (взгляд на #1233)."""
    real: Callable[..., subprocess.CompletedProcess[str]] = module.git

    def refusing(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("config",):
            return subprocess.CompletedProcess(list(args), 1, "", "нет прав")
        return real(*args, cwd=cwd)

    monkeypatch.setattr(module, "git", refusing)
    with pytest.raises(module.NotPublished, match="подпись"):
        module.publish(stand["source"], stand["tmp"] / "w1", sha="a")
