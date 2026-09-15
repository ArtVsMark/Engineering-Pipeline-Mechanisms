#!/usr/bin/env python3
"""Красная общая ветка: перезапустить минимум, записать остальное, не потерять.

Контур 3 договора (`docs/behaviour.md`) описан давно, а механизма под ним не
было ни одного: красноту видел человек. Здесь появляется первый — счёт красных
на голове общей ветки, перезапуск ОДНОГО и запись того, что осталось.

ПЕРЕЗАПУСК — РОВНО ОДИН И ТОЛЬКО ОН
([124](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/124-rerun-the-minimum-and-record-the-flake.md)).
Упал один джоб — перезапускается он один, и один раз. Зелёное со второго раза
это **находка о мигании, а не починка**: нестабильный тест, о котором не
записали, исчезает бесследно и возвращается. Упало несколько — перезапуск не
делается вовсе: несколько сразу похоже на дефект, а не на мигание, и второй
заход только оттянул бы разбор.

ЧТО СЧИТАТЬ ПОПЫТКОЙ, ВЫВОДИТСЯ ИЗ ПЛОЩАДКИ, А НЕ ХРАНИТСЯ. У прогона есть
номер попытки: `run_attempt > 1` значит, что перезапуск уже был. Свой счётчик
разошёлся бы с площадкой молча — и в сторону бесконечных перезапусков
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

КРАСНОЕ РАЗВОДИТСЯ ПО КЛАССУ ПРОВЕРКИ, И РЕШАЕТ ЭТО НЕ МЕХАНИЗМ, А ДАННЫЕ.
Класс объявлен проектом в `.pipeline.yml`, и он же говорит, чем красное
является:

* **обязательная** упала — очередь заморожена, слить не может никто. Это
  источник 0 контура 1: стоит работа всей семьи;
* **совещательная** упала — не заморожено ничто, но работа, помеченная
  закрытой, частью не работает. Это долг по УЖЕ сделанному, то есть источник 3,
  и он идёт перед правилами и планом. Пример, ради которого это и разведено:
  предрелизная ячейка матрицы. Её починка может оказаться переездом проекта на
  другую версию языка — работа немалая, и терять её в выводе прогона нельзя.

Объявить совещательное красное источником 0 было бы удобнее и неверно: простоя
нет, очередь идёт, и приоритет, который звучит всегда, перестаёт что-либо
значить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

ЗАПИСЬ — ЗЕРКАЛО, А НЕ ЖУРНАЛ. Разделы «держит слияние» и «не держит»
пересобираются из живых артефактов каждым заходом: позеленело — запись ушла
сама, упало снова — вернулась. Снятия рукой не требуется, и устареть запись не
может. Исключение одно и названо: мигание — СОБЫТИЕ, а не состояние; после
позеленения его в артефактах уже нет, поэтому мигания копятся списком, и
снимает их человек.

Исходы (правило 039): ``0`` общая ветка зелена · ``2`` шаг не отработал ·
``3`` есть краснота, и она записана.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import automerge
import ci_complete
import findings
import ghrest
import paths
import pipeline_checks as policy
import report

MARKER: Final = findings.marker("main-red")
TITLE: Final = "Общая ветка: краснота"

#: Номер прогона внутри адреса записи проверки: `…/actions/runs/<id>/job/<id>`.
RUN_ID_RE: Final = re.compile(r"/actions/runs/(\d+)")
#: Мигание в теле задачи: копится списком, потому что событие в артефактах не
#: остаётся. Читается строкой, чтобы заход не заводил его заново.
#: ПЕРЕВОД СТРОКИ В ИМЯ НЕ ВХОДИТ, И ЭТО НЕ ПРИДИРКА. Класс с отрицанием
#: (`[^·]`) матчит и перевод строки: имя первого мигания заглатывало ВСЁ тело до
#: первой настоящей записи — вместе с заголовками разделов, — а сборка печатала
#: это обратно. Реестр рос с каждым заходом и врал читателю двумя списками одного
#: раздела. Замер 14.09.2026: 19 «миганий», первое из них полтора килобайта, шесть
#: разделов вместо трёх, тело выросло за один заход с 3052 до 3144 знаков
#: ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
FLAKE_RE: Final = re.compile(
    r"^- (?P<name>[^·\n]+) · (?P<day>\S+) · прогон (?P<run>\d+)(?: · (?P<where>\S+))?\s*$",
    re.M,
)

#: Где мигнуло, если не на общей ветке. Умолчание молчаливое намеренно: записи
#: общей ветки были заведены раньше и переписывать их задним числом незачем.
SHARED: Final = "общая ветка"

EXIT_GREEN: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RED: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «ветка зелена»."""


