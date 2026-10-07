"""Общий издатель фактов семьи: общая часть, слияние со своим и исходы (#1001, шаг 2).

Проверяется то, без чего общий шаг вернул бы разнобой, от которого заведён:
свой ключ проекта не перекрывает общего, у показателя договора есть значение
или причина, и наша сборка даёт те же факты, что общий шаг.
"""

import json
from pathlib import Path

import pytest

from tests.conftest import ROOT, RunScript, load_script

module = load_script("facts_common.py")
build = load_script("build_facts.py")

REPO = "Я/Проект"


def tree(root: Path) -> Path:
    """Минимальное дерево потребителя: только прогон CI, без тегов и без версии."""
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("jobs: {}\n", encoding="utf-8")
    return root


def test_a_consumer_without_its_own_numbers_gets_reasons_not_silence(tmp_path: Path) -> None:
    """Чего никто не дал — причина в `none` с именем того, кто должен: третьего нет (#1001)."""
    shared = module.common(tree(tmp_path), sha="голова", repo=REPO, ci_workflow="ci.yml")
    said = module.merge(shared, {})
    assert said["ci"] == {"workflow": "ci.yml"}
    for key in module.CONTRACT_METRICS:
        assert key in said or key in said["none"], f"у «{key}» ни значения, ни причины"
    assert said["none"]["tests"] == module.NOT_GIVEN
    assert said["none"]["python"] == module.NO_MATRIX


def test_an_own_key_does_not_override_a_common_one() -> None:
    """Свой генератор того же числа — отказ, а не перезапись (045)."""
    with pytest.raises(module.NotRun, match="перекрывает общие"):
        module.merge({"version": "1.2.3"}, {"version": "9.9.9"})


def test_a_value_and_a_reason_at_once_are_refused() -> None:
    """Значение и причина у одного показателя — два ответа сразу, а не один."""
    with pytest.raises(module.NotRun, match="и значение, и причина"):
        module.merge({}, {"tests": {"functions": 1}, "none": {"tests": "нет"}})


def test_an_own_section_and_an_own_reason_ride_along() -> None:
    """Своё проекта вливается: раздел сверх договора и своя причина в `none`."""
    said = module.merge({"repo": REPO}, {"rules": {"total": 1}, "none": {"checks_per_pr": "нет"}})
    assert said["rules"] == {"total": 1}
    assert said["none"]["checks_per_pr"] == "нет"


def test_a_named_matrix_is_read_and_a_bad_name_is_refused(tmp_path: Path) -> None:
    """Матрица называется «файл:джоб»; иная запись — отказ, а не угаданный джоб."""
    with pytest.raises(module.NotRun, match="файл прогона"):
        module.matrix_at(tmp_path, "ci.yml")
    run, none = module.ci_facts(ROOT, "ci.yml", build.OUR_MATRIX, build.OUR_NEXT)
    assert none == {} and run["python"] == build.python_facts()


def test_our_build_and_the_shared_step_give_the_same_facts(tmp_path: Path) -> None:
    """Наша сборка и общий шаг дают одни факты: источник общей части один (022)."""
    whole = build.collect(ROOT, "голова", mine=REPO)
    shared = module.common(
        ROOT,
        sha="голова",
        repo=REPO,
        ci_workflow="ci.yml",
        python_matrix=build.OUR_MATRIX,
        python_next=build.OUR_NEXT,
    )
    said = module.merge(shared, build.ours(ROOT, mine=REPO))
    for one in (whole, said):
        one.pop("generated_at")
    assert said == whole


def test_the_publisher_writes_the_file(tmp_path: Path, run_script: RunScript) -> None:
    """Исход 0: файл собран и лежит, где назван; свои числа влиты."""
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"tests": {"functions": 3}}), encoding="utf-8")
    out = tmp_path / "out" / "facts.json"
    done = run_script(
        "facts_common.py",
        "--root",
        str(tree(tmp_path / "дерево")),
        "--out",
        str(out),
        "--sha",
        "голова",
        "--repo",
        REPO,
        "--extra",
        str(extra),
    )
    assert done.code == module.EXIT_OK, done.text
    said = json.loads(out.read_text(encoding="utf-8"))
    assert said["tests"] == {"functions": 3} and said["repo"] == REPO


def test_the_publisher_refuses_an_overriding_file(tmp_path: Path, run_script: RunScript) -> None:
    """Исход 2: свой файл перекрывает общий ключ — фактов нет, причина названа."""
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"release": "9.9"}), encoding="utf-8")
    done = run_script(
        "facts_common.py",
        "--root",
        str(tree(tmp_path / "дерево")),
        "--out",
        str(tmp_path / "facts.json"),
        "--sha",
        "голова",
        "--repo",
        REPO,
        "--extra",
        str(extra),
    )
    assert done.code == module.EXIT_BROKEN, done.text
    assert "перекрывает" in done.text and not (tmp_path / "facts.json").exists()


def test_an_unread_own_file_is_refused(tmp_path: Path) -> None:
    """Свой файл не прочитан или не объект — отказ, а не пустое своё: не названо — пусто."""
    assert module.read_extra(None) == {}
    broken = tmp_path / "extra.json"
    broken.write_text("[1]", encoding="utf-8")
    with pytest.raises(module.NotRun, match="не объект"):
        module.read_extra(broken)
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(module.NotRun, match="не прочитан"):
        module.read_extra(broken)
