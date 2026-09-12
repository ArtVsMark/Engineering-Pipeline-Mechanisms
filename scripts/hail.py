#!/usr/bin/env python3
"""Оклик: вердикт находит окно, которое его заработало.

ЗЕРКАЛО ОСТАЁТСЯ ИСТОЧНИКОМ ИСТИНЫ, ОКЛИК — ЕГО АДРЕСНАЯ ПОЛОВИНА. Реестры
(#23, #89, #99, #193) отвечают на вопрос «что не разобрано»; ни один не
отвечает на вопрос «КОМУ это чинить». Пока адресата нет, состояние видит тот,
кто сам зашёл посмотреть, — то есть владелец, а не окно, оставившее работу
([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)).

АДРЕС У НАС УЖЕ ЕСТЬ, И ОН МАШИННЫЙ. Трейлер ``Claude-Session`` несёт настоящий
номер сессии — тот же, что у живого окна, — и едет в общую ветку вместе с
работой. До сих пор он лишь переносился в тело уплотнения
(``scripts/squash_body.py``) и никем не читался.

ОКЛИКАЕМ ТОЛЬКО ПРО ТО, ЧТО ОКНО ЧИНИТ САМО. Список закрытый, и это не
осторожность: оклик про чужое приучают пропускать, а пропускать начинают все
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md),
[068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).

* **конфликт** — штатный источник работы (004), и разрешает его автор ветки;
* **своё красное** — обязательная проверка на голове изменения не прошла.

Не окликаем: отставание базы — его чинит очередь сама; красную общую ветку —
у неё свой дежурный и свой адресат (#99); находки взгляда — у них адресат #23.

ОДИН ОКЛИК НА СОСТОЯНИЕ. Отпечаток состояния — номер изменения, род и голова:
новая голова означает новую работу и новый оклик, а повторный заход на
неизменившейся голове не создаёт второго. Ведётся это не счётчиком, а чтением
уже стоящих окликов
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)):
второй список того же разошёлся бы с первым молча.

МЁРТВОЕ ОКНО МЕНЯЕТ АДРЕСАТА, А НЕ ОТМЕНЯЕТ ОКЛИК. Признака «сессия жива» у
площадки нет, и выдумывать его нечем. Есть живой артефакт: ветка не двигалась
дольше срока, а изменение так и стоит в источнике работы. Тогда оклик
адресуется владельцу и говорит, почему адресат сменился
([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md)).

ТОКЕН — ВЛАДЕЛЬЦА, И ЭТО ВЫЯСНИЛОСЬ ПРОГОНОМ. Состояние слияния площадка
отдаёт только тому, у кого есть доступ на запись: у `github.token` его нет, и
конфликт для шага становится невидим. Замер 11.09.2026: изменение #217 стояло
конфликтным, локальный сухой заход владельцем видел его и называл, а прогон на
токене прогона молчал. Очередь это уже знала — `automerge.merge_state()`
принимает `owner_token`, — а шапка этого шага утверждала обратное.

ТОЛЧОК В ЖИВУЮ СЕССИЮ СЮДА НЕ ВХОДИТ, и это названо, а не забыто. Разбудить
окно может учётная запись Claude, а не токен репозитория: положить её в секреты
значило бы дать прогону право вести сессии на всей учётке — несопоставимо
больше, чем оставить записку. Решение отложено до того дня, когда след покажет,
что именно окно пропускает.

Исходы (правило 039): ``0`` заход отработал · ``2`` шаг не отработал ·
``3`` не настроено — нет токена.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import ci_complete
import findings
import ghrest
import pipeline_checks as policy
import report

#: Токен владельца: тот же, что у очереди. Имя общее намеренно — два имени для
#: одного секрета разошлись бы при первой же смене.
ENV_TOKEN: Final = "MERGE_QUEUE_TOKEN"

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_UNSET: Final = 3

#: Метка оклика в комментарии. Та же фраза-хранитель, что у живых задач: два
#: понимания «это ведёт механизм» разошлись бы молча (090).
MARKER: Final = findings.marker("hail")

#: Адрес окна в трейлере коммита. Читается номер, а не ссылка целиком: ссылка
#: — способ открыть, номер — то, чем окно называется.
SESSION_RE: Final = re.compile(r"^Claude-Session:\s*\S*?(session_[A-Za-z0-9]+)", re.MULTILINE)

#: Отпечаток состояния внутри оклика: по нему заход узнаёт свой прежний.
STAMP_RE: Final = re.compile(r"<!--\s*hail-stamp:\s*(?P<stamp>[\w.:-]+)\s*-->")

#: Роды состояния, про которые окликают. Закрытый список: род вне его — не
#: «неизвестный оклик», а то, про что окликать не договаривались.
KIND_CONFLICT: Final = "conflict"
KIND_OWN_RED: Final = "own-red"
KINDS: Final = (KIND_CONFLICT, KIND_OWN_RED)

#: Как род называется человеку. Рядом с отпечатком, а не вместо: человек читает
#: слова, механизм — род.
KIND_SAID: Final = {
    KIND_CONFLICT: "конфликт с общей веткой",
    KIND_OWN_RED: "своё красное: обязательная проверка на голове не прошла",
}

#: Состояние слияния, означающее конфликт. Слово площадки, а не наше.
STATE_CONFLICT: Final = "dirty"

#: Состояния, означающие «ответа ещё нет»: площадка считает слияние лениво, и
#: первый запрос лишь заказывает вычисление. Читать их как «конфликта нет»
#: значило бы выводить ответ из незнания (045).
UNCOMPUTED: Final = frozenset({"", "unknown"})

#: Сколько часов без нового коммита делает окно предположительно мёртвым.
#: ВЕЛИЧИНА ОБЪЯВЛЕНА, А НЕ ВЫВЕДЕНА: она про внимание человека и его смену, а
#: не про данные. Ошибка в меньшую сторону зовёт владельца зря, в большую —
#: оставляет работу лежать; двенадцать часов покрывают ночь и не покрывают
#: рабочий день.
QUIET_AFTER_HOURS: Final = 12


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «окликать некого»."""


