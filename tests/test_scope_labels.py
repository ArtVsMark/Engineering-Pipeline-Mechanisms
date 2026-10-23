"""Сценарий меткой `scope/*`: ставит `agent_pr`, сверяет гейт разметки (#1599).

Метка — след классификатора и вход только в одну сторону: владелец расширяет,
сузить нельзя. Здесь проверяется каждая из трёх сторон: выбор тестов с меткой,
постановка метки и гейт.
"""

import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, RunScript, load_script
from tests.test_gates_reject import CLEAN, REJECTED, write_event

scope = load_script("scope.py")
agent_pr = load_script("agent_pr.py")
meta = load_script("check_pr_meta.py")


def test_every_scenario_has_a_declared_label() -> None:
    """Каждый сценарий классификатора заведён меткой в составе — и только они."""
    flow = yaml.safe_load((ROOT / ".github" / "labels.yml").read_text(encoding="utf-8"))
    declared = {str(one["name"]) for one in flow if str(one["name"]).startswith("scope/")}
    assert declared == {scope.label_of(one) for one in scope.ORDER}


@pytest.mark.parametrize(
    ("names", "widest"),
    [
        ([], None),
        (["area/docs", "bug"], None),
        (["scope/code"], "code"),
        (["scope/text", "scope/full", "scope/code"], "full"),
        (["scope/чужое"], None),
    ],
    ids=["пусто", "нет-сценария", "один", "широкий-побеждает", "чужое-слово"],
)
def test_the_widest_label_wins(names: list[str], widest: str | None) -> None:
    """Из нескольких меток решает самая широкая; чужое слово сценарием не считается."""
    assert scope.widest(names) == widest


def test_a_wider_label_widens_the_choice() -> None:
    """`scope/full` от владельца даёт полный набор там, где граф выбрал один файл."""
    choice = scope.Choice(scope.CODE, ("tests/test_a.py",), "")
    said = scope.widened(choice, ["scope/full"])
    assert said.scenario == scope.FULL
    assert said.tests is None
    assert "scope/full" in said.why


@pytest.mark.parametrize("names", [["scope/text"], ["scope/code"], []], ids=["уже", "та-же", "нет"])
def test_a_label_never_narrows_the_choice(names: list[str]) -> None:
    """Метка не шире ответа выбор не меняет: сузить проверки словом нельзя."""
    choice = scope.Choice(scope.CODE, ("tests/test_a.py",), "")
    assert scope.widened(choice, names) == choice


