#!/usr/bin/env python3
"""Выпуск: необратимый шаг проверяется ДО прогона, а не прогоном.

Порядок выпуска записан в `docs/release.md` с самого начала, а механизма под ним
не было: путь ни разу не проходили целиком, и «работает» держалось тем, что его
никто не пробовал
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

ТЕГ НЕ ПЕРЕСТАВЛЯЕТСЯ, И ЭТО ОПРЕДЕЛЯЕТ ВСЮ ФОРМУ. Шаг, который нельзя
отменить, получает собственную проверку ПЕРЕД собой, а не разбор последствий
после
([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)).
Поэтому заход разделён надвое: сначала все условия проверяются на сухую и
печатаются, и лишь потом — с ключом `--apply` — делается то, что откатить
нельзя.

ДВА ЧИСЛА, ДВА ПРАВИЛА. Тег выпуска двигает МИНОР на каждом выпуске, и линия
считается от тега; версия контракта поднимается только вместе с тронутой
поверхностью, а несовместимость объявляют ключом `--breaking`. Патч не растёт
ни у одного из них: он разряд ГОЛОВЫ, число принятых изменений после тега.
Разбор и отвергнутые варианты —
`docs/decisions/017-a-release-moves-the-minor-the-contract-moves-itself.md`.

Механизм не выбирает разряд за человека: он отвергает номер, который линии
противоречит
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

МАЖОР ПОДНИМАЕТ ЗАКРЫТАЯ ПРИЁМКА, А НЕ ВЫПУСК. `0.x` означает «ещё не доделано
здесь», и единицу выпускает не появление потребителя, а закрытая приёмка
(`docs/decisions/009-one-zero-means-it-works-at-home.md`). Поэтому мажор
механизм требует объявить отдельно — ключом `--acceptance <номер задачи>`, — и
САМ спрашивает у площадки, закрыта ли она: приёмка, названная словом, но не
закрытая, ничем не отличалась бы от прежнего «назовите потребителя».

Ключ один на обе поры намеренно. До передачи приёмка — эпик «работает у себя»;
после неё мажор растёт с каждым подключённым, и приёмкой становится задача его
подключения. Номер задачи здесь не зашит: зашитый устарел бы молча (005).

НЕЗНАНИЕ — ТРЕТИЙ ИСХОД, А НЕ ПОБЛАЖКА. Если состояние приёмки не прочитано —
нет токена, площадка молчит, — выпуск не идёт и причина называется. Считать
непрочитанное за «закрыта» значило бы завести обход там, где стоит проверка
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Исходы (правило 039): ``0`` выпуск готов либо сделан · ``1`` условия не
сошлись · ``2`` шаг не отработал.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import build_changelog
import ghrest
import paths
import pipeline_checks as policy
import report
import version as project_version

VERSION_RE: Final = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
#: Род фрагмента, объявляющий правку поверхности контракта.
CONTRACT_KIND: Final = ".contract.md"

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «выпускать нечего»."""


def git(*args: str) -> str:
    """Ответ git; отказ — это отказ входа, а не пустая строка."""
    done = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if done.returncode != 0:
        raise NotRun(f"git {' '.join(args)}: {report.cut(done.stderr.strip())}")
    return done.stdout.strip()


def fragments() -> list[Path]:
    """Фрагменты, ожидающие выпуска."""
    return sorted(p for p in paths.FRAGMENTS.glob("*.md") if p.name != "README.md")


def touches_contract(waiting: list[Path]) -> list[str]:
    """Фрагменты, объявившие правку поверхности."""
    return [p.name for p in waiting if p.name.endswith(CONTRACT_KIND)]


def declared_version() -> str:
    """Объявленная версия контракта — то, от чего считается следующая."""
    return paths.VERSION.read_text(encoding="utf-8").strip()


