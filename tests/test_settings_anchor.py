"""У настроек один якорь, и поиска вверх по дереву нет.

Правило каталога
[115](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/115-config-has-one-anchor-and-a-bounded-search.md)
до этого гейта держалось построением: адреса настроек были короткими, каждый
читатель писал `Path("...")` сам, и завести второй якорь ничто не мешало.

ЗАВЕСТИ УСПЕЛИ, И ЭТО ЗАМЕР, А НЕ ОПАСЕНИЕ. 09.09.2026 путь `CONTRACT_VERSION`
строился в трёх модулях сразу — `build_changelog.py`, `build_facts.py`,
`check_version.py`. Три независимых адреса у единственного источника версии:
правка в одном месте выглядит полной, а расходятся они молча.

ВТОРАЯ ПОЛОВИНА ПРАВИЛА — ЗАПРЕТ ПОИСКА. Механизм, ищущий `.pipeline.yml`
вверх по дереву, в чужом окружении находит файл соседнего проекта и молча
принимает его за свой. Поэтому пути строятся ОТ якоря, а не разыскиваются.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import load_script

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ANCHOR = SCRIPTS / "paths.py"
paths = load_script("paths.py")

#: Якорь объявляет адреса; все остальные их импортируют.
ANCHOR_NAME = ANCHOR.name
#: Построение пути литералом: `Path("что-то")`.
LITERAL_PATH_RE = re.compile(r'Path\(\s*["\']([^"\']+)["\']')
#: Адрес настройки, написанный ГОЛОЙ строкой: `".rules/bindings.json"`. Второй
#: якорь заводится и так — обёртка в `Path` тут ни при чём, а прежний образец
#: видел только её. Замер 11.09.2026: три адреса каталога правил жили в
#: `drift.py` строками, два из них уже были объявлены якорем, третий — нет.
#: Нашёл внешний взгляд на #170.
SETTING_DIRS = ("\\.rules", "\\.github", "changelog\\.d")
BARE_PATH_RE = re.compile(r'["\']((?:' + "|".join(SETTING_DIRS) + r')/[\w./-]+\.[a-z]{2,5})["\']')
#: Поиск вверх по дереву в любом виде.
SEARCH_RE = re.compile(r"\.parents\b|\.parent\.parent\b|rglob\(|os\.getcwd\(")

#: Пути, которые механизм вправе построить сам: они не настройки, а его
#: собственный вывод или временный файл. Список разрешительный (068).
NOT_SETTINGS = frozenset({".", "..", ""})

#: Каталоги кода, объявленные якорем. ИХ СОСТАВ — ТОЖЕ НАСТРОЙКА, и образец
#: выше его не видел: он ловит адреса ФАЙЛОВ под `.rules`, `.github` и
#: `changelog.d`, а «где живёт код» — это каталоги, и написаны они иначе.
#:
#: Замер 16.09.2026: состав источников был объявлен строками ДВАЖДЫ помимо
#: якоря — в гейте «новое приезжает со своим прогоном» (нашёл внешний взгляд,
#: `675d64c`) и в гейте журнала, где это уже стоило дыры: `packages/transport/`
#: в перечне не было, и починка общего низа проходила БЕЗ единой проверки.
SOURCE_DIRS = frozenset(one.as_posix() for one in paths.SOURCES)


def scripts() -> list[Path]:
    """Механизмы проекта, кроме самого якоря."""
    return sorted(p for p in SCRIPTS.glob("*.py") if p.name != ANCHOR_NAME)


def declared_in_the_anchor() -> set[Path]:
    """Адреса, объявленные якорем: читаются из модуля, а не из его текста."""
    return {
        value
        for name, value in vars(paths).items()
        if not name.startswith("_") and isinstance(value, Path)
    }


def test_the_anchor_exists_and_declares_something() -> None:
    """Предмет проверки найден: якорь есть и не пуст (075)."""
    assert ANCHOR.is_file(), "якоря настроек нет — проверять нечего"
    assert declared_in_the_anchor(), "якорь не объявляет ни одного адреса"


def test_the_declared_list_covers_every_address() -> None:
    """`paths.ALL` — не украшение: он перечисляет ровно то, что объявлено.

    Список, о котором сказано «по нему сверяет гейт», обязан быть тем, что гейт
    действительно читает, иначе это обещание в прозе. Добавленный мимо `ALL`
    адрес разошёлся бы с ним молча: снаружи полный список и неполный выглядят
    одинаково ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    missing = sorted(str(item) for item in declared_in_the_anchor() - set(paths.ALL))
    assert not missing, f"адрес объявлен, а в paths.ALL его нет: {missing}"
    stray = sorted(str(item) for item in set(paths.ALL) - declared_in_the_anchor())
    assert not stray, f"paths.ALL называет то, чего якорь не объявляет: {stray}"


