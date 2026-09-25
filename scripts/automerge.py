#!/usr/bin/env python3
"""Шаг 8: очередь и слияние. Контур 2 договора, целиком.

ПОРЯДОК ЗАДАЁТСЯ ПРАВИЛОМ, А НЕ ГОТОВНОСТЬЮ
([053](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/053-queue-order-is-a-rule-not-arrival.md)).
Очередь по времени прихода означает, что починку общей ветки обгоняет любая
правка опечатки, поданная минутой раньше. Ступеней четыре: чинящее красную
общую ветку → помеченное блокирующим → трогающее общий с соседом файл →
остальные. Внутри одной ступени порядок — по номеру: приход решает только
там, где правило уже ничего не решает.

ПРИОРИТЕТ — ВСТАВКОЙ, А НЕ ПЕРЕУПОРЯДОЧИВАНИЕМ
(`docs/decisions/003-own-automerge-not-native-queue.md`). Очередь здесь не
хранится: она вычисляется на каждом заходе из живых изменений и их меток
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
Ведомый руками реестр разошёлся бы с площадкой на первом же закрытом изменении.

ДВИГАЕТСЯ ТОЛЬКО ГОЛОВА, И ТОЛЬКО ПЕРЕД СЛИЯНИЕМ
([052](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/052-only-the-head-of-the-queue-moves.md)).
Подтягивать базу всем после каждого слияния — квадрат холостой работы: замер
каталога на 09.09.2026 — 21 холостой прогон против 12 полезных на шести
изменениях; след — `docs/decisions/003-own-automerge-not-native-queue.md`.
Отсюда же и цена этого шага: полный список изменений — один запрос, состав
файлов — по запросу на кандидата, и только у головы читается её состояние
целиком. При объёме в единицы изменений в день это дешевле любого кеша, а
дороже стать не может: список кандидатов ограничен меткой.

КОНФЛИКТ — ШТАТНАЯ СИТУАЦИЯ, А НЕ АВАРИЯ
([004](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/004-conflict-is-normal-not-outage.md)).
Конфликтная голова пропускается, очередь идёт дальше, и изменение возвращается
в контур 1 источником 1. Ничего не замораживается и никто не будится: авария
здесь только у того, кто считает конфликт аварией.

ЗАМОРОЗКА — СЛИЯНИЯ, А НЕ РАБОТЫ. Красная общая ветка останавливает очередь
целиком, кроме изменения с меткой починки. Разница стоила соседу тринадцати
часов простоя: работа по обычным задачам при заморозке продолжается, ветки
режутся от последнего зелёного коммита.

ТОКЕН — ВЛАДЕЛЬЦА, а не прогона. На `github.token` шаг не переходит молча: это
дало бы ровно ту подмену авторства, ради которой заведён `MERGE_QUEUE_TOKEN`
([131](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/131-no-writes-from-a-cloud-session.md),
[135](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/135-session-identity-is-established-by-a-write.md)).
Слияние — уплотнением, и тело собирает `scripts/squash_body.py`
(`docs/decisions/006-merge-by-squash.md`): площадка склеивает тело сама из ВСЕХ
сообщений ветки, и на трёх коммитах это даёт три копии трейлеров.

ПУСТАЯ ОЧЕРЕДЬ — ЗАКОННОЕ СОСТОЯНИЕ, А ПУСТАЯ ГОЛОВА — ОТКАЗ. Разница по
[075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)
проходит не по слову «пусто», а по тому, найден ли ПРЕДМЕТ проверки. «Никто не
просил слияния» — это ответ, и краснеть на нём значило бы завести проверку,
которую приучаются обходить ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
«Кандидат есть, а записей проверок на его голове нет ни одной» — предмет не
найден: прогон не стартовал, и это отказ, а не «зелено».

Исходы (правило 039): ``0`` очередь прочитана и продвинута · ``2`` шаг не
отработал · ``3`` не настроено — нет токена владельца.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final

import arm
import changerefs
import ci_complete
import ghrest
import labels
import look_waits
import paths
import pipeline_checks as policy
import report
import review_findings
import squash_body
import unlooked

#: Метки — вход механизма, а не украшение (064). Имена здесь — то, что читает
#: очередь; ОБЪЯВЛЕНЫ они в составе, и совпадение сверяется перед заходом.
LABEL_AUTOMERGE: Final = "automerge"
LABEL_HOLD: Final = "hold"
LABEL_BLOCKER: Final = "blocker"
LABEL_FIX_MAIN: Final = "fix-main"
#: Остановка ЗАМОРОЗКОЙ, а не человеком: ставит и снимает шаг 9. Очередь читает
#: её так же, как `hold`, — не взводит и снимает согласие, — но владелец у метки
#: один, и это механизм: две руки на одной метке расходятся молча (022).
LABEL_PAUSED: Final = "paused/main-red"
READ_LABELS: Final = (
    LABEL_AUTOMERGE,
    LABEL_HOLD,
    LABEL_BLOCKER,
    LABEL_FIX_MAIN,
    LABEL_PAUSED,
)
#: Приставка метки-СЛЕДА: какой источник очередь присвоила изменению. Очередь
#: решает по вычисленному источнику, а не по этой метке — устаревшая увела бы
#: слияние не туда, и поймать это было бы нечем. Метка отвечает человеку на
#: списке изменений, без открытия лога.
SOURCE_PREFIX: Final = "source/"

ENV_TOKEN: Final = "MERGE_QUEUE_TOKEN"

#: СТУПЕНЬ ОЧЕРЕДИ — ЭТО НОМЕР ИСТОЧНИКА РАБОТЫ ИЗ КОНТУРА 1. Словарь один на
#: оба контура: у проекта уже есть порядок, по которому окно берёт работу
#: (`docs/behaviour.md`), и заводить рядом второй, свой, значило бы объявить,
#: что важное на входе и важное на выходе — разные вещи. Они одно.
#:
#: СЛОВАРЬ ПОЛНЫЙ — ВСЕ СЕМЬ ИСТОЧНИКОВ, а не только те, что даёт сортировка.
#: Изменение, взятое из плана, стоит на 6; покраснев, оно становится работой по
#: источнику 2, а конфликтнув — по источнику 1. Это не другая очередь, а то же
#: изменение, сменившее источник, и печатать его надо тем же словом.
#:
#: ДВА ИСТОЧНИКА НЕ ВЫВОДЯТСЯ ДО ОБРАЩЕНИЯ К ПЛОЩАДКЕ, и это цена правила 052,
#: а не недосмотр. Красноту головы заход и так спрашивает у каждого кандидата —
#: значит источник 2 назвать может. Конфликт живёт в состоянии слияния, а его
#: площадка считает лениво: спросить его у ВСЕХ значит заказать вычисление,
#: которое никому не понадобится. Поэтому источник 1 называется там, где он
#: обнаружен, — у головы, — а не заранее.
RANK_MAIN_RED: Final = 0
RANK_CONFLICT: Final = 1
RANK_OWN_RED: Final = 2
RANK_FINDINGS: Final = 3
RANK_OWNER: Final = 4
RANK_RULES: Final = 5
RANK_PLAN: Final = 6

RANK_NAMES: Final = {
    RANK_MAIN_RED: "0 · чинит красную общую ветку",
    RANK_CONFLICT: "1 · конфликт слияния",
    RANK_OWN_RED: "2 · красная проверка на своём изменении",
    RANK_FINDINGS: "3 · снимает находку внешнего взгляда",
    RANK_OWNER: "4 · слово владельца",
    RANK_RULES: "5 · долг по правилам каталога",
    RANK_PLAN: "6 · план",
}

#: Ответ проекта каталогу: правка здесь — признак работы по источнику 5.
#: ЭТО ЭВРИСТИКА, И ОНА НАЗВАНА ЭВРИСТИКОЙ. Изменение может тронуть ответ
#: попутно, делая работу из плана, и тогда ступень будет выше заслуженной.
#: Ошибка тут дешёвая — порядок слияния, а не решение о слиянии, — а точного
#: признака у долга по правилам в дереве нет вовсе.
RULES_ANSWER: Final = f"{paths.BINDINGS}"

#: Состояние изменения, при котором площадка сама говорит «слить нечем».
STATE_CONFLICT: Final = "dirty"
#: Состояние «голова отстала от базы»: подтягивается ТОЛЬКО у головы очереди.
STATE_BEHIND: Final = "behind"
#: Состояния, при которых слияние ЗАКОННО, — список разрешительный (068).
#: `unstable` значит «красна необязательная проверка»: класс объявлен данными,
#: и совещательное красное слияния не держит. Всё прочее — `blocked`,
#: `unknown`, `draft`, пустая строка — голова пропускается с названной
#: причиной: площадка либо ещё считает, либо слить не даст, и звать слияние
#: наугад значит менять пропуск одной головы на красный весь заход.
STATE_MERGEABLE: Final = frozenset({"clean", "unstable", "has_hooks"})
#: Состояние, при котором слить НЕЛЬЗЯ СЕЙЧАС, но можно потом: обязательные
#: проверки ещё идут либо не отчитались. Именно оно отдаётся площадке — она
#: дождётся зелёного и сольёт сама
#: (`docs/decisions/011-merging-is-handed-to-the-platform.md`).
#:
#: Красную голову сюда не пускает вердикт разметки: взведённое красное заняло
#: бы единственное место взведения и держало бы очередь до починки, а красное —
#: это работа по источнику 2, вернувшаяся в окно, а не голова очереди.
STATE_ARMABLE: Final = "blocked"

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_NOT_CONFIGURED: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «очередь пуста»."""


