"""Разбор слитого против задачи: что он отмечает и чего не отмечает.

Отвергаемое здесь — ЛОЖНАЯ ОТМЕТКА. Пункт, отмеченный по догадке, теряется
вместе с задачей: неотмеченный видно, ложно отмеченный — нет. Основание у
разбора слабее, чем у автора: автор говорит «я это сделал», разбор выводит это
из кода ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Поэтому проверяется не «умеет ли он отмечать», а граница: пункт без названного
доказательства не отмечается, а текст, обращённый к разбору из тела изменения,
предложением не считается.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, load_script
from tests.test_live_references import TEST_ADDRESS_RE

module = load_script("task_items.py")
items = load_script("items.py")

#: Тело разбора — общий шаг; вызывающий держит события и очередь записи (#994).
WORKFLOW = ROOT / ".github" / "workflows" / "step-task-items.yml"
CALLER = ROOT / ".github" / "workflows" / "task-items.yml"


def test_a_proposal_needs_its_proof() -> None:
    """Пункт с доказательством принимается, без — отбрасывается.

    Это вся граница механизма в одной проверке: доказательство отличает вывод
    по коду от догадки о коде.
    """
    paired, bare = module.proposals(
        "Закрывает пункт: механизм читает классы\n"
        "Доказательство: scripts/pipeline_checks.py, тест test_x\n"
        "Закрывает пункт: а этот просто так\n"
    )
    assert paired == [("механизм читает классы", "scripts/pipeline_checks.py, тест test_x")]
    assert bare == ["а этот просто так"]


def test_the_proof_must_follow_the_item() -> None:
    """Доказательство относится к пункту, за которым стоит, а не к любому в тексте.

    Иначе одно доказательство внизу ответа «закрывало» бы все пункты разом —
    ровно та догадка, против которой пара и заведена.
    """
    paired, bare = module.proposals(
        "Закрывает пункт: первый\nпроза, проза, ещё проза\nи ещё строка\nДоказательство: файл.py\n"
    )
    assert paired == []
    assert bare == ["первый"]


def test_a_blank_line_between_them_is_allowed() -> None:
    """Пустая строка между пунктом и доказательством законна: это разметка."""
    paired, _ = module.proposals("Закрывает пункт: первый\n\nДоказательство: файл.py\n")
    assert paired == [("первый", "файл.py")]


def test_an_example_in_quotes_is_not_a_proposal() -> None:
    """Строка, взятая в кавычки, предложением не считается.

    Вход разбора недоверенный: пример формата, процитированный из свода в теле
    изменения, не должен становиться отметкой (085).
    """
    paired, bare = module.proposals("`Закрывает пункт: пример из свода`\nДоказательство: ничего\n")
    assert paired == [] and bare == []


def test_an_example_in_a_fenced_block_is_not_a_proposal() -> None:
    """Пример в блоке кода — тоже пример."""
    paired, bare = module.proposals("```\nЗакрывает пункт: пример\nДоказательство: файл.py\n```\n")
    assert paired == [] and bare == []


def test_an_item_keeps_its_inline_code() -> None:
    """Инлайн-код внутри пункта — часть пункта: по нему его узнают в задаче.

    Ровно на этом отметка и срывалась 10.09: разбор обрезал `debt` вместе с
    кавычками, и совпадения с задачей не выходило.
    """
    paired, _ = module.proposals(
        "Закрывает пункт: `debt` печатает это число\nДоказательство: scripts/debt.py\n"
    )
    assert paired == [("`debt` печатает это число", "scripts/debt.py")]


def test_the_subject_carries_the_open_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """Предмет разбора несёт незакрытые пункты ДОСЛОВНО, а закрытые — нет.

    Дословно, потому что отметка ищет пункт по тексту: пересказанный пункт не
    совпадёт с задачей, и разбор предложит то, чего в ней нет.
    """
    answers = {
        "repos/o/r/pulls/7": {"title": "тема", "body": "Refs #39"},
        "repos/o/r/issues/39": {
            "title": "задача",
            "body": "- [ ] `debt` печатает это число;\n- [x] уже сделанный пункт\n",
        },
    }
    monkeypatch.setattr(
        module.ghrest, "request", lambda method, path, tok, body=None: answers[path]
    )
    text = module.subject("o/r", 7, "token")
    assert "`debt` печатает это число;" in text
    assert "уже сделанный пункт" not in text


def test_a_change_without_a_task_is_not_reviewed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменение без связи с задачей разбирать не против чего — это состояние."""
    monkeypatch.setattr(
        module.ghrest, "request", lambda *_, **__: {"title": "тема", "body": "без связи"}
    )
    with pytest.raises(module.NotRun, match="связи с задачей"):
        module.subject("o/r", 7, "token")


