#!/usr/bin/env python3
"""Шаг 11: изменение готово и НЕ СЛИТО — заход называет, чем именно оно стоит.

ПРЕДМЕТ — НЕ «ВИСИТ ДОЛЬШЕ N». Срок здесь не признак застревания, а защита от
ложного крика: изменение, открытое минуту назад, стоит законно. Признак —
состояние: обязательной проверки не создано вовсе, событие не дошло, значок
слияния не выдан, значок выдан и слияния нет. Каждое из них снаружи выглядит
одинаково — «открытое зелёное изменение», — и различает их только опрос.

СОСЕД НАЗВАН, ЧТОБЫ ГРАНИЦА НЕ ПОЛЗЛА (195). Оклик (`scripts/hail.py`) берёт
изменения со СВОИМ красным и с конфликтом: там есть кому работать, и работа
называется. Здесь ровно те, кого оклик пропускает, — зелёные, без конфликта, и
всё равно стоящие. Пересечения между шагами нет по построению: каждое живое
изменение попадает ровно к одному из двух.

ЗАЧЕМ ВООБЩЕ. Замеры семьи по этому месту дали три инцидента за двое суток, и
все — «обязательной проверки не создавалось вовсе»: событие потерялось, а
защита ветки ждала вердикт, которого не будет. Красное при этом не появляется
нигде: краснеть нечему. Именно поэтому шаг спрашивает ОТСУТСТВИЕ записи, а не
её исход ([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md),
[075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

ПОЧЕМУ БЕЗ РАСПИСАНИЯ. Наблюдение и тревога — предмет службы, а не площадки
(`docs/decisions/004-schedules-stay-service-observes.md`). Заход идёт по
завершении прогона гейтов и обходит ВСЕ живые изменения сразу: застревание
соседа обнаруживается чужим прогоном, потому что собственного у застрявшего
как раз и нет.

Исходы (правило 039): ``0`` застрявших нет · ``1`` застрявшее найдено ·
``2`` заход не отработал · ``3`` токен владельца не задан — обход был бы слепым.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import findings
import ghrest
import pipeline_checks as policy
import report

#: Токен владельца: состояние слияния площадка считает только тому, кто им
#: располагает, — то же выяснилось прогоном у оклика, а не чтением.
ENV_TOKEN: Final = "MERGE_QUEUE_TOKEN"

EXIT_OK: Final = 0
EXIT_STUCK: Final = 1
EXIT_BROKEN: Final = 2
EXIT_UNSET: Final = 3

#: Метка согласия на слияние и стоп-метка — те же имена, что читает очередь.
CONSENT: Final = "automerge"
HOLD: Final = "hold"

TITLE: Final = "Застрявшие изменения: готово и не слито"
MARKER: Final = findings.marker("stuck-prs")

#: Состояние слияния, которого площадка ещё не посчитала.
UNCOMPUTED: Final = frozenset({"", "unknown"})
#: Конфликт — предмет оклика, а не этого шага.
STATE_CONFLICT: Final = "dirty"

#: Записи, ничего не утверждающие о проверке: их наличие не отменяет пропажи.
WITHOUT_VERDICT: Final = frozenset({"cancelled", "skipped"})
#: Исходы, считающиеся пройденными.
PASSED: Final = frozenset({"success", "neutral"})

#: Сколько голова обязана постоять, прежде чем её молчание называют застреванием.
#: Срок отсчитывается от ГОЛОВЫ, а не от открытия изменения: толчок обнуляет
#: ожидание, потому что обнуляет и прогоны
#: ([100](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/100-two-deadlines-start-and-work.md)).
FRESH_MINUTES: Final = 20

#: Почему изменение НЕ застряло — состояние, а не молчание (154). Список
#: закрытый: новое состояние обязано получить строку, а не попасть в «прочее».
WHY_DRAFT: Final = "черновик — готовым не объявлен"
WHY_HOLD: Final = "остановлено меткой «hold» — стоп-кран стоит осознанно"
WHY_HOLD_LIFTED: Final = "стоп-кран снят: названного больше нет смысла ждать"
WHY_UNCOMPUTED: Final = "состояние слияния ещё не посчитано площадкой"
WHY_NEIGHBOUR: Final = "своё красное или конфликт — это предмет оклика, а не шага 11"
WHY_RUNNING: Final = "проверки идут"
WHY_NO_CONSENT: Final = "согласия на слияние нет — изменение в очередь не просилось"
WHY_FRESH: Final = "голова моложе срока — стоять ей пока законно"

#: Чем изменение застряло. Каждая причина называет СВОЮ починку: свести их к
#: одному «стоит» значит отправить человека искать не там (154).
STUCK_NO_RUNS: Final = "записей проверок на голове нет вовсе — событие не дошло"
STUCK_MISSING: Final = "обязательная проверка объявлена, но на голове не создана"
STUCK_UNARMED: Final = "зелено и согласие есть, а значок слияния не выдан"
STUCK_ARMED: Final = "значок выдан, всё зелено, а слияния нет"
STUCK_HOLD_MUTE: Final = "стоп-метка не называет, чего ждёт — отменяющий переключатель без адресата"

#: Чего ждёт стоп-метка — строкой в теле изменения (решение 018). Номер,
#: а не свободный текст: спрашивать у площадки можно только разрешимый адрес.
WAITS_RE: Final = re.compile(r"^Ждёт:\s*(?P<said>.+?)\s*$", re.MULTILINE)
#: Разрешимая форма названного: «#262».
SUBJECT_RE: Final = re.compile(r"^#(?P<number>\d+)$")


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не «застрявших нет» (039)."""