@dataclass(frozen=True, slots=True)
class Change:
    """Одно изменение-кандидат: то, по чему решается его место в очереди."""

    number: int
    branch: str
    base: str
    head: str
    title: str
    body: str
    draft: bool
    marks: frozenset[str]
    files: frozenset[str] = field(default=frozenset())
    #: Узел изменения в терминах площадки: взведение адресуется им, а не
    #: номером. Номер — адрес REST, узел — адрес мутации, и подменять один
    #: другим нечем.
    node: str = ""
    #: Взведено ли слияние у площадки. Читается из того же ответа, что и всё
    #: остальное: второй запрос за тем же знанием — вторая версия правды (052).
    armed: bool = False

    @property
    def fixes_main(self) -> bool:
        """Чинит ли изменение красную общую ветку."""
        return LABEL_FIX_MAIN in self.marks

    @property
    def held(self) -> bool:
        """Остановлено ли изменение меткой, сколько бы зелёного на нём ни было.

        Остановок две, и они РАЗНЫЕ по владельцу: `hold` ставит человек,
        `paused/main-red` — шаг 9 на время заморозки. Для очереди действие одно,
        поэтому спрашивается здесь вместе; кто остановил — видно по имени метки
        на самом изменении, без чтения логов.
        """
        return LABEL_HOLD in self.marks or LABEL_PAUSED in self.marks

    @property
    def paused(self) -> bool:
        """Остановлено ли изменение заморозкой общей ветки."""
        return LABEL_PAUSED in self.marks


def check_labels_declared() -> None:
    """Сверяет читаемые имена с составом: механизм не держит своей копии.

    Состав меток разбирает один модуль, а не каждый по-своему: читателей у
    файла трое, и раньше они читали его по-разному — один открывал изменение,
    которое другой тут же отвергал
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    Переименование метки в составе обязано ронять очередь громко: молча она
    перестала бы находить кандидатов и выглядела бы как «сливать нечего».
    """
    declared = {item.name for item in labels.load()}
    # Метки-следы объявляются наравне со входами: гейт разметки отвергает
    # изменение с меткой, которой нет в составе, — то есть очередь могла бы
    # своей же меткой сделать изменение красным.
    wanted = (*READ_LABELS, *(source_label(place) for place in RANK_NAMES))
    missing = [name for name in wanted if name not in declared]
    if missing:
        raise NotRun(
            f"очередь читает метки, которых нет в составе: {', '.join(missing)} — "
            "вход механизма не найден, и это отказ, а не «кандидатов нет» (064, 075)"
        )


def source_label(place: int) -> str:
    """Имя метки-следа для номера источника."""
    return f"{SOURCE_PREFIX}{place}"


def publish_source(
    repo: str, change: Change, place: int, owner_token: str, *, dry_run: bool
) -> frozenset[str]:
    """Выставляет изменению метку присвоенного источника — ровно одну.

    ПИШЕТ ТОЛЬКО ПРИ РАСХОЖДЕНИИ. Заход идёт на каждое событие, и переставлять
    метку каждый раз значило бы платить запросом за неизменившееся состояние
    ([017](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/017-measure-quota-do-not-guess.md)).
    Цена в худшем случае — два запроса на изменение, и только когда источник
    действительно сменился.

    ОТКАЗ РАЗМЕТКИ ЗАХОД НЕ РОНЯЕТ. Метка — след, а не вход: без неё очередь
    работает ровно так же, а красное здесь говорило бы о разметке, а не о
    слиянии (084).
    """
    wanted = source_label(place)
    present = {mark for mark in change.marks if mark.startswith(SOURCE_PREFIX)}
    if present == {wanted}:
        return frozenset(present)
    if dry_run:
        print(f"  {report.DRY} #{change.number}: метка стала бы «{wanted}»")
        return frozenset({wanted})
    try:
        for stale in sorted(present - {wanted}):
            path = f"repos/{repo}/issues/{change.number}/labels/{ghrest.quote(stale)}"
            ghrest.request("DELETE", path, owner_token)
        if wanted not in present:
            ghrest.request(
                "POST",
                f"repos/{repo}/issues/{change.number}/labels",
                owner_token,
                {"labels": [wanted]},
            )
    except ghrest.TransportError as exc:
        print(f"  #{change.number}: метка источника не выставлена — {report.cut(str(exc))}")
        return frozenset(present)
    # ЧТО СТОИТ ПОСЛЕ ЗАПИСИ, ЗНАЕТ ЗАПИСЬ, А НЕ СНИМОК. `change.marks` снят
    # перечислением — ДО этой постановки, — и снятие метки по нему не видело
    # той, которую заход поставил секундой раньше
    # ([135](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/135-session-identity-is-established-by-a-write.md)).
    return frozenset({wanted})


def drop_source(
    repo: str,
    change: Change,
    owner_token: str,
    *,
    dry_run: bool,
    also: frozenset[str] = frozenset(),
) -> None:
    """Снимает метку источника у изменения, по которому работать нечем.

    ИСТОЧНИК — ЭТО «ОТКУДА ВЗЯЛАСЬ РАБОТА», А У ПУСТОГО ЕЁ НЕТ. Метку ставит
    перечисление очереди, и ставит ДО того, как спрошен объём: пустая голова
    получала «6 · план» и выглядела обычной работой в хвосте очереди. Нашёл
    внешний взгляд на #288.

    ОТКАЗ РАЗМЕТКИ ЗАХОД НЕ РОНЯЕТ — как и у выставления метки: это след, а не
    вход
    ([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
    """
    # СНИМАЕТСЯ И ТО, ЧТО ПОСТАВИЛ ЭТОТ ЖЕ ЗАХОД. Метку источника ставит
    # перечисление очереди, а пустоту головы заход узнаёт позже — по снимку
    # `change.marks` свежей метки не видно, и она оставалась на пустой голове
    # навсегда: заход, который её поставил, сам же считал, что снимать нечего.
    # Нашёл внешний взгляд на #311.
    present = sorted(
        mark for mark in (set(change.marks) | set(also)) if mark.startswith(SOURCE_PREFIX)
    )
    if not present:
        return
    if dry_run:
        print(f"  {report.DRY} #{change.number}: метки источника сняли бы — {present}")
        return
    # КАЖДАЯ МЕТКА СНИМАЕТСЯ ОТДЕЛЬНО. Один `try` на весь список обрывался на
    # первом же отказе, а самый частый отказ здесь — 404 по метке, снятой
    # раньше: список собран из снимка И из записи этого захода, и они
    # пересекаются. Оборвавшись на снятой, цикл оставлял висеть ещё стоящую —
    # то есть терял ровно ту метку, ради которой заведён (084; нашёл внешний
    # взгляд на #328).
    for stale in present:
        path = f"repos/{repo}/issues/{change.number}/labels/{ghrest.quote(stale)}"
        try:
            ghrest.request("DELETE", path, owner_token)
        except ghrest.TransportError as exc:
            print(f"  #{change.number}: метка «{stale}» не снята — {report.cut(str(exc))}")


def token() -> str:
    """Токен владельца. Токен прогона сюда НЕ подставляется (131)."""
    return os.environ.get(ENV_TOKEN, "")


def marks_of(payload: dict[str, Any]) -> frozenset[str]:
    """Метки изменения множеством имён."""
    return frozenset(str(item.get("name", "")) for item in payload.get("labels") or [])


def open_changes(repo: str, owner_token: str) -> list[Change]:
    """Живые изменения площадки — без состава файлов: он читается отдельно."""
    found: list[Change] = []
    for payload in ghrest.paginate(f"repos/{repo}/pulls?state=open", owner_token):
        head = payload.get("head") or {}
        base = payload.get("base") or {}
        found.append(
            Change(
                number=int(payload["number"]),
                branch=str(head.get("ref", "")),
                base=str(base.get("ref", "")),
                head=str(head.get("sha", "")),
                title=str(payload.get("title", "")),
                body=str(payload.get("body") or ""),
                draft=bool(payload.get("draft")),
                marks=marks_of(payload),
                node=str(payload.get("node_id") or ""),
                armed=payload.get("auto_merge") is not None,
            )
        )
    return found


