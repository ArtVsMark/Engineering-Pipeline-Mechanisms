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
в контур 1 источником 2. Ничего не замораживается и никто не будится: авария
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
from dataclasses import dataclass, field
from typing import Any, Final

import ci_complete
import ghrest
import labels
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

ENV_TOKEN: Final = "MERGE_QUEUE_TOKEN"

#: Ступени очереди. Меньше — раньше; внутри ступени решает номер изменения.
RANK_FIX_MAIN: Final = 0
RANK_BLOCKER: Final = 1
RANK_SHARED: Final = 2
RANK_REST: Final = 3

RANK_NAMES: Final = {
    RANK_FIX_MAIN: "чинит общую ветку",
    RANK_BLOCKER: "блокирующее",
    RANK_SHARED: "трогает общий файл",
    RANK_REST: "остальное",
}

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
    draft: bool
    marks: frozenset[str]
    files: frozenset[str] = field(default=frozenset())

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
    missing = [name for name in READ_LABELS if name not in declared]
    if missing:
        raise NotRun(
            f"очередь читает метки, которых нет в составе: {', '.join(missing)} — "
            "вход механизма не найден, и это отказ, а не «кандидатов нет» (064, 075)"
        )


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
                draft=bool(payload.get("draft")),
                marks=marks_of(payload),
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


def rank(change: Change, shared: frozenset[str]) -> int:
    """Ступень очереди для одного изменения.

    Заморозки здесь нет: красная общая ветка решается ОТБОРОМ, а не ступенью.
    Учитывать её и тут значило бы завести ветку, которая в рабочем пути не
    исполняется никогда. Ступень «чинит» первая и на зелёной базе: починка,
    поданная позже, обгоняет готовое раньше.
    """
    if change.fixes_main:
        return RANK_FIX_MAIN
    if LABEL_BLOCKER in change.marks:
        return RANK_BLOCKER
    if change.files & shared:
        return RANK_SHARED
    return RANK_REST


def order(changes: list[Change], shared: frozenset[str]) -> list[Change]:
    """Очередь по правилу; внутри ступени — по номеру изменения."""
    return sorted(changes, key=lambda change: (rank(change, shared), change.number))


