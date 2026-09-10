"""Находки внешнего взгляда переживают слияние: у них есть адресат.

ПОЧЕМУ КОММЕНТАРИЯ НЕ ХВАТАЕТ. Пока изменение открыто, комментарий ревьюера и
есть адресат — он на глазах у автора. После слияния изменение уходит из списка
открытых, и туда больше никто не смотрит: находка формально существует и
фактически недоступна. Это правило 142 на другом предмете — не красное по
расписанию, а чужой разбор.

Замер соседа, из-за которого механизм и появился: из 29 слитых изменений с
прогоном ревью вердикт успел к слиянию у 10. Девятнадцать раз работа канала
пропала целиком, а однажды вердикт опоздал на 2,3 минуты, и две верные находки
уехали в общую ветку.

ПОЧЕМУ ЗАДАЧА, А НЕ КРАСНОЕ. Трекер — первый источник работы (091) и
единственный, куда окно смотрит обязательно. Красное на необязательном канале
слияние держать не должно (084): находка ревью советует, а не запрещает.

ПОЧЕМУ ОДНА ЖИВАЯ, А НЕ ПО ЗАДАЧЕ НА ИЗМЕНЕНИЕ. Копия на каждый прогон завалила
бы трекер и приучила листать его мимо. Тело обновляется по месту, а находится
задача по скрытому маркеру, а не по совпадению заголовка: заголовок правят.

СНИМАЕТ ЗАПИСЬ МЕХАНИЗМ, А НЕ ГАЛОЧКА. У каждой записи есть отпечаток — семь
знаков от хэша заголовка. Автор починки называет его строкой
``Разобрано: <отпечаток>`` в теле своего изменения, и следующий заход уносит
запись. Приём тот же, которым площадка закрывает задачу по слову ``Closes``:
снятие едет вместе с работой, а не отдельным жестом, который забудут (002).

ОТПЕЧАТОК ОТ ЗАГОЛОВКА, А НЕ ОТ «ФАЙЛ:СТРОКА». Адрес в файле сдвигается первой
же правкой выше по нему; заголовок находки переживает починку, ради которой и
назван.

ФОРМАТ СОВПАДАЕТ С СОСЕДСКИМ НАМЕРЕННО. Каталог держит свою реализацию того же
механизма, и когда он станет потребителем общего, разошедшиеся форматы стоили
бы переноса записей. Совпадают: строки ``НАХОДКА:`` и ``ВЕРДИКТ: находок N``,
вид записи в теле задачи, отпечаток и строка снятия. Расходится транспорт —
здесь REST стандартной библиотекой, у соседа ``gh`` (правило 001).

Исходы (правило 039): ``0`` записывать нечего · ``1`` есть незакрытые находки ·
``2`` механизм не отработал.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from difflib import SequenceMatcher
from typing import Any, Final

import changerefs
import findings
import ghrest

MARKER: Final = findings.MARKER
TITLE: Final = findings.TITLE

VERDICT_RE: Final = re.compile(r"^ВЕРДИКТ:\s*находок\s+(\d+)\s*$", re.I | re.M)
#: Вес — в самой строке находки: `НАХОДКА[дефект]: …`. Скобки необязательны,
#: и отсутствие веса не подставляет самый лёгкий, а объявляется отдельно.
FINDING_RE: Final = re.compile(r"^НАХОДКА(?:\[\s*([^\]]+?)\s*\])?:\s*(\S.*?)\s*$", re.I | re.M)
WEIGHTS: Final = findings.WEIGHTS
UNWEIGHED: Final = findings.UNWEIGHED
Entry = findings.Entry
ENTRY_RE: Final = findings.ENTRY_RE

EXIT_NOTHING: Final = 0
EXIT_BROKEN: Final = 2
#: Единицу отдаёт сам Python при необработанном сбое, поэтому объявленным
#: состоянием она быть не может: иначе сломанный механизм читается как
#: работающий. Объявленные исходы — 0, 2 и 3; всё прочее отказ (068).
EXIT_PENDING: Final = 3


class NotRun(RuntimeError):
    """Механизм не отработал: третий исход, а не «находок нет»."""


def fingerprint(title: str) -> str:
    """Семь знаков от хэша заголовка находки."""
    return hashlib.sha1(" ".join(title.split()).encode()).hexdigest()[:7]


#: Адрес в дереве, названный находкой: `путь:строка` или `путь:строка-строка`.
#: Формат требуется от ревьюера подсказкой — по нему находка узнаётся заново,
#: когда её пересказали другими словами.
ADDRESS_RE: Final = re.compile(r"\b([\w./-]+\.\w+:\d+(?:-\d+)?)")

#: Насколько два заголовка должны совпасть, чтобы считаться одной находкой.
#: Величина не подобрана на глаз: замер 10.09.2026 по 50 парам в реестре #23
#: дал 0.960 у настоящего дубля и 0.400 у ближайшей пары РАЗНЫХ находок — между
#: ними нет ни одной пары. Порог поставлен в этот пустой промежуток; двигать его
#: имеет смысл, только если замер покажет другое.
SAME_ENOUGH: Final = 0.85


def addresses(title: str) -> frozenset[str]:
    """Адреса в дереве, названные находкой.

    ТОЧНЫЙ ПРИЗНАК ТОЖДЕСТВА, И ОН СИЛЬНЕЕ СХОДСТВА СЛОВ. Пересказ меняет
    формулировку, но не место: «вторая точка вызова (scripts/ci_complete.py:341)»
    и «точка вызова scripts/ci_complete.py:341» — одна находка, и адреса у них
    совпадают дословно.

    Работает это ровно потому, что формат адреса ТРЕБУЕТСЯ от ревьюера. Без
    единого написания признак вырождается в сходство прозы, и тогда решает
    порог, а не факт.
    """
    return frozenset(ADDRESS_RE.findall(title))


def same_finding(one: str, other: str) -> bool:
    """Одна ли это находка, названная дважды.

    Два признака, и они разной силы. Совпавшие адреса — точный: место в дереве
    пересказ не меняет. Сходство слов — сеть под ним: находка может не назвать
    адреса вовсе, и тогда узнать её больше не по чему.

    Ошибаться здесь можно в обе стороны, и цены разные: лишняя запись стоит
    строки в реестре, а слипшиеся находки стоят потерянной находки. Поэтому
    сходство спрашивается ПОСЛЕ адресов и с порогом, стоящим в пустоте между
    замеренными значениями, а не посередине шкалы.

    СРАВНИВАЮТСЯ СЛОВА, А НЕ ЗНАКИ, и это не мелочь. Посимвольное сходство
    рушится от перестановки слов — «не может измениться» и «измениться не
    может» дают 0.827, то есть НИЖЕ порога, хотя это одна и та же фраза.
    Пословное на том же примере даёт 0.857, а на живых данных ещё и шире
    разводит дубль с чужой находкой: 0.960 против 0.400 (по знакам было 0.986
    против 0.514).
    """
    here, there = addresses(one), addresses(other)
    if here and here == there:
        return True
    return SequenceMatcher(None, one.lower().split(), other.lower().split()).ratio() >= SAME_ENOUGH


def existing_mark(entries: dict[str, Entry], pr: int, title: str) -> str | None:
    """Отпечаток уже лежащей записи о ТОЙ ЖЕ находке, если она есть.

    Ищется только среди находок ТОГО ЖЕ изменения: одна и та же беда в двух
    разных изменениях — это две находки, и снимать их надо по отдельности.
    """
    for mark, entry in entries.items():
        if entry.pr == pr and same_finding(entry.title, title):
            return mark
    return None


def weight_of(raw: str) -> str:
    """Вес из строки находки: из объявленной шкалы либо «без веса».

    Слово вне шкалы весом не считается и НЕ приводится к ближайшему: приведение
    решило бы за ревьюера, а объявленное «без веса» видно и разбирающему, и
    тому, кто правит подсказку ревью (154).
    """
    cleaned = " ".join(raw.strip("*_` ").split()).lower()
    return cleaned if cleaned in WEIGHTS else UNWEIGHED


def findings_of(comments: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Находки ревьюера парами «вес, заголовок» — по порядку и без повторов."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for comment in comments:
        for raw_weight, title in FINDING_RE.findall(comment.get("body") or ""):
            cleaned = " ".join(title.strip("*_` ").split())
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                found.append((weight_of(raw_weight), cleaned))
    return found


def verdict_of(comments: list[dict[str, Any]]) -> int | None:
    """Число из последней строки вердикта; None — вердикта нет вовсе."""
    verdict: int | None = None
    for comment in comments:
        for number in VERDICT_RE.findall(comment.get("body") or ""):
            verdict = int(number)
    return verdict


parse_entries = findings.parse_entries


def render_body(entries: dict[str, findings.Entry]) -> str:
    """Собирает тело живой задачи: заметки, а не счётчики.

    Записывается заголовок находки, а не число: «находок 2» не отвечает на
    вопрос, что делать, — за этим пришлось бы идти в слитое изменение.
    """
    lines = [
        MARKER,
        "",
        "> **Читатель:** окно, берущее работу. Это адресат находок внешнего",
        "> взгляда, переживающий слияние.",
        "",
        "Вес — из объявленной шкалы: "
        + " · ".join(f"`{name}` — {why}" for name, why in WEIGHTS.items())
        + f". `{UNWEIGHED}` значит, что ревьюер его не назвал.",
        "",
        "Запись снимается строкой `Разобрано: <отпечаток>` в теле изменения,",
        "которое её починило — снятие едет вместе с работой, а не отдельным",
        "жестом, который забудут. Задачу закрывает человек: механизм не знает,",
        "разобрана находка или просто надоела.",
        "",
    ]
    if entries:
        lines.append("## Не разобрано")
        lines.append("")
        # Порядок — по весу, а не по приходу: тяжёлое разбирают раньше, и
        # решать это должен не порядок появления (053).
        #
        # НЕНАЗВАННЫЙ ВЕС ИДЁТ ПЕРВЫМ, А НЕ ПОСЛЕДНИМ. Прежде он получал место
        # ЗА самой лёгкой категорией — то есть на практике трактовался как
        # «легче замечания», ровно в ту сторону, которую модуль обещает не
        # выбирать. Обещание и код разошлись молча, и нашёл это поздний взгляд
        # по общей ветке на #73.
        #
        # Первым — не потому, что «тяжелее», а потому, что неизвестное требует
        # взгляда, чтобы перестать быть неизвестным: очередь ведёт к разбору, а
        # не расставляет по важности. Ошибаться здесь можно только в сторону
        # «посмотреть лишний раз» (051).
        order = {name: place for place, name in enumerate(WEIGHTS)}
        for mark, entry in sorted(
            entries.items(),
            key=lambda item: (order.get(item[1].weight, -1), item[1].pr),
        ):
            lines.append(f"- `{mark}` · #{entry.pr} · {entry.weight} — {entry.title}")
    else:
        lines.append("## Не разобрано")
        lines.append("")
        lines.append("Пусто — все находки названы разобранными.")
    return "\n".join(lines) + "\n"


live_issue = findings.live_issue


def resolved_marks(repo: str, token: str, limit: int = ghrest.MERGED_WINDOW) -> set[str]:
    """Отпечатки, названные разобранными в последних слитых изменениях."""
    marks: set[str] = set()
    for item in ghrest.merged_changes(repo, token, limit):
        marks.update(changerefs.resolved_in(item.get("body") or ""))
    return marks


def save(repo: str, token: str, entries: dict[str, findings.Entry], apply: bool) -> None:
    """Записывает живую задачу: обновляет по месту или заводит одну."""
    number, _ = live_issue(repo, token)
    body = render_body(entries)
    if not apply:
        print(
            f"записал бы {len(entries)} заметок " + (f"в #{number}" if number else "в новую задачу")
        )
        return
    if number is None:
        created = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"заведена живая задача #{created['number']}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"живая задача #{number} обновлена: заметок {len(entries)}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr", type=int, help="изменение, чей вердикт разбирается")
    parser.add_argument("--sweep", action="store_true", help="только уборка разобранного")
    parser.add_argument("--apply", action="store_true", help="записывать, а не показывать")
    args = parser.parse_args(argv)

    try:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        if not args.sweep and args.pr is None:
            raise NotRun("не назван предмет разбора: --pr или --sweep")

        _, body = live_issue(args.repo, token)
        entries = parse_entries(body)

        if args.pr is not None:
            comments = list(ghrest.paginate(f"repos/{args.repo}/issues/{args.pr}/comments", token))
            verdict = verdict_of(comments or [])
            if verdict is None:
                raise NotRun(
                    f"в изменении #{args.pr} нет строки вердикта — ревьюер не дописал ответ "
                    "или не отработал вовсе; это не «находок нет» (075)"
                )
            titles = findings_of(comments or [])
            if len(titles) != verdict:
                # Расхождение названо, а не сглажено: вердикт и строки находок
                # пишет один и тот же ответ, и если они спорят, доверять нечему.
                print(
                    f"::warning::вердикт по #{args.pr} говорит «находок {verdict}», "
                    f"а строк находок {len(titles)} — записаны строки",
                    file=sys.stderr,
                )
            renamed = 0
            for weight, title in titles:
                # ЗАПИСЬ ИЩЕТСЯ ПРЕЖДЕ, ЧЕМ ЗАВОДИТСЯ. Отпечаток берётся от
                # заголовка, а заголовок ревьюер на новом заходе пересказывает
                # — и та же находка ложилась второй записью. Замер 10.09.2026:
                # четыре записи об одной беде на #149 и две на #148.
                #
                # Прежний отпечаток при этом СОХРАНЯЕТСЯ: по нему находку уже
                # могли назвать разобранной в теле изменения, и смена отпечатка
                # обессмыслила бы снятие.
                mark = existing_mark(entries, args.pr, title)
                if mark is not None:
                    renamed += 1
                    entries[mark] = findings.Entry(args.pr, weight, entries[mark].title)
                    continue
                entries[fingerprint(title)] = findings.Entry(args.pr, weight, title)
            said = f"из #{args.pr}: вердикт {verdict}, строк находок {len(titles)}"
            if renamed:
                said += f", из них уже лежат под своим отпечатком {renamed}"
            print(said)

        # Уборка идёт ПОСЛЕ записи, а не вместо: обратный порядок терял бы
        # заметку, снятую и заново найденную одним заходом.
        swept = resolved_marks(args.repo, token) & set(entries)
        for mark in swept:
            entries.pop(mark, None)
        if swept:
            print(f"снято как разобранное: {', '.join(sorted(swept))}")

        save(args.repo, token, entries, args.apply)
    except (NotRun, ghrest.TransportError) as exc:
        print(f"механизм не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    return EXIT_PENDING if entries else EXIT_NOTHING


if __name__ == "__main__":
    raise SystemExit(main())