#: Пути, тронутые изменением: по ним видно пересечение с соседом (133). Читатель
#: общий с уборкой реестра находок и живёт в транспорте — копия у каждого
#: разошлась бы молча (090).
files_of = ghrest.files_of


def candidates(changes: list[Change], base: str) -> list[Change]:
    """Отбирает то, что вообще просится в очередь.

    Черновик не кандидат: он не объявлен готовым. Метка ``hold`` снимает
    изменение с очереди при любом зелёном — это её единственный смысл
    ([147](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/147-a-cancelling-switch-needs-an-addressee.md)).
    """
    return [
        change
        for change in changes
        if change.base == base
        and not change.draft
        and not change.held
        and LABEL_AUTOMERGE in change.marks
    ]


def shared_paths(changes: list[Change]) -> frozenset[str]:
    """Пути, которые трогает больше одного кандидата.

    «Общий файл» здесь не объявленный список, а пересечение живых составов:
    граница изменения задаётся пересечением файлов, а не числом задач (133).
    Список, ведомый руками, устарел бы на первом же новом механизме.
    """
    seen: dict[str, int] = {}
    for change in changes:
        for path in change.files:
            seen[path] = seen.get(path, 0) + 1
    return frozenset(path for path, count in seen.items() if count > 1)


def rank(change: Change) -> int:
    """Ступень очереди — номер источника работы, которому изменение отвечает.

    Здесь называется источник, выводимый ДО обращения к площадке. Источники 1
    и 2 добавляются заходом там, где он их обнаружил: изменение из плана,
    покраснев, становится работой по источнику 2, а конфликтнув — по источнику
    1, и это то же изменение, сменившее источник, а не другая очередь.

    Признаки разные по природе, и это названо, а не сглажено. Источник 0 и
    источник 4 приходят МЕТКОЙ: краснота общей ветки — решение конвейера,
    слово владельца — решение человека, и вывести его из дерева нельзя вовсе
    («у владельца есть предмет, которого механизм не знает»). Источник 3
    выводится МАШИННО: снятие находки живёт строкой в теле изменения.
    Источник 5 — ЭВРИСТИКА по тронутому файлу, и она объявлена такой.

    Заморозки здесь нет: красная общая ветка решается ОТБОРОМ, а не ступенью.
    Ступень «чинит» первая и на зелёной базе: починка, поданная позже,
    обгоняет готовое раньше.
    """
    if change.fixes_main:
        return RANK_MAIN_RED
    if changerefs.resolved_in(change.body):
        return RANK_FINDINGS
    if LABEL_BLOCKER in change.marks:
        return RANK_OWNER
    if RULES_ANSWER in change.files:
        return RANK_RULES
    return RANK_PLAN


def order(changes: list[Change], shared: frozenset[str]) -> list[Change]:
    """Очередь: сначала правило, потом пропускная способность, потом приход.

    «Трогает общий с соседом файл» — НЕ ступень и не приоритет: это способ
    уменьшить будущие конфликты, а не утверждение о важности. Поэтому он решает
    ВНУТРИ ступени, до номера: среди равных вперёд идёт тот, чьё слияние
    избавит соседей от подтягивания базы.

    Номер изменения — последний ключ: приход решает только там, где правило и
    пропускная способность уже ничего не решают.
    """
    return sorted(
        changes,
        key=lambda change: (rank(change), not (change.files & shared), change.number),
    )


def branch_health(repo: str, sha: str, owner_token: str) -> list[str]:
    """Что не так на голове общей ветки: пусто — значит ветка зелёная.

    Опрашиваются ИМЕНА, объявленные обязательными данными проекта, а не все
    записи подряд: класс проверки — свойство потребителя (174), и читается он
    там же, где его читает сводный гейт.
    """
    checks = policy.load()
    required = policy.names_of(checks, policy.REQUIRED)
    runs = list(
        ghrest.paginate(
            f"repos/{repo}/commits/{sha}/check-runs?filter=latest", owner_token, key="check_runs"
        )
    )
    # Отсутствие записи здесь тоже не отказ, и по той же причине: проверка
    # изменения на общей ветке не идёт вовсе, а не «не стартовала».
    alive = ci_complete.worst_per_name(ci_complete.on_the_shared_branch(runs))
    problems, _ = ci_complete.verdict(alive, required, "", strict_missing=False)
    return problems


def head_verdict(repo: str, change: Change, owner_token: str) -> tuple[list[str], bool]:
    """Вердикт по голове кандидата: находки и признак «ещё идут».

    Пустой список записей на голове — отказ, а не «зелено»: предмет проверки не
    найден (075). Именно здесь эта строгость и нужна, в отличие от общей ветки.
    """
    checks = policy.load()
    required = policy.names_of(checks, policy.REQUIRED)
    runs = list(
        ghrest.paginate(
            f"repos/{repo}/commits/{change.head}/check-runs?filter=latest",
            owner_token,
            key="check_runs",
        )
    )
    if not runs:
        return ([f"#{change.number}: записей проверок на голове нет — прогон не стартовал"], False)
    return ci_complete.verdict(ci_complete.worst_per_name(runs), required, "", strict_missing=True)


#: Имя записи проверки взгляда на голове: имя джоба и есть имя контекста
#: (`docs/pipeline.md`), как и у реестра слитого без взгляда.
REVIEW_CHECK: Final = "review"


def look_pending(runs: list[dict[str, Any]]) -> bool:
    """Идёт ли на голове взгляд: запись проверки взгляда есть и не завершена.

    СОГЛАСИЕ ЖДЁТ ВЕРДИКТА ВЗГЛЯДА, А НЕ ЕГО ЗЕЛЕНИ (#654, решение владельца
    24.09.2026, вариант 3). Замер смены 23–24.09.2026: слито 32 изменения, 30
    из них догоняли находки взгляда на уже слитом — голова сливалась раньше,
    чем взгляд успевал сказать, и каждая находка уезжала отдельным изменением.
    Теперь голова не взводится и не сливается, пока взгляд идёт; находка,
    пришедшая до слияния, чинится в той же ветке.

    Исход взгляда при этом не судится: он совещательный, и красное или
    зелёное его записи слияния не держит (051). Записи нет вовсе — взгляд не
    запускался (правка файла прогона, форк), и ждать некого: молчание взгляда
    не становится затором, его называет реестр слитого без взгляда.
    """
    return any(
        str(run.get("name") or "") == REVIEW_CHECK and run.get("status") != "completed"
        for run in runs
    )


def awaits_look(repo: str, change: Change, owner_token: str) -> bool:
    """Ждёт ли голова вердикта взгляда — по записям проверок её головы.

    Спрашивается отдельно от вердикта проверок и только у головы, которую
    сейчас взводят или сливают: вопрос другой (взгляд в вердикт не входит), и
    читать его надо в миг решения, а не в начале захода.
    """
    runs = list(
        ghrest.paginate(
            f"repos/{repo}/commits/{change.head}/check-runs?check_name={REVIEW_CHECK}",
            owner_token,
            key="check_runs",
        )
    )
    return look_pending(runs)


def owed_look(repo: str, change: Change, owner_token: str) -> str:
    """Номер прогона взгляда, пропущенного на этой голове, пока она была красной.

    ВЗГЛЯД — ПОСЛЕДНИМ (#762): на красной голове он пропускается, и его запись
    завершается. Позеленей голова ТОЛЧКОМ — новый взгляд позовёт сам толчок.
    Но упавшее перезапускают и без толчка, и тогда голова зелёная, записи
    взгляда незавершённой нет — `awaits_look` молчит, и голова слилась бы без
    взгляда. Пропуск помечен аннотацией `look_waits.SKIPPED` на записи; очередь
    читает её у ПОСЛЕДНЕЙ записи взгляда головы. Пусто — взгляд не должен.
    """
    runs = ghrest.paginate(
        f"repos/{repo}/commits/{change.head}/check-runs?check_name={REVIEW_CHECK}&filter=latest",
        owner_token,
        key="check_runs",
    )
    for run in runs:
        if run.get("status") != "completed" or not run.get("id"):
            continue
        notes = ghrest.paginate(f"repos/{repo}/check-runs/{run['id']}/annotations", owner_token)
        if any(str(note.get("title") or "") == look_waits.SKIPPED for note in notes):
            return run_of(str(run.get("details_url") or ""))
    return ""


