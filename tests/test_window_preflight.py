"""Окно проверяет окружение на входе и своё красное перед толчком.

Оба механизма проверяются тем, что обязаны ОТВЕРГНУТЬ
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)):
подделанная версия интерпретатора и заведомо красная команда. Зелёное на
здоровом дереве не доказывает ничего — оно так же выглядит у механизма,
который не проверяет вовсе.

ЗАМЕР, ИЗ-ЗА КОТОРОГО ОБА НАПИСАНЫ, повторился в день написания: окно шло на
3.11, дерево требует `>=3.12`, и все локальные прогоны шли не на той версии, на
которой их гоняет площадка. Механизм назвал это первой же строкой.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import ROOT, RunScript, load_script

env = load_script("check_env.py")
preflight = load_script("preflight.py")

PYPROJECT = '[project]\nname = "x"\nrequires-python = ">=3.12"\n'
WORKFLOW = """
name: ci
on: [pull_request]
jobs:
  lint:
    steps:
      - name: поставить проверки
        run: python -m pip install --quiet "ruff>=0.6,<1" "mypy>=1.11,<2"
      - name: линтер
        run: ruff check scripts/
"""


def tree(root: Path, project: str = PYPROJECT, workflow: str = WORKFLOW) -> Path:
    """Собирает дерево из требований и прогона; отдаёт корень."""
    (root / "pyproject.toml").write_text(project, encoding="utf-8")
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ci.yml").write_text(workflow, encoding="utf-8")
    return root


# --- сверка окружения ---------------------------------------------------------


def test_a_survey_names_what_it_saw_and_what_diverged(tmp_path: Path) -> None:
    """Сверка отдаёт и увиденное, и расхождения — одним разбором на двух зовущих.

    До 18.09.2026 разбор жил ВНУТРИ точки входа и печатал по ходу: второму
    зовущему — предполётной — оставалось запустить процесс и разобрать его вывод,
    то есть завести второй разбор того же
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    said = env.survey(tree(tmp_path))
    assert said.seen, "сверка не назвала ни одного инструмента — читателю нечего прочесть"
    assert any("интерпретатор" in one for one in said.seen)


def test_the_survey_answers_four_questions_not_one(tmp_path: Path) -> None:
    """У сверки четыре поля, и каждое отвечает своему читателю.

    `seen` — человеку: что вообще увидено, включая сошедшееся. `problems` —
    зовущему механизму: расходится ли, и ему всё равно, чем это ставится.
    `gaps` — команде установки. `floor` — тому, кто печатает совет: граница уже
    прочитана сверкой, и читать её второй раз значило бы утверждать, что дерево
    между двумя чтениями не изменилось (005). Слить их в одно значило бы
    заставить каждого читателя разбирать чужой формат обратно
    ([021](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/021-split-docs-by-reader.md)).
    """
    empty = env.Survey(seen=[], problems=[], gaps=[], floor=(3, 12))
    assert (empty.seen, empty.problems, empty.gaps, empty.floor) == ([], [], [], (3, 12)), (
        "поля сверки перепутаны местами: три списка с разными читателями легко"
        " переставить, и снаружи подмена не видна"
    )
    # ПРЕДМЕТ ЗДЕСЬ — ФОРМА ОТВЕТА, А НЕ ЧУЖОЕ ОКРУЖЕНИЕ. Первая редакция
    # требовала пустых `problems` — то есть утверждала, что у ЗАПУСТИВШЕГО
    # установлено всё, что объявляет поддельное дерево. На матричной ячейке
    # площадки стоит один `pytest`, и здоровый набор краснел там из-за
    # отсутствующего `mypy`: проверка судила окружение прогона вместо своего
    # предмета
    # ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    said = env.survey(tree(tmp_path))
    assert said.seen, "сверка не назвала ни одного инструмента — читателю нечего прочесть"
    assert len(said.gaps) <= len(said.problems), (
        "команд установки больше, чем расхождений: у каждого куска команды обязано быть"
        f" своё расхождение — {said.gaps} против {said.problems}"
    )
    for gap in said.gaps:
        assert any(
            gap.strip('"-e ./').split(">")[0].split("<")[0] in one for one in said.problems
        ), f"кусок команды «{gap}» не отвечает ни одному названному расхождению"