@dataclass(frozen=True, slots=True)
class Subject:
    """Одно изменение в состоянии, про которое окликают."""

    number: int
    head: str
    kind: str
    session: str
    quiet: bool
    why: str

    @property
    def stamp(self) -> str:
        """Отпечаток состояния: новая голова — новая работа и новый оклик."""
        return f"{self.number}.{self.kind}.{self.head[:8]}"


def session_of(commits: list[dict[str, Any]]) -> str:
    """Номер окна из трейлеров ветки — последний названный, или пусто.

    ПОСЛЕДНИЙ, А НЕ ПЕРВЫЙ: ветку мог продолжить другой заход, и чинить работу
    зовут того, кто трогал её позже. Пусто — законное состояние: изменение мог
    открыть человек руками, и тогда адресат владелец.
    """
    for payload in reversed(commits):
        message = str(((payload or {}).get("commit") or {}).get("message") or "")
        found = SESSION_RE.search(message)
        if found:
            return found.group(1)
    return ""


def touched_at(commits: list[dict[str, Any]]) -> str:
    """Когда ветку трогали в последний раз — по дате коммитера."""
    if not commits:
        return ""
    commit = (commits[-1] or {}).get("commit") or {}
    return str((commit.get("committer") or {}).get("date") or "")


def is_quiet(said: str, now: datetime, hours: int = QUIET_AFTER_HOURS) -> bool:
    """Молчит ли ветка дольше срока. Неизвестная дата молчанием НЕ считается.

    Сторона выбрана та, где механизм не зовёт владельца зря: незнание — повод
    оставить адресатом окно, а не повод разбудить человека (045).
    """
    if not said:
        return False
    try:
        when = datetime.fromisoformat(said.replace("Z", "+00:00"))
    except ValueError:
        return False
    return now - when > timedelta(hours=hours)