#: Сколько раз очередь перезапускает пропущенный взгляд одной головы. Один:
#: второй пропуск значит, что ворота взгляда и очередь судят голову по-разному,
#: и перезапуски звали бы друг друга без конца (находка позднего взгляда на #771).
OWED_RERUNS: Final = 1


def call_the_owed_look(repo: str, run: str, owner_token: str, *, dry_run: bool) -> bool:
    """Перезапускает пропущенный взгляд; отказ площадки назван, а не проглочен (045).

    ПЕРЕЗАПУСК ОДИН. Попытка прогона видна у площадки (`run_attempt`), и
    прогон, уже перезапущенный очередью, второй раз не зовётся: голова ждёт, а
    расхождение названо. Держится это номером попытки, а не памятью очереди:
    заход очереди короткий, и свой счётчик разошёлся бы с площадкой (049).
    """
    try:
        attempt = int(
            (ghrest.request("GET", f"repos/{repo}/actions/runs/{run}", owner_token) or {}).get(
                "run_attempt"
            )
            or 1
        )
    except ghrest.TransportError as exc:
        print(f"::warning::попытка прогона взгляда {run} не прочитана: {exc}")
        return False
    if attempt > OWED_RERUNS:
        print(
            f"::warning::прогон взгляда {run} уже перезапускался ({attempt} попытки) и снова "
            "пропущен: ворота взгляда и очередь судят голову по-разному — второй перезапуск "
            "не зовётся, голова ждёт"
        )
        return False
    if dry_run:
        print(f"  {report.DRY} перезапустил бы прогон взгляда {run}")
        return True
    try:
        ghrest.request("POST", f"repos/{repo}/actions/runs/{run}/rerun", owner_token)
    except ghrest.TransportError as exc:
        print(f"::warning::прогон взгляда {run} не перезапущен: {exc}")
        return False
    return True


#: Прогон, из которого написан комментарий действия: шапка «View job» ведёт
#: на `…/actions/runs/<id>`, и адрес записи проверки несёт тот же номер.
RUN_ID_RE: Final = re.compile(r"/actions/runs/(\d+)")


def run_of(text: str) -> str:
    """Номер прогона по ПЕРВОЙ ссылке на прогон в тексте; пусто — ссылки нет.

    Первая — потому что шапку «View job» действие ставит в начало своего
    комментария. Ссылка, процитированная ниже, прогоном комментария не
    становится.
    """
    found = RUN_ID_RE.search(text)
    return found.group(1) if found else ""


def verdicts_on(
    comments: list[dict[str, Any]], looks: Mapping[str, list[str]] | None
) -> list[tuple[str, int]]:
    """Вердикты взгляда по изменению: время вердикта и число находок.

    `looks` — прогоны взгляда голов изменения: номер → когда завершалась
    каждая его попытка.

    Поздний взгляд по общей ветке сюда не входит: он о слитом, а не о голове
    изменения, и отмечен своей скрытой строкой. Вердикт — только из
    комментария бота: человек может процитировать строку вердикта.

    ВЕРДИКТ — ТОЛЬКО ИЗ ПРОГОНА ВЗГЛЯДА (`looks`), а не от любого бота.
    Ответчик по обращению (`claude.yml`) пишет тем же `claude[bot]`, и его
    цитата «ВЕРДИКТ: находок 0» снимала держание без починки (`1d79af0`).
    Различает их не автор, а прогон: шапка комментария ведёт на прогон, и
    засчитывается лишь прогон проверки `review` одной из голов изменения.
    Граница названа: держится это на том, что шапку ставит действие, а не
    модель. Комментарий, написанный мимо действия, со ссылкой на прогон
    взгляда первой строкой прошёл бы.
    """
    found: list[tuple[str, int]] = []
    for comment in comments:
        body = str(comment.get("body") or "")
        if unlooked.LATE_MARKER in body:
            continue
        # Вердикт пишет ревьюер-бот; процитированная человеком строка
        # «ВЕРДИКТ: находок 0» держание не снимает (`8b549e5`).
        if (comment.get("user") or {}).get("type") != "Bot":
            continue
        # `None` — прогон не сверяется: так читаются вердикты голов, которых
        # среди коммитов изменения уже нет (перезапись истории).
        if looks is not None and run_of(body) not in looks:
            continue
        said = review_findings.verdict_of([comment])
        if said is not None:
            found.append((verdict_time(comment, looks), said))
    return found


def verdict_time(comment: dict[str, Any], looks: Mapping[str, list[str]] | None) -> str:
    """Когда вердикт сказан: завершение его прогона взгляда, а не время комментария.

    НЕ ВРЕМЯ СОЗДАНИЯ. Действие создаёт комментарий в начале захода и
    вписывает вердикт правкой в конце; по времени создания вердикт прежней
    головы, вписанный после подтяжки, ложился «до головы» и считался
    державшим — и голова не держалась ни разу (#751, на #748).

    И НЕ ВРЕМЯ ПОСЛЕДНЕЙ ПРАВКИ. Правка комментария человеком (разметка,
    опечатка) сдвигает `updated_at`: старый вердикт уезжал «после головы», и
    голову держали второй раз (взгляд на #752). Завершение прогона правкой не
    сдвинуть. Время правки остаётся запасным: прогон ещё не завершён либо не
    найден среди голов (перезапись истории, `looks is None`) — и там граница
    с правкой рукой названа, а не закрыта.

    ПОПЫТОК У ПРОГОНА БЫВАЕТ НЕСКОЛЬКО, а номер в адресе у них один:
    перезапуск взгляда прежней головы давал её старому вердикту завершение
    НОВОЙ попытки, и голову держали второй раз (взгляд на #752). Каждая
    попытка пишет свой комментарий, поэтому вердикту принадлежит самое раннее
    завершение, случившееся не раньше создания его комментария.
    """
    written = str(comment.get("updated_at") or comment.get("created_at") or "")
    if looks is None:
        return written
    created = str(comment.get("created_at") or "")
    ends = sorted(
        end for end in looks.get(run_of(str(comment.get("body") or "")), []) if end >= created
    )
    return ends[0] if ends else written


def holds_for_findings(verdicts: list[tuple[str, int]], head_time: str) -> bool:
    """Держит ли вердикт голову: первый вердикт с находками — да, всё прочее — нет.

    ДЕРЖАНИЕ ОДНО НА ИЗМЕНЕНИЕ (#734, решение владельца 24.09.2026). После
    ПЕРВОГО вердикта с находками согласие ждёт следующего толчка — это окно,
    чтобы починка ехала в ту же ветку, а не новым изменением. На следующей
    голове держания уже нет, сколько бы находок ни пришло: ревьюер повторяет
    неснятые находки дословно, и держание «пока есть находки» стало бы вечным
    циклом.

    Вердикт принадлежит голове, если сказан после начала взгляда по ней
    (`verdict_time`). Сюда входит и вердикт ПРЕЖНЕЙ головы, сказанный после
    подтяжки: окна на починку его находок ещё не было, и держит он новую
    голову, даже если её собственный взгляд промолчал (взгляд на #752).
    Вердиктов после начала взгляда нет — держать нечем. Последний — по времени
    вердикта, а не по порядку комментариев: комментарий создаётся в начале
    захода, и долгий заход, начатый раньше, говорит позже.
    """
    ordered = sorted(verdicts, key=lambda one: one[0])
    before = [count for when, count in ordered if when < head_time]
    after = [count for when, count in ordered if when >= head_time]
    return bool(after) and after[-1] > 0 and not any(count > 0 for count in before)


def look_runs(repo: str, sha: str, owner_token: str) -> list[dict[str, Any]]:
    """Записи проверки взгляда на коммите — все заходы и все попытки, а не последняя.

    По умолчанию площадка отдаёт только последнюю попытку (`filter=latest`),
    и время ранней попытки терялось (взгляд на #752).

    Сосед по тому же чтению — ВРЕМЯ ГОЛОВЫ: теперь это начало ПЕРВОЙ попытки
    её взгляда, а не последней (взгляд на #755). Так и должно быть: взгляд по
    голове начался толчком. По последней попытке перезапуск взгляда самой
    головы делал её первый вердикт с находками «прежним», и держания не было.
    """
    return list(
        ghrest.paginate(
            f"repos/{repo}/commits/{sha}/check-runs?check_name={REVIEW_CHECK}&filter=all",
            owner_token,
            key="check_runs",
        )
    )


