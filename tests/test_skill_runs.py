"""Сводка журнала навыков: кого зовут, кого нет, и третий исход (#1449).

Набор идёт на подделке журнала: вызовы, отказы, строка не той формы, вызов без
имени и навык дерева без единого вызова. Пустой или нечитаемый журнал —
третий исход с причиной, а не «вызовов ноль» (045).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import RunScript, load_script

module = load_script("skill_runs.py")


def line(skill: str | None, outcome: str = "ok", ts: str = "2026-10-17T10:00:00+00:00") -> str:
    """Строка журнала в форме хука."""
    return json.dumps({"ts": ts, "skill": skill, "outcome": outcome, "session": "с1"})


def tree(root: Path, *names: str) -> Path:
    """Дерево с навыками по именам каталогов."""
    for one in names:
        (root / ".claude" / "skills" / one).mkdir(parents=True)
        (root / ".claude" / "skills" / one / "SKILL.md").write_text("---\n", encoding="utf-8")
    return root


def written(root: Path, *lines: str) -> Path:
    """Кладёт журнал в своё место дерева."""
    where: Path = root / module.JOURNAL
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text("".join(one + "\n" for one in lines), encoding="utf-8")
    return where


def test_the_journal_is_parsed_line_by_line() -> None:
    """Вызовы, отказы, последний день; строка не той формы — номером, без имени — счётом."""
    journal = module.parse(
        [
            line("a"),
            line("a", "fail", "2026-10-18T09:00:00+00:00"),
            "не json",
            line("a", "иначе"),
            line("a", ts="2026-10-17T10:00:00"),
            "[1]",
            "",
            line(None),
            line("плагин:x"),
        ]
    )
    a = journal.runs["a"]
    assert (a.calls, a.fails, module.day(a.last)) == (2, 1, "2026-10-18")
    assert journal.malformed == [3, 4, 5, 6]
    assert journal.nameless == 1
    assert set(journal.runs) == {"a", "плагин:x"}
    assert journal.sessions == {"с1"}


def test_an_uncalled_skill_is_named_and_the_outcome_is_one(
    tmp_path: Path, run_script: RunScript
) -> None:
    """Навык дерева без вызова — поимённо, исход 1; вызовы вне дерева названы отдельно."""
    root = tree(tmp_path, "a", "b", "c")
    written(root, line("a"), line("b", "fail"), line("плагин:x"), "битая")
    run = run_script("skill_runs.py", "--root", str(root))
    assert run.code == module.EXIT_UNCALLED, run.text
    quiet = run.out.split("## Не звали ни разу", 1)[1].split("##", 1)[0]
    assert "`c`" in quiet and "`a`" not in quiet, quiet
    assert "| `b` | 1 | 1 | 2026-10-17 |" in run.out
    assert "`плагин:x` — 1" in run.out
    assert "Строк не той формы: 1 (номера: 4)" in run.out
    assert "не звали ни разу: 1 из 3 — c" in run.out


def test_every_skill_called_is_an_empty_state_with_its_day(
    tmp_path: Path, run_script: RunScript
) -> None:
    """Все навыки звали — исход 0, а пустота раздела названа с днём обхода (027)."""
    root = tree(tmp_path, "a")
    written(root, line("a"))
    run = run_script("skill_runs.py", "--root", str(root))
    assert run.code == module.EXIT_OK, run.text
    assert "Пусто на " in run.out and "каждый навык дерева звали: 1" in run.out


@pytest.mark.parametrize(
    "lines",
    [None, (), ("битая", "[1]")],
    ids=["журнала-нет", "журнал-пуст", "только-битые"],
)
def test_an_absent_or_empty_journal_does_not_run(
    lines: tuple[str, ...] | None, tmp_path: Path, run_script: RunScript
) -> None:
    """Нет журнала, он пуст или в нём ни одной строки журнала — исход 2 с причиной."""
    root = tree(tmp_path, "a")
    if lines is not None:
        written(root, *lines)
    run = run_script("skill_runs.py", "--root", str(root))
    assert run.code == module.EXIT_BROKEN and "не отработала" in run.err, run.text
    assert "журнал" in run.err


def test_an_unreadable_journal_does_not_run(tmp_path: Path, run_script: RunScript) -> None:
    """Журнал не читается — исход 2, а не трасса с кодом 1 (039)."""
    root = tree(tmp_path, "a")
    (root / module.JOURNAL).mkdir(parents=True)
    run = run_script("skill_runs.py", "--root", str(root))
    assert run.code == module.EXIT_BROKEN and "не прочитан" in run.err, run.text


def test_a_tree_without_skills_does_not_run(tmp_path: Path, run_script: RunScript) -> None:
    """Навыков нет — сводить не с чем: исход 2, а не «все звали» (075)."""
    written(tmp_path, line("a"))
    run = run_script("skill_runs.py", "--root", str(tmp_path))
    assert run.code == module.EXIT_BROKEN and "навыков" in run.err, run.text


def test_the_cloud_window_does_not_write(tmp_path: Path, run_script: RunScript) -> None:
    """`--apply` из облачного окна — отказ до записи: туда пишет локальное окно (131)."""
    root = tree(tmp_path, "a")
    written(root, line("a"))
    run = run_script(
        "skill_runs.py",
        "--root",
        str(root),
        "--repo",
        "o/r",
        "--apply",
        env={"CLAUDE_CODE_REMOTE": "true", "GITHUB_TOKEN": "x"},
    )
    assert run.code == module.EXIT_BROKEN and "131" in run.err, run.text


@pytest.mark.parametrize(
    ("number", "verb"), [(None, "POST"), (7, "PATCH")], ids=["заводит", "обновляет"]
)
def test_apply_keeps_one_live_issue(
    number: int | None, verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--apply` заводит живую задачу с маркером или переписывает найденную по месту."""
    root = tree(tmp_path, "a")
    written(root, line("a"))
    sent: list[tuple[str, str, Any]] = []
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(module.findings, "live_issue", lambda repo, token, marker: (number, ""))

    def request(method: str, url: str, token: str, data: Any = None) -> dict[str, int]:
        """Запись площадки — в список, а не по сети."""
        sent.append((method, url, data))
        return {"number": 9}

    monkeypatch.setattr(module.ghrest, "request", request)
    assert module.main(["--root", str(root), "--repo", "o/r", "--apply"]) == module.EXIT_OK
    [(method, url, data)] = sent
    assert method == verb and data["body"].startswith(module.MARKER)
    assert url.endswith(f"/issues/{number}" if number else "/issues")


