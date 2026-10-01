"""Хук старта облачного окна: вне облака молчит, планку берёт у `check_env` (#1017)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, load_script

HOOK: Final = ROOT / ".claude" / "hooks" / "session-start.sh"
SETTINGS: Final = ROOT / ".claude" / "settings.json"


def test_outside_the_cloud_the_hook_does_nothing(tmp_path: Path) -> None:
    """Без `CLAUDE_CODE_REMOTE=true` — выход 0 и ни строки в файл окружения окна."""
    env_file = tmp_path / "env"
    environment = {
        **os.environ,
        "CLAUDE_CODE_REMOTE": "",
        "CLAUDE_PROJECT_DIR": str(ROOT),
        "CLAUDE_ENV_FILE": str(env_file),
    }
    done = subprocess.run(
        [str(HOOK)], env=environment, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, done.stderr
    assert not env_file.exists(), "вне облака хук тронул окружение окна"


def test_the_hook_reads_the_floor_and_tools_from_check_env() -> None:
    """Планку и строки установки хук спрашивает у `check_env`, а не разбирает сам (214)."""
    check_env = load_script("check_env.py")
    text = HOOK.read_text(encoding="utf-8")
    for name in (
        check_env.python_floor.__name__,
        check_env.needs.__name__,
        check_env.local_packages.__name__,
    ):
        assert f"c.{name}(" in text, f"хук не спрашивает `check_env.{name}`"
    # Судятся исполняемые строки: в комментариях-пояснениях имя файла законно.
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    own = [line for line in code if "requires-python" in line or "tomllib" in line]
    assert own == [], f"хук разбирает планку сам: {own}"
    # Сборка пакета из исходников — след установки: без уборки проверка типов
    # видит модуль дважды (замер окна 01.10.2026, `packages/transport/build`).
    assert 'rm -rf "$local/build"' in text, "хук не убирает сборку локальных пакетов"


def test_the_hook_is_registered_beside_the_push_guard() -> None:
    """`SessionStart` добавлен рядом со сторожем толчка, а не вместо него."""
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    started = [one["command"] for entry in hooks["SessionStart"] for one in entry["hooks"]]
    assert any(HOOK.name in command for command in started)
    guarded = [one["command"] for entry in hooks["PreToolUse"] for one in entry["hooks"]]
    assert any("push_guard.py" in command for command in guarded), "сторож толчка пропал"
