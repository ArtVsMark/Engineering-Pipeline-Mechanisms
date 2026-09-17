"""Роль расписания объявлена данными, а его цена сходится с лимитом.

Правило 169 говорит: расписание площадки — это пожелание, а не частота. Замер
соседа: десять срабатываний вместо семидесяти двух за тридцать шесть часов.
Отсюда два требования, и оба проверяются здесь:

* у каждого расписания названа РОЛЬ — основной путь или страховка. Страховка,
  на которую полагаются как на основной путь, — это механизм, которого нет;
* цена расписаний в худший час укладывается в объявленную долю часового лимита.
  Квота общая (058): в тот же час в неё ходят прогоны изменений и очередь.

Гейт не ищет слова: он сверяет объявленное с деревом и считает арифметику —
ровно ту половину, которая из данных следует.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT

SCHEDULES = ROOT / ".rules" / "schedules.json"
WORKFLOWS = ROOT / ".github" / "workflows"
ROLES = frozenset({"main", "safety-net"})
CRON_RE = re.compile(r"^\s*-\s*cron:\s*[\"']?(?P<cron>[^\"'#]+?)[\"']?\s*$", re.M)


def declared() -> dict[str, Any]:
    """Объявление расписаний проекта."""
    said = json.loads(SCHEDULES.read_text(encoding="utf-8"))
    assert isinstance(said, dict), "объявление расписаний не словарь"
    return said


def in_tree() -> dict[str, list[str]]:
    """Расписания, реально стоящие в прогонах: файл → список cron."""
    found: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
        events = document.get(True) or document.get("on") or {}
        if not isinstance(events, dict) or "schedule" not in events:
            continue
        found[path.name] = [match["cron"].strip() for match in CRON_RE.finditer(text)]
    return found


def test_every_schedule_in_the_tree_is_declared() -> None:
    """Расписание, стоящее в прогоне, объявлено в данных.

    Незаявленное расписание — это прогон, о цене и роли которого не знает никто:
    он тратит общую квоту и держится тем, что о нём помнят.
    """
    said = declared()["runs"]
    for name in in_tree():
        assert name in said, f"{name} ходит по расписанию, а роль его не объявлена (169)"


def test_no_declaration_outlives_its_schedule() -> None:
    """Объявление без расписания в дереве — мусор, устаревающий молча (005)."""
    live = in_tree()
    for name in declared()["runs"]:
        assert name in live, f"{name} объявлен расписанием, а расписания у него нет"


@pytest.mark.parametrize("name", sorted(declared()["runs"]), ids=lambda n: str(n))
def test_the_declared_cron_matches_the_tree(name: str) -> None:
    """Объявленный cron совпадает с тем, что стоит в прогоне.

    Это та половина, которая из данных СЛЕДУЕТ, и потому проверяется, а не
    принимается на слово (044).
    """
    said = declared()["runs"][name]["cron"]
    assert said in in_tree()[name], f"{name}: объявлено «{said}», в дереве {in_tree()[name]}"


@pytest.mark.parametrize("name", sorted(declared()["runs"]), ids=lambda n: str(n))
def test_a_schedule_names_its_role_and_price(name: str) -> None:
    """У расписания названы роль, цена и причина — все три."""
    said = declared()["runs"][name]
    assert said.get("role") in ROLES, f"{name}: роль не из объявленных — {said.get('role')}"
    assert isinstance(said.get("gh_calls_per_run"), int), f"{name}: цена не названа числом"
    for field in ("how", "why"):
        assert len(str(said.get(field) or "")) > 20, f"{name}: поле «{field}» ничего не объясняет"


def test_the_hourly_price_fits_the_declared_share() -> None:
    """Цена расписаний в худший час укладывается в объявленную долю лимита.

    Считается по худшему часу, а не по суткам: лимит часовой, и три прогона,
    сошедшиеся в один час, тратят его одновременно.
    """
    said = declared()
    limit = int(said["limits"]["gh_api_per_hour"]) * float(said["share"])
    by_hour: dict[int, int] = {}
    # ЗАХОД, ИДУЩИЙ КАЖДЫЙ ЧАС, ПОПАДАЕТ В КАЖДЫЙ ЧАС. Прежде он считался
    # отдельной корзиной по строке «*», и худший час выходил заниженным: три
    # фиксированных прогона и часовой сверх них складывались как четыре разных
    # часа. Запас держал, точность — нет. Нашёл внешний взгляд на #218.
    every_hour = 0
    for one in said["runs"].values():
        price = int(one["gh_calls_per_run"])
        field = str(one["cron"]).split()[1]
        if field.isdigit():
            by_hour[int(field)] = by_hour.get(int(field), 0) + price
            continue
        # Всё, что не одно число, — списком, шагом, диапазоном — считается
        # идущим КАЖДЫЙ час: ошибаться здесь можно только в сторону строгости
        # ([050](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/050-limits-move-down-only.md)).
        every_hour += price
    worst = (max(by_hour.values()) if by_hour else 0) + every_hour
    assert worst <= limit, f"худший час стоит {worst} вызовов при доле {limit:.0f}"


def test_an_hourly_run_is_counted_in_every_hour() -> None:
    """Часовой заход складывается с фиксированными, а не стоит своей корзиной.

    Проверяется тем, что счёт обязан ОТВЕРГНУТЬ: часовой прогон ценой в долю
    лимита не может «поместиться» рядом с фиксированным просто потому, что у
    него другая строка расписания.
    """
    said = declared()
    hourly = [one for one in said["runs"].values() if not str(one["cron"]).split()[1].isdigit()]
    if not hourly:
        pytest.skip("часовых заходов нет — складывать нечего")
    fixed = [one for one in said["runs"].values() if str(one["cron"]).split()[1].isdigit()]
    assert fixed, "фиксированных заходов нет — складывать не с чем"
    both = max(int(one["gh_calls_per_run"]) for one in fixed) + sum(
        int(one["gh_calls_per_run"]) for one in hourly
    )
    assert both > max(int(one["gh_calls_per_run"]) for one in said["runs"].values()), (
        "счёт худшего часа не вырос от часового захода — значит он в него не вошёл"
    )


def test_a_safety_net_is_not_leaned_on() -> None:
    """У страховки обязан быть замер срабатываний — в поле `fires`, как у всех.

    Пока замера нет, основной путь строят так, будто страховки не существует:
    планировщик площадки говорит «когда-нибудь» (169).

    ЗАМЕР ИМЕНУЕТСЯ ОДИНАКОВО ДЛЯ ВСЕХ РОЛЕЙ. Прежде здесь спрашивалось плоское
    поле `measured`, а у расписаний замер живёт в `fires` — то есть одно понятие
    имело две формы, и вторая ждала первой записи со страховкой, чтобы разойтись.
    Нашёл внешний взгляд замечанием `f55e4a0` на #392, назвав именно это:
    «источник путаницы для будущей записи». Имя `measured` осталось за замером
    СЛОВАМИ в `.rules/rerun.json` и `.rules/leniency.json` (022).

    ПРОВЕРКА СЕГОДНЯ БЕЗ ПРЕДМЕТА, И ЭТО СКАЗАНО, А НЕ ЗЕЛЕНО. Страховочных
    расписаний в объявлении нет ни одного: все пять — `main`. Обход пустого
    списка проходил молча и читался как работающая проверка
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    nets = {
        name: one for name, one in declared()["runs"].items() if one.get("role") == "safety-net"
    }
    if not nets:
        pytest.skip("страховочных расписаний в объявлении нет — предмета у проверки нет")
    for name, one in nets.items():
        assert one.get("fires"), f"{name}: страховка без замера срабатываний в `fires`"


