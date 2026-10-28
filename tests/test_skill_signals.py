"""Признаки навыков: у каждого навыка — ключ `expected`, у каждого признака — свой случай (#1694).

Обе половины: признак срабатывает на следе, ради которого заведён, и молчит на
соседнем; навык без ключа и признак чужой формы — отказ с именем навыка, а не
«не ждали никогда» (045).
"""

import subprocess
from pathlib import Path, PurePosixPath

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


def skilled_repo(root: Path, head: str) -> list[str]:
    """Репозиторий с одним навыком, чья шапка — `head`; отдаёт приставку вызова git."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)]
    (root / ".claude" / "skills" / "x").mkdir(parents=True)
    (root / ".claude" / "skills" / "x" / "SKILL.md").write_text(head, encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "навык"], check=True)
    return git


def test_signals_are_read_at_the_commit_not_the_tree(tmp_path: Path) -> None:
    """Признаки — шапки навыков НА КОММИТЕ: правка дерева после него их не меняет (#1715)."""
    git = skilled_repo(tmp_path, '---\nexpected:\n  touched: ["a.py"]\n---\n')
    (tmp_path / ".claude" / "skills" / "x" / "SKILL.md").write_text(
        '---\nexpected:\n  touched: ["b.py"]\n---\n', encoding="utf-8"
    )
    said = module.signals_at("HEAD", tmp_path)
    assert said["x"].touched == ("a.py",)
    subprocess.run([*git, "commit", "-q", "-am", "сегодня"], check=True)
    assert module.signals_at("HEAD~1", tmp_path)["x"].touched == ("a.py",)


def test_a_commit_before_any_signal_says_so_and_a_bad_one_refuses(tmp_path: Path) -> None:
    """Без ключа на коммите — `NoSignals`; неверный коммит — `BadSignals`, а не пусто."""
    skilled_repo(tmp_path, "---\nname: x\n---\n")
    with pytest.raises(module.NoSignals):
        module.signals_at("HEAD", tmp_path)
    with pytest.raises(module.BadSignals, match="ls-tree"):
        module.signals_at("нет-такого", tmp_path)


def test_a_skill_left_unmarked_beside_marked_ones_is_named(tmp_path: Path) -> None:
    """Ключ есть у одних навыков и нет у другого — отказ с его именем, а не «ещё не было»."""
    git = skilled_repo(tmp_path, '---\nexpected:\n  touched: ["a.py"]\n---\n')
    (tmp_path / ".claude" / "skills" / "y").mkdir()
    (tmp_path / ".claude" / "skills" / "y" / "SKILL.md").write_text("---\nname: y\n---\n", "utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "новый навык"], check=True)
    with pytest.raises(module.BadSignals, match="без ключа expected: y") as caught:
        module.signals_at("HEAD", tmp_path)
    assert not isinstance(caught.value, module.NoSignals)
