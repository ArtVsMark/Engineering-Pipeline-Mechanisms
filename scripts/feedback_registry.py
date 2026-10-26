#!/usr/bin/env python3
"""Реестр записей соседей о наших механизмах: живая задача с очередью на вердикт (#1665).

КАНАЛ ОТ СОСЕДЕЙ К НАМ ЗАКАНЧИВАЕТСЯ У НАС, А НЕ В ИХ ТРЕКЕРЕ. Сосед пишет
запись разделом `feedback:` своего `.pipeline.yml` (форма — `feedback_form`),
ночной обход семьи (`family_uptake`) читает её тем же клоном, что и вызовы
шагов, а этот механизм раскладывает собранное по живой задаче: записи без
нашего вердикта — очередью, с вердиктом — списком. Ведёт задачу механизм, а не
рука (049); вердикт пишем мы, в файле вердиктов (`paths.FEEDBACK_VERDICTS`), по
ключу `владелец/репозиторий:вид/слаг`.

ВОЗРАСТ ЗАПИСИ — ПЕРВАЯ ВСТРЕЧА, ЗАПИСАННАЯ МЕХАНИЗМОМ (решение владельца
26.10.2026, #1665). В записи соседа даты нет, и форма её не меняется: день,
когда обход впервые увидел ключ, хранится скрытым блоком `SEEN` в теле задачи
— тем же приёмом, что «Записано» у реестра находок. Ключ уходит из блока,
только когда сосед прочитан чисто и записи у него больше нет: непрочитанный
клон или битый раздел — не «записи нет», и день первой встречи не
сбрасывается (045).

ГРАНИЦЫ НАЗВАНЫ (046). Ключ держится на имени репозитория соседа:
переименование рвёт связь, и вердикт старого ключа назван сиротой, а не
потерян. Задача стоит рядом с удалённой — сосед удалил запись, а вердикт
остался — и это тот же список сирот: решать, снимать ли вердикт, нам.

Исходы (правило 039): ``0`` задача записана или уже описывает состояние ·
``2`` не отработал — файл обхода или вердиктов не читается, площадка молчит.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import family_uptake
import feedback_form
import findings
import ghrest
import paths
import report

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Метка живой задачи реестра.
MARKER: Final = findings.marker("feedback-registry")
#: Заголовок живой задачи.
TITLE: Final = "Записи соседей о наших механизмах: очередь на вердикт"
#: Скрытый блок первых встреч: `<!-- feedback-seen: {"ключ": "ГГГГ-ММ-ДД"} -->`.
SEEN_RE: Final = re.compile(r"<!-- feedback-seen: (?P<json>\{.*?\}) -->", re.DOTALL)
#: Начало строки с днём сборки: сверка «то же состояние» её не читает.
DATED: Final = "Собрано:"


class NotRun(RuntimeError):
    """Реестр не собран: третий исход, а не пустая очередь."""


@dataclass(frozen=True)
class Row:
    """Запись соседа с ключом вердикта."""

    repo: str
    record: feedback_form.Record

    @property
    def key(self) -> str:
        """Ключ вердикта — один для формы, реестра и файла вердиктов (214)."""
        return feedback_form.key_of(self.repo, self.record)


@dataclass(frozen=True)
class Collected:
    """Что принёс обход: записи, битые разделы и непрочитанные клоны."""

    rows: tuple[Row, ...]
    #: Сосед → почему его раздел `feedback:` не прочитан.
    broken: dict[str, str]
    unread: tuple[str, ...]

    def unseen(self) -> set[str]:
        """Соседи, чьих записей этой ночью не видно: по ним «нет» не судится."""
        return {repo.lower() for repo in (*self.broken, *self.unread)}


def quoted(text: object) -> str:
    """Чужой текст в тело задачи: одной строкой и без угловых скобок (взгляд на #1710, 085).

    Замер, след, причина битого раздела и имя соседа — ввод соседа, а не наш.
    Сырыми они давали нашей задаче чужую метку живой задачи (`findings.MARKER`
    реестра находок — и `findings.live_issue` взял бы её за другой реестр),
    поддельный блок дней первой встречи или строку `## …` и `Собрано:` из
    многострочного замера.
    Одна строка не начнёт ни заголовка, ни пункта; без `<` и `>` не откроет
    комментария разметки — а прочитать текст человеку это не мешает.
    """
    return " ".join(str(text).split()).replace("<", "&lt;").replace(">", "&gt;")


def collected(uptake: Any) -> Collected:
    """Записи соседей из файла обхода; файл не той формы — `NotRun`.

    Ключа `feedback` нет — файл старше канала, и «записей нет» сказать нельзя:
    отказ, а не пустая очередь (045).
    """
    if not isinstance(uptake, dict) or not isinstance(uptake.get("feedback"), list):
        raise NotRun("в файле обхода нет раздела feedback — обход старше канала или не тот файл")
    rows: list[Row] = []
    broken: dict[str, str] = {}
    for block in uptake["feedback"]:
        try:
            repo = str(block["repo"])
            if block.get("broken"):
                broken[repo] = str(block["broken"])
            rows += [Row(repo, feedback_form.Record(**one)) for one in block.get("records", [])]
        except (KeyError, TypeError, AttributeError) as exc:
            raise NotRun(f"запись обхода не той формы: {exc!r}") from exc
    unread = tuple((uptake.get("projects") or {}).get("unread_repos") or ())
    return Collected(tuple(rows), broken, unread)


def seen_in(body: str) -> dict[str, date]:
    """Первые встречи из тела задачи; блока нет или он битый — пусто.

    Битый блок — не отказ: задача реестра — канал, а не источник записей, и
    потеря дат стоит пересчёта сроков с сегодня, а не пропажи реестра (084).
    Об этом говорится строкой, а не молчанием.
    """
    # ПОСЛЕДНИЙ БЛОК, А НЕ ПЕРВЫЙ: настоящий механизм ставит его концом тела,
    # и чужой текст выше, даже пройди он мимо `quoted`, его не подменит.
    blocks = list(SEEN_RE.finditer(body or ""))
    if not blocks:
        return {}
    found = blocks[-1]
    try:
        raw = json.loads(found["json"])
        return {str(key): date.fromisoformat(str(day)) for key, day in raw.items()}
    except ValueError, AttributeError:
        print("::warning::блок первых встреч в задаче реестра не разобран — сроки с сегодня")
        return {}


def seen_now(said: Collected, before: dict[str, date], today: date) -> dict[str, date]:
    """Первые встречи после этой ночи: новые ключи — сегодня, ушедшие — вон.

    Ключ непрочитанного соседа остаётся с прежним днём: его записей не видно,
    а «не видно» не значит «нет».
    """
    hidden = said.unseen()
    kept = {key: day for key, day in before.items() if key.split(":", 1)[0] in hidden}
    for row in said.rows:
        kept[row.key] = before.get(row.key, today)
    return dict(sorted(kept.items()))


def render(
    said: Collected,
    verdicts: dict[str, feedback_form.Verdict],
    seen: dict[str, date],
    today: date,
) -> str:
    """Тело живой задачи: очередь без вердикта, вердикты, непрочитанное и сироты."""
    waiting = [row for row in said.rows if row.key not in verdicts]
    judged = [row for row in said.rows if row.key in verdicts]
    keys = {row.key for row in said.rows}
    hidden = said.unseen()
    orphans = sorted(
        key for key in verdicts if key not in keys and key.split(":", 1)[0] not in hidden
    )

    def first(row: Row) -> str:
        return seen.get(row.key, today).strftime("%d.%m.%Y")

    lines = [
        MARKER,
        "",
        "> **Читатель:** владелец, отвечающий соседям вердиктом, и окно, берущее",
        "> запись в работу. Запись пишет сосед в своём `.pipeline.yml`, вердикт — мы,",
        f"> в `{paths.FEEDBACK_VERDICTS}` по ключу `владелец/репозиторий:вид/слаг` (#1665).",
        "",
        "Тело переписывается целиком ночным обходом семьи (`badges.yml`) и ведётся",
        "механизмом, а не рукой (049): правка руки пропадёт следующей сборкой.",
        "",
        f"{DATED} {today.strftime('%d.%m.%Y')}.",
        "",
        f"## Без вердикта — {len(waiting)}",
        "",
    ]
    for row in waiting:
        one = row.record
        lines += [
            f"- `{row.key}` · `{one.mechanism}` {one.version} · "
            f"{feedback_form.KINDS[one.kind]} · след {quoted(one.trace)} · замечено {first(row)}",
            f"  - замер: {quoted(one.measured)}",
        ]
    if not waiting:
        lines.append("Пусто.")
    lines += ["", f"## С вердиктом — {len(judged)}", ""]
    for row in judged:
        verdict = verdicts[row.key]
        lines.append(f"- `{row.key}` · {verdict.verdict}: {verdict.said} · замечено {first(row)}")
    if not judged:
        lines.append("Пусто.")
    if said.broken or said.unread:
        lines += ["", f"## Записи не прочитаны — {len(said.broken) + len(said.unread)}", ""]
        lines += [
            f"- {quoted(repo)} — раздел feedback: {quoted(why)}"
            for repo, why in sorted(said.broken.items())
        ]
        lines += [f"- {quoted(repo)} — клон не прочитан обходом" for repo in sorted(said.unread)]
    if orphans:
        lines += ["", f"## Вердикт без записи — {len(orphans)}", ""]
        lines += [
            f"- `{key}` · {verdicts[key].verdict} — записи у соседа нет: снята или ключ сменился"
            for key in orphans
        ]
    block = json.dumps({key: day.isoformat() for key, day in seen.items()}, ensure_ascii=False)
    lines += ["", f"<!-- feedback-seen: {block} -->"]
    return "\n".join(lines) + "\n"


def stable(body: str) -> str:
    """Тело без строки дня сборки: с ней сверка «то же состояние» держалась бы сутки."""
    return findings.undated(body, (DATED,))


def verdicts_at(path: Path) -> dict[str, feedback_form.Verdict]:
    """Вердикты из файла; не читается или не той формы — `NotRun`."""
    try:
        return feedback_form.verdicts_of(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise NotRun(f"файл вердиктов {path} не прочитан: {exc}") from exc
    except feedback_form.NotRun as exc:
        raise NotRun(f"файл вердиктов {path}: {exc}") from exc


def save(
    repo: str,
    token: str,
    said: Collected,
    verdicts: dict[str, Any],
    *,
    apply: bool,
    today: date | None = None,
) -> None:
    """Переписывает живую задачу по месту или заводит одну — как задача карты гейтов.

    Пустой реестр задачи не заводит: адресат без записей — шум. Сухой заход
    называет то же действие, что совершил бы настоящий. `ghrest.TransportError`
    — наверх: зовущий объявляет его третьим исходом.
    """
    today = today or datetime.now(UTC).date()
    number, current = findings.live_issue(repo, token, MARKER)
    seen = seen_now(said, seen_in(current), today)
    body = render(said, verdicts, seen, today)
    if number is None and not (said.rows or said.broken):
        print(f"{'' if apply else report.DRY + ' '}записей соседей нет — задачу реестра не завожу")
        return
    if number is not None and stable(current) == stable(body):
        print(f"задача реестра записей #{number} уже описывает это состояние")
        return
    if not apply:
        print(f"{report.DRY} {'обновил бы' if number else 'завёл бы'} задачу реестра записей")
        return
    if number is None:
        fresh = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"заведена задача реестра записей #{(fresh or {}).get('number')}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"задача реестра записей #{number} обновлена")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: записи из файла обхода и вердикты — в живую задачу."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uptake", type=Path, required=True, help="файл обхода семьи")
    parser.add_argument("--root", type=Path, default=Path("."), help="наше дерево")
    parser.add_argument("--repo", default=family_uptake.OURS, help="наш репозиторий")
    parser.add_argument("--apply", action="store_true", help="записать, а не показать")
    args = parser.parse_args(argv)

    token = ghrest.token_from_env()
    if not token:
        print("реестр записей не собран: нет токена площадки", file=sys.stderr)
        return EXIT_BROKEN
    try:
        said = collected(json.loads(args.uptake.read_text(encoding="utf-8")))
        verdicts = verdicts_at(args.root / paths.FEEDBACK_VERDICTS)
        print(
            f"записей соседей: {len(said.rows)}, с вердиктом "
            f"{sum(row.key in verdicts for row in said.rows)}; "
            f"не прочитано: {len(said.broken) + len(said.unread)}"
        )
        save(args.repo, token, said, verdicts, apply=args.apply)
    except (OSError, ValueError, NotRun, ghrest.TransportError) as exc:
        print(f"реестр записей не собран: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
