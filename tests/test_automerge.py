"""Очередь проверяется тем, что она обязана НЕ слить.

Механизм, у которого проверен только счастливый путь, доказывает лишь то, что
он умеет сливать. Цена ошибки здесь несимметрична: не слитое зелёное изменение
подождёт события, а слитое красное уже в общей ветке, и уплотнение переписать
нечем ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).

Площадка сюда не зовётся: подменяются функции самого модуля, читающие её.
Предмет проверки — решение очереди, а не транспорт; транспорт проверен у себя
(`tests/test_ghrest.py`, `tests/test_token_paths.py`).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import RunScript, load_script

module = load_script("automerge.py")


def change(
    number: int,
    *marks: str,
    files: tuple[str, ...] = (),
    draft: bool = False,
    base: str = "main",
) -> Any:
    """Собирает изменение-кандидат в том виде, в каком его строит модуль."""
    return module.Change(
        number=number,
        branch=f"agent/change-{number}",
        base=base,
        head=f"sha{number}",
        title=f"изменение {number}",
        draft=draft,
        marks=frozenset(marks),
        files=frozenset(files),
    )


def record(name: str, conclusion: str | None = "success", status: str = "completed") -> Any:
    """Одна запись проверки в том виде, в каком её отдаёт площадка."""
    return {"name": name, "status": status, "conclusion": conclusion, "details_url": ""}


# --- отбор кандидатов --------------------------------------------------------


def test_hold_takes_a_change_out_of_the_queue() -> None:
    """`hold` снимает изменение с очереди при любом зелёном — в этом её смысл."""
    queue = module.candidates(
        [change(1, "automerge"), change(2, "automerge", "hold")],
        "main",
    )
    assert [item.number for item in queue] == [1]


def test_a_draft_is_not_a_candidate() -> None:
    """Черновик готовым не объявлен, и метка на нём этого не меняет."""
    queue = module.candidates([change(1, "automerge", draft=True)], "main")
    assert queue == []


def test_a_change_without_the_label_is_not_a_candidate() -> None:
    """Очередь берёт помеченное, а не всё зелёное: список разрешительный (068)."""
    assert module.candidates([change(1)], "main") == []


def test_another_base_is_not_this_queue() -> None:
    """Изменение в чужую базу этой очередью не двигается."""
    assert module.candidates([change(1, "automerge", base="release")], "main") == []


# --- порядок вставки ---------------------------------------------------------


def test_repair_outruns_everything_ready_earlier() -> None:
    """Починка общей ветки идёт первой, даже поданная последней (053).

    Это и есть отличие порядка по правилу от порядка по приходу: очередь FIFO
    поставила бы починку за тремя правками опечаток.
    """
    queue = [
        change(1, "automerge"),
        change(2, "automerge", "blocker"),
        change(9, "automerge", "fix-main"),
    ]
    ordered = module.order(queue, frozenset())
    assert [item.number for item in ordered] == [9, 2, 1]


def test_a_shared_file_outruns_the_rest() -> None:
    """Трогающее общий с соседом файл идёт раньше остальных."""
    first = change(5, "automerge", files=("scripts/ghrest.py",))
    second = change(6, "automerge", files=("scripts/ghrest.py",))
    lonely = change(2, "automerge", files=("docs/pipeline.md",))
    shared = module.shared_paths([first, second, lonely])
    assert shared == frozenset({"scripts/ghrest.py"})
    ordered = module.order([lonely, first, second], shared)
    assert [item.number for item in ordered] == [5, 6, 2]


def test_arrival_decides_only_inside_one_step() -> None:
    """Внутри ступени решает номер: приход работает там, где правило молчит."""
    ordered = module.order([change(7, "automerge"), change(3, "automerge")], frozenset())
    assert [item.number for item in ordered] == [3, 7]


def test_a_lonely_file_is_not_shared() -> None:
    """Общим считается пересечение живых составов, а не список руками (133)."""
    assert (
        module.shared_paths([change(1, files=("a.py",)), change(2, files=("b.py",))]) == frozenset()
    )


# --- заходы очереди ----------------------------------------------------------


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Подменяет всё, что модуль читает у площадки, и записывает его действия."""
    state: dict[str, Any] = {
        "changes": [],
        "files": {},
        "health": [],
        "runs": {},
        "states": {},
        "merged": [],
        "synced": [],
    }

    monkeypatch.setattr(module, "open_changes", lambda repo, tok: state["changes"])
    monkeypatch.setattr(
        module, "files_of", lambda repo, number, tok: frozenset(state["files"].get(number, ()))
    )
    monkeypatch.setattr(module, "branch_health", lambda repo, sha, tok: state["health"])
    monkeypatch.setattr(
        module.ghrest, "request", lambda method, path, tok, body=None: {"sha": "base-sha"}
    )
    monkeypatch.setattr(
        module,
        "merge_state",
        lambda repo, number, tok: state["states"].get(number, "clean"),
    )
    monkeypatch.setattr(
        module,
        "sync_head",
        lambda repo, number, tok, *, dry_run: state["synced"].append(number),
    )
    monkeypatch.setattr(
        module,
        "merge",
        lambda repo, item, tok, *, dry_run: (state["merged"].append(item.number), "merged-sha")[1],
    )

    def head_verdict(repo: str, item: Any, tok: str) -> tuple[list[str], bool]:
        problems, waiting = state["runs"].get(item.number, ([], False))
        return list(problems), bool(waiting)

    monkeypatch.setattr(module, "head_verdict", head_verdict)
    return state


