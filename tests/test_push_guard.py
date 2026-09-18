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

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ROOT

HOOK = ROOT / ".claude" / "hooks" / "push_guard.py"
#: Сам сторож как модуль: часть его разбора проверяется прямо, без процесса.
#: Он лежит не в `scripts/`, поэтому общий загрузчик набора сюда не годится.
_spec = importlib.util.spec_from_file_location("push_guard", HOOK)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
sys.modules["push_guard"] = module
_spec.loader.exec_module(module)
SETTINGS = ROOT / ".claude" / "settings.json"


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
        ["python3", str(HOOK)],
        input=event,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            "PATH": f"{fake}:/usr/bin:/bin",
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


def test_a_push_into_an_already_merged_branch_is_refused() -> None:
    """Работа слита — дописывать в эту ветку нечего.

    Второй признак нужен отдельно: ветку могли не удалить (настройка площадки),
    а история всё равно уже в общей. Тогда продолжение даёт конфликт ИСТОРИИ,
    который выглядит конфликтом содержимого — диф в четыре файла вместо одного.
    """
    done = ask("git push origin agent/here", merged="1", tracked="1")
    assert done.returncode == 2, done.stdout
    assert "уже достижима" in done.stderr, done.stderr


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
    Здесь заводится живой репозиторий, работа сливается в общую ветку — и
    признак «уже достижима» обязан сработать на нём.
    """

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "--quiet", "-b", "main")
    run("config", "user.email", "кто@то")
    run("config", "user.name", "кто-то")
    (tmp_path / "файл").write_text("раз", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "первый")
    run("checkout", "--quiet", "-b", "agent/work")
    (tmp_path / "файл").write_text("два", encoding="utf-8")
    run("commit", "--quiet", "-am", "работа")
    # ВЕТКУ ТОЛКАЛИ, и это часть предмета: воскресить можно лишь то, что на
    # площадке было. Слежение за одноимённой веткой ставит `push -u` — здесь
    # оно записывается прямо, потому что площадки у временного клона нет.
    run("config", "branch.agent/work.merge", "refs/heads/agent/work")
    run("config", "branch.agent/work.remote", "origin")
    # «Площадка» приняла толчок ветки, слила работу и общую ветку опубликовала.
    # ВЕТКУ ПРИ ЭТОМ НЕ УДАЛИЛА — это отдельный случай, и предмет здесь именно
    # он: первый признак («ссылки нет») молчит, второй («уже достижима») обязан
    # сработать. Настройка площадки удалять ветку при слиянии есть не везде.
    run("update-ref", "refs/remotes/origin/agent/work", "refs/heads/agent/work")
    run("checkout", "--quiet", "main")
    run("merge", "--quiet", "--ff-only", "agent/work")
    run("update-ref", "refs/remotes/origin/main", "refs/heads/main")
    run("checkout", "--quiet", "agent/work")

    here = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        said = module.merged_away("agent/work")
    finally:
        os.chdir(here)
    assert "уже достижима" in said, said or "живой репозиторий не дал признака слияния"


def test_a_first_push_of_a_fresh_branch_passes() -> None:
    """Первый толчок НОВОЙ ветки проходит: воскрешать ещё нечего.

    `git checkout -b <новая> origin/main` — процедура свода — оставляет
    `branch.<новая>.merge = refs/heads/main`: git настраивает слежение за той
    веткой, ОТ КОТОРОЙ отрезали. Ссылки `origin/<новая>` при этом нет, потому
    что ветки на площадке нет вовсе. Первая редакция запрета считала это
    воскрешением слитой и отвергала первый же толчок — то есть ломала ровно ту
    процедуру, которой сама и учит в тексте отказа. Нашёл внешний взгляд.
    """
    done = ask("git push -u origin agent/here", gone="1", elsewhere="1")
    assert done.returncode == 0, done.stderr


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
