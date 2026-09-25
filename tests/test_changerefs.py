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

from tests.conftest import ROOT, load_script, walk

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
    for path in walk(SCRIPTS, "*.py"):
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
    body = agent_pr.describe("agent/окно", "main").body
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
    body = agent_pr.describe("agent/окно", "main").body
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


def test_a_resolution_line_reads_its_whole_list() -> None:
    """Одна строка снимает столько находок, сколько названо.

    ЭТО БЫЛ ДЕФЕКТ, А НЕ НЕДОСТАЮЩЕЕ УДОБСТВО. Изменение #325 починило семь
    находок и назвало семь отпечатков; из реестра ушла одна, а шесть остались
    висеть как неразобранные — снятие при этом выглядело удавшимся с обеих
    сторон. Нашёл внешний взгляд; набор молчал, потому что проверял ровно тот
    случай, на котором образец и писали (045).
    """
    семь = "Разобрано: 67123c3, 0396b0e, 74dc54c, 4b5b012, e98fc10, f2f16eb, a9ab24d"
    assert changerefs.resolved_in(семь) == [
        "67123c3",
        "0396b0e",
        "74dc54c",
        "4b5b012",
        "e98fc10",
        "f2f16eb",
        "a9ab24d",
    ]


def test_a_resolution_keeps_what_the_author_wrote_after_the_marks() -> None:
    """Строка снятия отдаётся целиком: причина — часть записи, а не шум.

    У снятия два исхода — «починено» и «премиса не подтвердилась», — и второй
    обязан нести причину (044). Пока тело уплотнения собиралось из отпечатков,
    причина терялась по дороге в общую ветку, и оба исхода выглядели там
    одинаково (039).
    """
    сказано = "Разобрано: a70f8f5 — премиса не подтвердилась: у 136 механизм уже был"
    assert changerefs.resolutions_in_all([сказано]) == [сказано]
    assert changerefs.resolutions_in_all(["Разобрано: `abc1234`"]) == ["Разобрано: abc1234"], (
        "оформление кодом — дело автора, а запись нормализуется"
    )
    assert changerefs.resolutions_in_all(["Разобрано: замер"]) == []


def test_one_line_of_marks_is_kept_once() -> None:
    """Повтор той же строки в двух коммитах ветки записью не удваивается."""
    тела = ["fix: раз\n\nРазобрано: abc1234\n", "fix: два\n\nРазобрано: abc1234\n"]
    assert changerefs.resolutions_in_all(тела) == ["Разобрано: abc1234"]


def test_one_mark_is_recorded_once_even_when_described_twice() -> None:
    """Одна находка — одна запись, сколько бы коммитов её ни описывали.

    Повтор узнаётся по ОТПЕЧАТКУ, а не по строке: «Разобрано: abc1234» и
    «Разобрано: abc1234 — премиса не подтвердилась» — одно снятие, описанное
    дважды. Сверка строк пропускала оба, и в общую ветку ехали две записи об
    одной находке (нашёл внешний взгляд на #331).
    """
    тела = [
        "fix: раз\n\nРазобрано: abc1234\n",
        "fix: два\n\nРазобрано: abc1234 — премиса не подтвердилась\n",
        "fix: три\n\nРазобрано: def5678\n",
    ]
    assert changerefs.resolutions_in_all(тела) == [
        "Разобрано: abc1234",
        "Разобрано: def5678",
    ]


def test_a_new_mark_survives_a_line_that_repeats_an_old_one() -> None:
    """Строка со старым и новым отпечатком записывает новый, а не пропадает вся.

    Строка снятия несёт список, и у второй строки ветки часть отпечатков бывает
    новой. Снятие повтора по СТРОКЕ отбрасывало её целиком по одному
    совпадению: работа сделана, а запись в реестре висела неразобранной — та же
    молчаливая потеря, что шести отпечатков из семи на #325 (045).
    """
    тела = [
        "fix: раз\n\nРазобрано: abc1234\n",
        "fix: два\n\nРазобрано: abc1234, def5678 — две находки одной правкой\n",
    ]
    assert changerefs.resolutions_in_all(тела) == [
        "Разобрано: abc1234",
        "Разобрано: def5678 — две находки одной правкой",
    ], "новый отпечаток не теряется из-за соседа, записанного раньше"