def test_a_tool_outside_the_declared_bounds_is_named(tmp_path: Path) -> None:
    """Инструмент вне объявленных границ назван расхождением, а не мелочью.

    ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ПРОВЕРКА И НАПИСАНА: окно гоняло mypy
    2.3.1 при объявленных `>=1.11,<2`. Предполётная давала «зелено: 18»,
    площадка краснела на шаге типов — то есть зелёное окна не предсказывало
    площадку, а именно это оно и обещает
    ([073](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/073-tool-version-from-one-source-with-an-upper-bound.md)).
    """
    root = tree(
        tmp_path,
        workflow=WORKFLOW.replace('"mypy>=1.11,<2"', '"mypy>=99,<100"'),
    )
    said = env.survey(root)
    assert any(one.startswith("mypy:") for one in said.problems), (
        f"mypy вне границ не назван расхождением: {said.problems}"
    )
    assert any("mypy" in one for one in said.gaps), "расхождение названо, а команда установки — нет"


def test_the_floor_comes_from_the_tree(tmp_path: Path) -> None:
    """Требование к интерпретатору читается из `pyproject.toml`, а не из кода."""
    assert env.python_floor(tree(tmp_path)) == (3, 12)


def test_the_floor_is_read_once_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Граница читается ОДИН раз за заход, а не отдельно каждым читателем.

    Сверка спрашивает её у дерева сама — без неё она не отличит годный
    интерпретатор от старого, — и отдаёт полем. Пока поля не было, точка входа
    читала ту же границу повторно ради совета в конце: одно число, полученное
    дважды за прогон, и второе чтение молчаливо утверждало, что дерево между
    двумя вызовами не изменилось
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

    ДЕРЕВО ТРЕБУЕТ ЗАВЕДОМО НЕДОСТИЖИМОЙ ВЕРСИИ — чтобы заход дошёл до совета
    при любом окружении запустившего. Иначе проверка судила бы чужую машину
    вместо своего предмета (044).
    """
    root = tree(tmp_path, '[project]\nname = "x"\nrequires-python = ">=99.0"\n')
    counted: list[Path] = []
    real = env.python_floor

    def counting(where: Path = Path()) -> tuple[int, int]:
        """Считает обращения к границе и отвечает настоящим значением."""
        counted.append(where)
        # Разбор с приведением, а не возврат как есть: механизм приходит из
        # `load_script`, то есть нетипизированным, и строгий разбор типов не
        # принял бы `Any` там, где объявлена пара чисел.
        major, minor = real(where)
        return int(major), int(minor)

    monkeypatch.setattr(env, "python_floor", counting)
    assert env.main(["--root", str(root)]) == env.EXIT_MISMATCH
    assert "что делать" in capsys.readouterr().out, "заход не дошёл до совета — предмета нет (075)"
    assert len(counted) == 1, f"граница прочитана {len(counted)} раз(а) за один заход: {counted}"


def test_a_tree_without_requirements_is_an_input_error(tmp_path: Path) -> None:
    """Требований нет — отказ входа, а не «подходит любая версия» (075)."""
    with pytest.raises(env.NotRun):
        env.python_floor(tmp_path)


def test_a_requirement_without_a_floor_is_refused(tmp_path: Path) -> None:
    """`requires-python` без нижней границы не выдаётся за требование."""
    tree(tmp_path, '[project]\nname = "x"\nrequires-python = "<4"\n')
    with pytest.raises(env.NotRun, match="нижней границы"):
        env.python_floor(tmp_path)


def test_tools_come_from_the_install_lines(tmp_path: Path) -> None:
    """Инструменты и границы берутся из строк установки в прогонах."""
    found = env.needs(tree(tmp_path))
    assert found["ruff"].bounds == ">=0.6,<1"
    assert found["mypy"].bounds == ">=1.11,<2"


def test_a_tree_that_argues_with_itself_is_refused(tmp_path: Path) -> None:
    """Одно имя с разными границами в двух прогонах — отказ, а не выбор механизма.

    Обе строки одинаково правдоподобны, и взять любую значило бы решить за
    проект молча (022).
    """
    root = tree(tmp_path)
    (root / ".github" / "workflows" / "other.yml").write_text(
        'jobs:\n  x:\n    steps:\n      - run: python -m pip install "ruff>=0.9,<1"\n',
        encoding="utf-8",
    )
    with pytest.raises(env.NotRun, match="по-разному"):
        env.needs(root)


def test_a_tree_without_install_lines_is_an_input_error(tmp_path: Path) -> None:
    """Ни одной строки установки — предмет сверки не найден (075)."""
    tree(tmp_path, workflow="name: ci\non: [push]\njobs: {}\n")
    with pytest.raises(env.NotRun):
        env.needs(tmp_path)


@pytest.mark.parametrize(
    ("version", "bounds", "good"),
    [
        ("3.12.3", ">=3.12", True),
        ("3.11.15", ">=3.12", False),
        ("0.16.6", ">=0.6,<1", True),
        ("1.2.0", ">=0.6,<1", False),
        ("6.0.3", ">=6,<7", True),
        ("7.0", ">=6,<7", False),
        ("8.4.2", "", True),
    ],
)
def test_bounds_are_read_the_way_the_tree_writes_them(
    version: str, bounds: str, good: bool
) -> None:
    """Границы разбираются так, как они записаны в дереве.

    Верхняя граница здесь не украшение: без неё несовместимая версия
    применяется молча — это то, ради чего проект их и требует.
    """
    assert env.fits(version, bounds) is good


def test_an_unknown_kind_of_bound_is_refused() -> None:
    """Незнакомый вид границы — отказ, а не «наверное, годится» (068).

    Молчаливое «подходит» на неразобранной границе неотличимо от проверки, и
    именно так проверка перестаёт что-либо значить.
    """
    with pytest.raises(env.NotRun):
        env.fits("1.0", "~=1.0")


def test_the_step_says_what_to_do(run_script: RunScript, tmp_path: Path) -> None:
    """Расхождение печатается вместе с действием, а не одной констатацией.

    «Версия не та» без продолжения оставляет окно ровно там, где застало: в
    окружении, где установка в системный запрещена, а нужного интерпретатора
    нет под рукой.
    """
    tree(tmp_path, '[project]\nname = "x"\nrequires-python = ">=99.0"\n')
    run = run_script("check_env.py", "--root", str(tmp_path))
    assert run.code == 3, run.text
    assert "что делать" in run.text
    assert "venv" in run.text


# --- свой прогон перед толчком ------------------------------------------------


def test_the_commands_come_from_the_workflow(tmp_path: Path) -> None:
    """Что запускается, взято из прогона, а не перечислено в механизме.

    Иначе добавленный в прогон гейт появился бы здесь через полгода — или не
    появился бы вовсе, и разошлись бы они молча (022).
    """
    root = tree(tmp_path)
    names = [step.command for step in preflight.steps(root / ".github" / "workflows" / "ci.yml")]
    assert names == ["ruff check scripts/"], names


def test_a_platform_command_is_not_run_locally(tmp_path: Path) -> None:
    """Проверка, которой нужна площадка, локально НЕ запускается.

    Объявить её пройденной здесь значило бы завести тихий запасной путь: она
    выглядела бы зелёной, ничего не проверив (045).
    """
    root = tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n"
            "      - run: python scripts/check_pr_meta.py --files-from /tmp/x\n"
            "      - run: ruff check scripts/\n"
        ),
    )
    found = preflight.steps(root / ".github" / "workflows" / "ci.yml")
    assert [step.command for step in found] == ["ruff check scripts/"]


def test_a_workflow_without_commands_is_an_input_error(tmp_path: Path) -> None:
    """Ни одной выполнимой команды — отказ входа, а не «всё зелено» (075)."""
    root = tree(tmp_path, workflow="jobs:\n  x:\n    steps:\n      - uses: actions/checkout@v4\n")
    with pytest.raises(preflight.NotRun):
        preflight.steps(root / ".github" / "workflows" / "ci.yml")


def test_red_is_caught_before_the_push(run_script: RunScript, tmp_path: Path) -> None:
    """Заведомо красная команда ловится здесь, а не логами площадки.

    ПРЕДМЕТ НАЗВАН ПОИМЁННО, А НЕ ПО ИСХОДУ. На синтетическом дереве проверка
    ветки (`agent_pr.py --dry-run`) красна всегда: ветки с задачей там нет.
    Пока тест смотрел только на код возврата и слово «толкать рано», он был
    зелен и без своей красной команды — то есть проверял чужой отказ. Нашёл
    внешний взгляд на #151.
    """
    tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: заведомо красное\n"
            "        run: ruff check nowhere/\n"
        ),
    )
    run = run_script("preflight.py", "--root", str(tmp_path))
    assert run.code == 3, run.text
    assert "толкать рано" in run.text
    assert "заведомо красное" in run.text, run.text


def test_a_foreign_root_is_not_surveyed_at_all(tmp_path: Path) -> None:
    """Чужой корень не сверяется, и расхождений оттуда не приходит.

    Сверка отвечает на вопрос «предскажет ли зелёное площадку», а площадка есть
    у ОДНОГО дерева — того, в котором лежит сама предполётная. На чужом корне
    она сравнивала бы установленное у запустившего с объявлениями чужого дерева
    (044).
    """
    tree(tmp_path)
    assert preflight.environment_gap(tmp_path) == [], (
        "чужой корень дал расхождение: сверка судит не то дерево"
    )


def test_its_own_root_is_surveyed(tmp_path: Path) -> None:
    """Своё дерево сверяется — иначе шов зеленел бы всегда и не значил ничего.

    Вторая половина предыдущей проверки: без неё «расхождений нет» держалось бы
    тем, что сверка не идёт НИКОГДА
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    assert preflight.environment_gap(ROOT) == env.survey(ROOT).problems, (
        "на своём дереве шов отдаёт не то, что говорит сверка"
    )


