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
import io
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

from tests.conftest import HOOKS, code_files, code_roots, found_by, load_script, walk, walk_deep

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


#: Адрес теста: `tests/<файл>.py` и, если назван, `::<имя>`. Левая граница
#: обязательна: `packages/x/tests/y.py` или адрес в чужом репозитории — не наш
#: `tests/`, и судить его по нашему дереву значило бы краснеть ложно (взгляд на
#: #1224).
TEST_ADDRESS_RE = re.compile(r"(?<![\w./-])tests/(?P<file>[\w/]+\.py)(?:::(?P<name>\w+))?")
#: Где живут адреса тестов: перечень корней (068), а не обход всего дерева.
#: Код (`.py`) входит наравне с прозой — гейт `модуль.имя` выше адреса вида
#: `tests/<файл>.py::имя` не ловит, — и `.rules/` тоже: гейт адресов ответов
#: сверяет там имя файла, но не `::имя` (взгляд на #1224). Корни КОДА не
#: перечисляются заново, а берутся из `paths.py::SOURCES`, как у `SOURCES`
#: выше: новый источник там иначе прошёл бы мимо этого гейта (071, взгляд на
#: #1224).
LIVE_ROOTS = (
    *(where.as_posix() for where in load_script("paths.py").SOURCES),
    "tests",
    ".claude",
    ".github",
    "docs",
    "kit",
    ".rules",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
)
LIVE_SUFFIXES = frozenset({".py", ".yml", ".yaml", ".md", ".json", ".sh", ".toml"})
#: Не сверяются, с причиной (154): записи решений — история, ссылка там
#: говорит, где лежало тогда. Выпущенный журнал вне корней по той же причине.
HISTORY = ("docs/decisions/",)
#: Адреса, мёртвые НАРОЧНО: проза называет их как несуществующие. Значение —
#: файлы, где адрес назван, и причина. Каждое исключение обязано быть
#: заслуженным: адрес мёртв и стоит ИМЕННО в названных файлах — иначе причина
#: устареет молча (044, взгляд на #1224;
#: `test_every_deliberately_dead_address_is_earned`).
DELIBERATELY_DEAD: dict[str, tuple[tuple[str, ...], str]] = {
    "tests/test_journal.py": (
        ("scripts/check_journal.py", "tests/test_messages_point_somewhere.py"),
        "называют его как сторож, которого не существует — находка о самом его отсутствии",
    ),
}


def live_files() -> list[Path]:
    """Файлы под корнями `LIVE_ROOTS` с адресами тестов, без истории."""
    found: list[Path] = []
    for root in LIVE_ROOTS:
        where = ROOT / root
        candidates = [where] if where.is_file() else walk_deep(where)
        found += [
            one
            for one in candidates
            if one.is_file()
            and one.suffix in LIVE_SUFFIXES
            and not one.relative_to(ROOT).as_posix().startswith(HISTORY)
        ]
    return found