def test_a_reason_does_not_lend_its_words_to_the_marks() -> None:
    """Семь букв из a—f внутри причины чужого снятия не съедают.

    Сборка по ветке искала отпечатки во ВСЕЙ строке, включая причину, — список
    из разрешительного становился запретительным (068). Цена: `deadbeef`,
    названный в пояснении, давал отпечаток `deadbee`, и настоящее снятие
    `deadbee` из следующего коммита в общую ветку не уезжало.
    """
    тела = [
        "fix: раз\n\nРазобрано: 1111111 — иначе deadbeef висит\n",
        "fix: два\n\nРазобрано: deadbee\n",
    ]
    assert changerefs.resolutions_in_all(тела) == [
        "Разобрано: 1111111 — иначе deadbeef висит",
        "Разобрано: deadbee",
    ]


def test_one_mark_named_twice_in_one_line_is_printed_once() -> None:
    """Правило повтора одно на текст и на ветку: один отпечаток — одна запись.

    ОБЁРТКА `resolutions_in` СНЯТА (#630), А СВОЙСТВО ОСТАЛОСЬ. Она была
    `resolutions_in_all([text])` в одну строку и осиротела, когда рабочий путь
    пошёл через `_all`. Утверждение же про обёртку и не было: «один текст —
    частный случай ветки» держится тем, что правило повтора ОДНО, и проверяется
    оно теперь прямо на замене — одним телом против двух (022).
    """
    assert changerefs.resolutions_in_all(["Разобрано: abc1234 abc1234"]) == ["Разобрано: abc1234"]
    assert changerefs.resolutions_in_all(["Разобрано: abc1234"]) == changerefs.resolutions_in_all(
        ["Разобрано: abc1234", "Разобрано: abc1234"]
    ), "одно тело — частный случай ветки, а не второе правило"


def test_a_resolution_is_parsed_once_for_every_reader() -> None:
    """Разбор один: отпечатки из головы строки, причина — всё после них (090)."""
    (запись,) = changerefs.resolutions_parsed("Разобрано: `abc1234`, def5678 — почему")
    assert запись.marks == ("abc1234", "def5678")
    assert запись.why == "— почему"
    assert str(запись) == "Разобрано: abc1234, def5678 — почему"
    assert changerefs.resolutions_parsed("Разобрано: замер") == []
    assert запись == changerefs.Resolution(marks=("abc1234", "def5678"), why="— почему")


def test_a_resolution_prints_itself_the_way_the_body_reads_it() -> None:
    """Запись сама печатает строку: вид един у разбора и у сборки тела (022)."""
    assert str(changerefs.Resolution(marks=("abc1234",), why="")) == "Разобрано: abc1234"
    assert (
        str(changerefs.Resolution(marks=("abc1234", "def5678"), why="— премиса не подтвердилась"))
        == "Разобрано: abc1234, def5678 — премиса не подтвердилась"
    )


def test_a_resolution_stops_where_the_marks_end() -> None:
    """Разбор кончается на первом же слове, отпечатком не являющемся.

    Иначе семь букв подряд из a—f, случайно сложившиеся в пояснении, сняли бы
    чужую находку. Список разрешительный: берётся голова строки, а не всё, что
    похоже на хэш (068).
    """
    assert changerefs.resolved_in("Разобрано: `abc1234` — иначе deadbeef висит") == ["abc1234"]
    assert changerefs.resolved_in("Разобрано: замер, а не отпечаток") == []
    assert changerefs.resolved_in("Разобрано: abc1234 abc1234") == ["abc1234"], (
        "повтор одного отпечатка остаётся одной находкой"
    )


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
    body = agent_pr.describe("agent/окно", "main").body
    assert "Refs #12" in body and "Refs #7" in body


# --- пункт чек-листа ---------------------------------------------------------


def test_an_item_is_recognised_through_its_punctuation() -> None:
    """Знак конца строки к пункту не относится.

    В теле задачи пункты идут списком и кончаются точкой с запятой, а в теле
    изменения их пишут рукой и без неё. Замер 09.09.2026: первое же слияние с
    объявленным пунктом ничего не отметило именно из-за «;».
    """
    assert changerefs.normalise("сделать штуку;") == changerefs.normalise("сделать штуку")
    assert changerefs.normalise("**сделать штуку**.") == changerefs.normalise("сделать штуку")