def test_an_unsurveyed_environment_is_said_out_loud(run_script: RunScript, tmp_path: Path) -> None:
    """Сверка не отработала — это сказано, а не превращено в «сошлось».

    ПРИЧИН ДВЕ, И ОБЕ ГОВОРЯТСЯ ВСЛУХ. Первая: корень ЧУЖОЙ — предполётную
    натравили на дерево, в котором её самой нет, и объявления там про чужую
    площадку. Вторая: в дереве нет строк установки, читать нечего. Глушить из-за
    любой из них все проверки значило бы чинить не то; молчать — выдавать
    непроверенное за проверенное (045).

    ЗАМЕР 18.09.2026: пока сверка шла на ЛЮБОМ корне, она сравнивала
    установленное у запустившего с объявлениями поддельного дерева — и здоровый
    набор краснел на матричной ячейке площадки, где стоит один `pytest`.
    """
    tree(tmp_path, workflow="jobs:\n  x:\n    steps:\n      - run: true\n")
    run = run_script("preflight.py", "--root", str(tmp_path))
    assert "окружение НЕ сверено" in run.text, run.text


def test_a_green_command_is_not_listed_among_the_red(run_script: RunScript, tmp_path: Path) -> None:
    """Зелёная команда в списке красных не появляется — вторая половина проверки.

    Без неё «красное названо» держалось бы тем, что имя вообще печатается: шаг
    печатает все имена в режиме списка, и отличить «названо среди красных» от
    «названо вообще» было бы нечем (140).
    """
    tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: заведомо зелёное\n        run: python -c pass\n"
        ),
    )
    run = run_script("preflight.py", "--root", str(tmp_path))
    red = run.text.split("толкать рано", 1)[-1]
    assert "заведомо зелёное" not in red, run.text