def test_apply_without_a_repo_does_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Писать некуда — исход 2, а не молчаливый сухой заход."""
    root = tree(tmp_path, "a")
    written(root, line("a"))
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert module.main(["--root", str(root), "--repo", "", "--apply"]) == module.EXIT_BROKEN


def test_the_skills_of_the_tree_are_the_directories_with_a_skill_file(tmp_path: Path) -> None:
    """Навык — каталог с `SKILL.md`; каталог без него навыком не считается."""
    root = tree(tmp_path, "b", "a")
    (root / ".claude" / "skills" / "пустой").mkdir()
    assert module.skills(root) == ["a", "b"]


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("2026-10-17T10:00:00+00:00", True),
        ("2026-10-17T10:00:00", False),
        ("вчера", False),
        (5, False),
    ],
    ids=["с-поясом", "без-пояса", "не-время", "не-строка"],
)
def test_a_moment_without_a_zone_is_not_guessed(text: object, said: bool) -> None:
    """Время без пояса — не той формы, а не догадка о поясе."""
    assert (module.moment(text) is not None) is said


def test_runs_add_counts_calls_fails_and_the_last_day() -> None:
    """Счёт одного навыка: вызовы, отказы и самый поздний день, а не последний по порядку."""
    runs = module.Runs()
    late = module.moment("2026-10-18T00:00:00+00:00")
    early = module.moment("2026-10-17T00:00:00+00:00")
    runs.add(late, "ok")
    runs.add(early, "fail")
    assert (runs.calls, runs.fails, runs.last) == (2, 1, late)


def test_uncalled_and_render_body_agree(tmp_path: Path) -> None:
    """Тело называет в «не звали» ровно то, что отдаёт `uncalled`."""
    journal = module.parse([line("a")])
    body = module.render_body(journal, ["a", "b"], module.moment("2026-10-17T12:00:00+00:00"))
    assert module.uncalled(journal, ["a", "b"]) == ["b"]
    assert "- `b`" in body and "- `a`" not in body


def test_a_new_journal_shares_nothing_with_another() -> None:
    """Пустой `Journal` — ноль вызовов, и изменяемые поля у каждого свои.

    Общий словарь у двух разборов слил бы вызовы двух журналов в одну сводку
    молча: поля объявлены фабриками, и это держит набор, а не память.
    """
    first, second = module.Journal(), module.Journal()
    first.runs["a"] = module.Runs()
    first.malformed.append(1)
    first.sessions.add("с")
    assert (second.runs, second.malformed, second.sessions) == ({}, [], set())
    assert (second.nameless, second.first, second.last) == (0, None, None)
    assert module.uncalled(second, ["a", "b"]) == ["a", "b"]