def test_punctuation_inside_the_item_survives() -> None:
    """Внутренний знак — часть пункта, и обрезать его нельзя.

    Иначе два разных пункта, отличающиеся только запятой, стали бы одним, и
    отметка уехала бы на соседний — молча.
    """
    assert "," in changerefs.normalise("отметить пункт, не закрывая задачу;")


def test_a_line_break_does_not_break_the_match() -> None:
    """Пункт, перенесённый по строкам, узнаётся так же."""
    assert changerefs.normalise("длинный\n   пункт") == changerefs.normalise("длинный пункт")


def test_a_declared_item_is_read_from_the_body() -> None:
    """Строка объявления читается целиком и без повторов."""
    text = "Refs #25\nЗакрывает пункт: первый\nЗакрывает пункт: первый\nЗакрывает пункт: второй"
    assert changerefs.closed_items_in(text) == ["первый", "второй"]


def test_a_declared_item_keeps_the_words_it_was_written_with() -> None:
    """Пункт отдаётся как написан: строка едет в тело изменения к человеку.

    Приведённый вид опускает регистр и срезает знак в конце — читатель увидел
    бы огрызок вместо пункта задачи. Повтор при этом снимается по приведённому
    виду: «Первый пункт» и «первый пункт;» — один и тот же пункт.
    """
    text = "Refs #26\nЗакрывает пункт: Первый Пункт;\nЗакрывает пункт: первый пункт"
    assert changerefs.closed_items_in(text) == ["Первый Пункт;"]


def test_the_change_body_carries_the_declared_item() -> None:
    """Объявление пункта доезжает до ТЕЛА ИЗМЕНЕНИЯ, а не остаётся в коммите.

    Отмечает пункт шаг слияния, и читает он тело изменения. Без переноса
    объявление до него не доходит вовсе: замер 09.09.2026 — два слияния подряд
    объявили пункт закрытым и не отметили ничего.

    Проверяется сборка тела, а не намерение: механизм-близнец (перенос снятия
    находок) существовал, а этот — нет, и разница была невидима.
    """
    bodies = ["fix: что-то\n\nRefs #26\nЗакрывает пункт: Отметить пункт задачи;"]
    assert changerefs.closed_items_in_all(bodies) == ["Отметить пункт задачи;"]


def test_one_item_declared_twice_in_the_branch_stays_one() -> None:
    """Пункт, объявленный в двух коммитах по-разному, остаётся одним.

    Повтор снимается по приведённому виду, а не по строке: иначе он попал бы в
    тело изменения дважды, и человек прочитал бы это как два разных пункта.
    """
    bodies = [
        "fix: раз\n\nRefs #26\nЗакрывает пункт: Отметить пункт;",
        "fix: два\n\nRefs #26\nЗакрывает пункт: отметить пункт",
    ]
    assert changerefs.closed_items_in_all(bodies) == ["Отметить пункт;"]


# --- маркер вне кода, а текст — как написан -----------------------------------
#
# ЗАМЕР 10.09.2026, слияние #88. Пункт «`debt` печатает это число рядом с
# находками и правилами» доехал до тела изменения как «печатает это число
# рядом с находками и правилами»: разбор вырезал кодовую вставку ДО того, как
# взял текст. В задаче пункт остался целым, совпадения не вышло, пункт не
# отметился, а человек увидел в теле изменения огрызок своей строки.


def test_an_item_keeps_the_code_inside_it() -> None:
    """Инлайн-код внутри пункта — часть пункта, а не пример.

    Вырезанный `debt` менял текст, по которому пункт узнают в задаче, — то
    есть механизм искал не то, что было объявлено закрытым.
    """
    text = "Закрывает пункт: `debt` печатает это число рядом с находками и правилами"
    assert changerefs.closed_items_in(text) == [
        "`debt` печатает это число рядом с находками и правилами"
    ]


def test_a_fingerprint_written_as_code_is_still_a_fingerprint() -> None:
    """Отпечаток в кавычках снимает находку так же, как отпечаток без них.

    Строку пишет человек, и оформить хэш кодом — первое, что он делает.
    Молчаливая потеря здесь стоит невыполненного снятия: запись остаётся в
    живой задаче, хотя находка починена.
    """
    assert changerefs.resolved_in("Разобрано: `2993d29`") == ["2993d29"]


