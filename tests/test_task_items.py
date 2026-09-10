"""Разбор слитого против задачи: что он отмечает и чего не отмечает.

Отвергаемое здесь — ЛОЖНАЯ ОТМЕТКА. Пункт, отмеченный по догадке, теряется
вместе с задачей: неотмеченный видно, ложно отмеченный — нет. Основание у
разбора слабее, чем у автора: автор говорит «я это сделал», разбор выводит это
из кода ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Поэтому проверяется не «умеет ли он отмечать», а граница: пункт без названного
доказательства не отмечается, а текст, обращённый к разбору из тела изменения,
предложением не считается.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, load_script

module = load_script("task_items.py")
items = load_script("items.py")

WORKFLOW = ROOT / ".github" / "workflows" / "task-items.yml"


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
    group = document()["jobs"]["task-items"]["concurrency"]
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
