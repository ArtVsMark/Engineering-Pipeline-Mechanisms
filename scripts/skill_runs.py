#!/usr/bin/env python3
"""Сводка журнала навыков: какой навык зовут, какой нет (#1449, #1426).

ЗАЧЕМ. Навык не краснеет: невызванный неотличим от вызванного (решение 031).
Хук `.claude/hooks/skill_log.py` пишет каждый вызов строкой журнала, но журнал
ничего не говорит, пока его не свели. Сводка сверяет навыки дерева
(`.claude/skills/*/SKILL.md`) с журналом и называет поимённо те, кого не
звали ни разу.

СПЕРВА СПРОСИЛИ СЕМЬЮ (162): у каталога есть хук журнала, а сводки нет ни у
кого из семьи — строим своё. Образец взят у своего реестра находок: живая
задача с маркером, тело собирает механизм целиком. Форма строки журнала —
каталога, поле в поле: у каждого проекта своя сводка, но механизм и данные
общие (решение владельца 17.10.2026, #1449), поэтому журнал каталога читается
здесь как есть.

ЗАДАЧУ ПИШЕТ ТОЛЬКО ЛОКАЛЬНОЕ ОКНО. Журнал копится там, где окно живёт
долго, — облачный контейнер умирает вместе с ним. А писать в трекер из облака
нельзя: прокси подменяет учётные данные на записи (131). Поэтому `--apply` из
облачного окна (`CLAUDE_CODE_REMOTE=true`) — отказ, а без ключа — сухой заход:
тело печатается, ничего не пишется.

ГРАНИЦЫ, И ОНИ НАЗВАНЫ. «Не звали» — вывод по ВЫБОРКЕ, а не по проекту (107):
журнал пишет одно окно в одном рабочем дереве. Облачное окно ведёт свой журнал
и теряет его с контейнером, у другого git worktree журнал свой, и навык,
который звали там, здесь назван незванным. Поэтому выборка — дни и число
сессий — названа и в теле, и в строке исхода. Сводка видит, что навык ЗВАЛИ,
а не что его звали ВОВРЕМЯ: навык, позванный после толчка, засчитан наравне с
позванным до.
Отказ навыка сводка считает по событию площадки, а не по смыслу ответа.
Сверки «вызовы были, а журнал пуст» нет: для неё нужен счёт вызовов с другой
стороны, а его у площадки нет.

Исходы (правило 039): ``0`` каждый навык дерева звали · ``1`` есть навык без
единого вызова · ``2`` не отработал — журнала нет, он пуст или не читается,
или запись отказала.
"""

import argparse
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import findings
import ghrest
import main_guard
import paths
import report

EXIT_OK: Final = 0
EXIT_UNCALLED: Final = 1
EXIT_BROKEN: Final = 2

#: Журнал — тот же путь, что пишет хук; адрес у якоря, совпадение держит набор.
JOURNAL: Final = paths.SKILL_RUNS
#: Исходы строки журнала — имена событий хука.
OUTCOMES: Final = ("ok", "fail")
TITLE: Final = "Навыки: кого зовут, кого нет"
MARKER: Final = findings.marker("skill-runs")
#: Сколько номеров строк не той формы называется поимённо; остальные — числом.
SHOWN: Final = 20


class NotRun(RuntimeError):
    """Сводка не отработала: третий исход, а не «вызовов ноль» (039, 045)."""


@dataclass(slots=True)
class Runs:
    """Вызовы одного навыка по журналу."""

    calls: int = 0
    fails: int = 0
    last: datetime | None = None

    def add(self, at: datetime, outcome: str) -> None:
        """Засчитывает строку журнала."""
        self.calls += 1
        self.fails += outcome == "fail"
        self.last = at if self.last is None else max(self.last, at)


@dataclass(slots=True)
class Journal:
    """Журнал, разобранный целиком: навыки, строки без имени и строки не той формы."""

    runs: dict[str, Runs] = field(default_factory=dict)
    #: Вызов был, но имя хук не прочитал (`"skill": null`).
    nameless: int = 0
    #: Номера строк, которые не разбираются как строка журнала.
    malformed: list[int] = field(default_factory=list)
    sessions: set[str] = field(default_factory=set)
    first: datetime | None = None
    last: datetime | None = None


def skills(root: Path) -> list[str]:
    """Навыки дерева — по каталогам с `SKILL.md`: имя каталога и есть имя вызова."""
    return sorted(one.parent.name for one in (root / paths.SKILLS).glob("*/SKILL.md"))


def moment(text: object) -> datetime | None:
    """Время строки журнала; без пояса или не той формы — `None`, а не догадка.

    Форма та же, что у времени площадки, поэтому и разбор тот же — `ghrest.moment`,
    а не своя копия (взгляд на #1519, 090).
    """
    return ghrest.moment(text)


def parse(lines: Iterable[str]) -> Journal:
    """Разбирает журнал построчно; строка не той формы названа номером, а не съедена."""
    journal = Journal()
    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            line: Any = json.loads(raw)
        except ValueError:
            journal.malformed.append(number)
            continue
        if not isinstance(line, dict):
            journal.malformed.append(number)
            continue
        at, name, outcome = moment(line.get("ts")), line.get("skill"), line.get("outcome")
        if at is None or outcome not in OUTCOMES or not (name is None or isinstance(name, str)):
            journal.malformed.append(number)
            continue
        session = line.get("session")
        if isinstance(session, str):
            journal.sessions.add(session)
        journal.first = at if journal.first is None else min(journal.first, at)
        journal.last = at if journal.last is None else max(journal.last, at)
        if name is None:
            journal.nameless += 1
            continue
        journal.runs.setdefault(name, Runs()).add(at, outcome)
    return journal