def test_a_marker_inside_code_is_still_an_example() -> None:
    """Строка, целиком взятая в кавычки, маркером не считается.

    Держит это ЯКОРЬ начала строки, а не маска: маркер узнаётся только там, где
    строка начинается, и кавычка перед ним строку уже не начинает. Сказано
    прямо, потому что «проверено» здесь легко приписать не тому механизму —
    маска ловит другое, и её отдельная проверка ниже, на блоке кода (154).
    """
    assert changerefs.closed_items_in("`Закрывает пункт: пример из свода`") == []
    assert changerefs.resolved_in("в тексте пишут так: `Разобрано: bbbbbbb`") == []


def test_a_marker_inside_a_fenced_block_is_still_an_example() -> None:
    """Пример в блоке кода не читается ни как пункт, ни как снятие."""
    text = "```\nЗакрывает пункт: пример из документации\nРазобрано: aaaaaaa\n```"
    assert changerefs.closed_items_in(text) == []
    assert changerefs.resolved_in(text) == []


def test_the_mask_keeps_the_positions_of_the_line() -> None:
    """Маска той же длины, что и строка: по ней сверяют ПОЛОЖЕНИЕ маркера.

    Маска короче оригинала сдвигала бы сверку на соседние знаки, и «маркер
    уцелел» решалось бы по чужому месту — молча и правдоподобно.
    """
    for mask, line in changerefs.masked_lines("обычная строка\n`код` и текст\n```\nвнутри\n```"):
        assert len(mask) == len(line), f"маска и строка разошлись длиной: {mask!r} / {line!r}"


def test_a_hold_trailer_is_read_by_name() -> None:
    """`held_in` читает причину задержки и отдаёт её КАК НАПИСАНА.

    Причина едет в тело изменения человеку на глаза: нормализуются только
    пробелы, слова — нет.
    """
    assert changerefs.held_in("Ждёт:   замер,  эти прогоны\tне сливаются") == (
        "замер, эти прогоны не сливаются"
    )
    assert changerefs.held_in("ждёт: строчными — тот же трейлер") == "строчными — тот же трейлер"


def test_a_hold_without_a_reason_is_not_a_hold() -> None:
    """Задержка без причины неотличима от забытой метки и потому не читается (154)."""
    assert changerefs.held_in("Ждёт:") is None
    assert changerefs.held_in("Ждёт:    ") is None
    assert changerefs.held_in("обычное тело без трейлера") is None


def test_a_hold_inside_code_is_an_example_not_a_hold() -> None:
    """Пример трейлера в документации задержкой не становится — как у соседей."""
    assert changerefs.held_in("пишут так: `Ждёт: пример из свода`") is None
    assert changerefs.held_in("```\nЖдёт: пример из блока\n```") is None


def test_the_first_named_reason_wins_across_bodies() -> None:
    """`held_in_all` берёт ПЕРВУЮ названную причину: задержка — состояние, не список.

    Второй трейлер в соседнем коммите ту же задержку не усиливает, и складывать
    причины значило бы выдавать одно решение за несколько.
    """
    assert changerefs.held_in_all(["Refs #1", "Ждёт: первая", "Ждёт: вторая"]) == "первая"
    assert changerefs.held_in_all(["Refs #1", "Closes #2"]) is None
    assert changerefs.held_in_all([]) is None


# --- пример в ОТСТУПНОМ блоке кода — не ключ (#581) ---------------------------

#: Все пять ключей, которые читаются из тела коммита, и то, чем их читают.
#: Проверяются ВМЕСТЕ и одним предикатом: дыра была общая — у маскировки, — и
#: чинить её по одному значило бы вернуться сюда ещё четыре раза.
KEYS_AND_READERS = [
    ("Ждёт: пример", lambda t: changerefs.held_in(t)),
    ("Refs #999", lambda t: changerefs.links_in(t)),
    ("Closes #999", lambda t: changerefs.links_in(t)),
    ("Разобрано: aaaaaaa причина", lambda t: changerefs.resolved_in(t)),
    ("Закрывает пункт: текст", lambda t: changerefs.closed_items_in(t)),
]