def test_the_step_names_what_it_cannot_check(run_script: RunScript, tmp_path: Path) -> None:
    """Невыполнимое здесь названо НЕВЫПОЛНЕННЫМ, а не пропущено молча (046)."""
    tree(tmp_path)
    run = run_script("preflight.py", "--root", str(tmp_path), "--list")
    assert run.code == 0, run.text
    assert "не проверяет" in run.text
    assert "attribution" in run.text


def test_the_tools_come_from_the_running_interpreter(tmp_path: Path) -> None:
    """Команды идут тем интерпретатором, которым запущен механизм.

    Иначе `pytest` и `ruff` придут из системного пути, с ДРУГОЙ версией, — то
    есть прогон проверит не то окружение, ради которого он и заведён. Замер:
    ровно так этот механизм и упал в первом же заходе.
    """
    room = preflight.environment()
    assert room["PATH"].startswith(str(Path(preflight.sys.executable).parent))


# --- команда берётся блоком, а не строкой из середины -------------------------
#
# Находка ревью по #94: построчный разбор выдёргивал команду из середины блока
# `run: |`, оставляя за бортом обвязку — `set -euo pipefail`, подготовку базы,
# `git fetch`. Запускалось не то, что запускает площадка, и молча.


def test_a_command_is_taken_with_its_shell_wrapping(tmp_path: Path) -> None:
    """Блок берётся целиком: обвязка — часть команды, а не оформление."""
    root = tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: гейт\n        run: |\n"
            "          set -euo pipefail\n"
            "          export MODE=strict\n"
            "          ruff check scripts/\n"
        ),
    )
    found = preflight.steps(root / ".github" / "workflows" / "ci.yml")
    assert len(found) == 1
    assert "set -euo pipefail" in found[0].command
    assert "ruff check scripts/" in found[0].command


