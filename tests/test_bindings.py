"""Ответ каталогу проверяется на полноту формы, а не на наличие файла.

Правило 128: обязательное поле проверяется на полноту, а не на непустоту.
Правило 154: «не держится ничем» обязано назвать причину, иначе это молчание.

Отдельно проверяется, что адрес механизма **разрешим**: путь, который в дереве
не существует, — это ложный механизм. Ответ «держится гейтом по адресу X» при
отсутствующем X хуже отсутствия ответа: он выглядит выполненным.

Полноту относительно живого каталога держит не этот тест, а прогон
`rules-inbox`: число правил меняется в соседнем репозитории, и сверять его
дереву неоткуда.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import load_script

kinds = load_script("kinds.py")

ROOT = Path(__file__).resolve().parent.parent
BINDINGS = ROOT / ".rules" / "bindings.json"
PROPOSALS = ROOT / ".rules" / "proposals.json"
# Поля, которые в предложении заполняет каталог при приёме, а не проект.
OWNED_BY_CATALOGUE = {"id", "number", "rule"}
STATUSES = {"active", "rejected", "not-applicable", "unreviewed"}
# Виды механизма, которыми отвечает ЭТОТ проект. Не копия набора каталога:
# там есть `code`, которого у нас нет, — и наоборот, здесь перечислены только
# те, что мы вправе написать в своём ответе. `skill` читается из общего места
# (`scripts/kinds.py`), потому что на нём стоят ещё четыре счётчика, и вторая
# копия имени разъехалась бы молча (022, 090).
MECHANISMS = {"gate", "pipeline", "document", "none", kinds.SKILL}
# Похоже на адрес в этом дереве: с косой чертой или с расширением.
ADDRESS_RE = re.compile(r"[\w./*-]+\.(?:py|md|json|ya?ml)|[\w.-]+/[\w./*-]+")


def load() -> dict[str, Any]:
    """Читает ответ проекта каталогу."""
    document: dict[str, Any] = json.loads(BINDINGS.read_text(encoding="utf-8"))
    return document


def answers() -> dict[str, dict[str, str]]:
    """Отдаёт ответы по правилам."""
    rules: dict[str, dict[str, str]] = load()["rules"]
    return rules


def test_every_rule_has_an_answer() -> None:
    """Пустых записей нет: у каждого правила каталога есть свой ответ."""
    rules = answers()
    assert rules, "ответ пуст — предмет проверки не найден (075)"
    assert all(isinstance(item, dict) and item.get("status") for item in rules.values())


def test_statuses_are_from_the_contract() -> None:
    """Статус — из четырёх объявленных контрактом, а не произвольное слово."""
    assert {item["status"] for item in answers().values()} <= STATUSES


def test_active_names_its_mechanism_and_address() -> None:
    """У активного ответа названы механизм и адрес, а не только статус."""
    for number, item in answers().items():
        if item["status"] != "active":
            continue
        assert item.get("mechanism") in MECHANISMS, f"{number}: механизм не назван"
        if item["mechanism"] != "none":
            assert item.get("where"), f"{number}: механизм назван, адрес — нет"
        else:
            assert item.get("why"), f"{number}: механизма нет, причина не названа (154)"
            # МАШИННАЯ ПОЛОВИНА СПРАШИВАЕТСЯ КОНТРАКТОМ, А ГЕЙТОМ НЕ СПРАШИВАЛАСЬ.
            # Контракт 1.3 требует `machine_half` при `active` и `mechanism:
            # none` — что именно следует из данных целиком и почему всё-таки не
            # построено. Держалось это только доброй волей: ответ по правилу 154
            # даже утверждал, что гейт требует оба поля, а гейт требовал одно.
            # Нашёл внешний взгляд на #427.
            assert item.get("machine_half"), (
                f"{number}: механизма нет, а машинная половина не разобрана — "
                "«пробовали, машинно нельзя» и «никто не пробовал» это разные "
                "состояния (182)"
            )


def test_negative_answers_name_the_reason() -> None:
    """«Отвергнуто» и «не относится» обязаны назвать причину (154, 184)."""
    for number, item in answers().items():
        if item["status"] in {"rejected", "not-applicable"}:
            assert item.get("why"), f"{number}: отрицательный ответ без причины — это молчание"


@pytest.mark.parametrize(
    "number",
    sorted(
        n
        for n, i in answers().items()
        # У механизма «none» адреса нет по построению: правило признано
        # действующим и не держится ничем, причина названа в why. Такой ответ
        # проверяется правилом 154, а не адресом.
        if i["status"] == "active" and i.get("mechanism") != "none"
    ),
)
def test_declared_address_resolves(number: str) -> None:
    """Адрес механизма существует в дереве: иначе это ложный механизм."""
    where = answers()[number].get("where", "")
    candidates = [
        address
        for address in ADDRESS_RE.findall(where)
        # Чужие адреса — действие каталога, ссылки на его записи — здесь не
        # разрешаются намеренно: их владелец другой, и правит их он (185).
        if "@" not in address and not address.startswith(("ArtVsMark/", "http"))
    ]
    # Раньше набор без адреса молча зеленел, и ответ `"where": "."` прошёл
    # гейт 183 целиком: проверять было нечего, и «нечего проверять» считалось
    # «проверено». Гейт, не нашедший предмета, обязан падать (075).
    assert candidates, (
        f"{number}: механизм назван, а адреса в прозе нет — "
        f"проверять нечего, и это отказ, а не «зелено»: {where!r}"
    )
    resolved = [
        address for address in candidates if (ROOT / address).exists() or list(ROOT.glob(address))
    ]
    assert resolved, f"{number}: ни один адрес не разрешается: {candidates}"


def test_proposals_assign_no_numbers() -> None:
    """Номер правилу присваивает каталог при приёме, а не проект (185).

    Два проекта, выбравшие номер независимо, дают столкновение, которое уже
    нечем починить: номера не переиспользуются. Поэтому поля ``id``, ``number``
    и ``rule`` в предложении — ошибка, и это сказано гейтом, а не только прозой
    в самом файле. Пустой список — законное состояние («предлагать нечего»);
    отсутствие файла означает другое — «канал не подключён» (075).
    """
    assert PROPOSALS.exists(), "канал предложений не подключён: .rules/proposals.json нет"
    document: dict[str, Any] = json.loads(PROPOSALS.read_text(encoding="utf-8"))
    assert document.get("schema"), "след предложения без версии контракта"
    items = document.get("proposals")
    assert isinstance(items, list), "поле proposals — список, пустой в том числе"
    for item in items:
        assigned = OWNED_BY_CATALOGUE & set(item)
        assert not assigned, f"номер присваивает каталог, а не проект: {sorted(assigned)}"


def test_this_project_leans_on_gates() -> None:
    """Проект про механизмы: доля правил, держащихся гейтом, не должна быть мала.

    Несоответствие этому ожиданию само есть находка: правило про конвейер, у
    которого здесь нет механизма, — либо пробел, либо неверная область.
    """
    active = [item for item in answers().values() if item["status"] == "active"]
    gates = [item for item in active if item.get("mechanism") == "gate"]
    assert len(gates) >= len(active) // 4, "механизмов-гейтов подозрительно мало для этого проекта"


#: Поля, обязательные у предложения по контракту каталога (export/README.md).
#: Список закрытый и взят оттуда, а не придуман здесь: расхождение форм значило
#: бы, что предложение уедет и не будет принято (162).
PROPOSAL_FIELDS = ("slug", "claim", "incident", "trail")
#: Насколько подробным должен быть инцидент. Число не из вкуса: «что сломалось,
#: С КОНКРЕТИКОЙ» — требование контракта, а строка короче этого конкретики не
#: несёт и заставит каталог спрашивать заново.
INCIDENT_AT_LEAST = 200


def proposals() -> list[dict[str, Any]]:
    """Предложения проекта каталогу."""
    document: dict[str, Any] = json.loads(PROPOSALS.read_text(encoding="utf-8"))
    said = document.get("proposals")
    return list(said) if isinstance(said, list) else []


#: Шов, оставшийся от дописывания: предложение приклеили к строке, которая уже
#: кончалась точкой. Признак узкий и НЕ «две точки где угодно»: точка, пробел
#: или его отсутствие — этого мало, чтобы отличить шов от адреса.
#:
#: ПОЧЕМУ ОБРАЗЕЦ ПРИШЛОСЬ СУЗИТЬ, И ЧЕГО ЭТО СТОИЛО. Первая редакция ловила
#: любые `..` вне троеточия — и относительный адрес площадки `../../issues/N`
#: попал под неё наравне со швом. Хуже того, этой же редакцией была сделана
#: массовая замена по дереву, и живой адрес в ответе по правилу 022 превратился
#: в `././issues/N`: гейт не поймал порчу, потому что порчу сделал он сам.
#: Нашёл внешний взгляд на #191, оба конца — и саму порчу, и слепоту образца.
#:
#: Шов — это КОНЕЦ ПРЕДЛОЖЕНИЯ, к которому приписали следующее: точка, за ней
#: точка, а дальше пробел и заглавная буква либо конец строки. В адресе за
#: второй точкой идёт `/`, и он сюда не попадает.
SEAM_RE = re.compile(r"(?<![.\d])\.\.(?=\s+[А-ЯЁA-Z]|\s*$)")


@pytest.mark.parametrize("number", sorted(answers()))
def test_an_answer_carries_no_seam_from_appending(number: str) -> None:
    """В прозе ответа нет шва от дописывания (замечание #188).

    Ответы дописываются по ходу: разобрали находку — приписали к `where`
    предложение о том, чем она теперь держится. Приписать к строке, уже
    кончавшейся точкой, — типовая ошибка этого приёма, и она не косметическая:
    ответ читает человек, а двойная точка ровно в месте стыка говорит, что
    строку собирали, не перечитав. Замер 11.09.2026: три шва, все — от правок
    этой смены.
    """
    answer = answers()[number]
    for field in ("where", "why"):
        said = str(answer.get(field) or "")
        found = SEAM_RE.search(said)
        assert not found, (
            f"{number}, поле «{field}»: шов от дописывания — "
            f"…{said[max(0, found.start() - 40) : found.end() + 20]}…"
        )


def test_an_empty_queue_is_a_declared_state_not_a_missing_one() -> None:
    """Пустая очередь предложений — объявленное состояние, а не молчание (154).

    Без этой строки набор на пустой очереди просто пропускает обе проверки
    ниже — «нет предмета» и «предмет проверен» становятся неотличимы (075).
    Пустой список законен и означает «предлагать пока нечего»; отсутствие
    файла означает другое — «канал не подключён», — и это разные состояния.
    """
    document: dict[str, Any] = json.loads(PROPOSALS.read_text(encoding="utf-8"))
    assert isinstance(document.get("proposals"), list), (
        "раздела предложений нет вовсе: «пусто» и «канала нет» — разные состояния"
    )
    assert any("пуст" in str(key) + str(value) for key, value in document.items()), (
        "пустое состояние не объявлено словами — читателю нечем отличить его от забытого"
    )


@pytest.mark.parametrize("item", proposals(), ids=lambda one: str(one.get("slug", "?")))
def test_a_proposal_carries_what_the_catalogue_asks(item: dict[str, Any]) -> None:
    """У предложения есть все поля контракта, и инцидент — с конкретикой.

    Потребитель шлёт ИНЦИДЕНТ, а не готовую запись: что сломалось, с числами и
    последовательностью событий. Предложение без этого каталог принять не может
    — ему придётся спрашивать заново, и правило, родившееся здесь, останется
    здесь (080).
    """
    for field in PROPOSAL_FIELDS:
        assert item.get(field), f"{item.get('slug', '?')}: поля «{field}» нет"
    assert len(str(item["incident"])) >= INCIDENT_AT_LEAST, (
        f"{item['slug']}: инцидент без конкретики — каталогу придётся спрашивать заново"
    )


@pytest.mark.parametrize("item", proposals(), ids=lambda one: str(one.get("slug", "?")))
def test_a_proposal_trail_resolves_in_the_tree(item: dict[str, Any]) -> None:
    """След предложения — артефакт ЭТОГО дерева, где поломка видна (044).

    Ссылка на то, чего нет, превращает инцидент в рассказ: проверить его
    каталог не сможет, а поверить ему — не должен.
    """
    said = str(item.get("trail") or "")
    assert (ROOT / said).exists(), f"{item.get('slug', '?')}: след «{said}» не разрешается"


def test_a_slug_is_shaped_as_the_catalogue_asks() -> None:
    """Слаг — короткое имя латиницей: по нему каталог отвечает по каждому."""
    for item in proposals():
        said = str(item.get("slug") or "")
        assert re.fullmatch(r"[a-z0-9-]+", said), f"слаг «{said}» не по форме контракта"


# --- контракт 1.5: у ответа, которого не держит машина, назван предел ---------


#: Признак ЗАМЕРА в тексте: число, «ноль», «ни одного», «первый». Образец взят
#: у каталога — им он держит то же поле — и проверяет, что вопрос ЗАМЕРЕН, а не
#: что замер верен: второе требует чтения, а не разбора (182).
COUNTED_RE: Final = re.compile(
    r"\d|\bноль\b|\bни одного\b|\bни одной\b|\bпервый\b|\bпервая\b|\bпервое\b", re.I
)


#: Слова предела — ЗАКРЫТЫЙ словарь каталога, контракт 1.5. Счётчику доли
#: машинного соблюдения знаменатель надо РАЗДЕЛИТЬ, а прозу сложить нельзя.
#:   no          — машинной половины нет вовсе, текст и есть предел;
#:   not-yet     — половина есть и не построена, стройка возможна сегодня;
#:   conditional — станет возможна, когда появится названный ПРЕДМЕТ; до него
#:                 гейт зеленел бы вокруг пустоты (146), и предмет называется
#:                 полем `awaiting`.
#:
#: НАШЕ ЧЕТВЁРТОЕ СЛОВО СНЯТО, И ЭТО ЗАМЕР, А НЕ УСТУПКА. С 13.09.2026 здесь
#: жило собственное `measured-refusal` — «половина есть и ОТВЕРГНУТА замером», —
#: заведённое, когда словарь каталога был из двух слов. Перечитывание всех
#: восьми ответов под словарь из трёх (17.09.2026) показало, что слово было
#: ПЕРЕРАСШИРЕНО: шесть означали `no` (машинной половины нет: имя окна из дерева
#: убрано решением, приёмка роли решается смыслом, границы чужой выборки машине
#: неизвестны), один — `conditional` (машина повтор отличит, предмета ноль).
#: Остаток ОДИН — 133, и словаря на него нет: половина считается, а гейт краснел
#: бы на том, что решение 008 прямо разрешает. Он записан наименее ложным словом
#: с названной ценой в `why` и отправлен каталогу предложением; своё слово рядом
#: с чужим словарём не заводится — разойдясь, они дали бы два ответа на один
#: вопрос
#: ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
#: [157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).
LIMITS: Final = ("no", "not-yet", "conditional")

#: Механизмы, которые КРАСНЕЮТ. У прочих — `document`, `none`, `skill` —
#: исполнение не проверяется ничем, и вопрос «а можно ли держать машиной» у всех
#: троих один. Прежде он задавался только `document`, и два ответа оставались
#: вне счёта.
#:
#: БЕРЁТСЯ ИЗ ОБЩЕГО МЕСТА, А НЕ ПЕРЕЧИСЛЯЕТСЯ ЗДЕСЬ. Первая редакция написала
#: свой кортеж `("gate", "pipeline")` — ПЯТУЮ копию того же набора и первую, что
#: с ним разошлась: канон `kinds.MACHINE` содержит ещё и `code`. Прочие четыре
#: читателя (family, drift, build_facts, review_map) спрашивают канон, и только
#: эта копия жила своей жизнью. Вреда сегодня не вышло по СОСЕДНЕЙ причине, а не
#: по своей: `MECHANISMS` выше не разрешает нам писать `code` вовсе, и ответа
#: такого вида в файле возникнуть не может. Но это значит, что расхождение было
#: невидимо, а не безвредно (нашёл внешний взгляд на #442; 022, 090).
#:
#: Набор `MECHANISMS` выше — НЕ та же копия и остаётся своей: он отвечает на
#: другой вопрос — «что мы вправе написать в СВОЁМ ответе», — и его отличие от
#: набора каталога объявлено там же.
MACHINE_KINDS: Final = kinds.MACHINE


def unheld(answers: dict[str, Any] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Действующие ответы, которых не держит машина, — предмет предела.

    Ответы принимаются доводом, чтобы предикат проверялся ПРЯМО, а не только
    через живой файл: вида, которого у нас нет сегодня, в файле не найти, и
    разбор на нём не проверить иначе (107).
    """
    said = load()["rules"] if answers is None else answers
    return [
        (rule, one)
        for rule, one in said.items()
        if one.get("status") == "active" and (one.get("mechanism") or "none") not in MACHINE_KINDS
    ]


def test_the_predicate_of_the_limit_has_a_subject() -> None:
    """Предмет у проверки предела есть — иначе она доказывает только себя (075)."""
    assert len(unheld()) >= 5, f"ответов не под машиной {len(unheld())} — предмет не найден"


def test_every_unheld_answer_names_its_limit() -> None:
    """У каждого ответа вне машины сказано, есть ли машинная половина вовсе.

    Требуется от ВСЕХ, а не только от новых: оставить часть без ответа значило
    бы сделать вид, что их не разбирали.
    """
    bare = [rule for rule, one in unheld() if one.get("holdable") not in LIMITS]
    assert not bare, "ответ вне машины без названного предела: " + ", ".join(sorted(bare))


def test_a_conditional_limit_names_the_subject_it_waits_for() -> None:
    """`conditional` без события неотличим от долга, отложенного на «когда-нибудь».

    Событие называется полем `awaiting`, и отсутствие предмета там ИЗМЕРЕНО:
    в тексте есть число. «Пока рано» выводило бы правило из счёта долга даром.
    """
    silent = [
        rule
        for rule, one in unheld()
        if one.get("holdable") == "conditional"
        and not COUNTED_RE.search(str(one.get("awaiting") or ""))
    ]
    assert not silent, "«при условии» без замеренного предмета: " + ", ".join(sorted(silent))


def test_awaiting_is_absent_where_the_mechanism_reddens() -> None:
    """У готового механизма «ждём предмета, чтобы строить» утверждает неправду."""
    wrong = [
        rule
        for rule, one in load()["rules"].items()
        if str(one.get("awaiting") or "").strip()
        and (one.get("mechanism") or "none") in MACHINE_KINDS
    ]
    assert not wrong, "механизм краснеет, а поле awaiting осталось: " + ", ".join(sorted(wrong))


def test_a_date_in_an_answer_is_iso_and_not_in_the_future() -> None:
    """Даты ответа сравнивает машина: «16.09» и «Sep 16» она сравнить не может.

    Отсутствие даты — законный ответ «не сверяли». Неверная дата законной не
    бывает: её нельзя ни сравнить, ни отличить от опечатки (039).
    """
    today = date.today()
    broken: list[str] = []
    for rule, one in load()["rules"].items():
        for field in ("analysed", "decided"):
            raw = str(one.get(field) or "")
            if not raw:
                continue
            try:
                when = date.fromisoformat(raw)
            except ValueError:
                broken.append(f"{rule}.{field}=«{raw[:20]}»")
                continue
            if when > today:
                broken.append(f"{rule}.{field} в будущем: {raw}")
    assert not broken, "дата ответа негодна: " + ", ".join(broken)


def test_a_verdict_is_not_newer_than_the_look_that_produced_it() -> None:
    """Решают, посмотрев: `decided` не может быть позже `analysed`, и не бывает без него."""
    wrong: list[str] = []
    for rule, one in load()["rules"].items():
        decided, analysed = str(one.get("decided") or ""), str(one.get("analysed") or "")
        if not decided:
            continue
        if not analysed:
            wrong.append(f"{rule}: вердикт датирован, а сверка — нет")
        elif date.fromisoformat(decided) > date.fromisoformat(analysed):
            wrong.append(f"{rule}: вердикт {decided} новее сверки {analysed}")
    assert not wrong, "; ".join(wrong)


def test_a_named_limit_carries_its_reason() -> None:
    """Рядом с пределом стоит причина: значение из двух выбирается не думая.

    Причину не написать, не подумав, — этим она и держит выбор (154).
    """
    answers = load()["rules"]
    silent = [
        rule
        for rule, one in answers.items()
        if one.get("holdable") and not str(one.get("why") or "").strip()
    ]
    assert not silent, "предел назван без причины: " + ", ".join(sorted(silent))


def test_the_seam_pattern_does_not_see_a_relative_address() -> None:
    """Адрес площадки швом не считается (находка #191).

    `../../issues/7` — рабочая нотация, и первая редакция образца ловила её
    наравне со швом. Этой же редакцией была сделана массовая замена по дереву,
    и живой адрес превратился в `././issues/7`: гейт не поймал порчу, потому
    что порчу сделал он сам. Проверяется обоими концами — что адрес проходит и
    что шов ловится.
    """
    assert not SEAM_RE.search("ссылка ../../issues/7 и ../pull/9 — рабочие адреса")
    assert not SEAM_RE.search("многоточие … и «и т. д.» тоже не шов")
    assert SEAM_RE.search("первое предложение.. Второе началось")
    assert SEAM_RE.search("строка кончилась швом..")


def test_no_answer_carries_a_broken_relative_address() -> None:
    """В ответах нет адреса вида `././` — следа массовой замены (находка #191).

    Отдельная проверка, а не доверие к образцу выше: тот ловит ПРИЧИНУ, эта —
    СЛЕД. Причина уже была исправлена однажды, а след остался бы в дереве.
    """
    said = json.dumps(answers(), ensure_ascii=False)
    assert "././" not in said, "в ответе остался адрес, испорченный массовой заменой"


#: Адрес навыка внутри ответа: контракт 1.4 требует ровно эту форму.
SKILL_ADDRESS_RE: Final = re.compile(r"\.claude/skills/[\w-]+")
#: Механизм, рядом с которым навык ЗАПРЕЩЁН контрактом: «не держится ничем» и
#: «держится навыком» — разные ответы, и второй не прячется в первом.
NO_SKILL_BESIDE: Final = "none"


def named_skill() -> list[str]:
    """Правила, чей ответ несёт поле `skill`."""
    return sorted(n for n, one in answers().items() if one.get("skill"))


@pytest.mark.parametrize("number", named_skill())
def test_a_named_skill_resolves(number: str) -> None:
    """Адрес навыка разрешается в дереве, а не остаётся обещанием.

    `mechanism: skill` и поле `skill` — утверждение о механизме, и оно обязано
    проверяться механизмом. Проверяемого у навыка ровно столько: он есть в
    дереве и у него есть `SKILL.md`. Что навык СРАБОТАЛ, не проверяет никто, и
    это его названная граница, а не упущение
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).

    Форму самого навыка — непустые `name`, `description` и совпадение имени с
    каталогом — держит `tests/test_rulebook_fresh.py`, и второй копии этой
    проверки здесь нет
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    Проверяет это НАШ гейт, а не каталог: каталог читает ответ по HTTPS и
    нашего дерева не видит — та же граница, что у `where`.
    """
    address = str(answers()[number]["skill"])
    assert SKILL_ADDRESS_RE.fullmatch(address), (
        f"{number}: адрес навыка не той формы — контракт ждёт "
        f"`.claude/skills/<имя>`, а стоит {address!r}"
    )
    assert (ROOT / address / "SKILL.md").is_file(), (
        f"{number}: ответ называет навык {address}, а SKILL.md по этому адресу нет — "
        "ложный механизм хуже отсутствия ответа: он выглядит выполненным"
    )


def test_a_skill_named_in_prose_is_named_by_the_field() -> None:
    """Навык, на который ответ опирается прозой, назван и ПОЛЕМ.

    ЗАЧЕМ ПОЛЕ, ЕСЛИ АДРЕС УЖЕ В ПРОЗЕ. Проза не считается: доля машинного
    соблюдения по семье считается по полям, и навык, названный только словами,
    для счётчика не существует вовсе. Контракт 1.4 завёл поле рядом со
    значением именно потому, что навык бывает ВТОРОЙ половиной — гейт берёт
    машинное, навык берёт остаток, — и одним значением `mechanism` этот случай
    не выразить: пришлось бы выбирать, какую половину спрятать.

    ЗАМЕР 17.09.2026 ПО ВСЕМУ ДЕРЕВУ: из 203 ответов адрес навыка называли
    прозой ДВА (047 и 082), и поля не нёс НИ ОДИН. Каталог увидел это раньше
    нас и назвал нас в контракте поимённо. Предикат меряется по всем ответам, а
    не по этим двум: следующий такой ответ напишется так же — прозой, — и
    молча.
    """
    leaning = {
        number: sorted(
            set(
                SKILL_ADDRESS_RE.findall(
                    # ТРИ ПРОЗАИЧЕСКИХ ПОЛЯ ОТВЕТА, А НЕ ОДНО. `machine_half`
                    # здесь не про запас: у ответа «не держится ничем» адрес
                    # навыка в прозе — прямое противоречие, потому что контракт
                    # запрещает поле `skill` рядом с `none`. Найденный там навык
                    # обязан покраснеть, и краснеет он дважды — здесь и у
                    # `test_no_skill_stands_beside_an_empty_mechanism`. Внешний
                    # взгляд назвал эту часть предиката недокументированной
                    # (#420), и он был прав: она стояла без причины.
                    " ".join(str(one.get(key) or "") for key in ("where", "why", "machine_half"))
                )
            )
        )
        for number, one in answers().items()
    }
    silent = {
        number: found
        for number, found in leaning.items()
        if found and not answers()[number].get("skill")
    }
    assert not silent, "ответ опирается на навык прозой, а полем его не называет: " + "; ".join(
        f"{number} → {', '.join(found)}" for number, found in sorted(silent.items())
    )


def test_a_skill_mechanism_names_its_skill() -> None:
    """`mechanism: skill` без поля `skill` — механизм без адреса.

    Зеркало к `test_active_names_its_mechanism_and_address`: там адрес спрошен
    у гейта, здесь — у навыка. Разными полями, потому что предметы разные:
    `where` разрешается путём в дереве, `skill` — каталогом навыка.
    """
    bare = [
        number
        for number, one in answers().items()
        if one.get("mechanism") == kinds.SKILL and not one.get("skill")
    ]
    assert not bare, "механизм назван навыком, а навык не назван: " + ", ".join(bare)


def test_no_skill_stands_beside_an_empty_mechanism() -> None:
    """Рядом с `mechanism: none` навыка быть не может.

    «Правило действует и не держится ничем» и «держится навыком» — два разных
    состояния, и слияние их прячет механизм внутри ответа о его отсутствии
    (045). Контракт запрещает это прямо.
    """
    mixed = [
        number
        for number, one in answers().items()
        if one.get("mechanism") == NO_SKILL_BESIDE and one.get("skill")
    ]
    assert not mixed, "ответ «не держится ничем» называет навык — состояния слиты: " + ", ".join(
        mixed
    )


def test_a_machine_mechanism_is_never_asked_for_a_limit() -> None:
    """У механизма, который КРАСНЕЕТ, предела не спрашивают — ему нечего им отвечать.

    Проверяется тем видом, которого у нас сегодня нет: `code` есть в каноне
    `kinds.MACHINE`, и у соседа им держатся 13 правил. Первая редакция этой
    проверки завела свой кортеж без него — и потребовала бы `holdable` у
    механизма, который исполнение проверяет (нашёл внешний взгляд на #442).
    """
    for kind in sorted(kinds.MACHINE):
        said = {"999": {"status": "active", "mechanism": kind}}
        assert unheld(said) == [], f"у механизма «{kind}» спрошен предел, а он краснеет"


def test_a_non_machine_mechanism_is_asked_for_a_limit() -> None:
    """Вторая половина: у того, что машиной не держится, предел спрашивают.

    Без неё послабление снесло бы предмет целиком — набор, признающий машинным
    что угодно, не отличить от отсутствия проверки (051).
    """
    for kind in ("document", "none", kinds.SKILL):
        said = {"999": {"status": "active", "mechanism": kind}}
        assert unheld(said) != [], f"у механизма «{kind}» предел не спрошен, а он ничего не держит"


#: Признак ПРЕДИКАТА ПО ДЕРЕВУ в ответе «неприменимо»: путь, обратная кавычка с
#: командой либо число. Правило 205 родилось здесь и требует, чтобы вердикт
#: «неприменимо» нёс то, чем его можно ОПРОВЕРГНУТЬ, — а «правило вступит, когда
#: заведём второй язык» охраняет от устаревания и не охраняет от ошибки
#: прочтения, самой частой у нас: 22 ответа за историю сменились с «неприменимо»
#: на «действует», и причина у них одна — отвечали не на тот вопрос.
#:
#: ФОРМ АДРЕСА ДВЕ, И ВТОРУЮ ЧУТЬ НЕ ЗАБЫЛИ: путь с расширением
#: (`scripts/x.py`) и путь-КАТАЛОГ без него (`.github/workflows/`). Первая
#: редакция образца знала одну и не считала предикатом «в .github/workflows/ ни
#: одного такого шага» — то есть требовала бы переписать законный ответ. Поймано
#: вторым концом проверки, а не взглядом (051).
TREE_PREDICATE: Final = re.compile(
    r"[\w./-]+\.(?:py|md|json|ya?ml)|[\w.-]+/[\w./-]*|`[^`]+`|\bgit\s+\w+|\bgrep\b|\d"
)


def inapplicable() -> list[tuple[str, dict[str, Any]]]:
    """Ответы «неприменимо» — предмет проверки предиката."""
    return [
        (rule, one)
        for rule, one in load()["rules"].items()
        if one.get("status") == "not-applicable"
    ]


def test_the_inapplicable_band_has_a_subject() -> None:
    """Предмет есть, иначе проверка доказывает только себя (075)."""
    assert len(inapplicable()) >= 5, f"«неприменимо» {len(inapplicable())} — предмет не найден"


def test_every_inapplicable_answer_names_a_predicate_over_the_tree() -> None:
    """Вердикт «неприменимо» несёт то, чем его можно опровергнуть (205).

    ЗАМЕР 17.09.2026, полный обход полосы: из 14 живых «неприменимо» предикат
    несли СЕМЬ; семи остальным он написан и прогнан — каждый проверен командой в
    тот же день, а не объявлен. Правило родилось здесь, и держать его было нечем.
    """
    bare = [
        rule
        for rule, one in inapplicable()
        if not TREE_PREDICATE.search(str(one.get("why") or one.get("where") or ""))
    ]
    assert not bare, (
        "ответ «неприменимо» без предиката по дереву: " + ", ".join(sorted(bare)) + " — назовите, "
        "ЧТО должно появиться в дереве, чтобы ответ стал ложным, и проверьте это командой"
    )


def test_an_event_alone_is_not_a_predicate() -> None:
    """Второй конец: одного СОБЫТИЯ мало, и образец это различает.

    «Правило вступит вместе с первым подагентом» — событие: оно охраняет от
    устаревания и не охраняет от ошибки прочтения. Без этого конца образец,
    принимающий любую прозу, был бы неотличим от отсутствия проверки (051).
    """
    assert not TREE_PREDICATE.search("правило вступит вместе с первым подагентом")
    assert not TREE_PREDICATE.search("предмета у правила в проекте нет и не предвидится")
    assert TREE_PREDICATE.search("`git ls-files '*.po'` даёт ноль файлов")
    assert TREE_PREDICATE.search("в .github/workflows/ ни одного такого шага")


#: Где живут навыки проекта. Один адрес на гейт и на поле ответа: два понимания
#: «где лежит навык» разошлись бы молча (022).
SKILLS_DIR: Final = ROOT / ".claude" / "skills"
#: Ссылка на правило внутри навыка: `rules/ru/NNN-…`.
RULE_IN_SKILL: Final = re.compile(r"rules/ru/(\d{3})")


def skills_citing() -> list[tuple[str, str]]:
    """Пары «адрес навыка — номер правила, которое он цитирует»."""
    found: list[tuple[str, str]] = []
    for skill in sorted(SKILLS_DIR.iterdir()):
        card = skill / "SKILL.md"
        if not card.is_file():
            continue
        said = card.read_text(encoding="utf-8")
        for rule in sorted(set(RULE_IN_SKILL.findall(said))):
            found.append((f".claude/skills/{skill.name}", rule))
    return found


def test_the_skills_cite_rules_at_all() -> None:
    """Предмет есть: навыки ссылаются на правила, иначе сверять нечего (075)."""
    assert len(skills_citing()) >= 10, f"ссылок навыков на правила {len(skills_citing())}"


def test_a_skill_holding_an_unmachined_rule_is_named_by_its_answer() -> None:
    """Навык, цитирующий правило ВНЕ МАШИНЫ, назван ответом на это правило.

    Навык — это МОМЕНТ: он срабатывает в минуту вызова, тогда как документ
    читается один раз при старте окна. Если правило держится навыком, а ответ об
    этом молчит, счёт «чем держится проект» считает его неудержанным, и внешний
    взгляд идёт искать глазами то, у чего процедура есть.

    ЗАМЕР 17.09.2026: навыков шесть, назван ответами был ОДИН. Три правила вне
    машины держались навыком молча — 044, 062, 107, — и нашлось это вопросом
    человека, а не механизмом.

    ПРЕДМЕТ СУЖЕН ДО ПРАВИЛ ВНЕ МАШИНЫ, и это не послабление. Навык цитирует
    правила и как ДОВОД — `build-a-gate` ссылается на 051, 075, 139, объясняя
    себя, а держатся они гейтами. Требовать поля от них значило бы объявить
    навык механизмом всего, на что он сослался (051).
    """
    unnamed = [
        f"{rule} → {skill}"
        for skill, rule in skills_citing()
        if (one := answers().get(rule))
        if one.get("status") == "active"
        if (one.get("mechanism") or "none") not in MACHINE_KINDS
        if one.get("skill") != skill
    ]
    assert not unnamed, (
        "правило вне машины цитируется навыком, а ответ навыка не называет: "
        + ", ".join(sorted(unnamed))
        + " — либо назовите его полем `skill`, либо уберите ссылку из навыка"
    )
