"""Сырая запись о слитом изменении: ждали — вызван, на ветку `badges` поверх (#1694).

Проверяется на настоящем репозитории: запись выводится из уплотнённого коммита,
не уплотнение — «записывать нечего», вторая запись того же изменения не
пишется, а файл чужой формы — отказ, а не начало ряда заново (045).
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.conftest import ROOT, RunScript, load_script

module = load_script("skill_record.py")
TABLE = module.skill_signals.signals(ROOT)


def repo(tmp_path: Path) -> list[str]:
    """Пустой репозиторий с подписью; отдаёт приставку вызова git."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    return ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(tmp_path)]


def test_a_merged_change_becomes_a_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пути, ожидание по признакам и вызовы из строки `Навык:` — одной записью."""
    git = repo(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_x.py").write_text("x\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    body = "гейт (#12)\n\nРазобрано: abc1234\n\nНавык: build-a-gate\n"
    subprocess.run([*git, "commit", "-q", "-m", body], check=True)
    monkeypatch.chdir(tmp_path)
    said = module.record_of("HEAD", TABLE)
    assert said is not None and said["pr"] == 12
    assert said["added"] == ["scripts/check_x.py"] == said["touched"]
    assert {"build-a-gate", "close-a-finding"} <= set(said["expected"])
    assert said["invoked"] == ["build-a-gate"] and said["source"] == module.SOURCE


def test_a_commit_that_is_not_a_merged_change_is_not_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без «(#N)» в заголовке — не уплотнение изменения: записывать нечего, а не отказ."""
    git = repo(tmp_path)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "прямой коммит"], check=True)
    monkeypatch.chdir(tmp_path)
    assert module.record_of("HEAD", TABLE) is None


def test_the_store_grows_once_per_change_and_refuses_a_foreign_form() -> None:
    """Дописывается; та же запись второй раз — нет; чужая форма — отказ, а не новый ряд."""
    record = {"pr": 7}
    first = module.merged(None, record)
    assert first == {"schema": module.SCHEMA, "records": [record]}
    assert module.merged(first, {"pr": 7, "invoked": ["x"]}) is None
    with pytest.raises(module.NotRun, match="форма"):
        module.merged({"schema": 99, "records": []}, record)
    with pytest.raises(module.NotRun, match="records"):
        module.merged({"schema": module.SCHEMA, "records": {}}, record)


def test_publish_lays_the_record_on_top_of_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись ложится на ветку `badges` поверх, без `--force`; повтор того же — «уже есть»."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    work = tmp_path / "work"
    git = repo(work)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "начало"], check=True)
    subprocess.run([*git, "remote", "add", "origin", str(remote)], check=True)
    monkeypatch.chdir(work)
    record = {"pr": 5, "merged_at": "2026-10-26"}
    assert module.publish(record, tmp_path / "w1") is True
    shown = subprocess.run(
        ["git", "-C", str(remote), "show", f"badges:{module.RECORDS}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    assert json.loads(shown)["records"] == [record]
    assert module.publish(record, tmp_path / "w2") is False


def test_main_prints_the_record_without_a_workdir(run_script: RunScript) -> None:
    """Без `--workdir` — сухой заход: запись печатается, ветка не трогается; исход 0."""
    run = run_script("skill_record.py", "--commit", "HEAD", "--root", str(ROOT))
    assert run.code == module.EXIT_OK, run.text


def test_a_broken_commit_is_the_third_outcome(run_script: RunScript) -> None:
    """Коммит не читается — исход 2 с причиной, а не «записывать нечего» (039)."""
    run = run_script("skill_record.py", "--commit", "нет-такого", "--root", str(ROOT))
    assert run.code == module.EXIT_BROKEN and "не собрана" in run.text


def test_a_retry_starts_only_within_the_budget(tmp_path: Path) -> None:
    """Попытка, чей худший случай не влезает в остаток бюджета, не начинается (100)."""
    ticks = iter([0.0, module.BUDGET - module.ATTEMPT_WORST + 1])
    with pytest.raises(module.NotRun, match="бюджета"):
        module.publish({"pr": 1}, tmp_path, clock=lambda: next(ticks))


def test_the_budget_fits_under_the_job_limit() -> None:
    """Бюджет попыток меньше предела джоба шага — иначе площадка оборвёт толчок."""
    step = yaml.safe_load((ROOT / ".github" / "workflows" / "step-skills.yml").read_text("utf-8"))
    assert step["jobs"]["skills"]["timeout-minutes"] * 60 > module.BUDGET
    assert module.ATTEMPT_WORST <= module.BUDGET, "в бюджет не влезает и одна попытка"
