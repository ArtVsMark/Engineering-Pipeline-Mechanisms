#!/usr/bin/env python3
"""Цепочки находок по одному месту: замер рода «каскад», повторяемый командой.

ЗАЧЕМ. Род «каскад по одному месту» (`.rules/finding-kinds.json`, #746) и
предложение каталогу `a-second-finding-on-one-place-stops-the-patching`
опираются на числа: сколько мест получили находки на двух, трёх, четырёх
изменениях. Первый раз они были сняты разовым сценарием окна — и повторить их
было нечем, кроме памяти этого окна
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
Теперь число — команда:

    python scripts/finding_chains.py --repo <владелец/имя> --last 100
    python scripts/finding_chains.py --repo <владелец/имя> \
        --from 616 --to 743 --at 2026-09-24T19:00:00Z

Отрезок `--from/--to` — номера изменений включительно, и задаются они ОБА: одна
граница без другой читала бы всю историю молча. Отрезок повторяет ИЗМЕНЕНИЯ, но
не числа: поздний взгляд дописывает находки в ленты уже закрытых изменений, и
тот же отрезок завтра даст больше. Числа повторяет `--at`: в счёт идут только
комментарии, последняя правка которых сделана до этого момента (взгляд на #769).
ГРАНИЦА ПОВТОРА НАЗВАНА: правка комментария рукой после `--at` уносит его из
счёта целиком, и тот же `--at` после такой правки даст меньше. Отрезок без
изменений и момент раньше всех комментариев — не нулевой замер, а отказ:
пустое и измеренное неотличимы (045). Лента, прочитанная до момента, но без
находок, — настоящий ноль.

ЛЕНТЫ — ОСНОВНОЙ ВХОД, АРХИВ — ВТОРОЙ (`--archive`, ниже). Находки уходят из
реестра #23 после разбора, но остаются в лентах изменений — в комментариях
взгляда. Замер читает их там тем же разбором СТРОКИ, что и сборщик реестра
(`review_findings.findings_of`, `review_findings.fingerprint`): второй разбор
той же строки разошёлся бы с первым молча. ВХОД У НИХ РАЗНЫЙ, И ЭТО НАЗВАНО:
ленты замер читает только от бота — с `--at` и без него, — а сборщик реестра
и архив автора не смотрят. Строка `НАХОДКА[…]`, процитированная человеком, в
реестр и архив ляжет, а в замер по лентам — нет (взгляд на #789)
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

МЕСТО — ПУТЬ ДО ДВОЕТОЧИЯ. Взгляд называет место одним способом —
`путь/от/корня.py:12` (так требует его подсказка), и путь берётся из начала
заголовка находки. Формы пути перечислены разом, а не по одной (195): с
расширением (`scripts/x.py:12`), без него (`Makefile:3`, `.github/CODEOWNERS:1`)
и с точкой в начале (`.gitignore:3`). Путь пишется латиницей: слово кириллицей
перед двоеточием — проза, а не место. Находка без пути в месте не считается и
названа числом.

ПЕРЕСКАЗ СНИМАЕТСЯ В ПРЕДЕЛАХ ИЗМЕНЕНИЯ, А НЕ ПОПЕРЁК. Одна находка, повторённая
на том же изменении, считается один раз. Та же находка на ДРУГОМ изменении —
это новое звено цепочки: место снова получило находку, и снять её значило бы
занизить глубину и потерять изменение, где находка родилась. В счёте
уникальных находок отпечаток по-прежнему один.

ГРАНИЦА. «Цепочка» здесь — место с находками на нескольких изменениях, а не
«одна цепочка форм»: считать ли их одним предикатом, решает чтение поимённо,
и замер его не заменяет — он печатает места, чтобы было что читать.

ИЗ АРХИВА, А НЕ ИЗ ЛЕНТ (`--archive`, #778). Архив находок на ветке `badges`
хранит каждую находку с изменениями, где она звучала (`seen_on`), и читать
ленты заново ради того же не нужно: сотни запросов к площадке против одного
файла. ЧИСЛА ДВУХ ВХОДОВ НЕ РАВНЫ, И ОТЧЁТ ГОВОРИТ, ЧЕМ СНЯТ (взгляд на #817):
- автор: архив собран, как реестр, по всем комментариям, ленты — только от
  бота; цитата человека в архиве есть;
- отрезок: архив знает только СЛИТЫЕ изменения, ленты — все закрытые; `--last`
  берёт последние N своих;
- полнота: не дошло наполнение до головы — архив говорит это в `gaps`, и отчёт
  печатает эту строку, а не выдаёт отрезок учтённых за последние слитые.
Момента в архиве нет, поэтому `--at` с ним — отказ, а не молча игнорируемый
ключ (045). Чужая форма архива — тоже отказ с причиной, а не трасса.

Исходы (правило 039): ``0`` замер снят · ``2`` не снят (нет токена, площадка
не ответила; по архиву — `--at` с `--archive`, чужая форма архива, пустой
отрезок). Третьего — «снят с находками» — нет: это счёт, а не гейт, и
судить по нему не о чем
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import findings
import ghrest
import review_findings
import unlooked

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Сколько последних закрытых изменений читать, если не сказано иначе.
LAST: Final = 100

#: Место в начале заголовка находки: путь латиницей, затем двоеточие и номер
#: строки. Формы — в докстроке модуля: с расширением, без него, с точкой в начале.
PLACE_RE: Final = re.compile(
    r"^\s*`?(?P<path>(?:[A-Za-z0-9_.-]+/)*\.?[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)`?:\d"
)


@dataclass(frozen=True, slots=True)
class Chains:
    """Замер: сколько находок, мест и как далеко места дошли по изменениям."""

    findings: int
    changes: int
    unplaced: int
    #: место → номера изменений, на которых по нему были находки.
    places: dict[str, list[int]] = field(default_factory=dict)

    def reached(self, depth: int) -> list[str]:
        """Места с находками не меньше чем на `depth` изменениях."""
        return sorted(path for path, prs in self.places.items() if len(prs) >= depth)


def place_of(title: str) -> str:
    """Путь, с которого начинается заголовок находки; пусто — места нет."""
    found = PLACE_RE.match(title)
    return found.group("path") if found else ""


def chains(said: list[tuple[int, str]]) -> Chains:
    """Цепочки по парам «изменение, заголовок находки».

    Повтор снимается в пределах изменения; на другом изменении та же находка —
    новое звено цепочки места (докстрока модуля).
    """
    seen: set[str] = set()
    counted: set[tuple[int, str]] = set()
    places: dict[str, set[int]] = defaultdict(set)
    changes: set[int] = set()
    unplaced: set[str] = set()
    for number, title in said:
        mark = review_findings.fingerprint(title)
        if (number, mark) in counted:
            continue
        counted.add((number, mark))
        seen.add(mark)
        changes.add(number)
        path = place_of(title)
        if not path:
            unplaced.add(mark)
            continue
        places[path].add(number)
    return Chains(
        findings=len(seen),
        changes=len(changes),
        unplaced=len(unplaced),
        places={path: sorted(prs) for path, prs in places.items()},
    )


def moment(said: str) -> datetime:
    """Момент `--at`: ISO со временем и поясом, иначе отказ.

    Строка сравнивалась строкой, и `2026-09-24` отсекала весь день, а
    `…+03:00` сдвигала момент на смещение — молча и с кодом успеха (взгляд на
    #781). Момент без пояса неоднозначен, поэтому тоже отказ.
    """
    try:
        parsed = datetime.fromisoformat(said.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"момент не в ISO: {said}") from exc
    if parsed.tzinfo is None or "T" not in said:
        raise ValueError(f"момент без времени или пояса: {said}")
    return parsed


class Undated(RuntimeError):
    """У комментария нет метки времени — отсекать по моменту нечем."""


def said_at(comment: dict[str, Any]) -> datetime:
    """Когда находки комментария СКАЗАНЫ: время последней правки, а не создания.

    Действие взгляда создаёт комментарий со спиннером и дописывает находки
    правкой в конце захода: по времени создания заход, начатый до `--at`,
    приносил находки, записанные после (взгляд на #781). Граница названа:
    правка рукой после `--at` уносит комментарий из счёта целиком, и тот же
    `--at` после такой правки даст меньше. Меток нет вовсе — отказ с
    причиной, а не падение разбора.
    """
    raw = str(comment.get("updated_at") or comment.get("created_at") or "")
    if not raw:
        raise Undated("у комментария нет метки времени — отсекать по моменту нечем")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Undated(f"метка времени комментария не разбирается: {raw}") from exc


def read_counted(
    repo: str,
    token: str,
    last: int,
    first: int = 0,
    final: int = 0,
    at: datetime | None = None,
) -> tuple[list[tuple[int, str]], int, int]:
    """Находки взгляда из лент закрытых изменений и число прочитанных изменений.

    Отрезок `first..final` (номера включительно) выбирает изменения; без него
    читаются последние `last`. Ленты идут от новых к старым, поэтому за нижней
    границей отрезка чтение останавливается, а не листает историю до конца.
    `at` отсекает комментарии, написанные позже: так числа повторяются, хотя
    поздний взгляд дописывает ленты задним числом.
    """
    said: list[tuple[int, str]] = []
    pulls = ghrest.paginate(f"repos/{repo}/pulls?state=closed&sort=created&direction=desc", token)
    taken = 0
    kept = 0
    for pull in pulls:
        number = int(pull["number"])
        if first or final:
            if final and number > final:
                continue
            if number < first:
                break
        elif taken >= last:
            break
        taken += 1
        comments = [
            one
            for one in ghrest.paginate(f"repos/{repo}/issues/{number}/comments", token)
            if at is None or said_at(one) <= at
        ]
        # СЧИТАЕТСЯ ТОЛЬКО СКАЗАННОЕ БОТОМ — и вердикты, и находки. Реплика
        # человека до `--at` засчитала бы ленту, где взгляд сказал позже (взгляд
        # на #787), а строка `НАХОДКА[…]` в ней — находку, которой взгляд не
        # говорил, и снимала бы отказ снова (взгляд на #789). Признак тот же,
        # что у очереди слияний (`automerge.verdicts_on`): автор — бот.
        #
        # ОТВЕТ ВЕРИФИКАТОРА — НЕ ВЗГЛЯД. Он пишет от бота и может процитировать
        # `ВЕРДИКТ:` и `НАХОДКА[` из находки, которую проверяет; поздний взгляд
        # при этом считается намеренно — он дописывает находки задним числом
        # (взгляд на #827).
        looks = [
            one
            for one in comments
            if (one.get("user") or {}).get("type") == "Bot" and not unlooked.is_verification(one)
        ]
        kept += sum(1 for one in looks if review_findings.verdict_of([one]) is not None)
        said += [(number, found[1]) for found in review_findings.findings_of(looks)]
    return said, taken, kept


def from_archive(
    archive: dict[str, Any], last: int, first: int = 0, final: int = 0
) -> tuple[list[tuple[int, str]], int]:
    """Находки из архива: (изменение, заголовок) на каждое изменение, где звучала.

    Отрезок задаётся так же, как у лент, но берёт другое: `--from/--to` по
    номеру, иначе последние `last` УЧТЁННЫХ архивом, то есть слитых, изменений.
    Ленты берут последние закрытые, неслитые тоже. Второе в ответе — сколько
    изменений отрезок взял.
    """
    counted = sorted({int(one) for one in archive.get("counted") or []}, reverse=True)
    if first or final:
        taken = {number for number in counted if first <= number <= final}
    else:
        taken = set(counted[:last])
    said = [
        (int(number), str(entry.get("title") or ""))
        for entry in (archive.get("findings") or {}).values()
        for number in entry.get("seen_on") or []
        if int(number) in taken
    ]
    return said, len(taken)


def archive_heading(archive: dict[str, Any], taken: int) -> list[str]:
    """Чем снят замер по архиву: вход, отрезок и неполнота — строками отчёта."""
    lines = [
        f"вход: архив находок, {taken} слитых изменений; находки всех авторов, как у"
        " реестра (ленты считают только бота)"
    ]
    gap = findings.unfilled(archive)
    if gap:
        lines.append(f"АРХИВ НЕПОЛОН: {gap} — отрезок взят из учтённых, а не из последних слитых")
    return lines


def report(measured: Chains) -> list[str]:
    """Строки отчёта: числа замера и места, дошедшие до третьего изменения."""
    lines = [
        f"уникальных находок: {measured.findings} на {measured.changes} изменениях"
        f" (без места: {measured.unplaced})",
        f"мест с находками: {len(measured.places)}",
    ]
    lines += [
        f"  на {depth} и более изменениях: {len(measured.reached(depth))}" for depth in (2, 3, 4)
    ]
    lines.append("места на трёх и более изменениях — читать поимённо:")
    lines += [
        f"  {path}: {', '.join(f'#{pr}' for pr in measured.places[path])}"
        for path in measured.reached(3)
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Точка входа: читает ленты изменений и печатает замер цепочек."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--last",
        type=int,
        default=LAST,
        help="сколько последних изменений читать: закрытых по лентам, слитых по архиву",
    )
    parser.add_argument("--from", dest="first", type=int, default=0, help="первый номер отрезка")
    parser.add_argument("--to", dest="final", type=int, default=0, help="последний номер отрезка")
    parser.add_argument("--at", default="", help="момент ISO: комментарии позже него не считаются")
    parser.add_argument(
        "--archive", default="", help="архив находок (findings.json) вместо лент изменений"
    )
    args = parser.parse_args(argv)
    try:
        cut = moment(args.at) if args.at else None
    except ValueError as exc:
        print(f"замер не снят: {exc} — нужен вид 2026-09-24T19:00:00Z", file=sys.stderr)
        return EXIT_BROKEN
    if bool(args.first) != bool(args.final) or (args.first and args.first > args.final):
        print(
            "замер не снят: отрезок задаётся обеими границами, и первая не больше последней "
            f"(--from {args.first or '—'}, --to {args.final or '—'})",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    if args.archive:
        if cut is not None:
            print(
                "замер не снят: в архиве нет моментов, --at с --archive не сочетается",
                file=sys.stderr,
            )
            return EXIT_BROKEN
        try:
            archive = findings.read_archive(Path(args.archive))
        except ValueError as exc:
            print(f"замер не снят: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        said, seen = from_archive(archive, args.last, args.first, args.final)
        if not seen:
            print(
                "замер не снят: в отрезке нет ни одного учтённого изменения (045)", file=sys.stderr
            )
            return EXIT_BROKEN
        print("\n".join(archive_heading(archive, seen) + report(chains(said))))
        return EXIT_OK
    token = ghrest.token_from_env()
    if not token or not args.repo:
        print("замер не снят: нет токена или репозитория (045)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        said, seen, kept = read_counted(args.repo, token, args.last, args.first, args.final, cut)
    except ghrest.TransportError as exc:
        print(f"замер не снят: площадка не ответила — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except Undated as exc:
        print(f"замер не снят: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not seen:
        print("замер не снят: в отрезке нет ни одного закрытого изменения (045)", file=sys.stderr)
        return EXIT_BROKEN
    # МОМЕНТ РАНЬШЕ ВСЕХ ЛЕНТ — ТОТ ЖЕ ПУСТОЙ ЗАМЕР. Отрезок не пуст, но всё в
    # нём сказано позже `--at`, и ноль находок выдавался бы за замер (взгляд
    # на #781, соседний случай пустого отрезка, 195).
    # Отказ — когда до момента взгляд не сказал НИЧЕГО: ни вердикта, ни
    # находки. Отрезок, где взгляд честно ничего не нашёл, — настоящий ноль, и
    # с `--at` он обязан отвечать так же, как без него (взгляд на #781).
    if cut is not None and not kept and not said:
        print(
            "замер не снят: до момента --at взгляд не сказал ни вердикта, ни находки (045)",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    print("\n".join(report(chains(said))))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