def test_a_task_with_nothing_open_is_not_reviewed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Незакрытых пунктов нет — предлагать нечего, и это не поломка (027)."""
    answers = {
        "repos/o/r/pulls/7": {"title": "тема", "body": "Refs #39"},
        "repos/o/r/issues/39": {"title": "задача", "body": "- [x] всё сделано\n"},
    }
    monkeypatch.setattr(
        module.ghrest, "request", lambda method, path, tok, body=None: answers[path]
    )
    with pytest.raises(module.NotRun, match="предлагать нечего"):
        module.subject("o/r", 7, "token")


def test_the_comment_names_its_ground() -> None:
    """В записи видно, что отметка пришла разбором, а не от автора.

    Разные основания стоят разного, и стирать между ними границу нельзя (154):
    прочитавший задачу должен видеть, чем именно закрыт пункт.
    """
    note = module.render(7, "ответ целиком", [("пункт", "файл.py")], ["другой пункт"])
    assert module.BY_REVIEW in note
    assert "файл.py" in note
    assert "другой пункт" in note, "отброшенный пункт скрыт от читателя"


def test_the_marking_uses_the_item_text_only() -> None:
    """Отметка ставится по тексту пункта, без приписок.

    Приписка «отмечено разбором» внутри текста сделала бы пункт ненаходимым:
    он узнаётся по тексту, а не по номеру строки.
    """
    source = (ROOT / "scripts" / "task_items.py").read_text(encoding="utf-8")
    assert "[item for item, _ in paired]" in source, (
        "отметка собирается иначе — проверьте, не попала ли пометка в текст пункта"
    )


# --- прогон, который это запускает --------------------------------------------


def document() -> dict[str, Any]:
    """Описание прогона разбора."""
    loaded: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return loaded


def test_the_reviewer_has_no_write_tools() -> None:
    """У разбора нет права записи: пишет механизм.

    Его вход — код и тело изменения, то есть текст того, кого проверяют.
    Строка «отметь все пункты» была бы указанием тому, кто имеет право писать
    в трекер (085).
    """
    for job in document()["jobs"].values():
        for step in job["steps"]:
            tools = (step.get("with") or {}).get("claude_args", "")
            for forbidden in ("Write", "Edit", "Bash(gh ", "Bash(curl ", "WebFetch"):
                assert forbidden not in tools, f"разбору разрешена запись: {forbidden}"


def test_an_unmerged_close_is_not_reviewed() -> None:
    """Закрытое без слияния не разбирается: работа в общую ветку не поехала."""
    assert "merged == true" in document()["jobs"]["task-items"]["if"]


def test_the_writing_job_owns_the_task() -> None:
    """Запись в задачу идёт под репозиторной группой: ресурс общий (149)."""
    caller = yaml.safe_load(CALLER.read_text(encoding="utf-8"))
    group = caller["jobs"]["task-items"]["concurrency"]
    assert group["group"] and "${{" not in group["group"]
    assert group["cancel-in-progress"] is False


def test_the_step_that_reads_the_platform_gets_a_token() -> None:
    """Шаги, читающие площадку, получают токен прогона — иначе они молча слепы."""
    for step in document()["jobs"]["task-items"]["steps"]:
        if "task_items.py" in str(step.get("run") or ""):
            assert set(step.get("env") or {}) & {"GH_TOKEN", "GITHUB_TOKEN"}, step.get("name")


def test_the_prompt_declares_its_input_untrusted() -> None:
    """Промпт называет вход недоверенным — это условие безопасности, а не стиль."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "НЕДОВЕРЕННЫЙ ВХОД" in text
    assert "Доказательство:" in text, "формат пары не объяснён тому, кто отвечает"