def test_a_block_needing_the_platform_is_skipped_whole(tmp_path: Path) -> None:
    """Площадка нужна блоку целиком, если её требует хотя бы одна строка.

    Запустить остальное без неё значит проверить половину и назвать это
    проверкой.
    """
    root = tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: журнал\n        run: |\n"
            "          set -euo pipefail\n"
            "          git fetch --no-tags origin main\n"
            "          python scripts/check_pr_meta.py\n"
            "      - name: линтер\n        run: ruff check scripts/\n"
        ),
    )
    found = preflight.steps(root / ".github" / "workflows" / "ci.yml")
    assert [step.name for step in found] == ["линтер"]


def test_a_platform_substitution_makes_the_step_unrunnable(tmp_path: Path) -> None:
    """Подстановка площадки локально не раскрывается — шаг называется, а не запускается.

    Запустить блок с нераскрытой подстановкой значит проверить не ту команду и
    получить правдоподобный результат (045).
    """
    preflight.UNRUNNABLE.clear()
    root = tree(
        tmp_path,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: свод\n        run: |\n"
            '          python scripts/check_pipeline.py --self "${{ github.job }}"\n'
            "      - name: линтер\n        run: ruff check scripts/\n"
        ),
    )
    found = preflight.steps(root / ".github" / "workflows" / "ci.yml")
    assert [step.name for step in found] == ["линтер"]
    assert "свод" in preflight.UNRUNNABLE, "отложенный шаг не назван — пропуск стал молчанием"


