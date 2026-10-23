#!/usr/bin/env python3
"""Что задело изменение: сценарий проверок и выбор тестов по графу из кода (#1597).

ЗАЧЕМ. Каждое изменение гнало весь набор: 15 223 теста, 659 с у окна и 7–8 мин
на версию Python в CI (замер 23.10.2026), хотя типичная правка трогает один–три
скрипта. Решение владельца 23.10.2026 (эпик #1596): число проверок зависит от
того, что задето; сценарий виден меткой, тесты выбирает граф зависимостей.

ГРАФ ВЫВОДИТСЯ ИЗ КОДА, А НЕ ПИШЕТСЯ РУКАМИ. Рукописный список устарел бы на
первом же новом тесте (005). Ребро — то, что файл зовёт или читает:

* импорт модуля кода (`import x`, `from x import y`, `from tests.conftest …`);
* `load_script("x.py")` и `run_script("x.py", …)` тестов;
* обход всего кода помощником `code_files`/`code_roots` — ребро на все корни
  кода (обход каталога `walk(ROOT / "docs")` ловит литерал ниже);
* литерал строки, совпадающий с путём дерева или с его каталогом.

Рёбра кода ТРАНЗИТИВНЫ: тест модуля, импортирующего тронутый, тоже выбран.
Рёбра данных (литерал пути) — в ОДИН шаг: тест выбирается, если литерал стоит
в нём самом или в модуле, который он зовёт напрямую. Иначе `paths.py`,
называющий почти все файлы данных, сделал бы каждый тест зависимым от каждого
файла, и выбор выродился бы в полный набор. ГРАНИЦА НАЗВАНА (046): тест, чей
модуль читает данные через посредника, на правке данных не выбирается — его
ловят полный прогон общей ветки и ночной (#1598) и навык окна (#1601).

ЧЕГО ГРАФ НЕ ЗНАЕТ — ТО «ДЕРЕВО ЦЕЛИКОМ», А НЕ «НИЧЕГО». Неразобранный файл и
вызов `load_script`/`run_script`/обхода не литералом делают файл зависимым от
всего; тронутый путь вне известных мест и общие для всех файлы
(`tests/conftest.py`, `pyproject.toml`, `CONTRACT_VERSION`, `.pipeline.yml`)
дают полный набор. Ошибка выбора в сторону «больше» стоит минут, в сторону
«меньше» — пропущенного красного (Bazel: неполная карта — прогон всего).

ГРАФ — ПО БАЗЕ И ПО ГОЛОВЕ. Удалённый модуль в голове уже никто не
импортирует; тест, звавший его, в базе на него ссылался и обязан покраснеть.
Тронутое считается от общего предка (`journal.common_ancestor`), а не от
вершины базы: влитая база иначе раздула бы тронутое до всего, что база
получила.

СПЕРВА СПРОСИЛИ СЕМЬЮ (162): у семьи выбора проверок по задетому нет; глоссарий
фильтрует путями только совещательный `card-review.yml`. Приём взят вне семьи:
граф импортов — pytest-skippy и pytest-impacted, сценарий по путям — Prow
(`run_if_changed`) и Chromium CQ (`location_filters`), «неполная карта — всё» —
Bazel `rdeps`. Код не переносится, только идея.

Исходы (правило 039): ``0`` выбор назван · ``2`` не отработал (git не ответил,
база не найдена).
"""

