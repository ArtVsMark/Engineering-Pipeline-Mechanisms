#!/usr/bin/env python3
"""Признаки навыков: по какому следу в слитом изменении навык ждали (#1694).

ЗАЧЕМ. Навык не краснеет: невызванный неотличим от вызванного (решение 031).
Счёт «навык ждали — вызван» требует второй половины — КОГДА навык ждали, — и
она выводится из слитого изменения машинно: тронут механизм — ждали
`a-gate-obeys-every-rule`, в теле строка `Разобрано:` — `close-a-finding`.

ПРИЗНАКИ ЕДУТ С НАВЫКОМ, А НЕ ЛЕЖАТ НАШИМ КОДОМ (слово владельца 26.10.2026,
#1694). Потребителю ложится `SKILL.md`, и признак — ключ `expected` в его шапке,
рядом с описанием, которое называет тот же триггер словами. Второй перечень
рядом с навыками разошёлся бы с ними первой же правкой (022). Формы ключа:

* отображение — `touched` (шаблоны путей, тронутых изменением), `added`
  (шаблоны путей, им заведённых), `data` (ключи таблицы путей проекта,
  `paths.PROJECT`: файл данных тронут), `body` (начала строк тела слитого
  коммита); шаблоны — `PurePosixPath.full_match`, с `**`. Данные проекта —
  ключом, а не путём (#1623): у потребителя, переназначившего путь разделом
  `paths:`, признак иначе смотрел бы на файл, которого у него нет;
* строка `none — <причина>`: у навыка нет машинного следа в слитом (его
  событие — слово владельца, свежий свод), и это сказано словами (154).

Ключа нет вовсе — отказ формы, а не «не ждали никогда»: молчание неотличимо
от «забыли» (045). Ключи держит `tests/test_skill_signals.py` — у каждого
признака свой случай.

ГРАНИЦЫ НАЗВАНЫ. Признак — след в слитом, а не намерение окна: навык, который
нужен был до работы, а след её не оставил, признаком не виден, и наоборот —
след без нужды в навыке засчитается ожиданием. Ряд читается с размером
выборки, а не процентом (#1694).
"""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

import check_journal
import check_pr_meta
import gitcall
import paths
import pipeline_checks
import yaml

#: Дедлайн чтения одного локального объекта git (шапка навыка, ответ на
#: коммите): блоб читается за миллисекунды, а чтений столько, сколько навыков,
#: и сумма их дедлайнов входит в бюджет захода записи (`skill_record.BUDGET`, 100).
READ: Final = 10
#: Ключ шапки `SKILL.md`, несущий признаки.
KEY: Final = "expected"
#: Виды признака: ключ шапки → что сверяется.
KINDS: Final = {
    "touched": "путь, тронутый изменением",
    "added": "путь, заведённый изменением",
    "data": "файл данных проекта по ключу таблицы путей, тронутый изменением",
    "body": "начало строки тела слитого коммита",
}
#: «Признака нет» — словом и с причиной.
NONE_RE: Final = re.compile(r"^none\s+—\s+\S")
#: Шапка навыка: первый блок между строками `---`.
FRONT_RE: Final = re.compile(r"\A---\n(?P<yaml>.*?)\n---\n", re.DOTALL)


class BadSignals(ValueError):
    """Признаки навыка не той формы: отказ с именем навыка и ключом."""


class NoSignals(BadSignals):
    """Ключа признаков у навыка нет вовсе: на старом коммите — «ещё не было»."""


@dataclass(frozen=True)
class Signals:
    """Признаки одного навыка; `none` — причина, почему машинного следа нет.

    `data` хранит уже РАЗРЕШЁННЫЕ пути файлов данных — по таблице путей проекта.
    """

    touched: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    data: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    none: str = ""

    def match(self, touched: list[str], added: list[str], body: str) -> bool:
        """Ждали ли навык в изменении с такими путями и телом."""
        lines = [line.strip() for line in body.splitlines()]
        return (
            any(PurePosixPath(one).full_match(glob) for one in touched for glob in self.touched)
            or any(PurePosixPath(one).full_match(glob) for one in added for glob in self.added)
            or any(one in self.data for one in touched)
            or any(line.startswith(start) for line in lines for start in self.body)
        )