def test_the_shell_is_the_one_the_platform_uses() -> None:
    """Команды идут той же оболочкой, что у площадки, а не умолчанием `sh`.

    Площадка запускает шаги в bash; `shell=True` без указания берёт `/bin/sh`,
    и `set -o pipefail` там не понят — здоровый шаг краснел с «Illegal
    option». Прогон, идущий другой оболочкой, проверяет не то, что проверит
    площадка (022). Замер 10.09.2026, на шаге поверхности контракта.
    """
    source = (ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert 'executable="/bin/bash"' in source, "оболочка не названа — команды пойдут через sh"


# --- проверки ветки, которых нет шагом прогона --------------------------------


def test_branch_checks_run_before_the_workflow_ones() -> None:
    """Проверки ветки идут первыми: без них остальное бессмысленно.

    Красное здесь значит, что изменение не откроется вовсе, — и прогонять
    линтер по ветке, которая никуда не поедет, незачем.
    """
    assert preflight.BEFORE_PUSH
    assert "agent_pr.py --dry-run" in preflight.BEFORE_PUSH[0].command


def test_the_branch_check_is_not_a_second_list_of_the_workflow() -> None:
    """Это не второй список тех же команд (022), а то, чего в прогоне нет.

    Предмет у проверок ветки — состояние ДО открытия изменения: приставка и
    связь с задачей. Шага с такой командой нет ни в одном прогоне, потому что
    прогон запускается уже после.
    """
    workflow = {step.command for step in preflight.steps()}
    assert not any(step.command in workflow for step in preflight.BEFORE_PUSH)


def test_the_journal_gate_is_run_locally() -> None:
    """Гейт журнала спрашивается своим прогоном, а не только площадкой.

    Замер 10.09.2026: три изменения подряд покраснели на разборе фрагмента —
    имя, род и ссылка на задачу видны на дереве целиком, а ловились уже после
    толчка. Причина была механической: `git fetch` жил внутри блока проверки, и
    блок целиком считался требующим площадки.
    """
    commands = " ".join(step.command for step in preflight.steps())
    assert "check_journal.py" in commands
    assert "build_changelog.py --fragments" in commands
    assert "git fetch" not in commands


def test_deferred_steps_belong_to_this_read(tmp_path: Path) -> None:
    """Отложенное относится к ЭТОМУ дереву, а не ко всем прочитанным за жизнь.

    Словарь копился между вызовами в одном процессе и требовал ручной очистки в
    тесте — то есть механизм отвечал не про то дерево, которое у него спросили.
    Нашёл внешний взгляд на #101.
    """
    first = tmp_path / "с подстановкой"
    first.mkdir()
    with_mark = tree(
        first,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: разметка\n"
            "        run: pytest --strict-markers -k ${{ github.event.number }}\n"
            "      - name: линтер\n        run: ruff check scripts/\n"
        ),
    )
    preflight.steps(with_mark / ".github" / "workflows" / "ci.yml")
    assert "разметка" in preflight.UNRUNNABLE

    second = tmp_path / "чистое"
    second.mkdir()
    clean = tree(
        second,
        workflow=(
            "jobs:\n  x:\n    steps:\n      - name: линтер\n        run: ruff check scripts/\n"
        ),
    )
    preflight.steps(clean / ".github" / "workflows" / "ci.yml")
    assert preflight.UNRUNNABLE == {}, "отложенное прошлого чтения осталось в ответе"


def remember(where: list[object], what: object) -> int:
    """Запоминает вызов и отвечает успехом: подделка толчка для проверок ниже."""
    where.append(what)
    return int(preflight.EXIT_OK)


