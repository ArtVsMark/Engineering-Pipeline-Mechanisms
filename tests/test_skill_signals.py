"""Признаки навыков: у каждого навыка — ключ `expected`, у каждого признака — свой случай (#1694).

Обе половины: признак срабатывает на следе, ради которого заведён, и молчит на
соседнем; навык без ключа и признак чужой формы — отказ с именем навыка, а не
«не ждали никогда» (045).
"""

from pathlib import PurePosixPath

import pytest

from tests.conftest import ROOT, load_script

module = load_script("skill_signals.py")
TABLE = module.signals(ROOT)


def example(glob: str) -> str:
    """Путь, на котором шаблон обязан сработать: звёзды заменены словом."""
    return glob.replace("**", "x").replace("*", "x")


def test_every_skill_of_the_tree_declares_its_signals() -> None:
    """У каждого навыка дерева — признаки или «none — причина»; признаков нет ни у кого — отказ."""
    assert TABLE, "навыков не найдено — гейт доказывал бы только себя (075)"
    assert any(not one.none for one in TABLE.values()), "ни у одного навыка нет машинного следа"


@pytest.mark.parametrize(
    ("name", "kind", "value"),
    [
        (name, kind, value)
        for name, one in sorted(TABLE.items())
        for kind in module.KINDS
        for value in getattr(one, kind)
    ],
)
def test_every_signal_fires_on_its_own_trace(name: str, kind: str, value: str) -> None:
    """Каждый признак срабатывает на своём следе — и только его навык ждали по нему одному."""
    one = TABLE[name]
    if kind == "body":
        assert one.match([], [], f"Тема\n\n{value} 1")
    else:
        path = example(value)
        assert PurePosixPath(path).full_match(value), f"пример {path} не подходит к {value}"
        touched, added = ([path], []) if kind == "touched" else ([path], [path])
        assert one.match(touched, added, "")


def test_a_signal_is_silent_on_a_neighbouring_trace() -> None:
    """След рядом — не след: `added` не срабатывает на правке, `body` — на прозе."""
    assert not TABLE["build-a-gate"].match(["scripts/check_x.py"], [], "")
    assert not TABLE["close-a-finding"].match([], [], "в теле упомянуто Разобрано: внутри фразы")
    assert not TABLE["answer-a-rule"].match([".rules/other.json"], [], "")


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("# без шапки\n", "нет шапки"),
        ("---\nname: x\n---\n", "нет ключа expected"),
        ("---\nexpected: сделать\n---\n", "none — <причина>"),
        ("---\nexpected:\n  paths: [x]\n---\n", "незнакомые виды"),
        ("---\nexpected:\n  touched: x\n---\n", "список непустых строк"),
        ("---\nexpected: [\n---\n", "не разобрана"),
        ("---\nexpected:\n  data: [нет-такого]\n---\n", "ключей нет в таблице путей"),
    ],
)
def test_a_broken_signal_is_refused_with_the_skill_named(text: str, said: str) -> None:
    """Шапки нет, ключа нет, вид чужой, значение не той формы — отказ с именем навыка."""
    with pytest.raises(module.BadSignals, match=said):
        module.signals_of("навык", text)


def test_expected_names_every_skill_whose_trace_is_there() -> None:
    """Ожидание — по всем навыкам сразу, без повторов и по имени."""
    said = module.expected(TABLE, ["scripts/check_x.py"], ["scripts/check_x.py"], "Разобрано: abc")
    assert "build-a-gate" in said and "close-a-finding" in said and said == sorted(set(said))


def test_a_data_signal_follows_the_projects_own_paths() -> None:
    """Ключ `data` — путь из таблицы проекта: переназначенный файл ловится, умолчание — нет."""
    text = "---\nexpected:\n  data: [bindings]\n---\n"
    moved = {**module.paths.PROJECT, "bindings": module.Path("answers/ours.json")}
    one = module.signals_of("навык", text, moved)
    assert one.match(["answers/ours.json"], [], "")
    assert not one.match([module.paths.BINDINGS.as_posix()], [], "")
