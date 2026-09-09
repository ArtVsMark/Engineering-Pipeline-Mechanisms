#!/usr/bin/env python3
"""Открывает изменение от лица владельца по ветке агентского окна.

Правило 131: операция, несущая личность человека, из агентского окна не
выполняется — на записи прокси подменяет учётные данные, и автором в общей
ветке становится приложение. Такая операция уходит в конвейер, и этот скрипт
и есть тот конвейер.

Решает **учётная запись, открывшая изменение**, а не подпись коммитов ветки:
после уплотнения авторство итогового коммита уже не поправить (123). Поэтому
токен здесь — владельца, а не прогона; на `GITHUB_TOKEN` скрипт молча не
переходит, иначе он делал бы ровно ту подмену, ради которой заведён.

Имя ветки — переключатель поведения (003): изменение открывается только для
объявленных приставок. Приставок две, и вторая не для красоты: в облачном окне
имя ветки назначает платформа, окно его не выбирает.

Идемпотентность обязательна: повторный толчок в ту же ветку не должен открывать
второе изменение — у соседнего проекта это уже случалось.

Исходы (правило 039): ``0`` открыто или уже есть · ``1`` не настроено ·
``2`` не отработало.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.parse
from typing import Final

import changerefs
import ghrest
import labels
import report

PREFIXES: Final = ("agent/",)
#: Отметка, по которой видно, что тело собрано механизмом. Тело, правленное
#: человеком, шаг не переписывает: он источник заголовка, а не хозяин страницы.
MARK: Final = "Изменение открыто конвейером от лица владельца"
#: Согласие отдать изменение очереди. Ставит его МЕХАНИЗМ, а не человек: ветка
#: с приставкой конвейера и есть заявленное согласие — окно резало её под
#: задачу, а не для того, чтобы изменение стояло зелёным и ждало.
#:
#: Приём взят у соседа по семье, где он обкатан: там согласие ставится сразу
#: при открытии, а не ждёт обхода по расписанию, и метка работает не только
#: включателем, но и СЛЕДОМ — по ней видно, что изменение отдано автоматике.
CONSENT: Final = "automerge"
#: Отзыв согласия человеком. Сильнее согласия и переживает повторный заход:
#: «метку ещё не ставили» и «поставили и сняли» по состоянию изменения
#: неразличимы, поэтому снятое согласие вернулось бы следующим же толчком.
#: Увидев эту метку, шаг согласия не ставит, а стоящее — снимает.
HOLD: Final = "hold"

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
#: «Не настроено» намеренно НЕ единица. Единицу отдаёт сам Python при любом
#: необработанном сбое — включая ImportError, который случается до входа в
#: main и которому шаг себя защитить не может. Пока коды совпадали, сломанный
#: шаг печатал «секрет не задан» и оставлял прогон зелёным: тихий запасной
#: путь (045), замаскированный под объявленное состояние. Теперь зелёными
#: считаются только объявленные коды, всё прочее — отказ (068).
EXIT_NOT_CONFIGURED: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «открыто»."""


def git(*args: str) -> str:
    """Зовёт git, обращая отказ в третий исход."""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, check=True, text=True, encoding="utf-8"
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise NotRun(f"git {' '.join(args)} → {report.cut(str(detail))}") from exc


def changed_files(branch: str, base: str) -> list[str]:
    """Файлы, тронутые веткой относительно базы.

    Список читается по NUL (`-z`): без него git экранирует имена с пробелами и
    не-ASCII, построенный путь не разрешается, и файл молча выпадает из
    обработки — метка зоны не выставится, и никто этого не заметит (165).
    """
    merge_base = git("merge-base", f"origin/{base}", branch).strip()
    out = git("diff", "--name-only", "-z", f"{merge_base}...{branch}")
    return [name for name in out.split("\0") if name]