def signals_of(name: str, text: str, table: dict[str, Path] | None = None) -> Signals:
    """Признаки из текста `SKILL.md`; шапки или ключа нет, форма чужая — `BadSignals`.

    `table` — таблица путей проекта (`pipeline_checks.project_paths`); нет —
    умолчания `paths.PROJECT`. Ключ `data`, которого в ней нет, — отказ.
    """
    head = FRONT_RE.match(text)
    if not head:
        raise BadSignals(f"{name}: у SKILL.md нет шапки между строками ---")
    try:
        front = yaml.safe_load(head["yaml"])
    except yaml.YAMLError as exc:
        raise BadSignals(f"{name}: шапка не разобрана — {str(exc).splitlines()[0]}") from exc
    said = front.get(KEY) if isinstance(front, dict) else None
    if said is None:
        raise NoSignals(f"{name}: в шапке нет ключа {KEY} — признаки или «none — причина»")
    if isinstance(said, str):
        if not NONE_RE.match(said.strip()):
            raise BadSignals(f"{name}: {KEY} строкой — только «none — <причина>»")
        return Signals(none=said.strip())
    if not isinstance(said, dict) or not said:
        raise BadSignals(f"{name}: {KEY} — отображение {', '.join(KINDS)} или «none — причина»")
    unknown = sorted(str(key) for key in set(said) - set(KINDS))
    if unknown:
        raise BadSignals(f"{name}: незнакомые виды признака {', '.join(unknown)}")
    found: dict[str, tuple[str, ...]] = {}
    for kind in KINDS:
        values = said.get(kind, [])
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise BadSignals(f"{name}: {KEY}.{kind} — список непустых строк")
        found[kind] = tuple(values)
    known = paths.PROJECT if table is None else table
    strange = sorted(key for key in found["data"] if key not in known)
    if strange:
        raise BadSignals(f"{name}: {KEY}.data — ключей нет в таблице путей: {', '.join(strange)}")
    return Signals(
        touched=found["touched"],
        added=found["added"],
        data=tuple(known[key].as_posix() for key in found["data"]),
        body=found["body"],
    )


def signals(root: Path = Path()) -> dict[str, Signals]:
    """Признаки всех навыков дерева; навыки — по `check_pr_meta.known_skills` (214).

    Пути данных — по таблице проекта `root`: его раздел `paths:` переназначает
    умолчания; битый раздел — `paths.BadPaths` наверх.
    """
    table = pipeline_checks.project_paths(root / paths.PIPELINE)
    return {
        name: signals_of(
            name, (root / paths.SKILLS / name / "SKILL.md").read_text(encoding="utf-8"), table
        )
        for name in sorted(check_pr_meta.known_skills(root))
    }


def expected(
    table: dict[str, Signals], touched: list[str], added: list[str], body: str
) -> list[str]:
    """Навыки, которых изменение ждало, — по признакам, без повторов, по имени."""
    return sorted(name for name, one in table.items() if one.match(touched, added, body))


def signals_at(commit: str, root: Path = Path()) -> dict[str, Signals]:
    """Признаки навыков НА КОММИТЕ, а не на выложенном дереве; отказ git — `BadSignals`.

    ЭПОХА ЗАПИСИ — ЕЁ КОММИТА (поздний взгляд на #1715). Кнопка пишет старое
    изменение, и сегодняшние `SKILL.md` смешали бы его ожидание с нынешним.
    Список навыков, их шапки и раздел `paths:` ответа берутся у коммита. Ключа
    нет ни у одного навыка — `NoSignals`: признаков тогда ещё не было; нет у
    части — `BadSignals` с их именами: новый навык забыли разметить.
    """
    folder = paths.SKILLS.as_posix()
    # Фильтр пути, а не `коммит:каталог`: нет каталога навыков — пусто, а
    # неверный коммит — отказ; обращение к пути смешало бы оба в один отказ.
    listed = gitcall.output(
        ["ls-tree", "-z", "--name-only", commit, f"{folder}/"],
        BadSignals,
        cwd=str(root),
        timeout=READ,
    )
    try:
        answer = gitcall.output(
            ["show", f"{commit}:{paths.PIPELINE.as_posix()}"],
            BadSignals,
            cwd=str(root),
            timeout=READ,
        )
    except BadSignals as exc:
        if not any(said in str(exc) for said in check_journal.NO_SUCH_PATH):
            raise
        answer = ""
    try:
        table = pipeline_checks.project_paths_of(answer, f"{commit}:{paths.PIPELINE}")
    except paths.BadPaths as exc:
        raise BadSignals(f"таблица путей на {commit} не разобрана: {exc}") from exc
    found: dict[str, Signals] = {}
    unmarked: list[str] = []
    for name in sorted(PurePosixPath(one).name for one in listed.split("\0") if one):
        try:
            text = gitcall.output(
                ["show", f"{commit}:{folder}/{name}/SKILL.md"],
                BadSignals,
                cwd=str(root),
                timeout=READ,
            )
        except BadSignals as exc:
            if any(said in str(exc) for said in check_journal.NO_SUCH_PATH):
                continue
            raise
        try:
            found[name] = signals_of(name, text, table)
        except NoSignals:
            unmarked.append(name)
    # НИ У КОГО — «ЕЩЁ НЕ БЫЛО», У ЧАСТИ — ЗАБЫЛИ (взгляд на #1724). Старый
    # коммит не знает ключа вовсе; новый навык без ключа рядом с размеченными —
    # пропуск разметки, и молча гасить из-за него все записи нельзя (045).
    if unmarked and not found:
        raise NoSignals(f"ключа {KEY} нет ни у одного навыка на {commit}")
    if unmarked:
        raise BadSignals(f"на {commit} без ключа {KEY}: {', '.join(unmarked)}")
    return found