def next_after(current: str) -> str:
    """Какой номер ВЫПУСКА ожидается после текущего: минор плюс один.

    ВЫПУСК ДВИГАЕТ МИНОР, А ПАТЧ ВЫПУСКОМ НЕ БЫВАЕТ. Патч — разряд ГОЛОВЫ:
    `version.version()` считает его числом принятых изменений после тега, и
    `1.0.1` это версия дерева, а не выпуск. Замер по семье 12.09.2026: каталог
    `v1.0.0 → v1.1.0 → v1.2.0`, грейдер `v1.4.0 … v1.11.0`, токен
    `v0.1 → v0.2` — **патч-тегов нет ни у кого**.

    ПОЧЕМУ ЭТО НЕ ВОЗВРАТ К ОТМЕНЁННОМУ. Решение 015 сняло прежний расчёт
    потому, что тег и версия контракта были ОДНИМ числом: минор тега двигал
    минор контракта, и каждый выпуск ложно объявлял «поверхность расширена».
    Числа развязаны (`docs/decisions/017-a-release-moves-the-minor-the-contract-moves-itself.md`),
    и довод 015 остался в силе — он теперь про :func:`next_contract`, а не про
    этот расчёт.

    МАЖОР ЗДЕСЬ НЕ РАСТЁТ НИКОГДА: его поднимает закрытая приёмка, и состояние
    приёмки механизм спрашивает у площадки.
    """
    found = VERSION_RE.match(current)
    if found is None:
        raise NotRun(f"версия «{current}» не вида МАЖОР.МИНОР.ПАТЧ")
    major, minor = (int(found.group(one)) for one in (1, 2))
    return f"{major}.{minor + 1}.0"


def next_contract(current: str, *, touched: bool, breaking: bool = False) -> str:
    """Какой станет версия КОНТРАКТА: минор, только если поверхность тронута.

    ВЕРСИЯ КОНТРАКТА ДВИЖЕТСЯ СВОИМИ РАЗРЯДАМИ, и это довод решения 015,
    сохранённый целиком. Подъём её минора — требование перечитать ответы
    ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)),
    и требовать его на каждом выпуске значило бы требовать зря: перечитывание,
    потребованное зря, перестают делать
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

    Поверхность не тронута — число НЕ МЕНЯЕТСЯ вовсе: ни минор, ни патч. Патч
    контракта в этом проекте не растёт ни от чего, и это названо, а не забыто:
    у контракта нет события, которое двигало бы его, не тронув поверхность.

    НЕСОВМЕСТИМАЯ ПРАВКА ПОДНИМАЕТ МАЖОР, И ОБЪЯВЛЯЕТ ЕЁ ЧЕЛОВЕК. Род
    фрагмента `contract` не различает расширение от поломки — он говорит
    «поверхность тронута», и только. Различает это гейт связи, но он смотрит
    ДИФФ изменения, которого у выпуска уже нет: к моменту выпуска слито много
    изменений сразу. Поэтому несовместимость приходит ключом `--breaking`,
    ровно как мажор выпуска приходит закрытой приёмкой: угадывать необратимое
    механизм не берётся
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    Первая редакция пути к мажору не имела вовсе — несовместимость ушла бы
    минором, то есть обещанием «можно не читать». Нашёл внешний взгляд на #253.
    """
    found = VERSION_RE.match(current)
    if found is None:
        raise NotRun(f"версия контракта «{current}» не вида МАЖОР.МИНОР.ПАТЧ")
    if not touched:
        return current
    major, minor = (int(found.group(one)) for one in (1, 2))
    return f"{major + 1}.0.0" if breaking else f"{major}.{minor + 1}.0"


#: Состояния названной приёмки. Четыре, а не три: «такой задачи нет» чинится
#: НОМЕРОМ, «не прочитано» — токеном, и назвать второе вместо первого значит
#: отправить человека искать не туда (154).
ACCEPTANCE_CLOSED: Final = "closed"
ACCEPTANCE_OPEN: Final = "open"
ACCEPTANCE_MISSING: Final = "missing"
ACCEPTANCE_UNREAD: Final = "unread"
#: Пятое: вход не разобрался как номер — «#196», «196 », «эпик». Это тоже
#: чинится человеком, но ещё раньше: до всякого запроса к площадке.
ACCEPTANCE_NOT_A_NUMBER: Final = "not-a-number"

