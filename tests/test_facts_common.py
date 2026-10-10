"""Общий издатель фактов семьи: общая часть, слияние со своим и исходы (#1001, шаг 2).

Проверяется то, без чего общий шаг вернул бы разнобой, от которого заведён:
свой ключ проекта не перекрывает общего, у показателя договора есть значение
или причина, и наша сборка даёт те же факты, что общий шаг.
"""

import json
from pathlib import Path

import pytest
import yaml

from tests.conftest import ROOT, RunScript, load_script

module = load_script("facts_common.py")
build = load_script("build_facts.py")

REPO = "Я/Проект"
#: Поставщик кода конвейера — входом, как общий шаг даёт его из `job.workflow_repository`.
SUPPLIER = "Я/Поставщик"


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
    said = module.merge({"repo": REPO}, {"contract": "1.0", "none": {"checks_per_pr": "нет"}})
    assert said["contract"] == "1.0"
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
        # У нас шаг зовётся из нашего же репозитория: поставщик — мы сами.
        supplier=REPO,
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


# --- ответ каталогу: общий показатель с происхождением (#1282) ---------------


def answer(root: Path, rules: dict[str, dict[str, str]]) -> Path:
    """Посадить ответ каталогу `.rules/bindings.json` в дерево."""
    path = root / ".rules" / "bindings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8")
    return path


def test_machine_answers_are_split_by_origin(tmp_path: Path) -> None:
    """Машинные ответы — свои, взятые у поставщика и взятые у других; документ — ни то ни другое.

    Имя поставщика сравнивается без регистра: площадка его не различает. Сумма
    трёх чисел — все машинные ответы, иначе пропажа одного была бы не видна.
    """
    supplier = SUPPLIER.lower()
    planted = answer(
        tmp_path,
        {
            "001": {"status": "active", "mechanism": "gate", "origin_kind": "own"},
            "002": {
                "status": "active",
                "mechanism": "pipeline",
                "origin_kind": "called",
                "origin": f"{supplier}:.github/workflows/step-x.yml@v1.4.0",
            },
            "003": {
                "status": "active",
                "mechanism": "gate",
                "origin_kind": "copied",
                "origin": f"{SUPPLIER}:scripts/check_x.py@v1.4.0",
            },
            "004": {
                "status": "active",
                "mechanism": "pipeline",
                "origin_kind": "called",
                "origin": "Другой/Каталог:action.yml@v1.0.0",
            },
            "005": {"status": "active", "mechanism": "code"},
            "006": {"status": "active", "mechanism": "document", "origin": "x"},
            "007": {"status": "not-applicable"},
        },
    )
    said = module.rules_facts(planted, SUPPLIER)
    assert said["read"] is True
    assert said["machine"] == {
        "own": 2,
        "taken": 2,
        "elsewhere": 1,
        "by_origin_kind": {"called": 2, "copied": 1, "own": 1, module.UNNAMED_KIND: 1},
    }
    machine = sum(said["by_mechanism"][kind] for kind in ("gate", "pipeline", "code"))
    assert sum(said["machine"][key] for key in ("own", "taken", "elsewhere")) == machine
    # Поставщик не назван — взятое у него от взятого у других не отличить:
    # разбивка говорит «не прочитано», а не кладёт всё в «других».
    unnamed = module.rules_facts(planted)
    assert unnamed["machine"] == {"read": False, "why": module.NO_SUPPLIER}
    assert unnamed["by_mechanism"] == said["by_mechanism"]


def test_a_namesake_prefix_is_not_the_supplier() -> None:
    """Поставщик — имя целиком до двоеточия, а не начало строки: тёзка с хвостом — не мы."""
    assert module.taken_from(f"{SUPPLIER.upper()}:x.py@v1", SUPPLIER)
    assert not module.taken_from(f"{SUPPLIER}-fork:x.py@v1", SUPPLIER)
    assert not module.taken_from(f"Чужой/{SUPPLIER}:x.py@v1", SUPPLIER)


def test_a_consumer_without_an_answer_says_unread_not_zero(tmp_path: Path) -> None:
    """Нет ответа каталогу — раздел говорит «не прочитано» своей формой, а не нулём и не отказом.

    В `none` причину не положить: ключи `none` схема витрины перечисляет
    закрытым списком, и `rules` в нём нет.
    """
    shared = module.common(tree(tmp_path), sha="голова", repo=REPO, ci_workflow="ci.yml")
    assert shared["rules"]["read"] is False
    assert "нет ответа каталогу" in shared["rules"]["why"]
    assert "rules" not in shared.get("none", {})
    answer(tmp_path, {"001": {"status": "active", "mechanism": "gate"}})
    said = module.common(
        tmp_path, sha="голова", repo=REPO, ci_workflow="ci.yml", supplier=SUPPLIER
    )["rules"]
    assert said["read"] is True
    assert said["machine"]["own"] == 1
    # Тот же исход — у самого разбора, которым общая часть его берёт.
    assert module.rules_said(tmp_path, SUPPLIER) == said
    (tmp_path / ".rules" / "bindings.json").write_text("{ не json", encoding="utf-8")
    assert module.rules_said(tmp_path)["read"] is False


def test_the_shared_step_names_the_supplier_it_checked_out() -> None:
    """Шаг даёт издателю поставщика — того, чей код он выкачал, а не имя буквами (#1282).

    Без входа разбивка «свои/взяты» у каждого потребителя молча стала бы
    «не прочитано»: исход честный, но работа шага потеряна, и красным это не
    стало бы нигде.
    """
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "step-facts.yml").read_text("utf-8"))
    steps = [one for job in flow["jobs"].values() for one in job.get("steps", [])]
    made = [one for one in steps if "facts_common.py" in str(one.get("run", ""))]
    assert len(made) == 1, "шаг сборки фактов не найден — сверять нечего (075)"
    assert made[0]["env"]["SUPPLIER"] == "${{ job.workflow_repository }}"
    assert '--supplier "$SUPPLIER"' in made[0]["run"]
