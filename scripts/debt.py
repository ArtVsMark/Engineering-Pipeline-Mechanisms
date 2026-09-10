#!/usr/bin/env python3
"""Долг, который идёт перед планом: находки и незакрытая работа по правилам.

Порядок источников работы — `docs/behaviour.md`, контур 1. Перед новой работой
стоят два долга, и оба по УЖЕ сделанному:

* **находки внешнего взгляда, пережившие слияние** — часть работы, помеченной
  закрытой, не сделана
  ([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md));
* **незакрытая работа по правилам каталога** — правило без ответа, правило
  «действует, но не держится ничем», разошедшийся контракт с неперечитанными
  ответами. Этого требует сам каталог
  ([177](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/177-unfinished-rule-work-comes-first.md)).

РЯДОМ ПЕЧАТАЕТСЯ ТРЕТЬЕ ЧИСЛО, И ОНО НЕ ДОЛГ, А МЕРА. Слитое без внешнего
взгляда (`unlooked`) говорит, сколько работы прошло мимо совещательного канала.
Приоритет перед планом оно не даёт: посмотреть слитое заново можно, обязанности
сделать это до новой работы нет. Но и в невидимое это уходить не должно —
именно из невидимости растёт привычка считать, что взгляд был.

ЧИСЛА ЗДЕСЬ НЕ СЧИТАЮТСЯ, А ЧИТАЮТСЯ. По правилам их считает ночной прогон
действия каталога и кладёт в задачу-«входящие»; по находкам — механизм ревью в
свою живую задачу. Второй счёт того же разошёлся бы с первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)),
и разошёлся бы незаметно: оба числа выглядят одинаково правдоподобно.

Шаг **не краснеет от долга**: красное здесь стало бы проверкой, которую
приучаются обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)),
а долг бывает больше одного изменения. Его дело — не пускать долг в невидимое.

Исходы (правило 039): ``0`` остаток прочитан и напечатан · ``2`` не отработало ·
``3`` источник не прочитан — сказано, а не выдано за «долга нет».
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import ci_complete
import findings
import ghrest
import items
import items_left
import main_red
import report
import unlooked

#: Строка, которую пишет ночной прогон каталога. Три числа правила 177 в одном
#: месте — читаются целиком, а не собираются заново.
STATS_RE: Final = re.compile(
    r"Задач по правилам:\s*(\d+)\..*?«не рассмотрено»:\s*(\d+)\..*?держится ничем:\s*(\d+)",
    re.S,
)
CONTRACT_RE: Final = re.compile(r"\*\*Контракт разошёлся\.\*\*\s*(.+)")

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_PARTIAL: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «долга нет»."""


def rules_debt(body: str) -> tuple[int, int, int] | None:
    """Три числа правила 177 из задачи-«входящие»: задачи, очередь, «ничем»."""
    match = STATS_RE.search(body or "")
    if match is None:
        return None
    tasks, queue, unheld = (int(value) for value in match.groups())
    return tasks, queue, unheld


def contract_note(body: str) -> str | None:
    """Расхождение контракта каталога, если оно объявлено во «входящих»."""
    match = CONTRACT_RE.search(body or "")
    return match.group(1).strip() if match else None


def findings_debt(repo: str, token: str) -> list[tuple[str, int, str]]:
    """Неразобранные находки из живой задачи-адресата."""
    _, body = findings.live_issue(repo, token)
    return [
        (mark, entry.pr, f"[{entry.weight}] {entry.title}")
        for mark, entry in findings.parse_entries(body).items()
    ]


def unlooked_debt(repo: str, token: str) -> list[unlooked.Entry]:
    """Слитое без внешнего взгляда — из реестра, где его ведёт свой механизм.

    Третий долг ЧИТАЕТСЯ так же, как два первых: его считает `unlooked` в свою
    живую задачу, а здесь только берётся готовое число
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    _, body = findings.live_issue(repo, token, unlooked.MARKER)
    return [
        entry
        for entry in unlooked.parse_entries(body).values()
        if entry.state in unlooked.OPEN_STATES
    ]


def branch_debt(repo: str, token: str) -> tuple[list[str], list[str]]:
    """Краснота общей ветки из задачи, которую ведёт шаг 9.

    Возвращает раздельно: держащее слияние (источник 0) и не держащее
    (источник 3). Числа ЧИТАЮТСЯ, а не пересчитываются: считает их `main_red`
    по живым артефактам, и второй счёт того же разошёлся бы с первым молча
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    _, body = findings.live_issue(repo, token, main_red.MARKER)
    return section(body, "Держит слияние"), section(body, "Не держит слияние")