#: Как состояние называется человеку. Словарь объявлен ЗДЕСЬ, а не собран на
#: месте печати, ради одного: договор о выпуске обязан называть все состояния,
#: которые механизм различает, и сверить это можно только по перечислимому
#: списку. Договор и механизм уже расходились — новое правило мажора жило в
#: `docs/release.md`, пока механизм исполнял старое (#198).
ACCEPTANCE_SAID: Final = {
    ACCEPTANCE_CLOSED: "закрыта",
    ACCEPTANCE_OPEN: "ОТКРЫТА",
    ACCEPTANCE_MISSING: "такой задачи у площадки нет",
    ACCEPTANCE_UNREAD: "состояние не прочитано",
    ACCEPTANCE_NOT_A_NUMBER: "не разобрано как номер задачи",
}


def acceptance_state(repo: str, number: int, token: str) -> str:
    """Состояние названной приёмки одним из четырёх слов.

    ЧЕТЫРЕ, А НЕ ДВА, И РАЗНИЦА ВСЯ В ТОМ, ЧТО ЧЕЛОВЕКУ ЧИНИТЬ. «Закрыта» и
    «открыта» — про работу; «такой задачи нет» — про НОМЕР, набранный с
    опечаткой; «не прочитано» — про токен или молчащую площадку. Сведение
    третьего ко второму отправляло бы искать токен там, где неверна цифра.
    Нашёл внешний взгляд на #204.

    Ни одно из двух незнаний не считается за «закрыта»: это был бы обход
    проверки, стоящей перед необратимым (045, 074).
    """
    if not repo or not token:
        return ACCEPTANCE_UNREAD
    try:
        issue = ghrest.request("GET", f"repos/{repo}/issues/{number}", token) or {}
    except ghrest.NotFound:
        return ACCEPTANCE_MISSING
    except ghrest.TransportError:
        return ACCEPTANCE_UNREAD
    state = issue.get("state")
    if not state:
        return ACCEPTANCE_UNREAD
    return ACCEPTANCE_CLOSED if state == "closed" else ACCEPTANCE_OPEN


#: Как площадка называет право обхода защиты для спрашивающего. Прямому толчку
#: помогает только «always»: «pull_requests_only» разрешает обойти проверки
#: через изменение, а выпуск толкает коммит напрямую.
#: Общая ветка проекта: её защиту и спрашивает выпуск.
DEFAULT_BRANCH: Final = "main"
MAY_PUSH: Final = "always"
CANNOT_PUSH: Final = frozenset({"never", "pull_requests_only"})


def may_push(repo: str, branch: str, token: str) -> str:
    """Что площадка говорит про право ЭТОГО токена толкать в общую ветку.

    Пусто — значит не спрошено: ответ площадки не прочитан, и «обход есть» из
    незнания не выводится
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

    ЗАЧЕМ ЭТО ВООБЩЕ. 12.09.2026 выпуск `1.0.0` собрал журнал, поставил тег и
    упёрся в набор правил общей ветки: у машинного коммита выпуска нет и не
    может быть проверки изменения. Толчок ветки отвергнут, тег принят — метка
    повисла на коммите, до общей ветки не доехавшем. Порядок толчков починен
    тогда же, но узнаётся всё это по-прежнему ПОСЛЕ сборки. Шаг, который
    нельзя отменить, получает собственную проверку ПЕРЕД собой
    ([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)),
    и вот она.

    СПРАШИВАЕТСЯ ПРО СПРАШИВАЮЩЕГО, и это единственный честный способ: поле
    `current_user_can_bypass` отвечает про тот токен, которым задан вопрос. У
    выпуска это токен владельца — тот самый, которым он потом толкает.
    """
    try:
        rules = ghrest.request("GET", f"repos/{repo}/rules/branches/{branch}", token) or []
    except ghrest.TransportError:
        return ""
    for one in rules:
        ruleset = (one or {}).get("ruleset_id")
        if ruleset is None:
            continue
        try:
            got = ghrest.request("GET", f"repos/{repo}/rulesets/{ruleset}", token) or {}
        except ghrest.TransportError:
            return ""
        return str(got.get("current_user_can_bypass") or "")
    # Правил на ветке нет вовсе — толкать некуда не мешает никто.
    return MAY_PUSH


