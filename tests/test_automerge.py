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

from dataclasses import replace
from typing import Any, Final

import pytest

from tests.conftest import ROOT, RunScript, load_script

module = load_script("automerge.py")
WORKFLOWS = ROOT / ".github" / "workflows"


def change(
    number: int,
    *marks: str,
    files: tuple[str, ...] = (),
    draft: bool = False,
    base: str = "main",
    body: str = "",
    armed: bool = False,
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
        node=f"PR_{number}",
        armed=armed,
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
        "asked": [],
        "disarmed": [],
        # Снятые метки: у пустой головы источника работы нет.
        "dropped": [],
        "echo": True,
        "swallow": set(),
        "held": {},
        # Сколько файлов трогает изменение. По умолчанию — один: пустая голова
        # это отдельный случай, и объявлять его умолчанием нельзя.
        "files_changed": {},
        # Изменения, на голове которых взгляд ещё идёт (#654).
        "looking": set(),
        # Изменения, которые держит первый вердикт с находками (#734).
        "holding": set(),
    }

    monkeypatch.setattr(module, "open_changes", lambda repo, tok: state["changes"])
    monkeypatch.setattr(
        module, "files_of", lambda repo, number, tok: frozenset(state["files"].get(number, ()))
    )
    monkeypatch.setattr(module, "branch_health", lambda repo, sha, tok: state["health"])

    def platform_call(method: str, path: str, tok: str, body: Any = None) -> dict[str, str]:
        if method == "DELETE" and "/labels/" in path:
            state["dropped"].append(path.rsplit("/", 1)[-1].replace("%2F", "/"))
        return {"sha": "base-sha"}

    monkeypatch.setattr(module.ghrest, "request", platform_call)
    monkeypatch.setattr(
        module,
        "head_look",
        lambda repo, number, tok: module.Head(
            state["states"].get(number, "clean"), state["files_changed"].get(number, 1)
        ),
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
    monkeypatch.setattr(
        module, "awaits_look", lambda repo, item, tok: item.number in state["looking"]
    )
    monkeypatch.setattr(
        module, "findings_hold", lambda repo, item, tok: item.number in state["holding"]
    )
    # Взведение подменяется НА УРОВНЕ МУТАЦИИ, а не целым шагом: между «очередь
    # отдала последнее действие» и «очередь позвала свою функцию» разница ровно
    # в том, доходит ли до площадки НАШЕ тело уплотнения.
    monkeypatch.setattr(module, "fetch", lambda item: None)
    monkeypatch.setattr(module.squash_body, "compose", lambda branch, base: f"тело {branch}")

    def armed(node: str, headline: str, body: str, tok: str) -> dict[str, Any]:
        state["asked"].append((node, headline, body))
        # Тело проглатывается либо у ВСЕХ (`echo: False`), либо у названных
        # номеров (`swallow`): без второго нельзя собрать случай «один отказ,
        # сосед взведён», а именно там и была асимметрия пояснения.
        swallowed = not state["echo"] or int(node.removeprefix("PR_")) in state["swallow"]
        if swallowed:
            return {"enabledAt": "2026-09-12T10:00:00Z"}
        return {"commitHeadline": headline, "commitBody": body}

    monkeypatch.setattr(module.arm, "arm", armed)
    # Что площадка ДЕРЖИТ взведённым, читается отдельно: значок несёт тело
    # момента взведения, и ветка с тех пор могла уехать.
    monkeypatch.setattr(
        module, "held_body", lambda repo, number, tok: state["held"].get(number, ("", ""))
    )
    monkeypatch.setattr(module.arm, "disarm", lambda node, tok: state["disarmed"].append(node))

    # Разметка источника записывается стендом отдельно: проверять надо, что
    # метка ВЫСТАВЛЕНА, а не что о ней напечатано. Замер 09.09.2026: вызов
    # публикации в ветке красного отсутствовал, а тест сверял строку вывода —
    # и потому проходил.
    def publish(repo: str, item: Any, place: int, tok: str, *, dry_run: bool) -> frozenset[str]:
        """Подделка соблюдает контракт: она ОТДАЁТ поставленную метку.

        Настоящая функция возвращает то, что теперь стоит на изменении, — по
        этому ответу заход снимает метку с пустой головы, не спрашивая снимок,
        снятый до записи. Подделка, возвращавшая ничего, гасила бы ровно ту
        связь, ради которой ответ и заведён.
        """
        state["sources"].append((item.number, place))
        return frozenset({module.source_label(place)})

    monkeypatch.setattr(module, "publish_source", publish)
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
    # ИМЕНА БЕРУТСЯ У ОТВЕТА, А НЕ ПИШУТСЯ ЗДЕСЬ СПИСКОМ. Список руками — вторая
    # копия того же, и разошлась она молча на первом же выносе шага в
    # переиспользуемый прогон: имя стало составным, а здесь осталось голым, и
    # «здоровый вход» перестал быть здоровым
    # ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    required = module.policy.names_of(module.policy.load(), module.policy.REQUIRED)
    assert required, "обязательных проверок в ответе нет — здоровый вход не собрать (075)"
    green = [record(name) for name in required]
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


def test_head_look_reads_state_and_size_in_one_request(monkeypatch: Any) -> None:
    """Голова читается одним запросом, и объём приезжает вместе с состоянием."""
    asked: list[str] = []

    def answer(method: str, path: str, token: str, body: Any = None) -> dict[str, Any]:
        asked.append(path)
        return {"mergeable_state": "behind", "changed_files": 3}

    monkeypatch.setattr(module.ghrest, "request", answer)
    look = module.head_look("o/r", 7, "token")
    assert (look.state, look.changed) == ("behind", 3)
    assert asked == ["repos/o/r/pulls/7"], "объём стоил лишнего запроса (052)"


def test_head_look_keeps_silence_apart_from_zero(monkeypatch: Any) -> None:
    """Поля объёма нет — это `None`, а не ноль: молчание не пустота (045)."""
    monkeypatch.setattr(
        module.ghrest, "request", lambda method, path, tok, body=None: {"mergeable_state": "clean"}
    )
    assert module.head_look("o/r", 7, "token").changed is None


def test_an_emptied_head_is_not_revived(platform: dict[str, Any]) -> None:
    """Пустая голова не обновляется, а называется: её содержимое уже в базе.

    13.09.2026 площадка слила #285 уплотнением, но метаданные изменения этого
    не отразили — оно осталось открытым. Очередь увидела «отстало от базы»,
    подтянула базу, и прогоны пошли по второму кругу на дифе, которого больше
    нет. Пустота — состояние ТЕРМИНАЛЬНОЕ (109): закрыть изменение может
    только владелец, а дело очереди — не оживлять его. Разбор — #287.
    """
    platform["changes"] = [change(1, "automerge", armed=True), change(2, "automerge")]
    platform["states"] = {1: module.STATE_BEHIND}
    platform["files_changed"] = {1: 0}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["synced"] == [], "пустую голову подтянули — прогоны пойдут по кругу"
    assert "PR_1" in platform["disarmed"], "значок остался на изменении, которого нет"
    assert platform["merged"] == [2], "очередь встала на пустой голове"


def test_the_queue_names_why_no_head_was_ready(platform: dict[str, Any], capsys: Any) -> None:
    """Итог захода перечисляет НАСТОЯЩИЕ причины, а не две привычные.

    13.09.2026 заход с единственным кандидатом #285 закончился строкой «все
    кандидаты либо красны, либо конфликтуют», а кандидат был ПУСТ. Итог,
    называющий причину наугад, учит не смотреть на итог (045).
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["runs"] = {2: (["lint: failure"], False)}
    platform["files_changed"] = {1: 0}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "готовой головы нет: 1 красны, 1 пусты" in said, said[-300:]


def test_dropping_a_source_touches_nothing_when_there_is_none(
    platform: dict[str, Any],
) -> None:
    """Метки источника нет — площадку не трогают: снимать нечего."""
    module.drop_source("o/r", change(9, "automerge"), "token", dry_run=False)
    assert platform["dropped"] == []


def test_dropping_a_source_keeps_a_dry_run_dry(platform: dict[str, Any]) -> None:
    """Пробный заход рассказывает, а не снимает."""
    module.drop_source("o/r", change(9, "automerge", "source/2"), "token", dry_run=True)
    assert platform["dropped"] == []


def test_an_emptied_head_loses_its_source_label(platform: dict[str, Any]) -> None:
    """У пустой головы снимается метка источника: работы за ней нет.

    Метку ставит перечисление очереди — до того, как спрошен объём, — и пустая
    голова выглядела обычной работой в хвосте плана. Нашёл внешний взгляд
    на #288.
    """
    module.name_the_emptiness("o/r", change(8, "automerge", "source/6"), "token", dry_run=False)
    assert platform["dropped"] == ["source/6"], "метка источника осталась на пустом"


def test_name_the_emptiness_says_it_and_disarms(platform: dict[str, Any], capsys: Any) -> None:
    """Ответ о пустоте: сказать владельцу и снять согласие — ветку не трогать."""
    module.name_the_emptiness("o/r", change(4, "automerge", armed=True), "token", dry_run=False)
    said = capsys.readouterr().out
    assert "ПУСТО" in said and "Закрыть его может владелец" in said, (
        "пустота названа молча — у снятия согласия столько же читателей, сколько у слияния (154)"
    )
    assert platform["disarmed"] == ["PR_4"]
    assert platform["synced"] == []


def test_name_the_emptiness_keeps_a_dry_run_dry(platform: dict[str, Any]) -> None:
    """Пробный заход площадку не трогает: он рассказывает, а не делает."""
    module.name_the_emptiness("o/r", change(5, "automerge", armed=True), "token", dry_run=True)
    assert platform["disarmed"] == []


def test_a_red_head_that_is_empty_is_named_empty(platform: dict[str, Any]) -> None:
    """Пустая голова называется пустой, даже когда её проверки красны.

    Пустое изменение краснеет САМО: гейты отказываются работать без входа — и
    правильно делают (075). Замер 13.09.2026 на #285: голова была и пуста, и
    красна, и очередь назвала только красноту — то есть послала владельца
    искать поломку там, где чинить нечего (045).
    """
    platform["changes"] = [change(1, "automerge", armed=True), change(2, "automerge")]
    platform["runs"] = {1: (["journal: failure"], False)}
    platform["files_changed"] = {1: 0}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert "PR_1" in platform["disarmed"], "у пустой головы остался значок"
    assert platform["synced"] == [], "пустую голову подтянули"
    assert platform["merged"] == [2], "очередь встала на пустой голове"


def test_an_empty_head_loses_the_label_this_very_pass_set(platform: dict[str, Any]) -> None:
    """Метку источника снимает тот же заход, который её поставил.

    ЭТО БЫЛ ДЕФЕКТ, А НЕ МЕЛОЧЬ ОФОРМЛЕНИЯ. Метку ставит перечисление очереди —
    до того, как спрошен объём, — а пустоту головы заход узнаёт позже. Снятие
    же смотрело в `change.marks`, снимок ДО этой записи: свежей метки там нет,
    и заход решал, что снимать нечего. Пустая голова так и оставалась висеть с
    «6 · план», то есть выглядела обычной работой в хвосте очереди — ровно тем,
    что предыдущая починка и убирала. Нашёл внешний взгляд на #311.

    Настоящая разметка здесь не подделывается: проверяется, что DELETE ушёл на
    площадку (135) — по печатной строке это было бы неотличимо от молчания.
    """
    state = platform
    state["changes"] = [change(1, "automerge")]
    state["files_changed"] = {1: 0}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert "source/6" in state["dropped"], (
        "метка источника осталась на пустой голове: снятие смотрит снимок, "
        "снятый до собственной записи"
    )


def test_a_refused_label_does_not_stop_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ по одной метке не оставляет висеть остальные.

    Список для снятия собран из снимка И из записи этого захода, и они
    пересекаются — самый частый отказ здесь 404 по метке, снятой раньше. Один
    `try` на весь цикл обрывался на ней и оставлял стоять ещё висящую: заход
    терял ровно ту метку, ради которой заведён (084). Нашёл внешний взгляд
    на #328.
    """
    ушли: list[str] = []

    def request(method: str, path: str, tok: str, body: Any = None) -> None:
        имя = path.rsplit("/", 1)[-1].replace("%2F", "/")
        if имя == "source/1":
            raise module.ghrest.TransportError("404: метки уже нет")
        ушли.append(имя)

    monkeypatch.setattr(module.ghrest, "request", request)
    module.drop_source(
        "o/r",
        change(7, "automerge", "source/1"),
        "token",
        dry_run=False,
        also=frozenset({"source/6"}),
    )
    assert ушли == ["source/6"], "снятие оборвалось на уже снятой метке"


def test_a_red_head_of_unknown_size_is_treated_as_live(
    platform: dict[str, Any], capsys: Any
) -> None:
    """Площадка не назвала объём красной головы — она живая, а не пустая.

    Тот же разбор на обычной ветке прогонялся, а на красной — нет: ветки две,
    а проверка была одна, и регресс повторился бы молча в половине случаев
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    Нашли внешние взгляды на #290 — двумя записями.
    """
    platform["changes"] = [change(1, "automerge", armed=True), change(2, "automerge")]
    platform["runs"] = {1: (["journal: failure"], False)}
    platform["files_changed"] = {1: None}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "ПУСТО" not in said, "молчание об объёме приняли за пустоту"
    assert "красная проверка" in said, "красная голова не названа красной"
    assert platform["merged"] == [2], "очередь встала на красной голове"


def test_a_head_of_unknown_size_is_treated_as_live(platform: dict[str, Any]) -> None:
    """Площадка не назвала объём — изменение живое, а не пустое (045).

    «Поле не пришло» и «файлов ноль» снаружи одинаковы, и принять молчание за
    пустоту значит снять согласие с живой головы по отсутствию поля.
    """
    platform["changes"] = [change(1, "automerge", armed=True)]
    platform["states"] = {1: module.STATE_BEHIND}
    platform["files_changed"] = {1: None}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["synced"] == [1], "молчание о объёме приняли за пустоту"
    assert platform["disarmed"] == []


def test_a_head_whose_checks_are_running_is_handed_to_the_platform(
    platform: dict[str, Any],
) -> None:
    """Проверки головы идут — очередь ВЗВОДИТ её и уходит, а не ждёт и не обходит.

    Пропустить голову, пока её проверки идут, значило бы обойти порядок:
    следующий за ней слился бы раньше на ровном месте. Ждать внутри захода —
    держать исполнителя и гибнуть в ожидании (замер 10.09.2026: 45 мёртвых
    заходов из 120). Ждёт площадка
    (`docs/decisions/011-merging-is-handed-to-the-platform.md`).
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["states"] = {1: module.STATE_ARMABLE}
    platform["runs"] = {1: ([], True)}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [], "заход слил голову сам, хотя проверки шли"
    assert [node for node, _, _ in platform["asked"]] == ["PR_1"]


def test_the_body_of_the_squash_is_ours_and_it_reaches_the_mutation(
    platform: dict[str, Any],
) -> None:
    """Тело уплотнения собираем МЫ и передаём его взведению.

    Иначе площадка соберёт своё — список коммитов ветки, — и работа
    рассказалась бы в общей ветке столько раз, сколько было правок (`006`).
    """
    platform["changes"] = [change(1, "automerge")]
    platform["states"] = {1: module.STATE_ARMABLE}
    module.advance("o/r", "token", "main", dry_run=False)
    node, headline, body = platform["asked"][0]
    assert node == "PR_1"
    assert headline == "изменение 1 (#1)", "заголовок уплотнения не наш"
    assert body == "тело origin/agent/change-1", "тело уплотнения не наше"


def test_a_swallowed_body_stops_the_step_instead_of_merging_quietly(
    platform: dict[str, Any],
) -> None:
    """Тело не принято — шаг говорит, а не сливает молча (045).

    Это названное условие пересмотра решения 011: уплотнение ушло бы в общую
    ветку не нашим телом, и заметить это было бы нечем.
    """
    platform["changes"] = [change(1, "automerge")]
    platform["states"] = {1: module.STATE_ARMABLE}
    platform["echo"] = False
    # Исход КРАСНЫЙ, а не исключение: голова пропускается, чтобы не держать
    # очередь, но «тело не принято» обязано быть видно вердиктом захода.
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_BROKEN
    assert platform["merged"] == [], "слито с чужим телом уплотнения"


def test_only_the_head_of_the_queue_stays_armed(platform: dict[str, Any]) -> None:
    """Взведённой держится РОВНО ОДНА голова — иначе очередь станет гонкой.

    Площадка сливает взведённое в порядке позеленения, а не вставки. Взведи
    двоих — и порядок вставки перестанет что-либо значить, а он у нас правило,
    а не порядок прибытия (053).
    """
    platform["changes"] = [
        change(1, "automerge"),
        change(2, "automerge", armed=True),
    ]
    platform["states"] = {1: module.STATE_ARMABLE}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["disarmed"] == ["PR_2"], "взведение соседа не снято"
    assert [node for node, _, _ in platform["asked"]] == ["PR_1"]


def test_an_already_armed_head_is_not_armed_twice(platform: dict[str, Any]) -> None:
    """Взведённая голова не взводится заново: площадка уже ждёт ТЕМ ЖЕ телом.

    Повторное взведение стоило бы обращения к площадке на каждом заходе, а
    заходов у очереди столько, сколько прогонов.
    """
    platform["changes"] = [change(1, "automerge", armed=True)]
    platform["states"] = {1: module.STATE_ARMABLE}
    platform["held"] = {1: ("изменение 1 (#1)", "тело origin/agent/change-1")}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["asked"] == [] and platform["disarmed"] == []


def test_a_stale_arming_is_renewed_with_the_new_body(platform: dict[str, Any]) -> None:
    """В ветку дотолкнули — значок несёт СТАРОЕ тело, и его перевзводят.

    Тело собирается в момент взведения; коммит, пришедший позже, площадка
    сольёт телом без него — то есть работа рассказалась бы в общей ветке не
    вся. Сверка идёт с тем, что площадка ДЕРЖИТ, а не с предположением о её
    поведении при толчке (044).
    """
    platform["changes"] = [change(1, "automerge", armed=True)]
    platform["states"] = {1: module.STATE_ARMABLE}
    platform["held"] = {1: ("изменение 1 (#1)", "тело до последнего коммита")}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["disarmed"] == ["PR_1"], "черствое взведение не снято"
    assert [body for _, _, body in platform["asked"]] == ["тело origin/agent/change-1"]


def test_our_own_merge_also_takes_back_a_neighbours_arming(platform: dict[str, Any]) -> None:
    """Сливая старшего САМИ, значок соседа тоже снимаем.

    Иначе мы сливаем голову, а площадка следом сливает взведённого соседа —
    даже если между ними по нашему порядку стоял третий. Это и есть «кто
    первее, того и тапки», от которого очередь и существует (053).
    """
    platform["changes"] = [change(1, "automerge"), change(5, "automerge", armed=True)]
    platform["states"] = {1: "clean"}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["merged"] == [1]
    assert platform["disarmed"] == ["PR_5"], "значок соседа остался висеть"


def test_a_withdrawn_consent_takes_the_arming_back(platform: dict[str, Any]) -> None:
    """Согласие снято — взведение снимается тем же заходом (147).

    Метка `hold`, снятая `automerge`, черновик: всё это выводит изменение из
    кандидатов, а взведение, оставшееся на нём, однажды сольёт его без согласия.
    """
    platform["changes"] = [change(7, "automerge", "hold", armed=True)]
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["disarmed"] == ["PR_7"]


def test_a_frozen_queue_takes_back_what_was_armed(platform: dict[str, Any]) -> None:
    """Заморозка СНИМАЕТ взведённое, а не только не выдаёт новое.

    Не выдавать нового согласия недостаточно: взведённое площадка сольёт сама,
    как только проверки позеленеют, — и заморозка, которая только молчит,
    ничего не держит (126).
    """
    platform["changes"] = [change(1, "automerge", armed=True), change(9, "automerge", "fix-main")]
    platform["health"] = ["test: failure"]
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["disarmed"] == ["PR_1"]
    assert platform["merged"] == [9], "починка не прошла через заморозку"


def test_the_arming_is_taken_back_before_our_own_merge(platform: dict[str, Any]) -> None:
    """Зелёную голову сливаем САМИ — и снимаем с неё взведение перед этим.

    Брошенное согласие переживает слитое изменение в глазах площадки: она
    помнит его и на закрытом.
    """
    platform["changes"] = [change(1, "automerge", armed=True)]
    platform["states"] = {1: "clean"}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["disarmed"] == ["PR_1"]
    assert platform["merged"] == [1]


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

    Список разрешительный (068): на `unknown` и на пустом ответе площадка
    слияния не даст, и её отказ уронил бы ВЕСЬ заход вместо одной головы.
    Проверяется обоими значениями сразу — иначе разрешительный список
    неотличим от запретительного, где перечислены ровно эти два.

    `blocked` сюда не входит: он значит «слить нельзя СЕЙЧАС», и его очередь
    отдаёт площадке отдельным путём.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge"), change(3, "automerge")]
    platform["states"] = {1: "unknown", 2: ""}
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
    # Имена берутся у ответа по той же причине, что и у здорового входа выше:
    # второй список разошёлся бы молча. Пропускается ОДИН из обязательных —
    # какой именно, значения не имеет, важен сам пропуск.
    required = module.policy.names_of(module.policy.load(), module.policy.REQUIRED)
    assert len(required) > 1, "обязательных меньше двух — пропуск одного не проверить (075)"
    runs = [record(name) for name in required[1:]]
    runs.append(record(required[0], conclusion="skipped"))
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


def test_a_paused_change_is_not_a_candidate() -> None:
    """Метка заморозки снимает изменение с очереди так же, как `hold`.

    Владелец у метки при этом ДРУГОЙ: `hold` ставит человек, `paused/main-red` —
    шаг 9 на время заморозки. Для очереди действие одно, и читать его вторым
    способом значило бы развести два понимания одной остановки (022).
    """
    остановленные = [change(1, "automerge", module.LABEL_PAUSED), change(2, "automerge", "hold")]
    assert module.candidates(остановленные, "main") == []
    assert module.candidates([change(3, "automerge")], "main") != []


def test_the_pause_names_its_owner_in_the_report(capsys: pytest.CaptureFixture[str]) -> None:
    """В отчёте видно, КТО остановил: человек меткой `hold` или заморозка (154)."""
    module.report_held([change(7, "hold"), change(8, module.LABEL_PAUSED)])
    said = capsys.readouterr().out
    assert "#7" in said and "«hold»" in said
    assert "#8" in said and f"«{module.LABEL_PAUSED}»" in said


def test_the_pause_label_is_declared_in_the_tree() -> None:
    """Имя метки — вход механизма, и оно объявлено в составе, а не в коде (064)."""
    module.check_labels_declared()
    said = (ROOT / ".github" / "labels.yml").read_text(encoding="utf-8")
    assert module.LABEL_PAUSED in said


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


def test_taking_the_arming_back_names_its_reason(
    platform: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Снятие согласия называет причину и НИЧЕГО не делает на пробном заходе.

    «Почему сняли» имеет ровно столько же читателей, сколько само слияние
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)),
    а пробный заход обязан оставаться показом, а не действием (104).
    """
    module.take_back("o/r", change(5, "automerge"), "проверяю показ", "token", dry_run=True)
    assert platform["disarmed"] == [], "пробный заход тронул площадку"
    assert "проверяю показ" in capsys.readouterr().out

    module.take_back("o/r", change(5, "automerge"), "а теперь всерьёз", "token", dry_run=False)
    assert platform["disarmed"] == ["PR_5"]


def test_handing_over_shows_the_body_instead_of_arming_on_a_dry_run(
    platform: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Пробный заход ПОКАЗЫВАЕТ тело уплотнения, а не взводит.

    Проверяется прямым вызовом, а не через весь заход: показ — отдельное
    обещание шага, и ломаться оно может отдельно от порядка очереди.
    """
    head = change(4, "automerge")
    module.hand_over("o/r", head, [head], "token", dry_run=True)
    assert platform["asked"] == [], "пробный заход взвёл слияние"
    assert "тело origin/agent/change-4" in capsys.readouterr().out


def test_only_the_named_head_keeps_its_arming(platform: dict[str, Any]) -> None:
    """Прямой вызов: названная голова значок сохраняет, соседи — нет.

    Проверяется отдельно от захода, потому что зовётся из ДВУХ путей — «взвожу»
    и «сливаю сам», — и щель была именно в том, что на втором пути этого вызова
    не было (053).
    """
    head = change(1, "automerge", armed=True)
    queue = [head, change(5, "automerge", armed=True), change(7, "automerge")]
    module.keep_only("o/r", head, queue, "token", dry_run=False)
    assert platform["disarmed"] == ["PR_5"], "снято не то взведение"


def test_what_the_platform_holds_is_read_by_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Взведённое ЧИТАЕТСЯ обычным REST: поле `auto_merge` приходит с изменением.

    Взвести дешевле нельзя — у мутации нет REST-эквивалента, — а прочитать
    можно, и «раз уж пошли в GraphQL, спросим и это» — ровно тот путь, которым
    у соседей выросли 2436 строк из 131 (001).
    """
    seen: list[tuple[str, str]] = []

    def request(method: str, path: str, tok: str, body: Any = None) -> dict[str, Any]:
        seen.append((method, path))
        return {"auto_merge": {"commit_title": "изменение 1 (#1)", "commit_message": "тело"}}

    monkeypatch.setattr(module.ghrest, "request", request)
    assert module.held_body("o/r", 1, "token") == ("изменение 1 (#1)", "тело")
    assert seen == [("GET", "repos/o/r/pulls/1")]


def test_a_change_without_an_arming_holds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Значка нет — читается пустое, а не падает: это законное состояние."""
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: {"auto_merge": None})
    assert module.held_body("o/r", 1, "token") == ("", "")


def test_an_arming_without_body_fields_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Взведение есть, а полей тела в ответе нет — отказ ВСЛУХ, а не пустота.

    Имена полей были объявлены по памяти, а не замером, и внешний взгляд назвал
    это на #234. Пустая строка вместо отсутствующего поля читалась бы как «тело
    у площадки другое», и заход снимал бы и взводил значок на КАЖДОМ проходе,
    не сходясь никогда (045).
    """
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda *a, **k: {"auto_merge": {"enabled_by": {"login": "ArtVsMark"}}},
    )
    with pytest.raises(module.NotRun) as caught:
        module.held_body("o/r", 1, "token")
    assert "полей тела в ответе нет" in str(caught.value)
    assert "enabled_by" in str(caught.value), "отказ не назвал, что пришло вместо них"


def test_an_arming_on_a_foreign_base_is_left_alone(platform: dict[str, Any]) -> None:
    """Значок на изменении в ЧУЖУЮ базу очередь не трогает.

    Предмет очереди — вставка в её собственную ветку; значок на изменении,
    нацеленном в другую базу, поставлен не ею, и снимать его значит
    распоряжаться чужим согласием. Нашёл внешний взгляд на #232.
    """
    platform["changes"] = [
        change(3, "automerge", "hold", armed=True, base="release/1.x"),
        change(4, "automerge", "hold", armed=True),
    ]
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["disarmed"] == ["PR_4"], "снят значок с чужой базы"


def test_a_refused_arming_skips_the_head_instead_of_felling_the_pass(
    platform: dict[str, Any],
) -> None:
    """Отказ взведения — отказ по ЭТОЙ голове, а не по всему заходу.

    Форма ответа площадки не та, тело не принято, мутация отвергнута — очередь
    обязана идти дальше, как на красной и конфликтной голове. Иначе одна
    странная голова держит всю очередь до вмешательства человека (051). Нашёл
    внешний взгляд на #236.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["states"] = {1: module.STATE_ARMABLE, 2: "clean"}
    platform["echo"] = False
    # Сосед слит — очередь не встала; исход красный — отказ не исчез (045).
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_BROKEN
    assert platform["merged"] == [2], "заход упал на первой голове вместо того, чтобы идти дальше"


def test_a_red_outcome_is_explained_on_both_paths(
    platform: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Красный исход после чужого отказа поясняется и на пути ВЗВЕДЕНИЯ.

    Прежде пояснение печаталось только там, где заход сливал сам, — и красное
    при взведённой голове выглядело противоречием «взвёл и покраснел». Нашёл
    внешний взгляд на #245.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge")]
    platform["states"] = {1: module.STATE_ARMABLE, 2: module.STATE_ARMABLE}
    platform["swallow"] = {1}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_BROKEN
    said = capsys.readouterr().out
    assert "исход красный" in said, said
    assert [node for node, _, _ in platform["asked"]] == ["PR_1", "PR_2"], platform["asked"]


def test_a_head_waits_for_the_look_before_it_is_armed(platform: dict[str, Any]) -> None:
    """Голова, на которой идёт взгляд, не сливается и не взводится (#654, вариант 3).

    Замер смены 23–24.09.2026: 30 из 32 слитых изменений догоняли находки
    взгляда на уже слитом. Взведённую голову ожидание снимает — иначе
    площадка слила бы её сама; очередь идёт дальше к следующему кандидату.
    """
    platform["changes"] = [change(1, "automerge", armed=True), change(2, "automerge")]
    platform["looking"] = {1}
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["disarmed"] == ["PR_1"]
    assert platform["merged"] == [2], "голова, ждущая взгляда, слита или держит очередь"


def test_a_finished_look_lets_the_head_go(platform: dict[str, Any]) -> None:
    """Вторая половина: взгляд завершился — голова сливается как прежде."""
    platform["changes"] = [change(1, "automerge")]
    assert module.advance("o/r", "token", "main", dry_run=False) == module.EXIT_OK
    assert platform["merged"] == [1]


@pytest.mark.parametrize(
    ("runs", "pending"),
    [
        ([{"name": "review", "status": "in_progress"}], True),
        ([{"name": "review", "status": "queued"}], True),
        ([{"name": "review", "status": "completed", "conclusion": "failure"}], False),
        ([{"name": "review", "status": "completed", "conclusion": "skipped"}], False),
        ([{"name": "test", "status": "in_progress"}], False),
        ([], False),
    ],
    ids=["идёт", "в очереди", "упал", "пропущен", "чужая запись", "записи нет"],
)
def test_the_look_is_awaited_only_while_it_runs(runs: list[dict[str, Any]], pending: bool) -> None:
    """Ждётся только идущий взгляд: исход не судится, отсутствие записи не держит.

    Взгляд совещательный (051) — упавший или пропущенный слияние не держит.
    Записи нет — взгляд не запускался, и ждать некого: молчание называет
    реестр слитого без взгляда, а не очередь.
    """
    assert module.look_pending(runs) is pending


def test_awaiting_the_look_asks_the_review_record_of_the_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`awaits_look` спрашивает запись проверки взгляда на голове изменения."""
    asked: list[str] = []

    def paginate(path: str, tok: str, key: str | None = None) -> Any:
        asked.append(path)
        return iter([{"name": "review", "status": "in_progress"}])

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    item = change(1, "automerge")
    assert module.awaits_look("o/r", item, "token") is True
    assert asked == [f"repos/o/r/commits/{item.head}/check-runs?check_name=review"]


def test_a_head_behind_the_base_is_synced_before_the_look_is_awaited(
    platform: dict[str, Any],
) -> None:
    """Отставшую голову подтягивают, не дожидаясь старого взгляда (`14207cf`).

    Подтяжка всё равно отправит голову на новый взгляд: ждать старого значило
    бы ждать дважды, а при подвижной общей ветке — голодать.
    """
    platform["changes"] = [change(1, "automerge")]
    platform["states"] = {1: module.STATE_BEHIND}
    platform["looking"] = {1}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["synced"] == [1]


def test_a_repair_of_the_shared_branch_does_not_wait_for_the_look(
    platform: dict[str, Any],
) -> None:
    """Починка общей ветки взгляда не ждёт: заморозка стоит на ней (`f3c79a7`)."""
    platform["changes"] = [change(9, "automerge", "fix-main")]
    platform["health"] = ["test: failure"]
    platform["looking"] = {9}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["merged"] == [9]


def test_a_push_wakes_the_queue() -> None:
    """Толчок в изменение зовёт очередь — иначе взведение переживёт новый взгляд (`865341e`).

    Площадка слила бы взведённую голову по зелёному `ci` раньше, чем взгляд
    по новой голове скажет; снять взведение успевает только заход по самому
    толчку.
    """
    import yaml

    said = yaml.safe_load((ROOT / ".github" / "workflows" / "automerge.yml").read_text("utf-8"))
    events = said[True] if True in said else said["on"]
    assert "synchronize" in events["pull_request"]["types"]
    assert "review" in events["workflow_run"]["workflows"]


def test_a_forgotten_repair_label_on_a_green_branch_still_waits(
    platform: dict[str, Any],
) -> None:
    """Метка `fix-main` на ЗЕЛЁНОЙ общей ветке ожидания взгляда не снимает.

    Общую ветку починило другое изменение, а метка осталась: обход по одной
    метке слил бы голову без взгляда (взгляд на #735).
    """
    platform["changes"] = [change(9, "automerge", "fix-main")]
    platform["looking"] = {9}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["merged"] == []


def test_syncing_a_head_takes_back_an_armed_neighbour(platform: dict[str, Any]) -> None:
    """Подтяжка отставшей головы снимает взведение соседа до выхода (взгляд на #735).

    Толчок во взведённое изменение ниже зовёт заход; подтянув чужую голову и
    выйдя, заход оставил бы соседа взведённым — и площадка слила бы его раньше
    нового взгляда.
    """
    platform["changes"] = [change(1, "automerge"), change(2, "automerge", armed=True)]
    platform["states"] = {1: module.STATE_BEHIND}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["synced"] == [1]
    assert platform["disarmed"] == ["PR_2"]


def test_the_first_verdict_with_findings_holds_the_head(platform: dict[str, Any]) -> None:
    """Первый вердикт с находками держит голову до толчка с починкой (#734).

    Решение владельца 24.09.2026, «держать одну голову»: окно, чтобы починка
    ехала в ту же ветку, а не новым изменением. Взведённую голову держание
    снимает; очередь идёт к следующему.
    """
    platform["changes"] = [change(1, "automerge", armed=True), change(2, "automerge")]
    platform["holding"] = {1}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["disarmed"] == ["PR_1"]
    assert platform["merged"] == [2]


#: Прогон взгляда по изменению и прогон ответчика `claude.yml` — оба пишет
#: `claude[bot]`, различает их только шапка «View job».
LOOK_RUN: Final = "35976997147"
ANSWER_RUN: Final = "35984970999"


def verdict(
    when: str,
    count: int,
    *,
    late: bool = False,
    human: bool = False,
    run: str = LOOK_RUN,
    created: str = "",
) -> dict[str, Any]:
    """Комментарий взгляда с вердиктом — как его пишет бот (или цитирует человек).

    `when` — когда вердикт вписан; `created` — когда комментарий создан:
    действие создаёт его в начале захода, а вердикт вписывает в конце.
    """
    marker = f"{module.unlooked.LATE_MARKER}\n" if late else ""
    head = f"**Claude finished** —— [View job](https://github.com/o/r/actions/runs/{run})\n"
    return {
        "created_at": created or when,
        "updated_at": when,
        "user": {"type": "User" if human else "Bot"},
        "body": f"{marker}{head}разбор\nВЕРДИКТ: находок {count}",
    }


HEAD_AT: Final = "2026-09-24T10:00:00Z"


@pytest.mark.parametrize(
    ("comments", "holds"),
    [
        ([verdict("2026-09-24T10:05:00Z", 2)], True),
        ([verdict("2026-09-24T09:00:00Z", 1), verdict("2026-09-24T10:05:00Z", 2)], False),
        ([verdict("2026-09-24T09:00:00Z", 0), verdict("2026-09-24T10:05:00Z", 3)], True),
        ([verdict("2026-09-24T10:05:00Z", 0)], False),
        ([verdict("2026-09-24T09:00:00Z", 2)], False),
        ([verdict("2026-09-24T10:05:00Z", 2, late=True)], False),
        ([], False),
        (
            [verdict("2026-09-24T10:05:00Z", 2), verdict("2026-09-24T10:06:00Z", 0, human=True)],
            True,
        ),
        (
            [
                verdict("2026-09-24T10:05:00Z", 2),
                verdict("2026-09-24T10:06:00Z", 0, run=ANSWER_RUN),
            ],
            True,
        ),
        (
            [
                verdict("2026-09-24T09:00:00Z", 1, run=ANSWER_RUN),
                verdict("2026-09-24T10:05:00Z", 2),
            ],
            True,
        ),
        (
            [
                verdict("2026-09-24T10:06:00Z", 2, created="2026-09-24T09:59:00Z"),
                verdict("2026-09-24T10:08:00Z", 2),
            ],
            True,
        ),
    ],
    ids=[
        "первый с находками",
        "второй с находками",
        "первый после чистого",
        "чисто",
        "вердикт старой головы",
        "поздний взгляд",
        "вердиктов нет",
        "цитата человека",
        "цитата ответчика",
        "цитата ответчика до головы",
        "вердикт прежней головы вписан после подтяжки",
    ],
)
def test_only_the_first_verdict_with_findings_holds(
    comments: list[dict[str, Any]], holds: bool
) -> None:
    """Держит ровно первый вердикт с находками по этой голове — цикла нет (#734).

    Вердикт с находками по прежней голове уже держал её: второго держания нет,
    сколько бы находок ни пришло — ревьюер повторяет неснятые дословно, и
    «держать, пока есть находки» стало бы вечным циклом. Вердикт по старой
    голове новую не держит (взгляд промолчал), поздний взгляд — не о голове.
    """
    looks = frozenset({LOOK_RUN})
    assert module.holds_for_findings(module.verdicts_on(comments, looks), HEAD_AT) is holds


def test_the_hold_reads_the_head_time_and_the_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Время головы — начало взгляда по ней, а не дата коммита (`e09a581`).

    Коммит, сделанный до вердикта и толкнутый после, по дате коммитера
    выглядел старше вердикта; начало взгляда по голове — время толчка.
    Записи взгляда нет — держать нечем. Прогоны взгляда читаются и с прежних
    голов изменения: вердикт прежней головы решает, держали ли уже (`1d79af0`).
    """
    job = "https://github.com/o/r/actions/runs/{}/job/1"
    runs = {
        "head-sha": [
            {"name": "review", "started_at": HEAD_AT, "details_url": job.format(LOOK_RUN)}
        ],
        "old-sha": [{"name": "review", "details_url": job.format("111")}],
    }
    said = [verdict("2026-09-24T09:00:00Z", 1, run="111"), verdict("2026-09-24T10:05:00Z", 1)]

    events: list[dict[str, Any]] = []

    def paginate(path: str, tok: str, key: str | None = None) -> Any:
        if "check-runs" in path:
            return iter(list(runs[path.split("/commits/")[1].split("/")[0]]))
        if path.endswith("/commits"):
            return iter([{"sha": "old-sha"}, {"sha": "head-sha"}])
        if path.endswith("/events"):
            return iter(events)
        return iter(said)

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    head = replace(change(1, "automerge"), head="head-sha")
    assert module.look_runs("o/r", "old-sha", "token") == runs["old-sha"]
    assert module.findings_hold("o/r", head, "token") is False
    said.pop(0)
    assert module.findings_hold("o/r", head, "token") is True
    # Прежняя голова ушла перезаписью: её прогона среди коммитов нет, и
    # вердикт с находками по ней засчитывается прежним (взгляд на #743) —
    # но только когда перезапись была.
    said.insert(0, verdict("2026-09-24T09:00:00Z", 1, run="222"))
    assert module.findings_hold("o/r", head, "token") is True
    events.append({"event": "head_ref_force_pushed"})
    assert module.force_pushed("o/r", head, "token") is True
    assert module.findings_hold("o/r", head, "token") is False
    said.pop(0)
    assert module.findings_hold("o/r", head, "token") is True
    runs["head-sha"].clear()
    assert module.findings_hold("o/r", head, "token") is False


def test_a_held_head_in_conflict_is_published_as_a_source(platform: dict[str, Any]) -> None:
    """Держимая голова в конфликте публикуется источником работы (`999d49b`).

    Держание стояло выше конфликта, и конфликтная голова до толчка не
    называлась источником 004: окно не знало, что чинить надо и конфликт.
    """
    platform["changes"] = [change(1, "automerge")]
    platform["states"] = {1: module.STATE_CONFLICT}
    platform["holding"] = {1}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["sources"][-1] == (1, module.RANK_CONFLICT)
    assert platform["merged"] == []


def test_a_held_head_behind_the_base_is_not_synced(platform: dict[str, Any]) -> None:
    """Держимая голова не подтягивается: коммит слияния очереди — не починка (`f1b9f3f`).

    Подтяжка шла раньше держания, и новый коммит слияния снимал держание без
    починки: вердикт по подтянутой голове был уже вторым.
    """
    platform["changes"] = [change(1, "automerge")]
    platform["states"] = {1: module.STATE_BEHIND}
    platform["holding"] = {1}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["synced"] == []
    assert platform["merged"] == []


def test_a_repair_of_a_red_branch_is_not_held_by_findings(platform: dict[str, Any]) -> None:
    """Починку красной общей ветки держание находками не задерживает (#734)."""
    platform["changes"] = [change(9, "automerge", "fix-main")]
    platform["health"] = ["test: failure"]
    platform["holding"] = {9}
    module.advance("o/r", "token", "main", dry_run=False)
    assert platform["merged"] == [9]
