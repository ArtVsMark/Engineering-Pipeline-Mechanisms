"""Общий издатель фактов семьи: общая часть, слияние со своим и исходы (#1001, шаг 2).

Проверяется то, без чего общий шаг вернул бы разнобой, от которого заведён:
свой ключ проекта не перекрывает общего, у показателя договора есть значение
или причина, и наша сборка даёт те же факты, что общий шаг.
"""

import json
from pathlib import Path
from typing import Any

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
    # Файл — форма договора фактов (#1337, #1396): вторых записей в корне нет.
    assert said["schema"] == module.SCHEMA and not set(module.NOT_PUBLISHED) & set(said)


@pytest.mark.parametrize(
    ("supplier", "ours"),
    [(REPO, True), (REPO.upper(), True), ("Чужой/Поставщик", False), (None, False)],
    ids=["поставщик", "поставщик-иным-регистром", "чужой-поставщик", "поставщик-не-назван"],
)
def test_the_epm_topic_goes_only_to_the_supplier(
    tmp_path: Path, run_script: RunScript, supplier: str | None, ours: bool
) -> None:
    """Тема `epm` — только у поставщика: `--supplier` совпал с `--repo` (взгляд на #1345).

    Проверяется через CLI, а не через `published`: условие, подменённое на
    `True` или `False`, краснит здесь хотя бы один случай.
    """
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"family": {"read": True}}), encoding="utf-8")
    out = tmp_path / "facts.json"
    args = ["--root", str(tree(tmp_path / "дерево")), "--out", str(out), "--sha", "голова"]
    args += ["--repo", REPO, "--extra", str(extra)]
    if supplier is not None:
        args += ["--supplier", supplier]
    done = run_script("facts_common.py", *args)
    assert done.code == module.EXIT_OK, done.text
    said = json.loads(out.read_text(encoding="utf-8"))
    topics = said.get("exchange", {})
    assert ("epm" in topics) is ours, topics
    # Не поставщику его раздел остаётся его ключом в корне, а не уезжает в нашу тему.
    assert ("family" in said) is not ours, sorted(said)


def test_the_published_form_keeps_the_contract_at_the_root_and_the_rest_in_topics() -> None:
    """Корень — договор, своё — в `exchange.<тема>` со своей `schema`, без вторых записей."""
    flat = {
        "schema": module.SCHEMA,
        "repo": REPO,
        "coverage_percent": 93.1,
        "coverage": {"read": True},
        "version_whole": True,
        "family": {"read": False},
        "scripts": {"runnable": 1},
        "rules": {"total": 1},
        "manifest": {"gives": {}},
        "contract": "контракт",
    }
    said = module.published(flat, supplier=True)
    assert set(said) == {"schema", "repo", "coverage_percent", "exchange"}
    steps, epm = said["exchange"]["steps"], said["exchange"]["epm"]
    assert steps["schema"] == "1.0" and steps["coverage"] == {"read": True}
    assert steps["version_whole"] is True and epm["scripts"] == {"runnable": 1}
    lifted = module.lifted(said)
    assert {key: lifted[key] for key in ("coverage", "family", "scripts", "version_whole")} == {
        key: flat[key] for key in ("coverage", "family", "scripts", "version_whole")
    }


def test_a_consumer_keeps_its_own_sections_out_of_our_topic() -> None:
    """Свои `family`, `scripts`, `manifest` потребителя — его, а не наша тема (взгляд на #1345).

    Факты общего шага собирает каждый потребитель: под подписью «числа
    поставщика механизмов» его разделы были бы ложью, а вырезанными — потерей.
    """
    flat = {"schema": module.SCHEMA, "family": {"own": 1}, "manifest": {"m": 1}, "rules": {}}
    said = module.published(flat)
    assert said["family"] == {"own": 1} and said["manifest"] == {"m": 1}
    assert "epm" not in said.get("exchange", {}) and "rules" not in said


@pytest.mark.parametrize("exchange", [[], "тема", None])
def test_an_exchange_of_a_wrong_shape_lifts_nothing(exchange: object) -> None:
    """`exchange` не объектом — поднимать нечего, а не трейсбек (взгляд на #1345)."""
    assert module.lifted({"repo": REPO, "exchange": exchange}) == {"repo": REPO}