def own_red(runs: list[dict[str, Any]], required: list[str]) -> list[str]:
    """Обязательные имена, чей исход на голове — не «прошло».

    Отсутствие записи сюда НЕ входит: «проверка ещё не шла» и «проверка упала»
    значат разное, и оклик про первое звал бы окно чинить то, чего ещё нет.
    Разводит их сводный гейт, а не этот шаг.

    ПО ХУДШЕЙ ЗАПИСИ, А НЕ ПО ПОСЛЕДНЕЙ. На одной голове легко оказываются две
    записи одного имени — два прогона от двух событий, — и порядок, в котором
    их отдаёт площадка, ничего не решает. Прежний разбор брал ту, что пришла
    позже, и красное могло тихо не сработать. Отбор общий со сводным гейтом
    (`ci_complete.worst_per_name`): второе понимание «какая из двух главная»
    разошлось бы с первым молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    Нашёл внешний взгляд на #216.
    """
    wanted = set(required)
    mine = [run for run in runs if str(run.get("name") or "") in wanted]
    return sorted(
        str(run.get("name") or "")
        for run in ci_complete.worst_per_name(mine)
        if run.get("status") == "completed" and run.get("conclusion") not in ("success", None)
    )


def standing(comments: list[dict[str, Any]]) -> set[str]:
    """Отпечатки состояний, про которые оклик уже стоит."""
    stamps: set[str] = set()
    for payload in comments:
        body = str((payload or {}).get("body") or "")
        if MARKER not in body:
            continue
        found = STAMP_RE.search(body)
        if found:
            stamps.add(found.group("stamp"))
    return stamps


def render(subject: Subject) -> str:
    """Тело оклика: что случилось, кому и что делать."""
    if subject.quiet or not subject.session:
        why_owner = (
            f"ветку не трогали дольше {QUIET_AFTER_HOURS} ч — окно, похоже, закрыто"
            if subject.quiet
            else "в коммитах ветки нет адреса окна: изменение открыто не окном"
        )
        addressee = f"**Адресат — владелец.** Причина смены адресата: {why_owner}."
    else:
        addressee = (
            f"**Адресат — окно `{subject.session}`**, оставившее эту работу. "
            "Адрес взят из трейлера `Claude-Session` в коммитах ветки, а не назначен."
        )
    return "\n".join(
        (
            MARKER,
            f"<!-- hail-stamp: {subject.stamp} -->",
            "",
            f"## Оклик: {KIND_SAID[subject.kind]}",
            "",
            addressee,
            "",
            subject.why,
            "",
            "Оклик ставится ОДИН РАЗ на состояние: отпечаток — номер изменения, род и "
            f"голова (`{subject.head[:8]}`). Новый коммит означает новую работу и новый "
            "оклик; повторный заход на этой же голове второго не создаёт.",
            "",
            "Толкнуть окно этот механизм не может и не должен: разбудить сессию вправе "
            "учётная запись Claude, а не токен прогона (131). Здесь — след, который "
            "переживает слияние.",
        )
    )


