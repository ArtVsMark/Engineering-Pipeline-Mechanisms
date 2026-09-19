"""Команда подключения: заготовка выводится из дерева, а не пишется руками.

Порядок подключения, живущий прозой, исполняется по-разному каждым, кто его
прочёл, — и ровно так разошлись пять конвейеров семьи. Проверяется здесь то,
без чего заход был бы распечаткой памяти:

* состав шагов берётся из ПОМЕТОК дерева: список руками отстал бы на первом же
  вынесенном шаге, и отстал бы молча (022, 049);
* прибивка — тег ВЫПУСКА, а не версия поверхности: это разные числа, и
  вторая указала бы на тег, которого нет;
* имя записи проверки СОСТАВНОЕ: голое имя оставило бы потребителя со сводным
  гейтом, ждущим записи, которой никто не выдаст (045);
* класс проверки заход не решает: это свойство потребителя (174).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script

module = load_script("onboard.py")
policy = load_script("pipeline_checks.py")

#: Шаг, помеченный отдаваемым наружу, — минимальный, какой признаёт разбор.
MARKED = (
    "# ОТДАЁТСЯ НАРУЖУ: пример\n"
    "name: step-пример\non:\n  workflow_call:\njobs:\n  x:\n    steps: []\n"
)
#: Тот же файл БЕЗ пометки: помеченность объявляет автор, а не имя файла.
PLAIN = "name: step-молчун\non:\n  workflow_call:\njobs:\n  x:\n    steps: []\n"


def tree(tmp_path: Path, *, tagged: str = "v2.5.0", **runs: str) -> Path:
    """Дерево с прогонами и тегом выпуска — настоящим, а не подделанным.

    Тег читается разбором механизма версии, и тот спрашивает ЖИВОЙ git: на
    подделке проверка подтверждала бы согласие кода с нашим представлением о
    тегах, а не с git (170).
    """
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    for name, body in runs.items():
        (tmp_path / ".github" / "workflows" / f"{name}.yml").write_text(body, encoding="utf-8")
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    run = ["git", "-C", str(tmp_path)]
    subprocess.run([*run, "init", "--quiet", "-b", "main"], check=True)
    subprocess.run([*run, "config", "user.email", "т@т"], check=True)
    subprocess.run([*run, "config", "user.name", "т"], check=True)
    subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*run, "commit", "--quiet", "-m", "дерево"], check=True)
    if tagged:
        subprocess.run([*run, "tag", tagged], check=True)
    return tmp_path


def test_the_steps_come_from_the_marks(tmp_path: Path) -> None:
    """Состав — помеченные шаги, и только они."""
    root = tree(tmp_path, **{"step-пример": MARKED, "step-молчун": PLAIN})
    assert module.steps(root) == ["пример"]


def test_a_marked_tool_that_is_not_a_step_is_not_called(tmp_path: Path) -> None:
    """Помечен бывает и не шаг — пакет, действие. Заготовку вызова он не даёт.

    Вторая половина: без неё заход сочинил бы `uses:` на файл, который звать
    нечем, и потребитель узнал бы об этом отказом у себя (045).
    """
    root = tree(tmp_path, **{"step-пример": MARKED})
    (root / "scripts" / "раздача.py").write_text('"""ОТДАЁТСЯ НАРУЖУ: не шаг."""\n', "utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    assert module.steps(root) == ["пример"]


def test_the_pin_is_the_release_tag_not_the_contract_version(tmp_path: Path) -> None:
    """Прибивка — тег ВЫПУСКА, а не версия поверхности: они разные.

    В дереве теста `CONTRACT_VERSION` — подделка из общей константы, а выпуск
    помечен `v2.5.0`.
    Прибивка к первому указала бы на тег, которого нет, и вызов отказал бы у
    потребителя — там, где чинить его некому.
    """
    root = tree(tmp_path, tagged="v2.5.0", **{"step-пример": MARKED})
    assert module.pin_of(root) == "v2.5.0"
    assert FAKE_VERSION not in module.pin_of(root)


def test_without_a_release_the_kit_refuses(tmp_path: Path) -> None:
    """Выпусков нет — прибиваться не к чему, и это отказ, а не подвижная метка.

    Метка меняла бы у потребителя исполняемый код без его ведома (152), а
    молчаливая подстановка `@main` сделала бы это незаметно.
    """
    root = tree(tmp_path, tagged="", **{"step-пример": MARKED})
    with pytest.raises(module.NotRun, match=module.NO_RELEASE):
        module.pin_of(root)


def test_the_check_name_is_composed(tmp_path: Path) -> None:
    """Имя записи составное — то, которое выдаст площадка."""
    assert module.check_name("lint") == f"lint{policy.COMPOSED}lint"


def test_the_answer_leaves_the_class_to_the_consumer(tmp_path: Path) -> None:
    """Класс проверки заход не решает: это свойство потребителя (174).

    И не молчит о нём: `unreviewed` — объявленная очередь разбора. Молча
    обязательной проверка не становится, и молча совещательной тоже.
    """
    said = module.answer(["lint", "debt"])
    assert f'"lint{policy.COMPOSED}lint": {policy.UNREVIEWED}' in said
    assert policy.REQUIRED not in said and policy.ADVISORY not in said


def test_the_caller_pins_and_never_floats(tmp_path: Path) -> None:
    """Заготовка вызова несёт версию, а не подвижную метку."""
    said = module.caller("lint", "o/r", "v2.5.0")
    assert "@v2.5.0" in said
    assert "@main" not in said and "@latest" not in said


def test_nothing_shipped_is_its_own_outcome(tmp_path: Path, run_script: RunScript) -> None:
    """Не помечено ничего — «отдавать нечего», а не пустая заготовка (075).

    Пустая заготовка читалась бы как «подключили и ничего не пришло»: снаружи
    она неотличима от успеха.
    """
    root = tree(tmp_path, **{"step-молчун": PLAIN})
    (root / "README.md").write_text("# П\n\n## брать пока нечего\n", encoding="utf-8")
    assert module.main(["--root", str(root)]) == module.EXIT_NOTHING


def test_a_tree_without_runs_does_not_run(tmp_path: Path) -> None:
    """Каталогов поиска нет — заход не отработал, а не «нечего отдавать»."""
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN


def test_the_kit_is_built_on_the_live_tree(run_script: RunScript) -> None:
    """Живое дерево: заход собирает заготовку и называет наши шаги (139)."""
    done = run_script("onboard.py")
    assert done.code == module.EXIT_OK, done.err or done.out
    assert "uses:" in done.out and "checks:" in done.out
    for name in module.steps(ROOT):
        assert f"step-{name}.yml@" in done.out, f"шаг «{name}» в заготовку не попал"
