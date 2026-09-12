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

РАЗРЯД НОМЕРА НЕ ВЫДУМЫВАЕТСЯ, А ЧИТАЕТСЯ У ФРАГМЕНТОВ. Род `contract` среди
них означает, что поверхность тронута, — такой выпуск не может быть патчем.
Механизм не выбирает разряд за человека: он отвергает номер, который
фрагментам противоречит
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


def next_after(current: str, *, contract: bool) -> str:
    """Какой номер выпуска ожидается после текущего.

    РАЗРЯД ВЫБИРАЮТ ФРАГМЕНТЫ, А НЕ ФАКТ ПОСТАНОВКИ ТЕГА. Фрагмент рода
    `contract` означает, что поверхность тронута, — такой выпуск поднимает
    минор. Ни одного такого нет — поверхность не тронута, и это патч, ровно как
    сказано в таблице разрядов `docs/release.md`.

    ПРЕЖНИЙ РАСЧЁТ СПОРИЛ С ДОГОВОРОМ. Минор рос ВСЕГДА под инвариантом «каждый
    тег вида `vX.Y.0`», и каждый выпуск объявлял потребителю «поверхность
    расширена», даже когда правилась опечатка. Ложное обещание стоит
    перечитывания ответов, которых ничто не отменяло, а перечитывание,
    потребованное зря, перестают делать
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Разбор и отвергнутые варианты —
    `docs/decisions/015-the-contract-version-moves-by-its-own-digits.md`.

    МАЖОР ЗДЕСЬ НЕ РАСТЁТ НИКОГДА: его поднимает закрытая приёмка, а не род
    фрагмента, и состояние приёмки механизм спрашивает у площадки.
    """
    found = VERSION_RE.match(current)
    if found is None:
        raise NotRun(f"объявленная версия «{current}» не вида МАЖОР.МИНОР.ПАТЧ")
    major, minor, patch = (int(found.group(one)) for one in (1, 2, 3))
    return f"{major}.{minor + 1}.0" if contract else f"{major}.{minor}.{patch + 1}"


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


def refusals(wanted: str, *, acceptance: str, state: str = ACCEPTANCE_UNREAD) -> list[str]:
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

    tags = git("tag", "--list", f"v{wanted}")
    if tags:
        problems.append(f"тег v{wanted} уже стоит — тег не переставляется (074)")

    current = declared_version()
    expected = next_after(current, contract=bool(touches_contract(waiting)))
    major_now = int(VERSION_RE.match(current).group(1))  # type: ignore[union-attr]
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
            f"ожидается {expected}, а названо {wanted}: разряд выбирают ФРАГМЕНТЫ — "
            "фрагмент рода `contract` поднимает минор, его отсутствие — патч"
        )
    return problems


def announce(wanted: str, *, acceptance: str, state: str = ACCEPTANCE_UNREAD) -> None:
    """Печатает, из чего собран выпуск: человек читает это перед необратимым."""
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


def do_release(wanted: str) -> None:
    """Необратимая часть: журнал, версия, коммит, тег.

    Порядок ровно тот, что записан в `docs/release.md`, и он часть проверки, а
    не соглашение: тег ставится последним, когда всё остальное уже в коммите.
    """
    build_changelog.do_release(wanted)
    paths.VERSION.write_text(f"{wanted}\n", encoding="utf-8")
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
    args = parser.parse_args(argv)

    try:
        wanted = args.version or next_after(
            declared_version(), contract=bool(touches_contract(fragments()))
        )
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
        problems = refusals(wanted, acceptance=args.acceptance, state=state)
        announce(wanted, acceptance=args.acceptance, state=state)
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
        do_release(wanted)
    except (NotRun, build_changelog.NotRun) as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
