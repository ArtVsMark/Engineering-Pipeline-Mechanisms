"""Хук журнала навыков: вызов доходит до строки журнала путём окна (#1449).

Набор спрашивает хук через ВХОД, а не через функцию записи: команда берётся из
`.claude/settings.json`, обёртка выбирает интерпретатор планки, и строка
ложится в журнал (211). У соседа был писатель журнала без единого вызова к
нему, и сводка годами показывала ноль — поэтому функция без пути не в счёт.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

HOOKS = ROOT / ".claude" / "hooks"
SETTINGS = ROOT / ".claude" / "settings.json"
_spec = importlib.util.spec_from_file_location("skill_log", HOOKS / "skill_log.py")
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
sys.modules["skill_log"] = module
_spec.loader.exec_module(module)

NOW = datetime(2026, 10, 17, 21, 0, tzinfo=UTC)
#: Событие площадки после вызова навыка — только те поля, что читает хук.
EVENT: dict[str, Any] = {
    "session_id": "сессия-1",
    "tool_name": "Skill",
    "tool_input": {"skill": "build-a-gate", "args": "слова владельца"},
}


def commands(event: str) -> list[str]:
    """Команды хуков события с отбором `Skill` — так, как их зовёт окно."""
    said = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"].get(event, [])
    return [
        one["command"]
        for entry in said
        if entry.get("matcher") == "Skill"
        for one in entry.get("hooks", [])
    ]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Корень проекта с хуками окна: журнал ляжет сюда, а не в дерево набора."""
    where = tmp_path / "проект" / ".claude" / "hooks"
    where.mkdir(parents=True)
    for name in ("skill_log.sh", "skill_log.py", "floor.sh"):
        shutil.copy2(HOOKS / name, where / name)
    return tmp_path / "проект"


def floor_bin(tmp_path: Path) -> Path:
    """Каталог PATH с интерпретатором планки и `dirname` — и ничем больше.

    Системный `python3` в PATH не кладётся: годится он или нет, зависело бы от
    образа исполнителя, а не от обёртки.
    """
    floor = "{}.{}".format(*load_script("check_env.py").python_floor(ROOT))
    where = tmp_path / "bin"
    where.mkdir(exist_ok=True)
    (where / f"python{floor}").symlink_to(sys.executable)
    dirname = shutil.which("dirname")
    assert dirname, "без dirname обёртку не позвать"
    (where / "dirname").symlink_to(dirname)
    return where