def test_a_red_verdict_never_reaches_the_push(monkeypatch: pytest.MonkeyPatch) -> None:
    """Красный вердикт до толчка НЕ ДОХОДИТ: толкать нечем, а не «не следует».

    ВЕРДИКТ, КОТОРЫЙ ЧИТАЕТ ТОТ ЖЕ, КТО ДЕЙСТВУЕТ, — НАПОМИНАНИЕ, А НЕ
    МЕХАНИЗМ. Замер 17.09.2026: за смену ТРИ толчка из примерно пятнадцати ушли
    при красном вердикте, и каждый раз вердикт печатался тем же заходом, что и
    толчок. Ловил это человек, а не машина — а человек тут и есть тот, кто
    спешит.
    """
    pushed: list[object] = []
    monkeypatch.setattr(preflight, "push_branch", lambda root: remember(pushed, root))
    monkeypatch.setattr(preflight, "steps", lambda path: [])
    monkeypatch.setattr(preflight, "BEFORE_PUSH", [preflight.Step("красный", "false")])
    monkeypatch.setattr(preflight, "run", lambda step, root: (1, "красное"))
    monkeypatch.setattr(preflight, "report_gaps", lambda: None)
    # СВЕРКА ОКРУЖЕНИЯ — ТАКОЙ ЖЕ СОСЕД, как `steps` и `run`. Предмет здесь —
    # отношение «красное → не толкаем», а не состав чужой машины: без подмены
    # прогон зависел бы от того, стоит ли у запустившего `mypy` (150).
    monkeypatch.setattr(preflight, "environment_gap", lambda root: [])
    assert preflight.main(["--push"]) == preflight.EXIT_RED
    assert not pushed, "толчок случился при красном вердикте"


def test_a_green_verdict_pushes_in_the_same_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Зелёный вердикт толкает ТЕМ ЖЕ заходом: проверка и действие — один акт."""
    pushed: list[object] = []
    monkeypatch.setattr(preflight, "push_branch", lambda root: remember(pushed, root))
    monkeypatch.setattr(preflight, "steps", lambda path: [])
    monkeypatch.setattr(preflight, "BEFORE_PUSH", [preflight.Step("зелёный", "true")])
    monkeypatch.setattr(preflight, "run", lambda step, root: (0, ""))
    monkeypatch.setattr(preflight, "report_gaps", lambda: None)
    # СВЕРКА ОКРУЖЕНИЯ — ТАКОЙ ЖЕ СОСЕД, как `steps` и `run`. Предмет здесь —
    # отношение «красное → не толкаем», а не состав чужой машины: без подмены
    # прогон зависел бы от того, стоит ли у запустившего `mypy` (150).
    monkeypatch.setattr(preflight, "environment_gap", lambda root: [])
    assert preflight.main(["--push"]) == preflight.EXIT_OK
    assert pushed, "зелёный вердикт не довёл до толчка"


def test_without_the_flag_nothing_is_pushed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без флага заход остаётся ЧТЕНИЕМ: проверка сама ничего не отправляет.

    Толкать по умолчанию значило бы отправлять работу того, кто звал проверку
    посмотреть, — и обратной дороги у толчка нет.
    """
    pushed: list[object] = []
    monkeypatch.setattr(preflight, "push_branch", lambda root: remember(pushed, root))
    monkeypatch.setattr(preflight, "steps", lambda path: [])
    monkeypatch.setattr(preflight, "BEFORE_PUSH", [preflight.Step("зелёный", "true")])
    monkeypatch.setattr(preflight, "run", lambda step, root: (0, ""))
    monkeypatch.setattr(preflight, "report_gaps", lambda: None)
    # СВЕРКА ОКРУЖЕНИЯ — ТАКОЙ ЖЕ СОСЕД, как `steps` и `run`. Предмет здесь —
    # отношение «красное → не толкаем», а не состав чужой машины: без подмены
    # прогон зависел бы от того, стоит ли у запустившего `mypy` (150).
    monkeypatch.setattr(preflight, "environment_gap", lambda root: [])
    assert preflight.main([]) == preflight.EXIT_OK
    assert not pushed, "проверка толкнула без просьбы"