def section(body: str | None, title: str) -> list[str]:
    """Имена проверок из одного раздела задачи о красноте."""
    text = body or ""
    start = text.find(f"## {title}")
    if start < 0:
        return []
    end = text.find("\n## ", start + 1)
    piece = text[start : end if end > 0 else len(text)]
    return [line[4:-2].strip() for line in piece.splitlines() if line.startswith("- **")]


#: Состояние задачи-«входящие», когда её закрыл прогон каталога. Числа в ней
#: остаются последними, что каталог сказал: закрытие говорит «я посмотрел», а
#: не «долга нет» — в закрытой #37 на 10.09.2026 лежала единица по третьему виду.
CLOSED_INBOX: Final = "«входящие» закрыты — числа от последнего захода каталога"


#: После скольких часов снимок каталога считается вчерашним. Ночной прогон
#: каталога ходит раз в сутки (6:17), поэтому суточный возраст нормален, а
#: больший означает ПРОПУЩЕННЫЙ заход — не «немного устарело», а «один раз не
#: пришло». Запас в два часа — на разброс времени старта у площадки.
STALE_AFTER: Final = timedelta(hours=26)
#: Что шаг делает со снимком старше срока: называет возраст и продолжает.
#: Отказываться читать вчерашние числа нельзя — они последнее, что каталог
#: сказал, и «неизвестно» вместо них строже, чем правда (051). Молчать о
#: возрасте тоже нельзя: вчерашнее число, поданное как сегодняшнее, — это
#: утверждение на все времена (005).
STALE_NOTE: Final = "числам больше суток — ночной заход каталога, похоже, пропущен"