def test_an_empty_queue_is_a_state_not_a_refusal(platform: dict[str, Any]) -> None:
    """Никто не просил слияния — это ответ, а не отказ.

    Краснеть здесь значило бы завести проверку, которая красна почти всегда, —
    и её приучаются обходить (051). Отказ по 075 стоит в другом месте: на
    голове кандидата без единой записи проверки.
    """
    platform["changes"] = [change(1)]
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == []


def test_no_records_on_the_head_refuses_to_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Записей на голове нет ни одной — прогон не стартовал, а не «зелено» (075).

    Проверяется сам вердикт, а не его подмена: пустой ответ площадки обязан
    дойти до находки, иначе не стартовавший прогон читается как пройденный.
    """
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, tok, key=None: iter(()))
    problems, waiting = module.head_verdict("o/r", change(1, "automerge"), "token")
    assert not waiting
    assert problems and "прогон не стартовал" in problems[0]


def test_a_green_head_passes_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Здоровый вход обязан пройти: гейт проверяется обеими ошибками (097)."""
    green = [
        record(name) for name in ("lint", "test", "pr-meta", "journal", "attribution", "pipeline")
    ]
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, tok, key=None: iter(green))
    problems, waiting = module.head_verdict("o/r", change(1, "automerge"), "token")
    assert (problems, waiting) == ([], False)


def test_a_head_with_records_but_no_green_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Записи есть, а обязательных среди них нет — это тоже отказ."""
    monkeypatch.setattr(
        module.ghrest, "paginate", lambda path, tok, key=None: iter([record("badges")])
    )
    problems, _ = module.head_verdict("o/r", change(1, "automerge"), "token")
    assert problems and all("записи нет" in problem for problem in problems)


def test_a_red_head_is_skipped_and_the_queue_goes_on(platform: dict[str, Any]) -> None:
    """Одна красная голова не держит остальных: она уходит в контур 1."""
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["runs"] = {1: (["lint: failure"], False)}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [2]


def test_a_conflict_is_stepped_over_not_escalated(platform: dict[str, Any]) -> None:
    """Конфликт штатен (004): голова пропускается, очередь идёт дальше."""
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["states"] = {1: module.STATE_CONFLICT}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [2]


def test_only_the_head_pulls_the_base(platform: dict[str, Any]) -> None:
    """Отставшая голова подтягивает базу и на этом заход кончается (052).

    Второй кандидат не трогается вовсе: подтягивать всех — квадрат холостой
    работы, и это ровно тот замер, из-за которого правило записано.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["states"] = {1: module.STATE_BEHIND, 2: module.STATE_BEHIND}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["synced"] == [1]
    assert platform["merged"] == []


