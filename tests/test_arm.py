"""Замер взведения проверяется тем, что он обязан НЕ сделать.

Шаг берёт у площадки последнее действие — само слияние, — и до того, как
доверять, спрашивает её об одном: принимает ли мутация тело уплотнения. Поэтому
здесь проверяется не «взвелось», а границы: кого под замер брать нельзя, что
снятие идёт всегда, и что ответ площадки читается, а не предполагается
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md),
[145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import RunScript, load_script

module = load_script("arm.py")

HEADLINE = "замер взведения: тело передано явно (#7)"
BODY = "тело, которое площадка обязана вернуть дословно"


def change(number: int, state: str, *, draft: bool = False) -> dict[str, Any]:
    """Изменение в том виде, в каком его отдаёт площадка."""
    return {
        "number": number,
        "draft": draft,
        "node_id": f"PR_{number}",
        "mergeable_state": state,
    }


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Площадка на подмене: помнит, о чём спросили и что ей передали."""
    state: dict[str, Any] = {"changes": [], "graphql": [], "posted": [], "echo": True}

    def paginate(path: str, token: str, key: str | None = None) -> Any:
        return iter(state["changes"])

    def request(method: str, path: str, token: str, payload: Any = None) -> Any:
        if method == "GET":
            number = int(path.rsplit("/", 1)[-1])
            return next(one for one in state["changes"] if one["number"] == number)
        state["posted"].append((path, payload))
        return {}

    def graphql(query: str, variables: dict[str, Any], token: str) -> dict[str, Any]:
        # Различают мутации по ИМЕНИ ОПЕРАЦИИ, а не по подстроке: `enabledAt`
        # в ответе снятия делает поиск «enable» в тексте ложным другом.
        name = "arm" if module.ghrest.operation_of(query).startswith("enable") else "disarm"
        state["graphql"].append((name, variables))
        if name == "disarm":
            return {"disablePullRequestAutoMerge": {"pullRequest": {"number": 7}}}
        answer = {"enabledAt": "2026-09-12T10:00:00Z"}
        if state["echo"]:
            answer["commitHeadline"] = variables["headline"]
            answer["commitBody"] = variables["body"]
        return {"enablePullRequestAutoMerge": {"pullRequest": {"autoMergeRequest": answer}}}

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module.ghrest, "graphql", graphql)
    return state


def test_the_subject_is_armable_but_unmergeable(platform: dict[str, Any]) -> None:
    """Под замер берут то, что площадка взведёт, но не сольёт.

    Готовое к слиянию она сольёт сама в зазоре между взведением и снятием — и
    замер стал бы слиянием чужой работы без спроса.
    """
    platform["changes"] = [change(3, "clean"), change(7, module.ARMABLE_UNMERGEABLE)]
    found = module.armable("o/r", "t")
    assert found is not None and found["number"] == 7


def test_a_draft_is_not_taken_under_the_probe(platform: dict[str, Any]) -> None:
    """Черновик мутация отвергает сама — и это ответ не про тело, а про черновик."""
    platform["changes"] = [change(9, module.ARMABLE_UNMERGEABLE, draft=True)]
    assert module.armable("o/r", "t") is None


def test_no_subject_is_not_run_not_clean(platform: dict[str, Any]) -> None:
    """Предмета не нашлось — «не отработал», а не «взводить некого» (075)."""
    platform["changes"] = [change(3, "clean"), change(4, "dirty")]
    with pytest.raises(module.NotRun) as caught:
        module.probe("o/r", "t", dry_run=False)
    assert module.ARMABLE_UNMERGEABLE in str(caught.value)


def test_the_body_is_passed_and_asked_back(platform: dict[str, Any]) -> None:
    """Взведение передаёт тело И просит его обратно: «поля есть» ≠ «поля работают»."""
    answer = module.arm("PR_7", HEADLINE, BODY, "t")
    name, variables = platform["graphql"][0]
    assert name == "arm"
    assert variables["headline"] == HEADLINE and variables["body"] == BODY
    assert variables["method"] == module.METHOD, "способ слияния не назван решением"
    assert answer["commitHeadline"] == HEADLINE


def test_a_swallowed_body_is_named_field_by_field() -> None:
    """Проглоченное тело называют полем, а не итогом: пересматривать надо предметно."""
    assert (
        module.kept_the_body({"commitHeadline": HEADLINE, "commitBody": BODY}, HEADLINE, BODY) == []
    )
    missing = module.kept_the_body({"enabledAt": "2026-09-12T10:00:00Z"}, HEADLINE, BODY)
    assert [one.split(":")[0] for one in missing] == ["commitHeadline", "commitBody"]


def test_the_arming_is_always_taken_back(platform: dict[str, Any]) -> None:
    """Снятие идёт ВСЕГДА — даже если разбор ответа упал.

    Взведённое и брошенное площадка сольёт сама, как только проверки
    позеленеют: незакрытое согласие тут дороже красного шага
    ([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md)).
    """
    platform["changes"] = [change(7, module.ARMABLE_UNMERGEABLE)]

    def explode(*args: object, **kwargs: object) -> list[str]:
        raise RuntimeError("разбор ответа упал")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "kept_the_body", explode)
        with pytest.raises(RuntimeError):
            module.probe("o/r", "t", dry_run=False)
    assert [name for name, _ in platform["graphql"]] == ["arm", "disarm"]


