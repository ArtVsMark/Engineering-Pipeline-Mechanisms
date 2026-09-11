"""Сторож толчка: запрет ловится до вызова git, а не после.

Правило 012 держалось у нас документом с ответом «предмет вне досягаемости:
чья ветка, знает человек». Ответ описывал не тот предмет. Признак «чужая
ветка» машине и правда недоступен — а доступен другой, которым пользуются все
три соседа: имя ветки в команде не совпадает с текущей головой.

Инцидент свой: 10.09.2026 окно, стоя на `agent/items-sweep`, толкнуло в
`agent/marking-moves-out-of-the-queue`. Обе свои, обе законные — а следствие
такое же, как у чужой: конвейер открыл ВТОРОЕ изменение на ту же работу (#116),
закрывать его пришлось руками, и ветка осталась висеть.

Гейт проверяется тем, что он обязан ОТВЕРГНУТЬ (140), поэтому здесь отказов
больше, чем пропусков.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.conftest import ROOT

HOOK = ROOT / ".claude" / "hooks" / "push_guard.py"
SETTINGS = ROOT / ".claude" / "settings.json"


def ask(
    command: str, head: str = "agent/here", broken: str = ""
) -> subprocess.CompletedProcess[str]:
    """Спрашивает сторожа о команде, подделав текущую голову.

    `broken` заставляет подделку git отказать: так проверяется, что сторож,
    не сумевший узнать голову, отвергает толчок, а не пропускает его молча.
    """
    event = json.dumps({"tool_input": {"command": command}})
    fake = ROOT / "tests" / "fake_git"
    return subprocess.run(
        ["python3", str(HOOK)],
        input=event,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            "PATH": f"{fake}:/usr/bin:/bin",
            "FAKE_HEAD": head,
            "FAKE_HEAD_BROKEN": broken,
        },
    )


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin agent/other",
        "git push origin agent/other",
        "git push origin HEAD:agent/other",
        "git push origin agent/here:agent/other",
        "cd /tmp && git push origin agent/other",
    ],
    ids=["ключ", "просто", "из головы", "откуда-куда", "составная"],
)
def test_a_push_past_the_head_is_refused(command: str) -> None:
    """Толчок мимо головы отвергается во всех формах, включая составную.

    Форма `HEAD:<другая>` исключением не является: «своя голова под чужим
    именем» и есть та самая, которой вышел #116.
    """
    said = ask(command)
    assert said.returncode == 2, f"пропущено: {command}"
    assert "отвергнут" in said.stderr


@pytest.mark.parametrize(
    "command",
    ["git push origin main", "git push origin HEAD:main", "git -C /tmp push origin main"],
    ids=["прямо", "из головы", "с ключом git"],
)
def test_a_push_to_the_shared_branch_is_always_refused(command: str) -> None:
    """Общая ветка отвергается из любой головы: писать в неё напрямую нельзя."""
    said = ask(command, head="main")
    assert said.returncode == 2, f"пропущено: {command}"
    assert "общая ветка" in said.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push -u origin agent/here",
        "git status",
        "echo git push origin agent/other",
    ],
    ids=["без имени", "своя ветка", "не толчок", "не команда"],
)
def test_a_legitimate_command_passes(command: str) -> None:
    """Разрешённое проходит: сторож, мешающий работать, будет снят.

    Последний случай — про разбор: подстрока «git push» встречается в тексте
    документа и в сообщении коммита, а действие только у разобранной команды.
    """
    assert ask(command).returncode == 0, f"отвергнуто зря: {command}"


def test_a_heredoc_body_is_data_not_a_command() -> None:
    """`git push` внутри записываемого файла — текст, а не действие."""
    said = ask("cat > a.md <<'EOF'\ngit push origin agent/other\nEOF")
    assert said.returncode == 0, said.stderr


def test_an_unreadable_event_does_not_break_the_tool() -> None:
    """Событие не разобралось — сторож молчит, а не роняет чужой инструмент (084)."""
    said = subprocess.run(
        ["python3", str(HOOK)], input="не json", capture_output=True, text=True, encoding="utf-8"
    )
    assert said.returncode == 0


def test_the_hook_is_declared_to_the_window() -> None:
    """Хук объявлен в настройках: файл, который никто не зовёт, ничего не держит."""
    said = json.loads(SETTINGS.read_text(encoding="utf-8"))
    hooks = said["hooks"]["PreToolUse"]
    assert any(
        Path(HOOK).name in one.get("command", "")
        for entry in hooks
        for one in entry.get("hooks", [])
    ), "сторож есть, а окно о нём не знает"
    assert any(entry.get("matcher") == "Bash" for entry in hooks), "сторож не слушает Bash"


# --- что нашёл внешний взгляд: обёртки и слепой сторож ------------------------


@pytest.mark.parametrize(
    "command",
    [
        "/usr/bin/git push origin agent/other",
        "env git push origin agent/other",
        "VAR=1 git push origin agent/other",
        'bash -c "git push origin agent/other"',
        "nohup git push origin agent/other",
        'sh -c "cd /tmp && git push origin agent/other"',
    ],
    ids=["полный путь", "env", "присваивание", "bash -c", "nohup", "bash -c составная"],
)
def test_a_wrapped_push_is_still_a_push(command: str) -> None:
    """Обёртка не делает толчок другим действием (находка #143).

    Сторож ловил только буквальное первое слово `git`, и `/usr/bin/git push`,
    `env git push`, `bash -c "git push …"` проходили мимо целиком. Признак —
    ИМЯ программы, а не строка вызова: путь до неё дело окружения, а не
    намерения.
    """
    said = ask(command)
    assert said.returncode == 2, f"пропущено: {command}\n{said.stdout}{said.stderr}"
    assert "agent/other" in said.stderr


def test_a_wrapped_push_to_the_shared_branch_is_refused() -> None:
    """Общая ветка отвергается и под обёрткой: запрет не зависит от написания."""
    said = ask('bash -c "git push origin main"')
    assert said.returncode == 2
    assert "общая ветка" in said.stderr


def test_a_wrapper_does_not_swallow_a_harmless_command() -> None:
    """Обёртка вокруг НЕ толчка толчком не становится: сторож не ловит лишнего."""
    assert ask('bash -c "git status"').returncode == 0
    assert ask("env ls -la").returncode == 0


def test_nested_shells_end_in_a_refusal_not_in_a_loop() -> None:
    """У раскрытия вложенных оболочек есть предел, и он не пропуск.

    Без предела `bash -c "bash -c …"` уходил бы в бесконечность. С пределом
    разбор останавливается — но команда внутри разбираемой глубины всё равно
    видна.
    """
    said = ask("bash -c \"bash -c 'git push origin agent/other'\"")
    assert said.returncode == 2, said.stdout + said.stderr


def test_a_guard_that_cannot_see_the_head_refuses() -> None:
    """Сторож, не узнавший голову, отвергает толчок, а не машет рукой (находка #143).

    Прежде отказ `git rev-parse` отдавался пустой строкой — той же, что и
    отсоединённая голова, — и половина проверки исчезала МОЛЧА. Толчок
    необратим: отправленную ветку окно удалить не может, и цена этого уже
    оплачена (#116).
    """
    said = ask("git push origin agent/other", broken="not a git repository")
    assert said.returncode == 2, said.stdout + said.stderr
    assert "не смог узнать текущую ветку" in said.stderr
    assert "не выполнена, а не пройдена" in said.stderr


def test_the_shared_branch_is_refused_even_blind() -> None:
    """Запрет на общую ветку от головы не зависит и НАЗЫВАЕТ свою причину.

    Слепота сторожа не должна подменять точную причину общей: читателю нужна
    та, что говорит, чего нельзя, а не та, что говорит, чего сторож не смог.
    """
    said = ask("git push origin main", broken="not a git repository")
    assert said.returncode == 2
    assert "общая ветка" in said.stderr, said.stderr
