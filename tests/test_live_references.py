"""Ссылка на чужую функцию в прозе обязана указывать на живое имя.

ПЕРЕИМЕНОВАНИЕ РАСХОДИТСЯ С ПРОЗОЙ МОЛЧА, и это не мелочь оформления. Проза
здесь — не украшение: комментарий «тот же приём и по той же причине — в такой-то
функции такого-то модуля» отправляет читателя к разбору, ради которого он и
написан. После переименования такой адрес ведёт в пустоту, и читатель
заключает, что механизма нет.

Пример адреса пишется здесь БЕЗ точки намеренно: этот файл проверяется наравне
с остальными, и образец внутри него сработал бы на себе.

ЗАМЕР 11.09.2026: одно переименование (было `own_jobs`, стало `roster_of`) оставило ТРИ
мёртвых адреса в двух чужих модулях, и внешний взгляд назвал каждый отдельной
находкой. Три находки об одном — это не три правки, а отсутствующий механизм
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЧИТАЮТСЯ ТОЛЬКО СВОИ МОДУЛИ. `pathlib.Path` и `json.loads` сюда не попадают: у
чужого имени нет нашего дерева, и проверять его нечем. Границу задаёт список
файлов в `scripts/`, а не догадка по виду имени
([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
"""

import ast
import re
from pathlib import Path

import pytest

from tests.conftest import code_files, walk_deep

ROOT = Path(__file__).resolve().parent.parent
#: Где живёт код, названо ОДИН раз — `paths.py::SOURCES`, — и читается отсюда.
#: Пока список строился глобом по `scripts/`, общий низ, уехавший в пакет, в
#: него не попадал вовсе: мёртвый адрес в `ghrest` или `report` этот гейт не
#: видел, а объявление рядом утверждало, что источников два. Нашёл внешний
#: взгляд находкой `23549d5` на #366.
SOURCES = code_files(with_tests=True)

#: Адрес вида `модуль.имя` внутри инлайн-кода. Скобки вызова необязательны:
#: в прозе пишут и `roster_of`, и `roster_of()`.
REFERENCE_RE = re.compile(r"`(?P<module>[a-z_][a-z0-9_]*)\.(?P<name>[a-z_][a-z0-9_]*)\(?\)?`")

#: Расширения файлов: `drift.py` — ИМЯ ФАЙЛА, а не адрес функции, и по виду они
#: неразличимы. Перечислены, а не угаданы по длине (068).
FILE_SUFFIXES = frozenset({"py", "yml", "yaml", "json", "md", "svg", "txt", "toml", "cfg", "lock"})

#: Файлы, где такие адреса были бы ДАННЫМИ, а не ссылками: дословные записи
#: реестра находок, чей текст сам является предметом проверки.
#:
#: СПИСОК ПУСТ, И ЭТО СОСТОЯНИЕ, А НЕ ЗАБЫВЧИВОСТЬ. Он был заведён сразу с
#: одной записью — «на всякий случай», — а в названном файле не нашлось ни
#: одного адреса, который поймал бы образец. Исключение, чья премиса не
#: проверена, выглядит защитой и ею не является
#: ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
#: Нашёл внешний взгляд на #211.
#:
#: Новая запись сюда допускается, только если файл ДЕЙСТВИТЕЛЬНО несёт такой
#: адрес: это проверяет `test_every_exception_is_earned`.
NOT_REFERENCES: dict[str, str] = {}


