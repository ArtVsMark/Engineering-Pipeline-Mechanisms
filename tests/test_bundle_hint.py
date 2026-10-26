"""Совет о пачке: режешь `agent/…` без `bundle-the-work` в журнале сессии — скажи (#1708).

Обе половины: нарезка без вызова навыка даёт совет, а вызов в журнале этой
сессии, чужая ветка и не нарезка — молчание; журнал, который не прочитать, —
причина, а не совет вслепую (045). Код выхода — всегда 0: нарезку хук не держит.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT

HOOKS = ROOT / ".claude" / "hooks"
# Хук зовёт разбор стража толчка импортом соседа — как при запуске из каталога хуков.
sys.path.insert(0, str(HOOKS))
_spec = importlib.util.spec_from_file_location("bundle_hint", HOOKS / "bundle_hint.py")
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

SESSION = "s-1"


def event(command: str, session: str | None = SESSION) -> dict[str, Any]:
    """Событие PreToolUse инструмента Bash."""
    said: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if session is not None:
        said["session_id"] = session
    return said


def journal(root: Path, *rows: dict[str, Any]) -> Path:
    """Журнал вызовов навыков в корне `root` — той формы, что пишет `skill_log.py`."""
    path: Path = root / module.JOURNAL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def call(skill: str, session: str = SESSION, outcome: str = "ok") -> dict[str, str]:
    """Строка журнала о вызове навыка."""
    return {
        "ts": "2026-10-26T18:00:00+00:00",
        "skill": skill,
        "outcome": outcome,
        "session": session,
    }


@pytest.mark.parametrize(
    ("command", "branches"),
    [
        ("git checkout -b agent/x origin/main", ["agent/x"]),
        ("git checkout -B agent/x", ["agent/x"]),
        ("git switch -c agent/x", ["agent/x"]),
        ("git switch --create=agent/x", ["agent/x"]),
        ("git fetch origin main && git checkout -b agent/x origin/main", ["agent/x"]),
        ("git -C /tmp/w checkout -b agent/x", ["agent/x"]),
        ("bash -c 'git switch -c agent/x'", ["agent/x"]),
        ("git checkout --orphan agent/x", ["agent/x"]),
        ("git checkout -bagent/x", ["agent/x"]),
        ("git switch -cagent/x origin/main", ["agent/x"]),
        ("git checkout -bfix/x", []),
        ("git worktree add -b agent/x /tmp/w origin/main", ["agent/x"]),
        ("git worktree add /tmp/w agent/x", []),
        ("git checkout agent/x", []),
        ("git checkout -b fix/x", []),
        ("git branch agent/x", []),
        ("cat > f <<'EOF'\ngit checkout -b agent/x\nEOF", []),
        ("echo 'git checkout -b agent/x", []),
    ],
)
def test_every_form_of_cutting_an_agent_branch_is_seen(command: str, branches: list[str]) -> None:
    """Формы нарезки — `checkout -b|-B`, `switch -c`, цепочка, обёртка; текст — не нарезка."""
    assert module.created(command) == branches


def test_a_cut_without_the_skill_in_this_session_is_advised(tmp_path: Path) -> None:
    """Навык позван в чужой сессии, отказал или позван другой — совет звучит."""
    journal(
        tmp_path,
        call("bundle-the-work", session="другая"),
        call("bundle-the-work", outcome="fail"),
        call("work-the-plan"),
    )
    said = module.advice(event("git checkout -b agent/x"), tmp_path)
    assert "`agent/x`" in said and "до первого коммита" in said


def test_the_skill_in_this_sessions_journal_silences_the_hook(tmp_path: Path) -> None:
    """Вызов в журнале этой сессии — молчание; не нарезка `agent/…` — молчание тоже."""
    journal(tmp_path, "не JSON", call("plugin:bundle-the-work"))  # type: ignore[arg-type]
    assert module.advice(event("git checkout -b agent/x"), tmp_path) == ""
    assert module.advice(event("git checkout -b fix/x"), tmp_path / "нет") == ""
    assert module.advice(event("ls agent/"), tmp_path / "нет") == ""


def test_an_unreadable_journal_is_named_and_not_advised_blindly(tmp_path: Path) -> None:
    """Нет журнала, нет номера сессии, журнал — каталог: причина, а не совет вслепую (045)."""
    cut = event("git switch -c agent/x")
    assert "журнала вызовов навыков" in module.advice(cut, tmp_path)
    assert "номера сессии" in module.advice(event("git switch -c agent/x", session=None), tmp_path)
    (tmp_path / module.JOURNAL).mkdir(parents=True)
    assert "не читается" in module.advice(cut, tmp_path)


def run(stdin: str, root: Path) -> subprocess.CompletedProcess[str]:
    """Хук процессом, как его зовёт окно, — из каталога хуков, с корнем проекта."""
    return subprocess.run(
        [sys.executable, str(HOOKS / "bundle_hint.py")],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"CLAUDE_PROJECT_DIR": str(root), "PATH": ""},
        timeout=30,
        check=False,
    )


def test_the_advice_reaches_the_model_and_the_cut_is_never_held(tmp_path: Path) -> None:
    """Совет — `additionalContext` без решения о разрешении; код — 0 всегда (084)."""
    done = run(json.dumps(event("git checkout -b agent/x")), tmp_path)
    assert done.returncode == 0, done.stderr
    said = json.loads(done.stdout)["hookSpecificOutput"]
    assert said["hookEventName"] == "PreToolUse" and "permissionDecision" not in said
    assert "agent/x" in said["additionalContext"]
    broken = run("не JSON", tmp_path)
    assert broken.returncode == 0 and broken.stdout == ""


def test_the_hook_is_wired_to_bash_and_given_to_the_consumer() -> None:
    """Хук подключён к событию `Bash` обёрткой планки и кладётся потребителю как есть."""
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entry in settings["hooks"]["PreToolUse"]
        if entry.get("matcher") == "Bash"
        for hook in entry["hooks"]
    ]
    assert any(command.endswith('/.claude/hooks/bundle_hint.sh"') for command in commands)
    onboard_text = (ROOT / "scripts" / "onboard.py").read_text(encoding="utf-8")
    assert 'paths.HOOKS / "bundle_hint.py"' in onboard_text
    assert 'paths.HOOKS / "bundle_hint.sh"' in onboard_text


def test_the_journal_is_read_from_its_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Вызов этой сессии в хвосте журнала длиннее предела — найден: журнал только растёт (#1711)."""
    monkeypatch.setattr(module, "LIMIT", 200)
    path = journal(tmp_path, *[call("work-the-plan", session="давняя")] * 20)
    with path.open("a", encoding="utf-8") as tail:
        tail.write(json.dumps(call("bundle-the-work")) + "\n")
    assert path.stat().st_size > module.LIMIT
    assert module.advice(event("git checkout -b agent/x"), tmp_path) == ""


def test_a_session_number_the_journal_cannot_hold_is_named(tmp_path: Path) -> None:
    """Номер не той формы журнал пишет пустым — причина «проверить нечем», а не ложный совет."""
    journal(tmp_path, call("bundle-the-work"))
    said = module.advice(event("git checkout -b agent/x", session="с пробелом"), tmp_path)
    assert "не той формы" in said