@dataclass(frozen=True, slots=True)
class Verdict:
    """Что заход решил об одном изменении и почему.

    ПРИЧИНА ЕСТЬ ВСЕГДА, и у «не застряло» тоже: молчание о здоровом
    неотличимо от того, что изменение не смотрели вовсе (154).
    """

    number: int
    stuck: bool
    why: str
    missing: tuple[str, ...] = ()
    #: Снять ли стоп-метку: названное ею закрыто, ждать больше нечего (018).
    lift: bool = False

    def said(self) -> str:
        """Строка реестра: номер, причина и — если пропажа — чьи имена."""
        names = f" ({', '.join(self.missing)})" if self.missing else ""
        return f"- #{self.number} — {self.why}{names}"


def waits_for(body: str) -> str:
    """Что названо строкой «Ждёт:» — как написано, без разбора смысла.

    Пусто значит «строки нет»: стоп-кран без названного условия и есть предмет
    жалобы, а не пустая строка
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    Читается ПЕРВАЯ строка: две означали бы два условия, а снятие по одному из
    них было бы снятием по половине.
    """
    found = WAITS_RE.search(body or "")
    return found.group("said") if found else ""


def named_subject(said: str) -> int:
    """Номер, если названное разрешимо; ``0`` — если назван свободный текст.

    Ноль здесь не «не нашёл», а ВТОРОЙ исход: причина названа словом, спросить
    её у площадки нечем, и стоп-кран остаётся стоять осознанно (решение 018).
    """
    found = SUBJECT_RE.match(said.strip())
    return int(found.group("number")) if found else 0


def is_settled(repo: str, number: int, token: str) -> bool:
    """Закрыто ли названное. Неспрошенное считается ОТКРЫТЫМ.

    Снятие стоп-крана необратимо в том смысле, что вернуть его может только
    человек, и выводить «закрыто» из «не смог спросить» значит снимать
    чужую остановку по незнанию
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    try:
        got = ghrest.request("GET", f"repos/{repo}/issues/{number}", token) or {}
    except ghrest.TransportError:
        return False
    return str(got.get("state") or "") == "closed"


def marks_of(payload: dict[str, Any]) -> set[str]:
    """Метки изменения множеством имён."""
    return {str(item.get("name") or "") for item in payload.get("labels") or []}


def latest(runs: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Самая свежая запись имени, у которой ЕСТЬ вердикт.

    Отменённая и пропущенная не выбираются, пока у имени есть живая: отмена —
    штатное следствие группы, и свежесть между нею и работающей записью не
    решает. Тот же приём и по той же причине держит `ci_complete.worst_per_name`
    — разводить два понимания одного различия нельзя
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    named = [run for run in runs if str(run.get("name") or "") == name]
    if not named:
        return None
    live = [run for run in named if str(run.get("conclusion") or "") not in WITHOUT_VERDICT]
    pool = live or named
    return max(pool, key=lambda run: str(run.get("started_at") or ""))


def judge(
    payload: dict[str, Any],
    runs: list[dict[str, Any]],
    required: list[str],
    *,
    armed: bool,
    fresh: bool,
    lifted: bool = False,
) -> Verdict:
    """Вердикт по одному изменению: застряло ли и чем именно.

    ПОРЯДОК ВОПРОСОВ — ЧАСТЬ ОТВЕТА. Сперва снимаются состояния, в которых
    стоять законно (черновик, стоп-метка, несчитанное состояние, сосед), потом
    спрашивается то, ради чего шаг заведён. Обратный порядок называл бы
    застрявшим черновик.

    ЧИСТАЯ ФУНКЦИЯ НАД ОТВЕТАМИ ПЛОЩАДКИ, а не заход с сетью внутри: подделать
    застрявшее иначе нечем, а гейт проверяется тем, что обязан отвергнуть
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    number = int(payload.get("number") or 0)
    marks = marks_of(payload)

    if bool(payload.get("draft")):
        return Verdict(number, False, WHY_DRAFT)
    if HOLD in marks:
        # ТРИ ИСХОДА, А НЕ ДВА (039). «Остановлено» и «остановлено и забыто»
        # снаружи одинаковы, и различает их только то, названо ли условие
        # (решение 018). Третий — стоп-кран, не назвавший ничего: у него нет
        # адресата, и он идёт в реестр, а не в молчание (147, 158).
        if not waits_for(str(payload.get("body") or "")):
            return Verdict(number, True, STUCK_HOLD_MUTE)
        return Verdict(number, False, WHY_HOLD_LIFTED if lifted else WHY_HOLD, lift=lifted)
    state = str(payload.get("mergeable_state") or "")
    if state in UNCOMPUTED:
        return Verdict(number, False, WHY_UNCOMPUTED)
    if state == STATE_CONFLICT:
        return Verdict(number, False, WHY_NEIGHBOUR)

    picked = {name: latest(runs, name) for name in required}
    missing = tuple(name for name, run in picked.items() if run is None)
    red = [
        name
        for name, run in picked.items()
        if run is not None
        and str(run.get("status") or "") == "completed"
        and str(run.get("conclusion") or "") not in PASSED
    ]
    running = [
        name
        for name, run in picked.items()
        if run is not None and str(run.get("status") or "") != "completed"
    ]

    # СВОЁ КРАСНОЕ ОТДАЁТСЯ СОСЕДУ ДО РАЗБОРА ПРОПАЖИ: изменение с красным
    # стоит по понятной причине, и второй голос о том же был бы вторым
    # адресатом одного состояния (022).
    if red:
        return Verdict(number, False, WHY_NEIGHBOUR)
    if fresh:
        return Verdict(number, False, WHY_FRESH)
    if not runs:
        return Verdict(number, True, STUCK_NO_RUNS)
    if missing:
        return Verdict(number, True, STUCK_MISSING, missing)
    if running:
        return Verdict(number, False, WHY_RUNNING)
    if CONSENT not in marks:
        return Verdict(number, False, WHY_NO_CONSENT)
    if not armed:
        return Verdict(number, True, STUCK_UNARMED)
    return Verdict(number, True, STUCK_ARMED)


