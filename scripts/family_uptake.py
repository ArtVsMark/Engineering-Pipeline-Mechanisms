#!/usr/bin/env python3
"""Кто из семьи что взял: обход клонов против объявлений о подключении.

ПОЧЕМУ ОБХОД, А НЕ РЕЕСТР АДРЕСОВ. `scripts/consumers.py` спрашивает тех, кто
ОБЪЯВИЛСЯ: читает их `.pipeline.yml` по адресам из `.rules/consumers.json`.
Подключившийся молча ему невидим, а молчаливое подключение — обычный случай:
взять шаг проще, чем сказать о том, что взял. Предметы у механизмов разные, и
второго счёта одного и того же здесь не заводится
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

СПИСОК СЕМЬИ НЕ ПИШЕТСЯ РУКОЙ. Он берётся из выгрузки каталога — того же
источника, по которому считается разрез общих механизмов: второй список тех же
репозиториев отстал бы на первом же новом проекте, и отстал бы молча
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md),
[049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

ЧИТАЕТСЯ КЛОН, А НЕ API. Прогонов у проекта семьи до тринадцати, и чтение
каждого файла запросом стоило бы сотни вызовов из общей квоты
([058](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/058-when-the-quota-is-out-stop.md)).
Поверхностный клон с `--filter=blob:none --sparse` берёт только
`.github/workflows` — замер 20.09.2026: полторы секунды и 3.8 МБ на проект,
пять проектов около восьми секунд, вызовов к API ноль.

НЕПРОЧИТАННЫЙ КЛОН — НЕ «НЕ ПОДКЛЮЧЁН». Отказ клонирования называется по имени
и отделён от нуля подключений: частный репозиторий, сеть и отсутствие ветки
снаружи одинаковы, а значат разное
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ПУСТО — ЭТО СОСТОЯНИЕ, А НЕ ОТКАЗ. Замер 20.09.2026, в день выпуска шагов:
взявших ноль из пяти. Считать пустоту поломкой значило бы требовать, чтобы
соседи подключились; считать её тишиной — выдавать незнание за «никто не
взял». Заход говорит число словом.

Исходы (правило 039): ``0`` обход прошёл · ``2`` не отработал ·
``3`` часть клонов не прочитана — сказано, а не выдано за «не взяли».
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import catalogue
import ghrest
import onboard
import paths
import pipeline_checks as policy
import report

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_UNREAD: Final = 3

#: Наш адрес в чужом прогоне. Ищется ВЫЗОВ, а не упоминание: имя проекта
#: встречается и в прозе комментариев, и это не подключение (166). Регистр
#: имени площадка не различает, и сравнение с ним везде без регистра.
OURS: Final = "ArtVsMark/Engineering-Pipeline-Mechanisms"
CALL_RE: Final = re.compile(
    r"uses:\s*(?i:"
    + re.escape(OURS)
    + r")/\.github/workflows/(?P<step>[\w.-]+)\.ya?ml@(?P<ref>[\w.-]+)"
)

#: Что клонируется: только объявление прогонов. Остальное дерево соседа нам не
#: нужно, а за трафик платит и он тоже.
WANT: Final = str(paths.WORKFLOWS)
#: Откуда берутся клоны. Доводом, а не склейкой внутри: иначе проверить сам
#: обход можно только через сеть, то есть не проверить его вовсе (146).
HOST: Final = "https://github.com"
#: Сколько ждать ОДИН вызов git у соседа. Без предела заход висит на
#: недоступном соседе, и обход не доходит до остальных. Все вызовы одного
#: соседа вместе короче бюджета: иначе первый повисший сосед съедал бюджет
#: целиком, и остальные выходили непрочитанными — «один медленный прячет
#: состояние всех» в другой форме (взгляд на #1246). Число вызовов на соседа
#: тест меряет прогоном `sweep`, а не берёт отсюда (взгляд на #1261).
TIMEOUT: Final = 25
#: Сколько секунд обход начинает новых соседей. Шаг прогона снимается по своему
#: пределу целиком, и вместе с ним пропали бы числа уже прочитанных клонов;
#: поэтому предел держит сам обход: после бюджета соседи не начинаются и
#: названы непрочитанными, а ожидание git урезано до остатка (взгляд на #1241).
#: Худший случай — `BUDGET + TIMEOUT`, а не «плюс все вызовы»: остаток
#: `min(TIMEOUT, left)` считается один раз на соседа (взгляд на #1261). Тест
#: меряет его прогоном `sweep` с поддельными часами, и предел шага в
#: `badges.yml` сверяется с замером плюс запас на запуск интерпретатора и
#: уборку клонов (`STEP_MARGIN`).
BUDGET: Final = 75
#: Запас предела шага сверх худшего случая обхода: запуск Python и удаление
#: каталога с клонами (взгляд на #1246). Ожидания после снятия git здесь нет:
#: на POSIX `subprocess.run` после снятия каналы не дочитывает, и это
#: закрепляет тест.
STEP_MARGIN: Final = 60


class NotRun(RuntimeError):
    """Обход не отработал: третий исход, а не пустая сводка."""


@dataclass(frozen=True, slots=True)
class Took:
    """Что взял один проект семьи."""

    repo: str
    #: Пары «файл шага → версия» по каждому вызову — ЕДИНСТВЕННЫЙ источник:
    #: шаги и версии из них выводятся, а не хранятся рядом вторым ответом на
    #: тот же вопрос (взгляд на #1370, 090). Пусто — не взял ничего.
    pins: tuple[tuple[str, str], ...] = ()
    #: Диапазон `contract:` из его `.pipeline.yml`. `None` — не объявлен или
    #: не прочитан: «на свежем» без него не сказать, и он назван, а не угадан.
    span: str | None = None

    @property
    def steps(self) -> tuple[str, ...]:
        """Файлы наших шагов, которые он зовёт."""
        return tuple(sorted({step for step, _ref in self.pins}))

    @property
    def refs(self) -> tuple[str, ...]:
        """Версии, к которым он прибит. Их бывает НЕСКОЛЬКО — см. `said`."""
        return tuple(sorted({ref for _step, ref in self.pins}))

    def given(self, offered: list[str]) -> Took:
        """Тот же проект, сужённый до вызовов ОТДАВАЕМЫХ шагов (взгляд на #1355).

        Свежесть и «разные версии» судятся по ним: неотдаваемый `step-*` на
        `main` не говорит ни о свежести, ни о недоведённом переезде.
        """
        offers = set(offered)
        kept = tuple(pin for pin in self.pins if set(offered_names((pin[0],))) & offers)
        return Took(self.repo, kept, self.span)

    def said(self, offered: list[str] | None = None) -> str:
        """Строка сводки: числа и имена, а не оценка.

        Разные версии у одного потребителя — недоведённый переезд (152), и
        судятся они по отдаваемым шагам, когда `offered` назван.
        """
        if not self.steps:
            return f"- `{self.repo}` — не взял ничего"
        pinned = ", ".join(self.refs)
        about = f"{len(self.steps)} шаг(ов) на {pinned}: {', '.join(self.steps)}"
        judged = self.given(offered) if offered is not None else self
        if len(judged.refs) > 1:
            about += " · **разные версии у одного потребителя** — переезд не доведён (152)"
        return f"- `{self.repo}` — {about}"


def family(url: str = catalogue.WHERE_URL, local: Path | None = None) -> list[str]:
    """Репозитории семьи из выгрузки каталога, кроме нас самих.

    ``local`` — уже скачанная сводка: прогон значков берёт её один раз и
    отдаёт и разрезу, и обходу, чтобы оба считали по одному снимку (022).
    """
    try:
        if local is not None:
            said = json.loads(local.read_text(encoding="utf-8"))
        else:
            said = ghrest.raw_json(url)
    except (ghrest.TransportError, OSError, ValueError) as exc:
        raise NotRun(f"сводка семьи не прочитана: {exc}") from exc
    if not isinstance(said, dict):
        raise NotRun("сводка семьи не словарём — форма не узнана (075)")
    rows = said.get("consumers")
    if not isinstance(rows, list) or not rows:
        raise NotRun("в сводке семьи нет ни одного проекта — обходить некого (075)")
    found = [
        str(one["repo"])
        for one in rows
        if isinstance(one, dict)
        and one.get("repo")
        and str(one["repo"]).casefold() != OURS.casefold()
    ]
    if not found:
        raise NotRun(f"в сводке семьи только мы сами ({OURS}) — обходить некого (075)")
    return sorted(found)


def calls_in(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Наши шаги и версии, названные текстом одного прогона.

    Чистая: ни сети, ни диска. Так проверка идёт по данным, а не по подделке
    транспорта
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    # Разбор один — `pins_in`; здесь только проекция (взгляд на #1370, 090).
    took = Took("", pins_in(text))
    return took.steps, took.refs


def pins_in(text: str) -> tuple[tuple[str, str], ...]:
    """Пары «файл шага → версия» по каждому нашему вызову в тексте прогона."""
    return tuple(sorted({(found["step"], found["ref"]) for found in CALL_RE.finditer(text)}))


def shallow_clone(repo: str, where: Path, host: str = HOST, timeout: float = TIMEOUT) -> Path:
    """Поверхностный клон одного соседа: только объявление прогонов."""
    into = where / repo.replace("/", "_")
    # БЕЗ GIT НА ПУТИ — ОТКАЗ ЗДЕСЬ, у вызова, а не только выше у `took`: поимка
    # выше живёт в другом месте и уезжает от вызова молча (#1027).
    try:
        done = subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                f"{host}/{repo}",
                str(into),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if done.returncode:
            raise NotRun(f"{repo}: клон не взят — {report.cut(done.stderr.strip() or 'отказ git')}")
        # ОТКАЗ СУЖЕНИЯ НЕ ГЛОТАЕТСЯ. Здесь стояло `check=False`, и это было тихим
        # запасным путём: не сработало сужение — каталога прогонов в клоне нет, а
        # `took` отвечает «не взял ничего». Настоящий ноль и отказ инструмента
        # снаружи одинаковы, и первый читался бы как второй
        # ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
        # Нашёл внешний взгляд на #569.
        narrowed = subprocess.run(
            ["git", "-C", str(into), "sparse-checkout", "set", WANT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
        if narrowed.returncode:
            raise NotRun(
                f"{repo}: клон взят, но сузить до «{WANT}» не вышло — "
                f"{report.cut(narrowed.stderr.strip() or 'отказ git')}. "
                "Без сужения «не взял ничего» неотличимо от отказа инструмента (045)"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotRun(f"{repo}: git не запустился — {exc}") from exc
    return into


def took(repo: str, where: Path, timeout: float = TIMEOUT) -> Took:
    """Что взял один сосед — по его клону."""
    clone = shallow_clone(repo, where, timeout=timeout)
    folder = clone / WANT
    pins: set[tuple[str, str]] = set()
    # КАТАЛОГА ПРОГОНОВ МОЖЕТ НЕ БЫТЬ ВОВСЕ, и это «не взял», а не отказ:
    # проект без конвейера — законное состояние соседа.
    if folder.is_dir():
        for path in sorted(folder.glob("*.y*ml")):
            pins.update(pins_in(path.read_text(encoding="utf-8", errors="replace")))
    # ОТВЕТ ЛЕЖИТ В КОРНЕ, а сужение в режиме конуса корневые файлы оставляет:
    # второго клона ради одного файла не нужно.
    answer = clone / paths.PIPELINE
    text = answer.read_text(encoding="utf-8", errors="replace") if answer.is_file() else ""
    span = policy.span_said(text) if text else None
    return Took(repo=repo, pins=tuple(sorted(pins)), span=span)


def sweep(
    repos: list[str],
    where: Path,
    *,
    budget: float = BUDGET,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[Took], list[str]]:
    """Обход всех соседей; отдельно — те, чей клон не прочитан.

    ОТКАЗ ПО ОДНОМУ НЕ УНОСИТ ОБХОД: недоступный сосед не должен прятать
    состояние остальных, а его непрочитанность обязана быть названа (045).
    То же со временем: сосед, до которого не дошли за `budget`, назван
    непрочитанным, а прочитанные остаются в числах.
    """
    seen: list[Took] = []
    unread: list[str] = []
    deadline = clock() + budget
    for repo in repos:
        left = deadline - clock()
        if left <= 0:
            print(f"::warning::{repo}: не прочитан — время обхода исчерпано", file=sys.stderr)
            unread.append(repo)
            continue
        try:
            seen.append(took(repo, where, timeout=min(TIMEOUT, left)))
        except (NotRun, subprocess.TimeoutExpired, OSError) as exc:
            print(f"::warning::{repo}: не прочитан — {report.cut(str(exc))}", file=sys.stderr)
            unread.append(repo)
    return seen, unread


def takers(seen: list[Took], offered: list[str]) -> list[Took]:
    """Взявшие: позвали хотя бы один ОТДАВАЕМЫЙ шаг. Одно правило на печать и факты (022)."""
    offers = set(offered)
    return [one for one in seen if offers & set(offered_names(one.steps))]


def report_lines(seen: list[Took], unread: list[str], offered: list[str]) -> list[str]:
    """Строки сводки — отдельно от печати, чтобы их можно было спросить.

    «Взяли» считается тем же `takers`, что и в фактах: печать и файл одного
    захода не отвечают на один вопрос разными числами (взгляд на #1241).
    """
    lines = [f"взяли наши шаги: {len(takers(seen, offered))} из {len(seen)} прочитанных"]
    lines += [one.said(offered) for one in seen]
    if unread:
        lines.append(
            f"не прочитано клонов: {len(unread)} — {', '.join(unread)}. "
            "Это незнание, а не «не взяли» (045)"
        )
    return lines


def offered_names(called: tuple[str, ...]) -> list[str]:
    """Имена позванных файлов шагов в форме `onboard.steps` — без приставки `step-`."""
    return [
        name[len(onboard.STEP_PREFIX) :] for name in called if name.startswith(onboard.STEP_PREFIX)
    ]


def uptake(seen: list[Took], unread: list[str], offered: list[str]) -> dict[str, object]:
    """Числа «взяли вызовом» для фактов: проекты и шаги, с числителем и знаменателем.

    Решение владельца 07.10.2026 (#1199). Знаменатель проектов — вся семья без
    нас, и непрочитанный клон в нём есть, но в «взял» не засчитан и назван
    поимённо: незнание — не «не взял» (045). Знаменатель шагов — то, что мы
    отдаём наружу (`onboard.steps`), а не то, что кто-то позвал: позванный, но
    не отдаваемый шаг в числитель не идёт — ни шагов, ни проектов.

    `steps` и `refs` в `by` — ОТДАВАЕМЫЕ шаги и их версии (взгляды на #1355 и
    #1370): свежесть судится по ним, и неотдаваемый `step-*` на `main` не
    уводит соседа в «на ветке», когда отдаваемое у него на теге выпуска.
    """
    # ИМЕНА ПРИВОДЯТСЯ К ОДНОЙ ФОРМЕ. Вызов называет файл (`step-lint`), а
    # отдаваемое — шаг без приставки (`lint`, `onboard.steps`): сравнение как
    # есть давало пустое пересечение всегда (взгляд на #1241).
    offers = set(offered)
    took_ours = takers(seen, offered)
    taken = sorted({step for one in took_ours for step in offered_names(one.steps)} & offers)
    return {
        "projects": {
            "took": len(took_ours),
            "of": len(seen) + len(unread),
            "unread": len(unread),
            "unread_repos": sorted(unread),
        },
        "steps": {"taken": len(taken), "of": len(offered), "names": taken},
        "by": [
            # Шаги и версии строки — ОДНОГО среза, отдаваемых шагов (взгляд на
            # #1370): таблица фактов ставит их в одну строку «шаги | теги», и
            # тег неотдаваемого шага в ней пропадал бы без объяснения.
            {
                "repo": one.repo,
                "steps": list(given.steps),
                "refs": list(given.refs),
                "contract": one.span,
            }
            for one in took_ours
            for given in (one.given(offered),)
        ],
    }


#: Свежесть без выпуска или без обхода не считается — и это сказано, а не ноль.
NO_FRESHNESS: Final = "выпуска или обхода нет — на свежем ли семья, неизвестно, а не «никто»"
#: Пин тегом выпуска: `v` и три числа. Хеш коммита — от семи шестнадцатеричных
#: знаков. Иное имя (`main`, `dev`) — ветка: она движется, и возраста у неё нет.
TAG_RE: Final = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_RE: Final = re.compile(r"^[0-9a-f]{7,40}$")


def pin_of(ref: str, release: dict[str, str]) -> str:
    """Чем прибит вызов: `release` — тег или коммит выпуска (и короткий хеш тоже),
    `other` — другой тег или коммит, `branch` — имя ветки."""
    if ref == release["tag"] or (SHA_RE.match(ref) and release["sha"].startswith(ref)):
        return "release"
    return "other" if TAG_RE.match(ref) or SHA_RE.match(ref) else "branch"


def freshness(
    by: list[dict[str, Any]], release: dict[str, str] | None, steps: str
) -> dict[str, object]:
    """На свежем ли взявшие: пин на последний выпуск и диапазон, включающий `steps`.

    Решение владельца 14.10.2026 (#1344): вопрос издателя — «на каком
    контракте и теге сидит семья». Свёртка — поле фактов, картинку рисует
    каталог. Знаменатель — взявшие проекты. Группы:

    - **на свежем** — каждый пин на теге выпуска или его коммите (полным или
      коротким хешем), и `contract:` включает текущий номер `steps`;
    - **в диапазоне** — контракт совместим, а пин на другом теге или коммите;
    - **на ветке** — контракт совместим, а вызов прибит к имени ветки: она
      движется, и «старше» о ней не скажешь (195);
    - **отстал** — диапазон кончается не выше текущего номера;
    - **впереди** — диапазон начинается выше текущего номера: сосед объявил
      контракт, которого мы не выпускали, — это не отставание;
    - **не объявлен** — диапазона нет или он не разбирается: свежесть не
      утверждается и не отрицается (045).

    Каждая группа, кроме свежих, — поимённо.
    """
    if not release:
        return {"read": False, "why": NO_FRESHNESS}
    now = tuple(int(part) for part in steps.split(".")[:2])
    groups: dict[str, list[str]] = {
        name: [] for name in ("fresh", "in_range", "branch", "behind", "ahead", "undeclared")
    }
    for one in by:
        repo, span = str(one["repo"]), one.get("contract")
        # Форма диапазона — одним разбором с `policy.compatible` (взгляд на
        # #1355, 090): своя регулярка рядом разошлась бы с ним молча.
        try:
            low, _high = policy.span_bounds(str(span)) if span else (None, None)
        except policy.BadPolicy:
            low = None
        if low is None:
            groups["undeclared"].append(repo)
            continue
        if policy.compatible(str(span), steps):
            pins = {pin_of(str(ref), release) for ref in one.get("refs") or []}
            group = "branch" if "branch" in pins else "in_range" if "other" in pins else "fresh"
            groups[group].append(repo)
        elif now < low:
            groups["ahead"].append(repo)
        else:
            groups["behind"].append(repo)
    return {
        "read": True,
        "release": release["tag"],
        "steps": steps,
        "of": len(by),
        "fresh": len(groups["fresh"]),
        "in_range": len(groups["in_range"]),
        **{f"{name}_repos": groups[name] for name in groups if name != "fresh"},
    }


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обходит клоны семьи и печатает, кто что взял."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--where", help="готовый каталог с клонами; по умолчанию временный")
    parser.add_argument("--summary", help="уже скачанная сводка семьи where.json")
    parser.add_argument("--out", help="куда положить числа для фактов (JSON)")
    parser.add_argument("--root", default=".", help="наше дерево: отсюда берутся отдаваемые шаги")
    args = parser.parse_args(argv)

    try:
        repos = family(local=Path(args.summary) if args.summary else None)
        offered = onboard.steps(Path(args.root))
    except NotRun as exc:
        print(f"обход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not offered:
        print(
            "обход не отработал: отдаваемых шагов не найдено — знаменателя нет (075)",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    # УБОРКА КЛОНОВ НЕ УНОСИТ ЧИСЕЛ (взгляд на #1261). После снятия git по
    # пределу его потомки (`index-pack`, `git-remote-https`) живут дальше и
    # могут ещё писать в клон: удаление каталога падало бы на ENOTEMPTY ДО
    # отчёта, и пропадали бы числа уже прочитанных соседей. Каталог временный —
    # остаток уберёт раннер.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        seen, unread = sweep(repos, Path(args.where or tmp))

    for line in report_lines(seen, unread, offered):
        print(line)
    if args.out:
        Path(args.out).write_text(
            json.dumps(uptake(seen, unread, offered), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return EXIT_UNREAD if unread else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