def findings_hold(repo: str, change: Change, owner_token: str) -> bool:
    """Держат ли находки вердикта эту голову — по ленте изменения и времени головы.

    ВРЕМЯ ГОЛОВЫ — НАЧАЛО ВЗГЛЯДА ПО НЕЙ, а не дата коммита. Коммит, сделанный
    до вердикта по прежней голове и толкнутый после, по дате коммитера
    выглядел старше вердикта — и тот держал его второй раз (`e09a581`). Взгляд
    по голове стартует толчком, и его начало — время толчка. Записи взгляда
    нет — держать нечем.

    Прогоны взгляда читаются по ВСЕМ коммитам изменения: вердикт прежней
    головы решает, держали ли уже, и он тоже обязан быть из прогона взгляда
    (`1d79af0`). Права те же, что у записей проверок головы: API прогонов
    токену владельца не объявлено. Цена — запрос на коммит изменения, и только
    у зелёной непустой головы.
    """
    runs = look_runs(repo, change.head, owner_token)
    starts = [str(run.get("started_at") or "") for run in runs if run.get("started_at")]
    when = min(starts, default="")
    if not when:
        return False
    for commit in ghrest.paginate(f"repos/{repo}/pulls/{change.number}/commits", owner_token):
        sha = str(commit.get("sha") or "")
        if sha and sha != change.head:
            runs += look_runs(repo, sha, owner_token)
    looks: dict[str, list[str]] = {}
    for run in runs:
        number = run_of(str(run.get("details_url") or ""))
        if not number:
            continue
        # Ключ — у КАЖДОГО прогона взгляда: по нему `verdicts_on` решает, из
        # прогона ли взгляда комментарий. Незавершённый прогон — без времени.
        ends = looks.setdefault(number, [])
        if run.get("completed_at"):
            ends.append(str(run["completed_at"]))
    comments = list(ghrest.paginate(f"repos/{repo}/issues/{change.number}/comments", owner_token))
    if not holds_for_findings(verdicts_on(comments, looks), when):
        return False
    # ПЕРЕЗАПИСЬ ИСТОРИИ УНОСИТ ПРЕЖНИЕ ГОЛОВЫ из `pulls/{n}/commits`, и с ними
    # — прогоны их взгляда: вердикт с находками по такой голове отбрасывался,
    # и новую голову держали второй раз (взгляд на #743). Вердикт с находками
    # до головы, чей прогон не найден, засчитывается прежним — но только если
    # перезапись была: иначе цитата ответчика снова решала бы за взгляд.
    # Граница: на перезаписанном изменении такая цитата до головы держание
    # снимет — это одно окно для починки, а не слияние без взгляда. Время
    # здесь — время правки комментария: прогона потерянной головы не найти, и
    # правка рукой его сдвинет (названо у `verdict_time`).
    lost = [count for at, count in verdicts_on(comments, None) if at < when and count > 0]
    return not (lost and force_pushed(repo, change, owner_token))


def force_pushed(repo: str, change: Change, owner_token: str) -> bool:
    """Перезаписывали ли историю ветки изменения — по событиям изменения."""
    return any(
        str(event.get("event") or "") == "head_ref_force_pushed"
        for event in ghrest.paginate(f"repos/{repo}/issues/{change.number}/events", owner_token)
    )


@dataclass(frozen=True, slots=True)
class Head:
    """Что площадка говорит о голове очереди: чем слить и сколько там работы.

    `changed` — число тронутых файлов, и `None` здесь НЕ ноль: «площадка не
    сказала» и «изменение пусто» — разные ответы, и путать их значит снимать
    согласие с живого изменения по молчанию поля
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """

    state: str
    #: Сколько файлов тронуто. Имя НЕ `files`: у изменения уже есть поле с этим
    #: именем и другим смыслом — там пути, здесь счёт. Одно имя на два смысла в
    #: одном модуле читается как одно и то же (022). Нашёл внешний взгляд
    #: на #288.
    changed: int | None


def head_look(repo: str, number: int, owner_token: str) -> Head:
    """Состояние слияния и объём изменения у головы очереди — одним запросом.

    Читается ТОЛЬКО у головы (052): площадка считает состояние лениво, и
    спрашивать его у всех значит заказывать вычисление, которое никому не
    понадобится. Объём приезжает тем же ответом и своего запроса не стоит.
    """
    payload = ghrest.request("GET", f"repos/{repo}/pulls/{number}", owner_token) or {}
    said = payload.get("changed_files")
    return Head(
        str(payload.get("mergeable_state") or ""),
        said if isinstance(said, int) and not isinstance(said, bool) else None,
    )


def sync_head(repo: str, number: int, owner_token: str, *, dry_run: bool) -> None:
    """Подтягивает базу в голову очереди — и только в неё."""
    if dry_run:
        print(f"  {report.DRY} база подтянулась бы в #{number}")
        return
    ghrest.request("PUT", f"repos/{repo}/pulls/{number}/update-branch", owner_token, body={})


def fetch(change: Change) -> None:
    """Приносит ветку кандидата и базу в чекаут очереди.

    Заход очереди работает не на ветке кандидата: чекаут у него свой, и голого
    имени `agent/<задача>` в нём нет — `git log` по нему не разрешится, и тело
    уплотнения не соберётся ни разу. Ветка приносится явно и читается как
    `origin/<ветка>`: сборщик подставляет `origin/` только базе.
    """
    for ref in (change.base, change.branch):
        squash_body.git("fetch", "--no-tags", "origin", f"{ref}:refs/remotes/origin/{ref}")


def merge(repo: str, change: Change, owner_token: str, *, dry_run: bool) -> str:
    """Сливает изменение уплотнением; тело собирает общий модуль."""
    fetch(change)
    body = squash_body.compose(f"origin/{change.branch}", change.base)
    title = f"{change.title} (#{change.number})"
    if dry_run:
        print(f"  {report.DRY} слилось бы #{change.number} телом:\n{body}")
        return ""
    payload = ghrest.request(
        "PUT",
        f"repos/{repo}/pulls/{change.number}/merge",
        owner_token,
        body={"merge_method": "squash", "commit_title": title, "commit_message": body},
    )
    return str((payload or {}).get("sha", ""))


def take_back(repo: str, change: Change, why: str, owner_token: str, *, dry_run: bool) -> None:
    """Снимает взведение с изменения, называя причину.

    Причина печатается ВСЕГДА: снятие согласия — действие, и «почему» у него
    ровно столько же читателей, сколько у самого слияния
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    print(f"#{change.number}: снимаю взведение — {why}")
    if dry_run:
        return
    arm.disarm(change.node, owner_token)


def name_the_emptiness(
    repo: str,
    change: Change,
    owner_token: str,
    *,
    dry_run: bool,
    also: frozenset[str] = frozenset(),
) -> None:
    """Называет пустую голову и снимает с неё согласие, не трогая ветку.

    ПУСТОЕ ИЗМЕНЕНИЕ — СОСТОЯНИЕ ТЕРМИНАЛЬНОЕ, А НЕ «ОТСТАЛО». 13.09.2026
    площадка слила #285 уплотнением, но метаданные изменения этого не
    отразили: `merged_at` пуст, изменение открыто. Очередь увидела «behind»,
    подтянула базу — и прогоны пошли по второму кругу на дифе, которого уже
    нет. Выход из такого состояния обязан быть терминальным
    ([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md)),
    а закрыть изменение может только владелец — значит дело очереди назвать
    это и не оживлять. Разбор — #287.

    Читателей у этого ответа двое — пустая голова и голова, которая пуста И
    красна, — и второе их понимание разошлось бы с первым молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    print(
        f"#{change.number}: изменение ПУСТО — содержимое уже в базе. Работать по нему "
        "нечем; обновление ветки только погнало бы прогоны по второму кругу (109). "
        "Закрыть его может владелец."
    )
    # Источник работы снимается: у пустого изменения его нет, а метка,
    # поставленная перечислением очереди до вопроса об объёме, выдавала бы его
    # за обычную работу в хвосте плана.
    drop_source(repo, change, owner_token, dry_run=dry_run, also=also)
    if change.armed:
        take_back(
            repo, change, "изменение пусто: содержимое уже в базе", owner_token, dry_run=dry_run
        )


