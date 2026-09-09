"""Связь с задачей читается одинаково всеми механизмами.

Замер, ради которого написан модуль: строка `Refs #2, #29` в коммите. Гейт
разметки её видел, шаг открытия — нет, и открыл изменение без раздела связи,
которое тот же гейт немедленно отверг. Дефект был не в регулярке, а в том, что
регулярок было две.
"""

from __future__ import annotations

import ast
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

changerefs = load_script("changerefs.py")
agent_pr = load_script("agent_pr.py")

SCRIPTS = ROOT / "scripts"


def test_a_list_after_one_verb_is_read_whole() -> None:
    """`Refs #2, #29` — это ДВЕ связи, а не ноль и не одна."""
    assert [str(link) for link in changerefs.links_in("Refs #2, #29")] == ["Refs #2", "Refs #29"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("closes #12", "Closes #12"),
        ("FIXES #3", "Fixes #3"),
        ("Part of #7", "Part of #7"),
        ("см. refs #9 в теле", "Refs #9"),
    ],
)
def test_verb_is_read_in_any_case(text: str, expected: str) -> None:
    """Глагол читается в любом написании и приводится к одному виду."""
    assert str(changerefs.links_in(text)[0]) == expected


def test_repeats_collapse_and_order_survives() -> None:
    """Порядок появления сохраняется, повтор не удваивает связь."""
    links = changerefs.links_in("Refs #5\nCloses #1\nRefs #5")
    assert [str(link) for link in links] == ["Refs #5", "Closes #1"]


def test_closing_verbs_are_told_apart() -> None:
    """`Closes` закроет задачу при слиянии, `Refs` — нет, и это видно механизму."""
    closing, mention = changerefs.links_in("Closes #1 Refs #2")
    assert closing.closes and not mention.closes


def test_text_without_a_task_is_empty_not_guessed() -> None:
    """Номер без глагола связью не считается: #12 в прозе — это не «закрывает»."""
    assert changerefs.links_in("правка по #12 и вообще") == []
    assert not changerefs.has_link("ни слова о задачах")


def test_no_mechanism_reads_the_link_itself() -> None:
    """Гейт на дрейф: своей регулярки на связь нет ни у кого, кроме модуля.

    Две регулярки на один вход — это не дублирование кода, а два разных
    понимания одной строки, и расходятся они молча.
    """
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name == "changerefs.py":
            continue
        # Смотрятся именно образцы `re.compile`, а не текст файла: слова
        # «Closes #N» законно стоят в подсказке гейта, и запрет на подстроку
        # ловил бы объяснение вместо второго разбора.
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "compile"):
                continue
            pattern = node.args[0] if node.args else None
            if not (isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)):
                continue
            lowered = pattern.value.lower()
            assert not any(verb in lowered for verb in changerefs.VERBS), (
                f"{path.name} разбирает связь с задачей своей регуляркой"
            )


def test_opening_refuses_a_branch_without_a_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменение без связи не открывается: гейт отвергнет его через минуту.

    Молчаливое открытие отдавало красное туда, где предмет виден уже здесь.
    """
    monkeypatch.setattr(agent_pr, "git", lambda *args: "правка без задачи\n")
    with pytest.raises(agent_pr.NotRun, match="не называет задачу"):
        agent_pr.describe("agent/окно", "main")


def test_description_puts_one_task_per_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каждая задача получает свою строку: ключевое слово читается у каждой."""
    monkeypatch.setattr(agent_pr, "git", lambda *args: "feat: что-то\n\nRefs #2, #29\n")
    _, body = agent_pr.describe("agent/окно", "main")
    assert "Refs #2\nRefs #29" in body


def fake_transport(monkeypatch: pytest.MonkeyPatch, current: dict[str, Any]) -> list[Any]:
    """Подменяет транспорт и собирает то, что механизм отправил бы площадке."""
    sent: list[Any] = []

    def request(method: str, path: str, token: str, body: Any = None) -> Any:
        sent.append((method, path, body))
        return current if method == "GET" else {}

    monkeypatch.setattr(agent_pr.ghrest, "request", request)
    return sent