def describe(branch: str, base: str) -> tuple[str, str]:
    """Собирает заголовок и тело изменения из коммитов ветки."""
    merge_base = git("merge-base", f"origin/{base}", branch).strip()
    log = git("log", "--reverse", "--format=%s", f"{merge_base}..{branch}")
    subjects = [line for line in log.splitlines() if line]
    if not subjects:
        raise NotRun(f"в ветке {branch} нет коммитов сверх {base} — открывать нечего (075)")

    title = subjects[0] if len(subjects) == 1 else f"{subjects[0]} (+{len(subjects) - 1})"
    # Тела разделяются НУЛЕВЫМ байтом, а не строкой «---»: разделитель обязан
    # быть таким, какого в теле коммита не бывает, иначе граница подделывается
    # текстом. Разбор идёт по одному телу — склеенные документы неразличимы для
    # разметки, и незакрытая вставка одного коммита съедала связь другого.
    log_bodies = git("log", "--reverse", "--format=%B%x00", f"{merge_base}..{branch}")
    bodies = log_bodies.split("\0")

    # Связь читается общим модулем, а не своей регуляркой: у гейта разметки она
    # была другой, и строка «Refs #2, #29» для шага открытия не существовала.
    links = changerefs.links_in_all(bodies)
    if not links:
        raise NotRun(
            "ни один коммит ветки не называет задачу: ни «Closes #N», ни «Refs #N». "
            "Изменение без связи гейт разметки отвергнет, и открывать его молча — "
            "значит отдать красное туда, где предмет виден уже здесь (075)"
        )

    lines = ["## Что в изменении", ""]
    lines += [f"- {subject}" for subject in subjects]
    # По строке на задачу: ключевое слово площадка читает у каждого номера
    # отдельно, и список после одного глагола закрывает только первую задачу.
    lines += ["", "## Связь с задачами", ""] + [str(link) for link in links]

    # Снятие находки едет вместе с работой: строка из коммита попадает в тело
    # изменения, а механизм находок читает именно тело слитого изменения. Без
    # переноса «снятие вместе с работой» держалось бы тем, что кто-то вспомнит
    # дописать описание руками.
    resolved = changerefs.resolved_in_all(bodies)
    if resolved:
        lines += ["", "## Разобранные находки", ""]
        lines += [f"Разобрано: {mark}" for mark in resolved]

    # Отметка пункта задачи едет тем же путём и по той же причине: объявление
    # живёт в коммите, а отмечает пункт шаг слияния — и читает он ТЕЛО
    # ИЗМЕНЕНИЯ. Без переноса объявление до него не доезжает вовсе.
    #
    # ЗАМЕР 09.09.2026: перенос снятия находок был, а перенос отметки — нет,
    # хотя механизмы близнецы. Два слияния подряд объявили пункт закрытым и не
    # отметили ничего; механизм честно сказал «пункт не найден», потому что в
    # теле изменения его действительно не было.
    closed = changerefs.closed_items_in_all(bodies)
    if closed:
        lines += ["", "## Закрытые пункты задач", ""]
        lines += [f"Закрывает пункт: {item}" for item in closed]

    lines += [
        "",
        "---",
        "",
        f"{MARK}: операция, несущая",
        "личность человека, из агентского окна не выполняется (правило 131).",
    ]
    return title, "\n".join(lines)


def sync_description(
    repo: str, number: int, token: str, title: str, body: str, dry_run: bool
) -> None:
    """Приводит описание открытого изменения к тому, что говорят коммиты.

    Шаг обязан быть идемпотентным целиком: изменение, открытое до правки
    механизма, иначе навсегда остаётся с телом, собранным по старому чтению, —
    и гейт разметки отвергает его на каждом прогоне, а починить это нечем,
    кроме рук.

    Тело, правленное человеком, не переписывается: отметка `MARK` отличает
    собранное механизмом от написанного. Затирать чужой текст своим — цена,
    которой идемпотентность не стоит.
    """
    current = ghrest.request("GET", f"repos/{repo}/pulls/{number}", token) or {}
    if MARK not in str(current.get("body") or ""):
        print("тело изменения писал человек — механизм его не переписывает")
        return
    if current.get("title") == title and current.get("body") == body:
        return
    if dry_run:
        print(f"обновило бы описание #{number}")
        return
    ghrest.request("PATCH", f"repos/{repo}/pulls/{number}", token, {"title": title, "body": body})
    print(f"описание #{number} приведено к коммитам ветки")


def apply_zones(repo: str, number: int, token: str, branch: str, base: str, dry_run: bool) -> None:
    """Доставляет изменению зоны, выведенные из тронутых файлов.

    ЗОНЫ СТАВИТ ТОТ, КТО ОТКРЫЛ. Метка — вход механизма (064), и гейт разметки
    требует зону: изменение, открытое без неё, конвейер тут же отвергает за
    собственную недоработку.

    Ставятся ТОЛЬКО зоны: они выводятся из путей состава машинно, а род задачи
    — суждение автора, и угадывать его нечем.

    Вызывается и при создании, и когда изменение уже открыто: POST меток
    добавляет, а не заменяет, поэтому повтор безвреден, а вот пропуск —
    необратим.
    """
    zones = sorted(labels.zones_for(labels.load(), changed_files(branch, base)))
    if not zones:
        print(
            "зоны не выведены: тронутое не покрыто путями состава — "
            "разметку поставит человек, и гейт об этом скажет"
        )
        return
    if dry_run:
        print(f"проставил бы зоны: {', '.join(zones)}")
        return
    ghrest.request("POST", f"repos/{repo}/issues/{number}/labels", token, {"labels": zones})
    print(f"проставлены зоны: {', '.join(zones)}")


