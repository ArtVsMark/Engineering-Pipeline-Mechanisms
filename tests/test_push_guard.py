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

import ast
import importlib.util
import json
import os
import shutil
import string
import subprocess
import sys
from pathlib import Path

import pytest
import report

from tests.conftest import ROOT, load_script, python_shim, walk

HOOK = ROOT / ".claude" / "hooks" / "push_guard.py"
#: То, что зовёт окно: обёртка выбирает интерпретатор планки (#1058). Набор
#: спрашивает сторожа через неё же — иначе проверялся бы не тот вызов, что идёт
#: в окне, и `python3` ниже планки остался бы невидим.
WRAPPER = ROOT / ".claude" / "hooks" / "push_guard.sh"
#: Сам сторож как модуль: часть его разбора проверяется прямо, без процесса.
#: Он лежит не в `scripts/`, поэтому общий загрузчик набора сюда не годится.
_spec = importlib.util.spec_from_file_location("push_guard", HOOK)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
sys.modules["push_guard"] = module
_spec.loader.exec_module(module)
SETTINGS = ROOT / ".claude" / "settings.json"


#: Каталог с `python<планка>` для PATH обёртки — его кладёт фикстура ниже.
FLOOR_BIN: dict[str, str] = {}


@pytest.fixture(autouse=True, scope="module")
def floor_interpreter_on_path(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Кладёт `python<планка>` — интерпретатор набора — туда, где обёртка его ищет.

    Набор идёт на планке (`check_env` сверяет это до прогона), а в PATH проверки
    — только `/usr/bin:/bin`, где интерпретатора планки может не быть: тогда
    обёртка закрыла бы толчок, не спросив сторожа, и вердикты ниже проверяли бы
    её, а не его. Ссылка кладётся в свой каталог, чтобы не тащить в PATH
    остальное окружение, — и в площадку прогона, а не в общий `/tmp` (149).
    """
    floor = "{}.{}".format(*load_script("check_env.py").python_floor(ROOT))
    where = tmp_path_factory.mktemp("floor-python")
    python_shim(where, f"python{floor}")
    FLOOR_BIN["dir"] = str(where)


def floor_interpreter() -> str:
    """Каталог с интерпретатором планки, положенный фикстурой модуля."""
    return FLOOR_BIN["dir"]


def ask(
    command: str,
    head: str = "agent/here",
    broken: str = "",
    gone: str = "",
    merged: str = "",
    elsewhere: str = "",
    tracked: str = "",
) -> subprocess.CompletedProcess[str]:
    """Спрашивает сторожа о команде, подделав состояние репозитория.

    `broken` заставляет подделку git отказать: так проверяется, что сторож,
    не сумевший узнать голову, отвергает толчок, а не пропускает его молча.
    `gone` — площадка удалила ветку, `merged` — работа уже слита.
    """
    event = json.dumps({"tool_input": {"command": command}})
    fake = ROOT / "tests" / "fake_git"
    return subprocess.run(
        [str(WRAPPER)],
        input=event,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            "PATH": f"{fake}:{floor_interpreter()}:/usr/bin:/bin",
            "FAKE_HEAD": head,
            "FAKE_HEAD_BROKEN": broken,
            "FAKE_REMOTE_GONE": gone,
            "FAKE_MERGED": merged,
            "FAKE_UPSTREAM_ELSEWHERE": elsewhere,
            "FAKE_TRACKED": tracked,
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
    assert "не ветка изменения" in said.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push origin master",
        "git push origin develop",
        "git push origin HEAD:claude/окно",
        "git -C /tmp/другой push origin main",
    ],
    ids=["master", "develop", "ветка окна", "другой клон"],
)
def test_only_an_agent_branch_takes_a_push(command: str) -> None:
    """Толчок проходит только в `agent/…`, какая бы ветка ни была общей (#1220).

    Имя общей ветки перехвату не нужно: `master`, `develop`, ветка окна и
    толчок в другой клон отвергаются одним правилом, без чтения `origin/HEAD`.
    """
    said = ask(command, head=command.rsplit(" ", 1)[-1].split(":")[-1])
    assert said.returncode == 2, said.stderr
    assert "не ветка изменения" in said.stderr, said.stderr


def test_the_prefix_is_the_pipeline_one() -> None:
    """Приставка перехвата — та же, по которой конвейер открывает изменение (003, 046)."""
    assert (module.AGENT_PREFIX,) == load_script("agent_pr.py").PREFIXES


@pytest.mark.parametrize(
    "text",
    ["коротко", "я" * report.LIMIT, "я" * (report.LIMIT + 1), "  поля  ", "я" * 400],
    ids=["коротко", "на-границе", "за-границей", "поля", "длинно"],
)
def test_the_cut_is_the_transport_one(text: str) -> None:
    """Обрезка сторожа — копия `report.cut`, и разойтись с ним молча ей нельзя (016, 046)."""
    assert module.LIMIT == report.LIMIT
    assert module.cut(text) == report.cut(text)


@pytest.mark.parametrize(
    "text",
    ["коротко", "я" * report.LIMIT, "я" * (report.LIMIT + 1), "  поля  ", "я" * 400],
    ids=["коротко", "на-границе", "за-границей", "поля", "длинно"],
)
def test_the_tail_is_the_transport_one(text: str) -> None:
    """Хвост сторожа — копия `report.tail`, и разойтись с ним молча ему нельзя (016, 046)."""
    assert module.tail(text) == report.tail(text)


def test_a_long_git_refusal_keeps_its_cause() -> None:
    """Длинный отказ git обрезан с начала: причина у него последней строкой (взгляд на #1486)."""
    said = ask("git push origin agent/other", broken="ш" * 400 + "\nfatal: not a git repository")
    assert said.returncode == 2, said.stdout + said.stderr
    assert "fatal: not a git repository" in said.stderr and "обрезано" in said.stderr


#: Длинный чужой текст для причины отказа.
LONG: str = "я" * 400


@pytest.mark.parametrize(
    "command",
    [
        f"env --x={LONG} git push origin agent/x",
        f"bash -{LONG}c 'git push origin agent/x'",
        f"git push origin {LONG}",
        f"git push origin agent/{LONG}",
        f"cat <<{LONG}\ngit push origin agent/x",
    ],
    ids=["ключ-обёртки", "связка-ключей-оболочки", "чужая-цель", "ветка-не-головы", "разделитель"],
)
def test_foreign_text_in_a_refusal_is_cut_aloud(command: str) -> None:
    """Чужой текст в причине отказа обрезан вслух во всех случаях, а не в двух (взгляд на #1486)."""
    said = ask(command)
    assert said.returncode == 2, said.stdout + said.stderr
    assert "обрезано" in said.stderr and LONG not in said.stderr, said.stderr


@pytest.mark.parametrize(
    "segment",
    [["bash", "-c", "echo '" + "я" * 400], ["env", "-S", "echo '" + "я" * 400]],
    ids=["оболочка", "env-S"],
)
def test_an_unparsed_script_is_cut_aloud(segment: list[str]) -> None:
    """Неразобранный скрипт в причине отказа обрезан вслух, а не целиком (`64f3440`)."""
    found, blind = module.unwrap(segment, module.DEPTH)
    assert not found and "(обрезано, всего 406 знаков)" in blind, blind
    assert len(blind) < report.LIMIT + 100, len(blind)


def test_the_revival_advice_names_no_guessed_branch() -> None:
    """Совет после слияния не подставляет имя общей ветки — перехват его не знает (#1218)."""
    said = ask("git push -u origin agent/here", gone="1")
    assert said.returncode == 2, said.stderr
    assert "origin/<общая>" in said.stderr and "agent/<новая>" in said.stderr, said.stderr


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


@pytest.mark.parametrize("head", ["main", "claude/окно", "HEAD"])
def test_a_push_without_a_target_is_judged_by_the_head(head: str) -> None:
    """`git push` без цели толкает голову — и вне `agent/…` отвергается (взгляд на #1226)."""
    said = ask("git push", head=head)
    assert said.returncode == 2, f"толчок без цели с головы «{head}» пропущен"
    assert "не ветка изменения" in said.stderr, said.stderr


@pytest.mark.parametrize("command", ["ls", "git status", "pytest -q"])
def test_a_command_that_is_not_a_push_passes_on_any_head(command: str) -> None:
    """Не толчок проходит и с головы вне `agent/…`: голова судит только толчок без цели."""
    assert ask(command, head="HEAD").returncode == 0, f"отвергнуто зря: {command}"
    assert ask(command, broken="1").returncode == 0, f"отвергнуто зря при слепой голове: {command}"


def test_a_push_without_a_target_and_an_unknown_head_is_refused() -> None:
    """Голову не узнать — толчок без цели не проверить, и он отвергается."""
    said = ask("git push", broken="1")
    assert said.returncode == 2, said.stderr
    assert "толкает голову" in said.stderr, said.stderr


def test_a_push_without_a_target_does_not_revive_a_merged_branch() -> None:
    """`git push` со слитой головы воскресил бы её так же, как толчок по имени."""
    said = ask("git push", gone="1")
    assert said.returncode == 2, said.stderr


def test_a_heredoc_body_is_data_not_a_command() -> None:
    """`git push` внутри записываемого файла — текст, а не действие."""
    said = ask("cat > a.md <<'EOF'\ngit push origin agent/other\nEOF")
    assert said.returncode == 0, said.stderr


def test_an_unreadable_event_does_not_break_the_tool() -> None:
    """Событие не разобралось — сторож молчит, а не роняет чужой инструмент (084)."""
    said = subprocess.run(
        [str(WRAPPER)],
        input="не json",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PATH": f"{floor_interpreter()}:/usr/bin:/bin"},
    )
    assert said.returncode == 0, said.stderr


def test_the_hook_is_declared_to_the_window() -> None:
    """Хук объявлен в настройках: файл, который никто не зовёт, ничего не держит."""
    said = json.loads(SETTINGS.read_text(encoding="utf-8"))
    hooks = said["hooks"]["PreToolUse"]
    assert any(
        WRAPPER.name in one.get("command", "") for entry in hooks for one in entry.get("hooks", [])
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
    assert "не ветка изменения" in said.stderr


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


def test_the_head_beside_a_same_named_tag_is_its_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Голова на ветке с одноимённым тегом — эта ветка, а не `heads/<имя>` (взгляд на #1513).

    Короткое имя отвергло бы толчок в свою же ветку как толчок мимо неё.
    """
    tree = tmp_path / "дерево"
    tree.mkdir()
    run = ["git", "-c", "user.name=т", "-c", "user.email=т@т"]
    for args in (
        ["init", "-q"],
        ["commit", "-q", "--allow-empty", "-m", "а"],
        ["checkout", "-q", "-b", "agent/x"],
        ["tag", "agent/x"],
    ):
        subprocess.run([*run, *args], cwd=tree, check=True, capture_output=True, timeout=30)
    monkeypatch.chdir(tree)
    assert module.head() == ("agent/x", "")
    assert module.refused(["agent/x"], module.head()[0]) == ""


def test_a_guard_without_its_floor_names_the_floor(tmp_path: Path) -> None:
    """Нет `floor.sh` — толчок закрыт, причина — планка, а не интерпретатор (взгляд на #1491).

    Остальные команды окна открыты: обёртка закрывает только то, что страж и
    сторожит.
    """
    where = tmp_path / "hooks"
    where.mkdir()
    for name in ("push_guard.sh", "push_guard.py"):
        shutil.copy2(HOOK.parent / name, where / name)

    def wrapped(command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(where / "push_guard.sh")],
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={"PATH": f"{floor_interpreter()}:/usr/bin:/bin"},
            timeout=30,
        )

    said = wrapped("git push origin agent/x")
    assert said.returncode == 2, said.stdout + said.stderr
    assert "планка интерпретатора не прочитана" in said.stderr, said.stderr
    assert "перезапустите" not in said.stderr and "python?" not in said.stderr, said.stderr
    assert wrapped("ls").returncode == 0


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
    assert "не ветка изменения" in said.stderr, said.stderr


# --- разбор, не дошедший до конца, отвергает ---------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "env -i git push origin agent/other",
        "nice -n 5 git push origin agent/other",
        "stdbuf -oL git push origin agent/other",
        "env -u HOME git push origin agent/other",
        'bash -lc "git push origin agent/other"',
        'sh -xc "git push origin agent/other"',
    ],
    ids=["env -i", "nice -n", "stdbuf -oL", "env -u", "bash -lc", "sh -xc"],
)
def test_a_wrapper_with_its_own_flags_is_still_a_push(command: str) -> None:
    """Свои ключи обёртки не делают толчок невидимым (находки #181).

    Разбор требовал, чтобы команда шла сразу за именем обёртки, и `env -i`,
    `nice -n 5`, `stdbuf -oL` проходили мимо целиком. Совмещённый короткий ключ
    оболочки (`-lc`, `-xc`) — обычное написание, а искалось ровно слово `-c`.
    """
    said = ask(command)
    assert said.returncode == 2, f"пропущено: {command}\n{said.stdout}{said.stderr}"
    assert "agent/other" in said.stderr


def test_an_exhausted_depth_refuses_instead_of_passing() -> None:
    """Предел вложенности исчерпан — отказ, а не пропуск (находки #181).

    Сторож, не дочитавший команду, не знает, толчок это или нет, и «не знаю»
    здесь обязано значить «не пущу» — как и у неузнанной головы. Прежде предел
    молча отдавал команду дальше, расходясь с фейл-клоузом того же изменения.
    """
    said = ask('bash -c "bash -c \'bash -c \\"bash -c \\\\\\"git push origin x\\\\\\"\\"\'"')
    assert said.returncode == 2, said.stdout + said.stderr


def test_the_depth_limit_is_reached_by_the_declared_budget() -> None:
    """Граница DEPTH названа числом и проверяется им же (замечание #181).

    Бюджет общий на присваивания и оболочки, и именно он обнажает находку выше:
    без проверки предел был бы числом, о котором никто не спрашивал.
    """
    inner = ["git", "push", "origin", "agent/other"]
    found, blind = module.unwrap(inner, module.DEPTH)
    assert not blind and found == [inner]
    found, blind = module.unwrap(inner, 0)
    assert not found and "предел вложенности" in blind


def test_an_unparsable_command_refuses() -> None:
    """Незакрытая кавычка — тоже «не разобрал», и тоже отказ."""
    said = ask('git push origin "agent/other')
    assert said.returncode == 2, said.stdout + said.stderr
    assert "двойная кавычка не закрыта" in said.stderr


def test_a_harmless_wrapped_command_still_passes() -> None:
    """Фейл-клоуз не значит «отвергать всё»: разобранное и безобидное проходит."""
    assert ask("env -i ls -la").returncode == 0
    assert ask('bash -lc "git status"').returncode == 0
    assert ask("nice -n 5 python -c pass").returncode == 0


# --- обёртка знает свои ключи, а не угадывает их ------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'env bash -c "git push origin agent/other"',
        'nohup bash -c "git push origin agent/other"',
        'command bash -lc "git push origin agent/other"',
        'nice -n 5 sh -c "git push origin agent/other"',
    ],
    ids=["env+bash", "nohup+bash", "command+bash -lc", "nice+sh"],
)
def test_a_wrapper_around_a_shell_is_still_a_push(command: str) -> None:
    """Обёртка вокруг оболочки — тоже обёртка (находка #186).

    Разбор снимал `env` и на этом останавливался: дальше шёл не `git`, а
    `bash`. Снятие идёт по кругу, пока снимается.
    """
    said = ask(command)
    assert said.returncode == 2, f"пропущено: {command}\n{said.stdout}{said.stderr}"
    assert "agent/other" in said.stderr


def test_a_wrappers_own_positional_is_not_the_command() -> None:
    """Длительность `timeout` — её слово, а не имя программы.

    `timeout 30 git push …` проходил необнаруженным: разбор принимал `30` за
    команду и уходил ни с чем.
    """
    assert ask("timeout 30 git push origin main").returncode == 2
    assert ask("timeout -k 5 30 git push origin main").returncode == 2
    assert ask("timeout 30 echo hi").returncode == 0


def test_data_of_another_program_is_not_a_push() -> None:
    """`git` в АРГУМЕНТАХ чужой программы толчком не является (находка #186).

    Прежде внутри обёртки шло сканирование — «найти `git` дальше по словам», —
    и оно дотягивалось до данных: `env echo git push origin main` отвергалось
    как толчок в общую ветку. Гейт, краснеющий на верной работе, учит читать
    красное как фон (051).
    """
    assert ask("env echo git push origin main").returncode == 0
    assert ask("echo git push origin main").returncode == 0
    assert ask('bash -c "echo git push origin main"').returncode == 0


def test_an_ambiguous_shell_flag_cluster_blinds_the_guard() -> None:
    """Связка с `c` не на конце — не `-c`, и сторож это говорит (находка #186).

    `-norc` содержит `c`, но `c` в нём не последний, а `o` несёт значение.
    Принять такую связку за `-c` значит прочитать не тот аргумент как скрипт —
    и толчок под ней пройдёт необнаруженным.
    """
    said = ask('bash -norc "git push origin main"')
    assert said.returncode == 2, said.stdout + said.stderr
    assert "неоднозначна" in said.stderr


def test_an_unknown_wrapper_flag_blinds_the_guard() -> None:
    """Ключ вне набора обёртки — слепота, а не догадка.

    Угадать, несёт он значение или нет, нечем, а ошибка в любую сторону молча
    меняет, что считается командой.
    """
    said = ask("env --unknown-flag git push origin main")
    assert said.returncode == 2
    assert "неизвестен" in said.stderr


def test_a_known_shell_cluster_still_works() -> None:
    """Законная связка перед `-c` по-прежнему читается: `-lc`, `-xc`, `-ic`."""
    for flag in ("-lc", "-xc", "-ic", "-c"):
        said = ask(f'bash {flag} "git push origin agent/other"')
        assert said.returncode == 2, f"{flag}: {said.stdout}{said.stderr}"


@pytest.mark.parametrize(
    "command",
    [
        "env -C /tmp git push origin agent/other",
        "env -S 'git push origin agent/other'",
        "time -a -o /tmp/t git push origin agent/other",
    ],
    ids=["env -C", "env -S", "time -a -o"],
)
def test_the_flag_lists_know_the_real_utilities(command: str) -> None:
    """Списки ключей знают настоящие ключи этих утилит (находка #189).

    Первая редакция не знала `env -C`, `env -S`, `time -a` — и на них сторож
    слеп, то есть отвергал законную команду. Отказ безопасен, но он мешает
    работать, и список пополняется по мере встречи.
    """
    said = ask(command)
    assert said.returncode == 2, f"{command}: {said.stdout}{said.stderr}"
    assert "agent/other" in said.stderr, said.stderr


def test_an_unknown_flag_still_errs_towards_refusing() -> None:
    """Неполнота списка идёт в безопасную сторону, и это названо.

    Ключ, которого в наборе нет, делает сторожа слепым — и слепой ОТВЕРГАЕТ.
    Обратная ошибка, угадать и пропустить толчок, здесь невозможна по
    построению: в этом и смысл выбора (051).
    """
    said = ask("env --some-future-flag git push origin main")
    assert said.returncode == 2
    assert "неизвестен" in said.stderr


def test_a_push_into_a_branch_the_platform_deleted_is_refused() -> None:
    """Ветку удалила площадка — толчок воскресит её, и сторож отвергает.

    ЗАМЕР 17.09.2026, РАДИ КОТОРОГО ЗАПРЕТ И ЗАВЕДЁН: за одну смену слияние
    прошло под ногами ЧЕТЫРЕ раза, и прежний сторож не отверг ни одного — во
    всех четырёх голова стояла на той же ветке, в которую шёл толчок, то есть
    оба прежних запрета проходили. Один случай из четырёх нашёл ВЛАДЕЛЕЦ, а не
    механизм
    ([202](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/202-a-merged-branch-is-recreated-by-any-push.md)).
    """
    done = ask("git push -u origin agent/here", gone="1")
    assert done.returncode == 2, done.stdout
    assert "площадка удалила" in done.stderr, done.stderr
    assert "checkout -b" in done.stderr, "отказ обязан назвать, что делать вместо толчка (104)"


def test_a_squash_merge_leaves_the_branch_unreachable(tmp_path: Path) -> None:
    """Довод снятия второго признака ЗАМЕРЕН, а не объявлен.

    Второй признак спрашивал «голова достижима из origin/main» и говорил «работа
    слита». При слиянии УПЛОТНЕНИЕМ — способ этого проекта, решение 006 — она из
    общей НЕ достижима: уплотнение рождает новый коммит, а коммиты ветки в общую
    не едут. Признак не срабатывал почти никогда, и снят он по замеру; здесь
    замер повторяется живым git, иначе довод держался бы словом
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """

    def run(*args: str) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return done.stdout.strip()

    subprocess.run(["git", "init", "--quiet", "-b", "main", str(tmp_path)], check=True)
    run("config", "user.email", "кто@то")
    run("config", "user.name", "кто-то")
    (tmp_path / "файл").write_text("раз", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "первый")
    run("checkout", "--quiet", "-b", "agent/work")
    (tmp_path / "файл").write_text("два", encoding="utf-8")
    run("commit", "--quiet", "-am", "работа")
    голова = run("rev-parse", "agent/work")
    # Площадка сливает УПЛОТНЕНИЕМ: содержимое едет, коммит рождается новый.
    run("checkout", "--quiet", "main")
    run("merge", "--squash", "agent/work")
    run("commit", "--quiet", "-m", "уплотнение")
    run("update-ref", "refs/remotes/origin/main", "refs/heads/main")

    достижима = subprocess.run(
        ["git", "merge-base", "--is-ancestor", голова, "refs/remotes/origin/main"],
        cwd=tmp_path,
        capture_output=True,
    )
    assert достижима.returncode != 0, (
        "после уплотнения голова ветки оказалась достижима из общей — довод снятия"
        " второго признака перестал быть верным, и признак надо вернуть"
    )


def test_a_branch_pushed_without_upstream_is_a_named_gap() -> None:
    """Названный предел: ветку, толкнутую без `-u`, сторож не увидит.

    Слежения за собой у неё нет — значит следа толчка, по которому запрет и
    узнаёт предмет, тоже нет. Предел назван числом (одна ветка из 147 в этом
    окне) и проверяется здесь, чтобы не выдавать его за полноту (046).
    """
    done = ask("git push origin agent/here", merged="1")
    assert done.returncode == 0, (
        "сторож отверг толчок в ветку без следа толчка — предел, названный в коде,"
        f" разошёлся с поведением: {done.stderr}"
    )


def test_a_live_branch_still_passes() -> None:
    """Здоровый вход обязан пройти: ветка на месте и не слита (140)."""
    done = ask("git push -u origin agent/here")
    assert done.returncode == 0, done.stderr


def test_the_merge_check_asks_about_the_target_not_the_head() -> None:
    """Предмет — ветка ЦЕЛИ толчка, а не голова: у формы `HEAD:имя` они разные.

    ГОЛОВА И ЦЕЛЬ ЗДЕСЬ НАЗВАНЫ РАЗНО НАМЕРЕННО. Первая редакция проверки брала
    обе одинаковыми — и подмена предмета на голову её не роняла: проверка
    говорила о различении, не различая. Поймано откатом
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    done = ask("git push origin HEAD:agent/here", head="agent/other", gone="1")
    assert done.returncode == 2, done.stdout
    assert "agent/here" in done.stderr, done.stderr
    assert "agent/other" not in done.stderr, "спрошена голова вместо цели толчка"


def test_a_detached_head_is_not_asked_about_revival(tmp_path: Path) -> None:
    """У отсоединённой головы имени ветки нет — спрашивать не о чем.

    Пустое имя и `HEAD` дошли бы до `git config branch..merge`, то есть до
    запроса о ветке, которой не существует. Молчание здесь верно: предмета нет,
    а не «ветка жива».
    """
    assert module.merged_away("") == ""
    assert module.merged_away("HEAD") == ""


def test_the_revival_check_runs_against_a_real_repository(tmp_path: Path) -> None:
    """Признак проверен на НАСТОЯЩЕМ git, а не только на подделке.

    Подделка отвечает то, что мы ей велели, и потому подтверждает согласие кода
    с нашим представлением о git, а не с git
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    Здесь заводится живой клон, ветку толкают, площадка её удаляет — и признак
    «слежение за собой, а ссылки нет» обязан сработать на нём.
    """
    import os

    bare = tmp_path / "площадка"
    clone = tmp_path / "клон"

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=clone, check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True, capture_output=True)
    run("config", "user.email", "кто@то")
    run("config", "user.name", "кто-то")
    (clone / "файл").write_text("раз", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "первый")
    run("push", "--quiet", "-u", "origin", "main")
    run("checkout", "--quiet", "-b", "agent/work")
    (clone / "файл").write_text("два", encoding="utf-8")
    run("commit", "--quiet", "-am", "работа")
    run("push", "--quiet", "-u", "origin", "agent/work")
    # Площадка удаляет ветку при слиянии — так она и поступает.
    subprocess.run(["git", "branch", "-D", "agent/work"], cwd=bare, capture_output=True)
    run("fetch", "--prune", "--quiet", "origin")

    here = Path.cwd()
    try:
        os.chdir(clone)
        said = module.merged_away("agent/work")
    finally:
        os.chdir(here)
    assert "площадка удалила" in said, said or "живой репозиторий не дал признака удаления"


def test_the_revival_check_survives_the_real_auto_tracking(tmp_path: Path) -> None:
    """Автотрекинг воспроизведён НАСТОЯЩИМ git, а не объявлен подделкой.

    Подделка отвечает то, что мы ей велели, — и первая редакция запрета была
    зелёной на ней ровно потому, что связь «есть конфиг ⇒ ветку удалили» задали
    ей мы сами
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    Здесь клон настоящий, с объявленным `origin`: без него git слежения не
    ставит вовсе, и замер прошёл бы мимо предмета.
    """
    import os

    bare = tmp_path / "площадка"
    clone = tmp_path / "клон"

    def run(where: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=where, check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True, capture_output=True)
    run(clone, "config", "user.email", "кто@то")
    run(clone, "config", "user.name", "кто-то")
    (clone / "файл").write_text("раз", encoding="utf-8")
    run(clone, "add", "-A")
    run(clone, "commit", "--quiet", "-m", "первый")
    run(clone, "push", "--quiet", "-u", "origin", "main")
    run(clone, "checkout", "--quiet", "-b", "agent/новая", "origin/main")

    upstream = subprocess.run(
        ["git", "config", "--get", "branch.agent/новая.merge"],
        cwd=clone,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert upstream.stdout.strip() == "refs/heads/main", (
        "git не поставил слежение за общей веткой — предмет проверки не"
        f" воспроизвёлся: {upstream.stdout!r}"
    )

    here = Path.cwd()
    try:
        os.chdir(clone)
        said = module.merged_away("agent/новая")
    finally:
        os.chdir(here)
    assert said == "", f"первый толчок новой ветки отвергнут ложно: {said}"


@pytest.mark.parametrize(
    ("target", "expect"),
    [
        ("agent/here", "agent/here"),
        ("HEAD:agent/here", "agent/here"),
        ("refs/heads/agent/here", "agent/here"),
        ("HEAD:refs/heads/agent/here", "agent/here"),
    ],
)
def test_the_target_branch_is_read_the_same_way_everywhere(target: str, expect: str) -> None:
    """Имя ветки из записи цели читается ОДНИМ разбором на всех спрашивающих.

    Разбор был вписан дважды — в проверке запретов и в проверке воскрешения, — и
    второе понимание той же формы разошлось бы с первым молча. Нашёл внешний
    взгляд (090).
    """
    assert module.branch_of(target) == expect


def test_the_reachability_sign_is_not_back(tmp_path: Path) -> None:
    """Признак «голова достижима из общей» снят — и снят ПОВЕДЕНИЕМ, а не прозой.

    СНЯТИЕ БЫЛО ПОДТВЕРЖДЕНО ЗАМЕРОМ ВКЛАДА, НО НЕ ПРОГОНОМ. Замер 18.09.2026
    по 147 живым веткам показал, что при слиянии уплотнением голова из общей не
    достижима почти никогда, и вклад второго признака сверх первого — ноль
    находок. Довод был верен, но держался он комментарием: верни признак — и
    ничего не покраснеет. Нашёл это внешний взгляд (`acc6d71`).

    ПРЕДМЕТ ЗАВЕДЁН ЖИВЫМ GIT: ветка сброшена на общую, то есть её голова из
    `origin/main` достижима, слежение за собой стоит, и ссылка `origin/<имя>`
    НА МЕСТЕ — площадка ничего не удаляла. Прежний второй признак сказал бы
    «работа слита» и отверг бы законный толчок
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    import os

    bare = tmp_path / "площадка"
    clone = tmp_path / "клон"

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=clone, check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True, capture_output=True)
    run("config", "user.email", "кто@то")
    run("config", "user.name", "кто-то")
    (clone / "файл").write_text("раз", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "первый")
    run("push", "--quiet", "-u", "origin", "main")
    # ВЕТКА БЕЗ СВОИХ КОММИТОВ: голова та же, что у общей, — то есть достижима.
    run("checkout", "--quiet", "-b", "agent/сброшена")
    run("push", "--quiet", "-u", "origin", "agent/сброшена")
    run("fetch", "--prune", "--quiet", "origin")

    reachable = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
        cwd=clone,
        capture_output=True,
    )
    assert reachable.returncode == 0, (
        "предмет не воспроизвёлся: голова ветки из origin/main не достижима,"
        " а прежний признак срабатывал именно на достижимости"
    )

    here = Path.cwd()
    try:
        os.chdir(clone)
        said = module.merged_away("agent/сброшена")
    finally:
        os.chdir(here)
    assert not said, (
        "достижимость из общей снова читается как «работа слита» — признак,"
        f" снятый по замеру, вернулся и отвергает законный толчок: {said}"
    )


# --- обёртка без интерпретатора планки (#1058) ---------------------------------


def system_python3_reaches_the_floor() -> bool:
    """Не ниже ли планки `python3` системного PATH — тогда окна «без планки» не собрать."""
    floor = load_script("check_env.py").python_floor(ROOT)
    done = subprocess.run(
        ["python3", "-c", f"import sys; sys.exit(sys.version_info[:2] < {tuple(floor)!r})"],
        env={"PATH": os.defpath},
        capture_output=True,
        check=False,
    )
    return done.returncode == 0


def ask_with_python3(command: str, python3: Path) -> subprocess.CompletedProcess[str]:
    """Спрашивает обёртку, у которой из интерпретаторов есть только `python3` из `python3`."""
    return subprocess.run(
        [str(WRAPPER)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PATH": f"{python3.parent}:/usr/bin:/bin"},
        cwd=ROOT,
    )


def test_a_local_window_runs_the_guard_by_a_python3_on_the_floor(tmp_path: Path) -> None:
    """Локальное окно без `python<планка>`, но с `python3` не ниже — страж исполняется.

    Находка `08446b4` на #1072: хук старта ставит интерпретатор планки только
    в облачном окне, и в локальном обёртка отвергала бы КАЖДЫЙ толчок, советуя
    перезапуск, который там ничего не даёт. Страж, а не обёртка, должен
    ответить — его отказ на общую ветку и есть признак.
    """
    floor = "python{}.{}".format(*load_script("check_env.py").python_floor(ROOT))
    if any(Path(where, floor).exists() for where in ("/usr/bin", "/bin")):
        pytest.skip(f"{floor} стоит в /usr/bin — окна без него здесь не собрать")
    python3 = python_shim(tmp_path, "python3")
    harmless = ask_with_python3("ls", python3)
    assert harmless.returncode == 0, harmless.stderr
    shared = ask_with_python3("git push origin main", python3)
    assert shared.returncode == 2
    assert "страж толчка не запущен" not in shared.stderr, "ответила обёртка, а не страж"


def test_a_python3_below_the_floor_does_not_run_the_guard(tmp_path: Path) -> None:
    """Вторая половина: `python3` ниже планки стража не исполняет — толчок закрыт обёрткой."""
    floor = "python{}.{}".format(*load_script("check_env.py").python_floor(ROOT))
    if any(Path(where, floor).exists() for where in ("/usr/bin", "/bin")):
        pytest.skip(f"{floor} стоит в /usr/bin — окна без него здесь не собрать")
    python3 = tmp_path / "python3"
    python3.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    python3.chmod(0o755)
    said = ask_with_python3("git push origin agent/here", python3)
    assert said.returncode == 2
    assert "страж толчка не запущен" in said.stderr
    assert "в локальном поставьте" in said.stderr, "совет называет только перезапуск"


def ask_without_floor(command: str) -> subprocess.CompletedProcess[str]:
    """Спрашивает обёртку в окне, где интерпретатора планки нет вовсе."""
    return subprocess.run(
        [str(WRAPPER)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PATH": "/nonexistent-floor:" + os.defpath},
    )


@pytest.mark.parametrize(
    "command",
    [
        "git push origin agent/other",
        "git push",
        "git -C /tmp push origin agent/here",
        "/usr/bin/git push origin main",
        'bash -c "git push origin main"',
    ],
    ids=["просто", "без имени", "с ключом git", "полным путём", "в оболочке"],
)
def test_without_the_floor_interpreter_a_push_is_refused(command: str) -> None:
    """Нет интерпретатора планки — толчок закрыт кодом 2, а не пропущен молча.

    Ненулевой код, кроме 2, площадка считает неблокирующим: без этой ветки
    сторож отключился бы ровно тогда, когда его некому запустить. Закрыт и
    `git push` без имени: что он толкнёт, без сторожа не проверить. Форма
    `git -C путь push` — та, которую подстрока каталога `git push` пропускала.
    """
    floor = "python{}.{}".format(*load_script("check_env.py").python_floor(ROOT))
    if any(Path(where, floor).exists() for where in os.defpath.split(":") if where):
        pytest.skip(f"{floor} стоит в системном PATH — окна без него здесь не собрать")
    if system_python3_reaches_the_floor():
        pytest.skip("системный python3 не ниже планки — обёртка законно берёт его")
    said = ask_without_floor(command)
    assert said.returncode == 2, f"пропущено без сторожа: {command}"
    assert "страж толчка не запущен" in said.stderr
    assert "Толчок отвергнут" in said.stderr


@pytest.mark.parametrize("command", ["ls", "git status", "pytest -q"])
def test_without_the_floor_interpreter_other_commands_pass(command: str) -> None:
    """Остальное открыто: закрыть всё значило бы обездвижить окно сбоем старта."""
    said = ask_without_floor(command)
    assert said.returncode == 0, said.stderr
    assert said.stderr == ""


@pytest.mark.parametrize(
    "tail",
    [
        "2>&1",
        ">out.log",
        "> out.log",
        ">> out.log",
        "2>/dev/null",
        "&>out.log",
        "&>> out.log",
        "< in.txt",
        ">& out.log",
        "2>& out.log",
        "<& 3",
        ">| out.log",
        "<> rw.txt",
        "<<< слово",
    ],
)
def test_a_shell_redirect_is_not_a_push_target(tail: str) -> None:
    """Перенаправление оболочки — не ветка-цель, а цель толчка видна по-прежнему.

    ЗАМЕР 03.10.2026 (#1075): `git push -u origin agent/x 2>&1 | tail -2` был
    отвергнут — сторож прочёл «2>&1» второй целью, хотя голова стояла на
    `agent/x`. Слитная и раздельная формы проверяются обе: у раздельной
    снимается и следующее слово.
    """
    assert module.push_targets(f"git push -u origin agent/x {tail}").targets == ("agent/x",)


def test_a_branch_after_a_redirect_is_still_seen() -> None:
    """Вторая половина: ветка, названная после перенаправления, целью остаётся (140)."""
    assert module.push_targets("git push origin 2>&1 agent/x").targets == ("agent/x",)


@pytest.mark.parametrize("glued", [">out.log", ">&1", ">>out.log", "&>out.log", ">", ">&"])
def test_a_redirect_glued_to_the_branch_leaves_the_branch(glued: str) -> None:
    """Перенаправление, приклеенное к ветке, — ветка остаётся целью, а не «agent/x>…».

    Находка `55f1f51` на #1076: `git push origin agent/x>out.log` оболочка
    читает как толчок `agent/x` с выводом в файл, а сторож — как ветку
    «agent/x>out.log», и законный толчок отвергался. Хвост без цели (`>`,
    `>&`) забирает следующее слово, и оно целью не становится.
    """
    look = module.push_targets(f"git push origin agent/x{glued} out.log")
    expect = ("agent/x",) if glued in (">", ">&") else ("agent/x", "out.log")
    assert look.targets == expect


def test_a_number_is_a_descriptor_only_alone() -> None:
    """Номер дескриптора — только слово из одних цифр, как у самой оболочки.

    `2>&1` — перенаправление без цели толчка, а `agent/x2>&1` — толчок
    ветки `agent/x2`: цифра, приклеенная к имени, принадлежит имени.
    """
    assert module.push_targets("git push origin agent/x 2>&1").targets == ("agent/x",)
    assert module.push_targets("git push origin agent/x2>&1").targets == ("agent/x2",)


# --- разбор строки по правилу оболочки (#1076, 210) ----------------------------


@pytest.mark.parametrize(
    ("command", "expect"),
    [
        ("git push origin 'x>y:main'", ("x>y:main",)),
        ('git push origin "agent/x&&y"', ("agent/x&&y",)),
        ("git push origin agent/x\\>y", ("agent/x>y",)),
    ],
    ids=["одиночные", "двойные", "косая черта"],
)
def test_a_quoted_operator_is_part_of_the_word(command: str, expect: tuple[str, ...]) -> None:
    """`>` и `&&` в кавычках — часть слова, а не оператор (`6254a26`, `3a20466`).

    `shlex.split` снимал кавычки до разбора, и `'x>y:main'` читалось
    перенаправлением: цель толчка пропадала, а с ней и отказ на общую ветку.
    """
    assert module.push_targets(command).targets == expect


def test_a_quoted_shared_target_is_still_refused() -> None:
    """Цель на общую ветку в кавычках с `>` — отказ, а не пропуск."""
    said = ask("git push origin 'x>y:main'")
    assert said.returncode == 2, said.stderr


@pytest.mark.parametrize(
    "command",
    [
        "cd d&&git push origin main",
        "true;git push origin main",
        "false||git push origin main",
        "ls|git push origin main",
        "(git push origin main)",
        "ls\ngit push origin main",
    ],
    ids=["&&", ";", "||", "|", "скобки", "перевод строки"],
)
def test_a_glued_control_operator_still_splits_commands(command: str) -> None:
    """Оператор вплотную к слову делит команды так же, как отдельно стоящий (`9248712`)."""
    assert module.push_targets(command).targets == ("main",), command


def test_a_push_after_a_heredoc_body_is_seen() -> None:
    """Вторая половина: тело документа — данные, но команда ПОСЛЕ него читается."""
    command = "cat > a.md <<'EOF'\nтекст\nEOF\ngit push origin main"
    assert module.push_targets(command).targets == ("main",)
    tabbed = "cat > a.md <<-EOF\n\ttekst\n\tEOF\ngit push origin main"
    assert module.push_targets(tabbed).targets == ("main",)


def test_a_comment_is_not_a_command() -> None:
    """`#` в начале слова — комментарий до конца строки; `a#b` — слово."""
    assert module.push_targets("ls # git push origin main").targets == ()
    # Разделитель внутри комментария команды не начинает: без разбора
    # комментария `;` отделил бы толчок, и сторож отверг бы безобидное.
    assert module.push_targets("ls # ; git push origin main").targets == ()
    assert module.push_targets("git push origin agent/a#b").targets == ("agent/a#b",)


def test_an_unclosed_quote_blinds_the_guard() -> None:
    """Незакрытая кавычка — слепота сторожа, а не «не толчок» (045)."""
    assert module.push_targets("git push origin 'main").blind


def test_a_heredoc_without_its_delimiter_blinds_the_guard() -> None:
    """`<<` без разделителя — слепота, а не тело до конца (`664b218`).

    `$((1<<2))` — арифметика, и толчок на следующей строке прежде пропадал в
    «теле» документа, которого нет.
    """
    look = module.push_targets("echo $((1<<2))\ngit push origin main")
    assert "без разделителя" in look.blind, look


@pytest.mark.parametrize("quoted", ["$'main'", '$"main"'])
def test_dollar_quotes_are_quotes(quoted: str) -> None:
    """`$'main'` и `$"main"` — цель `main`, а не `$main` (`c4a1a12`)."""
    assert module.push_targets(f"git push origin {quoted}").targets == ("main",)


def test_a_backslash_newline_inside_double_quotes_is_removed() -> None:
    """`"ma\\⏎in"` — цель `main`, как у оболочки (`17859f3`)."""
    assert module.push_targets('git push origin "ma\\\nin"').targets == ("main",)


def test_a_dollar_alone_is_still_part_of_the_word() -> None:
    """Вторая половина: `$` без кавычки за ним — часть слова, как прежде."""
    assert module.push_targets("git push origin agent/$x").targets == ("agent/$x",)


# --- дедлайн и отказ git: сторож не пропускает толчок молча (письмо каталога #1439) ---


def test_the_git_budget_fits_the_hook_limit() -> None:
    """Бюджет git и дедлайн вызова меньше предела хука: убитый хук пропустил бы толчок (100)."""
    said = json.loads(SETTINGS.read_text(encoding="utf-8"))
    limits = [
        one["timeout"]
        for entry in said["hooks"]["PreToolUse"]
        for one in entry.get("hooks", [])
        if WRAPPER.name in one.get("command", "")
    ]
    assert limits, "предел хука стража не объявлен"
    assert module.GIT_DEADLINE <= module.GIT_BUDGET < min(limits) - 1


@pytest.mark.parametrize(
    "failure",
    [OSError("нет git"), subprocess.TimeoutExpired(["git"], 2.5)],
    ids=["no-git", "timeout"],
)
def test_a_failing_git_is_a_reason_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Отказ запуска и истёкший срок — причина строкой, а не трейсбек с кодом 1."""

    def broken(*_: object, **__: object) -> None:
        raise failure

    monkeypatch.setattr(module.subprocess, "run", broken)
    said = module.git("rev-parse", "HEAD")
    assert isinstance(said, str) and said
    current, why = module.head()
    assert current == "" and why
    assert "не проверил" in module.merged_away("agent/x")


def test_an_exhausted_budget_stops_calling_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Бюджет исчерпан — git не зовётся, а отказ называет причину."""
    called: list[object] = []
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: called.append(a))
    monkeypatch.setattr(module, "started", module.time.monotonic() - module.GIT_BUDGET - 1)
    said = module.git("rev-parse", "HEAD")
    assert isinstance(said, str) and "исчерпан" in said and not called


def test_the_budget_starts_with_the_run_not_the_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Модуль, загруженный давно, получает в `main()` полный бюджет, а не остаток."""
    called: list[object] = []

    def fake(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        called.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", fake)
    monkeypatch.setattr(module, "started", module.time.monotonic() - module.GIT_BUDGET - 1)
    event = json.dumps({"tool_input": {"command": "git push -u origin agent/here"}})
    monkeypatch.setattr(module.sys, "stdin", __import__("io").StringIO(event))
    module.main()
    assert called, "заход начался с исчерпанным бюджетом — отсчёт идёт от импорта"


def test_a_push_without_git_is_refused_through_main(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Без git толчок в свою ветку — отказ 2, а не трейсбек и пропуск."""

    def broken(*_: object, **__: object) -> None:
        raise OSError("нет git")

    monkeypatch.setattr(module.subprocess, "run", broken)
    event = json.dumps({"tool_input": {"command": "git push -u origin agent/here"}})
    monkeypatch.setattr(module.sys, "stdin", __import__("io").StringIO(event))
    assert module.main() == 2
    assert "не запустился" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "outcome"),
    [
        ("git push -u origin agent/here", 2),
        ('git p"u"sh origin agent/here', 2),
        ("ls -la", 0),
    ],
    ids=["толчок", "толчок-в-кавычках", "не-толчок"],
)
def test_a_crash_while_judging_refuses_a_push_and_spares_the_rest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    outcome: int,
) -> None:
    """Сбой судейства на толчке — отказ 2, а не код 1; прочая команда не роняется.

    Толчок в кавычках разбор видит толчком — значит, и признак при сбое обязан
    (находка `d256792`). Отказ не валит причину на разбор (`7e090fe`).
    """

    def crash(_: str) -> int:
        raise RuntimeError("сломано")

    monkeypatch.setattr(module, "judge", crash)
    event = json.dumps({"tool_input": {"command": command}})
    monkeypatch.setattr(module.sys, "stdin", __import__("io").StringIO(event))
    assert module.main() == outcome
    if outcome:
        assert "не досудив команду" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [
        "git push origin agent/x",
        'git p"u"sh origin agent/x',
        "git p\\ush origin agent/x",
        "git pu\\\nsh origin agent/x",
        "git 'pu'sh origin agent/x",
        "git pu$'s'h origin agent/x",
        'git pu$"s"h origin agent/x',
    ],
    ids=["голое", "кавычки", "косая", "перенос", "одинарные", "ansi-c", "локаль"],
)
def test_every_push_the_parse_sees_the_crash_sign_sees(command: str) -> None:
    """Толчок, который видит разбор, видит и признак при сбое (`d256792`, `662c08e`).

    Форма сверяется с самим разбором (`push_targets`): проба о том, что разбор
    снимает, а не о нашем представлении о нём.
    """
    assert module.push_targets(command).push, "разбор не видит толчка — проба не о том"
    assert module.maybe_push(command)


@pytest.mark.parametrize(
    "between",
    sorted(set(string.punctuation + string.whitespace + string.digits + "\u200b\u00a0")),
)
def test_no_non_letter_between_the_letters_hides_a_push(between: str) -> None:
    """Класс, а не перечень (`a9ebaae`, `dba0e48`): любой не-буквенный знак между буквами.

    Что бы разбор ни снимал между буквами слова, это не буква, — поэтому
    признак обязан видеть толчок при ЛЮБОМ таком знаке, а не при перечисленных.
    """
    assert module.maybe_push(f"git pu{between}sh origin agent/x"), repr(between)


@pytest.mark.parametrize("command", ["ls -la", "git status", "git fetch origin"])
def test_the_crash_sign_spares_what_is_not_a_push(command: str) -> None:
    """Команда без слова `push` среди букв — не толчок: прочее сторож не роняет (084)."""
    assert not module.maybe_push(command)


@pytest.mark.parametrize(
    "event", ["[1]", '{"tool_input": [1]}', '"строка"'], ids=["список", "ввод-списком", "строка"]
)
def test_an_event_of_another_shape_is_silence_not_a_trace(
    monkeypatch: pytest.MonkeyPatch, event: str
) -> None:
    """Событие не той формы — молчание 0, а не трейсбек с кодом 1 (находка `74fb515`)."""
    monkeypatch.setattr(module.sys, "stdin", __import__("io").StringIO(event))
    assert module.main() == 0


def test_judge_lets_a_harmless_command_through() -> None:
    """`judge` прямо: не толчок — пускать."""
    assert module.judge("ls -la") == 0


def test_run_ends_outside_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """После `main()` отсчёта нет: следующий вызов не наследует чужое начало."""
    event = json.dumps({"tool_input": {"command": "ls -la"}})
    monkeypatch.setattr(module.sys, "stdin", __import__("io").StringIO(event))
    assert module.run() == 0, "заход без отсчёта — бюджет не считается, команда пущена"
    monkeypatch.setattr(module.sys, "stdin", __import__("io").StringIO(event))
    assert module.main() == 0
    assert module.started is None


@pytest.mark.parametrize(
    ("segment", "cause"),
    [
        (["bash", "-c", 'git push "x'], "двойная кавычка не закрыта"),
        (["env", "-S", "git push 'x"], "одиночная кавычка не закрыта"),
    ],
    ids=["bash-c", "env-S"],
)
def test_a_nested_parse_refusal_names_its_cause(segment: list[str], cause: str) -> None:
    """Вложенный отказ разбора называет причину, как верхний уровень (195, `1b66011`)."""
    found, blind = module.unwrap(segment, module.DEPTH)
    assert not found and cause in blind, blind


def links_the_interpreter(tree: ast.Module) -> bool:
    """Зовёт ли модуль `….symlink_to(…sys.executable…)` — шим интерпретатора ссылкой."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "symlink_to"
        and "executable" in ast.unparse(node)
        for node in ast.walk(tree)
    )


def test_no_test_links_the_interpreter() -> None:
    """Шим интерпретатора — только `conftest.python_shim`, ссылкой — никогда (#1705, `16c2c31`).

    Запущенный через ссылку Python не узнаёт венв окна; две находки по этому
    месту (c3dea21, 3e8e9ae) — повод для гейта, а не для прозы (210).
    """
    linking = [
        path.name
        for path in walk(ROOT / "tests", "*.py")
        if links_the_interpreter(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert linking == []


def test_the_link_gate_sees_a_link(tmp_path: Path) -> None:
    """Обратная половина: ссылка на интерпретатор узнаётся."""
    said = "import sys\nfrom pathlib import Path\nPath('p').symlink_to(sys.executable)\n"
    assert links_the_interpreter(ast.parse(said))
    assert not links_the_interpreter(ast.parse("Path('p').symlink_to('x')\n"))


def two_trees(tmp_path: Path) -> tuple[Path, Path]:
    """Дерево проекта на `main` и второй репозиторий окна на `agent/второй` — настоящий git."""
    trees = []
    for name, branch in (("проект", "main"), ("второй", "agent/второй")):
        tree = tmp_path / name
        subprocess.run(["git", "init", "-q", "-b", "main", str(tree)], check=True, timeout=30)
        # Голова без коммита не разбирается — дереву нужен первый коммит.
        subprocess.run(
            [
                *("git", "-C", str(tree), "-c", "user.name=т", "-c", "user.email=т@т"),
                *("commit", "-q", "--allow-empty", "-m", "первый"),
            ],
            check=True,
            timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(tree), "checkout", "-q", "-B", branch],
            check=True,
            timeout=30,
        )
        trees.append(tree)
    return trees[0], trees[1]


@pytest.mark.parametrize(
    ("command", "start", "expect"),
    [
        ("git -C {второй} push origin agent/второй", "", 0),
        ("cd {второй} && git push -u origin agent/второй", "", 0),
        ("git push origin agent/второй", "{второй}", 0),
        ("git -C второй push origin agent/второй", "{база}", 0),
        ("git -C {второй} push origin agent/чужая", "", 2),
        ("cd {второй} && git push origin agent/чужая", "", 2),
        ("git push origin agent/второй", "", 2),
        ("cd - && git push origin agent/второй", "", 2),
        ("git --git-dir={второй}/.git push origin agent/второй", "", 2),
    ],
    ids=[
        "ключ-C",
        "cd-в-строке",
        "каталог-события",
        "C-от-каталога-события",
        "C-чужая-ветка",
        "cd-чужая-ветка",
        "дерево-проекта-не-та-ветка",
        "cd-минус-не-узнан",
        "git-dir-не-судится",
    ],
)
def test_the_head_is_read_in_the_pushed_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, start: str, expect: int
) -> None:
    """Голова читается в дереве, которое толкают, а не в дереве сторожа (#1746).

    Окно ведёт два репозитория; сторож запущен в дереве проекта на `main`.
    Толчок своей `agent/…` второго репозитория — через `-C`, `cd` или каталог
    события — проходит; чужая ветка и неузнанный каталог — отказ.
    """
    project, second = two_trees(tmp_path)
    monkeypatch.chdir(project)
    said = {"второй": str(second), "база": str(tmp_path)}
    assert module.judge(command.format(**said), start.format(**said)) == expect
