"""Новая ветка окна не толкается, пока у него три открытых изменения (#1085).

Проверяется то, без чего предел был бы строкой договора:

* предмет — открытые изменения ЭТОГО окна по трейлеру `Claude-Session`, а не
  все открытые: чужое окно предела не тратит;
* толчок в ветку, по которой изменение уже открыто, — починка своего и
  предела не прибавляет (вторая половина предиката, 051);
* отсутствие токена — отдельный исход, а не «чисто» (045);
* отказ называет, ЧТО делать вместо толчка (104);
* `preflight.py --push` держит толчок на пределе, а отказ канала — нет.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import git, load_script

module = load_script("check_open_limit.py")
preflight = load_script("preflight.py")

MINE = "https://claude.ai/code/session_mine"
THEIRS = "https://claude.ai/code/session_theirs"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Дерево под git с адресом `origin` и коммитом окна `MINE` в голове."""
    git(tmp_path, "init", "-q", "-b", "agent/новая")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "remote", "add", "origin", "https://github.com/o/r.git")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "основание (#1)")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "работа", "-m", f"Claude-Session: {MINE}")
    return tmp_path


def platform(
    monkeypatch: pytest.MonkeyPatch, sessions: dict[int, str], here: list[Any] | None = None
) -> list[str]:
    """Площадка: открытые изменения с сессией коммитов и ответ о голове ветки."""
    asked: list[str] = []
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")

    def request(_method: str, path: str, _token: str) -> Any:
        asked.append(path)
        return here or []

    def paginate(path: str, _token: str) -> Any:
        asked.append(path)
        if path.endswith("/commits"):
            number = int(path.split("/")[-2])
            return iter([{"commit": {"message": f"x\n\nClaude-Session: {sessions[number]}"}}])
        return iter([{"number": number} for number in sessions])

    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    return asked