def apply_consent(repo: str, number: int, token: str, marks: set[str], dry_run: bool) -> None:
    """Отдаёт изменение очереди — или снимает согласие, если стоит стоп-метка.

    СОГЛАСИЕ СТАВИТ МЕХАНИЗМ. Ветка с приставкой конвейера и есть заявленное
    согласие: окно резало её под задачу. Ждать, пока кто-то повесит метку
    рукой, значит оставить зелёное изменение стоять — ровно та беда, от которой
    очередь и заведена.

    СТОП-МЕТКА СИЛЬНЕЕ И ПЕРЕЖИВАЕТ ЗАХОД. Отличить «метку ещё не ставили» от
    «поставили и сняли» по состоянию изменения нельзя — оно одинаковое, — и
    снятое человеком согласие вернулось бы следующим толчком. Поэтому отзыв
    выражается явно: `hold` не только останавливает очередь, но и снимает
    согласие, чтобы след не врал.

    Отказ разметки шаг не роняет: изменение уже открыто, и терять открытие
    из-за метки — худший размен (084).
    """
    if dry_run:
        print(f"согласие {'сняло бы' if HOLD in marks else 'проставило бы'}: {CONSENT}")
        return
    if HOLD in marks:
        # Снимать нечего — обычное состояние повторного захода, а не отказ.
        # Толчков в ветку с висящей стоп-меткой бывает много, и каждый звал
        # DELETE по уже снятой метке: площадка отвечала 404, а механизм
        # печатал «согласие не проставлено» — то есть жаловался на исправно
        # работающую отмену (045).
        if CONSENT not in marks:
            print(f"согласия нет и не будет: стоит стоп-метка «{HOLD}»")
            return
        path = f"repos/{repo}/issues/{number}/labels/{ghrest.quote(CONSENT)}"
        try:
            ghrest.request("DELETE", path, token)
            print(f"снято согласие «{CONSENT}»: стоит стоп-метка «{HOLD}»")
        except ghrest.NotFound:
            # Гонка со вторым заходом или с рукой человека: метки уже нет, и
            # это тот же успех, только достигнутый не нами.
            print(f"согласия уже нет: стоп-метка «{HOLD}» на месте")
        except ghrest.TransportError as exc:
            print(f"согласие не снято: {exc} — стоп-метка держит очередь и без этого")
        return

    try:
        ghrest.request("POST", f"repos/{repo}/issues/{number}/labels", token, {"labels": [CONSENT]})
        print(f"проставлено согласие: {CONSENT}")
    except ghrest.TransportError as exc:
        print(f"согласие не проставлено: {exc} — изменение открыто, метку ставит человек")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--base", default="main")
    parser.add_argument("--dry-run", action="store_true", help="показать, но не открывать")
    args = parser.parse_args(argv)

    try:
        if not args.repo or not args.branch:
            raise NotRun("не названы репозиторий или ветка")

        if not args.branch.startswith(PREFIXES):
            print(
                f"ветка «{args.branch}» без объявленной приставки "
                f"({', '.join(PREFIXES)}) — изменение не открывается.\n"
                "Имя ветки здесь переключатель поведения (003), а не оформление."
            )
            return EXIT_OK

        token = os.environ.get("MERGE_QUEUE_TOKEN", "")
        if not token:
            print(
                "не настроено: нет токена владельца (MERGE_QUEUE_TOKEN).\n"
                "Изменение придётся открыть руками, и автором станет тот, кто открыл.\n"
                "На токен прогона шаг не переходит намеренно: это дало бы ровно ту\n"
                "подмену авторства, ради которой он заведён (131).",
                file=sys.stderr,
            )
            return EXIT_NOT_CONFIGURED

        owner = args.repo.split("/")[0]
        head = f"{owner}:{args.branch}"
        query = urllib.parse.urlencode({"head": head, "state": "open"})
        existing = ghrest.request("GET", f"repos/{args.repo}/pulls?{query}", token) or []
        if existing:
            number = existing[0]["number"]
            print(f"изменение для ветки уже открыто: #{number} — второе не заводится")
            # Зоны доставляются и здесь, а не только при создании. Иначе отказ
            # на шаге разметки необратим: изменение уже открыто, следующий
            # прогон уходит этой веткой и выходит с нулём, ни разу не
            # попытавшись доставить метки, — а гейт разметки продолжает его
            # отвергать. Шаг обязан быть идемпотентным целиком, а не наполовину.
            apply_zones(args.repo, number, token, args.branch, args.base, args.dry_run)
            marks = {str(item.get("name", "")) for item in existing[0].get("labels") or []}
            apply_consent(args.repo, number, token, marks, args.dry_run)
            title, body = describe(args.branch, args.base)
            sync_description(args.repo, number, token, title, body, args.dry_run)
            return EXIT_OK

        title, body = describe(args.branch, args.base)
        if args.dry_run:
            print(f"открыло бы: {title}\n\n{body}")
            return EXIT_OK

        created = ghrest.request(
            "POST",
            f"repos/{args.repo}/pulls",
            token,
            {"title": title, "body": body, "head": args.branch, "base": args.base, "draft": False},
        )
        number = created["number"]
        print(f"открыто изменение #{number}: {created['html_url']}")
        apply_zones(args.repo, number, token, args.branch, args.base, args.dry_run)
        # Только что открытое изменение стоп-метки нести не может: её ставит
        # человек, а он его ещё не видел.
        apply_consent(args.repo, number, token, set(), args.dry_run)
        print(
            "Проба, а не доверие (135): автор в общей ветке после слияния обязан\n"
            "стать человеком. Не стал — механизм неверен, и видно это сразу."
        )
        return EXIT_OK
    except (NotRun, labels.BadConfig, ghrest.TransportError) as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