import argparse
import ast
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import ghrest
import gitcall
import journal
import paths
import pipeline_checks
import report
import scope_areas

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Сценарии, от узкого к широкому. Метки `scope/*` (#1599) — те же слова.
TEXT: Final = "text"
CODE: Final = "code"
FLOWS: Final = "flows"
FULL: Final = "full"
#: Порядок сценариев: индекс — ширина.
ORDER: Final = (TEXT, CODE, FLOWS, FULL)
#: Приставка метки сценария.
LABEL_PREFIX: Final = "scope/"
#: Корни кода: модуль отсюда — узел графа по имени файла без расширения.
#: Источники — из объявления `paths.SOURCES`, хуки окна — их соседи по графу.
CODE_ROOTS: Final = (*(f"{one.as_posix()}/" for one in paths.SOURCES), ".claude/hooks/")
#: Тест-файлы — то, что выбирается.
TESTS: Final = "tests/"
#: Помощники всех тестов: их правка — полный набор, их рёбра данных — не чтение теста.
CONFTEST: Final = "tests/conftest.py"
#: Общие для всех: тронуты — набор полный.
WHOLE_FILES: Final = frozenset(
    {CONFTEST, "pyproject.toml", paths.VERSION.as_posix(), paths.PIPELINE.as_posix()}
)
#: Прогоны и действия: тронуты — сценарий `flows`, набор полный (41 тест-файл их судит).
FLOWS_ROOTS: Final = (f"{paths.WORKFLOWS.as_posix()}/", f"{paths.ACTIONS.as_posix()}/")
#: Известные места дерева. Тронутое вне их — полный набор, а не «никто не зависит».
KNOWN: Final = (
    *CODE_ROOTS,
    TESTS,
    ".github/",
    ".claude/",
    ".rules/",
    "docs/",
    f"{paths.FRAGMENTS.as_posix()}/",
    "export/",
    f"{paths.KIT.as_posix()}/",
)
#: Корневые файлы, известные по имени.
KNOWN_FILES: Final = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        paths.CHANGELOG.as_posix(),
        "HISTORY.md",
        "LICENSE",
        ".gitignore",
        *WHOLE_FILES,
    }
)
#: Вызовы тестов, первым доводом которых идёт имя скрипта.
SCRIPT_CALLS: Final = frozenset({"load_script", "run_script"})
#: Обходы всего кода проекта.
CODE_WALKS: Final = frozenset({"code_files", "code_roots"})
#: Предел времени git: дерево базы и списки путей — локальные операции.
GIT_TIMEOUT: Final = 120
#: Сводный гейт, чей зелёный исход делает голову «проверенной» (#1602).
GREEN_CHECK: Final = "ci-complete"
#: Сколько прежних голов спрашивать: дальше суд от общего предка — дедлайн
#: прогона тестов (10 мин) не тратится на опрос длинной истории (100).
MAX_HEADS: Final = 20


class NotRun(RuntimeError):
    """Выбор не отработал: третий исход, а не «тронуто ничего»."""


@dataclass(slots=True)
class Edges:
    """Что файл зовёт (код, транзитивно) и что читает (данные, в один шаг)."""

    code: set[str] = field(default_factory=set)
    data: set[str] = field(default_factory=set)
    #: Почему файл зависит от всего; пусто — граф его понял.
    whole: str = ""


@dataclass(frozen=True, slots=True)
class Choice:
    """Ответ классификатора: сценарий и тесты; `tests` None — полный набор."""

    scenario: str
    tests: tuple[str, ...] | None
    why: str


def modules(files: Iterable[str]) -> dict[str, set[str]]:
    """Имя модуля → пути: модуль `x` в `scripts/`, `packages/transport/` или `tests/` — `x`."""
    index: dict[str, set[str]] = {}
    for one in files:
        # Тест-модуль, импортированный другим тестом (`from tests.test_x import f`),
        # — тоже ребро кода: правка помощника в нём задевает и импортирующего.
        if one.endswith(".py") and one.startswith((*CODE_ROOTS, TESTS)):
            index.setdefault(Path(one).stem, set()).add(one)
    index.setdefault("conftest", set()).add("tests/conftest.py")
    return index