def test_a_topic_of_another_major_is_not_lifted() -> None:
    """Тема чужого мажора в корень не поднимается: её форму мы не знаем (#1337)."""
    said = {"exchange": {"epm": {"schema": "2.0", "scripts": {"runnable": 9}}}}
    assert "scripts" not in module.lifted(said)


def test_drawing_takes_the_unpublished_from_the_tree() -> None:
    """Неопубликованное рисующий берёт из дерева тем же кодом, а не второй записью (#1337)."""
    said = build.rehydrated({"repo": REPO}, ROOT, REPO)
    assert said["rules"] == module.rules_said(ROOT, REPO)
    assert said["manifest"] == build.manifest_facts(ROOT)


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
            # Машинный ответ без происхождения — «не названо» (вид из канона, #1566).
            "005": {"status": "active", "mechanism": "gate"},
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
    machine = sum(said["by_mechanism"][kind] for kind in module.kinds.MACHINE)
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


# --- сверка с договором семьи по тегу (#1337, #1396) -------------------------


def contract_step() -> dict[str, Any]:
    """Шаг общего шага фактов, сверяющий файл проверкой витрины с её выпуска."""
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "step-facts.yml").read_text("utf-8"))
    return next(
        one
        for job in flow["jobs"].values()
        for one in job.get("steps", [])
        if "check_facts.py" in str(one.get("run") or "")
    )


def test_the_contract_tag_matches_the_schema_and_the_step() -> None:
    """Тег проверки, номер формы и тег в шаге — один договор, а не три записи (#1337).

    Номер формы отстаёт от тега ровно на объявленный переезд (#1396): мажор
    формы — `SCHEMA_LAGS_TO`, и только пока он объявлен. Без него форма и тег
    обязаны совпасть до минора.
    """
    tag = module.CONTRACT_TAG
    assert tag.startswith("facts-v")
    said = tag.removeprefix("facts-v")
    major = module.SCHEMA.split(".")[0]
    # ОБЪЯВЛЕННЫЙ ПЕРЕЕЗД СНИМАЕТСЯ С ПОДЪЁМОМ (находка `6d5a560`): мажор формы
    # ушёл с объявленного — константа обязана уйти, а не остаться зелёной.
    assert module.SCHEMA_LAGS_TO in {"", major}, (
        f"SCHEMA_LAGS_TO = {module.SCHEMA_LAGS_TO!r}, а мажор формы уже {major} — снимите переезд"
    )
    if major == module.SCHEMA_LAGS_TO:
        # Переезд: мажор тега — ровно следующий за мажором формы (взгляд на #1442).
        assert said.split(".")[0] == str(int(module.SCHEMA_LAGS_TO) + 1), (tag, module.SCHEMA)
    else:
        assert said.startswith(f"{module.SCHEMA}."), (tag, module.SCHEMA)
    assert contract_step()["env"]["FACTS_CONTRACT"] == tag


#: Строка, которой `check_facts.py --file` выпуска называет расхождения:
#: `print(f"{args.repo}: {'договору отвечает' if not found else f'расхождений {len(found)}'}")`
#: (тег `facts-v2.1.0` механизмов — строка та же, что у `facts-v2.0.0` каталога).
#: Шаг судит по ней, а не по одному коду.
MISMATCH: str = "o/a: расхождений 3"