def watch_push(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Вызовы git из предполётной; сам толчок не уходит наружу, а отвечает подделкой."""
    said: list[list[str]] = []
    original = subprocess.run

    def watched(args: Any, **rest: Any) -> Any:
        said.append(list(args))
        if "push" in args:
            return subprocess.CompletedProcess(args, 0, "толкнуто", "")
        return original(args, **rest)

    monkeypatch.setattr(preflight.subprocess, "run", watched)
    return said


def test_three_open_changes_of_the_window_refuse_a_new_branch(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Три открытых своих — отказ, и отказ называет их номера и выход (104)."""
    platform(monkeypatch, {11: MINE, 12: MINE, 13: MINE})
    code, said = module.look(repo, "agent/новая")
    assert code == module.EXIT_OVER
    assert "#11, #12, #13" in said and "сольётся" in said


def test_changes_of_another_window_do_not_spend_the_limit(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Чужие открытые предела не тратят: предмет — окно, а не площадка."""
    platform(monkeypatch, {11: MINE, 12: MINE, 13: THEIRS, 14: THEIRS})
    code, said = module.look(repo, "agent/новая")
    assert code == module.EXIT_OK and "2 изменений из 3" in said


def test_a_push_to_an_open_change_is_a_fix_not_a_new_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ветка с открытым изменением — починка своего, и предел её не держит (051)."""
    platform(monkeypatch, {11: MINE, 12: MINE, 13: MINE}, here=[{"number": 13}])
    code, said = module.look(repo, "agent/новая")
    assert code == module.EXIT_OK and "#13" in said


def test_no_token_is_not_clean(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Без токена — «не спросили», отдельный исход, а не «чисто» (045)."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    code, said = module.look(repo, "agent/новая")
    assert code == module.EXIT_UNASKED and "НЕ ПРОВЕРЕН" in said


def test_a_branch_without_the_trailer_is_not_the_subject(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ветка без своих коммитов с трейлером — не работа окна, и площадку не спрашивают."""
    git(repo, "reset", "-q", "--hard", "origin/main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "рукой")
    asked = platform(monkeypatch, {11: MINE, 12: MINE, 13: MINE})
    assert module.look(repo, "agent/новая")[0] == module.EXIT_OK
    assert asked == []


def test_the_entry_point_names_the_outcome(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`main` отдаёт исход вердикта и печатает отказ в поток ошибок."""
    platform(monkeypatch, {11: MINE, 12: MINE, 13: MINE})
    argv = ["--branch", "agent/новая", "--root", str(repo)]
    assert module.main(argv) == module.EXIT_OVER
    assert "толчок отвергнут" in capsys.readouterr().err


def test_preflight_holds_the_push_at_the_limit(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Предел вшит в толчок: `git push` при достигнутом пределе не звучит."""
    monkeypatch.setattr(
        preflight.check_branch_revival, "look", lambda *_: (0, "слитых изменений не несёт")
    )
    monkeypatch.setattr(preflight.check_open_limit, "look", lambda *_: (module.EXIT_OVER, "предел"))
    said = watch_push(monkeypatch)
    assert preflight.push_branch(repo) == preflight.EXIT_BROKEN
    assert not any("push" in one for one in said), f"толчок сверх предела случился: {said}"


def test_a_platform_refusal_does_not_hold_the_push(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ канала толчок не держит, но называется (051)."""
    monkeypatch.setattr(
        preflight.check_branch_revival, "look", lambda *_: (0, "слитых изменений не несёт")
    )

    def broken(*_: object) -> tuple[int, str]:
        raise preflight.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(preflight.check_open_limit, "look", broken)
    said = watch_push(monkeypatch)
    preflight.push_branch(repo)
    assert any("push" in one for one in said), "толчок задержан отказом канала"
    assert "предел открытых изменений не проверен" in capsys.readouterr().err


def test_own_open_reads_the_trailer_in_any_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Своё — если трейлер окна несёт ХОТЯ БЫ ОДИН коммит изменения, а не только последний."""
    pages: dict[str, list[dict[str, Any]]] = {
        "repos/o/r/pulls?state=open": [{"number": 1}, {"number": 2}],
        "repos/o/r/pulls/1/commits": [
            {"commit": {"message": f"x\n\nClaude-Session: {MINE}"}},
            {"commit": {"message": "слияние main без трейлера"}},
        ],
        "repos/o/r/pulls/2/commits": [{"commit": {"message": f"y\n\nClaude-Session: {THEIRS}"}}],
    }
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, _token: iter(pages[path]))
    assert [one["number"] for one in module.own_open("o/r", "токен", MINE)] == [1]


def test_a_merge_of_the_base_on_top_keeps_the_window(repo: Path) -> None:
    """Голова — слияние общей ветки без трейлера, а окно — по своим коммитам (взгляд на #1087)."""
    git(repo, "checkout", "-q", "-b", "база", "origin/main")
    git(
        repo, "commit", "-q", "--allow-empty", "-m", "чужое (#2)", "-m", f"Claude-Session: {THEIRS}"
    )
    git(repo, "checkout", "-q", "agent/новая")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "база")
    git(repo, "update-ref", "refs/remotes/origin/main", "база")
    assert module.session_of(repo) == MINE


def test_a_quoted_session_is_not_a_trailer() -> None:
    """Адрес окна в цитате — не трейлер: своё узнаётся строкой целиком (взгляд на #1087)."""
    quoted = f"оклик\n\nАдресат — окно, трейлер «Claude-Session: {MINE}» в коммитах"
    assert module.trailers_in(quoted) == set()
    assert module.trailers_in(f"x\n\nClaude-Session: {MINE}\n") == {MINE}


def test_overlaps_count_changes_opened_over_the_limit() -> None:
    """Замер: открытое при трёх открытых своих — превышение; чужие и закрытые — нет."""
    rows = [
        (1, "2026-10-01T10:00", None, "a"),
        (2, "2026-10-01T10:01", None, "a"),
        (3, "2026-10-01T10:02", "2026-10-01T10:05", "a"),
        (4, "2026-10-01T10:03", "2026-10-01T10:05", "a"),
        (5, "2026-10-01T10:04", None, "b"),
        (6, "2026-10-01T10:06", None, "a"),
        (7, "2026-10-01T10:07", None, ""),
    ]
    # 6 открыто после закрытия 3 и 4: у окна открыты лишь 1 и 2.
    assert module.overlaps(rows) == [4]


def test_the_measure_prints_the_count(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--measure` берёт окно из тела уплотнения, а время — у площадки."""
    monkeypatch.chdir(repo)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    body = f"x\n\nClaude-Session: {MINE}"
    monkeypatch.setattr(
        module.trunk_log,
        "git_log",
        lambda *_, **__: "".join(
            f"т (#{n}){module.trunk_log.FIELD}{body}{module.trunk_log.RECORD}" for n in (1, 2, 3, 4)
        ),
    )
    pulls = [
        {"number": n, "created_at": f"2026-10-01T10:0{n}", "closed_at": None} for n in (1, 2, 3, 4)
    ]
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter(pulls))
    assert module.main([module.MEASURE]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert "с известным окном 4" in out and out.rstrip().endswith("— 1"), out


def test_the_measure_refuses_a_shallow_history(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Замер на мелком клоне — отказ, а не число неполной истории (045, взгляд на #1087)."""
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)],
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(shallow)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([]))
    assert module.main([module.MEASURE]) == module.EXIT_BROKEN
    said = capsys.readouterr().err
    assert module.trunk_log.SHALLOW in said and "окна слитых изменений" in said, said


def shallow_clone_of(repo: Path, where: Path) -> Path:
    """Мелкий клон дерева окна: обе ветки по одному коммиту."""
    git(repo, "branch", "-f", "main", "origin/main")
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-single-branch", f"file://{repo}", str(where)],
        check=True,
        capture_output=True,
    )
    return where


def test_a_shallow_clone_is_refused_even_with_a_visible_trailer(repo: Path, tmp_path: Path) -> None:
    """Мелкий клон — отказ и при видимом трейлере (210, взгляды на #1094 и #1100).

    За срезом `base..HEAD` не ограничен своими коммитами, и видимый трейлер
    бывает чужим — его случай ниже.
    """
    with pytest.raises(module.NotRun, match="свои коммиты ветки"):
        module.session_of(shallow_clone_of(repo, tmp_path / "shallow"))


def test_a_foreign_trailer_behind_the_cut_is_not_taken(repo: Path, tmp_path: Path) -> None:
    """Случай взгляда на #1100: в ветку слита общая с чужим уплотнением, клон мелкий.

    Прежняя редакция возвращала чужое окно; теперь — отказ, а не чужой счёт.
    """
    git(repo, "checkout", "-q", "origin/main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "чужое уплотнение\n\nClaude-Session: theirs")
    theirs = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    for one in range(3):
        git(repo, "commit", "-q", "--allow-empty", "-m", f"общая ветка {one}")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "checkout", "-q", "-")
    git(repo, "commit", "-q", "--allow-empty", "-m", "своё без трейлера")
    git(repo, "merge", "-q", "--no-edit", theirs)
    shallow = tmp_path / "shallow"
    git(repo, "branch", "-f", "main", "origin/main")
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--depth",
            "3",
            "--no-single-branch",
            f"file://{repo}",
            str(shallow),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(module.NotRun, match="свои коммиты ветки"):
        module.session_of(shallow)


def test_a_shallow_branch_without_a_visible_trailer_is_refused(repo: Path, tmp_path: Path) -> None:
    """Трейлера не видно и клон мелкий — отказ, а не «предел не про неё» (#1094)."""
    git(repo, "commit", "-q", "--allow-empty", "-m", "рукой поверх среза")
    shallow = shallow_clone_of(repo, tmp_path / "shallow")
    with pytest.raises(module.NotRun, match="свои коммиты ветки"):
        module.session_of(shallow)