def held_body(repo: str, number: int, owner_token: str) -> tuple[str, str]:
    """Чем площадка держит изменение взведённым: заголовок и тело уплотнения.

    ЧИТАЕТСЯ REST, И ЭТО ВАЖНО. Взвести дешевле нельзя — у мутации нет
    REST-эквивалента, — а вот ПРОЧИТАТЬ взведённое можно обычным запросом:
    поле `auto_merge` отдаётся вместе с изменением. Правило
    [001](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/001-transport-rest-not-graphql.md)
    требует REST по умолчанию, и «раз уж пошли в GraphQL, спросим и это» —
    ровно тот путь, которым у соседей выросли 2436 строк из 131.
    """
    payload = ghrest.request("GET", f"repos/{repo}/pulls/{number}", owner_token) or {}
    kept = payload.get("auto_merge")
    if not kept:
        # Значка нет — законное состояние, и молчать о нём можно: спрашивали
        # именно это.
        return "", ""
    title, body = kept.get("commit_title"), kept.get("commit_message")
    if title is None or body is None:
        # ФОРМА ОТВЕТА НЕ УГАДЫВАЕТСЯ. Имена полей были объявлены по памяти, и
        # внешний взгляд назвал это на #234 (`9a451c0`). ЗАМЕР 12.09.2026 на
        # взведённом #236: площадка отдаёт `commit_message`, `commit_title`,
        # `enabled_by`, `merge_method`.
        #
        # ЧТО ЗАМЕР ОТКРЫЛ, А ЧТО ЛИШЬ ПОДТВЕРДИЛ — РАЗНЫЕ ВЕЩИ, и в один ряд
        # их ставить нельзя (нашёл внешний взгляд на #237). ОТКРЫЛ: имена полей
        # верны — их мы и угадывали; и `enabled_by` равен владельцу, чего мы не
        # передавали вовсе, то есть площадка сама назвала личность (131).
        # ПОДТВЕРДИЛ: `merge_method` равен `squash` — это эхо нашего же входа,
        # и доказывает он лишь, что вход дошёл, а не что площадка так решила.
        # Имена теперь держатся замером, а не памятью (005). Пустая
        # строка вместо отсутствующего поля читалась бы как «тело у площадки
        # другое» — и заход снимал бы и взводил значок на КАЖДОМ проходе, не
        # сходясь никогда
        # ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
        # Поэтому взведение без полей тела — отказ вслух, а не тихий пропуск.
        raise NotRun(
            f"#{number}: площадка держит взведение, но полей тела в ответе нет — "
            f"пришло {sorted(kept)}. Форма ответа изменилась либо названа неверно, и "
            "сверять тело не с чем"
        )
    return str(title), str(body)


def keep_only(
    repo: str, change: Change, queue: list[Change], owner_token: str, *, dry_run: bool
) -> None:
    """Оставляет взведённой ровно одну голову — названную, — и снимает остальные.

    ЭТО И ЕСТЬ ТО, ЧЕМ СОХРАНЯЕТСЯ НАШ ПОРЯДОК. Площадка сливает взведённое в
    порядке позеленения, а не вставки: взведи двоих — и очередь станет их
    гонкой, «кто первее, того и тапки», а порядок у нас правило, а не порядок
    прибытия
    ([053](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/053-queue-order-is-a-rule-not-arrival.md)).
    Одному кандидату гонку составить некому — площадке просто некого гнать.

    ЗОВЁТСЯ ИЗ ОБОИХ ПУТЕЙ, и это была щель. Снятие стояло внутри взведения, и
    на пути «голова зелена, сливаю сам» значок соседа оставался висеть: мы
    сливали старшего, а площадка следом сливала взведённого — даже если между
    ними по нашему порядку стоял третий.
    """
    for neighbour in queue:
        if neighbour.armed and neighbour.number != change.number:
            take_back(repo, neighbour, "взведена не голова очереди", owner_token, dry_run=dry_run)


def hand_over(
    repo: str, change: Change, queue: list[Change], owner_token: str, *, dry_run: bool
) -> None:
    """Отдаёт площадке последнее действие: взводит слияние НАШИМ телом.

    ВЗВЕДЁННОЙ ДЕРЖИТСЯ РОВНО ОДНА ГОЛОВА — за этим следит :func:`keep_only`,
    и зовётся она из обоих путей, а не только отсюда.

    ТЕЛО СВЕРЯЕТСЯ, А НЕ ПРЕДПОЛАГАЕТСЯ ЗАСТЫВШИМ. Значок несёт тело,
    собранное в момент взведения; в ветку могли дотолкнуть коммит, и тогда
    площадка сольёт СТАРЫМ телом — без последней работы. Поэтому заход читает
    у площадки то, что она держит, и сверяет со свежесобранным: разошлось —
    снять и взвести заново. Премисы «площадка сама сбрасывает значок на
    толчок» здесь нет намеренно: если сбрасывает, сверка просто не срабатывает
    ни разу, и механизм верен в обоих мирах (044).

    ТЕЛО УПЛОТНЕНИЯ СОБИРАЕМ МЫ. Мутация принимает `commitHeadline` и
    `commitBody`, и это проверено прогоном, а не прочитано: замер 12.09.2026 на
    #231 («blocked») и #217 («dirty») вернул и заголовок, и тело дословно. Тем
    же заходом проверяется и здесь: проглоченное тело — наступившее условие
    пересмотра решения 011, и заход об этом ГОВОРИТ, а не сливает молча (045).
    """
    keep_only(repo, change, queue, owner_token, dry_run=dry_run)

    fetch(change)
    body = squash_body.compose(f"origin/{change.branch}", change.base)
    title = f"{change.title} (#{change.number})"
    if change.armed:
        if held_body(repo, change.number, owner_token) == (title, body):
            print(f"#{change.number}: уже взведено тем же телом — площадка ждёт зелёного")
            return
        take_back(
            repo, change, "взведено телом без последней работы ветки", owner_token, dry_run=dry_run
        )
    if dry_run:
        print(f"  {report.DRY} взвёл бы #{change.number} телом:\n{body}")
        return
    answer = arm.arm(change.node, title, body, owner_token)
    lost = arm.kept_the_body(answer, title, body)
    if lost:
        raise NotRun(
            f"#{change.number}: площадка взвела слияние, но ТЕЛО не приняла — "
            f"{'; '.join(lost)}. Уплотнение уйдёт в общую ветку не нашим телом, и это "
            "названное условие пересмотра решения 011"
        )
    print(f"взведено #{change.number} — площадка дождётся зелёного и сольёт уплотнением")


def report_held(changes: list[Change]) -> None:
    """Называет остановленное меткой: отменяющий переключатель нужен адресату.

    Полного адресата у забытого ``hold`` пока нет — им станет шаг 11, — и это
    названо пробелом в AGENTS.md, а не выровнено молчанием (046, 147).
    """
    # Согласия у остановленного НЕТ и быть не должно: шаг открытия его снимает,
    # увидев стоп-метку. Требовать его здесь значило бы показывать остановленное
    # ровно до того мгновения, когда отмена сработала, — и терять из виду
    # именно то, ради чего отчёт заведён.
    held = [change for change in changes if change.held]
    if not held:
        return
    print(f"остановлено меткой: {len(held)}")
    for change in held:
        why = LABEL_PAUSED if change.paused else LABEL_HOLD
        print(f"  #{change.number} — {change.title} (метка «{why}»)")


def source_of(change: Change, red: bool) -> int:
    """Источник работы одного изменения: выводимый признак плюс своя краснота.

    Источник 0 не перебивается ничем: изменение, чинящее общую ветку, стоит
    работы всей семьи, и своя краснота его с головы очереди не снимает —
    напротив, чинить его надо тем более. Всё прочее краснота перебивает: по
    контуру 1 своё красное — источник 2, а находки, слово владельца, правила и
    план идут ниже.
    """
    place = rank(change)
    if place == RANK_MAIN_RED:
        return place
    return RANK_OWN_RED if red else place


def classify(
    repo: str, queue: list[Change], owner_token: str, *, dry_run: bool
) -> tuple[dict[int, tuple[list[str], bool]], dict[int, frozenset[str]]]:
    """Присваивает источник КАЖДОМУ кандидату и отдаёт прочитанные вердикты.

    ЗАЧЕМ ВСЕМ, А НЕ ГОЛОВЕ. Метка источника — не украшение головы очереди, а
    способ увидеть, чем занят каждый открытый кандидат: кто чинит общую ветку,
    у кого своё красное, кто ждёт плана. Прежний заход спрашивал вердикт до
    первой готовой головы и на ней останавливался, поэтому у хвоста очереди
    метка отставала на неопределённый срок.

    Опрос записей проверок здесь ОДИН на кандидата за заход, и его же читает
    движение головы ниже: второй опрос того же дал бы второе состояние того же
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

    ЧЕГО ЗДЕСЬ НЕТ: конфликта. Состояние слияния площадка считает ЛЕНИВО, и
    запрос его заказывает вычисление; спрашивать у всех значит заказывать
    работу, которая понадобится одному. Источник 1 остаётся тем, что заход
    обнаруживает на голове, и это названо, а не сглажено (046).
    """
    verdicts: dict[int, tuple[list[str], bool]] = {}
    # Что заход ПОСТАВИЛ — отдельно от того, что он прочитал: снимать метку
    # ниже придётся по записи, а не по снимку, снятому до неё.
    placed: dict[int, frozenset[str]] = {}
    print(f"кандидатов: {len(queue)}")
    for place, change in enumerate(queue, start=1):
        problems, waiting = head_verdict(repo, change, owner_token)
        verdicts[change.number] = (problems, waiting)
        source = source_of(change, bool(problems))
        print(f"  {place}. #{change.number} [{RANK_NAMES[source]}] — {change.title}")
        placed[change.number] = publish_source(repo, change, source, owner_token, dry_run=dry_run)
    return verdicts, placed


