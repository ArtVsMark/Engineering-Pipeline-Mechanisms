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
    body: str = "",
) -> Any:
    """Собирает изменение-кандидат в том виде, в каком его строит модуль."""
    return module.Change(
        number=number,
        branch=f"agent/change-{number}",
        base=base,
        head=f"sha{number}",
        title=f"изменение {number}",
        body=body,
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


def test_the_step_is_the_number_of_the_work_source() -> None:
    """Ступень очереди — номер источника работы контура 1, а не свой словарь.

    У проекта уже есть порядок, по которому окно БЕРЁТ работу. Второй,
    собственный порядок для слияния означал бы, что важное на входе и важное на
    выходе — разные вещи; они одно (022).
    """
    assert module.rank(change(1, "automerge", "fix-main")) == 0
    assert module.rank(change(1, "automerge", body="Разобрано: abc1234")) == 3
    assert module.rank(change(1, "automerge", "blocker")) == 4
    assert module.rank(change(1, "automerge", files=(module.RULES_ANSWER,))) == 5
    assert module.rank(change(1, "automerge")) == 6


def test_the_vocabulary_covers_every_work_source() -> None:
    """Словарь полный — все семь источников, а не только сортируемые.

    Изменение из плана, покраснев, становится работой по источнику 2, а
    конфликтнув — по источнику 1. Это то же изменение, сменившее источник, и
    называть его надо тем же словом; отдельные слова завели бы второй словарь.
    """
    assert sorted(module.RANK_NAMES) == [0, 1, 2, 3, 4, 5, 6]


def test_the_two_platform_sources_are_published_where_they_are_found(
    platform: dict[str, Any],
) -> None:
    """Источники 1 и 2 ВЫСТАВЛЯЮТСЯ там, где заход их обнаружил.

    До обращения к площадке они не выводятся, и это цена правила 052: красноту
    заход и так спрашивает у каждого кандидата, а состояние слияния площадка
    считает лениво — спрашивать его у всех значит заказывать вычисление,
    которое никому не понадобится.

    Проверяется ДЕЙСТВИЕ, а не сообщение. Прежняя редакция сверяла строку
    вывода — и проходила при отсутствующем вызове публикации: имя источника
    печаталось рядом, а метка не выставлялась никогда. Замер 09.09.2026.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge"), change(3, "automerge")]
    platform["runs"] = {1: (["lint: failure"], False)}
    platform["states"] = {2: module.STATE_CONFLICT}
    module.advance("o/r", "token", "main", dry_run=False)
    assert (1, module.RANK_OWN_RED) in platform["sources"]
    assert (2, module.RANK_CONFLICT) in platform["sources"]
    assert platform["merged"] == [3]


def test_every_candidate_gets_its_source_published(platform: dict[str, Any]) -> None:
    """Метку получает каждый кандидат — и ту, которая ему присвоена.

    Сверять одни номера мало: заход, выставивший всем одну и ту же ступень,
    прошёл бы такую проверку, а очередь по такой метке читалась бы неверно.
    Оба кандидата здесь из плана, и сказано это должно быть именно так.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    module.advance("o/r", "token", "main", dry_run=False)
    assert set(platform["sources"]) == {(1, module.RANK_PLAN), (2, module.RANK_PLAN)}


def test_a_finding_repair_outruns_the_plan() -> None:
    """Снятие находки идёт раньше работы по плану — как и в контуре 1.

    Долг по УЖЕ сделанному стоит перед новой работой: поверх непочиненного
    механизма строится всё, что сольётся после него.
    """
    plan = change(1, "automerge")
    debt = change(9, "automerge", body="Refs #23\nРазобрано: abc1234")
    assert [item.number for item in module.order([plan, debt], frozenset())] == [9, 1]


def test_the_owner_word_outruns_the_rules_debt() -> None:
    """Слово владельца идёт раньше долга по правилам — тот же порядок (091)."""
    rules = change(1, "automerge", files=(module.RULES_ANSWER,))
    owner = change(9, "automerge", "blocker")
    assert [item.number for item in module.order([rules, owner], frozenset())] == [9, 1]


def test_a_shared_file_decides_inside_a_step_not_across_them() -> None:
    """Общий файл — пропускная способность, а не приоритет.

    Он уменьшает будущие конфликты, а не говорит о важности. Поэтому решает
    ВНУТРИ ступени: изменение из плана, трогающее общий файл, не обгоняет
    снятие находки.
    """
    debt = change(1, "automerge", body="Разобрано: abc1234", files=("docs/pipeline.md",))
    plan = change(9, "automerge", files=("scripts/ghrest.py",))
    other = change(10, "automerge", files=("scripts/ghrest.py",))
    shared = module.shared_paths([debt, plan, other])
    assert [item.number for item in module.order([plan, other, debt], shared)] == [1, 9, 10]


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
        "sources": [],
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
    # Разметка источника записывается стендом отдельно: проверять надо, что
    # метка ВЫСТАВЛЕНА, а не что о ней напечатано. Замер 09.09.2026: вызов
    # публикации в ветке красного отсутствовал, а тест сверял строку вывода —
    # и потому проходил.
    monkeypatch.setattr(
        module,
        "publish_source",
        lambda repo, item, place, tok, *, dry_run: state["sources"].append((item.number, place)),
    )
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
        record(name)
        for name in ("lint", "test", "pr-meta", "journal", "attribution", "pipeline", "contract")
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
    работы: замер каталога на 09.09.2026 — 21 холостой прогон против 12
    полезных на шести изменениях.
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


# --- здоровье общей ветки ----------------------------------------------------


def test_a_change_only_check_skipped_on_main_is_not_a_red_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пропуск на общей ветке — объявленное состояние, а не краснота.

    Разметка, фрагмент журнала и авторство коммитов проверяются на изменении, а
    не на `main`: джобы объявлены change-only условием и кладут туда запись
    `skipped`. Считать её отказом значит объявить общую ветку красной ВСЕГДА —
    очередь тогда не сдвинется ни разу. Замер 09.09.2026: первый живой прогон
    шага 8 сообщил «общая ветка красна» по трём пропускам.
    """
    runs = [
        record("lint"),
        record("test"),
        record("pipeline"),
        record("pr-meta", conclusion="skipped"),
        record("journal", conclusion="skipped"),
        record("attribution", conclusion="skipped"),
    ]
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, tok, key=None: iter(runs))
    assert module.branch_health("o/r", "sha", "token") == []


def test_a_real_failure_on_main_still_freezes_the_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Послабление про пропуск не глушит настоящую красноту (097).

    Иначе заморозка перестала бы наступать вовсе, и лечение оказалось бы хуже
    болезни: очередь двигала бы изменения на сломанное основание.
    """
    runs = [record("lint"), record("test", conclusion="failure"), record("pipeline")]
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, tok, key=None: iter(runs))
    problems = module.branch_health("o/r", "sha", "token")
    assert problems and any("test" in problem for problem in problems)