def age_of(seen: str, now: datetime | None = None) -> timedelta | None:
    """Сколько прошло с последней правки задачи; ``None`` — дата не разобралась.

    Не ноль и не «свежо»: неразобранная дата означает, что возраст НЕИЗВЕСТЕН,
    и выдавать его за свежесть — тихий запасной ответ (045).
    """
    try:
        stamp = datetime.fromisoformat(seen.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (now or datetime.now(UTC)) - stamp


def said_age(age: timedelta | None) -> str:
    """Возраст снимка словами — рядом с числами, а не в задаче.

    ЗАЧЕМ ВСЛУХ. Числа правила 177 считает чужой прогон, и читаются они как
    сегодняшние. Замер 10.09.2026: разрез приоритета строился по сводке семьи
    семичасовой давности и назвал восемь правил документами, когда они уже
    держались гейтами, — список заимствований по ним вышел неверным.
    """
    if age is None:
        return "возраст снимка неизвестен: дата не разобралась"
    hours = int(age.total_seconds() // 3600)
    said = f"снято {hours} ч назад" if hours else "снято меньше часа назад"
    return f"{said} · {STALE_NOTE}" if age > STALE_AFTER else said


def inbox_body(repo: str, token: str) -> tuple[str, str, str]:
    """Тело задачи-«входящие» и пометка о её состоянии.

    ПОЧЕМУ НЕ ТОЛЬКО ЖИВАЯ. Живой считается открытая задача, а «входящие»
    закрывает прогон каталога — 10.09.2026 в 11:22 он это и сделал. С той
    минуты шаг долга читал «числа не найдены» и объявлял долг по правилам
    НЕИЗВЕСТНЫМ на каждом изменении: совещательный канал говорил о поломке там,
    где было штатное состояние, а такое красное учат пролистывать (045, 142).

    Закрытая читается ТОЛЬКО если открытой нет: открытая всегда свежее.
    """
    number, body, seen = findings.live_issue_seen(repo, token, findings.INBOX_MARKER)
    if number is not None:
        return body, "", seen
    found: list[tuple[int, str, str]] = []
    for issue in ghrest.paginate(f"repos/{repo}/issues?state=closed", token):
        if issue.get("pull_request") is not None:
            continue
        said = str(issue.get("body") or "")
        if findings.INBOX_MARKER in said:
            found.append((int(issue["number"]), said, str(issue.get("updated_at") or "")))
    if not found:
        return "", "", ""
    newest = max(found)
    return newest[1], CLOSED_INBOX, newest[2]


def stuck_changes(repo: str, token: str) -> tuple[list[str], list[str]]:
    """Свои открытые изменения, застрявшие: конфликтом и красным.

    ПОЧЕМУ ЭТО ДОЛГ, И ПРИТОМ ПЕРВЫЙ. Источники 1 и 2 контура 1 — конфликт на
    своём изменении и красная проверка на нём — стоят выше находок, правил и
    плана. Механизма у них до сих пор не было: их видел только тот, кто откроет
    список изменений глазами, и открытое красное висело, пока о нём не спросят.
    Живой случай 10.09.2026: изменение с починкой ревью простояло красным час,
    и заметил это владелец, а не конвейер.

    ПОЧЕМУ ЗДЕСЬ, А НЕ ТРЕВОГОЙ. Тревога о застрявшем — предмет службы
    наблюдения (`docs/decisions/004-schedules-stay-service-observes.md`), и
    строить её здесь значило бы делать работу дважды. Но ЧИТАТЬ своё состояние
    окно обязано само: долг перед планом — это не тревога, а порядок работ
    ([091](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/091-work-sources-are-ordered-first-non-empty-wins.md)).

    Возвращает раздельно: конфликтующие (источник 1) и красные (источник 2).
    Свалить их в одно число значило бы стереть разницу между «база устарела» и
    «работа не работает» (154).
    """
    conflicting: list[str] = []
    red: list[str] = []
    for change in ghrest.request("GET", f"repos/{repo}/pulls?state=open&per_page=50", token) or []:
        number = int(change.get("number") or 0)
        title = str(change.get("title") or "")[:60]
        said = f"#{number} — {title}"
        if change.get("draft"):
            # Черновик застрять не может: он и не подан.
            continue
        if str(change.get("mergeable_state") or "") == "dirty":
            conflicting.append(said)
            continue
        runs = list(
            ghrest.paginate(
                f"repos/{repo}/commits/{change['head']['sha']}/check-runs", token, key="check_runs"
            )
        )
        if not runs:
            continue
        worst = ci_complete.worst_per_name(runs)
        if any(str(one.get("conclusion") or "") == "failure" for one in worst):
            red.append(said)
    return conflicting, red


def open_issues(repo: str, token: str) -> list[dict[str, Any]]:
    """Открытые задачи без изменений — общий вход обоих счётов по пунктам.

    Список читается ОДИН раз: два прохода по одному источнику расходятся тем
    охотнее, чем невиннее выглядят, и расходятся молча (022).
    """
    return [
        issue
        for issue in ghrest.paginate(f"repos/{repo}/issues?state=open", token)
        if issue.get("pull_request") is None
    ]


def looks_done(issues: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Задачи, у которых пункты есть и все закрыты, а сама задача открыта.

    ПОЧЕМУ ЭТО ВООБЩЕ НУЖНО. Пункты отмечает механизм, а закрывает задачу
    человек — и это верно: «сделано» и «надоело» механизму неразличимы (154).
    Но состояние «все пункты закрыты, а задача открыта» до сих пор не видел
    НИКТО: `task_items` его прямо вычисляет и наружу об этом молчит. Живой
    случай 10.09.2026 — #26 и #25 простояли готовыми до вопроса владельца, и
    сколько именно, сказать нечем: этого никто не мерил.

    ЭТО СЧЁТ, А НЕ ПРИКАЗ. Механизм называет кандидата и не закрывает ничего:
    пункты не обязаны покрывать всю работу.

    ЗАДАЧА БЕЗ ПУНКТОВ КАНДИДАТОМ НЕ СЧИТАЕТСЯ. Пустой чек-лист — это не «всё
    сделано», а «этапов не называли»: у #25 пунктов не было вовсе, и
    автоматическое «готова» стояло бы на ней с первого дня.
    """
    ready: list[tuple[int, str]] = []
    for issue in issues:
        body = str(issue.get("body") or "")
        if items.open_items(body) or not items.done_items(body):
            continue
        ready.append((int(issue["number"]), str(issue.get("title") or "")))
    return sorted(ready)


def rules_left(numbers: tuple[int, int, int] | None, note: str | None) -> bool:
    """Есть ли незакрытая работа по правилам — по ТРЁМ видам 177, а не по счёту задач.

    Первое из трёх чисел — сколько задач по правилам заведено в трекере, и
    долгом оно не является: задача может быть открыта и разобрана, а долг —
    это правило без ответа, правило «действует и не держится ничем» и
    разошедшийся контракт. Считать долгом любое ненулевое из трёх значило
    объявлять долг ВСЕГДА: задачи по правилам у проекта есть постоянно, и
    напоминание в таком виде перестаёт что-либо значить (051).

    Третий вид — расхождение контракта — печатался, но в решение не входил
    ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)):
    поднявшийся контракт означает, что ответы надо перечитать, и молчать об
    этом нельзя.

    Числа не прочитаны — долг НЕИЗВЕСТЕН, а не равен нулю (045): неизвестность
    считается долгом, потому что снимать приоритет с непроверенного источника
    хуже, чем напомнить лишний раз.
    """
    if numbers is None:
        return True
    _, queue, unheld = numbers
    return bool(queue or unheld or note)


def remind(has_debt: bool) -> None:
    """Ведёт к договору, а не пересказывает его."""
    if has_debt:
        print(
            "\nЭто идёт ПЕРЕД планом: docs/behaviour.md, контур 1, источники 3 и 5.\n"
            "Правило каталога — 177: пока незакрытая работа по правилам есть, новую не начинают."
        )
    else:
        print("\nдолга нет: оба источника пусты, работа берётся по плану")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает остаток долга и возвращает исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)

    token = ghrest.token_from_env()
    if not token or not args.repo:
        print(
            "остаток не прочитан: нет токена или репозитория. Долг НЕИЗВЕСТЕН — это\n"
            "сказано, а не выдано за «долга нет» (045).",
            file=sys.stderr,
        )
        # Напоминание печатается и здесь: окно, увидевшее «не прочитано»,
        # должно знать, где записан порядок, — иначе оно решит за себя само.
        remind(True)
        return EXIT_PARTIAL

    try:
        left = findings_debt(args.repo, token)
        unlooked_left = unlooked_debt(args.repo, token)
        holding, lagging = branch_debt(args.repo, token)
        inbox, inbox_note, inbox_seen = inbox_body(args.repo, token)
        conflicting, red = stuck_changes(args.repo, token)
        # Список задач читается ОДИН раз на оба счёта по пунктам: два прохода
        # по одному источнику расходятся тем охотнее, чем невиннее выглядят (022).
        issues = open_issues(args.repo, token)
        ready = looks_done(issues)
        built, quiet = items_left.look(issues, items.open_items)
    except ghrest.TransportError as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # СВОИ ЗАСТРЯВШИЕ ИЗМЕНЕНИЯ ПЕЧАТАЮТСЯ ПЕРВЫМИ, потому что они и есть
    # первые источники: 1 — конфликт, 2 — красное на своём. Всё остальное ниже
    # по порядку контура 1, и порядок вывода повторяет его намеренно (091).
    if conflicting:
        print(f"конфликт на своих изменениях: {len(conflicting)} — это источник 1")
        for said in conflicting:
            print(f"  {said}")
    if red:
        print(f"красное на своих изменениях: {len(red)} — это источник 2")
        for said in red:
            print(f"  {said}")

    print(f"находки, пережившие слияние: {len(left)}")
    for mark, pr, title in left:
        print(f"  {mark} · #{pr} — {title}")

    # ТРЕТИЙ ДОЛГ ПЕЧАТАЕТСЯ, НО НАПОМИНАНИЯ НЕ ВКЛЮЧАЕТ. Слитое без взгляда —
    # мера того, сколько прошло мимо канала, а не список работы: посмотреть
    # заново можно, но обязанности сделать это до новой работы нет, и
    # напоминание, звучащее всегда, перестаёт что-либо значить (051). Число
    # видно, решение — за человеком (154).
    # КРАСНОТА ОБЩЕЙ ВЕТКИ ПЕЧАТАЕТСЯ ДВУМЯ СТРОКАМИ, А НЕ ОДНОЙ. Держащее
    # слияние — источник 0: очередь заморожена, и это не «долг перед планом», а
    # стоп. Не держащее — источник 3: работа помечена закрытой и частью не
    # работает. Свалить их в одно число значило бы стереть разницу между
    # простоем и долгом (154).
    if holding:
        print(f"общая ветка красна, слияние стоит: {len(holding)} — это источник 0")
        for name in holding:
            print(f"  {name}")
    if lagging:
        print(f"совещательные красные на общей ветке: {len(lagging)} — источник 3")
        for name in lagging:
            print(f"  {name}")

    # ГОТОВОЕ ПЕЧАТАЕТСЯ РЯДОМ С ДОЛГОМ, НО ДОЛГОМ НЕ ЯВЛЯЕТСЯ. Это не работа,
    # которую надо сделать, а работа, которую, возможно, уже сделали и забыли
    # закрыть. Приоритета перед планом не даёт и напоминания не включает:
    # решение — за человеком (154).
    if ready:
        print(f"выглядят готовыми к закрытию: {len(ready)} — все пункты закрыты")
        for number, title in ready:
            print(f"  #{number} — {title}")

    # СЧЁТ ПО ПУНКТАМ ПЕЧАТАЕТСЯ ВСЕГДА, А НЕ ТОЛЬКО КОГДА НАШЁЛ. Строка,
    # появляющаяся лишь при находке, не отличима от невключённого механизма, и
    # «вежливо выключен» выглядит снаружи как «чисто» (142). Ноль здесь —
    # ответ, а не молчание.
    print(f"открытых пунктов с готовой работой: {len(built)}")
    for candidate in built:
        print(f"  #{candidate.number} · {', '.join(candidate.evidence)}")
        print(f"      {report.cut(' '.join(candidate.item.split()), 120)}")
    print(f"задач с открытыми пунктами и без событий: {len(quiet)}")
    for task in quiet:
        print(f"  #{task.number} — {task.title} · {task.days} дн · пунктов {task.left}")

    print(f"слито без внешнего взгляда: {len(unlooked_left)}")
    for entry in sorted(unlooked_left, key=lambda item: -item.number):
        print(f"  #{entry.number} · {entry.state} · {entry.merged}")

    partial = False
    numbers = rules_debt(inbox)
    note = contract_note(inbox)
    if numbers is None:
        partial = True
        print(
            "правила: «входящие» не найдены или без строки счёта — ночной прогон каталога\n"
            "не отработал. Долг по правилам НЕИЗВЕСТЕН, а не равен нулю (045, 075).",
            file=sys.stderr,
        )
    else:
        tasks, queue, unheld = numbers
        print(
            f"правила (считает каталог): задач {tasks}, без ответа {queue}, держится ничем {unheld}"
        )
        # ВОЗРАСТ ПЕЧАТАЕТСЯ ВСЕГДА, А НЕ ТОЛЬКО КОГДА ОН ПЛОХОЙ. Строка,
        # появляющаяся лишь при беде, читается как беда; строка, стоящая
        # всегда, делает свежесть видимой величиной, а не предположением.
        print(f"  {said_age(age_of(inbox_seen))}")
        if inbox_note:
            print(f"  {inbox_note}")
    # Расхождение контракта печатается и тогда, когда счёта нет: это отдельный
    # вид долга, и от строки со счётом он не зависит.
    if note:
        print(f"  контракт разошёлся: {note}")

    # Совещательное красное общей ветки входит в долг перед планом; держащее
    # слияние — нет: оно не долг, а остановка, и решается оно починкой, а не
    # порядком работ.
    remind(bool(left) or bool(lagging) or rules_left(numbers, note))
    return EXIT_PARTIAL if partial else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