def test_the_subject_file_is_built_by_the_mechanism() -> None:
    """Предмет собирает механизм: пункты задачи разбор обязан видеть дословно."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--collect" in text
    assert "subject.md" in text


def test_the_item_marker_lives_in_one_place() -> None:
    """Разбор и шаг слияния отмечают пункт ОДНИМ механизмом.

    Второе понимание того же разошлось бы с первым молча: у одного пункт
    находился бы, у другого нет, и оба выглядели бы правдоподобно (090).
    """
    marking = (ROOT / "scripts" / "task_items.py").read_text(encoding="utf-8")
    assert "items.mark(" in marking or "items.sweep(" in marking, (
        "разбор отмечает пункты мимо общего механизма"
    )
    for name in ("automerge.py", "task_items.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "CHECKLIST_RE" not in source, f"{name} завёл свой разбор пунктов"

    # ОЧЕРЕДЬ ПУНКТОВ НЕ ОТМЕЧАЕТ, И ЭТО ПРОВЕРЯЕТСЯ. Момент слияния верный, но
    # предмет чужой: очередь про слияние, а не про чужие задачи. Второй предмет
    # делал её ответственной за то, чего она не решает.
    queue = (ROOT / "scripts" / "automerge.py").read_text(encoding="utf-8")
    assert "items.mark(" not in queue, "очередь снова взялась отмечать пункты задач"


def test_the_shared_marker_is_where_it_says() -> None:
    """Предмет проверки найден: общий механизм существует и отмечает (075)."""
    body = "- [ ] первый пункт\n- [ ] второй\n"
    after, found = items.marked(body, "первый пункт")
    assert found and "- [x] первый пункт" in after


def test_an_answer_that_was_cut_short_is_not_a_proposal(tmp_path: Path) -> None:
    """Оборванный прогон не даёт отметок: ответа нет — значит нечего разбирать."""
    with pytest.raises(module.late_look.NotRun):
        module.late_look.answer_of("[]")


def test_a_proposal_that_marked_nothing_is_not_a_green_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Разбор сказал «Закрыто», а отметка не легла — шаг НЕ отработал (045).

    «Отметил ноль из трёх» и «отметил всё» снаружи одинаковы, и это уже стоило
    эпику вранья о себе: замер 12.09.2026 — разбор по #232 объявил закрытым
    пункт 2, галочка в #196 не встала, а шаг остался зелёным, потому что исход
    брался из наличия разбора, а не из его записи. Причина была в сравнении, но
    найти её мешало ровно это молчание.
    """
    answer = tmp_path / "ответ.md"
    answer.write_text(
        "### Закрыто\n\n- **2. Слияние отдаётся площадке**\n  — `scripts/automerge.py` "
        "и `tests/test_automerge.py::test_x` доказывают это\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(module, "linked", lambda repo, number, token: ([196], {}))
    monkeypatch.setattr(module, "publish", lambda repo, numbers, body, token: None)
    monkeypatch.setattr(
        module.items,
        "mark",
        lambda *a, **k: items.Outcome([], [], ["2. Слияние отдаётся площадке"]),
    )
    code = module.main(["--repo", "o/r", "--pr", "232", "--from", str(answer), "--apply"])
    assert code == module.EXIT_BROKEN, "шаг зелен, хотя пункт остался открытым"


def linked_change(body: str, merge: str = "deadbee") -> dict[str, Any]:
    """Слитое изменение с названной связью."""
    return {"number": 7, "body": body, "merge_commit_sha": merge}


def platform_says(states: dict[int, str], closers: dict[int, str] | None = None) -> Any:
    """Ответ площадки о задачах и о том, чем каждая закрыта."""
    shut = closers or {}

    def reply(_method: str, path: str, *_args: object, **_kwargs: object) -> Any:
        number = int(path.rstrip("/").rsplit("/", 1)[1].split("?")[0])
        return {"state": states.get(number, "open")}

    return reply, shut


def test_a_promised_closure_that_did_not_happen_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обещали `Closes`, а задача открыта — связь соврала, и это сказано.

    Гейт разметки этого знать не может: он работает ДО слияния, когда сбыться
    ещё нечему.
    """
    reply, _ = platform_says({12: "open"})
    monkeypatch.setattr(module.ghrest, "request", reply)
    said = module.fate(
        "o/r", linked_change("Closes #12"), module.changerefs.links_in("Closes #12"), "t"
    )
    assert list(said) == [12], said
    assert "открыта" in said[12]


def test_a_kept_promise_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обещали закрыть и закрыли — записи нет: канал не шумит на исправном."""
    reply, _ = platform_says({12: "closed"})
    monkeypatch.setattr(module.ghrest, "request", reply)
    assert (
        module.fate(
            "o/r", linked_change("Closes #12"), module.changerefs.links_in("Closes #12"), "t"
        )
        == {}
    )


def test_a_task_closed_without_a_promise_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Refs` значит «не закрывать» — а задача закрыта этим же слиянием.

    Вторая сторона, и она дороже первой: незакрытое видно в трекере, а
    закрытое лишнее уходит из поля зрения вместе с невыполненной работой
    ([097](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/097-a-checker-has-two-error-types.md)).
    """
    reply, _ = platform_says({12: "closed"})
    monkeypatch.setattr(module.ghrest, "request", reply)
    monkeypatch.setattr(module, "closed_by", lambda *a, **k: "deadbee")
    said = module.fate(
        "o/r", linked_change("Refs #12"), module.changerefs.links_in("Refs #12"), "t"
    )
    assert list(said) == [12], said
    assert "НЕ закрывать" in said[12]


def test_a_task_closed_by_someone_else_is_not_blamed_on_the_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Закрытая задача, закрытая НЕ этим слиянием, изменению не вменяется.

    По состоянию задачи «закрыл человек» и «закрыло изменение» неразличимы, и
    свести их значило бы обвинять изменение в чужой работе (044).
    """
    reply, _ = platform_says({12: "closed"})
    monkeypatch.setattr(module.ghrest, "request", reply)
    monkeypatch.setattr(module, "closed_by", lambda *a, **k: "чужой-коммит")
    assert (
        module.fate("o/r", linked_change("Refs #12"), module.changerefs.links_in("Refs #12"), "t")
        == {}
    )


def test_an_unreadable_closer_is_not_read_as_this_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила, чем закрыта задача — обвинения нет (045)."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(module.ghrest, "paginate", refuse)
    assert module.closed_by("o/r", 12, "t") == ""


# --- объявленные исходы захода -----------------------------------------------


def test_a_sweep_that_marked_nothing_is_its_own_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Обход прошёл, отмечать было нечего — свой исход, а не «записано».

    «Прошёл и отметил» и «прошёл и нечего» — разные состояния: по первому
    видно работу, по второму — что работы не было
    ([039](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/039-three-outcomes-not-two.md)).
    """
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module.items, "sweep", lambda repo, token, *, dry_run: 0)
    assert module.main(["--sweep", "--repo", "o/r"]) == module.EXIT_NOTHING
    assert "отмечено пунктов по объявлению автора: 0" in capsys.readouterr().out


def test_a_sweep_that_marked_something_records_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пункты отмечены — исход записи, и число названо."""
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module.items, "sweep", lambda repo, token, *, dry_run: 2)
    assert module.main(["--sweep", "--repo", "o/r"]) == module.EXIT_RECORDED
    assert "отмечено пунктов по объявлению автора: 2" in capsys.readouterr().out


def test_no_task_close_event_shares_the_review_queue() -> None:
    """Закрытие задачи не встаёт в группу разбора: его догоняет ночной обход (#1208).

    Группа держит одно ожидающее место. Событие `issues: closed` при слиянии с
    `Closes` приходило вслед за слиянием и вытесняло ожидающий разбор слитого.
    Решение владельца 08.10.2026: событие снято, задачу, закрытую руками,
    догоняет обход по расписанию.
    """
    caller = yaml.safe_load(CALLER.read_text(encoding="utf-8"))
    events = caller.get("on") or caller.get(True)
    assert "issues" not in events, "закрытие задачи снова стоит в группе разбора"
    assert "schedule" in events, "ночного обхода нет — задачу, закрытую руками, не догонит никто"


def test_the_review_waits_for_a_change_number_not_an_event_name() -> None:
    """Шаги разбора идут по номеру изменения: ночной обход без номера их не зовёт."""
    steps = {step.get("name"): step for step in document()["jobs"]["task-items"]["steps"]}
    assert steps["ключа нет — разбор не состоится"]["if"] == "steps.number.outputs.number != ''"


def test_the_caller_names_the_test_that_holds_the_close_case() -> None:
    """Вызов называет тест, держащий закрытие задачи, и это тест этого модуля.

    Общий гейт `tests/test_live_references.py` судит только НАЙДЕННЫЕ адреса и
    любое определённое имя: убери ссылку из комментария или назови ею
    константу — он зелёный. Что ссылка есть и ведёт на тест, держит этот
    контракт вызова (взгляды на #1208 и #1224).
    """
    said = CALLER.read_text(encoding="utf-8")
    # Адрес ищется образцом общего гейта, с его левой границей: два образца
    # одного адреса судили бы по-разному (взгляд на #1230).
    named = [
        found.group("name")
        for found in TEST_ADDRESS_RE.finditer(said)
        if found.group("file") == "test_task_items.py" and found.group("name")
    ]
    assert named, "вызов не называет теста, который держит закрытие задачи"
    for name in named:
        assert name.startswith("test_") and callable(globals().get(name)), (
            f"вызов называет не тест этого модуля: {name}"
        )


# --- доводка задачи по `Refs` (#1412) ----------------------------------------


def finishing_platform(
    issues: dict[int, dict[str, Any]], comments: list[dict[str, Any]] | None = None
) -> tuple[Any, Any, list[tuple[str, str, Any]]]:
    """Площадка с задачами и журналом записей: что механизм прочёл и что написал."""
    wrote: list[tuple[str, str, Any]] = []

    def reply(method: str, path: str, _token: str, payload: Any = None) -> Any:
        if method != "GET":
            wrote.append((method, path, payload))
            return {}
        number = int(path.rstrip("/").rsplit("/", 1)[1])
        return issues[number]

    def pages(_path: str, _token: str, _key: str | None = None) -> Any:
        return iter(comments or [])

    return reply, pages, wrote


def an_issue(body: str, *, state: str = "open", labels: tuple[str, ...] = ()) -> dict[str, Any]:
    """Задача площадки: тело, состояние, метки."""
    return {"state": state, "body": body, "labels": [{"name": one} for one in labels]}


@pytest.mark.parametrize(
    ("issue", "closes"),
    [
        (an_issue("## Приёмка\n\n- [x] первое\n- [x] второе\n"), True),
        (an_issue("## Приёмка\n\n- [x] первое\n- [ ] второе\n"), False),
        (an_issue("- [x] первое\n", labels=("epic",)), False),
        (an_issue(f"{module.findings.MARKER}\n- [x] первое\n"), False),
        (an_issue(f"{module.findings.PLAN_MARKER}\n- [x] первое\n"), False),
        (an_issue("- [x] первое\n", state="closed"), False),
    ],
    ids=["all-ticked", "one-open", "epic", "live", "plan", "already-closed"],
)
def test_a_refs_task_with_every_item_ticked_is_closed(
    monkeypatch: pytest.MonkeyPatch, issue: dict[str, Any], closes: bool
) -> None:
    """`Refs`, а все пункты отмечены — механизм закрывает задачу; иначе не трогает.

    Обе стороны (097): закрыть сделанную и НЕ закрыть ни недоделанную, ни
    эпик, ни живую задачу-адресат, ни уже закрытую.
    """
    reply, pages, wrote = finishing_platform({12: issue})
    monkeypatch.setattr(module.ghrest, "request", reply)
    monkeypatch.setattr(module.ghrest, "paginate", pages)
    closed, asked = module.finish(
        "o/r", linked_change("Refs #12"), module.changerefs.links_in("Refs #12"), "t"
    )
    assert closed == ([12] if closes else []), (closed, asked)
    assert asked == []
    shut = [one for one in wrote if one[0] == "PATCH"]
    assert shut == (
        [("PATCH", "repos/o/r/issues/12", {"state": "closed", "state_reason": "completed"})]
        if closes
        else []
    )


def test_a_closes_link_is_left_to_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Closes` закрывает площадка; доводка его не трогает и задачу не читает."""
    reply, pages, wrote = finishing_platform({})
    monkeypatch.setattr(module.ghrest, "request", reply)
    monkeypatch.setattr(module.ghrest, "paginate", pages)
    assert module.finish(
        "o/r", linked_change("Closes #12"), module.changerefs.links_in("Closes #12"), "t"
    ) == ([], [])
    assert wrote == []


def test_a_refs_task_without_items_is_asked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача без пунктов не закрывается — ей предлагают закрыть, и только раз."""
    reply, pages, wrote = finishing_platform({12: an_issue("Прозой: что сделать.\n")})
    monkeypatch.setattr(module.ghrest, "request", reply)
    monkeypatch.setattr(module.ghrest, "paginate", pages)
    links = module.changerefs.links_in("Refs #12")
    assert module.finish("o/r", linked_change("Refs #12"), links, "t") == ([], [12])
    assert [one[0] for one in wrote] == ["POST"]
    assert module.NO_ITEMS_NOTE in wrote[0][2]["body"]

    asked_before = [{"body": f"{module.NO_ITEMS_NOTE}\nпредложено"}]
    reply, pages, wrote = finishing_platform({12: an_issue("Прозой.\n")}, asked_before)
    monkeypatch.setattr(module.ghrest, "request", reply)
    monkeypatch.setattr(module.ghrest, "paginate", pages)
    assert module.finish("o/r", linked_change("Refs #12"), links, "t") == ([], [])
    assert wrote == []


def test_a_dry_finish_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без `--apply` доводка называет, что сделала бы, и не пишет ни строки."""
    reply, pages, wrote = finishing_platform({12: an_issue("- [x] первое\n")})
    monkeypatch.setattr(module.ghrest, "request", reply)
    monkeypatch.setattr(module.ghrest, "paginate", pages)
    links = module.changerefs.links_in("Refs #12")
    assert module.finish("o/r", linked_change("Refs #12"), links, "t", dry_run=True) == ([12], [])
    assert wrote == []


def test_nobody_finishes_an_epic_or_a_live_task() -> None:
    """Эпик, живая задача и план — не доводятся; задача человека — доводится."""
    assert module.nobody_finishes(an_issue("тело", labels=("epic",)))
    assert module.nobody_finishes(an_issue(f"{module.findings.MARKER}\nтело"))
    assert module.nobody_finishes(an_issue(f"{module.findings.PLAN_MARKER}\nтело"))
    assert not module.nobody_finishes(an_issue("- [x] пункт\n", labels=("enhancement",)))


def test_the_merge_fate_publishes_first_and_then_finishes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--fate` зовёт доводку — и только ПОСЛЕ записи судьбы связи (взгляд на #1418).

    Отказ доводки на площадке не должен уносить найденное `fate`: его запись к
    этому моменту уже в задаче. Закрытие называется аннотацией, а не молчит.
    """
    order: list[str] = []
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module, "linked", lambda *a: ([12], linked_change("Refs #12")))
    monkeypatch.setattr(module, "fate", lambda *a: {12: "не сбылось"})
    monkeypatch.setattr(module, "publish", lambda *a: order.append("publish"))

    def finishing(*_a: object, **_k: object) -> tuple[list[int], list[int]]:
        order.append("finish")
        return [12], []

    monkeypatch.setattr(module, "finish", finishing)
    code = module.main(["--repo", "o/r", "--fate", "--pr", "7", "--apply"])
    assert code == module.EXIT_RECORDED
    assert order == ["publish", "finish"], order
    assert "::notice::#12" in capsys.readouterr().out