def test_a_skipped_check_on_a_candidate_head_is_still_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """На голове ИЗМЕНЕНИЯ пропуск остаётся отказом (040).

    Послабление сделано для общей ветки и только для неё: иначе выключение
    шага снова стало бы способом обойти гейт.
    """
    runs = [record(name) for name in ("lint", "test", "journal", "attribution", "pipeline")]
    runs.append(record("pr-meta", conclusion="skipped"))
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, tok, key=None: iter(runs))
    problems, _ = module.head_verdict("o/r", change(1, "automerge"), "token")
    assert problems and any("пропущен" in problem for problem in problems)


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


# --- отметка пунктов задачи --------------------------------------------------


def test_the_assigned_source_is_published_as_a_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Очередь выставляет изменению метку присвоенного источника."""
    seen: list[tuple[str, str, Any]] = []
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda method, path, tok, body=None: seen.append((method, path, body)),
    )
    module.publish_source("o/r", change(7, "automerge"), module.RANK_PLAN, "token", dry_run=False)
    assert seen == [("POST", "repos/o/r/issues/7/labels", {"labels": ["source/6"]})]


def test_an_unchanged_source_costs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Метка не переставляется, пока источник не сменился.

    Заход идёт на каждое событие; платить запросом за неизменившееся состояние
    значит тратить квоту на ничто (017).
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("метка не должна переставляться без нужды")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    item = change(7, "automerge", "source/6")
    module.publish_source("o/r", item, module.RANK_PLAN, "token", dry_run=False)


def test_a_changed_source_replaces_the_stale_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сменился источник — старая метка снимается, новая ставится.

    Две метки источника разом означали бы, что изменение принадлежит двум
    источникам сразу; такого состояния нет.
    """
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda method, path, tok, body=None: seen.append((method, path.rsplit("/", 1)[-1])),
    )
    item = change(7, "automerge", "source/6")
    module.publish_source("o/r", item, module.RANK_OWN_RED, "token", dry_run=False)
    assert seen[0] == ("DELETE", "source%2F6")
    assert seen[1][0] == "POST"