@pytest.mark.parametrize(
    "key, read", KEYS_AND_READERS, ids=lambda x: x if isinstance(x, str) else ""
)
def test_a_key_in_an_indented_block_is_an_example(key: str, read: Any) -> None:
    """Пример, написанный отступным блоком, ключом не становится — ни один из пяти.

    ЗАМЕР, РАДИ КОТОРОГО ЭТО ЗАВЕДЕНО (21.09.2026, #581). Нашёл владелец, а не
    набор: изменение #579 открылось со стоп-меткой `hold`, которой никто не
    ставил, и причиной в его теле стоял ПРИМЕР из тела коммита — строка
    `    Hold: замер, эти прогоны не сливаются` с отступом в четыре пробела.
    Маскировка снимала обратные кавычки и заборы, а отступные блоки — нет.

    Дороже всех платил бы не `Hold:`, а `Closes #N`: пример в прозе закрыл бы
    настоящую задачу при слиянии.
    """
    assert not read(f"пишут так:\n\n    {key}\n"), (
        f"{key!r} в отступном блоке прочитан как настоящий ключ"
    )
    assert not read(f"или табуляцией:\n\n\t{key}\n"), (
        f"{key!r} после табуляции прочитан как настоящий ключ"
    )


@pytest.mark.parametrize(
    "key, read", KEYS_AND_READERS, ids=lambda x: x if isinstance(x, str) else ""
)
def test_a_key_in_the_first_column_is_still_read(key: str, read: Any) -> None:
    """Вторая половина: настоящий ключ в первой колонке читается по-прежнему.

    Её забывают, и тогда гейт неотличим от «не читать ничего»: первая половина
    зеленеет и на предикате, который не находит вообще ничего.
    """
    assert read(f"{key}\n"), f"{key!r} в первой колонке перестал читаться"


