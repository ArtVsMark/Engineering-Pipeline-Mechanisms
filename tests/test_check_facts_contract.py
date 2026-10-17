"""Гейт сверки фактов с выпуском витрины: жива ли сверка до слияния (#1380).

Сам шаг исполняется гейтом по-настоящему, с сетью, — на площадке. Здесь сети
нет, и набор держит то, что от неё не зависит: где гейт берёт шаг, когда он
идёт, как судит два захода и чем отличает отказ канала от неверного тега.
"""

import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, load_script

module = load_script("check_facts_contract.py")

GOOD = (0, "o/a: договору отвечает\n")
CAUGHT = (1, f"{module.STRANGER}: расхождений 1\n")


def test_the_gate_finds_exactly_one_contract_step_in_the_tree() -> None:
    """Шаг сверки в `step-facts.yml` один и несёт тег, адрес выпуска и хеши."""
    step = module.contract_step(module.pipeline_checks.run_of(ROOT / module.FLOW))
    assert set(step["env"]) >= {"FACTS_CONTRACT", "RELEASES", "FACTS_SHA256"}


@pytest.mark.parametrize("copies", [0, 2], ids=["шага-нет", "шагов-два"])
def test_no_single_contract_step_is_the_third_outcome(copies: int) -> None:
    """Нет шага сверки или их два — «не отработал», а не «чисто» (075)."""
    step = '      - name: сверка\n        run: python "$dir/check_facts.py"\n'
    flow = "jobs:\n  facts:\n    steps:\n" + step * copies
    with pytest.raises(module.NotRun):
        module.contract_step(yaml.safe_load(flow))


@pytest.mark.parametrize(
    ("good", "stranger", "missing", "code"),
    [
        (GOOD, CAUGHT, False, 0),
        ((1, "::error::Файлы выпуска не сходятся с прибитыми хешами"), CAUGHT, False, 1),
        ((0, "::warning::Факты не сверены: проверка не отработала"), CAUGHT, False, 1),
        (GOOD, (0, "::warning::проверка не отработала"), False, 1),
        (GOOD, (1, "Traceback (most recent call last):"), False, 1),
        ((0, "::warning::check_facts.py выпуска не скачан"), CAUGHT, False, 4),
        ((0, "::warning::check_facts.py выпуска не скачан"), CAUGHT, True, 1),
        (GOOD, (0, "::warning::check_facts.py выпуска не скачан"), False, 4),
        (GOOD, (0, "::warning::check_facts.py выпуска не скачан"), True, 1),
        (
            (1, "::error::Файлы выпуска не сходятся с прибитыми хешами"),
            (0, "::warning::check_facts.py выпуска не скачан"),
            False,
            1,
        ),
        ((module.STEP_TIMED_OUT, "шаг не уложился в дедлайн 300 с"), CAUGHT, False, 4),
        (GOOD, (module.STEP_TIMED_OUT, "шаг не уложился в дедлайн 300 с"), False, 4),
        (
            (1, "::error::Файлы выпуска не сходятся с прибитыми хешами"),
            (module.STEP_TIMED_OUT, "шаг не уложился в дедлайн 300 с"),
            False,
            1,
        ),
    ],
    ids=[
        "сверка-жива",
        "хеш-не-тот",
        "мертва-на-годных",
        "расхождение-не-остановило",
        "код-1-без-строки",
        "канал-молчит",
        "тега-нет",
        "канал-молчит-на-втором",
        "тега-нет-на-втором",
        "мёртвая-на-годных-при-молчании-второго",
        "дедлайн-на-годных",
        "дедлайн-на-втором",
        "мёртвая-на-годных-при-дедлайне-второго",
    ],
)
def test_the_verdict_names_a_dead_check(
    good: tuple[int, str], stranger: tuple[int, str], missing: bool, code: int
) -> None:
    """Жива — только когда годное прошло, а расхождение остановило шаг своей строкой.

    Отказ канала судится по ОБОИМ заходам: сеть, отказавшая на втором, — тоже
    молчание канала, а не «сверка мертва» (взгляд на #1391).
    """
    assert module.verdict(good, stranger, lambda named: missing)[0] == code


def test_the_probe_asks_for_the_file_of_the_pass_that_failed() -> None:
    """Проба спрашивает файл, названный тем заходом, который его не скачал."""
    asked: list[str] = []
    second = (0, "::warning::Факты не сверены: facts.schema.json выпуска facts-v1.6.0 не скачан")

    def probe(named: str) -> bool:
        asked.append(named)
        return False

    module.verdict(GOOD, second, probe)
    assert asked == ["facts.schema.json"]


def test_the_gate_subject_follows_its_own_imports() -> None:
    """Модули самого гейта — предмет: правка разбора 404 у пробы должна его звать."""
    assert "packages/transport/ghrest.py" in module.subject(ROOT)


