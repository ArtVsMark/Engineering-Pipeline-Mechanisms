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
from typing import Any, Final

import ghrest

MARKER: Final = "<!-- review-findings: не удаляйте, по этой строке задача находится снова -->"
TITLE: Final = "Находки внешнего взгляда: не разобранные"

VERDICT_RE: Final = re.compile(r"^ВЕРДИКТ:\s*находок\s+(\d+)\s*$", re.I | re.M)
FINDING_RE: Final = re.compile(r"^НАХОДКА:\s*(\S.*?)\s*$", re.I | re.M)
RESOLVED_RE: Final = re.compile(r"^\s*Разобрано:\s*([0-9a-f]{7})\b", re.I | re.M)
ENTRY_RE: Final = re.compile(r"^- `([0-9a-f]{7})` · #(\d+) — (.+?)\s*$", re.M)

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


def findings_of(comments: list[dict[str, Any]]) -> list[str]:
    """Заголовки находок из комментариев ревьюера — по порядку и без повторов."""
    titles: list[str] = []
    for comment in comments:
        for title in FINDING_RE.findall(comment.get("body") or ""):
            cleaned = " ".join(title.strip("*_` ").split())
            if cleaned and cleaned not in titles:
                titles.append(cleaned)
    return titles


def verdict_of(comments: list[dict[str, Any]]) -> int | None:
    """Число из последней строки вердикта; None — вердикта нет вовсе."""
    verdict: int | None = None
    for comment in comments:
        for number in VERDICT_RE.findall(comment.get("body") or ""):
            verdict = int(number)
    return verdict


def parse_entries(body: str | None) -> dict[str, tuple[int, str]]:
    """Разбирает тело живой задачи обратно в записи по отпечатку."""
    return {mark: (int(pr), title) for mark, pr, title in ENTRY_RE.findall(body or "")}


def render_body(entries: dict[str, tuple[int, str]]) -> str:
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
        "Запись снимается строкой `Разобрано: <отпечаток>` в теле изменения,",
        "которое её починило — снятие едет вместе с работой, а не отдельным",
        "жестом, который забудут. Задачу закрывает человек: механизм не знает,",
        "разобрана находка или просто надоела.",
        "",
    ]
    if entries:
        lines.append("## Не разобрано")
        lines.append("")
        for mark, (pr, title) in sorted(entries.items(), key=lambda item: item[1][0]):
            lines.append(f"- `{mark}` · #{pr} — {title}")
    else:
        lines.append("## Не разобрано")
        lines.append("")
        lines.append("Пусто — все находки названы разобранными.")
    return "\n".join(lines) + "\n"


def live_issue(repo: str, token: str) -> tuple[int | None, str]:
    """Находит живую задачу по скрытому маркеру.

    Списком, а не поиском: поисковый индекс площадки догоняет с задержкой в
    минуты, и за это время механизм заводит вторую задачу вместо одной.
    """
    for item in ghrest.paginate(f"repos/{repo}/issues?state=open", token):
        # REST кладёт изменения в /issues наравне с задачами — отсеиваем.
        if item.get("pull_request") is not None:
            continue
        body = item.get("body") or ""
        if MARKER in body:
            return int(item["number"]), body
    return None, ""


def resolved_marks(repo: str, token: str, limit: int = 30) -> set[str]:
    """Отпечатки, названные разобранными в последних слитых изменениях."""
    marks: set[str] = set()
    items = ghrest.request("GET", f"repos/{repo}/pulls?state=closed&per_page={limit}", token) or []
    for item in items:
        if not item.get("merged_at"):
            continue
        marks.update(mark.lower() for mark in RESOLVED_RE.findall(item.get("body") or ""))
    return marks


def save(repo: str, token: str, entries: dict[str, tuple[int, str]], apply: bool) -> None:
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
            for title in titles:
                entries[fingerprint(title)] = (args.pr, title)
            print(f"из #{args.pr}: вердикт {verdict}, строк находок {len(titles)}")

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