def refusals(
    wanted: str,
    *,
    acceptance: str,
    state: str = ACCEPTANCE_UNREAD,
    breaking: bool = False,
    push: str = MAY_PUSH,
) -> list[str]:
    """Все причины НЕ выпускать — списком, а не первой попавшейся.

    Списком потому, что выпуск делают редко и по одной причине за раз чинить
    его дороже: человек должен увидеть сразу всё, что мешает.
    """
    problems: list[str] = []
    if VERSION_RE.match(wanted) is None:
        return [f"версия «{wanted}» не вида МАЖОР.МИНОР.ПАТЧ"]

    waiting = fragments()
    if not waiting:
        problems.append("ни одного фрагмента — это ошибка входа, а не пустой выпуск (075)")

    if git("status", "--porcelain"):
        problems.append("дерево грязно: выпуск делается с чистого дерева, иначе тег врёт")

    # ОТКАЗ ТОЛЬКО НА ОПРЕДЁННОМ, ПРЕДУПРЕЖДЕНИЕ НА ВЕРОЯТНОМ (051). «never» и
    # «pull_requests_only» значат, что прямой толчок отвергнут наверняка, и
    # собирать журнал незачем. Непрочитанный ответ означает незнание, а не
    # запрет: он печатается отдельной строкой в `announce`, но выпуск не
    # держит — порядок толчков и так не даст уехать тегу без ветки.
    if push in CANNOT_PUSH:
        problems.append(
            f"общая ветка не примет коммит выпуска: право обхода у этого токена — «{push}». "
            "Коммит выпуска собирает машина из уже слитых фрагментов, проверки изменения у "
            "него нет и быть не может (Settings → Rules → Bypass list)"
        )

    tags = git("tag", "--list", f"v{wanted}")
    if tags:
        problems.append(f"тег v{wanted} уже стоит — тег не переставляется (074)")

    # ЛИНИЯ ВЫПУСКОВ СЧИТАЕТСЯ ОТ ТЕГА, А НЕ ОТ ВЕРСИИ КОНТРАКТА: числа
    # развязаны (решение 017), и версия контракта больше не говорит, какой тег
    # ожидается следующим. Тега нет вовсе — линия начинается с нуля.
    line = (project_version.release_tag() or "v0.0.0").lstrip("v")
    expected = next_after(line)
    current = declared_version()
    major_now = int(VERSION_RE.match(line).group(1))  # type: ignore[union-attr]
    major_wanted = int(VERSION_RE.match(wanted).group(1))  # type: ignore[union-attr]

    if major_wanted > major_now and not acceptance:
        problems.append(
            f"мажор {major_now} → {major_wanted} поднимает не выпуск, а ЗАКРЫТАЯ приёмка: "
            "«0.x» значит «ещё не доделано здесь» (docs/release.md, decisions/009). "
            "Назовите её: --acceptance <номер задачи>"
        )
    elif major_wanted > major_now and state == ACCEPTANCE_NOT_A_NUMBER:
        problems.append(
            f"мажор {major_now} → {major_wanted}: «{acceptance}» не разобрано как номер задачи. "
            "Ожидается одно число без решётки и пробелов: --acceptance 196"
        )
    elif major_wanted > major_now and state == ACCEPTANCE_MISSING:
        problems.append(
            f"мажор {major_now} → {major_wanted}: задачи #{acceptance} у площадки НЕТ. "
            "Чинится номером, а не токеном: приёмка названа несуществующей"
        )
    elif major_wanted > major_now and state == ACCEPTANCE_UNREAD:
        problems.append(
            f"мажор {major_now} → {major_wanted}: состояние приёмки #{acceptance} не прочитано "
            "— нет токена или площадка молчит. Непрочитанное за «закрыта» не считается (045)"
        )
    elif major_wanted > major_now and state != ACCEPTANCE_CLOSED:
        problems.append(
            f"мажор {major_now} → {major_wanted}: приёмка #{acceptance} ещё ОТКРЫТА. "
            "Единицу выпускает её закрытие, а не выпуск (decisions/009)"
        )
    elif major_wanted == major_now and wanted != expected:
        problems.append(
            f"ожидается {expected}, а названо {wanted}: выпуск двигает МИНОР на единицу. "
            "Патч выпуском не бывает — это разряд головы (`1.0.1` версия, а не выпуск)"
        )

    # ПОДЪЁМ ВЕРСИИ КОНТРАКТА ОБЯЗАН ПОМЕЩАТЬСЯ В НАШ ЖЕ ОТВЕТ. Мы сами
    # потребитель своего контракта: `.pipeline.yml` объявляет диапазон
    # совместимости, и версия вне него роняет обязательную проверку `pipeline`
    # на общей ветке — то есть выпуск покрасил бы её сразу после себя.
    # Отказ идёт ДО необратимого, и перечитывание требуется словами (157).
    after = next_contract(current, touched=bool(touches_contract(waiting)), breaking=breaking)
    try:
        span = policy.span()
    except policy.BadPolicy as exc:
        # Ответ проекта не прочитан — это НЕ «диапазон подходит». Выпуск не
        # может убедиться, что подъём в него поместится, и говорит об этом
        # причиной, а не трассировкой (045).
        problems.append(f"ответ проекта не прочитан, и диапазон спросить не у чего: {exc}")
    else:
        if after != current and not policy.compatible(span, after):
            problems.append(
                f"выпуск поднимет версию контракта {current} → {after}, а объявленный диапазон "
                f"«{span}» её не принимает: обязательная проверка `pipeline` покраснеет сразу "
                "после выпуска. Перечитайте ответы и подвиньте диапазон в `.pipeline.yml` (157)"
            )
    return problems


