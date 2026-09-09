"""У настроек один якорь, и поиска вверх по дереву нет.

Правило каталога
[115](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/115-settings-have-one-anchor-not-a-search.md)
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

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ANCHOR = SCRIPTS / "paths.py"

#: Якорь объявляет адреса; все остальные их импортируют.
ANCHOR_NAME = ANCHOR.name
#: Построение пути литералом: `Path("что-то")`.
LITERAL_PATH_RE = re.compile(r'Path\(\s*["\']([^"\']+)["\']')
#: Поиск вверх по дереву в любом виде.
SEARCH_RE = re.compile(r"\.parents\b|\.parent\.parent\b|rglob\(|os\.getcwd\(")

#: Пути, которые механизм вправе построить сам: они не настройки, а его
#: собственный вывод или временный файл. Список разрешительный (068).
NOT_SETTINGS = frozenset({".", "..", ""})


def scripts() -> list[Path]:
    """Механизмы проекта, кроме самого якоря."""
    return sorted(p for p in SCRIPTS.glob("*.py") if p.name != ANCHOR_NAME)


def test_the_anchor_exists_and_declares_something() -> None:
    """Предмет проверки найден: якорь есть и не пуст (075)."""
    assert ANCHOR.is_file(), "якоря настроек нет — проверять нечего"
    declared = LITERAL_PATH_RE.findall(ANCHOR.read_text(encoding="utf-8"))
    assert declared, "якорь не объявляет ни одного адреса"


@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.name)
def test_no_second_anchor_is_declared(path: Path) -> None:
    """Механизм берёт адрес настройки у якоря, а не строит свой.

    Замер 09.09.2026: у `CONTRACT_VERSION` было три независимых адреса.
    """
    built = {
        found
        for found in LITERAL_PATH_RE.findall(path.read_text(encoding="utf-8"))
        if found not in NOT_SETTINGS
    }
    assert not built, (
        f"{path.name} строит адрес настройки сам: {sorted(built)} — "
        f"второй якорь заводится именно так, а объявлены они в {ANCHOR_NAME}"
    )


@pytest.mark.parametrize("path", [*scripts(), ANCHOR], ids=lambda p: p.name)
def test_no_mechanism_searches_up_the_tree(path: Path) -> None:
    """Настройка не разыскивается вверх по дереву, а берётся от якоря.

    Поиск нашёл бы файл соседнего проекта и принял бы его за свой — молча,
    потому что снаружи «нашёл чужой» и «нашёл свой» выглядят одинаково.
    """
    found = SEARCH_RE.findall(path.read_text(encoding="utf-8"))
    assert not found, f"{path.name} ищет настройку вверх по дереву: {sorted(set(found))}"
