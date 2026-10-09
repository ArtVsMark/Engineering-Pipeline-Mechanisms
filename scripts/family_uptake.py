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
from typing import Final

import catalogue
import ghrest
import onboard
import paths
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
#: недоступном соседе, и обход не доходит до остальных. Предел ниже бюджета —
#: вдвое с запасом (вызовов на соседа два): иначе первый повисший сосед съедал
#: бюджет целиком, и остальные выходили непрочитанными — «один медленный прячет
#: состояние всех» в другой форме (взгляд на #1246). Связь держит тест.
TIMEOUT: Final = 25
#: Сколько секунд обход начинает новых соседей. Шаг прогона снимается по своему
#: пределу целиком, и вместе с ним пропали бы числа уже прочитанных клонов;
#: поэтому предел держит сам обход: после бюджета соседи не начинаются и
#: названы непрочитанными, а ожидание git урезано до остатка (взгляд на #1241).
#: Худший случай — бюджет плюс два вызова последнего начатого соседа, то есть
#: `BUDGET + 2 × TIMEOUT`; предел шага в `badges.yml` стоит выше него с запасом
#: на запуск интерпретатора и уборку клонов (`STEP_MARGIN`).
BUDGET: Final = 75
#: Запас предела шага сверх худшего случая обхода: запуск Python, удаление
#: каталога с клонами, ожидание после снятия git (взгляд на #1246).
STEP_MARGIN: Final = 60


class NotRun(RuntimeError):
    """Обход не отработал: третий исход, а не пустая сводка."""


@dataclass(frozen=True, slots=True)
class Took:
    """Что взял один проект семьи."""

    repo: str
    #: Имена наших шагов, которые он зовёт. Пусто — не взял ничего.
    steps: tuple[str, ...]
    #: Версии, к которым он прибит. Их бывает НЕСКОЛЬКО, и это находка: разные
    #: шаги на разных тегах означают недоведённый переезд.
    refs: tuple[str, ...]

    def said(self) -> str:
        """Строка сводки: числа и имена, а не оценка."""
        if not self.steps:
            return f"- `{self.repo}` — не взял ничего"
        pinned = ", ".join(self.refs)
        about = f"{len(self.steps)} шаг(ов) на {pinned}: {', '.join(self.steps)}"
        if len(self.refs) > 1:
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
    steps: list[str] = []
    refs: list[str] = []
    for found in CALL_RE.finditer(text):
        steps.append(found["step"])
        refs.append(found["ref"])
    return tuple(sorted(set(steps))), tuple(sorted(set(refs)))


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
    except OSError as exc:
        raise NotRun(f"{repo}: git не запустился — {exc}") from exc
    return into


def took(repo: str, where: Path, timeout: float = TIMEOUT) -> Took:
    """Что взял один сосед — по его клону."""
    folder = shallow_clone(repo, where, timeout=timeout) / WANT
    steps: set[str] = set()
    refs: set[str] = set()
    # КАТАЛОГА ПРОГОНОВ МОЖЕТ НЕ БЫТЬ ВОВСЕ, и это «не взял», а не отказ:
    # проект без конвейера — законное состояние соседа.
    if folder.is_dir():
        for path in sorted(folder.glob("*.y*ml")):
            mine, pinned = calls_in(path.read_text(encoding="utf-8", errors="replace"))
            steps.update(mine)
            refs.update(pinned)
    return Took(repo=repo, steps=tuple(sorted(steps)), refs=tuple(sorted(refs)))


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
    lines += [one.said() for one in seen]
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
            {"repo": one.repo, "steps": list(one.steps), "refs": list(one.refs)}
            for one in took_ours
        ],
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

    with tempfile.TemporaryDirectory() as tmp:
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