def is_fresh(head_at: str, now: datetime, minutes: int = FRESH_MINUTES) -> bool:
    """Моложе ли голова срока. Неразобранная отметка считается СТАРОЙ.

    Из «времени не прочесть» нельзя вывести «изменение новое»: это вывод из
    незнания, а он запрещён
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Старая отметка лишь пускает изменение в разбор — застрявшим его делает
    состояние, а не срок.
    """
    if not head_at:
        return False
    try:
        seen = datetime.fromisoformat(head_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return now - seen < timedelta(minutes=minutes)


def head_time(repo: str, sha: str, token: str) -> str:
    """Когда сделан коммит головы; пусто — если спросить не удалось."""
    try:
        got = ghrest.request("GET", f"repos/{repo}/commits/{sha}", token) or {}
    except ghrest.TransportError:
        return ""
    commit = got.get("commit") or {}
    return str((commit.get("committer") or {}).get("date") or "")


def sweep(repo: str, token: str, now: datetime, minutes: int = FRESH_MINUTES) -> list[Verdict]:
    """Обход всех живых изменений: вердикт по каждому, без исключений.

    Изменение, пропущенное молча, — ровно тот случай, который шаг и ищет,
    поэтому список вердиктов полон, а печатается из него то, что спросили.
    """
    checks = policy.load(policy.DEFAULT_PATH)
    required = policy.names_of(checks, policy.REQUIRED)
    if not required:
        raise NotRun("обязательных имён не объявлено — предмет обхода не найден (075)")

    seen: list[Verdict] = []
    for short in ghrest.paginate(f"repos/{repo}/pulls?state=open", token):
        number = int(short["number"])
        full = ghrest.request("GET", f"repos/{repo}/pulls/{number}", token) or {}
        head = str((full.get("head") or {}).get("sha") or "")
        if not head:
            raise NotRun(f"#{number}: головы нет — читать нечего (075)")
        runs = (
            ghrest.request("GET", f"repos/{repo}/commits/{head}/check-runs?per_page=100", token)
            or {}
        ).get("check_runs") or []
        said = waits_for(str(full.get("body") or "")) if HOLD in marks_of(full) else ""
        subject = named_subject(said)
        seen.append(
            judge(
                full,
                list(runs),
                required,
                armed=bool(full.get("auto_merge")),
                fresh=is_fresh(head_time(repo, head, token), now, minutes),
                lifted=bool(subject) and is_settled(repo, subject, token),
            )
        )
    return seen


def lift_hold(repo: str, number: int, token: str, *, apply: bool) -> None:
    """Снимает стоп-метку и ВОЗВРАЩАЕТ согласие: причина снятия была одна.

    Согласие снял не человек, а сама метка (`agent_pr.apply_consent`). Убрать причину
    и оставить следствие значило бы, что снятия нет вовсе, — есть уборка
    мусора, после которой изменение стоит ровно так же, только молча
    (решение 018).

    Отказ площадки здесь не роняет обход: остальные изменения ещё не
    посмотрены, а стоп-кран простоит до следующего захода
    ([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
    """
    if not apply:
        print(f"  #{number}: снял бы «{HOLD}» и вернул «{CONSENT}» — названное закрыто")
        return
    try:
        ghrest.request("DELETE", f"repos/{repo}/issues/{number}/labels/{ghrest.quote(HOLD)}", token)
        ghrest.request("POST", f"repos/{repo}/issues/{number}/labels", token, {"labels": [CONSENT]})
    except ghrest.TransportError as exc:
        print(f"  #{number}: стоп-кран снять не удалось — {report.cut(str(exc))}")
        return
    print(f"  #{number}: «{HOLD}» снят, «{CONSENT}» возвращено — названное закрыто")


def render_body(stuck: list[Verdict], now: datetime) -> str:
    """Тело реестра: пересобирается заходом целиком, а не дописывается."""
    lines = [
        MARKER,
        "",
        "> **Читатель:** владелец и окно. Здесь изменения, которые **готовы и не",
        "> слиты**: красного у них нет, конфликта нет, работать по ним некому —",
        "> и всё равно они стоят.",
        "",
        "Своё красное и конфликт сюда не попадают: их предмет — оклик",
        "(`scripts/hail.py`), и у них есть кому работать. Здесь остаётся то, что",
        "не чинится правкой изменения: потерянное событие, несозданная проверка,",
        "невыданный значок, невыполненное слияние.",
        "",
        f"Обход: {now.strftime('%Y-%m-%d %H:%M')} UTC.",
        "",
        "## Стоят",
        "",
    ]
    if not stuck:
        lines.append("Пусто — всё готовое либо слито, либо движется.")
        return "\n".join(lines) + "\n"
    lines.extend(item.said() for item in sorted(stuck, key=lambda item: item.number))
    return "\n".join(lines) + "\n"


def save(repo: str, token: str, stuck: list[Verdict], now: datetime, *, apply: bool) -> None:
    """Записывает реестр: обновляет по месту или заводит одну задачу."""
    number, _ = findings.live_issue(repo, token, MARKER)
    body = render_body(stuck, now)
    if not apply:
        print(f"записал бы {len(stuck)} в " + (f"#{number}" if number else "новую задачу"))
        return
    if number is None:
        created = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"реестр заведён: #{(created or {}).get('number')}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"реестр обновлён: #{number}, записей {len(stuck)}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обходит живые изменения и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--after",
        type=int,
        default=FRESH_MINUTES,
        help="сколько минут голова стоит, прежде чем её молчание разбирают",
    )
    parser.add_argument("--apply", action="store_true", help="записать реестр, а не показать")
    args = parser.parse_args(argv)

    try:
        # ОТКАТА НА ТОКЕН ПРОГОНА НЕТ, И ЭТО ИЗМЕРЕНО У СОСЕДА. Состояние
        # слияния площадка считает только тому, у кого есть доступ на запись:
        # на слабом токене обход выглядел бы отработавшим, а «конфликта нет» и
        # «я не вижу конфликта» — разные утверждения (045). Молчание дороже
        # ложного «застрявших нет».
        token = os.environ.get(ENV_TOKEN, "")
        if not token:
            print(
                f"{ENV_TOKEN} не задан: состояние слияния площадка отдаёт только "
                "тому, у кого есть доступ на запись, и обход был бы слепым",
                file=sys.stderr,
            )
            return EXIT_UNSET
        if not args.repo:
            raise NotRun("репозиторий не назван — обходить нечего (075)")
        now = datetime.now(UTC)
        seen = sweep(args.repo, token, now, args.after)
    except (NotRun, policy.BadPolicy, ghrest.TransportError) as exc:
        print(f"обход не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN

    stuck = [item for item in seen if item.stuck]
    for item in seen:
        if item.lift:
            lift_hold(args.repo, item.number, token, apply=args.apply)
        if not item.stuck:
            print(f"  #{item.number}: не застряло — {item.why}")
    save(args.repo, token, stuck, now, apply=args.apply)
    if not stuck:
        print(f"застрявших нет: живых изменений {len(seen)}")
        return EXIT_OK
    print(f"застрявших: {len(stuck)} из {len(seen)} живых")
    for item in stuck:
        print(item.said())
    return EXIT_STUCK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