def test_the_indented_block_opens_only_after_a_blank_line() -> None:
    """Отступный блок открывается после ПУСТОЙ строки — как его видит разметка.

    Без этого условия маскировалась бы любая отбитая строка, включая перенос
    абзаца, и предикат стал бы шире предмета
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    # Строка продолжает абзац, а не открывает блок: пустой строки перед ней нет.
    assert changerefs.links_in("абзац идёт\n    Refs #7") == [changerefs.Link("Refs", 7)]
    # А здесь пустая строка есть — это блок.
    assert changerefs.links_in("абзац идёт\n\n    Refs #7") == []


def test_the_block_survives_its_own_second_line() -> None:
    """Блок не закрывается на второй своей строке: пустой строки перед ней нет.

    Условие «после пустой» проверяется на ОТКРЫТИИ, а не на каждой строке —
    иначе замаскировалась бы ровно первая строка примера, а остальные уехали
    бы как настоящие. Это половина, которую легче всего потерять.
    """
    assert changerefs.links_in("пример:\n\n    Closes #1\n    Refs #2") == []


# --- объявление починки общей ветки (#585) ------------------------------------


def test_a_fix_main_trailer_names_the_red_step() -> None:
    """`Чинит main: <имя>` читается как объявление предмета починки.

    Имя отдаётся КАК НАПИСАНО: его сверяют с именем записи проверки у площадки,
    и нормализуются только пробелы.
    """
    assert changerefs.fixes_main_in("Чинит main:  ci-complete ") == "ci-complete"
    assert changerefs.fixes_main_in("чинит main: test-matrix (3.12)") == "test-matrix (3.12)"


def test_a_fix_main_without_a_name_is_not_a_declaration() -> None:
    """Объявление без имени шага предметом не является (154)."""
    assert changerefs.fixes_main_in("Чинит main:") is None
    assert changerefs.fixes_main_in("обычное тело") is None


def test_a_fix_main_example_in_code_is_not_a_declaration() -> None:
    """Пример в блоке кода объявлением не становится — как у всех ключей."""
    assert changerefs.fixes_main_in("пишут так: `Чинит main: ci-complete`") is None
    assert changerefs.fixes_main_in("```\nЧинит main: ci-complete\n```") is None
    assert changerefs.fixes_main_in("пример:\n\n    Чинит main: ci-complete") is None


def test_the_first_declared_fix_wins() -> None:
    """Из нескольких тел берётся первое имя: починка — состояние, а не список."""
    assert changerefs.fixes_main_in_all(["Refs #1", "Чинит main: lint", "Чинит main: test"]) == (
        "lint"
    )
    assert changerefs.fixes_main_in_all(["Refs #1"]) is None


def test_a_twin_after_the_word_is_resolved_too() -> None:
    """`Разобрано: A дубль B` снимает обе записи, а не одну A (#807)."""
    (record,) = changerefs.resolutions_parsed("Разобрано: 456de48 дубль 259442a")
    assert record.marks == ("456de48", "259442a")
    (quoted,) = changerefs.resolutions_parsed("Разобрано: `456de48` дубль `259442a` — почему")
    assert quoted.marks == ("456de48", "259442a") and quoted.why == "— почему"
    assert changerefs.resolved_in("Разобрано: 456de48 дубль 259442a") == ["456de48", "259442a"]


def test_a_word_that_is_not_a_twin_stays_a_reason() -> None:
    """Иное слово после отпечатка — пояснение, и отпечаток в нём не снимается (068)."""
    (record,) = changerefs.resolutions_parsed("Разобрано: 1111111 — сосед deadbeef рядом")
    assert record.marks == ("1111111",)
    (long,) = changerefs.resolutions_parsed("Разобрано: 1111111 дубль 22222223")
    assert long.marks == ("1111111",), "восемь знаков — не отпечаток"


@pytest.mark.parametrize(
    ("line", "marks", "twins"),
    [
        ("Разобрано: 456de48 дубль 259442a", ("456de48", "259442a"), {"456de48": "259442a"}),
        (
            "Разобрано: aaaaaaa, ccccccc дубль bbbbbbb",
            ("aaaaaaa", "ccccccc", "bbbbbbb"),
            {"aaaaaaa": "bbbbbbb", "ccccccc": "bbbbbbb"},
        ),
        (
            "Разобрано: aaaaaaa дубль bbbbbbb, ccccccc",
            ("aaaaaaa", "bbbbbbb", "ccccccc"),
            {"aaaaaaa": "bbbbbbb"},
        ),
        (
            "Разобрано: aaaaaaa дубль bbbbbbb дубль ccccccc — почему",
            ("aaaaaaa", "bbbbbbb", "ccccccc"),
            {"aaaaaaa": "bbbbbbb", "bbbbbbb": "ccccccc"},
        ),
        ("Разобрано: AAAAAAA ДУБЛЬ BBBBBBB", ("aaaaaaa", "bbbbbbb"), {"aaaaaaa": "bbbbbbb"}),
    ],
    ids=["пара", "список до", "список после", "цепочка", "регистр"],
)
def test_every_twin_in_a_chain_is_resolved(
    line: str, marks: tuple[str, ...], twins: dict[str, str]
) -> None:
    """Вся цепочка дублей снимается, и связь дублей видна (взгляд на #809)."""
    (record,) = changerefs.resolutions_parsed(line)
    assert record.marks == marks
    assert record.twin_of == twins


def test_a_twin_line_travels_to_the_change_body_in_its_own_form() -> None:
    """Строка доезжает до тела изменения с «дубль»: архив читает связь оттуда (#807)."""
    (record,) = changerefs.resolutions_parsed("Разобрано: aaaaaaa, ccccccc дубль bbbbbbb — так")
    assert str(record) == "Разобрано: aaaaaaa, ccccccc дубль bbbbbbb — так"
    (again,) = changerefs.resolutions_parsed(str(record))
    assert again.marks == record.marks and again.twin_of == record.twin_of


def test_the_squash_body_keeps_the_twin_form() -> None:
    """Тело уплотнения несёт «дубль»: архив на общей ветке читает связь оттуда (#809)."""
    said = changerefs.resolutions_in_all(
        ["Разобрано: aaaaaaa, ccccccc дубль bbbbbbb — так", "Разобрано: aaaaaaa — повтор"]
    )
    assert said == ["Разобрано: aaaaaaa, ccccccc дубль bbbbbbb — так"]
    (record,) = changerefs.resolutions_parsed(said[0])
    assert record.twin_of == {"aaaaaaa": "bbbbbbb", "ccccccc": "bbbbbbb"}


def test_a_twin_already_resolved_drops_its_group_not_the_rest() -> None:
    """Группа, чьи отпечатки уже сняты раньше, выпадает, а новые снимаются."""
    said = changerefs.resolutions_in_all(["Разобрано: bbbbbbb", "Разобрано: aaaaaaa дубль bbbbbbb"])
    assert said == ["Разобрано: bbbbbbb", "Разобрано: aaaaaaa"]
