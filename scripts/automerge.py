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
import sys
from dataclasses import dataclass, field, replace
from typing import Any, Final

import arm
import changerefs
import ci_complete
import ghrest
import labels
import paths
import pipeline_checks as policy
import report
import squash_body

#: Метки — вход механизма, а не украшение (064). Имена здесь — то, что читает
#: очередь; ОБЪЯВЛЕНЫ они в составе, и совпадение сверяется перед заходом.
LABEL_AUTOMERGE: Final = "automerge"
LABEL_HOLD: Final = "hold"
LABEL_BLOCKER: Final = "blocker"
LABEL_FIX_MAIN: Final = "fix-main"
READ_LABELS: Final = (LABEL_AUTOMERGE, LABEL_HOLD, LABEL_BLOCKER, LABEL_FIX_MAIN)
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
        """Остановлено ли изменение меткой, сколько бы зелёного на нём ни было."""
        return LABEL_HOLD in self.marks


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
) -> None:
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
        return
    if dry_run:
        print(f"  (пробный заход) #{change.number}: метка стала бы «{wanted}»")
        return
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


def files_of(repo: str, number: int, owner_token: str) -> frozenset[str]:
    """Пути, тронутые изменением: по ним видно пересечение с соседом (133)."""
    path = f"repos/{repo}/pulls/{number}/files"
    return frozenset(str(item.get("filename", "")) for item in ghrest.paginate(path, owner_token))


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


def merge_state(repo: str, number: int, owner_token: str) -> str:
    """Состояние слияния у головы очереди.

    Читается ТОЛЬКО у головы (052): площадка считает его лениво, и спрашивать
    его у всех значит заказывать вычисление, которое никому не понадобится.
    """
    payload = ghrest.request("GET", f"repos/{repo}/pulls/{number}", owner_token) or {}
    return str(payload.get("mergeable_state") or "")


def sync_head(repo: str, number: int, owner_token: str, *, dry_run: bool) -> None:
    """Подтягивает базу в голову очереди — и только в неё."""
    if dry_run:
        print(f"  (пробный заход) база подтянулась бы в #{number}")
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
        print(f"  (пробный заход) слилось бы #{change.number} телом:\n{body}")
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
        print(f"  (пробный заход) взвёл бы #{change.number} телом:\n{body}")
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
    print(f"остановлено меткой «{LABEL_HOLD}»: {len(held)}")
    for change in held:
        print(f"  #{change.number} — {change.title}")


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
) -> dict[int, tuple[list[str], bool]]:
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
    print(f"кандидатов: {len(queue)}")
    for place, change in enumerate(queue, start=1):
        problems, waiting = head_verdict(repo, change, owner_token)
        verdicts[change.number] = (problems, waiting)
        source = source_of(change, bool(problems))
        print(f"  {place}. #{change.number} [{RANK_NAMES[source]}] — {change.title}")
        publish_source(repo, change, source, owner_token, dry_run=dry_run)
    return verdicts


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
    verdicts = classify(repo, queue, owner_token, dry_run=dry_run)

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

    for change in queue:
        problems, _ = verdicts[change.number]
        if problems:
            # Красное вернуло изменение в контур 1 источником 2 ещё разметкой,
            # а очередь идёт дальше: одна красная голова не обязана держать
            # остальных.
            print(
                f"#{change.number} [{RANK_NAMES[RANK_OWN_RED]}]: пропущено — {'; '.join(problems)}"
            )
            continue

        state = merge_state(repo, change.number, owner_token)
        if state == STATE_BEHIND:
            print(f"#{change.number}: голова очереди отстала от базы — подтягиваю только её (052)")
            sync_head(repo, change.number, owner_token, dry_run=dry_run)
            return EXIT_OK
        if state == STATE_CONFLICT:
            print(
                f"#{change.number} [{RANK_NAMES[RANK_CONFLICT]}]: штатный источник работы "
                "(004), очередь идёт дальше"
            )
            publish_source(repo, change, RANK_CONFLICT, owner_token, dry_run=dry_run)
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
    print("готовой головы нет: все кандидаты либо красны, либо конфликтуют")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа: двигает очередь на один шаг и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base", default="main", help="общая ветка")
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