def test_pending_checks_make_the_queue_wait_not_skip(platform: dict[str, Any]) -> None:
    """Идущие проверки головы останавливают заход, а не пропускают её.

    Пропустить голову, пока её проверки идут, значило бы обойти порядок:
    следующий за ней слился бы раньше на ровном месте.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["runs"] = {1: ([], True)}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == []


def test_a_red_shared_branch_freezes_everything_but_the_repair(
    platform: dict[str, Any],
) -> None:
    """Красная общая ветка замораживает очередь, кроме починки."""
    platform["changes"] = [change(1, "automerge"), change(9, "automerge", "fix-main")]
    platform["health"] = ["test: failure"]
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [9]


def test_a_red_shared_branch_without_a_repair_moves_nothing(platform: dict[str, Any]) -> None:
    """Заморозка без починки не двигает ничего — и говорит об этом."""
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["health"] = ["test: failure"]
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == []


def test_one_pass_merges_at_most_one_change(platform: dict[str, Any]) -> None:
    """За заход сливается одна голова: остальные после неё уже устарели."""
    platform["changes"] = [change(1, "automerge"), change(2, "automerge"), change(3, "automerge")]
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [1]


def test_an_unmergeable_state_skips_the_head_instead_of_reddening(
    platform: dict[str, Any],
) -> None:
    """Незнакомое состояние головы пропускается, а не зовёт слияние наугад.

    Список разрешительный (068): на `blocked` и `unknown` площадка слияния не
    даст, и её отказ уронил бы ВЕСЬ заход вместо одной головы. Проверяется
    обоими значениями сразу — иначе разрешительный список неотличим от
    запретительного, где перечислены ровно эти два.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge"), change(3, "automerge")]
    platform["states"] = {1: "blocked", 2: "unknown"}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [3]


def test_an_advisory_red_still_merges(platform: dict[str, Any]) -> None:
    """`unstable` — красна необязательная проверка, и слияния она не держит.

    Класс проверки объявлен данными: совещательное красное оставляет запись
    адресату, но очередь не останавливает (084).
    """
    platform["changes"] = [change(1, "automerge")]
    platform["states"] = {1: "unstable"}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [1]


def test_the_candidate_branch_is_fetched_before_the_body_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Тело собирается по `origin/<ветка>`, и ветка приносится перед сборкой.

    Заход очереди работает в своём чекауте: голого имени `agent/<задача>` в
    нём нет, и без явной доставки сборщик не разрешил бы ссылку ни разу —
    слияние падало бы почти всегда.
    """
    fetched: list[tuple[str, ...]] = []
    asked: list[tuple[str, str]] = []

    def remember_git(*args: str) -> str:
        fetched.append(args)
        return ""

    def remember_compose(branch: str, base: str) -> str:
        asked.append((branch, base))
        return "тело"

    monkeypatch.setattr(module.squash_body, "git", remember_git)
    monkeypatch.setattr(module.squash_body, "compose", remember_compose)
    module.merge("o/r", change(1, "automerge"), "token", dry_run=True)

    assert asked == [("origin/agent/change-1", "main")]
    assert any("agent/change-1" in " ".join(call) for call in fetched)
    assert any("main" in " ".join(call) for call in fetched)


# --- вход механизма ----------------------------------------------------------


def test_every_label_the_queue_reads_is_declared() -> None:
    """Все четыре метки очереди объявлены составом, а не только кодом (064)."""
    module.check_labels_declared()


def test_a_renamed_label_drops_the_queue_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переименование метки в составе роняет очередь, а не обеззвучивает её.

    Молча очередь перестала бы находить кандидатов и выглядела бы как «сливать
    нечего»: отсутствующий вход и пустой вход снаружи неотличимы (075).
    """
    monkeypatch.setattr(module.labels, "load", lambda *args, **kwargs: [])
    with pytest.raises(module.NotRun) as caught:
        module.check_labels_declared()
    assert module.LABEL_AUTOMERGE in str(caught.value)


# --- исходы ------------------------------------------------------------------


def test_missing_owner_token_is_not_configured(run_script: RunScript) -> None:
    """Без токена владельца шаг не краснеет, а называет третий исход (084).

    На токен прогона он не переходит намеренно: это дало бы ровно ту подмену
    авторства, ради которой заведён отдельный секрет (131).
    """
    done = run_script("automerge.py", "--repo", "o/r", env={"MERGE_QUEUE_TOKEN": ""})
    assert done.code == module.EXIT_NOT_CONFIGURED
    assert "не настроено" in done.text


def test_the_run_token_is_never_taken_for_the_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Токен прогона очередью не читается: имя секрета одно и оно объявлено."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_run")
    monkeypatch.setenv("GH_TOKEN", "ghp_run")
    monkeypatch.delenv(module.ENV_TOKEN, raising=False)
    assert module.token() == ""