@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.name)
def test_no_second_anchor_is_declared(path: Path) -> None:
    """Механизм берёт адрес настройки у якоря, а не строит свой.

    Замер 09.09.2026: у `CONTRACT_VERSION` было три независимых адреса.
    """
    said = path.read_text(encoding="utf-8")
    built = {found for found in LITERAL_PATH_RE.findall(said) if found not in NOT_SETTINGS}
    # ГОЛАЯ СТРОКА — ТОТ ЖЕ ВТОРОЙ ЯКОРЬ. Обёртка в `Path` к делу не относится:
    # расходятся адреса, а не их типы.
    built |= {found for found in BARE_PATH_RE.findall(said) if found not in NOT_SETTINGS}
    assert not built, (
        f"{path.name} строит адрес настройки сам: {sorted(built)} — "
        f"второй якорь заводится именно так, а объявлены они в {ANCHOR_NAME}"
    )


#: Каталоги, целиком отданные под хранилища объявлений: всё, что там лежит, —
#: настройка, и адрес ей полагается у якоря. Список закрытый и мал намеренно:
#: `.github/` и `changelog.d/` сюда не идут — там живут прогоны и фрагменты,
#: то есть файлы, которые механизмы перебирают глобом, а не адресуют поимённо.
STORAGE_DIRS: Final = (".rules",)