def test_open_change_gets_its_description_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменение, открытое до правки механизма, чинится следующим прогоном."""
    current = {"title": "старое", "body": f"старое тело\n\n{agent_pr.MARK}: …"}
    sent = fake_transport(monkeypatch, current)
    agent_pr.sync_description("о/р", 32, "токен", "новое", "новое тело", False)
    assert [method for method, _, _ in sent] == ["GET", "PATCH"]
    assert sent[1][2] == {"title": "новое", "body": "новое тело"}


def test_a_human_written_description_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тело, написанное человеком, механизм не переписывает своим."""
    sent = fake_transport(monkeypatch, {"title": "своё", "body": "человек писал это сам"})
    agent_pr.sync_description("о/р", 32, "токен", "новое", "новое тело", False)
    assert [method for method, _, _ in sent] == ["GET"]


def test_matching_description_is_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    """Совпавшее описание не переписывается: прогон не шумит на здоровом."""
    body = f"тело\n\n{agent_pr.MARK}: …"
    sent = fake_transport(monkeypatch, {"title": "имя", "body": body})
    agent_pr.sync_description("о/р", 32, "токен", "имя", body, False)
    assert [method for method, _, _ in sent] == ["GET"]


def test_gate_and_opening_agree_on_one_string() -> None:
    """Гейт и шаг открытия читают одну строку одинаково — теперь буквально."""
    check = load_script("check_pr_meta.py")
    text = "Refs #2, #29"
    assert check.changerefs.links_in(text) == changerefs.links_in(text)


def test_resolution_travels_with_the_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Строка снятия из коммита попадает в тело изменения, а не теряется.

    Механизм находок читает тело СЛИТОГО изменения. Пока перенос делался
    руками, «снятие едет вместе с работой» держалось тем, что кто-то вспомнит
    дописать описание — то есть не держалось ничем.
    """
    monkeypatch.setattr(
        agent_pr, "git", lambda *args: "fix: правка\n\nРазобрано: abc1234\nRefs #7\n"
    )
    _, body = agent_pr.describe("agent/окно", "main")
    assert "Разобрано: abc1234" in body


def test_resolution_is_read_the_same_by_both(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг открытия и механизм находок читают снятие одним разбором."""
    findings = load_script("review_findings.py")
    assert findings.changerefs.resolved_in is changerefs.resolved_in


@pytest.mark.parametrize(
    "text",
    [
        "старая регулярка была `^Refs #12$`, и это пример",
        "```\nRefs #12\n```",
    ],
)
def test_an_example_in_code_is_not_a_link(text: str) -> None:
    """Ссылка внутри кодовой вставки — цитата, а не связь с задачей.

    Поймано на себе: описание правки цитировало старую регулярку `^Refs #12$`,
    и механизм записал изменению задачу #12, которой оно не касается. Площадка
    ключевые слова внутри кода тоже не читает.
    """
    assert changerefs.links_in(text) == []


def test_a_resolution_inside_code_is_not_a_resolution() -> None:
    """Пример снятия в документации не снимает чужую находку."""
    assert changerefs.resolved_in("пишется так: `Разобрано: abc1234`") == []


def test_a_link_next_to_code_is_still_read() -> None:
    """Вырезается только код: настоящая связь рядом с примером остаётся."""
    text = "правка в `scripts/changerefs.py`\n\nRefs #7"
    assert [str(link) for link in changerefs.links_in(text)] == ["Refs #7"]


def test_an_unpaired_backtick_eats_nothing() -> None:
    """Забытая кавычка не съедает связь из соседнего коммита.

    Шаг открытия склеивает тела всех коммитов ветки, и вставка, тянущаяся
    через границу коммита, уносила с собой настоящие строки. Замер: связь
    `Refs #12` пропадала целиком, и ветка с названной задачей не открывалась.
    """
    text = "fix: не используй `--no-verify\n\nRefs #12\n---\nfeat: правка `кода`\n\nRefs #7"
    assert [str(link) for link in changerefs.links_in(text)] == ["Refs #12", "Refs #7"]