def test_the_shared_branch_is_never_pushed_by_the_check(tmp_path: Path) -> None:
    """Общую ветку проверка не толкает: работа идёт в `agent/<задача>` (003)."""
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "файл").write_text("предмет", encoding="utf-8")
    for args in (
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "набор"],
        ["add", "-A"],
        ["commit", "-qm", "предмет"],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    assert preflight.push_branch(tmp_path) == preflight.EXIT_BROKEN


def test_the_branch_name_is_read_from_the_tree(tmp_path: Path) -> None:
    """Имя ветки берётся из дерева, а не из памяти зовущего.

    Толкать по имени, переданному руками, значит отправлять работу туда, куда
    её никто не клал: дерево знает своё имя само (049).
    """
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "agent/предмет"], cwd=tmp_path, check=True)
    (tmp_path / "файл").write_text("предмет", encoding="utf-8")
    for args in (
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "набор"],
        ["add", "-A"],
        ["commit", "-qm", "предмет"],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    assert preflight.branch_now(tmp_path) == "agent/предмет"


def test_a_tree_without_a_branch_is_the_third_outcome(tmp_path: Path) -> None:
    """Ветку не прочитать — это отказ входа, а не пустое имя (045)."""
    with pytest.raises(preflight.NotRun):
        preflight.branch_now(tmp_path)


def test_a_branch_without_the_prefix_is_never_pushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ветка без приставки конвейера не толкается — изменения по ней не откроется.

    ПРИСТАВКА — ПЕРЕКЛЮЧАТЕЛЬ, А НЕ СТИЛЬ (003). Первая редакция отвергала два
    имени, `main` и `HEAD`, и пропускала всё остальное — включая `claude/<окно>`,
    ветку, которую окну выдаёт сама площадка. Толчок туда проходит, изменения не
    открывает, и заход рапортует успех: работа уезжает в никуда. Сообщение при
    этом уже ссылалось на 003 и проверяло не то, о чём 003 говорит. Нашёл
    внешний взгляд на #433.
    """
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "claude/окно-1"], cwd=tmp_path, check=True)
    (tmp_path / "файл").write_text("предмет", encoding="utf-8")
    for args in (
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "набор"],
        ["add", "-A"],
        ["commit", "-qm", "предмет"],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    said: list[list[str]] = []
    original = subprocess.run

    def watched(args, **rest):  # type: ignore[no-untyped-def]
        said.append(list(args))
        return original(args, **rest)

    monkeypatch.setattr(preflight.subprocess, "run", watched)
    assert preflight.push_branch(tmp_path) == preflight.EXIT_BROKEN
    # ОТКАЗ ОБЯЗАН ПРИЙТИ ОТ ПРОВЕРКИ, А НЕ ОТ НЕУДАЧНОГО ТОЛЧКА. В пустом
    # дереве `git push` падает и сам по себе, и первая редакция этого теста
    # зеленела на прежнем — негодном — условии: код возврата совпадал, причина
    # была другая. Поэтому судится СОСТАВ вызовов: толчка не должно случиться
    # вовсе (170 — зелёное на подделке тоже гипотеза).
    assert not any("push" in one for one in said), f"толчок случился на ветке без приставки: {said}"


def test_the_prefix_comes_from_the_one_who_decides_by_it() -> None:
    """Список приставок берётся у `agent_pr`, а не пишется здесь второй копией.

    Разъехавшись, два списка дали бы худший из отказов: толчок прошёл,
    изменение не открылось, красного нет нигде (022, 090).
    """
    agent_pr = load_script("agent_pr.py")
    assert preflight.agent_pr.PREFIXES is agent_pr.PREFIXES or (
        preflight.agent_pr.PREFIXES == agent_pr.PREFIXES
    ), "проверка толчка ведёт свой список приставок"
    assert agent_pr.PREFIXES, "приставок не объявлено — предмета у проверки нет (075)"