@dataclass(frozen=True, slots=True)
class Flake:
    """Мигание: имя проверки, день, прогон и где это увидели."""

    name: str
    day: str
    run: int
    where: str = SHARED

    def said(self) -> str:
        """Строка записи. Общая ветка не подписывается: она умолчание."""
        tail = "" if self.where == SHARED else f" · {self.where}"
        return f"- {self.name} · {self.day} · прогон {self.run}{tail}"


#: Исходы, которые считаются НАСТОЯЩИМ красным. Отменённая и пропущенная сюда не
#: входят: пройденной ни одна не считается, но и отказом не является.
REAL_RED: Final = frozenset({"failure", "timed_out", "action_required"})

#: Прогон, которым доказывается зелень общей ветки. Имя файла, а не номер
#: площадки: номер в дереве не виден и сверить его нечем, а файл виден оба раза
#: ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
PROOF_RUN: Final = "ci.yml"

#: ПРЕДЕЛ ПОПЫТОК ДОКАЗАТЬ ЗЕЛЕНЬ. «Чиним, пока не позеленеет» без предела не
#: сходится, если причина не в коде вовсе — отказал внешний сервис, кончились
#: исполнители. После предела следующий шаг не починка, а владелец
#: ([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md),
#: [100](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/100-two-deadlines-start-and-work.md)).
#:
#: ПОЧЕМУ ТРИ. Два — это одна починка: красное бывает и от осечки площадки, и
#: отдавать владельцу после единственной попытки значило бы будить его на
#: мигании. Пять — три починки подряд по одной причине; если две не помогли,
#: третья тем же способом не поможет тоже. Число объявлено, а не выведено из
#: замера, и это сказано: замер 14.09.2026 по 273 прогонам `ci` на общей ветке
#: нашёл пять красных полос, и каждая длиной в ОДИН заход — полосы длиннее в
#: проекте не случалось ни разу. То есть предел сегодня не срабатывает, и цена
#: его объявления — ноль; условие пересмотра — в записи решения 021.
TRIES_LIMIT: Final = 3


@dataclass(frozen=True, slots=True)
class Proof:
    """Счёт неудачных доказательств зелени: число и полнота замера."""

    tries: int
    whole: bool

    @property
    def spent(self) -> bool:
        """Исчерпан ли предел попыток — то есть дальше владелец, а не починка."""
        return self.tries >= TRIES_LIMIT

    def said(self) -> str:
        """Число словами. Неполный замер называет себя НЕ МЕНЬШЕ, а не точным."""
        about = "не меньше " if not self.whole else ""
        return f"{about}{self.tries}"


def proofs(repo: str, token: str) -> Proof:
    """Сколько заходов подряд НЕ доказали зелень общей ветки.

    СЧЁТЧИК ВЫВОДИТСЯ ИЗ ПЛОЩАДКИ, А НЕ ХРАНИТСЯ — по той же причине, что и
    номер попытки прогона: свой счётчик разошёлся бы с ней молча, и в сторону
    бесконечных попыток (049). Попытка здесь — ЗАХОД, доказывающий зелень:
    слияние починки, ручная кнопка, заход по расписанию. Именно так это и
    объявлено в контуре 3: «Проверка» считает прогоны от расписания и от руки,
    потому что доказательство зелени не имеет права идти через замороженное
    слияние ([126](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/126-a-freeze-needs-a-thaw-path.md)).

    ОТМЕНЁННАЯ ПОПЫТКОЙ НЕ СЧИТАЕТСЯ И ПОЛОСУ НЕ РВЁТ: у неё нет вердикта
    вовсе, а считать отсутствие вердикта доказательством зелени — то же
    молчаливое умолчание, от которого страхует 045. Такой заход пропускается, и
    счёт идёт дальше по следующему.

    ПОЛНОТА ЗАМЕРА НАЗЫВАЕТСЯ. Читается одна страница — сто заходов; если
    зелёного в ней нет вовсе, число это НЕ МЕНЬШЕ прочитанного, и выдавать его
    за точное значило бы врать в сторону, удобную механизму (045).
    """
    payload = (
        ghrest.request(
            "GET",
            f"repos/{repo}/actions/workflows/{PROOF_RUN}/runs"
            f"?branch={paths.TRUNK}&status=completed&per_page=100",
            token,
        )
        or {}
    )
    tries = 0
    for run in payload.get("workflow_runs") or []:
        end = str(run.get("conclusion") or "")
        if end == "success":
            return Proof(tries, True)
        if end in REAL_RED:
            tries += 1
    return Proof(tries, False)