def test_a_dead_check_is_a_refusal_of_the_whole_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заход гейта целиком: шаг остановил годные факты — отказ гейта, а не «чисто»."""
    said: list[str] = []

    def stopped(step: dict[str, Any], temp: Path, repo: str) -> tuple[int, str]:
        said.append(repo)
        return 1, "::error::Файлы выпуска facts-v1.6.0 не сходятся с прибитыми хешами"

    monkeypatch.setattr(module, "run_step", stopped)
    assert module.main(["--root", str(ROOT), "--repo", "o/a"]) == module.EXIT_FOUND
    assert said == ["o/a", module.STRANGER], "заходов не два или имена не те"


def test_without_a_name_the_gate_does_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Имени проекта нет — «не отработал»: собрать факты и сверить их не на чем."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert module.main(["--root", str(ROOT), "--repo", ""]) == module.EXIT_BROKEN


def git(cwd: Path, *args: str) -> None:
    """Зовёт git в подготовленном репозитории теста."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.mark.parametrize(
    ("path", "touches"),
    [
        (".github/workflows/step-facts.yml", True),
        ("scripts/facts_common.py", True),
        ("scripts/facts.py", False),
        ("README.md", False),
    ],
    ids=["шаг", "сборка-фактов", "сосед-по-имени", "чужой-файл"],
)
def test_the_gate_runs_only_on_its_subject(tmp_path: Path, path: str, touches: bool) -> None:
    """С базой гейт идёт, только если тронут шаг или сборка фактов, — иначе сеть на всё."""
    git(tmp_path, "init", "--quiet", "--initial-branch=main")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "x").write_text("x\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "--quiet", "-m", "база")
    git(tmp_path, "checkout", "--quiet", "-b", "work")
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    # Прогон — разбираемый: гейт читает прогоны дерева, и битый был бы отказом.
    target.write_text("jobs: {}\n" if path.endswith(".yml") else "правка\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "--quiet", "-m", "правка")
    assert module.touched("main", tmp_path) is touches


@pytest.mark.parametrize(
    ("raised", "missing"),
    [
        (urllib.error.HTTPError("u", 404, "Not Found", {}, None), True),  # type: ignore[arg-type]
        (urllib.error.HTTPError("u", 503, "Unavailable", {}, None), False),  # type: ignore[arg-type]
        (urllib.error.URLError("нет сети"), False),
        (None, False),
    ],
    ids=["404", "503", "сети-нет", "выпуск-есть"],
)
def test_only_a_404_says_the_tag_is_wrong(
    monkeypatch: pytest.MonkeyPatch, raised: Exception | None, missing: bool
) -> None:
    """«Нет такого» — находка о дереве; любой другой отказ — молчание канала (084)."""

    def fetch(url: str, timeout: int = 30) -> str:
        if raised is None:
            return "1\n"
        raise module.ghrest.TransportError(f"снимок не прочитан ({url})") from raised

    monkeypatch.setattr(module.ghrest, "raw_text", fetch)
    step = {"env": {"RELEASES": "https://example.invalid", "FACTS_CONTRACT": "facts-v0.0.0"}}
    assert module.release_missing(step) is missing


def whole_run(monkeypatch: pytest.MonkeyPatch, said: tuple[int, str]) -> int:
    """Заход гейта целиком: годный заход отвечает `said`, чужой — ловит расхождение."""

    def step(one: dict[str, Any], temp: Path, repo: str) -> tuple[int, str]:
        return CAUGHT if repo == module.STRANGER else said

    monkeypatch.setattr(module, "run_step", step)
    monkeypatch.setattr(module, "release_missing", lambda one, named=module.PROBED: False)
    return int(module.main(["--root", str(ROOT), "--repo", "o/a"]))


def test_a_whole_run_names_a_live_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Годное прошло, расхождение остановило шаг — сверка жива, исход 0."""
    assert whole_run(monkeypatch, GOOD) == module.EXIT_OK


def test_a_whole_run_names_a_silent_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Выпуск не скачан, а тег есть — 4: молчание канала названо предупреждением (045)."""
    unfetched = (0, "::warning::check_facts.py выпуска не скачан")
    assert whole_run(monkeypatch, unfetched) == module.EXIT_SILENT


def test_an_untouched_subject_is_clean_without_the_network(tmp_path: Path) -> None:
    """Предмет не тронут — 0 без единого захода шага: сеть не оплачивается зря."""
    git(tmp_path, "init", "--quiet", "--initial-branch=main")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "x").write_text("x\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "--quiet", "-m", "база")
    assert module.main(["--root", str(tmp_path), "--base", "main", "--repo", "o/a"]) == 0


def test_the_step_runs_as_the_platform_runs_it(tmp_path: Path) -> None:
    """Шаг идёт в `bash` с его `env`, своим `RUNNER_TEMP` и именем проекта — как на площадке."""
    step = {
        "env": {"FACTS_CONTRACT": "facts-v0.0.0"},
        "run": 'echo "$FACTS_CONTRACT $GITHUB_REPOSITORY $RUNNER_TEMP"; exit 3',
    }
    code, said = module.run_step(step, tmp_path, "o/a")
    assert code == 3
    assert said.strip() == f"facts-v0.0.0 o/a {tmp_path}"


def test_a_step_past_its_deadline_is_its_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Истёкший дедлайн — код `STEP_TIMED_OUT` с названной причиной (находка `c91b22a`)."""

    def hung(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 300, output=b"half")

    monkeypatch.setattr(module.subprocess, "run", hung)
    code, said = module.run_step({"run": "true"}, tmp_path, "o/a")
    assert code == module.STEP_TIMED_OUT
    assert "не уложился в дедлайн 300 с" in said


def test_a_step_that_does_not_start_is_not_a_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`OSError` — гейт не отработал (2), а не «не уложился» (находка `673fef5`)."""

    def absent(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("bash")

    monkeypatch.setattr(module.subprocess, "run", absent)
    with pytest.raises(module.NotRun, match="не запустился"):
        module.run_step({"run": "true"}, tmp_path, "o/a")


def test_the_subject_is_read_from_the_tree() -> None:
    """Предмет — по дереву: гейт, его прогон, вызывающий шага и модули сборки (взгляд на #1391)."""
    found = module.subject(ROOT)
    expected = {
        module.FLOW.as_posix(),
        "scripts/check_facts_contract.py",
        "scripts/facts_common.py",
        "scripts/kinds.py",
        "scripts/version.py",
        ".github/workflows/badges.yml",
        ".github/workflows/ci.yml",
    }
    assert expected <= found, f"нет в предмете: {sorted(expected - found)}"
    assert "scripts/facts.py" not in found


def test_the_facts_are_built_with_the_callers_inputs() -> None:
    """Сборка получает файл CI и матрицы из `with:` вызывающего — как публикация."""
    args = module.build_args(ROOT)
    given = dict(zip(args[::2], args[1::2], strict=True))
    assert set(given) == set(module.BUILD_INPUTS.values())
    assert given["--python-matrix"], "матрица не передана — витрина её не увидит"


def test_no_single_caller_is_the_third_outcome(tmp_path: Path) -> None:
    """Вызывающего шага нет — «не отработал»: с какими аргументами собирать, неизвестно."""
    (tmp_path / module.paths.WORKFLOWS).mkdir(parents=True)
    with pytest.raises(module.NotRun):
        module.build_args(tmp_path)


def test_the_probe_asks_for_the_file_the_step_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проба спрашивает тот файл, который назвало предупреждение, а не любой (взгляд на #1391)."""
    asked: list[str] = []

    def probe(step: dict[str, Any], named: str = module.PROBED) -> bool:
        asked.append(named)
        return True

    def step(one: dict[str, Any], temp: Path, repo: str) -> tuple[int, str]:
        return 0, "::warning::Факты не сверены: facts.schema.json выпуска facts-v1.6.0 не скачан"

    monkeypatch.setattr(module, "run_step", step)
    monkeypatch.setattr(module, "release_missing", probe)
    assert module.main(["--root", str(ROOT), "--repo", "o/a"]) == module.EXIT_FOUND
    assert asked == ["facts.schema.json"]


def test_imports_are_followed_only_into_our_sources(tmp_path: Path) -> None:
    """Замыкание идёт по нашим модулям, а чужие импорты не тянет."""
    scripts = tmp_path / module.paths.SCRIPTS
    scripts.mkdir()
    (scripts / "a.py").write_text("import json\nimport b\n", encoding="utf-8")
    (scripts / "b.py").write_text("from a import x\n", encoding="utf-8")
    found = module.module_closure("a", tmp_path)
    assert found == {module.paths.SCRIPTS / "a.py", module.paths.SCRIPTS / "b.py"}


def test_the_gate_builds_the_facts_the_step_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заход гейта отдаёт сборке те же входы, что вызывающий шага (взгляд на #1391)."""
    built: list[list[str]] = []

    def build(argv: list[str]) -> int:
        built.append(argv)
        return 1

    monkeypatch.setattr(module.facts_common, "main", build)
    assert module.main(["--root", str(ROOT), "--repo", "o/a"]) == module.EXIT_BROKEN
    assert built and set(module.build_args(ROOT)) <= set(built[0])


def test_gate_runs_finds_the_flow_that_calls_the_gate(tmp_path: Path) -> None:
    """Прогон гейта находится по шагу, который его зовёт, а не по имени файла."""
    flows = tmp_path / module.paths.WORKFLOWS
    flows.mkdir(parents=True)
    (flows / "x.yml").write_text(
        "jobs:\n  g:\n    steps:\n      - run: python scripts/check_facts_contract.py\n",
        encoding="utf-8",
    )
    (flows / "y.yml").write_text("jobs:\n  h:\n    steps:\n      - run: echo\n", encoding="utf-8")
    assert module.gate_runs(tmp_path) == {module.paths.WORKFLOWS / "x.yml"}