#: Форма даты замера: день.месяц.год. Она обязательна, потому что число без даты
#: читается как сегодняшнее и живёт дольше, чем верно
#: ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
MEASURED_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def test_the_prose_does_not_repeat_the_measured_numbers() -> None:
    """Проза расписания не повторяет числа замера: они живут в данных.

    Второе написание того же расходится с первым молча, и расходится в худшую
    сторону: проза читается первой, а поправят её последней. Этот файл уже
    чинили от того же класса, и класс вернулся — нашёл внешний взгляд находками
    `046aaba` и `6a7bbc5` на #392, ОДНА беда, названная дважды
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md),
    [022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

    Судятся ЧИСЛА ЗАМЕРА, а не всякая цифра: номера правил, задач и часы в прозе
    законны. Предмет — ровно значения из `fires`.
    """
    said = declared()["runs"]
    recorded = {name: one for name, one in said.items() if one.get("fires")}
    assert recorded, "ни у одного расписания нет замера — предмета нет (075)"
    for name, one in recorded.items():
        numbers = [str(v) for k, v in one["fires"].items() if isinstance(v, int)]
        assert numbers, f"{name}: в замере нет чисел — проверять нечего"
        said_twice = [number for number in numbers if number in str(one.get("why") or "")]
        assert not said_twice, (
            f"{name}: числа замера повторены в прозе: {said_twice} — "
            "они объявлены в `fires`, и второе написание разойдётся молча"
        )


def test_a_recorded_firing_names_its_day() -> None:
    """Замер срабатываний планировщика назван с датой и сходится сам с собой.

    ЗАЧЕМ ЗАПИСЫВАТЬ ЕГО ВООБЩЕ. Реестр пропущенных заходов называет число
    каждый день, и у `hail` оно велико. Дефектом это не является, планировщик
    площадки обещает «когда-нибудь» (104). Но сигнал, у которого нет ответа,
    читается как новая работа, и окно выводит ответ заново каждую смену.
    Записанный замер — и есть ответ. Сами числа здесь НЕ повторяются: они живут
    в данных, и второе их написание разошлось бы с первым молча (022).

    ДЕНЬ ОБЯЗАТЕЛЕН. Без него доля через неделю прочтётся как сегодняшнее
    состояние, и следующее решение встанет на устаревшем числе (005).

    ПОЛЕ ЗОВЁТСЯ `day`, А НЕ `measured`. В `.rules/rerun.json` и
    `.rules/leniency.json` `measured` означает замер СЛОВАМИ — «день · прогон ·
    исход», — и одно имя на две формы расходится молча. Нашёл внешний взгляд
    замечанием `f55e4a0` на #392.
    """
    said = declared()["runs"]
    recorded = {name: one["fires"] for name, one in said.items() if one.get("fires")}
    assert recorded, "ни у одного расписания нет записанного замера — предмета нет (075)"
    for name, fires in recorded.items():
        assert MEASURED_RE.match(str(fires.get("day") or "")), (
            f"{name}: у замера нет дня в виде ДД.ММ.ГГГГ — число без дня устаревает молча"
        )
        expected, happened = fires.get("expected"), fires.get("happened")
        assert isinstance(expected, int) and isinstance(happened, int), (
            f"{name}: замер назван не числами"
        )
        assert 0 <= happened <= expected, (
            f"{name}: случилось {happened} при ожидавшихся {expected} — "
            "замер не сходится сам с собой"
        )