def announce(
    wanted: str,
    *,
    acceptance: str,
    state: str = ACCEPTANCE_UNREAD,
    breaking: bool = False,
    push: str = MAY_PUSH,
) -> None:
    """Печатает, из чего собран выпуск: человек читает это перед необратимым."""
    if not push:
        # НЕПРОЧИТАННОЕ НАЗЫВАЕТСЯ, А НЕ МОЛЧИТ (154). Выпуск это не держит:
        # запрета из незнания не выводят, а порядок толчков и так не даст
        # уехать тегу без ветки.
        print(
            "право обхода защиты не прочитано: площадка не ответила. Если общая ветка "
            "отвергнет коммит, тег НЕ уедет — но узнается это после сборки"
        )
    waiting = fragments()
    contract = touches_contract(waiting)
    print(f"выпуск {wanted}: фрагментов {len(waiting)}, из них о поверхности {len(contract)}")
    for name in contract:
        print(f"  поверхность: {name}")
    number, whole = project_version.version()
    print(
        f"версия проекта на этой голове: {number}" + ("" if whole else " (неполна: тегов не видно)")
    )
    if acceptance:
        print(f"приёмка мажора: #{acceptance} — {ACCEPTANCE_SAID[state]}")
    # ЧЕЛОВЕК ЧИТАЕТ ЭТО ПЕРЕД НЕОБРАТИМЫМ, поэтому подъём версии контракта
    # называется числами, а не словом «изменится».
    now = declared_version()
    after = next_contract(now, touched=bool(contract), breaking=breaking)
    # ПОМЕТКА СЛЕДУЕТ ЧИСЛУ, А НЕ КЛЮЧУ. `--breaking` без фрагментов поверхности
    # ничего не двигает, и метить такой заход «НЕСОВМЕСТИМО» значило бы пугать
    # человека перед необратимым тем, чего не происходит
    # ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    # Нашёл внешний взгляд на #255.
    if after == now:
        print(f"версия контракта: {now} — не меняется, поверхность не тронута")
        if breaking:
            print("  ключ --breaking передан, но двигать нечего: фрагментов поверхности нет")
        return
    said = " (НЕСОВМЕСТИМО, объявлено ключом --breaking)" if breaking else ""
    print(f"версия контракта: {now} → {after}{said}")