def test_a_refused_label_does_not_stop_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ разметки заход не роняет: метка — след, а не вход (084)."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.publish_source("o/r", change(7, "automerge"), module.RANK_PLAN, "token", dry_run=False)


def test_every_source_label_is_declared_in_the_config() -> None:
    """Метка-след объявлена составом наравне со входом.

    Гейт разметки отвергает изменение с меткой, которой нет в составе, — то
    есть очередь могла бы своей же меткой сделать изменение красным (068).
    """
    module.check_labels_declared()


def test_a_held_change_is_reported_after_the_consent_is_gone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Остановленное видно и после того, как согласие с него снято.

    Шаг открытия снимает согласие, увидев стоп-метку. Требовать его в отчёте
    значило бы показывать остановленное ровно до мгновения, когда отмена
    сработала, — и терять из виду то, ради чего отчёт заведён.
    """
    module.report_held([change(7, "hold")])
    assert "#7" in capsys.readouterr().out


def test_labels_are_set_even_when_the_shared_branch_is_red(platform: dict[str, Any]) -> None:
    """Красная общая ветка морозит движение, но не разметку.

    Прежний порядок морозил очередь ДО разметки, и метки застывали ровно
    тогда, когда нужнее всего: по красной ветке надо видеть, кто её чинит, а
    кто просто ждёт. Заморозка — решение о ДВИЖЕНИИ, а источник работы —
    свойство самого изменения.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["health"] = ["lint: failure"]
    module.advance("o/r", "token", "main", dry_run=False)
    assert {number for number, _ in platform["sources"]} == {1, 2}
    assert platform["merged"] == [], "очередь двинулась по красной общей ветке"


def test_a_fix_for_the_shared_branch_keeps_source_zero(platform: dict[str, Any]) -> None:
    """Источник 0 не перебивается своей краснотой.

    Изменение, чинящее общую ветку, стоит работы всей семьи. Своя краснота с
    головы очереди его не снимает — напротив, чинить его надо тем более.
    """
    platform["changes"] = [change(1, "automerge", module.LABEL_FIX_MAIN)]
    platform["runs"] = {1: (["lint: failure"], False)}
    module.advance("o/r", "token", "main", dry_run=False)
    assert (1, module.RANK_MAIN_RED) in platform["sources"]
    assert (1, module.RANK_OWN_RED) not in platform["sources"]


def test_the_tail_of_the_queue_is_labelled_too(platform: dict[str, Any]) -> None:
    """Метку получает и хвост очереди, а не только всё до готовой головы.

    Прежний заход спрашивал вердикт до первой готовой головы и на ней
    останавливался — у хвоста метка отставала на неопределённый срок, и
    очередь по меткам читалась неверно.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge"), change(3, "automerge")]
    module.advance("o/r", "token", "main", dry_run=False)
    assert {number for number, _ in platform["sources"]} == {1, 2, 3}
    assert platform["merged"] == [1], "слита не голова очереди"


def test_the_head_verdict_is_asked_once_per_change(
    platform: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Записи проверок опрашиваются ОДИН раз на кандидата за заход.

    Второй опрос того же дал бы второе состояние того же: между двумя
    обращениями прогон успевает закончиться, и разметка сказала бы одно, а
    движение сделало другое (022).
    """
    asked: list[int] = []

    def counting(repo: str, item: Any, tok: str) -> tuple[list[str], bool]:
        asked.append(item.number)
        return [], False

    monkeypatch.setattr(module, "head_verdict", counting)
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    module.advance("o/r", "token", "main", dry_run=False)
    assert sorted(asked) == [1, 2], f"вердикт спрошен не по разу: {asked}"


def test_the_source_of_a_change_is_decided_without_the_platform() -> None:
    """Источник выводится из самого изменения — проверяется без площадки.

    Разметка и движение решают разное, и решение о ступени обязано быть
    проверяемым отдельно от захода: иначе его правильность видна только на
    подделанном стенде целиком.
    """
    plan = change(1, "automerge")
    assert module.source_of(plan, red=False) == module.RANK_PLAN
    assert module.source_of(plan, red=True) == module.RANK_OWN_RED
    fixing = change(2, "automerge", module.LABEL_FIX_MAIN)
    assert module.source_of(fixing, red=True) == module.RANK_MAIN_RED
