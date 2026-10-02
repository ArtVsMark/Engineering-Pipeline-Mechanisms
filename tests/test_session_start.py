"""Хук старта облачного окна: вне облака молчит, планку берёт у `check_env` (#1017)."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

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


#: Встроенный в хук код на Python — между `<интерпретатор> -c "` и `" "$1"`.
SNIPPET: Final = re.compile(r'(\S+) -c "\n(.*?)\n" "\$1"', re.S)
#: Число планки в хуке: одна строка `want=<X.Y>` (взгляд на #1049).
WANT: Final = re.compile(r"^want=(\S+)$", re.M)


def hook_interpreter() -> str:
    """`python<планка>` — тот интерпретатор, которым хук исполняет свой разбор.

    Не `sys.executable`: набор вправе идти выше планки, и синтаксис новее неё
    он исполнил бы, а хук — нет (взгляд на #1049, 107). Нет интерпретатора
    планки, и набор идёт не на ней (предрелизный прогон) — пропуск с причиной:
    исполнимость разбора проверяет прогон на планке, а подставить свой
    интерпретатор значило бы проверить другое.
    """
    floor = load_script("check_env.py").python_floor(ROOT)
    found = shutil.which("python{}.{}".format(*floor))
    if found:
        return found
    if sys.version_info[:2] == floor:
        return sys.executable
    pytest.skip(
        "нет python{}.{}: разбор хука исполняет прогон на планке (ci.yml), а не этот".format(*floor)
    )


def snippet_says(mode: str) -> str:
    """Что печатает встроенный в хук разбор дерева, исполненный интерпретатором хука."""
    found = SNIPPET.search(HOOK.read_text(encoding="utf-8"))
    assert found, "встроенного разбора дерева в хуке нет — сверять нечего (075)"
    done = subprocess.run(
        [hook_interpreter(), "-c", found[2], mode],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.mark.parametrize("mode", ["floor", "needs", "local"])
def test_the_hooks_snippet_answers_what_check_env_answers(mode: str) -> None:
    """Встроенный разбор ИСПОЛНЯЕТСЯ и говорит то же, что `check_env` (взгляд на #1024, 107).

    Подстрока `c.<имя>(` не ловит смену формы `Need` или `local_packages`:
    хук ушёл бы в предупреждение, а набор остался бы зелёным.
    """
    check_env = load_script("check_env.py")
    expected = {
        "floor": "{}.{}".format(*check_env.python_floor(ROOT)),
        "needs": " ".join(f"{one.name}{one.bounds}" for one in check_env.needs().values()),
        "local": " ".join(str(where) for _, where in check_env.local_packages()),
    }[mode]
    assert expected, f"{mode}: check_env ответил пусто — сверять не с чем (075)"
    assert snippet_says(mode) == expected


def test_the_hook_reads_the_tree_with_the_floor_interpreter() -> None:
    """Разбор дерева в хуке идёт интерпретатором планки — тем, что исполняет набор.

    Взгляд на #1036: набор исполнял разбор `sys.executable` (планка), а хук —
    системным `python3` окна (3.11). Синтаксис выше 3.11 в `check_env` или
    `paths` набор пропустил бы, а хук ушёл бы в предупреждение (107).

    Взгляд на #1049: число планки было вписано в хук рукой не один раз. Где
    именно, докстрока не пересказывает — источник один:
    `git show 2a693c3^:.claude/hooks/session-start.sh | grep -n 3.14`. Три
    пересказа подряд разошлись с ним (взгляды на #1057 и #1060), и правило 210
    велит остановиться, а не чинить четвёртый. Проверяется здесь итог, а не
    история: число в коде хука одно — `want`, — оно равно планке, ставит и
    читает дерево именно `python$want`, и установка стоит РАНЬШЕ разбора.
    """
    said = HOOK.read_text(encoding="utf-8")
    code = "\n".join(line for line in said.splitlines() if not line.lstrip().startswith("#"))
    floor = "{}.{}".format(*load_script("check_env.py").python_floor(ROOT))
    wanted = WANT.findall(code)
    assert wanted == [floor], f"want в хуке {wanted}, а планка {floor}"
    assert code.count(floor) == 1, f"число планки {floor} вписано в код хука не один раз"
    found = SNIPPET.search(code)
    assert found, "встроенного разбора дерева в хуке нет — сверять нечего (075)"
    assert found[1] == '"python$want"', f"хук читает дерево {found[1]}, а не python$want"
    install = code.index('uv python install "$want"')
    read = code.index("$(read_tree floor)")
    assert install < read, "интерпретатор ставится после разбора дерева"
    # Обе ветки хука, которые называют настоящую причину (взгляд на #1057):
    # нет интерпретатора — до разбора, расхождение `want` с планкой — после.
    guard = code.index('command -v "python$want" >/dev/null 2>&1 || { warn "нет python$want')
    assert install < guard < read, "охрана «нет python$want» стоит не между установкой и разбором"
    mismatch = code.index('if [ "$floor" != "$want" ]; then')
    assert read < mismatch, "сверка want с планкой стоит не после чтения планки"
    assert "поправьте want в хуке" in code[mismatch:], "расхождение want с планкой не названо"
    # Отказ чтения планки тоже называет `want`: поднятую планку `python$want`
    # может не прочесть вовсе, и до сверки дело не дойдёт (взгляд на #1057).
    unread = code[guard:mismatch]
    assert "поправьте want в хуке" in unread, "отказ чтения планки не называет want"
    head = said.splitlines()[1]
    assert floor not in head, "шапка хука вписывает число планки рукой — разойдётся с want молча"
    assert 'ln -sf "$(/opt/uv/bin/uv python find "$want")" "/usr/local/bin/python$want"' in code


def test_the_hook_installs_local_packages_editable_and_skips_a_fit_env() -> None:
    """Пакеты дерева — `-e`, годное окружение не переставляется (взгляд на #1024)."""
    code = "\n".join(
        line
        for line in HOOK.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert 'editable+=(-e "$local")' in code, "пакеты дерева ставятся копией, а не -e"
    assert re.search(r"if ! \.venv/bin/python scripts/check_env\.py", code), (
        "годное окружение переставляется на каждом старте"
    )