def test_an_unpaired_backtick_does_not_eat_a_resolution() -> None:
    """То же для снятия находки: строка не теряется по дороге в описание."""
    text = "fix: флаг `--no-verify\n\nРазобрано: abc1234\n---\nfeat: `код`"
    assert changerefs.resolved_in(text) == ["abc1234"]


def test_a_code_block_is_still_cut_whole() -> None:
    """Тройная вставка вырезается целиком, вместе с переносами внутри неё."""
    assert changerefs.links_in("```\nRefs #12\nещё строка\n```\nRefs #7") == (
        changerefs.links_in("Refs #7")
    )


def test_an_unclosed_fence_eats_nothing() -> None:
    """Незакрытый забор не смыкается с блоком соседнего коммита.

    Та же болезнь, что у одиночной кавычки, и та же цена: связь пропадала, а
    шаг открытия отказывал ветке, задачу назвавшей. Половина пары — не пара:
    при непарном числе заборов блоков в тексте нет вовсе.
    """
    text = "fix: X\n```\nзаметка\n\nRefs #12\n---\nfeat: Y\n```\nблок\n```\n\nRefs #7"
    assert [str(link) for link in changerefs.links_in(text)] == ["Refs #12", "Refs #7"]


def test_an_unclosed_fence_does_not_eat_a_resolution() -> None:
    """То же для снятия находки: строка доезжает до тела изменения."""
    text = "fix: X\n```\nзаметка\n\nРазобрано: abc1234\n---\nfeat: `код`"
    assert changerefs.resolved_in(text) == ["abc1234"]


def test_inline_code_inside_a_block_changes_nothing() -> None:
    """Внутри блока вырезано всё, включая строки, похожие на связь."""
    text = "```\nпример: `Refs #12` и Refs #13\n```\n\nRefs #7"
    assert [str(link) for link in changerefs.links_in(text)] == ["Refs #7"]


def test_two_unclosed_fences_in_different_bodies_eat_nothing() -> None:
    """Разметка одного тела не достаёт до соседнего.

    Замер: два коммита, в каждом свой незакрытый забор. Число заборов чётное,
    склеенный текст читается как один блок — и связь между ними исчезает.
    Счётом это не лечится: одна разметка на два документа. Тела разбираются
    по одному.
    """
    bodies = ["fix: A\n```\nзаметка A\n\nRefs #12\n", "feat: B\n```\nзаметка B\n\nRefs #7\n"]
    assert [str(link) for link in changerefs.links_in_all(bodies)] == ["Refs #12", "Refs #7"]


def test_resolutions_survive_the_same_way() -> None:
    """Снятие находки переживает чужую незакрытую разметку так же."""
    bodies = ["fix: A\n```\nзаметка\n\nРазобрано: abc1234\n", "feat: B\n```\nещё\n"]
    assert changerefs.resolved_in_all(bodies) == ["abc1234"]


def test_repeats_across_bodies_collapse() -> None:
    """Одна задача, названная в двух коммитах, даёт одну строку в описании."""
    bodies = ["fix: A\n\nRefs #7", "feat: B\n\nRefs #7"]
    assert [str(link) for link in changerefs.links_in_all(bodies)] == ["Refs #7"]


def test_description_is_built_from_separate_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг открытия разбирает тела по одному, а не склейкой.

    Проверяется на том самом входе, что был дефектом: незакрытый забор в
    первом коммите и настоящая связь во втором.
    """

    def git(*args: str) -> str:
        if "--format=%s" in args:
            return "fix: A\nfeat: B\n"
        if "--format=%B%x00" in args:
            return "fix: A\n```\nзаметка\n\nRefs #12\n\x00feat: B\n\nRefs #7\n\x00"
        return "основание\n"

    monkeypatch.setattr(agent_pr, "git", git)
    _, body = agent_pr.describe("agent/окно", "main")
    assert "Refs #12" in body and "Refs #7" in body
