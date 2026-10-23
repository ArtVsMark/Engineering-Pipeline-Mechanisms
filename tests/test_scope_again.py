"""Повторный толчок судится по изменённому с последней зелёной головы (#1602).

Подделка — настоящий git: голова, база, влитая база и сдвинутый предок
строятся коммитами, а не подстановкой ответа `touched_paths`.
"""

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script
from tests.test_scope import git

scope = load_script("scope.py")
preflight = load_script("preflight.py")


def write(root: Path, name: str, text: str) -> None:
    """Кладёт файл дерева."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(root: Path, message: str) -> str:
    """Коммит всего дерева; отдаёт его отпечаток."""
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD").strip()


def tree(tmp_path: Path) -> Path:
    """База: `a` зовёт `c`, у `a` и `b` по тесту; ветка `agent/x` от базы."""
    root = tmp_path
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    write(root, "scripts/a.py", "import c\n")
    write(root, "scripts/b.py", "B = 1\n")
    write(root, "scripts/c.py", "C = 1\n")
    write(root, "tests/test_a.py", 'load_script("a.py")\n')
    write(root, "tests/test_b.py", 'load_script("b.py")\n')
    write(root, "README.md", "x\n")
    commit(root, "база")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(root, "checkout", "-qb", "agent/x")
    return root


def green_head(root: Path) -> str:
    """Первый толчок ветки: правка `a` — прежняя зелёная голова."""
    write(root, "scripts/a.py", "import c\nA = 2\n")
    return commit(root, "первый толчок")


def move_base(root: Path, name: str, text: str) -> None:
    """Общая ветка получает свою правку, ветка вливает её."""
    git(root, "checkout", "-q", "main")
    write(root, name, text)
    commit(root, "чужое в базе")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(root, "checkout", "-q", "agent/x")
    git(root, "-c", "core.editor=true", "merge", "-q", "--no-edit", "origin/main")


def test_a_new_message_alone_runs_no_tests(tmp_path: Path) -> None:
    """Поменялось только сообщение коммита — дерево то же: сценарий text, тестов ноль."""
    root = tree(tmp_path)
    since = green_head(root)
    git(root, "commit", "-q", "--amend", "-m", "первый толчок\n\nРазобрано: 1234567")
    said = scope.choose(root, "origin/main", since)
    assert (said.scenario, said.tests) == (scope.TEXT, ())
    assert since[:12] in said.why


def test_only_what_changed_since_the_green_head_is_judged(tmp_path: Path) -> None:
    """Повтор правит `b` — гонится тест `b`, а не `a`, проверенный на прежней голове."""
    root = tree(tmp_path)
    since = green_head(root)
    write(root, "scripts/b.py", "B = 2\n")
    commit(root, "починка находки")
    assert scope.choose(root, "origin/main", since).tests == ("tests/test_b.py",)
    assert scope.choose(root, "origin/main").tests == ("tests/test_a.py", "tests/test_b.py")


def test_a_merged_base_is_subtracted(tmp_path: Path) -> None:
    """Влитая база правит `b`: файл совпадает с базой и не тронут; несвязанное — повтора нет."""
    root = tree(tmp_path)
    since = green_head(root)
    move_base(root, "scripts/b.py", "B = 3\n")
    said = scope.choose(root, "origin/main", since)
    assert said.tests == ()
    assert "база сдвинулась" in said.why


def test_a_moved_base_runs_the_intersection(tmp_path: Path) -> None:
    """База правит `c`, который зовёт тронутый изменением `a`: гонится пересечение — тест `a`."""
    root = tree(tmp_path)
    since = green_head(root)
    move_base(root, "scripts/c.py", "C = 2\n")
    assert scope.choose(root, "origin/main", since).tests == ("tests/test_a.py",)


@pytest.mark.parametrize(
    ("left", "right", "both"),
    [
        (None, ("t1",), ("t1",)),
        (("t1",), None, ("t1",)),
        (None, None, None),
        (("t1", "t2"), ("t2", "t3"), ("t2",)),
    ],
)
def test_the_intersection_of_choices(
    left: tuple[str, ...] | None, right: tuple[str, ...] | None, both: tuple[str, ...] | None
) -> None:
    """«Все» в пересечении уступает другому выбору; два списка — общие файлы."""
    assert scope.common(left, right) == both


def test_the_union_of_choices() -> None:
    """Объединение с «все» — «все»; два списка — оба."""
    assert scope.joined(("t1",), None) is None
    assert scope.joined(("t1",), ("t2",)) == ("t1", "t2")


def platform(monkeypatch: pytest.MonkeyPatch, commits: list[str], green: set[str]) -> None:
    """Площадка: коммиты изменения и зелёный сводный гейт на названных."""

    def answer(method: str, path: str, token: str, body: Any = None) -> Any:
        if "/pulls/" in path:
            return [{"sha": one} for one in commits]
        sha = path.split("/commits/")[1].split("/")[0]
        conclusion = "success" if sha in green else "failure"
        return {"check_runs": [{"name": scope.GREEN_CHECK, "conclusion": conclusion}]}

    monkeypatch.setattr(scope.ghrest, "request", answer)


def test_the_last_green_head_is_asked_of_the_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Зелёная — последняя голова с `success`, кроме нынешней; красная новее не в счёт."""
    root = tree(tmp_path)
    old = green_head(root)
    write(root, "scripts/b.py", "B = 2\n")
    red = commit(root, "красный толчок")
    write(root, "scripts/b.py", "B = 3\n")
    head = commit(root, "нынешний")
    platform(monkeypatch, [old, red, head], {old, head})
    assert scope.last_green("о/р", 7, "т", root) == old