def flaky_names(runs: list[dict[str, Any]]) -> dict[str, int]:
    """Имена, давшие на ОДНОЙ голове настоящее красное и затем зелёное.

    ЭТО И ЕСТЬ МИГАНИЕ, И ВИДНО ОНО БЕЗ ПЕРЕЗАПУСКА. Голова та же — значит
    дерево то же, и зелёное после красного получено не правкой. Прежний замер
    искал мигания среди перезапусков и не мог их найти: перезапускать было
    некому, и отсутствие перезапусков доказывало само себя
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    Разбор — `docs/decisions/014-a-flake-must-be-visible-before-it-is-rerun.md`.

    Порядок читается по времени начала записи, а не по порядку ответа площадки:
    зелёное ДО красного — это обычная краснота, а не мигание.
    """
    fell: dict[str, tuple[str, int]] = {}
    rose: dict[str, str] = {}
    for run in runs:
        if run.get("status") != "completed":
            continue
        name = str(run.get("name") or "")
        started = str(run.get("started_at") or "")
        outcome = run.get("conclusion")
        if outcome in REAL_RED:
            if name not in fell or started < fell[name][0]:
                fell[name] = (started, run_id_of(run))
        elif outcome == "success":
            rose[name] = max(rose.get(name, started), started)
    # НОМЕР ПАДАВШЕГО ПРОГОНА — ЧАСТЬ НАХОДКИ, А НЕ УКРАШЕНИЕ. По нему запись
    # отличается от следующей такой же: одно имя мигает не единожды, и сводить
    # эти случаи в один значило бы потерять частоту — то самое, ради чего
    # мигания и записывают. Нашёл внешний взгляд на #222.
    return {
        name: where[1] for name, where in fell.items() if rose.get(name, "") > where[0] and where[1]
    }


