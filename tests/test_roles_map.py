"""Карта направлений против правила 082: полнота и форма записи.

ПОЧЕМУ КАРТА ВООБЩЕ ЕСТЬ. Правило требует, чтобы у каждого пласта продукта был
владелец вопроса, и прямо говорит, что покрытие НЕ равно штату: направление
бывает профилем существующей роли. Проект долго отвечал «неприменимо, потому что
исполнителей двое» — то есть отвечал на вопрос о должностях, а правило спрашивает
о вопросах
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

ЧТО ДЕРЖИТ ГЕЙТ, А ЧТО НЕТ. Гейт судит ПОЛНОТУ и ФОРМУ: назван ли каждый вопрос
правила и объявлен ли по нему исход. Верен ли исход, машина не знает — это
чтение, и оно за человеком
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
Вторую половину — обход вопросов при взятии работы — держит навык, а не гейт:
навык читается в момент вызова, и предмета в дереве у него нет по построению.

МОЛЧАНИЕ КАТАЛОГА — СВОЙ ИСХОД. Список направлений живёт в самом правиле, и
проверка полноты его оттуда и берёт. Недоступный каталог — отказ КАНАЛА, а не
находка о дереве: проверка пропускается с названной причиной, ровно как у сверки
ссылок на правила
([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

catalogue = load_script("catalogue.py")

MAP: Final = ROOT / "docs" / "roles.md"
#: Номер правила, чью карту мы ведём. Один литерал: второе написание того же
#: разошлось бы с первым молча (022).
RULE: Final = "082"

#: Строка карты: направление, исход, обоснование. Заголовки таблиц и
#: разделители сюда не попадают — у них другое число ячеек или дефисы вместо
#: текста.
ROW_RE: Final = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<outcome>[^|]+?)\s*\|\s*(?P<why>[^|]+?)\s*\|$", re.M
)

#: Объявленные исходы. Список разрешительный (068): пометка вне его — не исход,
#: а мнение, и сравнивать по ней нечего. «Профиль» допускает уточнение чьим
#: именно — «профиль каталога», «профиль владельца», — потому что это ответ на
#: вопрос «кто задаёт», а не другой исход.
OUTCOMES: Final = ("профиль", "роли нет", "артефакта нет", "пласта нет")

#: Строка таблицы направлений в самом правиле: имя, вопрос, чем владеет.
RULE_ROW_RE: Final = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<question>[^|]+?)\s*\|\s*(?P<owns>[^|]+?)\s*\|$", re.M
)
#: Заголовок таблицы правила: по нему строки заголовков и отбиваются.
RULE_HEAD: Final = "Направление"


def rows() -> dict[str, tuple[str, str]]:
    """Наша карта: направление → (исход, обоснование)."""
    found: dict[str, tuple[str, str]] = {}
    for one in ROW_RE.finditer(MAP.read_text(encoding="utf-8")):
        name = one["name"]
        if name == "Направление" or set(name) <= set("- "):
            continue
        found[name] = (one["outcome"], one["why"])
    return found


def directions_of_the_rule() -> list[str]:
    """Направления, названные самим правилом; молчание канала — `Silent`."""
    export = catalogue.read(catalogue.EXPORT_URL)
    # Выгрузка отдаёт правила СПИСКОМ, и номер здесь ищется, а не индексирует:
    # форма чужого документа — его дело, и полагаться на неё как на словарь
    # значило бы молча сломаться при первой же смене формы (055).
    one = next((rule for rule in export["rules"] if str(rule.get("id")) == RULE), None)
    assert one is not None, f"в выгрузке каталога нет правила {RULE} — договор разошёлся"
    where = one["files"]["ru"]
    said = catalogue.read_text(f"{catalogue.RAW}/main/{where}")
    found: list[str] = []
    for one in RULE_ROW_RE.finditer(said):
        name = one["name"]
        if name == RULE_HEAD or set(name) <= set("- "):
            continue
        found.append(name)
    return found


def test_the_map_has_rows_to_judge() -> None:
    """Карта разобрана: без строк проверки ниже — поверхность без предмета (075)."""
    assert len(rows()) >= 30, f"строк карты разобрано {len(rows())} — разбор её не видит"


@pytest.mark.parametrize("name", sorted(rows()), ids=lambda one: str(one))
def test_every_direction_declares_one_of_the_outcomes(name: str) -> None:
    """У направления объявлен исход из закрытого списка, а не своими словами.

    Пометка вне списка — не исход, а мнение: по ней нельзя ни посчитать дыры,
    ни отличить «ждёт работы» от «не наш пласт» (068).
    """
    outcome, _ = rows()[name]
    assert outcome.startswith(OUTCOMES), (
        f"«{name}»: исход «{outcome}» не из объявленных — {', '.join(OUTCOMES)}"
    )


@pytest.mark.parametrize("name", sorted(rows()), ids=lambda one: str(one))
def test_a_hole_names_what_it_is(name: str) -> None:
    """Дыра названа обоснованием, а не одним словом «нет».

    «Роли нет» без объяснения снаружи неотличимо от «не дошли руки»: читатель
    не знает ни предмета, ни того, чем это уже кусалось (046, 154).
    """
    outcome, why = rows()[name]
    if not outcome.startswith("роли нет"):
        pytest.skip("исход не «роли нет» — обоснование здесь не обязательно")
    assert len(why) >= 40, f"«{name}»: дыра объявлена без объяснения — «{why}»"


def test_the_map_names_every_direction_of_the_rule() -> None:
    """Карта покрывает ВСЕ направления правила, а не те, что вспомнились.

    Дыра в составе не обнаруживается чтением списка ролей — список выглядит
    внушительно ровно настолько, насколько внушительны те роли, что в нём есть.
    Поэтому полнота сверяется с источником, а не с памятью (005, 055).
    """
    try:
        named = directions_of_the_rule()
    except catalogue.Silent as why:
        pytest.skip(f"каталог не ответил — предмет проверки недоступен: {why}")
    assert named, "в правиле не разобрано ни одного направления — разбор сломан (075)"
    missing = [one for one in named if one not in rows()]
    assert not missing, f"направления правила не названы в карте: {missing}"


def test_the_map_invents_no_direction_of_its_own() -> None:
    """И обратно: в карте нет направлений, которых правило не называет.

    Своё направление в карте — это либо опечатка в имени, из-за которой строка
    правила считается непокрытой, либо роль, придуманная здесь и не прошедшая
    приёмку правила 062.
    """
    try:
        named = set(directions_of_the_rule())
    except catalogue.Silent as why:
        pytest.skip(f"каталог не ответил — предмет проверки недоступен: {why}")
    extra = [one for one in rows() if one not in named]
    assert not extra, f"в карте направления, которых правило не называет: {extra}"