def test_the_dry_run_touches_nothing(platform: dict[str, Any]) -> None:
    """Без `--apply` шаг ничего не взводит: показ и действие — разные заходы (104)."""
    platform["changes"] = [change(7, module.ARMABLE_UNMERGEABLE)]
    said = module.probe("o/r", "t", dry_run=True)
    assert "#7" in said and not platform["graphql"]


def test_a_kept_body_says_the_decision_stands(platform: dict[str, Any]) -> None:
    """Тело вернулось дословно — решение 011 строится на проверенном."""
    platform["changes"] = [change(7, module.ARMABLE_UNMERGEABLE)]
    said = module.probe("o/r", "t", dry_run=False)
    assert "ВМЕСТЕ с телом" in said


def test_a_lost_body_names_the_condition_of_review(platform: dict[str, Any]) -> None:
    """Тело проглочено — наступило названное решением условие пересмотра."""
    platform["changes"] = [change(7, module.ARMABLE_UNMERGEABLE)]
    platform["echo"] = False
    said = module.probe("o/r", "t", dry_run=False)
    assert "ТЕЛО НЕТ" in said and "пересмотра" in said


def test_the_disarming_names_its_own_mutation(platform: dict[str, Any]) -> None:
    """Снятие — своя мутация, а не взведение с пустым телом."""
    module.disarm("PR_7", "t")
    name, variables = platform["graphql"][0]
    assert name == "disarm" and variables == {"id": "PR_7"}


def test_a_missing_owner_token_is_its_own_outcome(run_script: RunScript) -> None:
    """Нет токена владельца — «не настроено», а не поломка (039, 154).

    Заход здесь ОТДЕЛЬНЫМ ПРОЦЕССОМ: исход шага площадка читает кодом возврата,
    и проверять его вызовом функции значило бы проверять не то, что пойдёт в
    прогоне
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).
    """
    done = run_script("arm.py", "--repo", "o/r", "--probe", "--apply", env={module.ENV_TOKEN: ""})
    assert done.code == module.EXIT_UNSET, done.text
    assert module.ENV_TOKEN in done.text


def test_the_answer_is_written_where_a_human_reads_it(
    platform: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Замер, оставшийся в логе прогона, замером не является: логи окну не видны."""
    platform["changes"] = [change(7, module.ARMABLE_UNMERGEABLE)]
    monkeypatch.setenv(module.ENV_TOKEN, "t")
    assert module.main(["--repo", "o/r", "--probe", "--apply", "--say-to", "196"]) == module.EXIT_OK
    path, payload = platform["posted"][0]
    assert path.endswith("issues/196/comments")
    assert "Замер взведения" in payload["body"]


def test_a_step_without_a_subject_refuses_out_loud(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Заход без `--probe` не молчит: предмет шага называют, а не угадывают."""
    monkeypatch.setenv(module.ENV_TOKEN, "t")
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN
    assert "не отработал" in capsys.readouterr().err


def test_the_measurement_is_written_by_one_place(platform: dict[str, Any]) -> None:
    """Запись ответа — своя функция: заголовок раздела один на все исходы."""
    module.say("o/r", "196", "тело принято", "t")
    path, payload = platform["posted"][0]
    assert path == "repos/o/r/issues/196/comments"
    assert payload["body"].startswith("## Замер взведения")


def test_a_refused_measurement_is_written_too(
    platform: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Не отработал» — такой же ответ решению 011, как и «тело принято» (154).

    Молчание неотличимо от «не запускали», а логи прогона окну не видны: отказ,
    оставшийся в них, выглядел бы так, будто замера не было.
    """
    platform["changes"] = [change(3, "clean")]
    monkeypatch.setenv(module.ENV_TOKEN, "t")
    code = module.main(["--repo", "o/r", "--probe", "--apply", "--say-to", "196"])
    assert code == module.EXIT_BROKEN
    _, payload = platform["posted"][0]
    assert "не отработал" in payload["body"]


def test_an_unwritable_answer_is_not_a_measurement(
    platform: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Замер, который некуда записать, замером не является — исход красный."""
    platform["changes"] = [change(7, module.ARMABLE_UNMERGEABLE)]
    monkeypatch.setenv(module.ENV_TOKEN, "t")

    def refuse(repo: str, task: str, said: str, token: str) -> None:
        raise module.ghrest.TransportError("403: лента закрыта")

    monkeypatch.setattr(module, "say", refuse)
    assert module.main(["--repo", "o/r", "--probe", "--apply", "--say-to", "196"]) == (
        module.EXIT_BROKEN
    )
    assert [name for name, _ in platform["graphql"]] == ["arm", "disarm"], "взведение не снято"