def red_of(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Записи, которые на общей ветке означают красное.

    «Идёт» красным не считается: незавершённая проверка это не отказ, а
    отсутствие вердикта, и объявлять по ней заморозку значило бы морозить
    ветку на каждом прогоне. Отменённая — тоже: она пройденной не считается,
    но и отказом не является (её разбирает сводный гейт на изменении).
    """
    return [
        run
        for run in runs
        if not ci_complete.pending(run)
        and run.get("conclusion") not in (None, "success", "skipped", "cancelled")
    ]


def split(runs: list[dict[str, Any]], required: list[str]) -> tuple[list[str], list[str]]:
    """Делит красные имена на держащие слияние и не держащие."""
    names = sorted({str(run.get("name", "")) for run in runs})
    holds = [name for name in names if name in required]
    rest = [name for name in names if name not in required]
    return holds, rest


def run_id_of(run: dict[str, Any]) -> int:
    """Номер прогона, которому принадлежит запись проверки.

    Берётся из адреса записи: у площадки нет поля с номером прогона в ответе
    check-runs, а адрес его несёт. Разбор строгий — не разобралось, значит
    запись поставило не то приложение, и перезапускать нечего.
    """
    found = RUN_ID_RE.search(str(run.get("details_url") or ""))
    return int(found.group(1)) if found else 0


def attempt(repo: str, run: int, token: str) -> int:
    """Какая это попытка прогона: больше единицы — перезапуск уже был."""
    payload = ghrest.request("GET", f"repos/{repo}/actions/runs/{run}", token) or {}
    return int(payload.get("run_attempt") or 1)


def rerun_failed(repo: str, run: int, token: str) -> None:
    """Перезапускает ТОЛЬКО упавшие джобы прогона — минимум, а не всё."""
    ghrest.request("POST", f"repos/{repo}/actions/runs/{run}/rerun-failed-jobs", token, {})


#: Почему перезапуск не делается. Причина называется словами: «не будем»
#: без причины и «нечем» снаружи одинаковы (154).
NOT_ALONE: Final = "упал не один — это похоже на дефект, а не на мигание"
ALREADY: Final = "уже перезапускался — значит это дефект, а не мигание (124)"
NO_ADDRESS: Final = "адрес записи не разобрался — перезапускать нечем"
#: Красных ОБЯЗАТЕЛЬНЫХ нет, а совещательные есть. Перезапуска не будет, но
#: причина здесь другая: не «упал не один», а «упало то, что ничего не держит».
#: Разница не косметическая — прежняя редакция говорила «упал не один» про
#: единственную красную совещательную, то есть называла состояние неверно, и
#: читатель шёл искать второй упавший джоб, которого нет (154).
ADVISORY_ONLY: Final = (
    "красных обязательных нет — упавшее совещательное уходит в долг, а не в перезапуск (084)"
)


def one_fall(holds: list[str], rest: list[str], fed: dict[str, set[str]]) -> bool:
    """Одно ли это падение, отражённое несколькими именами.

    МАТРИЦА И ЕЁ АГРЕГАТ КРАСНЕЮТ ВМЕСТЕ ВСЕГДА. Агрегат ждёт матрицу через
    `needs` и краснеет ровно потому, что красна ячейка: два имени, одно
    падение. Пока это считалось двумя, перезапуск мигнувшей общей ветки не
    случался НИКОГДА — условие «упал ровно один» не выполнялось по построению.

    Замер 10.09.2026: `main` встала красной на `test` и `test-matrix (3.12)`,
    очередь заморозилась, и снять заморозку было нечем — новых слияний в
    замороженной очереди не бывает. Тупик разомкнулся руками.

    Связь читается из `needs` прогонов, то есть из данных, а не из прозы: имя
    матричной ячейки несёт версию (`test-matrix (3.12)`), поэтому сверяется
    начало имени до скобки.
    """
    if len(holds) != 1:
        return False
    feeding = fed.get(holds[0], set())
    return all(name.split(" (")[0] in feeding for name in rest)


def target_run(
    holds: list[str], rest: list[str], red: list[dict[str, Any]], fed: dict[str, set[str]]
) -> int:
    """Номер прогона, который перезапускают; ``0`` — перезапускать нечего.

    Решение о перезапуске и ВЫБОР ЕГО ПРЕДМЕТА — один вопрос, и спрашиваться он
    обязан одинаково. Пока выбор жил своим условием внутри захода, он
    расходился с решением: `one_fall` уже говорил «одно падение», а предмет
    по-прежнему не находился, и отказ приходил под другим именем.

    Перезапускается запись ОБЯЗАТЕЛЬНОГО имени: она и держит слияние. Соседние
    имена того же падения (матричные ячейки) поедут вместе с ней — их вердикт
    в неё и доезжает.
    """
    if not one_fall(holds, rest, fed):
        return 0
    for item in red:
        if str(item.get("name")) == holds[0]:
            return run_id_of(item)
    return 0


def rerun_reason(
    holds: list[str],
    rest: list[str],
    run: int,
    tries: int,
    feeds: dict[str, set[str]] | None = None,
) -> str:
    """Почему перезапуска НЕ будет; пустая строка — будет.

    Решение вынесено из захода отдельно, потому что оно и есть предмет правила
    124, а проверять его внутри `main()` пришлось бы подделкой всей площадки —
    то есть не проверять вовсе
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).

    Причины разведены поимённо. «Попытка уже была» и «адрес записи не
    разобрался» дают одинаковое бездействие, а значат разное: первое —
    состояние работы (дефект, идём чинить), второе — поломка чтения (площадка
    ответила не тем). Одно сообщение на оба отправило бы разбирать дефект,
    которого нет.
    """
    if not holds:
        return ADVISORY_ONLY
    if not one_fall(holds, rest, feeds or {}):
        return NOT_ALONE
    if not run:
        return NO_ADDRESS
    return ALREADY if tries > 1 else ""


def parse_flakes(body: str | None) -> list[Flake]:
    """Мигания, уже записанные в задаче."""
    return [
        Flake(found["name"].strip(), found["day"], int(found["run"]), found["where"] or SHARED)
        for found in FLAKE_RE.finditer(body or "")
    ]


def flakes_after(
    known: list[Flake], name: str, run: int, day: str, where: str = SHARED
) -> list[Flake]:
    """Добавляет мигание, если этого прогона в списке ещё нет.

    По прогону, а не по имени: одна и та же проверка мигает не единожды, и
    сводить эти случаи в один значило бы потерять частоту — то самое, ради чего
    мигания и записывают.
    """
    if any(item.run == run and item.name == name for item in known):
        return known
    return [*known, Flake(name, day, run, where)]


def flakes_on_changes(repo: str, token: str, known: list[Flake], day: str) -> list[Flake]:
    """Дописывает мигания, увиденные на головах ЖИВЫХ изменений.

    ПОЧЕМУ ЗДЕСЬ, А НЕ ОТДЕЛЬНЫМ МЕХАНИЗМОМ. Реестр мигания один — #99, — и он
    уже ведётся этим шагом. Второй механизм, пишущий в тот же список, разошёлся
    бы с первым молча
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)),
    а второй список того же — ровно то, ради чего реестр и заведён один.

    ПЕРЕЗАПУСКА ЗДЕСЬ НЕТ НАМЕРЕННО. Правило 124 требует двух вещей, и записать
    можно то, чего ещё не перезапускали; обратное — нет. Разрешённый список
    автоперезапуска остаётся пустым, пока эти записи не назовут первое имя.
    """
    found = list(known)
    try:
        # СЛИТЫЕ ОБХОДЯТСЯ НАРАВНЕ С ОТКРЫТЫМИ, И БЕЗ ЭТОГО СПИСОК БЫЛ ПУСТ ПО
        # ПОСТРОЕНИЮ. Мигание — свойство ГОЛОВЫ, и слияние его не отменяет:
        # записи проверок остаются лежать там же. А изменение, слившееся за
        # минуты, из списка открытых исчезает раньше, чем шаг успевает
        # заглянуть, — то есть чем БЫСТРЕЕ работает очередь, тем меньше
        # миганий видит детектор.
        #
        # Замер 13.09.2026: реестр #99 говорил «повторных зелёных не было», а
        # на головах слитых #259 и #262 лежало по настоящему миганию
        # `ci-complete` — красное и затем зелёное без правки дерева. Молчание
        # реестра было не наблюдением, а следствием того, куда он смотрит
        # ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
        #
        # Цена молчания здесь не «одна потерянная запись»: пока записей нет,
        # не наступает и условие пересмотра решения `014`, то есть разрешённый
        # список автоперезапуска остаётся пустым НАВСЕГДА.
        changes = list(ghrest.paginate(f"repos/{repo}/pulls?state=open", token))
        changes += ghrest.merged_changes(repo, token)
    except ghrest.TransportError as exc:
        # Отказ здесь не роняет заход: краснота общей ветки — главный предмет
        # шага, и терять её из-за соседнего счёта нельзя (084).
        print(f"мигания изменений не сосчитаны: {report.cut(str(exc))}")
        return found
    for change in changes:
        head = str((change.get("head") or {}).get("sha") or "")
        number = int(change.get("number") or 0)
        if not head or not number:
            continue
        try:
            # СПИСОК ИДЁТ СТРАНИЦАМИ, как и у общей ветки. Умолчание площадки
            # обрезает хвост молча, а хвост — это и есть вторая запись имени,
            # без которой мигание неотличимо от обычной красноты (#222).
            runs = list(
                ghrest.paginate(f"repos/{repo}/commits/{head}/check-runs", token, key="check_runs")
            )
        except ghrest.TransportError as exc:
            print(f"  #{number}: записи проверок не прочитаны: {report.cut(str(exc))}")
            continue
        for name, run in flaky_names(runs).items():
            before = len(found)
            found = flakes_after(found, name, run, day, where=f"#{number}")
            if len(found) > before:
                print(f"  #{number}: мигание «{name}» на прогоне {run} — зелёное после красного")
    return found


#: Метка заморозки. Имя читает очередь (`scripts/automerge.py`), объявлено оно в
#: составе меток дерева, а ставит и снимает его ЭТОТ шаг: у метки один владелец —
#: механизм, и этим она отличается от `hold`, которую ставит человек (022).
LABEL_PAUSED: Final = automerge.LABEL_PAUSED
#: Метка починки: её несущее изменение заморозка не останавливает — оно и есть
#: выход из неё.
LABEL_FIX_MAIN: Final = automerge.LABEL_FIX_MAIN


def stamp(repo: str, number: int, token: str, *, on: bool) -> None:
    """Ставит или снимает метку заморозки на одном изменении."""
    if on:
        ghrest.request(
            "POST", f"repos/{repo}/issues/{number}/labels", token, {"labels": [LABEL_PAUSED]}
        )
        return
    # Имя метки несёт косую черту, и в адресе она обязана быть закодирована:
    # иначе площадка ищет метку «main-red» внутри пути «paused» и отвечает
    # «не найдено» — снятие выглядело бы сделанным (045).
    ghrest.request(
        "DELETE", f"repos/{repo}/issues/{number}/labels/{ghrest.quote(LABEL_PAUSED)}", token
    )


def pause(repo: str, token: str, *, frozen: bool, apply: bool) -> tuple[list[int], list[int]]:
    """Отмечает заморозку на живых изменениях: ставит на все, кроме починки.

    ПОЧЕМУ МЕТКА, А НЕ ТОЛЬКО СНЯТИЕ ВЗВЕДЕНИЯ. Очередь и так снимает согласие
    при красной общей ветке, но снятие живёт в выводе её захода: человек на
    списке изменений видит зелёные проверки и не видит причины, почему ничего не
    сливается. Метка — состояние НА изменении, и она не отменяется следующим
    решением очереди
    ([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)).

    ПОЧИНКА НЕ ОСТАНАВЛИВАЕТСЯ: изменение с меткой `fix-main` — единственный
    выход из заморозки, и остановить его значило бы запереть выход
    ([126](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/126-a-freeze-needs-a-thaw-path.md)).

    СНЯТИЕ — ТОГО ЖЕ ШАГА, а не человека: у метки один владелец. Позеленела
    общая ветка — метка уходит сама, и «забытая метка» означает не забывчивость
    человека, а незашедший механизм; об этом говорит счёт пропущенных заходов по
    расписанию, а не вторая метка.

    Возвращает два списка: помеченные и освобождённые.
    """
    try:
        changes = list(ghrest.paginate(f"repos/{repo}/pulls?state=open", token))
    except ghrest.TransportError as exc:
        # Отказ здесь не роняет заход: краснота — главный предмет шага, и терять
        # её из-за соседнего действия нельзя (084).
        print(f"метки заморозки не расставлены: {report.cut(str(exc))}")
        return [], []

    marked: list[int] = []
    freed: list[int] = []
    for change in changes:
        number = int(change.get("number") or 0)
        if not number:
            continue
        marks = {str((one or {}).get("name") or "") for one in change.get("labels") or []}
        paused_now = LABEL_PAUSED in marks
        want = frozen and LABEL_FIX_MAIN not in marks
        if want == paused_now:
            continue
        try:
            if apply:
                stamp(repo, number, token, on=want)
        except ghrest.TransportError as exc:
            print(f"#{number}: метка заморозки не {'поставлена' if want else 'снята'}: {exc}")
            continue
        (marked if want else freed).append(number)
    if marked:
        print(f"заморозка отмечена{'' if apply else ' была бы'} на: {marked}")
    if freed:
        print(f"метка заморозки снята{'' if apply else ' была бы'} с: {freed}")
    return marked, freed


def queue_now(repo: str, token: str) -> tuple[int, int]:
    """Сколько изменений ждёт очереди и сколько из них помечены починкой.

    ЧИТАЕТСЯ У ПЛОЩАДКИ, А НЕ СЧИТАЕТСЯ ЗАНОВО. Предмет — живые изменения и их
    метки; вести это вторым списком значило бы разойтись с площадкой на первом
    же закрытом изменении (049).

    СПИСОК БЕРЁТСЯ У ОЧЕРЕДИ, А НЕ СОБИРАЕТСЯ ЗДЕСЬ ВТОРОЙ РАЗ. Прежде шаг
    запрашивал открытые изменения сам, одной страницей на пятьдесят: при
    большем числе счёт «в очереди» занижался молча, и хуже того — занижался
    счёт помеченных `fix-main`, то есть механизм мог сказать «разблокировать
    некому», когда разблокирующее изменение уже стояло. Тот же список читает
    `automerge.open_changes`, страницами и с теми же метками; второе прочтение
    одного источника расходится с первым молча (022, 090). Нашёл внешний
    взгляд на #168 — трижды, и все три раза об одном.
    """
    try:
        changes = automerge.open_changes(repo, token)
    except ghrest.TransportError:
        return (0, 0)
    queued = [
        change
        for change in changes
        if automerge.LABEL_AUTOMERGE in change.marks and not change.draft
    ]
    fixing = sum(1 for change in queued if automerge.LABEL_FIX_MAIN in change.marks)
    return len(queued), fixing


def said_queue(waiting: int, fixing: int) -> list[str]:
    """Что заморозка значит для очереди ПРЯМО СЕЙЧАС — словами и числом.

    ЗАЧЕМ. Заморозка объявлена, метка названа — и всё равно дважды за смену
    починка стояла в очереди без метки, потому что «это чинит общую ветку»
    решает человек, а не механизм. Очередь при этом молчала: она пишет «нет
    изменения с меткой» в лог своего прогона, куда никто не смотрит. Адресат у
    такого сообщения есть — эта самая задача (142).

    Механизм НЕ ставит метку сам: из дерева не следует, чинит ли изменение
    красноту, и решать это за человека значило бы пропускать в замороженную
    очередь что попало (154). Но сказать, что очередь стоит и никто её не
    разблокирует, он обязан.
    """
    if fixing:
        return [
            f"В очереди {waiting}, из них с меткой `fix-main`: **{fixing}** — они и пойдут.",
            "",
        ]
    if waiting:
        return [
            f"**В очереди {waiting}, и ни одно не помечено `fix-main`.** Очередь не",
            "двинется, пока метку не поставят: механизм её не ставит сам — из дерева",
            "не следует, чинит ли изменение красноту (154).",
            "",
        ]
    return ["Очередь пуста: чинить некому и нечего двигать.", ""]


def said_tries(proof: Proof) -> list[str]:
    """Счётчик попыток словами — и смена адресата, когда предел исчерпан.

    ДНО У ЦИКЛА НАЗЫВАЕТСЯ ЗАРАНЕЕ, А НЕ ПОСЛЕ. Пока предела нет, «чиним, пока
    не позеленеет» звучит как план и при причине вне кода не сходится никогда
    (109). Механизм при этом никого не останавливает и останавливать не вправе:
    он называет число и того, кому дальше решать, — решает человек (154).

    АДРЕСАТ МЕНЯЕТСЯ ТЕМИ ЖЕ СЛОВАМИ, ЧТО У ОКЛИКА. Два понимания «дальше
    владелец» разошлись бы молча, а читатель у обеих записей один (090).
    """
    said = [f"Заходов подряд, не доказавших зелень: **{proof.said()}** из {TRIES_LIMIT}.", ""]
    if not proof.whole:
        said = [
            f"Заходов подряд, не доказавших зелень: **{proof.said()}** из {TRIES_LIMIT} —"
            " зелёного захода в прочитанном окне нет вовсе, поэтому число это не",
            "меньшее, а не точное (045).",
            "",
        ]
    if not proof.spent:
        return said
    return [
        *said,
        "**Адресат — владелец.** Причина смены адресата: предел попыток доказать",
        f"зелень исчерпан ({proof.said()} из {TRIES_LIMIT}). Следующий шаг не починка:",
        "столько заходов подряд без зелени значит, что причина может быть вне кода",
        "вовсе — отказала площадка, кончились исполнители, — и выбор между",
        "«чиним дальше» и «ждём» делает человек, а не механизм (109, 100).",
        "",
    ]


def render_body(
    holds: list[str],
    rest: list[str],
    flakes: list[Flake],
    sha: str,
    queue: tuple[int, int] | None = None,
    tries: Proof | None = None,
) -> str:
    """Собирает тело задачи: два зеркала и один журнал."""
    lines = [
        MARKER,
        "",
        "> **Читатель:** окно, берущее работу, и владелец. Здесь то, что красно",
        "> на общей ветке прямо сейчас, и то, что мигало.",
        "",
        "Разделы ниже — **зеркало живых артефактов**: они пересобираются каждым",
        "заходом. Позеленело — запись уходит сама, упало снова — возвращается.",
        "Снимать их рукой не нужно и не следует.",
        "",
        f"Голова общей ветки: `{sha[:7] or '—'}`.",
        "",
        "## Держит слияние — источник 0",
        "",
    ]
    if holds:
        lines += [
            "Очередь заморожена: слить не может никто, кроме починки. Это первый",
            "источник работы контура 1 — стоит работа всей семьи.",
            "",
            *[f"- **{name}**" for name in holds],
            "",
            "Починка подаётся изменением с меткой `fix-main`: очередь пропускает",
            "только его, и приёмка у него строже обычной (193).",
            "",
            *(said_queue(*queue) if queue else []),
            *(said_tries(tries) if tries else []),
        ]
    else:
        lines += ["Пусто — обязательные проверки на голове зелены.", ""]

    lines += ["## Не держит слияние, но не потеряно — источник 3", ""]
    if rest:
        lines += [
            "Совещательная проверка слияния не держит, и очередь идёт. Но работа,",
            "помеченная закрытой, частью не работает — это долг по УЖЕ сделанному,",
            "и он идёт перед правилами и планом.",
            "",
            *[f"- **{name}**" for name in rest],
            "",
            "Починка такого бывает крупной — вплоть до переезда на другую версию",
            "языка. Тогда из записи заводится задача, и запись уходит вместе с",
            "починкой, а не с забвением.",
            "",
        ]
    else:
        lines += ["Пусто — совещательные проверки на голове зелены.", ""]

    lines += [
        "## Мигания",
        "",
        "Зелёное со второго раза — **находка, а не починка** (124). В артефактах",
        "после позеленения этого не остаётся, поэтому список копится и его",
        "снимает человек: механизм не знает, разобрано мигание или надоело.",
        "",
    ]
    if flakes:
        lines += [item.said() for item in flakes]
    else:
        lines.append("Пусто — повторных зелёных не было.")
    return "\n".join(lines) + "\n"


def save(repo: str, token: str, body: str, apply: bool) -> None:
    """Записывает задачу: обновляет по месту или заводит одну."""
    number, _ = findings.live_issue(repo, token, MARKER)
    if not apply:
        print("записал бы в " + (f"#{number}" if number else "новую задачу"))
        return
    if number is None:
        created = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"задача заведена: #{(created or {}).get('number')}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"задача обновлена: #{number}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: считает красноту головы, перезапускает минимум и пишет."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default="", help="голова общей ветки; по умолчанию — её вершина")
    parser.add_argument("--branch", default=paths.TRUNK, help="общая ветка")
    parser.add_argument("--apply", action="store_true", help="записать и перезапустить")
    args = parser.parse_args(argv)

    holds: list[str] = []
    rest: list[str] = []
    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")

        sha = args.sha or str(
            (ghrest.request("GET", f"repos/{args.repo}/commits/{args.branch}", token) or {}).get(
                "sha", ""
            )
        )
        if not sha:
            raise NotRun(f"голова ветки «{args.branch}» не прочитана — считать нечего")

        runs = ci_complete.worst_per_name(
            ci_complete.on_the_shared_branch(
                list(
                    ghrest.paginate(
                        f"repos/{args.repo}/commits/{sha}/check-runs?filter=latest",
                        token,
                        key="check_runs",
                    )
                )
            )
        )
        if not runs:
            raise NotRun(f"на голове {sha[:7]} нет ни одной записи проверки — считать нечего (075)")

        required = policy.names_of(policy.load(), policy.REQUIRED)
        red = red_of(runs)
        holds, rest = split(red, required)

        _, body = findings.live_issue(args.repo, token, MARKER)
        flakes = parse_flakes(body)
        day = datetime.now(UTC).strftime("%d.%m.%Y")

        # Мигание видно ТАМ ЖЕ, где всё остальное: зелёная запись прогона,
        # который шёл не с первой попытки. Отдельного состояния для этого не
        # нужно — площадка помнит номер попытки за нас.
        for run in runs:
            if run.get("conclusion") != "success":
                continue
            number = run_id_of(run)
            if number and attempt(args.repo, number, token) > 1:
                flakes = flakes_after(flakes, str(run.get("name", "")), number, day)

        if holds or rest:
            # Упал ровно один — перезапускается он один и один раз. Номер
            # попытки спрашивается у площадки: свой счётчик разошёлся бы с ней
            # молча, и в сторону бесконечных перезапусков.
            #
            # УСЛОВИЕ ЗДЕСЬ ТО ЖЕ, ЧТО И В РЕШЕНИИ. Пока оно было своим
            # («ровно один и никого рядом»), сценарий «агрегат плюс его
            # матрица» до перезапуска не доходил: номер прогона не вычислялся,
            # и отказ приходил уже по другой причине — «адрес записи не
            # разобрался». Починка меняла причину отказа, а не исход. Нашёл
            # внешний взгляд на #160.
            fed = policy.feeds()
            number = target_run(holds, rest, red, fed)
            tries = attempt(args.repo, number, token) if number else 1
            why = rerun_reason(holds, rest, number, tries, fed)
            if why:
                print(f"перезапуска не будет: {why}")
            else:
                if args.apply:
                    rerun_failed(args.repo, number, token)
                print(
                    f"упал ровно один — «{holds[0]}»: "
                    + ("перезапущен" if args.apply else "перезапустил бы")
                    + f" прогон {number} (124)"
                )

        print(f"голова {sha[:7]}: держат слияние {len(holds)}, не держат {len(rest)}")
        for name in holds:
            print(f"  [источник 0] {name}")
        for name in rest:
            print(f"  [источник 3] {name}")
        # МИГАНИЕ НА ГОЛОВЕ ИЗМЕНЕНИЯ ВИДНО ОТСЮДА ЖЕ. Реестр мигания один
        # (#99), и второй список того же разошёлся бы с первым молча (022).
        # Перезапуск на изменении при этом НЕ делается: пока у разрешённого
        # списка нет ни одного измеренного имени, автоперезапуск был бы
        # заполнен догадкой
        # (`docs/decisions/014-a-flake-must-be-visible-before-it-is-rerun.md`).
        flakes = flakes_on_changes(args.repo, token, flakes, day)

        # Очередь спрашивается ТОЛЬКО при заморозке: без неё этот счёт ничего
        # не решает, а лишний обход площадки стоит вызовов из общей квоты (058).
        queue = queue_now(args.repo, token) if holds else None
        # МЕТКА ЗАМОРОЗКИ РАССТАВЛЯЕТСЯ В ОБЕ СТОРОНЫ И КАЖДЫМ ЗАХОДОМ: она
        # зеркало состояния общей ветки, а не журнал события. Позеленело —
        # снимается сама, покраснело снова — вернулась (049).
        pause(args.repo, token, frozen=bool(holds), apply=args.apply)
        # СЧЁТЧИК ПОПЫТОК СПРАШИВАЕТСЯ ТОЛЬКО ПРИ ЗАМОРОЗКЕ. Предел живёт в
        # контуре 3 у состояния «Проверка», а оно наступает от красной
        # ОБЯЗАТЕЛЬНОЙ: совещательное красное очередь не морозит, чинить его
        # никто не обязан прямо сейчас, и будить владельца по его счёту значило
        # бы сделать приоритет, который звучит всегда (051).
        proof = proofs(args.repo, token) if holds else None
        if proof:
            print(f"заходов подряд без зелени: {proof.said()} из {TRIES_LIMIT}")
            if proof.spent:
                print("предел попыток исчерпан — адресат владелец (109)")
        save(args.repo, token, render_body(holds, rest, flakes, sha, queue, proof), args.apply)
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except policy.BadPolicy as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except ghrest.TransportError as exc:
        print(f"шаг не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_RED if holds or rest else EXIT_GREEN


if __name__ == "__main__":
    raise SystemExit(main())