def hook(command: str, project: Path, path: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    """Зовёт команду хука из настроек так, как её зовёт окно."""
    return subprocess.run(
        ["/bin/sh", "-c", command],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={"PATH": str(path), "CLAUDE_PROJECT_DIR": str(project)},
    )


def journal(project: Path) -> list[dict[str, Any]]:
    """Строки журнала проекта."""
    text = (project / module.JOURNAL).read_text(encoding="utf-8")
    return [json.loads(one) for one in text.splitlines()]


@pytest.mark.parametrize(
    ("event", "outcome"),
    [("PostToolUse", "ok"), ("PostToolUseFailure", "fail")],
    ids=["вызов", "отказ"],
)
def test_a_skill_call_reaches_the_journal_through_the_settings(
    event: str, outcome: str, project: Path, tmp_path: Path
) -> None:
    """Команда из настроек → обёртка → интерпретатор планки → строка журнала (211)."""
    [command] = commands(event)
    run = hook(command, project, floor_bin(tmp_path), json.dumps(EVENT))
    assert run.returncode == 0, run.stderr
    [line] = journal(project)
    assert line["skill"] == "build-a-gate" and line["outcome"] == outcome
    assert line["session"] == "сессия-1"
    assert "слова владельца" not in json.dumps(line, ensure_ascii=False)


def test_without_the_floor_interpreter_the_call_is_named_and_not_blocked(
    project: Path, tmp_path: Path
) -> None:
    """Нет интерпретатора планки — код 1 с причиной: не блокирует и не молчит (084, 045)."""
    where = tmp_path / "голый"
    where.mkdir()
    dirname = shutil.which("dirname")
    assert dirname
    (where / "dirname").symlink_to(dirname)
    [command] = commands("PostToolUse")
    run = hook(command, project, where, json.dumps(EVENT))
    assert run.returncode == module.NOT_RECORDED and "не записан" in run.stderr, run.stderr
    assert not (project / module.JOURNAL).exists()


def test_the_hook_limit_covers_its_work() -> None:
    """Хук не зовёт процессов и сети: предел из настроек — на запуск и одну запись (100)."""
    said = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    limits = [
        one["timeout"]
        for event in ("PostToolUse", "PostToolUseFailure")
        for entry in said[event]
        for one in entry["hooks"]
        if "skill_log.sh" in one["command"]
    ]
    assert limits and all(isinstance(one, int) and one > 0 for one in limits), limits
    text = (HOOKS / "skill_log.py").read_text(encoding="utf-8")
    assert "subprocess" not in text and "urllib" not in text


@pytest.mark.parametrize(
    ("event", "skill", "session"),
    [
        (EVENT, "build-a-gate", "сессия-1"),
        ({**EVENT, "tool_input": {"skill": "плагин:навык"}}, "плагин:навык", "сессия-1"),
        ({**EVENT, "tool_input": {"skill": "rm -rf /"}}, None, "сессия-1"),
        ({**EVENT, "tool_input": "навык"}, None, "сессия-1"),
        ({**EVENT, "session_id": "a b"}, "build-a-gate", None),
        (None, None, None),
    ],
    ids=[
        "имя",
        "имя-плагина",
        "не-идентификатор",
        "вход-не-словарь",
        "сессия-не-той-формы",
        "не-разобрано",
    ],
)
def test_a_call_is_written_and_only_identifiers_pass(
    event: object, skill: str | None, session: str | None
) -> None:
    """Вызов пишется всегда; имя и сессия — только идентификатором, иначе `null` (045)."""
    line = module.line_of(event, "ok", NOW)
    assert line == {
        "ts": "2026-10-17T21:00:00+00:00",
        "skill": skill,
        "outcome": "ok",
        "session": session,
    }


def test_another_tool_is_not_a_skill_call() -> None:
    """Событие другого инструмента — не вызов навыка: строки нет."""
    assert module.line_of({**EVENT, "tool_name": "Bash"}, "ok", NOW) is None


@pytest.mark.parametrize(
    ("stdin", "said"),
    [("не json", "не JSON"), ("x" * (1024 * 1024 + 1), "больше предела")],
    ids=["не-json", "больше-предела"],
)
def test_an_unread_event_is_still_a_call(
    stdin: str,
    said: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Неразобранный вход — строка без имени и причина в stderr, а не пропажа (016, 045)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", _Stdin(stdin))
    assert module.main(["fail"], now=NOW) == module.RECORDED
    assert said in capsys.readouterr().err
    [line] = journal(tmp_path)
    assert line == {
        "ts": "2026-10-17T21:00:00+00:00",
        "skill": None,
        "outcome": "fail",
        "session": None,
    }


def test_a_journal_that_cannot_be_written_is_said_and_not_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Журнал не записан — код 1 и причина: человек её видит, а работа идёт дальше (084, 045)."""
    (tmp_path / ".claude").write_text("файл на месте каталога", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", _Stdin(json.dumps(EVENT)))
    assert module.main(["ok"], now=NOW) == module.NOT_RECORDED
    assert "не записан" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["failed"]], ids=["без-довода", "опечатка"])
def test_an_unknown_outcome_is_not_written_as_a_call(
    argv: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Незнакомый довод — код 1 и причина, а не тихий «ok» поверх отказа (045)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", _Stdin(json.dumps(EVENT)))
    assert module.main(argv, now=NOW) == module.NOT_RECORDED
    err = capsys.readouterr().err
    assert "не записан" in err and ".claude/settings.json" in err, err
    assert not (tmp_path / module.JOURNAL).exists()


def test_the_hook_and_the_summary_read_one_journal() -> None:
    """Хук пишет туда, откуда сводка читает: путь у них один (#1449)."""
    assert module.JOURNAL == load_script("skill_runs.py").JOURNAL
    assert module.OUTCOMES == load_script("skill_runs.py").OUTCOMES


class _Stdin:
    """Поток ввода из строки: хук читает его с пределом."""

    def __init__(self, text: str) -> None:
        self.text = text

    def read(self, size: int = -1) -> str:
        """Отдаёт не больше `size` знаков, как настоящий поток."""
        return self.text if size < 0 else self.text[:size]
