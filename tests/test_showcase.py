"""Витрина отвечает на объявленный набор вопросов — или называет, чего нет.

Набор один на все проекты семьи и взят у каталога: разные наборы не сравнить, и
то, что проект перестал отвечать, не заметит никто (022). Замер каталога по
пяти публичным проектам: из восьми вопросов пять отвечал один грейдер, остальные
четыре — ни одного.

Проверяется здесь то, без чего ответ витрине был бы объявлением намерения:

* на КАЖДЫЙ вопрос набора есть ответ — значок, адрес или названная причина;
* причина отсутствия — предложение, а не отписка: отсутствующий значок и
  застывший с витрины неотличимы (046, 075);
* у вопроса посетителя значок ПОКАЗАН в витрине: значок, которого никто не
  видит, отвечает в пустоту;
* у вопроса сопровождающего адрес РАЗРЕШАЕТСЯ в дереве, а не назван прозой (049).
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, badges_shown, load_script

facts = load_script("build_facts.py")

SHOWCASE = ROOT / ".rules" / "showcase.json"
README = ROOT / "README.md"
#: Насколько длинной должна быть причина, чтобы ею что-то объяснялось. Число
#: взято у каталога, где правило родилось: короче — это отписка, а не причина.
REASON_AT_LEAST = 20


def answers() -> list[dict[str, Any]]:
    """Ответы проекта по вопросам витрины."""
    said = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    return list(said["questions"])


def test_the_showcase_answer_exists() -> None:
    """Ответ витрине заведён и непуст — иначе проверять нечего (075)."""
    assert SHOWCASE.is_file(), "ответа витрине нет вовсе"
    assert len(answers()) >= 5, "набор вопросов подозрительно мал"


@pytest.mark.parametrize("question", answers(), ids=lambda q: str(q["id"]))
def test_every_question_has_an_answer(question: dict[str, Any]) -> None:
    """У вопроса либо значок, либо адрес, либо названная причина.

    Пропуск не проходит: вопрос без ответа выглядит как забытый, а не как
    решённый, и отличить одно от другого снаружи нельзя.
    """
    kinds = [key for key in ("badge", "where", "absent") if question.get(key)]
    assert kinds, f"{question['id']}: ответа нет ни в каком виде"
    assert len(kinds) == 1, f"{question['id']}: ответов сразу несколько — {kinds}"


@pytest.mark.parametrize(
    "question", [q for q in answers() if q.get("absent")], ids=lambda q: str(q["id"])
)
def test_an_absent_answer_explains_itself(question: dict[str, Any]) -> None:
    """Причина отсутствия — объяснение, а не отписка."""
    said = str(question["absent"]).strip()
    assert len(said) >= REASON_AT_LEAST, f"{question['id']}: причина слишком коротка"


#: Адрес опубликованного числа: файл витрины и путь к ключу внутри него.
PUBLISHED: Final = re.compile(r"^(?:\.github/badges/)?[\w.-]+\.json#[\w.]+$")


@cache
def collected() -> dict[str, Any]:
    """Факты, собранные ТЕМ ЖЕ механизмом, что публикует витрину.

    Сборка одна на весь модуль: она ходит по всему дереву, и повтор на каждый
    вопрос стоил бы секунд на ровном месте.
    """
    build = load_script("build_facts.py")
    return dict(build.collect(ROOT, sha="проверка", mine=""))


@pytest.mark.parametrize(
    "question", [q for q in answers() if q.get("where")], ids=lambda q: str(q["id"])
)
def test_a_maintainer_answer_points_at_the_published_number(question: dict[str, Any]) -> None:
    """Адрес ведёт к ОПУБЛИКОВАННОМУ числу, а не к тому, чем его считают.

    Рецепт для человека («получается прогоном pytest -q») разошёлся бы с деревом
    молча: у сопровождающего должен быть адрес, по которому число ЖИВЁТ
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

    ПУТЬ К СКРИПТУ ЭТОМУ НЕ ОТВЕЧАЕТ, И ПРЕЖНЯЯ ПРОВЕРКА ЕГО ПРИНИМАЛА. Она
    спрашивала лишь, разрешается ли путь в дереве, — и три ответа сопровождающему
    называли `scripts/build_facts.py` и `.pipeline.yml`, то есть ВЫЧИСЛИТЕЛЬ.
    Сосед, пришедший по такому адресу, обязан склонировать нас и посчитать число
    сам по нашему определению; копия чужого определения верна до первой правки на
    той стороне и расходится молча
    ([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)).

    Поэтому форма адреса — `<опубликованный файл>#<путь.к.ключу>`, и ключ обязан
    существовать в СОБРАННЫХ фактах, а не только в объявлении: проверять адрес по
    тому же файлу, который его и объявляет, значило бы сравнивать запись с самой
    собой
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    said = str(question["where"])
    assert PUBLISHED.match(said), (
        f"{question['id']}: адрес «{said}» — путь в дереве, а не опубликованное число."
        " Форма: .github/badges/facts.json#путь.к.ключу"
    )
    assert question.get("branch"), f"{question['id']}: не названа ветка, где лежит опубликованное"
    _, _, path = said.partition("#")
    value: Any = collected()
    for step in path.split("."):
        assert isinstance(value, dict) and step in value, (
            f"{question['id']}: в собранных фактах нет ключа «{path}» — адрес ведёт в пустоту (075)"
        )
        value = value[step]
    assert value is not None, f"{question['id']}: по адресу «{path}» нет значения"