def on_the_shared_branch(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставляет записи, которые на общей ветке вообще что-то значат.

    ПОЧЕМУ ПРОПУСК ЗДЕСЬ НЕ ОТКАЗ, ХОТЯ НА ГОЛОВЕ ИЗМЕНЕНИЯ — ОТКАЗ. Предмет у
    части проверок — изменение, а не общая ветка: разметка, фрагмент журнала и
    авторство коммитов на `main` проверять не на чем. Такие джобы объявлены
    change-only условием `if: github.event_name != 'push'` и на общей ветке
    кладут запись с исходом `skipped`. Считать её отказом — значит объявить
    общую ветку красной ВСЕГДА.

    Цена ошибки была ровно такой: замер 09.09.2026 — очередь на первом живом
    прогоне сообщила «общая ветка красна» по трём пропускам и не сдвинулась.
    Нашёл это прогон, а не набор — механизм подтверждается прогоном, а не чтением
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

    Послабление держится не обещанием: то, что change-only джобы объявлены
    условием, а не выключены руками, проверяет
    `tests/test_gates_contract.py::test_change_only_jobs_do_not_run_on_the_shared_branch`.
    Пропуск на голове ИЗМЕНЕНИЯ остаётся отказом (040) — здесь другая ветка и
    другой предмет.
    """
    return [run for run in runs if run.get("conclusion") != "skipped"]


def severity(run: dict[str, Any]) -> int:
    """Насколько плоха одна запись. Больше — хуже; отменённая ниже любой живой."""
    conclusion = run.get("conclusion")
    # «Идёт» решается общим разбором, а не своим: запись со `status:
    # in_progress` и уже проставленным исходом завершена, и ждать её вечно.
    if ci_complete.pending(run):
        return 1
    if conclusion == "cancelled":
        return -1
    if conclusion == "success":
        return 0
    if conclusion == "skipped":
        return 2
    return 3


def worst_per_name(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставляет по одной, САМОЙ ПЛОХОЙ записи на имя.

    ПОЧЕМУ НЕ «НЕОДНОЗНАЧНОСТЬ». Сводный гейт, увидев две живые записи одного
    имени, объявляет вердикт неоднозначным — и правильно делает: он опрашивает
    голову изнутри своего же прогона и различает своё от чужого по номеру
    прогона. У очереди своего прогона среди них нет: она приходит снаружи и
    видит два прогона `ci` на одной голове — штатное следствие двух событий
    (толчок и навешенная метка), а не спор механизмов. Замер 09.09.2026: на
    первом живом заходе очередь отвергла изменение #57 с шестью зелёными
    именами, потому что каждое было представлено дважды.

    ПОЧЕМУ ХУДШАЯ, А НЕ ЛЮБАЯ. Взять первую попавшуюся значило бы иногда
    сливать красное: из двух записей одного имени зелёная попадалась бы
    первой. Худшая делает разбор строже сводного гейта, а не мягче, — и это
    единственная сторона, в которую здесь можно ошибаться
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

    Отменённая запись ниже любой живой: она пройденной не считается, но и
    отказом становится только тогда, когда живой у имени нет вовсе.
    """
    best: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = str(run.get("name", ""))
        current = best.get(name)
        if current is None or severity(run) > severity(current):
            best[name] = run
    return list(best.values())


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
    problems, _ = ci_complete.verdict(
        worst_per_name(on_the_shared_branch(runs)), required, "", strict_missing=False
    )
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
    return ci_complete.verdict(worst_per_name(runs), required, "", strict_missing=True)


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


def report_held(changes: list[Change]) -> None:
    """Называет остановленное меткой: отменяющий переключатель нужен адресату.

    Полного адресата у забытого ``hold`` пока нет — им станет шаг 11, — и это
    названо пробелом в AGENTS.md, а не выровнено молчанием (046, 147).
    """
    held = [change for change in changes if change.held and LABEL_AUTOMERGE in change.marks]
    if not held:
        return
    print(f"остановлено меткой «{LABEL_HOLD}»: {len(held)}")
    for change in held:
        print(f"  #{change.number} — {change.title}")


def advance(repo: str, owner_token: str, base: str, *, dry_run: bool) -> int:
    """Один заход очереди: читает, упорядочивает и двигает ГОЛОВУ."""
    check_labels_declared()
    changes = open_changes(repo, owner_token)
    report_held(changes)

    queue = candidates(changes, base)
    if not queue:
        print("очередь пуста: слияния никто не просит — это состояние, а не отказ")
        return EXIT_OK

    base_sha = str(
        (ghrest.request("GET", f"repos/{repo}/commits/{base}", owner_token) or {}).get("sha", "")
    )
    if not base_sha:
        raise NotRun(f"голова общей ветки «{base}» не прочитана — двигать очередь не на что")

    troubles = branch_health(repo, base_sha, owner_token)
    base_red = bool(troubles)
    if base_red:
        print("общая ветка красна — очередь заморожена, кроме починки:")
        for trouble in troubles:
            print(f"  {trouble}")
        queue = [change for change in queue if change.fixes_main]
        if not queue:
            print(f"изменения с меткой «{LABEL_FIX_MAIN}» нет — не двигается ничего")
            return EXIT_OK

    queue = [
        Change(
            number=change.number,
            branch=change.branch,
            base=change.base,
            head=change.head,
            title=change.title,
            draft=change.draft,
            marks=change.marks,
            files=files_of(repo, change.number, owner_token),
        )
        for change in queue
    ]
    shared = shared_paths(queue)
    queue = order(queue, shared)

    print(f"кандидатов: {len(queue)}")
    for place, change in enumerate(queue, start=1):
        step = RANK_NAMES[rank(change, shared)]
        print(f"  {place}. #{change.number} [{step}] — {change.title}")

    for change in queue:
        problems, waiting = head_verdict(repo, change, owner_token)
        if waiting:
            print(f"#{change.number}: проверки ещё идут — очередь ждёт голову, а не обходит её")
            return EXIT_OK
        if problems:
            # Красное возвращает изменение в контур 1 источником 2, а очередь
            # идёт дальше: одна красная голова не обязана держать остальных.
            print(f"#{change.number}: не готово, пропущено — {'; '.join(problems)}")
            continue

        state = merge_state(repo, change.number, owner_token)
        if state == STATE_BEHIND:
            print(f"#{change.number}: голова очереди отстала от базы — подтягиваю только её (052)")
            sync_head(repo, change.number, owner_token, dry_run=dry_run)
            return EXIT_OK
        if state == STATE_CONFLICT:
            print(
                f"#{change.number}: конфликт — штатный источник работы (004), очередь идёт дальше"
            )
            continue
        if state not in STATE_MERGEABLE:
            # Список разрешительный: незнакомое состояние — повод пропустить
            # голову, а не звать слияние наугад. Отказ площадки на `blocked`
            # или `unknown` уронил бы весь заход вместо одной головы.
            print(f"#{change.number}: состояние «{state or '—'}» слияния не допускает, пропущено")
            continue

        sha = merge(repo, change, owner_token, dry_run=dry_run)
        print(f"слито #{change.number}{f' → {sha}' if sha else ''}")
        return EXIT_OK

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