def read(where: Path) -> Journal:
    """Читает журнал; нет, пуст или не читается — `NotRun` с причиной (045)."""
    try:
        text = where.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise NotRun(
            f"журнала {where} нет — хук `.claude/hooks/skill_log.sh` в этом окне не "
            "писал. Сводку строит окно, где журнал копится: локальное"
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise NotRun(f"журнал {where} не прочитан: {exc}") from exc
    journal = parse(text.splitlines())
    if journal.first is None:
        raise NotRun(
            f"в журнале {where} нет ни одной строки журнала — "
            f"строк не той формы: {len(journal.malformed)}"
        )
    return journal


def uncalled(journal: Journal, tree: list[str]) -> list[str]:
    """Навыки дерева без единого вызова — поимённо."""
    return [one for one in tree if one not in journal.runs]


def day(at: datetime | None) -> str:
    """День строки; без времени — прочерк."""
    return at.astimezone(UTC).strftime("%Y-%m-%d") if at else "—"


def span(journal: Journal) -> str:
    """Выборка журнала словами: «не звали» верно только для неё (107)."""
    return f"с {day(journal.first)} по {day(journal.last)}, сессий: {len(journal.sessions)}"


def render_body(journal: Journal, tree: list[str], now: datetime) -> str:
    """Тело сводки: пересобирается заходом целиком, а не дописывается."""
    quiet = uncalled(journal, tree)
    outside = sorted(set(journal.runs) - set(tree))
    lines = [
        MARKER,
        "",
        "> **Читатель:** владелец и окно. Здесь навыки дерева, которых окно не",
        "> зовёт, и вызовы каждого по журналу.",
        "",
        "Навык не краснеет: невызванный неотличим от вызванного (решение 031).",
        "Сводку строит `scripts/skill_runs.py` из журнала локального окна.",
        "",
        f"Обход: {now.strftime('%Y-%m-%d %H:%M')} UTC. Журнал — {span(journal)}.",
        "",
        "## Не звали в этом журнале",
        "",
        "Вывод по выборке, а не по проекту (107): журнал пишет одно окно в одном",
        "рабочем дереве. Навык, который звали в облачном окне или в другом git",
        "worktree, здесь назван незванным.",
        "",
    ]
    if quiet:
        lines.extend(f"- `{one}`" for one in quiet)
    else:
        lines.append(f"Пусто на {now.strftime('%Y-%m-%d')} — каждый навык дерева звали.")
    lines += ["", "## Вызовы", "", "| Навык | Вызовов | Отказов | Последний |", "|---|---|---|---|"]
    for one in tree:
        runs = journal.runs.get(one, Runs())
        lines.append(f"| `{one}` | {runs.calls} | {runs.fails} | {day(runs.last)} |")
    if outside:
        said = ", ".join(f"`{one}` — {journal.runs[one].calls}" for one in outside)
        lines += ["", f"Звали навыки вне дерева (плагины, чужие): {said}."]
    if journal.nameless:
        lines += ["", f"Вызовов, чьё имя хук не прочитал: {journal.nameless}."]
    if journal.malformed:
        shown = ", ".join(str(one) for one in journal.malformed[:SHOWN])
        more = len(journal.malformed) - SHOWN
        lines += [
            "",
            f"Строк не той формы: {len(journal.malformed)} (номера: {shown}"
            + (f" и ещё {more}" if more > 0 else "")
            + ").",
        ]
    return "\n".join(lines) + "\n"


def save(repo: str, token: str, body: str) -> None:
    """Записывает сводку: обновляет живую задачу по месту или заводит одну."""
    number, _ = findings.live_issue(repo, token, MARKER)
    if number is None:
        created = ghrest.request(
            "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
        )
        print(f"сводка заведена: #{(created or {}).get('number')}")
        return
    ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
    print(f"сводка обновлена: #{number}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сводит журнал с навыками дерева и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--journal", type=Path, default=None, help="журнал; по умолчанию — свой")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="записать живую задачу, а не показать")
    args = parser.parse_args(argv)
    report.announce(not args.apply)
    try:
        if args.apply and os.environ.get("CLAUDE_CODE_REMOTE") == "true":
            raise NotRun(
                "запись из облачного окна отвергнута: прокси подменяет учётные данные на "
                "записи (131), а журнал облака умирает с контейнером. Сводку пишет "
                "локальное окно; здесь — сухой заход без --apply"
            )
        tree = skills(args.root)
        if not tree:
            raise NotRun(f"навыков в {args.root / paths.SKILLS} нет — сводить не с чем (075)")
        where = args.journal or args.root / JOURNAL
        journal = read(where)
        body = render_body(journal, tree, datetime.now(UTC))
        if args.apply:
            if not args.repo:
                raise NotRun("репозиторий не назван — писать сводку некуда")
            save(args.repo, ghrest.token_from_env(), body)
        else:
            print(body, end="")
    except (NotRun, ghrest.TransportError) as exc:
        print(f"сводка не отработала: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    quiet = uncalled(journal, tree)
    sample = f"по журналу {where} ({span(journal)})"
    if quiet:
        print(f"не звали {sample}: {len(quiet)} из {len(tree)} — " + ", ".join(quiet))
        return EXIT_UNCALLED
    print(f"каждый навык дерева звали {sample}: {len(tree)}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