@pytest.mark.parametrize(
    "question", [q for q in answers() if q.get("badge")], ids=lambda q: str(q["id"])
)
def test_a_visitor_badge_is_shown_and_built(question: dict[str, Any]) -> None:
    """Значок посетителя показан в витрине и собирается механизмом.

    Значок, которого никто не показывает, отвечает в пустоту; значок, который
    никто не собирает, застывает — и с витрины эти два случая неотличимы.
    """
    name = Path(str(question["badge"])).name
    shown = badges_shown(README.read_text(encoding="utf-8"))
    assert name in shown, f"{question['id']}: значка нет в витрине — показано {sorted(shown)}"
    source = (ROOT / "scripts" / "build_facts.py").read_text(encoding="utf-8")
    assert name in source, f"{question['id']}: значок объявлен, а собирать его нечем"


def test_a_badge_from_another_branch_is_not_expected_in_the_tree() -> None:
    """Значок с ветки `badges` в дереве общей ветки не лежит и не должен (125).

    Требовать его здесь значило бы требовать того, чего быть не может: ветка
    заведена ровно для того, чтобы пересборка не двигала общую.
    """
    for question in answers():
        badge = question.get("badge")
        if badge and question.get("branch") == "badges":
            assert not (ROOT / str(badge)).exists(), f"{question['id']}: артефакт вернулся в дерево"


def own() -> list[dict[str, Any]]:
    """Свои значки проекта — те, что рисуются сверх общего набора вопросов."""
    said = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    return list(said.get("own") or [])


def drawn() -> set[str]:
    """Что сборка РИСУЕТ — спрошено у её инвентаря, а не выписано сюда.

    Список, выписанный в проверку рукой, отстаёт молча и при этом зеленеет:
    ровно так `tests/test_facts.py` два месяца сверял четыре имени из шести
    (146). Здесь предмет тот же, и источник поэтому один — `build_facts.BADGES`.
    """
    names = set(facts.BADGES)
    assert len(names) >= 5, f"сборка рисует {sorted(names)} — предмет проверки не найден (075)"
    return names


def test_every_badge_the_build_draws_is_named_by_the_showcase() -> None:
    """ОБРАТНЫЙ ХОД: нарисованное объявлено — вопросом набора либо своим.

    Прежде проверка шла только в одну сторону, объявление → дерево: у каждого
    ОБЪЯВЛЕННОГО значка спрашивалось, показан ли он и собирается ли. Значок,
    который собирается и не объявлен, для набора не существовал вовсе — и так
    вышло с четырьмя из шести. Замер 17.09.2026: сборка рисует шесть значков,
    витрина знала два.

    Это тот же рисунок, что каталог принял правилом
    [206](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/206-a-form-the-gate-cannot-see-is-a-bypass.md):
    гейт находит предмет не весь и потому зеленеет законно.
    """
    named = {Path(str(q["badge"])).name for q in answers() if q.get("badge")}
    named |= {Path(str(one["badge"])).name for one in own()}
    silent = sorted(drawn() - named)
    assert not silent, (
        f"сборка рисует {silent}, и витрина о них молчит: назвать вопросом набора "
        "либо объявить своим в `own` с вопросом и причиной"
    )