def called_name(node: ast.Call) -> str:
    """Имя зовомого: `f(…)` и `obj.f(…)` — оба `f`."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def first_text(node: ast.Call) -> str | None:
    """Первый довод вызова строкой; не литерал — `None`."""
    if node.args and isinstance(node.args[0], ast.Constant):
        value = node.args[0].value
        return value if isinstance(value, str) else None
    return None


def as_path(text: str, files: frozenset[str], dirs: frozenset[str]) -> str | None:
    """Литерал как путь дерева: файл — он сам, каталог — с косой на конце."""
    said = text.strip().removeprefix("./").rstrip("/")
    if not said or "\n" in said or len(said) > 200:
        return None
    if said in files:
        return said
    if said in dirs:
        return f"{said}/"
    return None


def edges_of(
    source: bytes, index: dict[str, set[str]], files: frozenset[str], dirs: frozenset[str]
) -> Edges:
    """Рёбра одного файла; не разобран — зависит от всего (с причиной)."""
    found = Edges()
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        found.whole = f"не разобран: {exc}"
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.code |= index.get(alias.name.split(".")[-1], set())
                found.code |= index.get(alias.name.split(".")[0], set())
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.code |= index.get(module.split(".")[-1], set())
            for alias in node.names:
                found.code |= index.get(alias.name, set())
        elif isinstance(node, ast.Call):
            name = called_name(node)
            if name in SCRIPT_CALLS:
                said = first_text(node)
                if said is None:
                    found.whole = f"{name} не литералом"
                else:
                    found.code |= index.get(Path(said).stem, set())
            elif name in CODE_WALKS:
                found.data |= set(CODE_ROOTS)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            place = as_path(node.value, files, dirs)
            if place is not None:
                found.data.add(place)
    return found


def covers(target: str, path: str) -> bool:
    """Задевает ли тронутый путь цель ребра: файл — равенством, каталог — началом."""
    return path == target or (target.endswith("/") and path.startswith(target))


def dirs_of(files: Iterable[str]) -> set[str]:
    """Каталоги путей дерева разбором строки: `a/b/c.py` — `a` и `a/b`."""
    found: set[str] = set()
    for one in files:
        parts = one.split("/")[:-1]
        found |= {"/".join(parts[: n + 1]) for n in range(len(parts))}
    return found


def graph(root: Path, files: list[str]) -> dict[str, Edges]:
    """Рёбра каждого `.py` дерева, прочитанного с диска под `root`."""
    known = frozenset(files)
    dirs = frozenset(dirs_of(files))
    index = modules(files)
    edges: dict[str, Edges] = {}
    for one in files:
        if not one.endswith(".py"):
            continue
        try:
            source = (root / one).read_bytes()
        except OSError as exc:
            edges[one] = Edges(whole=f"не прочитан: {exc}")
            continue
        edges[one] = edges_of(source, index, known, dirs)
    return edges


def merged(*graphs: dict[str, Edges]) -> dict[str, Edges]:
    """Объединение графов базы и головы: ребро любого из них — ребро."""
    out: dict[str, Edges] = {}
    for one in graphs:
        for name, said in one.items():
            mine = out.setdefault(name, Edges())
            mine.code |= said.code
            mine.data |= said.data
            mine.whole = mine.whole or said.whole
    return out


def touched_code(edges: dict[str, Edges], touched: set[str]) -> set[str]:
    """Файлы кода, задетые транзитивно: тронутые и все, кто их зовёт по цепочке."""
    hit = {one for one in touched if one in edges}
    while True:
        more = {name for name, said in edges.items() if name not in hit and said.code & hit}
        if not more:
            return hit
        hit |= more


def chosen(edges: dict[str, Edges], touched: set[str]) -> tuple[str, ...]:
    """Тесты, которые изменение задело: кодом по цепочке, данными в один шаг.

    Тронутого нет — тестов нет, и тест «дерево целиком» тоже не идёт: он
    зависит от всего, а от ничего не зависит никто (взгляд на #1605).
    """
    if not touched:
        return ()
    code = touched_code(edges, touched)

    def reads(name: str, *, own: bool) -> bool:
        # Каталог в литерале МОДУЛЯ — якорь пути (`Path("scripts")` в paths.py), а
        # не чтение: обход делает тот, кто зовёт помощника. Поэтому у зовомого
        # модуля считаются только файлы, у самого теста — и каталоги.
        data = edges[name].data
        targets = data if own else {one for one in data if not one.endswith("/")}
        return any(covers(target, path) for target in targets for path in touched)

    picked: set[str] = set()
    for name, said in edges.items():
        if not is_test(name):
            continue
        # `conftest` — помощники всех тестов: его рёбра данных — не чтение каждого.
        helpers = [one for one in said.code if one in edges and one != CONFTEST]
        if (
            said.whole
            or name in code
            or said.code & code
            or reads(name, own=True)
            or any(reads(one, own=False) for one in helpers)
        ):
            picked.add(name)
    return tuple(sorted(picked))


def is_test(name: str) -> bool:
    """Тест-файл набора: `tests/test_*.py`."""
    return name.startswith(TESTS) and Path(name).name.startswith("test_")


def scenario(touched: set[str], areas: tuple[scope_areas.Area, ...] = ()) -> tuple[str, str]:
    """Сценарий по тронутому и причина, когда он `full`; пути областей — известные места."""
    if not touched:
        return TEXT, ""
    if hit := sorted(touched & WHOLE_FILES):
        return FULL, f"тронут общий для всех файл: {', '.join(hit)}"
    if strange := sorted(
        one
        for one in touched
        if not one.startswith(KNOWN)
        and one not in KNOWN_FILES
        and not scope_areas.known(one, areas)
    ):
        return FULL, f"место вне известных: {', '.join(strange[:3])}"
    if any(one.startswith(FLOWS_ROOTS) for one in touched):
        return FLOWS, "тронуты прогоны или действия"
    if any(one.endswith(".py") and one.startswith((*CODE_ROOTS, TESTS)) for one in touched):
        return CODE, ""
    return TEXT, ""


def classify(
    touched: set[str], edges: dict[str, Edges], areas: tuple[scope_areas.Area, ...] = ()
) -> Choice:
    """Сценарий и выбор тестов для тронутого по готовому графу или по областям.

    ОБЛАСТИ ЗАМЕНЯЮТ ГРАФ, А НЕ ДОПОЛНЯЮТ (#1600). Объявлены — выбор начинается
    со всех тестов и теряет тесты нетронутых областей: граф судит формами
    нашего дерева, и у потребителя с иными формами он выбрал бы меньше, чем
    задето. Общие для всех файлы, неизвестное место и прогоны — полный набор
    и при областях.
    """
    kind, why = scenario(touched, areas)
    if kind in (FULL, FLOWS):
        return Choice(kind, None, why)
    if not areas:
        return Choice(kind, chosen(edges, touched), "")
    every = sorted(name for name in edges if is_test(name))
    kept = scope_areas.narrowed(every, touched, areas)
    if len(kept) == len(every):
        return Choice(kind, None, "области: тронутое задевает все")
    quiet = [area.name for area in areas if not area.touched_by(touched)]
    return Choice(kind, kept, f"области не задеты: {', '.join(quiet)}")


def label_of(kind: str) -> str:
    """Метка сценария: `scope/<сценарий>`."""
    return f"{LABEL_PREFIX}{kind}"


def widest(names: Iterable[str]) -> str | None:
    """Самый широкий сценарий среди меток; меток сценария нет — None.

    Чужое слово после приставки — не сценарий и не учитывается: список меток
    разрешительный, и необъявленную метку судит гейт разметки (068).
    """
    kinds = [name.removeprefix(LABEL_PREFIX) for name in names if name.startswith(LABEL_PREFIX)]
    known = [kind for kind in kinds if kind in ORDER]
    return max(known, key=ORDER.index) if known else None


def widened(choice: Choice, names: Iterable[str]) -> Choice:
    """Выбор с поправкой на метку владельца: метка только расширяет (#1599).

    МЕТКА — СЛЕД КЛАССИФИКАТОРА, А НЕ ВХОД, кроме одного направления. Метка уже
    ответа не сужает выбор: сузить значило бы пропустить красное по слову, а не
    по графу, — такую метку отвергает гейт разметки. Шире — владелец хочет
    больше проверок, чем вывел граф, и `flows`/`full` дают полный набор.
    """
    labelled = widest(names)
    if labelled is None or ORDER.index(labelled) <= ORDER.index(choice.scenario):
        return choice
    tests = None if labelled in (FLOWS, FULL) else choice.tests
    return Choice(labelled, tests, f"сценарий расширен меткой {label_of(labelled)}")


def git(root: Path, *args: str) -> str:
    """Git с дедлайном; отказ, отсутствие или истёкший предел — `NotRun` (gitcall)."""
    return gitcall.output(["-C", str(root), *args], NotRun, timeout=GIT_TIMEOUT)


def tracked(root: Path, ref: str = "") -> list[str]:
    """Пути дерева: рабочего (`ref` пуст) или коммита."""
    said = (
        git(root, "ls-tree", "-r", "-z", "--name-only", ref) if ref else git(root, "ls-files", "-z")
    )
    return [one for one in said.split("\0") if one]


def touched_paths(root: Path, fork: str) -> set[str]:
    """Тронутое от общего предка: коммиты ветки, правки рабочего дерева и новые файлы.

    Переименование даёт оба имени, удаление — прежнее: тест, звавший удалённое,
    обязан быть выбран.
    """
    changed = [
        one
        for one in git(root, "diff", "-z", "--name-only", "--no-renames", fork).split("\0")
        if one
    ]
    fresh = [
        one
        for one in git(root, "ls-files", "-z", "--others", "--exclude-standard").split("\0")
        if one
    ]
    return {*changed, *fresh}


def base_graph(root: Path, fork: str) -> dict[str, Edges]:
    """Граф дерева общего предка: распакован во временный каталог, рабочее не трогается."""
    with tempfile.TemporaryDirectory() as room:
        try:
            archive = subprocess.run(
                ["git", "-C", str(root), "archive", "--format=tar", fork],
                capture_output=True,
                timeout=GIT_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotRun(f"дерево базы {fork} не прочитано: {exc}") from exc
        if archive.returncode != 0:
            raise NotRun(f"дерево базы {fork} не прочитано: {report.cut(archive.stderr.decode())}")
        try:
            subprocess.run(
                ["tar", "-x", "-C", room],
                input=archive.stdout,
                capture_output=True,
                timeout=GIT_TIMEOUT,
                check=True,
            )
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            raise NotRun(f"дерево базы {fork} не распаковано: {exc}") from exc
        return graph(Path(room), tracked(root, fork))


def fork_of(root: Path, base: str, head: str = "HEAD") -> str:
    """Общий предок головы с базой; не найден — `NotRun`."""
    try:
        return journal.common_ancestor(base, head, root=root)
    except journal.NotRun as exc:
        raise NotRun(str(exc)) from exc


def common(left: tuple[str, ...] | None, right: tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Пересечение выборов; None — «все», и пересечение с ним — другой выбор."""
    if left is None:
        return right
    if right is None:
        return left
    return tuple(sorted(set(left) & set(right)))


def joined(left: tuple[str, ...] | None, right: tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Объединение выборов; None — «все», и объединение с ним — «все»."""
    if left is None or right is None:
        return None
    return tuple(sorted({*left, *right}))


def again(
    root: Path,
    base: str,
    since: str,
    fork: str,
    edges: dict[str, Edges],
    areas: tuple[scope_areas.Area, ...] = (),
) -> Choice:
    """Повторный толчок: судится изменённое с зелёной головы `since` (#1602).

    СВОЁ — ТО, ЧТО ПОМЕНЯЛОСЬ С `since` И ОТЛИЧАЕТСЯ ОТ ВЕРШИНЫ БАЗЫ. Файл,
    совпадающий с новой базой, пришёл влитой базой и проверен на ней: судить его
    здесь значило бы гнать чужое. Поменялось только сообщение коммита — дерево
    то же, своего нет, тестов ноль.

    ОТКАТ К БАЗЕ — СВОЙ, А НЕ ПРИШЕДШИЙ (взгляд на #1605). Файл, вернувшийся с
    зелёной головы к вершине базы, совпадает с базой, но принесла его не база,
    если база его не трогала: это своя правка — откат, — и она судится. Иначе
    зелёная голова с `b.py` и `test_b.py` и откат `b.py` давали пустое «своё»,
    и CI уходил «судить нечего», хотя `test_b` упадёт.

    ПРИШЕДШЕЕ В БАЗУ — ПЕРЕСЕЧЕНИЕМ. Сдвинулся общий предок — база принесла
    своё. Ломает изменение только то, что задевает и его, и пришедшее: тесты
    пересечения двух выборов. Пустое — повтор ничего не скажет. ГРАНИЦА НАЗВАНА
    (046): правки, не связанные графом, всё же могут сломать друг друга — это
    ловит полный набор слияния и общей ветки, а не этот выбор.
    """
    before = fork_of(root, base, since)
    came = (
        {
            one
            for one in git(root, "diff", "-z", "--name-only", "--no-renames", before, fork).split(
                "\0"
            )
            if one
        }
        if before != fork
        else set()
    )
    moved = touched_paths(root, since)
    mine_now = touched_paths(root, base)
    own = (moved & mine_now) | (moved - mine_now - came)
    kind, why = scenario(own, areas)
    note = f"повторный толчок от {since[:12]}"
    if kind in (FULL, FLOWS):
        return Choice(kind, None, f"{note}: {why}")
    picked = classify(own, edges, areas).tests if areas else chosen(edges, own)
    tests: tuple[str, ...] | None = picked
    if before != fork:
        mine = classify(touched_paths(root, fork), edges, areas).tests
        tests = joined(picked, common(classify(came, edges, areas).tests, mine))
        note += f"; база сдвинулась с {before[:12]}"
    return Choice(kind, tests, note)


def choose(root: Path, base: str, since: str = "") -> Choice:
    """Полный ответ: тронутое от общего предка или от зелёной головы, граф, выбор.

    `since` — последняя голова с зелёным сводным гейтом; пусто — первый толчок
    или красная прежняя голова, и суд идёт от общего предка.
    """
    fork = fork_of(root, base)
    try:
        areas = pipeline_checks.areas_for_tests(root / paths.PIPELINE)
    except scope_areas.BadAreas as exc:
        raise NotRun(str(exc)) from exc
    edges = merged(base_graph(root, fork), graph(root, tracked(root)))
    said = (
        again(root, base, since, fork, edges, areas)
        if since
        else classify(touched_paths(root, fork), edges, areas)
    )
    return present(said, set(tracked(root)))


def present(choice: Choice, files: set[str]) -> Choice:
    """Выбор без тест-файлов, которых в голове нет (взгляд на #1605).

    Граф объединяет базу и голову: тест, удалённый или переименованный
    изменением, есть в графе базы и выбирается по прежнему имени — pytest
    получил бы несуществующий путь и покраснел ошибкой сбора.
    """
    if choice.tests is None:
        return choice
    return Choice(choice.scenario, tuple(one for one in choice.tests if one in files), choice.why)


def last_green(repo: str, number: int, token: str, root: Path) -> str:
    """Последняя голова изменения, кроме нынешней, с зелёным `ci-complete` (#1602).

    Головы — коммиты изменения от новых к старым, не больше `MAX_HEADS`;
    голова засчитывается, если она есть в дереве (переписанная история её
    теряет) и сводный гейт на ней `success`. Нет такой — пусто: суд от общего
    предка. Отказ площадки — `NotRun`: зовущий судит от предка, а не «ничего не
    тронуто» (039).
    """
    head = git(root, "rev-parse", "HEAD").strip()
    try:
        heads = [
            str(one.get("sha") or "")
            for one in ghrest.paginate(f"repos/{repo}/pulls/{number}/commits", token)
        ]
        for sha in [one for one in reversed(heads) if one and one != head][:MAX_HEADS]:
            runs = ghrest.paginate(
                f"repos/{repo}/commits/{sha}/check-runs?check_name={GREEN_CHECK}",
                token,
                key="check_runs",
            )
            if not any(run.get("conclusion") == "success" for run in runs):
                continue
            try:
                git(root, "cat-file", "-e", f"{sha}^{{commit}}")
            except NotRun:
                continue
            return sha
    except ghrest.TransportError as exc:
        raise NotRun(f"зелёная голова не найдена: {exc}") from exc
    return ""


def failed_files(report: Path) -> set[str]:
    """Тест-файлы, упавшие в отчёте pytest `--junitxml`; отчёт не читается — `NotRun`.

    Файл выводится из `classname` (`tests.test_x` или `tests.test_x.Класс`):
    поле `file` pytest пишет не во всех формах отчёта.
    """
    try:
        cases = ElementTree.parse(report).getroot().iter("testcase")
    except (OSError, ElementTree.ParseError) as exc:
        raise NotRun(f"отчёт тестов {report} не прочитан: {exc}") from exc
    found: set[str] = set()
    for case in cases:
        if case.find("failure") is None and case.find("error") is None:
            continue
        parts = str(case.get("classname") or "").split(".")
        for end, part in enumerate(parts):
            if part.startswith("test_"):
                found.add("/".join(parts[: end + 1]) + ".py")
                break
    return found


def missed(choice: Choice, failed: set[str]) -> list[str]:
    """Упавшие тест-файлы, которых выбор не назвал (#1598); полный выбор не пропускает."""
    if choice.tests is None:
        return []
    return sorted(failed - set(choice.tests))


def said_missed(root: Path, base: str, report: Path) -> int:
    """Полный прогон общей ветки покраснел: назвать, что выбор изменения пропустил (#1598).

    Слитый коммит судится от `base` (на общей ветке — `HEAD^`) выбором ПЕРВОГО
    толчка — всем тронутым изменением. Упавший тест вне выбора — НАХОДКА О
    ГРАФЕ, а не мигание: ребра, которое его связало бы с правкой, граф не видит.
    Исход — «назван»: краснеет прогон сам, этот шаг только говорит, почему
    изменение было зелёным.

    ГРАНИЦА НАЗВАНА (046, взгляд на #1605): повторный толчок судился уже — от
    зелёной головы (`again`), и что он сузил, отсюда не видно: какую голову
    изменение сочло зелёной, знает только его прогон. Пропуск, рождённый этим
    сужением, здесь читается как «выбор первого толчка задел упавшее», и вывод
    говорит именно это, а не «выбор задел».
    """
    try:
        failed = failed_files(report)
        gaps = missed(choose(root, base), failed)
    except NotRun as exc:
        print(f"пропуск выбора не сверен: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    for one in gaps:
        print(
            f"::error::выбор тестов пропустил {one}: упал на полном прогоне, а изменению "
            "его не назвал — находка о графе (навык what-the-graph-misses)"
        )
    if not gaps:
        print(
            f"выбор первого толчка задел все упавшие тест-файлы: {len(failed)} "
            "(сужение повторных толчков отсюда не сверить)"
        )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает сценарий; с `--tests` — выбранные тест-файлы построчно."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="", help="с чем сравнивать; по умолчанию база изменения")
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--tests", action="store_true", help="напечатать выбранные тест-файлы")
    parser.add_argument(
        "--labels", default="", help="метки изменения через пробел: `scope/*` расширяет сценарий"
    )
    parser.add_argument(
        "--since", default="", help="зелёная прежняя голова: судить изменённое с неё"
    )
    parser.add_argument(
        "--pr", type=int, default=0, help="номер изменения: зелёную голову спросить у площадки"
    )
    parser.add_argument(
        "--missed",
        type=Path,
        help="отчёт pytest --junitxml полного прогона: назвать упавшее, что выбор пропустил",
    )
    args = parser.parse_args(argv)
    if args.missed:
        return said_missed(args.root, journal.base_from_env(args.base), args.missed)
    since = args.since
    if not since and args.pr:
        try:
            since = last_green(
                os.environ.get("GITHUB_REPOSITORY", ""), args.pr, ghrest.token_from_env(), args.root
            )
        except NotRun as exc:
            print(f"зелёная голова не найдена — суд от общего предка: {exc}", file=sys.stderr)
    try:
        said = choose(args.root, journal.base_from_env(args.base), since)
    except NotRun as exc:
        print(f"выбор не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    said = widened(said, args.labels.split())
    if args.tests:
        if said.tests is None:
            print("ALL")
        else:
            print("\n".join(said.tests))
        return EXIT_OK
    shown = "все" if said.tests is None else str(len(said.tests))
    print(
        f"сценарий: {said.scenario}; тест-файлов: {shown}" + (f" — {said.why}" if said.why else "")
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