def test_every_file_of_the_storage_is_declared() -> None:
    """Файл, лежащий в хранилище объявлений, назван якорем поимённо.

    ПОЛНОТА СПИСКА — НЕ ТО ЖЕ, ЧТО ЕГО СОГЛАСОВАННОСТЬ. Соседняя проверка
    сверяет `paths.ALL` с тем, что якорь объявил, — то есть якорь с самим собой.
    Файл, положенный в `.rules/` мимо якоря, обе стороны этой сверки оставляет
    верными и потому не краснеет нигде
    ([115](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/115-config-has-one-anchor-and-a-bounded-search.md),
    [096](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/096-storage-follows-lifecycle-not-convenience.md)).

    ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ПРОВЕРКА И НАПИСАНА: в `.rules/` одиннадцать
    записей, якорь объявлял десять. Необъявленным был `claims.json` —
    исключительные утверждения свода, — и единственный его читатель строил адрес
    сам. Ответ проекта при этом утверждал, что полноту держит механизм. Нашёл
    аудит ответа, а не гейт, потому что гейта на это и не было
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    declared = {value.as_posix() for value in declared_in_the_anchor()}
    stray: list[str] = []
    for where in STORAGE_DIRS:
        directory = ROOT / where
        assert directory.is_dir(), f"хранилища {where} нет — предмет проверки не найден (075)"
        stray += [
            f"{where}/{item.name}"
            for item in sorted(directory.iterdir())
            if item.is_file() and f"{where}/{item.name}" not in declared
        ]
    assert not stray, (
        "файл хранилища не объявлен якорем (096, 115):\n  "
        + "\n  ".join(stray)
        + f"\n  Объявите адрес в {ANCHOR_NAME} и внесите его в ALL: читатель,"
        " строящий адрес сам, и есть второй якорь."
    )


def anchor_files() -> set[str]:
    """Адреса ФАЙЛОВ, объявленных якорем, — прочитанные у якоря, а не угаданные.

    Каталоги (`scripts`, `changelog.d`) сюда не идут: их имена — ещё и обычные
    слова, ключ в витрине фактов среди прочего, и судить их по строке значило бы
    красить исправный код. Для них есть :func:`source_dirs_in`, который судит
    УПОТРЕБЛЕНИЕ. Каталог узнаётся по дереву, а не по списку имён.
    """
    return {
        value.as_posix()
        for value in declared_in_the_anchor()
        if not (ROOT / value).is_dir() and value.as_posix() not in NOT_SETTINGS
    }


@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.name)
def test_no_declared_address_is_written_out_by_hand(path: Path) -> None:
    """Адрес, объявленный якорем, не вписан в механизм строкой.

    ПРЕДМЕТ БЕРЁТСЯ У ЯКОРЯ, А НЕ ИЗ СПИСКА КАТАЛОГОВ. Образец `BARE_PATH_RE`
    выше знает ровно три каталога — `.rules`, `.github`, `changelog.d`, — и
    корневые настройки мимо него проходят целиком: `.pipeline.yml`,
    `CONTRACT_VERSION`, `CHANGELOG.md`, `README.md`. Замер 18.09.2026: якорь
    объявляет 23 адреса, из них **шесть** корневых, и вписанный рядом
    `"CONTRACT_VERSION"` не покраснел бы нигде — то есть правило исполнялось и
    держалось привычкой
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

    Угаданный список каталогов заменён замером по самому якорю: он и есть
    канонический перечень настроек, и расходиться с собой не может
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
    [068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
    """
    written = sorted(written_as_a_path(path, anchor_files()))
    assert not written, (
        f"{path.name} вписывает адрес настройки строкой: {written} — "
        f"он объявлен в {ANCHOR_NAME}, и вписанная копия расходится с ним молча"
    )


def written_as_a_path(path: Path, wanted: frozenset[str] | set[str]) -> set[str]:
    """Имена из `wanted`, написанные в файле КАК ПУТЬ, а не как слово.

    СУДИТСЯ УПОТРЕБЛЕНИЕ, А НЕ СТРОКА, и это не педантизм: «scripts» — ещё и
    ключ в витрине фактов, а «README.md» — имя в сравнении `path.name == …`;
    запретить слово значило бы красить исправный код. Путь узнаётся по тому, что
    с ним делают: делят через `/`, кладут в `Path()` или ищут по нему начало
    пути. Первая редакция сверяла строки и покраснела на ключе JSON — поймано
    первым же прогоном (051); вторая, уже по адресам якоря, покраснела на четырёх
    сравнениях по имени файла — поймано откатом в тот же день.

    ХОДОК ЗДЕСЬ ОДИН НА ДВА ПРЕДМЕТА. Каталоги кода и файлы настроек судятся по
    одному признаку, и второй такой разбор разошёлся бы с первым молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()

    def named(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            said = node.value.rstrip("/")
            return said if said in wanted else None
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            for side in (node.left, node.right):
                if (said := named(side)) is not None:
                    found.add(said)
        elif isinstance(node, ast.Call):
            call = node.func
            head = call.attr if isinstance(call, ast.Attribute) else getattr(call, "id", "")
            if head in {"Path", "startswith", "glob", "rglob"}:
                for one in node.args:
                    if (said := named(one)) is not None:
                        found.add(said)
        # Прибитый слэш делает строку путём независимо от употребления:
        # «scripts/» ключом не бывает.
        elif (
            isinstance(node, ast.Constant)
            and str(node.value).endswith("/")
            and (said := named(node)) is not None
        ):
            found.add(said)
    return found


def source_dirs_in(path: Path) -> set[str]:
    """Каталоги кода, написанные в файле как путь."""
    return written_as_a_path(path, SOURCE_DIRS)


@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.name)
def test_no_mechanism_lists_the_source_dirs_itself(path: Path) -> None:
    """«Где живёт код» механизм читает у якоря, а не перечисляет строками.

    Состав источников — настройка наравне с адресами файлов, и второе его
    написание расходится с первым МОЛЧА: новый каталог кода выпадает из-под
    гейта, не покраснев. Здесь это уже случилось — гейт журнала не считал
    `packages/transport/` механизмом, и починка общего низа проходила без
    единой проверки (022, 090).
    """
    listed = sorted(source_dirs_in(path))
    assert not listed, (
        f"{path.name} перечисляет каталоги кода строками: {listed} — "
        f"состав источников объявлен в {ANCHOR_NAME}, поле SOURCES"
    )


@pytest.mark.parametrize("path", [*scripts(), ANCHOR], ids=lambda p: p.name)
def test_no_mechanism_searches_up_the_tree(path: Path) -> None:
    """Настройка не разыскивается вверх по дереву, а берётся от якоря.

    Поиск нашёл бы файл соседнего проекта и принял бы его за свой — молча,
    потому что снаружи «нашёл чужой» и «нашёл свой» выглядят одинаково.
    """
    found = SEARCH_RE.findall(path.read_text(encoding="utf-8"))
    assert not found, f"{path.name} ищет настройку вверх по дереву: {sorted(set(found))}"
