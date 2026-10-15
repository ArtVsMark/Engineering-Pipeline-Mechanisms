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

from tests.conftest import ROOT, load_script

module = load_script("check_facts_contract.py")

GOOD = (0, "o/a: договору отвечает\n")
CAUGHT = (1, f"{module.STRANGER}: расхождений 1\n")


def test_the_gate_finds_exactly_one_contract_step_in_the_tree() -> None:
    """Шаг сверки в `step-facts.yml` один и несёт тег, адрес выпуска и хеши."""
    step = module.contract_step((ROOT / module.FLOW).read_text(encoding="utf-8"))
    assert set(step["env"]) >= {"FACTS_CONTRACT", "RELEASES", "FACTS_SHA256"}


@pytest.mark.parametrize("copies", [0, 2], ids=["шага-нет", "шагов-два"])
def test_no_single_contract_step_is_the_third_outcome(copies: int) -> None:
    """Нет шага сверки или их два — «не отработал», а не «чисто» (075)."""
    step = '      - name: сверка\n        run: python "$dir/check_facts.py"\n'
    flow = "jobs:\n  facts:\n    steps:\n" + step * copies
    with pytest.raises(module.NotRun):
        module.contract_step(flow)


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
    ],
    ids=[
        "сверка-жива",
        "хеш-не-тот",
        "мертва-на-годных",
        "расхождение-не-остановило",
        "код-1-без-строки",
        "канал-молчит",
        "тега-нет",
    ],
)
def test_the_verdict_names_a_dead_check(
    good: tuple[int, str], stranger: tuple[int, str], missing: bool, code: int
) -> None:
    """Жива — только когда годное прошло, а расхождение остановило шаг своей строкой."""
    assert module.verdict(good, stranger, missing)[0] == code


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
    target.write_text("правка\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "--quiet", "-m", "правка")
    assert module.touched("main", tmp_path) is touches


@pytest.mark.parametrize(
    ("raised", "missing"),
    [
        (urllib.error.HTTPError("u", 404, "Not Found", {}, None), True),  # type: ignore[arg-type]
        (urllib.error.HTTPError("u", 503, "Unavailable", {}, None), False),  # type: ignore[arg-type]
        (urllib.error.URLError("нет сети"), False),
    ],
    ids=["404", "503", "сети-нет"],
)
def test_only_a_404_says_the_tag_is_wrong(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, missing: bool
) -> None:
    """«Нет такого» — находка о дереве; любой другой отказ — молчание канала (084)."""

    def refuse(*_: object, **__: object) -> None:
        raise raised

    monkeypatch.setattr(module.urllib.request, "urlopen", refuse)
    step = {"env": {"RELEASES": "https://example.invalid", "FACTS_CONTRACT": "facts-v0.0.0"}}
    assert module.release_missing(step) is missing