def test_an_agent_marking_is_followed_by_finishing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Разбор агентом отмечает пункты позже `--fate` — доводка зовётся и после него."""
    called: list[str] = []
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module, "linked", lambda *a: ([12], linked_change("Refs #12")))
    monkeypatch.setattr(module.late_look, "answer_of", lambda _text: "ответ")
    monkeypatch.setattr(module, "proposals", lambda _a: ([("пункт", "тест")], []))
    monkeypatch.setattr(module, "publish", lambda *a: None)
    monkeypatch.setattr(
        module.items, "mark", lambda *a, **k: module.items.Outcome(["пункт"], [], [])
    )

    def finishing(*_a: object, **_k: object) -> tuple[list[int], list[int]]:
        called.append("finish")
        return [], []

    monkeypatch.setattr(module, "finish", finishing)
    run = tmp_path / "run.json"
    run.write_text("{}", encoding="utf-8")
    module.main(["--repo", "o/r", "--pr", "7", "--from", str(run), "--apply"])
    assert called == ["finish"]


NO_TASK_BODY: str = "Без задачи, потому что починка красной ветки\n"


@pytest.mark.parametrize(
    "argv",
    [["--fate", "--pr", "7", "--apply"], ["--pr", "7", "--collect", "subject.md"]],
    ids=["судьба", "предмет"],
)
def test_a_declared_no_task_is_nothing_after_merge(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    argv: list[str],
) -> None:
    """«Без задачи, потому что …» после слияния — «нечего» с кодом 0 (взгляд на #1584)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: linked_change(NO_TASK_BODY))
    assert module.main(["--repo", "o/r", *argv]) == module.EXIT_NOTHING
    assert "Без задачи, потому что" in capsys.readouterr().out


def test_silence_about_the_task_is_still_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Связи нет и объявления нет — по-прежнему отказ с кодом 2: молчание не ответ (154)."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: linked_change("текст\n"))
    assert module.main(["--repo", "o/r", "--fate", "--pr", "7"]) == module.EXIT_BROKEN


def test_unlinked_tells_a_declaration_from_silence() -> None:
    """`unlinked` — `NoTask` при объявлении, `NotRun` при молчании; объявление в коде не ответ."""
    assert isinstance(module.unlinked(7, NO_TASK_BODY, "записывать"), module.NoTask)
    silent = module.unlinked(7, "текст", "записывать")
    assert type(silent) is module.NotRun
    fenced = module.unlinked(7, f"```\n{NO_TASK_BODY}```\n", "записывать")
    assert type(fenced) is module.NotRun


def test_a_declaration_in_the_title_counts_like_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Объявление в заголовке — тоже «нечего»: гейт читает заголовок, шаг — так же (#1594)."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    change = {**linked_change("текст\n"), "title": NO_TASK_BODY.strip()}
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: change)
    assert module.main(["--repo", "o/r", "--fate", "--pr", "7"]) == module.EXIT_NOTHING