def test_no_green_head_judges_from_the_fork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Зелёной нет или её нет в дереве (история переписана) — пусто: суд от общего предка."""
    root = tree(tmp_path)
    head = green_head(root)
    platform(monkeypatch, ["0" * 40, head], {"0" * 40})
    assert scope.last_green("о/р", 7, "т", root) == ""


def test_a_silent_platform_is_the_third_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Площадка не ответила — `NotRun`, а `main` судит от предка и говорит об этом."""
    root = tree(tmp_path)
    green_head(root)

    def refuse(*args: object, **kwargs: object) -> None:
        raise scope.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(scope.ghrest, "request", refuse)
    with pytest.raises(scope.NotRun):
        scope.last_green("о/р", 7, "т", root)
    argv = ["--root", str(root), "--base", "origin/main", "--pr", "7", "--tests"]
    assert scope.main(argv) == scope.EXIT_OK
    said = capsys.readouterr()
    assert "суд от общего предка" in said.err
    assert said.out.split() == ["tests/test_a.py"]


def test_the_window_judges_from_its_pushed_head(tmp_path: Path) -> None:
    """У окна прежняя голова — `origin/<ветка>`; ветка не толкнута — пусто."""
    root = tree(tmp_path)
    assert preflight.pushed(root) == ""
    since = green_head(root)
    git(root, "update-ref", "refs/remotes/origin/agent/x", since)
    assert preflight.pushed(root) == since


def test_the_preflight_hands_the_pushed_head_to_the_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Предполётная зовёт выбор с толкнутой головой, а не от предка всегда."""
    seen: list[str] = []

    def choose(root: Path, base: str, since: str = "") -> object:
        seen.append(since)
        return scope.Choice(scope.TEXT, (), "")

    monkeypatch.setattr(preflight, "pushed", lambda root: "abc")
    monkeypatch.setattr(preflight.scope, "choose", choose)
    preflight.chosen_scope(tmp_path, everything=False)
    assert seen == ["abc"]


def junit(tmp_path: Path, *failed: str) -> Path:
    """Отчёт pytest: упавшие по `classname`, один зелёный рядом."""
    cases = "".join(
        f'<testcase classname="{one}" name="t"><failure message="x"/></testcase>' for one in failed
    )
    path = tmp_path / "tests.xml"
    path.write_text(
        f'<testsuites><testsuite>{cases}<testcase classname="tests.test_ok" name="t"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def test_failed_files_are_read_from_the_report(tmp_path: Path) -> None:
    """Файл — из `classname`, с классом и без; зелёный не в счёт."""
    report = junit(tmp_path, "tests.test_a", "tests.test_b.TestCase")
    assert scope.failed_files(report) == {"tests/test_a.py", "tests/test_b.py"}


def test_a_full_choice_misses_nothing() -> None:
    """Выбор «все» ничего не пропускает; список — упавшее вне него."""
    failed = {"tests/test_a.py", "tests/test_b.py"}
    assert scope.missed(scope.Choice(scope.FULL, None, ""), failed) == []
    assert scope.missed(scope.Choice(scope.CODE, ("tests/test_a.py",), ""), failed) == [
        "tests/test_b.py"
    ]


def test_a_red_full_run_names_the_miss(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Слитая правка `a` от `HEAD^`; упал `b` — выбор его пропустил, и это названо находкой."""
    root = tree(tmp_path / "дерево")
    green_head(root)
    argv = ["--root", str(root), "--base", "HEAD^", "--missed"]
    assert scope.main([*argv, str(junit(tmp_path, "tests.test_b"))]) == scope.EXIT_OK
    said = capsys.readouterr().out
    assert "::error::выбор тестов пропустил tests/test_b.py" in said
    assert "находка о графе" in said
    assert scope.main([*argv, str(junit(tmp_path, "tests.test_a"))]) == scope.EXIT_OK
    assert "выбор задел все упавшие" in capsys.readouterr().out


def test_an_unreadable_report_is_the_third_outcome(tmp_path: Path) -> None:
    """Отчёт не разбирается — «не отработал», а не «пропусков нет» (039)."""
    root = tree(tmp_path / "дерево")
    green_head(root)
    bad = tmp_path / "bad.xml"
    bad.write_text("<не xml", encoding="utf-8")
    argv = ["--root", str(root), "--base", "HEAD^", "--missed", str(bad)]
    assert scope.main(argv) == scope.EXIT_BROKEN


def test_the_fork_and_the_miss_are_asked_by_name(tmp_path: Path) -> None:
    """`fork_of` — общий предок с базой, нет базы — `NotRun`; `said_missed` — исход шага."""
    root = tree(tmp_path / "дерево")
    base = git(root, "rev-parse", "HEAD").strip()
    green_head(root)
    assert scope.fork_of(root, "origin/main") == base
    with pytest.raises(scope.NotRun):
        scope.fork_of(root, "origin/нет")
    report = junit(tmp_path, "tests.test_a")
    assert scope.said_missed(root, "HEAD^", report) == scope.EXIT_OK