def advance(repo: str, owner_token: str, base: str, *, dry_run: bool) -> int:
    """Один заход очереди: читает, упорядочивает и двигает ГОЛОВУ.

    ЗЕЛЁНОГО ЗАХОД БОЛЬШЕ НЕ ЖДЁТ — ждёт площадка
    (`docs/decisions/011-merging-is-handed-to-the-platform.md`). Прежде здесь
    стояло ожидание внутри захода, и заводилось оно от честной беды: заход
    **гибнет в ожидании** события — группа держит одного ожидающего, и замер
    10.09.2026 дал 45 мёртвых заходов из 120. Ожидание спасало вердикт, но
    держало исполнителя и упиралось в собственный предел.

    Площадка ждёт бесплатно и без предела. Поэтому голове, у которой проверки
    ещё идут, очередь ОТДАЁТ последнее действие: взводит слияние нашим телом
    уплотнения и уходит. Порядок вставки остаётся нашим целиком — взведённой
    держится ровно одна голова, и следит за этим :func:`keep_only`, которую
    зовут ОБА пути: и взведение, и собственное слияние зелёной головы. Нашёл
    внешний взгляд на #234: докстрока называла распорядителем `hand_over`, то
    есть ровно тот путь, на котором щель и была.
    """
    check_labels_declared()
    changes = open_changes(repo, owner_token)
    report_held(changes)

    queue = candidates(changes, base)

    # СОГЛАСИЕ ОТОЗВАНО — ВЗВЕДЕНИЕ СНИМАЕТСЯ, И ДО ВСЕГО ОСТАЛЬНОГО. Метка
    # `hold`, снятая `automerge`, черновик, сменившаяся база: всё это выводит
    # изменение из кандидатов, а взведение, оставшееся на нём, однажды сольёт
    # его без согласия. Отменяющий переключатель обязан отменять
    # ([147](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/147-a-cancelling-switch-needs-an-addressee.md)).
    #
    # ВЫШЕ ПУСТОЙ ОЧЕРЕДИ — не для порядка: когда согласие снято у единственного
    # кандидата, очередь как раз и становится пустой. Стоя ниже, снятие не
    # случилось бы ровно в том случае, ради которого оно есть.
    # ЧУЖАЯ БАЗА — ЧУЖОЕ ДЕЛО. Обход идёт по живым изменениям НАШЕЙ ветки: у
    # очереди предмет — вставка в неё, и значок на изменении, нацеленном в
    # другую базу, поставлен не ею. Снимать его значило бы распоряжаться чужим
    # согласием. Нашёл внешний взгляд на #232 (`9459ea9`).
    asked = {change.number for change in queue}
    for change in changes:
        if change.base == base and change.armed and change.number not in asked:
            take_back(repo, change, "согласия на слияние больше нет", owner_token, dry_run=dry_run)

    if not queue:
        print("очередь пуста: слияния никто не просит — это состояние, а не отказ")
        return EXIT_OK

    base_sha = str(
        (ghrest.request("GET", f"repos/{repo}/commits/{base}", owner_token) or {}).get("sha", "")
    )
    if not base_sha:
        raise NotRun(f"голова общей ветки «{base}» не прочитана — двигать очередь не на что")

    queue = [replace(change, files=files_of(repo, change.number, owner_token)) for change in queue]
    shared = shared_paths(queue)
    queue = order(queue, shared)

    # РАЗМЕТКА ИДЁТ ДО РЕШЕНИЯ О ЗАМОРОЗКЕ И НЕ ЗАВИСИТ ОТ НЕГО. Источник
    # работы — свойство самого изменения, а не общей ветки, и вычислять его
    # нечем, кроме самого изменения. Прежний порядок замораживал очередь
    # раньше разметки, и метки застывали ровно тогда, когда нужнее всего:
    # красная общая ветка — момент, когда надо видеть, кто её чинит (0), а кто
    # просто ждёт.
    verdicts, placed = classify(repo, queue, owner_token, dry_run=dry_run)

    troubles = branch_health(repo, base_sha, owner_token)
    if troubles:
        print("общая ветка красна — очередь заморожена, кроме починки:")
        for trouble in troubles:
            print(f"  {trouble}")
        # ЗАМОРОЗКА СНИМАЕТ УЖЕ ВЗВЕДЁННОЕ. Не выдавать новое согласие
        # недостаточно: взведённое площадка сольёт сама, как только проверки
        # позеленеют, — то есть заморозка, которая только молчит, ничего не
        # держит
        # ([126](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/126-a-freeze-needs-a-thaw-path.md)).
        for change in queue:
            if change.armed and not change.fixes_main:
                take_back(repo, change, "общая ветка красна", owner_token, dry_run=dry_run)
        queue = [change for change in queue if change.fixes_main]
        if not queue:
            print(f"изменения с меткой «{LABEL_FIX_MAIN}» нет — не двигается ничего")
            return EXIT_OK

    # Отказы ПО ГОЛОВАМ копятся и объявляются исходом захода. Пропустить голову
    # и уйти зелёным значило бы спрятать «тело не принято» — названное условие
    # пересмотра решения 011 — за успехом соседа (045).
    refused: list[str] = []
    # Почему каждая голова не поехала. Итог захода перечисляет ИМЕННО ЭТО:
    # строка «все кандидаты либо красны, либо конфликтуют» называла причину
    # наугад и 13.09.2026 назвала неверно — единственный кандидат #285 был
    # ПУСТ, а не красен. Красное, называющее не свою причину, учит не смотреть
    # на красное (045).
    skipped: Counter[str] = Counter()

    for change in queue:
        problems, _ = verdicts[change.number]
        if problems:
            # КРАСНУЮ ГОЛОВУ СПРАШИВАЕМ ОБ ОБЪЁМЕ, И ЭТО НЕ НАРУШЕНИЕ 052.
            # Пустое изменение краснеет САМО: гейты отказываются работать без
            # входа — и правильно делают (075). Объявить такую голову «красной
            # проверкой» значит назвать не ту причину: чинить там нечего, а
            # владелец пойдёт искать поломку (045). Замер 13.09.2026 на #285:
            # голова была и пуста, и красна, и очередь назвала только красноту.
            # Цена — один запрос на КРАСНУЮ голову, а не на каждого кандидата.
            if head_look(repo, change.number, owner_token).changed == 0:
                name_the_emptiness(
                    repo,
                    change,
                    owner_token,
                    dry_run=dry_run,
                    also=placed.get(change.number, frozenset()),
                )
                skipped["пусты"] += 1
                continue
            # Красное вернуло изменение в контур 1 источником 2 ещё разметкой,
            # а очередь идёт дальше: одна красная голова не обязана держать
            # остальных.
            print(
                f"#{change.number} [{RANK_NAMES[RANK_OWN_RED]}]: пропущено — {'; '.join(problems)}"
            )
            skipped["красны"] += 1
            continue

        look = head_look(repo, change.number, owner_token)
        state = look.state
        if look.changed == 0:
            name_the_emptiness(
                repo,
                change,
                owner_token,
                dry_run=dry_run,
                also=placed.get(change.number, frozenset()),
            )
            skipped["пусты"] += 1
            continue
        # Починка идёт мимо ожидания только при КРАСНОЙ общей ветке: забытая
        # метка `fix-main` на зелёной ветке сливала бы голову без взгляда.
        repair = change.fixes_main and bool(troubles)
        # КОНФЛИКТ СТОИТ ВЫШЕ ДЕРЖАНИЯ: держимая голова в конфликте иначе не
        # публиковалась источником работы (004) до толчка, а чинить её в той
        # же ветке надо и от конфликта (`999d49b`). Слить конфликтную голову
        # площадка не может, так что держать её здесь нечего: разрешит её
        # толчок окна, и он же — толчок с починкой.
        if state == STATE_CONFLICT:
            print(
                f"#{change.number} [{RANK_NAMES[RANK_CONFLICT]}]: штатный источник работы "
                "(004), очередь идёт дальше"
            )
            publish_source(repo, change, RANK_CONFLICT, owner_token, dry_run=dry_run)
            skipped["конфликтуют"] += 1
            continue
        if not repair and findings_hold(repo, change, owner_token):
            # Окно для починки в той же ветке: следующий толчок снимет
            # держание — вердикт по новой голове держать уже не будет (#734).
            # Держание стоит ДО подтяжки: коммит слияния очереди — не толчок
            # с починкой, и подтянутая голова держание снимала без починки
            # (`f1b9f3f`).
            if change.armed:
                take_back(repo, change, "ждёт починки находок", owner_token, dry_run=dry_run)
                queue = [
                    replace(one, armed=False) if one.number == change.number else one
                    for one in queue
                ]
            print(
                f"#{change.number}: первый вердикт с находками — жду толчка с починкой "
                "в ту же ветку (#734)"
            )
            skipped["ждут починки находок"] += 1
            continue
        if state == STATE_BEHIND:
            print(f"#{change.number}: голова очереди отстала от базы — подтягиваю только её (052)")
            # Взведение соседей снимается и на этом выходе: толчок во
            # взведённое изменение ниже зовёт заход, и если он подтянет чужую
            # голову и выйдет, соседа сольёт площадка раньше нового взгляда.
            keep_only(repo, change, queue, owner_token, dry_run=dry_run)
            sync_head(repo, change.number, owner_token, dry_run=dry_run)
            return EXIT_OK
        # ОЖИДАНИЕ ВЗГЛЯДА СТОИТ ПОСЛЕ ПОДТЯЖКИ И КОНФЛИКТА: отставшую голову
        # подтяжка всё равно отправит на новый взгляд, и ждать старого значило
        # бы ждать дважды (`14207cf`). Починку КРАСНОЙ общей ветки ожидание не
        # держит: заморозка стоит на ней, и каждая минута ожидания — минута
        # красной общей ветки для всех (`f3c79a7`).
        if not repair and awaits_look(repo, change, owner_token):
            # ВЗВЕДЁННУЮ ГОЛОВУ ОЖИДАНИЕ СНИМАЕТ: площадка слила бы её сама, как
            # только позеленеют обязательные, — то есть ожидание, которое только
            # молчит, ничего не держит (126). Очередь снова позовёт завершение
            # прогона взгляда (`workflow_run` по `review`), а снимет взведение
            # после толчка — сам толчок (`synchronize`, `865341e`).
            if change.armed:
                take_back(repo, change, "ждёт вердикта взгляда", owner_token, dry_run=dry_run)
                # Снятое помечается в самой очереди: иначе слияние соседа ниже
                # сняло бы то же взведение второй раз по устаревшему снимку.
                queue = [
                    replace(one, armed=False) if one.number == change.number else one
                    for one in queue
                ]
            print(f"#{change.number}: ждёт вердикта взгляда — не взвожу (#654)")
            skipped["ждут вердикта взгляда"] += 1
            continue
        # ВЗГЛЯД, ПРОПУЩЕННЫЙ НА КРАСНОЙ ГОЛОВЕ, ГОЛОВА ЕЩЁ ДОЛЖНА (#762).
        #
        # ДВА ВОПРОСА, И У НИХ РАЗНЫЕ ГРАНИЦЫ. «Должна ли голова взгляд» — у
        # ЛЮБОЙ головы: должную не взводят, иначе площадка сольёт её без
        # взгляда, как только проверки позеленеют (щель #654). «Звать ли
        # перезапуск сейчас» — только у ЗЕЛЁНОЙ (`STATE_MERGEABLE`): у головы с
        # идущими проверками вердикта ещё нет, и перезапуск раньше него позвал
        # бы ворота на красное снова (находка на #771). Первая редакция #784
        # сузила до зелёной оба вопроса сразу, и голову в `blocked`, которую
        # перезапустили без толчка, взводили без взгляда (взгляд на #784).
        # Вердикт головы ворота читают тем же разбором, что очередь
        # (`ci_complete`, #775).
        owed = owed_look(repo, change, owner_token) if not repair else ""
        if owed:
            if change.armed:
                take_back(
                    repo, change, "взгляд пропущен на красной голове", owner_token, dry_run=dry_run
                )
                queue = [
                    replace(one, armed=False) if one.number == change.number else one
                    for one in queue
                ]
            if state in STATE_MERGEABLE:
                called = call_the_owed_look(repo, owed, owner_token, dry_run=dry_run)
                said = (
                    "перезапущен, не взвожу (#762)"
                    if called
                    else "перезапуск отказал, не взвожу (#762)"
                )
            else:
                said = "перезапуск — когда голова позеленеет, не взвожу (#762)"
            print(f"#{change.number}: взгляд пропущен, пока голова была красной — {said}")
            skipped["ждут пропущенного взгляда"] += 1
            continue
        if state == STATE_ARMABLE:
            # СЛИТЬ НЕЛЬЗЯ СЕЙЧАС — не значит «нельзя». Проверки идут либо не
            # отчитались, и ждать их теперь площадке, а не заходу.
            #
            # ОДНА ГОЛОВА НЕ УНОСИТ ВЕСЬ ЗАХОД. Отказ здесь — это отказ по
            # ЭТОЙ голове: форма ответа площадки не та, тело не принято,
            # мутация отвергнута. Очередь идёт дальше, ровно как на красной и
            # конфликтной голове, — иначе одна странная голова держала бы всю
            # очередь до вмешательства человека
            # ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
            # Нашёл внешний взгляд на #236.
            try:
                hand_over(repo, change, queue, owner_token, dry_run=dry_run)
            except NotRun as exc:
                print(f"#{change.number}: не взведено — {exc}")
                refused.append(str(exc))
                continue
            if refused:
                # Пояснение печатается НА ОБОИХ путях, а не только на слиянии:
                # красный исход при взведённой голове иначе выглядит
                # противоречием — «взвёл и покраснел». Нашёл внешний взгляд
                # на #245.
                print("голова взведена, но отказы по головам выше остались — исход красный")
            return EXIT_BROKEN if refused else EXIT_OK
        if state not in STATE_MERGEABLE:
            # Список разрешительный: незнакомое состояние — повод пропустить
            # голову, а не звать слияние наугад. Отказ площадки на `unknown`
            # уронил бы весь заход вместо одной головы.
            print(f"#{change.number}: состояние «{state or '—'}» слияния не допускает, пропущено")
            skipped[f"в состоянии «{state or '—'}»"] += 1
            continue

        # Значок остаётся у ОДНОЙ головы и на этом пути тоже: иначе мы сливаем
        # старшего, а площадка следом сливает взведённого соседа — даже если
        # между ними по нашему порядку стоял третий.
        keep_only(repo, change, queue, owner_token, dry_run=dry_run)
        if change.armed:
            # Взведение снимается ПЕРЕД своим слиянием: у мутации обратная
            # сторона, и брошенное согласие пережило бы слитое изменение в
            # чужих глазах — площадка помнит его на закрытом.
            take_back(repo, change, "сливаю сам: голова уже зелена", owner_token, dry_run=dry_run)
        sha = merge(repo, change, owner_token, dry_run=dry_run)
        print(f"слито #{change.number}{f' → {sha}' if sha else ''}")
        if refused:
            print("заход отработал, но отказы по головам выше остались — исход красный")
        # Отметка пунктов задачи здесь БЫЛА и отсюда ушла. Момент верный —
        # пункт становится сделанным ровно при слиянии, — но предмет чужой:
        # очередь про слияние, а не про чужие задачи, и второй предмет делал её
        # ответственной за то, чего она не решает. Отмечает шаг `task-items`:
        # он идёт по тому же событию и вдобавок догоняет пропущенное обходом
        # окна (022).
        return EXIT_BROKEN if refused else EXIT_OK

    if refused:
        print(f"взвести не удалось ни одну голову: отказов {len(refused)}")
        return EXIT_BROKEN
    why = ", ".join(f"{count} {said}" for said, count in sorted(skipped.items()))
    print(f"готовой головы нет: {why}" if why else "готовой головы нет: кандидатов не осталось")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа: двигает очередь на один шаг и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base", default=paths.TRUNK, help="общая ветка")
    parser.add_argument("--dry-run", action="store_true", help="показать, но не сливать")
    args = parser.parse_args(argv)

    owner_token = token()
    if not owner_token:
        print(
            f"не настроено: нет токена владельца ({ENV_TOKEN}).\n"
            "Слияние придётся сделать руками. На токен прогона шаг не переходит\n"
            "намеренно: автором слияния стало бы приложение (131).",
            file=sys.stderr,
        )
        return EXIT_NOT_CONFIGURED
    if not args.repo:
        print("шаг не отработал: не назван репозиторий", file=sys.stderr)
        return EXIT_BROKEN

    try:
        return advance(args.repo, owner_token, args.base, dry_run=args.dry_run)
    except (NotRun, labels.BadConfig, policy.BadPolicy, squash_body.NotRun) as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except ghrest.TransportError as exc:
        print(f"шаг не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
