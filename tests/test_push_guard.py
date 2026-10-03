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

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script

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
    (where / f"python{floor}").symlink_to(sys.executable)
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
    assert "кавычки не закрыты" in said.stderr


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
    python3 = tmp_path / "python3"
    python3.symlink_to(sys.executable)
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