def names_of(path: Path) -> set[str]:
    """Имена верхнего уровня модуля: функции, классы, присваивания."""
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        # ИМПОРТЫ СЧИТАЮТСЯ ИМЕНАМИ МОДУЛЯ. `automerge.ghrest` — законный адрес:
        # общий транспорт зовут через модуль, который его импортировал, и в
        # прозе это пишут именно так.
        if isinstance(node, ast.Import):
            found.update((one.asname or one.name.split(".")[0]) for one in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.update((one.asname or one.name) for one in node.names)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            found.update(one.id for one in node.targets if isinstance(one, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


#: Живые имена берутся с ТЕХ ЖЕ источников, что и адреса. Разойдись эти два
#: списка — гейт молча перестал бы разрешать адрес в модуль, которого в первом
#: списке нет: ссылка на живое имя читалась бы как чужая и пропускалась (022).
LIVE = {path.stem: names_of(path) for path in code_files()}


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_a_named_function_of_ours_still_exists(path: Path) -> None:
    """Каждый адрес `модуль.имя` в прозе указывает на существующее имя."""
    if path.name in NOT_REFERENCES:
        pytest.skip(NOT_REFERENCES[path.name])
    dead = [
        f"{found.group('module')}.{found.group('name')}"
        for found in REFERENCE_RE.finditer(path.read_text(encoding="utf-8"))
        if found.group("name") not in FILE_SUFFIXES
        and found.group("module") in LIVE
        and found.group("name") not in LIVE[found.group("module")]
    ]
    assert not dead, f"{path.name}: адреса ведут в пустоту после переименования: {dead}"


def test_the_shared_bottom_is_read_as_a_source() -> None:
    """Общий низ — источник наравне со скриптами, и гейт его видит.

    ПРОПУСК ЗДЕСЬ БЕСШУМЕН ПО УСТРОЙСТВУ. Адрес в модуль, которого нет в списке
    живых, гейт считает ЧУЖИМ и пропускает — у чужого имени нашего дерева нет,
    и проверять его нечем. Значит потеря источника не краснеет нигде: она
    выглядит ровно как «адресов в этот модуль не писали»
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    Держать её можно только проверкой на сам ОХВАТ.

    ЗАМЕР 16.09.2026: в прозе дерева два адреса в общий низ — `ghrest.paginate`
    и `ghrest.token_from_env`. Пока список строился глобом по `scripts/`, оба
    не проверялись вовсе. Нашёл внешний взгляд находкой `23549d5` на #366.
    """
    bottom = {"ghrest", "report"}
    assert bottom <= {path.stem for path in SOURCES}, (
        f"общий низ выпал из источников: {sorted(bottom - {p.stem for p in SOURCES})}"
    )
    assert bottom <= set(LIVE), (
        "имена общего низа не разобраны — адрес в него гейт сочтёт чужим и пропустит"
    )


def test_the_gate_has_a_subject() -> None:
    """Гейт, не нашедший ни одного адреса, доказывает только себя (075)."""
    seen = sum(
        1
        for path in SOURCES
        if path.name not in NOT_REFERENCES
        for found in REFERENCE_RE.finditer(path.read_text(encoding="utf-8"))
        if found.group("module") in LIVE and found.group("name") not in FILE_SUFFIXES
    )
    assert seen, "адресов вида `модуль.имя` в дереве нет — предмет проверки не найден"


def test_every_exception_is_earned() -> None:
    """Исключение допускается, только если файл ДЕЙСТВИТЕЛЬНО несёт такой адрес.

    Незаслуженное исключение выглядит защитой и ею не является: читатель верит,
    что предмет там есть и намеренно пропущен, а его нет вовсе (044, 075).
    Ровно это и было: список завели с одной записью «на всякий случай», и
    поймал её внешний взгляд, а не прогон.
    """
    for name, why in NOT_REFERENCES.items():
        path = next((one for one in SOURCES if one.name == name), None)
        assert path is not None, f"исключение названо для файла, которого нет: {name}"
        assert why.strip(), f"{name}: исключение без причины (154)"
        addresses = [
            found.group(0)
            for found in REFERENCE_RE.finditer(path.read_text(encoding="utf-8"))
            if found.group("module") in LIVE and found.group("name") not in FILE_SUFFIXES
        ]
        assert addresses, f"{name}: исключать нечего — в файле нет ни одного такого адреса"


#: Адрес теста в прозе: `tests/<файл>.py` и, если назван, `::<имя>`.
TEST_ADDRESS_RE = re.compile(r"tests/(?P<file>[\w/]+\.py)(?:::(?P<name>\w+))?")
#: Где живёт ЖИВАЯ проза, которая отсылает к тестам: перечень корней (068), а
#: не обход всего дерева. Код (`.py`) сверяет гейт выше.
PROSE_ROOTS = (".github", ".claude", "docs", "kit", "AGENTS.md", "CLAUDE.md", "README.md")
PROSE_SUFFIXES = frozenset({".yml", ".yaml", ".md", ".json", ".sh", ".toml"})
#: Не сверяются, с причиной (154). Записи решений — история: ссылка там
#: говорит, где лежало тогда, и правка задним числом переписала бы её.
#: Выпущенный журнал и `.rules/` вне корней вовсе: первый тоже история, у
#: адресов механизмов в `.rules/` свой гейт — `test_bindings_addresses.py`.
PROSE_HISTORY = ("docs/decisions/",)


def prose_files() -> list[Path]:
    """Файлы живой прозы под корнями `PROSE_ROOTS`, без истории."""
    found: list[Path] = []
    for root in PROSE_ROOTS:
        where = ROOT / root
        candidates = [where] if where.is_file() else walk_deep(where)
        found += [
            one
            for one in candidates
            if one.is_file()
            and one.suffix in PROSE_SUFFIXES
            and not one.relative_to(ROOT).as_posix().startswith(PROSE_HISTORY)
        ]
    return found


def dead_test_addresses(text: str) -> list[str]:
    """Адреса тестов в тексте, которые ведут в пустоту: нет файла или имени в нём."""
    dead = []
    for found in TEST_ADDRESS_RE.finditer(text):
        path = ROOT / "tests" / found.group("file")
        if not path.is_file():
            dead.append(f"{found.group(0)} — нет файла")
        elif found.group("name") and found.group("name") not in names_of(path):
            dead.append(f"{found.group(0)} — нет имени")
    return dead


@pytest.mark.parametrize(
    ("text", "dead"),
    [
        ("держит `tests/test_live_references.py::dead_test_addresses`", 0),
        ("держит `tests/test_live_references.py::переименован`", 1),
        ("держит `tests/test_нет_такого.py`", 1),
        ("держит `tests/test_live_references.py`", 0),
    ],
    ids=["живое имя", "мёртвое имя", "нет файла", "файл без имени"],
)
def test_a_test_address_is_judged_by_file_and_name(text: str, dead: int) -> None:
    """Адрес теста судится по обеим половинам: файл есть, имя в нём есть."""
    assert len(dead_test_addresses(text)) == dead


def test_every_test_address_in_prose_is_alive() -> None:
    """Каждый адрес `tests/<файл>.py[::имя]` в живой прозе указывает на живое (взгляд на #1211).

    Сверка была частной: один тест в `test_task_items.py` проверял ссылки
    одного прогона на один файл тестов, а ссылки на `test_reusable_steps.py`
    рядом и ещё сотня в других прогонах и документах не сверялись никем —
    переименование протушило бы их молча. Замер 08.10.2026: 114 адресов в 47
    файлах живой прозы, мёртвых — ни одного.
    """
    files = prose_files()
    seen = 0
    dead: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        seen += len(TEST_ADDRESS_RE.findall(text))
        dead += [f"{path.relative_to(ROOT)}: {one}" for one in dead_test_addresses(text)]
    assert seen, "адресов тестов в живой прозе нет — предмет проверки не найден (075)"
    assert not dead, "адреса тестов ведут в пустоту:\n  " + "\n  ".join(dead)
