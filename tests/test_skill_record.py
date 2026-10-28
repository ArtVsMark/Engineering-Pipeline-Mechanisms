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


def test_a_relative_workdir_with_a_foreign_root_lands_in_one_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--root` ≠ cwd и относительный `--workdir` — запись в ветку `root`, а не мимо (`c065808`)."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    work = tmp_path / "work"
    git = repo(work)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "начало"], check=True)
    subprocess.run([*git, "remote", "add", "origin", str(remote)], check=True)
    elsewhere = tmp_path / "в-стороне"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    record = {"pr": 9, "merged_at": "2026-10-28"}
    assert module.publish(record, Path("w"), root=work) is True
    shown = subprocess.run(
        ["git", "-C", str(remote), "show", f"badges:{module.RECORDS}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    assert json.loads(shown)["records"] == [record]


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
    # Подготовка до публикации — внутри того же бюджета (100): граница истории,
    # шапки навыков и ответ на коммите — по `READ`, разбор коммита — три `LOCAL`.
    read = module.skill_signals.READ
    prepare = (3 + len(TABLE)) * read + 3 * module.gitcall.LOCAL
    assert prepare < module.BUDGET, "подготовка записи не влезает в бюджет захода"


def test_a_publish_past_the_runs_deadline_does_not_start(tmp_path: Path) -> None:
    """Бюджет дан от входа захода и уже исчерпан — попытка не начинается (100)."""
    with pytest.raises(module.NotRun, match="бюджета"):
        module.publish({"pr": 1}, tmp_path, clock=lambda: 100.0, deadline=100.0)


def test_before_the_first_skill_line_nothing_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """До первой строки `Навык:` в истории `invoked` неизвестен — записи нет.

    Поздний взгляд на #1715: докстрока обещала это, а кода не было.
    """
    git = repo(tmp_path)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "гейт (#12)\n\nтело"], check=True)
    # Текущий каталог — чужая история: всё читается из `--root` (взгляд на #1724).
    monkeypatch.chdir(ROOT)
    assert module.named_skills_yet("HEAD", tmp_path) is False
    assert module.main(["--commit", "HEAD", "--root", str(tmp_path)]) == module.EXIT_OK
    assert "строки «Навык:» в истории ещё не было" in capsys.readouterr().out
    subprocess.run(
        [*git, "commit", "-q", "--allow-empty", "-m", "ещё (#13)\n\nНавык: build-a-gate"],
        check=True,
    )
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "после (#14)"], check=True)
    assert module.named_skills_yet("HEAD", tmp_path), "граница — предки, а не только сам коммит"


def test_a_broken_path_table_is_the_third_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Битый раздел `paths:` на коммите — исход 2 с причиной, а не трасса (#1715)."""
    git = repo(tmp_path)
    (tmp_path / ".pipeline.yml").write_text("paths:\n  нет-такого: x\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "гейт (#12)\n\nНавык: build-a-gate"], check=True)
    monkeypatch.chdir(tmp_path)
    assert module.main(["--commit", "HEAD", "--root", str(tmp_path)]) == module.EXIT_BROKEN


def test_a_commit_before_the_signals_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """У навыков на коммите ещё нет признаков — ожидание неизвестно, записи нет (#1715)."""
    git = repo(tmp_path)
    (tmp_path / ".claude" / "skills" / "x").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "x" / "SKILL.md").write_text("---\nname: x\n---\n", "utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "гейт (#12)\n\nНавык: x"], check=True)
    monkeypatch.chdir(tmp_path)
    assert module.main(["--commit", "HEAD", "--root", str(tmp_path)]) == module.EXIT_OK
    assert "признаков навыков на нём ещё не было" in capsys.readouterr().out