def subjects(repo: str, token: str, now: datetime) -> list[Subject]:
    """Живые изменения в состоянии, про которое окликают.

    Состояние выводится из площадки на каждом заходе, а не ведётся: второй
    список того же разошёлся бы с первым на первом же слиянии (049).
    """
    checks = policy.load(policy.DEFAULT_PATH)
    required = policy.names_of(checks, policy.REQUIRED)
    if not required:
        raise NotRun("обязательных имён не объявлено — предмет оклика не найден (075)")

    found: list[Subject] = []
    for payload in ghrest.paginate(f"repos/{repo}/pulls?state=open", token):
        number = int(payload["number"])
        head = str((payload.get("head") or {}).get("sha") or "")
        if bool(payload.get("draft")) or not head:
            continue
        full = ghrest.request("GET", f"repos/{repo}/pulls/{number}", token) or {}
        state = str(full.get("mergeable_state") or "")
        if state in UNCOMPUTED:
            # СОСТОЯНИЕ ЕЩЁ НЕ ПОСЧИТАНО — ЭТО ОТВЕТ, А НЕ ПУСТОТА. Площадка
            # считает его лениво, и первый запрос заказывает вычисление. Молча
            # пропустить значило бы читать «конфликта нет» из «я не знаю» (045).
            print(f"  #{number}: состояние слияния ещё не посчитано — окликать рано")
            continue
        runs = (
            ghrest.request("GET", f"repos/{repo}/commits/{head}/check-runs?per_page=100", token)
            or {}
        ).get("check_runs") or []
        red = own_red(list(runs), required)

        if state == STATE_CONFLICT:
            kind, why = (
                KIND_CONFLICT,
                (
                    "Изменение разошлось с общей веткой. Очередь его пропустила и пошла "
                    "дальше — конфликт здесь штатный источник работы, а не авария (004). "
                    "Развести ветку может только её автор."
                ),
            )
        elif red:
            kind, why = (
                KIND_OWN_RED,
                (
                    "Обязательные проверки на голове не прошли: "
                    + ", ".join(f"`{name}`" for name in red)
                    + ". Это красное СВОЁ — про эту работу, а не про общую ветку."
                ),
            )
        else:
            continue

        commits = list(ghrest.paginate(f"repos/{repo}/pulls/{number}/commits", token))
        found.append(
            Subject(
                number=number,
                head=head,
                kind=kind,
                session=session_of(commits),
                quiet=is_quiet(touched_at(commits), now),
                why=why,
            )
        )
    return found


def hail(repo: str, token: str, *, dry_run: bool, now: datetime) -> int:
    """Ставит недостающие оклики; отдаёт, сколько поставлено."""
    placed = 0
    for subject in subjects(repo, token, now):
        comments = list(ghrest.paginate(f"repos/{repo}/issues/{subject.number}/comments", token))
        if subject.stamp in standing(comments):
            print(f"  #{subject.number}: оклик про «{subject.kind}» уже стоит — второго не надо")
            continue
        whom = "владельцу" if (subject.quiet or not subject.session) else subject.session
        if dry_run:
            print(f"  (пробный заход) #{subject.number}: оклик «{subject.kind}» → {whom}")
            continue
        try:
            ghrest.request(
                "POST",
                f"repos/{repo}/issues/{subject.number}/comments",
                token,
                {"body": render(subject)},
            )
        except ghrest.TransportError as exc:
            # Отказ записи заход не роняет: оклик — след, а не условие работы
            # (084). Но и молчать о нём нельзя: «окликнул ноль из трёх» и
            # «окликнул всех» снаружи одинаковы (045).
            print(f"  #{subject.number}: оклик не записан: {report.cut(str(exc))}")
            continue
        print(f"  #{subject.number}: оклик «{subject.kind}» → {whom}")
        placed += 1
    return placed


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="записывать, а не показывать")
    args = parser.parse_args(argv)

    try:
        # ТОКЕН ВЛАДЕЛЬЦА, А НЕ ПРОГОНА, И ПРИЧИНА ИЗМЕРЕНА. Состояние слияния
        # площадка отдаёт только с доступом на запись; на токене прогона шаг
        # конфликта не видит вовсе и молчит, выглядя при этом зелёным.
        token = os.environ.get(ENV_TOKEN, "") or ""
        if not token:
            print(
                f"не настроено: нет {ENV_TOKEN} — состояние слияния площадка не отдаст, "
                "и оклик про конфликт был бы слепым",
                file=sys.stderr,
            )
            return EXIT_UNSET
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        placed = hail(args.repo, token, dry_run=not args.apply, now=datetime.now(UTC))
    except (NotRun, ghrest.TransportError, policy.BadPolicy) as exc:
        print(f"оклик не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # ПУСТО — ЗАКОННОЕ СОСТОЯНИЕ, И ЭТО НЕ «НЕ НАШЁЛ ПРЕДМЕТА». Предмет здесь —
    # список живых изменений, и он прочитан; «никому не о чем сказать» ответ, а
    # не молчание (075 читается по предмету проверки, а не по числу находок).
    print(f"окликов поставлено: {placed}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