def test_main_takes_the_labels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--labels` доезжает до выбора: с `scope/full` печатается ALL."""
    monkeypatch.setattr(
        scope, "choose", lambda root, base, since="": scope.Choice(scope.TEXT, (), "")
    )
    assert scope.main(["--tests", "--base", "main", "--labels", "bug scope/full"]) == 0
    assert capsys.readouterr().out.strip() == "ALL"


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    """Записывает обращения к площадке вместо того, чтобы их выполнять."""
    seen: list[tuple[str, str, Any]] = []

    def remember(method: str, path: str, token: str, body: Any = None) -> Any:
        seen.append((method, path, body))
        return {}

    monkeypatch.setattr(agent_pr.ghrest, "request", remember)
    return seen


def touching(monkeypatch: pytest.MonkeyPatch, *files: str) -> None:
    """Ветка трогает названные файлы."""
    monkeypatch.setattr(agent_pr, "changed_files", lambda branch, base: list(files))


def test_a_fresh_change_gets_its_scenario(
    monkeypatch: pytest.MonkeyPatch, platform: list[tuple[str, str, Any]]
) -> None:
    """Код тронут — `agent_pr` ставит `scope/code`, как ставит зону."""
    touching(monkeypatch, "scripts/x.py")
    agent_pr.apply_scope("о/р", 7, "т", "b", "main", set(), dry_run=False)
    assert platform == [("POST", "repos/о/р/issues/7/labels", {"labels": ["scope/code"]})]


def test_a_narrower_trace_is_replaced(
    monkeypatch: pytest.MonkeyPatch, platform: list[tuple[str, str, Any]]
) -> None:
    """Толчок задел код — прежний след `scope/text` снимается, иначе гейт отвергнет."""
    touching(monkeypatch, "scripts/x.py")
    agent_pr.apply_scope("о/р", 7, "т", "b", "main", {"scope/text"}, dry_run=False)
    assert [one[0] for one in platform] == ["POST", "DELETE"]
    assert platform[1][1].endswith("/labels/scope%2Ftext")


def test_the_owner_wider_word_stays(
    monkeypatch: pytest.MonkeyPatch, platform: list[tuple[str, str, Any]]
) -> None:
    """`scope/full` владельца шире ответа — его не трогают и уже не добавляют."""
    touching(monkeypatch, "README.md")
    agent_pr.apply_scope("о/р", 7, "т", "b", "main", {"scope/full"}, dry_run=False)
    assert platform == []


def test_undeclared_scenarios_are_not_set(
    monkeypatch: pytest.MonkeyPatch, platform: list[tuple[str, str, Any]]
) -> None:
    """У потребителя без `scope/*` в составе метка не ставится: она была бы необъявленной."""
    touching(monkeypatch, "scripts/x.py")
    monkeypatch.setattr(agent_pr.labels, "load", lambda: [])
    agent_pr.apply_scope("о/р", 7, "т", "b", "main", set(), dry_run=False)
    assert platform == []


def test_a_refused_scenario_does_not_lose_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ площадки шаг не роняет: изменение открыто, метка — след (084)."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise agent_pr.ghrest.TransportError("площадка недоступна")

    touching(monkeypatch, "scripts/x.py")
    monkeypatch.setattr(agent_pr.ghrest, "request", refuse)
    agent_pr.apply_scope("о/р", 7, "т", "b", "main", set(), dry_run=False)


def test_an_open_change_gets_its_scenario_too() -> None:
    """Сценарий ставит общая цепочка `settle`, которую зовут оба пути — создание и «уже открыто»."""
    assert "apply_scope(" in inspect.getsource(agent_pr.settle)
    assert "settle(" in inspect.getsource(agent_pr.finish_open)
    assert "settle(" in inspect.getsource(agent_pr.main)


@pytest.mark.parametrize(
    ("on_pr", "files", "red"),
    [
        (["scope/text"], ["scripts/x.py"], True),
        (["scope/code"], ["scripts/x.py"], False),
        (["scope/full"], ["scripts/x.py"], False),
        ([], ["scripts/x.py"], False),
    ],
    ids=["уже-красно", "та-же", "шире-владелец", "без-метки"],
)
def test_the_gate_rejects_only_a_narrower_label(
    on_pr: list[str], files: list[str], red: bool
) -> None:
    """Гейт краснеет на метке уже ответа, а шире и отсутствие пропускает."""
    declared = {scope.label_of(one) for one in scope.ORDER}
    assert bool(meta.scope_problems(set(on_pr), declared, files)) is red


def test_the_gate_is_silent_without_declared_scenarios() -> None:
    """Сценарии не объявлены — судить нечего: у потребителя их нет."""
    assert meta.scope_problems({"scope/text"}, set(), ["scripts/x.py"]) == []


def test_the_gate_names_a_narrower_label(run_script: RunScript, tmp_path: Path) -> None:
    """Процессом: `scope/text` на правке кода отвергается с названной причиной."""
    env = write_event(tmp_path, ["area/gates", "bug", "scope/text"], "Closes #1")
    result = run_script("check_pr_meta.py", "--files", "scripts/x.py", env=env)
    assert result.code == REJECTED
    assert "scope/text" in result.text


def test_the_gate_lets_the_owner_widen(run_script: RunScript, tmp_path: Path) -> None:
    """Процессом: `scope/full` владельца на правке текста проходит."""
    env = write_event(tmp_path, ["area/docs", "documentation", "scope/full"], "Closes #8")
    assert run_script("check_pr_meta.py", "--files", "README.md", env=env).code == CLEAN