def do_release(wanted: str, *, breaking: bool = False) -> None:
    """Необратимая часть: журнал, версия, коммит, тег.

    Порядок ровно тот, что записан в `docs/release.md`, и он часть проверки, а
    не соглашение: тег ставится последним, когда всё остальное уже в коммите.
    """
    # ПОВЕРХНОСТЬ СПРАШИВАЕТСЯ ДО ПЕРЕЕЗДА ФРАГМЕНТОВ, а не после. Сборка
    # журнала УНОСИТ их в `released/`, и спрошенное после неё всегда отвечало
    # «не тронута»: версия контракта не двигалась ни при какой правке
    # поверхности. Нашёл это интеграционный тест, которого сначала не было, —
    # ровно тот случай, ради которого он и потребован внешним взглядом на #253
    # ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).
    touched = bool(touches_contract(fragments()))
    build_changelog.do_release(wanted)
    # ВЕРСИЯ КОНТРАКТА ПИШЕТСЯ ТОЛЬКО ЕСЛИ ПОВЕРХНОСТЬ ТРОНУТА. Прежде здесь
    # стоял номер выпуска, и два числа были одним: каждый тег двигал версию
    # контракта, то есть требовал перечитать ответы, которых ничто не
    # отменяло. Решение 017 развязало их.
    contract_now = declared_version()
    contract_after = next_contract(contract_now, touched=touched, breaking=breaking)
    if contract_after != contract_now:
        paths.VERSION.write_text(f"{contract_after}\n", encoding="utf-8")
        print(f"версия контракта {contract_now} → {contract_after}: поверхность тронута")
    else:
        print(f"версия контракта осталась {contract_now}: поверхность не тронута")
    build_changelog.main([])
    git("add", "-A")
    git("commit", "-m", f"release: {wanted}")
    git("tag", "-a", f"v{wanted}", "-m", f"v{wanted}")
    print(f"выпуск {wanted} собран и помечен тегом v{wanted}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сухая проверка, а по ключу — необратимый шаг."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="номер выпуска; по умолчанию следующий")
    parser.add_argument("--apply", action="store_true", help="сделать необратимое")
    parser.add_argument(
        "--acceptance",
        default="",
        help="номер задачи-приёмки: мажор поднимает её ЗАКРЫТИЕ, а не выпуск",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="где спрашивать состояние приёмки",
    )
    # НЕСОВМЕСТИМОСТЬ ОБЪЯВЛЯЕТ ЧЕЛОВЕК: род фрагмента `contract` не различает
    # расширение от поломки, а гейт связи смотрит дифф ИЗМЕНЕНИЯ, которого у
    # выпуска уже нет — к этому моменту слито много изменений сразу.
    parser.add_argument(
        "--breaking",
        action="store_true",
        help="поверхность изменена НЕСОВМЕСТИМО: поднимает МАЖОР версии контракта",
    )
    args = parser.parse_args(argv)

    try:
        wanted = args.version or next_after((project_version.release_tag() or "v0.0.0").lstrip("v"))
        # Состояние приёмки спрашивается ОДИН раз и передаётся обоим: разбор и
        # печать обязаны говорить об одном состоянии, а два запроса на одном
        # заходе могли бы разойтись.
        # ФОРМА ВХОДА РАЗБИРАЕТСЯ ДО ЗАПРОСА, И ОТКАЗ У НЕЁ СВОЙ. «#196» не
        # число, и молчаливое сведение его к «состояние не прочитано» называло
        # причиной токен там, где неверна форма (154). Нашёл внешний взгляд
        # на #204.
        state = (
            acceptance_state(args.repo, int(args.acceptance), ghrest.token_from_env())
            if args.acceptance.isdigit()
            else ACCEPTANCE_NOT_A_NUMBER
        )
        # ПРАВО ТОЛКНУТЬ СПРАШИВАЕТСЯ ТЕМ ЖЕ ТОКЕНОМ, которым выпуск потом
        # толкает: ответ площадки про обход относится к спрашивающему.
        push = may_push(args.repo, DEFAULT_BRANCH, ghrest.token_from_env()) if args.repo else ""
        problems = refusals(
            wanted,
            acceptance=args.acceptance,
            state=state,
            breaking=args.breaking,
            push=push or MAY_PUSH,
        )
        announce(
            wanted,
            acceptance=args.acceptance,
            state=state,
            breaking=args.breaking,
            push=push,
        )
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if problems:
        print(f"\nвыпускать нельзя ({len(problems)}):")
        for problem in problems:
            print(f"  {problem}")
        return EXIT_REFUSED

    if not args.apply:
        print("\nусловия сошлись. Необратимое делается ключом --apply")
        return EXIT_OK

    try:
        do_release(wanted, breaking=args.breaking)
    except (NotRun, build_changelog.NotRun) as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