@pytest.mark.parametrize(
    ("fetched", "intact", "code", "said", "stops"),
    [
        (True, True, 0, "o/a: договору отвечает", False),
        (True, True, 1, MISMATCH, True),
        (True, True, 1, "Traceback (most recent call last):", False),
        (True, True, 2, "проверка не отработала", False),
        (False, True, 0, "", False),
        (True, False, 0, "o/a: договору отвечает", True),
    ],
    ids=["отвечает", "расхождения", "трассировка", "не-отработала", "не-скачан", "хеш-не-тот"],
)
def test_the_contract_step_stops_only_on_a_mismatch_or_a_foreign_file(
    tmp_path: Path, fetched: bool, intact: bool, code: int, said: str, stops: bool
) -> None:
    """Останавливают расхождения и чужой файл; трассировка и недоступный выпуск — предупреждение.

    Код 1 даёт и трассировка Python (взгляд на #1348): вердикт — строка
    проверки, а не один код. Файл выпуска исполняется только по хешу.
    """
    import hashlib
    import os
    import subprocess

    run = str(contract_step()["run"])
    fake = tmp_path / "bin"
    fake.mkdir()
    body = "файл выпуска"
    (fake / "curl").write_text(
        "#!/bin/sh\n"
        + (
            'while [ "$#" -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
            f"printf %s '{body}' > \"$out\"\n"
            if fetched
            else "exit 22\n"
        ),
        encoding="utf-8",
    )
    (fake / "python").write_text(f"#!/bin/sh\necho '{said}'\nexit {code}\n", encoding="utf-8")
    for one in fake.iterdir():
        one.chmod(0o755)
    digest = hashlib.sha256(body.encode()).hexdigest() if intact else "0" * 64
    pinned = "\n".join(
        f"{digest}  {name}" for name in ("check_facts.py", "facts.schema.json", "facts.version")
    )
    done = subprocess.run(
        ["bash", "-c", run],
        env={
            **os.environ,
            "PATH": f"{fake}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "FACTS_CONTRACT": module.CONTRACT_TAG,
            "FACTS_SHA256": pinned,
            "RELEASES": "https://example.invalid",
            "GITHUB_REPOSITORY": "o/a",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert (done.returncode != 0) is stops, done.stdout + done.stderr
    if not stops and (code or not fetched):
        assert "::warning::" in done.stdout


def test_every_release_file_is_pinned_by_its_hash() -> None:
    """Каждый скачиваемый файл выпуска прибит sha256 — чужой код не исполняется без сверки."""
    import re

    step = contract_step()
    pinned: dict[str, str] = {}
    for line in str(step["env"]["FACTS_SHA256"]).splitlines():
        if line:
            digest, name = line.split("  ", 1)
            pinned[name] = digest
    fetched = re.search(r"for f in ([^;]+); do", str(step["run"]))
    assert fetched, "шаг больше не перечисляет файлы выпуска — сверять нечего"
    assert set(pinned) == set(fetched.group(1).split())
    assert all(re.fullmatch(r"[0-9a-f]{64}", one) for one in pinned.values())


def test_the_answer_path_comes_from_the_table(tmp_path: Path) -> None:
    """Адрес ответа каталогу — по таблице путей дерева; битый раздел — отказ (#1632)."""
    root = tree(tmp_path)
    assert module.answer_path(root) == module.paths.BINDINGS
    (root / ".pipeline.yml").write_text("paths:\n  bindings: cfg/a.json\n", encoding="utf-8")
    assert module.answer_path(root) == Path("cfg/a.json")
    (root / ".pipeline.yml").write_text("paths:\n  bindings: ../a.json\n", encoding="utf-8")
    with pytest.raises(module.NotRun, match="вне дерева"):
        module.answer_path(root)
    assert module.rules_said(root)["read"] is False


def test_ours_reads_the_answer_where_the_table_puts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build_facts.ours` берёт ответ каталогу по таблице путей; битая — отказ (`8ea4930`)."""

    class Read(Exception):
        """Ответ прочитан — дальше сборка не нужна."""

    seen: list[Path] = []

    def answer(path: Path, *_: object, **__: object) -> dict[str, Any]:
        seen.append(path)
        raise Read

    monkeypatch.setattr(build, "rules_facts", answer)
    (tmp_path / ".pipeline.yml").write_text("paths:\n  bindings: cfg/answer.json\n", "utf-8")
    with pytest.raises(Read):
        build.ours(tmp_path)
    assert seen == [tmp_path / "cfg" / "answer.json"]
    (tmp_path / ".pipeline.yml").write_text("paths:\n  bindings: /abs.json\n", "utf-8")
    with pytest.raises(build.NotRun, match="вне дерева"):
        build.ours(tmp_path)
    assert len(seen) == 1, "битая таблица дошла до чтения ответа"