def prose_of(path: Path) -> str:
    """Проза файла: у кода — комментарии и докстроки, у прочего — весь текст.

    Строки кода — данные, а не ссылки: адрес файла-подделки в тесте — вход
    разбора, и требовать от него существования значило бы красить
    исправное (так же решено в `test_messages_point_somewhere.py`).
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".py":
        return text
    parts = [
        token.string
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    ]
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            said = ast.get_docstring(node, clean=False)
            if said:
                parts.append(said)
    return "\n".join(parts)


def defined_in(path: Path) -> set[str]:
    """Имена, которые модуль ОПРЕДЕЛЯЕТ: функции, классы, присваивания — не импорты.

    Импорт — чужое имя: `Path`, импортированный в модуль тестов, адресом теста
    живым быть не должен (взгляд на #1224).
    """
    return names_of(path) - {
        (one.asname or one.name.split(".")[0])
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for one in node.names
    }


def dead_test_addresses(text: str, where: str = "") -> list[str]:
    """Адреса тестов в тексте `where`, которые ведут в пустоту: нет файла или имени в нём.

    Нарочно мёртвый адрес прощается только в местах, названных в
    `DELIBERATELY_DEAD`: ключ исключения — пара «адрес и место», а не один адрес.
    Иначе третий файл, назвавший того же несуществующего сторожа живым, прошёл
    бы молча (взгляд на #1230).
    """
    dead = []
    for found in TEST_ADDRESS_RE.finditer(text):
        path = ROOT / "tests" / found.group("file")
        excused = DELIBERATELY_DEAD.get(found.group(0))
        if excused and where in excused[0]:
            continue
        if not path.is_file():
            dead.append(f"{found.group(0)} — нет файла")
        elif found.group("name") and found.group("name") not in defined_in(path):
            dead.append(f"{found.group(0)} — нет имени")
    return dead


@pytest.mark.parametrize(
    ("text", "dead"),
    [
        ("держит `tests/test_live_references.py::dead_test_addresses`", 0),
        ("держит `tests/test_live_references.py::переименован`", 1),
        ("держит `tests/test_нет_такого.py`", 1),
        ("держит `tests/test_live_references.py`", 0),
        ("держит `tests/test_live_references.py::Path`", 1),
        ("держит `packages/x/tests/test_нет_такого.py`", 0),
        ("держит `other/repo/tests/test_нет_такого.py`", 0),
    ],
    ids=[
        "живое имя",
        "мёртвое имя",
        "нет файла",
        "файл без имени",
        "импорт — не имя модуля",
        "чужой tests/ в пакете",
        "чужой tests/ в адресе",
    ],
)
def test_a_test_address_is_judged_by_file_and_name(text: str, dead: int) -> None:
    """Адрес теста судится по обеим половинам: файл есть, имя в нём определено."""
    assert len(dead_test_addresses(text)) == dead


def test_code_is_judged_by_its_prose_only(tmp_path: Path) -> None:
    """У кода судятся комментарии и докстроки, строки-данные — нет."""
    code = tmp_path / "x.py"
    code.write_text(
        '"""Держит `tests/test_нет_докстроки.py`."""\n'
        "# держит `tests/test_нет_комментария.py`\n"
        'DATA = "tests/test_данные.py"\n',
        encoding="utf-8",
    )
    said = prose_of(code)
    assert "test_нет_докстроки" in said and "test_нет_комментария" in said
    assert "test_данные" not in said


def test_every_test_address_is_alive() -> None:
    """Каждый адрес `tests/<файл>.py[::имя]` в живом дереве указывает на живое.

    Сверка была частной: один тест в `test_task_items.py` проверял ссылки
    одного прогона на один файл тестов (взгляд на #1211). Первая редакция
    общего гейта взяла только прозу и пропустила код и `.rules/` (взгляд на
    #1224). Замер 08.10.2026: 563 адреса под корнями, мёртвые — только
    нарочные из `DELIBERATELY_DEAD`.
    """
    seen = 0
    dead: list[str] = []
    for path in live_files():
        text = prose_of(path)
        seen += len(TEST_ADDRESS_RE.findall(text))
        place = path.relative_to(ROOT).as_posix()
        dead += [f"{place}: {one}" for one in dead_test_addresses(text, place)]
    assert seen, "адресов тестов в дереве нет — предмет проверки не найден (075)"
    assert not dead, "адреса тестов ведут в пустоту:\n  " + "\n  ".join(dead)


def test_a_deliberately_dead_address_is_excused_only_in_its_places() -> None:
    """Тот же мёртвый адрес вне названных мест — мёртв (взгляд на #1230)."""
    said = "сторож `tests/test_journal.py`"
    assert dead_test_addresses(said, "scripts/check_journal.py") == []
    assert len(dead_test_addresses(said, "docs/новый.md")) == 1


def test_every_package_is_a_declared_source() -> None:
    """Каждый пакет в `packages/` назван в `paths.py::SOURCES` (взгляд на #1230).

    Корни кода этот гейт берёт из `SOURCES`, а не из всего `packages/`: пакет,
    положенный туда без записи, выпал бы из сверки адресов молча. Сверка держит
    обе стороны — и `SOURCES` как единственный перечень, и полноту сверки.
    """
    declared = {where.as_posix() for where in load_script("paths.py").SOURCES}
    packages = sorted(
        one.relative_to(ROOT).as_posix()
        for one in walk(ROOT / "packages")
        if one.is_dir() and found_by(one, "**/*.py")
    )
    assert packages, "пакетов нет — предмет сверки не найден (075)"
    missing = [one for one in packages if one not in declared]
    assert not missing, f"пакеты вне `paths.py::SOURCES`: {missing}"


def same_names(files: list[Path]) -> dict[str, list[str]]:
    """Имена `.py`-файлов, встреченные больше одного раза, — с местами, в одном корне или в разных.

    Ключ — имя файла, а не путь модуля: тёзок внутри одного корня (`x.py` в
    каталоге и в его подкаталоге) ключ по имени смешает так же, как тёзок из
    разных корней (взгляд на #1307).
    """
    seen: dict[str, list[str]] = {}
    for path in files:
        seen.setdefault(path.name, []).append(path.relative_to(ROOT).as_posix())
    return {name: places for name, places in sorted(seen.items()) if len(places) > 1}


def blind_roots(roots: list[str], places: list[str], base: Path = ROOT) -> list[str]:
    """Корни, где лежит `.py`, но в обходе нет ни одного файла из них (взгляды на #1315, #1319)."""
    return [
        root
        for root in roots
        if found_by(base / root, "**/*.py")
        and not any(one.startswith(f"{root}/") for one in places)
    ]


def test_module_names_are_unique_across_the_roots() -> None:
    """Имя `.py`-файла одно на корни кода, `tests/` и хуки на Python (#1273, #1276, 210).

    Обходы, переведённые на два корня, исключают и ключуют файл по имени
    (`path.name`, `stem`): одноимённый модуль в `packages/transport` молча выпал
    бы из гейта или схлопнулся с модулем из `scripts/`. Чинить каждый обход
    — форма за формой; строгое правило одно: имя уникально, и тогда ключ по
    имени верен везде. Замер 09.10.2026: одноимённых модулей ноль.

    НАБОР И ХУКИ — В ТОМ ЖЕ ПРАВИЛЕ (взгляд на #1276). `NOT_REFERENCES` ищет
    файл по `path.name` в наборе с `tests/`, и правило без них обещало бы
    больше, чем держит. Замер 10.10.2026 с `tests/` и `.claude/hooks`:
    одноимённых файлов ноль.

    ПРЕДЕЛ НАЗВАН (взгляд на #1307): судятся только `.py` — `code_files` ищет
    по `*.py`. Хуки на оболочке (`*.sh`) сюда не входят: их по имени не
    ключует ни один обход, и правило о них ничего не обещает.

    ЧТО ГЕЙТ ВИДИТ ВСЕ СВОИ КОРНИ, СВЕРЯЕТ ОН САМ (взгляды на #1307, #1315):
    проба вне гейта судила бы обёртку, а не вызов в гейте. Корни — каждый из
    `paths.SOURCES`, ради тёзок которых правило и заведено, плюс набор и хуки:
    выпади любой из `code_files`, гейт краснеет, а не зеленеет на половине.

    ТЁЗКИ ПО УСТРОЙСТВУ ЯЗЫКА ЗАПРЕЩЕНЫ ТОЖЕ, И ЭТО ВЫБОР (взгляды на #1315,
    #1319). Второй `__init__.py`, вложенный `conftest.py` или `__main__.py`
    гейт краснит: `LIVE` ключует модули по `stem`, а `NOT_REFERENCES` ищет
    файл по `name`, и тёзка схлопнул бы их молча. Изъять эти имена — значит
    держать обходы удачей, а не гейтом. Понадобится подпакет — сперва обходы
    переводятся на путь, потом снимается запрет.
    """
    files = code_files(with_tests=True, with_hooks=True)
    places = [path.relative_to(ROOT).as_posix() for path in files]
    # Корни — из того же `code_roots`, что обходит `code_files`: второй список
    # отстал бы от первого (взгляд на #1319). Требуется корень, где `.py`
    # вообще лежит: хуки на одной оболочке гейт красить не должны.
    roots = [one.as_posix() for one in code_roots(with_tests=True, with_hooks=True)]
    blind = blind_roots(roots, places)
    assert not blind, f"гейт имён не видит корни: {blind}"
    twins = same_names(files)
    assert not twins, f"одноимённые `.py`-файлы — ключ по имени их смешает: {twins}"


def test_a_root_without_python_is_not_blind(tmp_path: Path) -> None:
    """Корень на одной оболочке гейт не красит, а корень с `.py` вне обхода — красит (#1319)."""
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "guard.sh").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
    assert blind_roots(["hooks", "src"], [], tmp_path) == ["src"]
    assert blind_roots(["hooks", "src"], ["src/a.py"], tmp_path) == []


def test_code_roots_hold_every_declared_source() -> None:
    """Корни обхода — каждый из `paths.SOURCES`, набор и хуки: список не теряет источник (#1319)."""
    roots = set(code_roots(with_tests=True, with_hooks=True))
    assert set(load_script("paths.py").SOURCES) <= roots, f"источник выпал из корней: {roots}"
    assert {Path("tests"), HOOKS} <= roots, f"набор или хуки выпали из корней: {roots}"


def test_a_twin_name_is_named() -> None:
    """Проба: тёзки называются с местами — в разных корнях и внутри одного (взгляд на #1315)."""
    one = ROOT / "scripts" / "x.py"
    two = ROOT / "packages" / "transport" / "x.py"
    assert same_names([one, two]) == {"x.py": ["scripts/x.py", "packages/transport/x.py"]}
    nested = ROOT / "scripts" / "sub" / "x.py"
    assert same_names([one, nested]) == {"x.py": ["scripts/x.py", "scripts/sub/x.py"]}
    package = [ROOT / "scripts" / "__init__.py", ROOT / "scripts" / "sub" / "__init__.py"]
    assert same_names(package) == {
        "__init__.py": ["scripts/__init__.py", "scripts/sub/__init__.py"]
    }, "имя, повторяемое языком, пропущено: обходы по имени схлопнули бы его (#1319)"


def addresses_in(text: str) -> set[str]:
    """Адреса тестов в тексте — тем же образцом, что судит гейт, а не подстрокой."""
    return {found.group(0) for found in TEST_ADDRESS_RE.finditer(text)}


def test_an_address_inside_another_is_not_a_meeting() -> None:
    """Чужой `tests/` и адрес с именем не засчитываются встречей адреса файла."""
    said = "`packages/x/tests/test_journal.py` и `tests/test_journal.py::x`"
    assert "tests/test_journal.py" not in addresses_in(said)
    assert "tests/test_journal.py" in addresses_in("называет `tests/test_journal.py`")


def test_every_deliberately_dead_address_is_earned() -> None:
    """Нарочно мёртвый адрес мёртв и стоит в каждом названном файле (044, 075)."""
    for address, (where, why) in DELIBERATELY_DEAD.items():
        assert why.strip() and where, f"{address}: исключение без мест и причины (154)"
        assert not (ROOT / address).exists(), f"{address}: адрес жив, исключение не нужно"
        for named in where:
            assert address in addresses_in(prose_of(ROOT / named)), (
                f"{address}: в `{named}` адреса нет — причина исключения устарела"
            )


def test_code_files_reach_a_nested_source(tmp_path: Path) -> None:
    """Общий обходчик видит вложенный каталог источника — как сверка пакетов (взгляд на #1252).

    Неглубокий обход пропускал вложенное молча, а восемь гейтов брали его
    копии: каждый пропустил бы одно и то же.

    Соседи (CI и взгляд на #1298): копия сборки `build/lib/`, которую прячет
    `.gitignore`, кодом не считается; новый модуль до `git add` — считается.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    for where in load_script("paths.py").SOURCES:
        (tmp_path / where / "nested").mkdir(parents=True)
        (tmp_path / where / "top.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / where / "nested" / "deep.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    for where in load_script("paths.py").SOURCES:
        (tmp_path / where / "build" / "lib").mkdir(parents=True)
        (tmp_path / where / "build" / "lib" / "top.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / where / "fresh.py").write_text("x = 1\n", encoding="utf-8")
    found = {one.relative_to(tmp_path).as_posix() for one in code_files(root=tmp_path)}
    for where in load_script("paths.py").SOURCES:
        assert f"{where.as_posix()}/nested/deep.py" in found, sorted(found)
        assert f"{where.as_posix()}/fresh.py" in found, sorted(found)
        assert f"{where.as_posix()}/build/lib/top.py" not in found, sorted(found)


def test_code_files_outside_git_is_a_named_refusal(tmp_path: Path) -> None:
    """Вне рабочего дерева git обходчик отказывает словами проекта, а не трассой (075, #1298)."""
    for where in load_script("paths.py").SOURCES:
        (tmp_path / where).mkdir(parents=True)
        (tmp_path / where / "top.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="не рабочее дерево git"):
        code_files(root=tmp_path)
