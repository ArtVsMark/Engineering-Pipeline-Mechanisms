"""Шаг тестов `ci.yml` на изменении гонит выбор классификатора (#1598).

Блок шага исполняется настоящим bash с подделанными `scope.py` и `pytest`:
проверяется то, что прогон сделает, а не то, что в блоке написано (подстрока
текста команды — род находки «подстрока вместо отношения»).
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.conftest import ROOT, load_script

#: Имя шага тестов в джобе матрицы.
STEP = "тесты"


def step_block() -> str:
    """Блок шага тестов матрицы, как его исполнит прогон."""
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    (step,) = [one for one in flow["jobs"]["test-matrix"]["steps"] if one.get("name") == STEP]
    return str(step["run"])


def run_block(
    tmp_path: Path, event: str, said: str, code: int = 0
) -> subprocess.CompletedProcess[str]:
    """Исполняет блок: `scope.py` отвечает `said` с кодом `code`, pytest пишет доводы."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "said.txt").write_text(said, encoding="utf-8")
    python = bin_dir / "python"
    python.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = scripts/scope.py ] && [ "${2:-}" = --tests ]; then\n'
        f'  cat "{tmp_path}/said.txt"; exit {code}\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    pytest_bin = bin_dir / "pytest"
    pytest_bin.write_text(f'#!/bin/bash\necho "$@" > "{tmp_path}/args.txt"\n', encoding="utf-8")
    for one in (python, pytest_bin):
        one.chmod(one.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_EVENT_NAME": event,
        "RANDOM_SEED": "1",
    }
    return subprocess.run(
        ["bash", "-c", step_block()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def args_of(tmp_path: Path) -> list[str] | None:
    """Доводы, с которыми позван pytest; не позван — None."""
    path = tmp_path / "args.txt"
    return path.read_text(encoding="utf-8").split() if path.exists() else None


def test_a_change_runs_the_chosen_files(tmp_path: Path) -> None:
    """На изменении pytest получает выбранные тест-файлы."""
    done = run_block(tmp_path, "pull_request", "tests/test_a.py\ntests/test_b.py\n")
    assert done.returncode == 0, done.stderr
    args = args_of(tmp_path)
    assert args is not None, "pytest не зван"
    assert args[-2:] == ["tests/test_a.py", "tests/test_b.py"]


@pytest.mark.parametrize(
    ("event", "said", "code"),
    [
        ("push", "tests/test_a.py\n", 0),
        ("pull_request", "ALL\n", 0),
        ("pull_request", "", 2),
    ],
    ids=["общая ветка", "классификатор: всё", "классификатор отказал"],
)
def test_the_whole_set_runs_where_it_must(tmp_path: Path, event: str, said: str, code: int) -> None:
    """Общая ветка, ответ «всё» и отказ классификатора — полный набор, без файлов."""
    done = run_block(tmp_path, event, said, code)
    assert done.returncode == 0, done.stderr
    assert args_of(tmp_path) == [
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "--randomly-seed=1",
    ]
    if code:
        assert "полный набор" in done.stdout


def test_nothing_touched_is_a_verdict_not_a_run(tmp_path: Path) -> None:
    """Изменение не задело ни одного теста — «судить нечего», pytest не зван, исход зелёный."""
    done = run_block(tmp_path, "pull_request", "")
    assert done.returncode == 0, done.stderr
    assert "судить нечего" in done.stdout
    assert args_of(tmp_path) is None


def test_a_consumer_keeps_the_whole_set() -> None:
    """Общие шаги, которые зовёт потребитель, выбора не делают: его набор прежний (#1598).

    Семейство `test` потребителю не отдаётся (`docs/use/onboarding.md`), и выбор
    живёт в нашем `ci.yml`; до настройки областей (#1600) общий шаг его не берёт.
    """
    shared = sorted((ROOT / ".github" / "workflows").glob("step-*.yml"))
    assert shared, "общих шагов не найдено — гейт ничего не проверил (075)"
    taking = [one.name for one in shared if "scope.py" in one.read_text(encoding="utf-8")]
    assert not taking, f"общий шаг берёт выбор тестов до настройки потребителя: {taking}"


def test_nothing_to_judge_is_counted_and_a_skip_is_not(tmp_path: Path) -> None:
    """«Судить нечего» даёт `success`, и `ci-complete` его засчитывает; `skipped` — нет (#1599).

    Потому пропуск и оформлен вердиктом, а не `if:` у джоба: пропущенный
    обязательный джоб сводный гейт объявляет отказом (187).
    """
    ci_complete = load_script("ci_complete.py")
    done = run_block(tmp_path, "pull_request", "")
    conclusion = "success" if done.returncode == 0 else "failure"
    head = [{"name": "test-matrix", "status": "completed", "conclusion": conclusion}]
    assert ci_complete.verdict(head, ["test-matrix"], "ci-complete") == ([], False)
    skipped = [{"name": "test-matrix", "status": "completed", "conclusion": "skipped"}]
    problems, _ = ci_complete.verdict(skipped, ["test-matrix"], "ci-complete")
    assert problems