def test_the_showcase_names_only_what_is_drawn() -> None:
    """И наоборот: объявленного, но не рисуемого значка быть не может.

    Показанный и не рисуемый значок — сломанная картинка на витрине (196), и от
    имени с опечаткой она неотличима.
    """
    named = {Path(str(q["badge"])).name for q in answers() if q.get("badge")}
    named |= {Path(str(one["badge"])).name for one in own()}
    phantom = sorted(named - drawn())
    assert not phantom, f"витрина называет {phantom}, а сборка их не рисует"


@pytest.mark.parametrize("one", own(), ids=lambda one: str(one["badge"]))
def test_an_own_badge_is_shown_and_explains_why_it_is_own(one: dict[str, Any]) -> None:
    """У своего значка есть вопрос, причина и место в витрине.

    Без этого `own` становится списком исключений: туда уезжает всё, что лень
    объявлять, и обратный ход снова перестаёт что-либо держать (051).
    """
    name = Path(str(one["badge"])).name
    shown = badges_shown(README.read_text(encoding="utf-8"))
    assert name in shown, f"{name}: своего значка нет в витрине — показано {sorted(shown)}"
    assert str(one.get("ask") or "").strip(), f"{name}: не назван вопрос, на который он отвечает"
    why = str(one.get("why") or "")
    assert len(why) >= REASON_AT_LEAST, f"{name}: причина «{why}» — отписка, а не причина"


@pytest.mark.parametrize("one", own(), ids=lambda one: str(one["badge"]))
def test_an_own_badge_does_not_answer_a_question_declared_absent(one: dict[str, Any]) -> None:
    """Своим не объявляется значок на вопрос, о котором сказано «предмета нет».

    Иначе `own` становится отмычкой: предмет объявлен несуществующим — и тут же
    нарисован каждым прогоном. Признак берётся механический, а не на глаз:
    у значка `<id>.svg` имя совпадает с идентификатором вопроса набора (046).
    """
    stem = Path(str(one["badge"])).stem
    absent = {str(q["id"]) for q in answers() if q.get("absent")}
    assert stem not in absent, (
        f"{stem}.svg объявлен своим, а на вопрос «{stem}» витрина отвечает «предмета нет». "
        "Одно из двух неверно: либо предмет есть и вопросу отвечает значок, либо значок "
        "рисовать незачем"
    )


def moves() -> dict[str, str]:
    """Объявление «что сдвинет значок» — по одному на значок инвентаря."""
    said = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (said.get("moves") or {}).items()}


def test_every_badge_declares_what_moves_it() -> None:
    """У каждого значка названо СОБЫТИЕ, при котором он покажет другое.

    Число, равное знаменателю по построению, — украшение на месте мерила: оно не
    говорит ни где проект стоит, ни что он сдвинулся. Заметить это можно только
    назвав событие ЗАРАНЕЕ, до того как значок повешен
    ([200](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/200-a-badge-that-cannot-move-is-not-a-measure.md)).

    ЗАМЕР 18.09.2026: значков шесть, событие не называл НИ ОДИН — при том что
    проект уже пережил этот дефект: значок правил считал `answered/total`, был
    равен знаменателю по построению и не мог сдвинуться никогда. Нашёл это
    владелец, спросив, почему число не меняется, — то есть не механизм
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

    ПРЕДМЕТ БЕРЁТСЯ ИЗ ИНВЕНТАРЯ СБОРКИ, а не из объявления: иначе значок,
    забытый в объявлении, вышел бы из-под проверки вместе со своей записью —
    проверка сравнивала бы объявление сама с собой
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    said = moves()
    assert facts.BADGES, "инвентарь значков пуст — предмет проверки не найден (075)"
    mute = [
        f"{name}: {'нет записи' if name not in said else 'событие не названо'}"
        for name in sorted(facts.BADGES)
        if len(said.get(name, "").strip()) < REASON_AT_LEAST
    ]
    assert not mute, (
        "значок не говорит, при каком событии покажет другое (200):\n  "
        + "\n  ".join(mute)
        + "\n  Пока событие не названо, неподвижный значок неотличим от подвижного."
    )


def test_no_declaration_outlives_its_badge() -> None:
    """Объявление не переживает свой значок: снятый значок уносит и запись.

    Обратная половина, и без неё раздел копит мёртвые строки: они читаются как
    обещание показать число, которого никто не рисует
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    orphan = sorted(set(moves()) - set(facts.BADGES))
    assert not orphan, (
        f"объявлено, что сдвинет значок, которого сборка не рисует: {', '.join(orphan)}"
    )
