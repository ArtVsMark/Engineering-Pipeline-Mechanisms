"""Свежесть свода проверяется тем, что гейт обязан отвергнуть.

Прогоняется каждый объявленный исход, включая третий — «не отработал»
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md),
[145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).

ОТДЕЛЬНО ДЕРЖИТСЯ ГРАНИЦА, КОТОРАЯ ДАЛА БЫ ЛОЖНОЕ КРАСНОЕ. Правка свода СВОИМ
же окном правилу 047 не подчиняется: окно её знает, она прошла через его работу.
У текущего окна таких правок девять, и без этой границы все девять покрасили бы
исправную работу.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
import yaml

from tests.conftest import ROOT, WINDOW_A, WINDOW_B, commit, git, load_script

module = load_script("check_rulebook_fresh.py")

BROKEN: Final = 2
FOUND: Final = 1
CLEAN: Final = 0

SKILL_DIR: Final = ROOT / ".claude" / "skills"


def edit_rulebook(root: Path, subject: str, *, day: float, session: str | None) -> None:
    """Коммит, правящий свод, от имени названного окна."""
    (root / "AGENTS.md").write_text(subject, encoding="utf-8")
    git(root, "add", "AGENTS.md")
    commit(root, subject, day=day, session=session)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Дерево с общей веткой, на которой окно `A` уже отметилось."""
    root = tmp_path / "tree"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Artem Markitanov")
    git(root, "config", "user.email", "86671904+ArtVsMark@users.noreply.github.com")
    (root / "AGENTS.md").write_text("свод как он был при старте окна", encoding="utf-8")
    git(root, "add", "AGENTS.md")
    commit(root, "первая работа окна", day=0)
    return root


def run(root: Path, *args: str) -> int:
    """Заход гейта по подготовленному дереву."""
    code: int = module.main(["--root", str(root), "--base", "main", "--history", "main", *args])
    return code


def test_an_untouched_rulebook_is_clean(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Свод не менялся — чистый исход, и окно при этом НАЗВАНО.

    Молчаливое зелёное ничем не отличалось бы от невыполненной проверки (075).
    """
    git(tree, "checkout", "-b", "work")
    commit(tree, "работа на второй день", day=1)
    assert run(tree, "--head", "work") == CLEAN
    assert WINDOW_A in capsys.readouterr().out, "окно не названо"


def test_a_foreign_edit_under_a_live_window_is_named(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Чужая правка свода между началом окна и его головой — исход «найдено».

    Это и есть предмет правила 047: окно продолжает работать по своду, которого
    оно не читало.
    """
    edit_rulebook(tree, "свод переписан соседом", day=0.5, session=WINDOW_B)
    git(tree, "checkout", "-b", "work")
    commit(tree, "работа после чужой правки", day=1)
    git(tree, "checkout", "main")
    git(tree, "merge", "--ff-only", "work")
    assert run(tree, "--head", "main", "--base", "main~2") == FOUND
    said = capsys.readouterr().out
    assert "свод менялся под ним" in said
    assert "свод переписан соседом" in said, "правка не названа поимённо (154)"
    assert module.SKILL in said, "навык перечитывания не назван — чинить нечем"


def test_a_first_change_of_a_window_still_sees_the_edit(tmp_path: Path) -> None:
    """Окно, чья первая работа ещё НЕ слита, всё равно видит чужую правку свода.

    ЗДЕСЬ ГЕЙТ БЫЛ СЛЕП, И СЛЕП МОЛЧА. Начало окна искалось только в истории
    общей ветки; у окна без слитых коммитов там нет ничего, и `window.lifetime`
    законно называет началом саму голову — для СРОКА жизни это верно, срок
    нулевой. Для свежести свода тот же ответ даёт пустой промежуток: между
    «началом» и головой не помещается ни одна правка, и гейт молчит ровно на
    первом изменении окна — том самом, где свод новее всего. Нашёл внешний
    взгляд находкой `734268a` на #377.
    """
    root = tmp_path / "tree"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Artem Markitanov")
    git(root, "config", "user.email", "86671904+ArtVsMark@users.noreply.github.com")
    (root / "AGENTS.md").write_text("свод при старте окна A", encoding="utf-8")
    git(root, "add", "AGENTS.md")
    # В общей ветке окна A нет вовсе: работал здесь только сосед.
    commit(root, "работа соседа", day=0, session=WINDOW_B)
    git(root, "checkout", "-b", "work")
    commit(root, "первый коммит окна A", day=1, session=WINDOW_A)
    git(root, "checkout", "main")
    edit_rulebook(root, "сосед переписал свод", day=2, session=WINDOW_B)
    # Сливать ветку незачем: правка лежит в ИСТОРИИ, а гейт читает историю.
    # Предмет здесь — начало окна, а не состав ветки.
    git(root, "checkout", "work")
    commit(root, "вторая работа окна A", day=3, session=WINDOW_A)
    code = module.main(
        ["--root", str(root), "--base", "main", "--history", "main", "--head", "work"]
    )
    assert code == FOUND, "правка свода под первым изменением окна не найдена"


def test_a_windows_own_edit_is_not_a_finding(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Своя же правка свода красным не считается — окно её знает.

    Без этой границы каждое окно, тронувшее `AGENTS.md`, красило бы само себя:
    у текущего окна таких правок девять (замер 16.09.2026).
    """
    edit_rulebook(tree, "свод правит само окно", day=0.5, session=WINDOW_A)
    git(tree, "checkout", "-b", "work")
    commit(tree, "работа после своей правки", day=1)
    assert run(tree, "--head", "work") == CLEAN, capsys.readouterr().out


def test_an_edit_before_the_window_started_is_not_a_finding(tmp_path: Path) -> None:
    """Правка ДО начала окна — это свод, который окно и прочитало при старте.

    Нижняя граница названа: иначе гейт краснел бы на всей истории свода разом.
    """
    root = tmp_path / "tree"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Artem Markitanov")
    git(root, "config", "user.email", "86671904+ArtVsMark@users.noreply.github.com")
    (root / "AGENTS.md").write_text("свод до окна", encoding="utf-8")
    git(root, "add", "AGENTS.md")
    commit(root, "чужая правка свода до начала окна", day=0, session=WINDOW_B)
    git(root, "checkout", "-b", "work")
    commit(root, "первая работа окна A", day=1, session=WINDOW_A)
    assert (
        module.main(["--root", str(root), "--base", "main", "--history", "main", "--head", "work"])
        == CLEAN
    )


def test_a_change_without_a_window_has_no_subject(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Изменение без окна правилу 047 не подчиняется, и это СКАЗАНО (154)."""
    git(tree, "checkout", "-b", "work")
    commit(tree, "правка рукой человека", day=1, session=None, by_window=False)
    assert run(tree, "--head", "work") == CLEAN
    assert "предмета нет" in capsys.readouterr().out


def test_no_commits_is_the_third_outcome(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Коммитов между базой и головой нет — «не отработал», а не «чисто» (075)."""
    assert run(tree, "--head", "main") == BROKEN
    assert "шаг не отработал" in capsys.readouterr().err


def test_a_shallow_history_is_the_third_outcome(
    tmp_path: Path, tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Обрезанная история — «не отработал»: правки свода вышли бы неполными (045)."""
    edit_rulebook(tree, "чужая правка свода", day=0.5, session=WINDOW_B)
    commit(tree, "ещё работа окна", day=1)
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "--depth", "1", f"file://{tree}", str(shallow))
    assert module.main(["--root", str(shallow), "--base", "HEAD~0", "--history", "main"]) == BROKEN
    assert "шаг не отработал" in capsys.readouterr().err


def test_touching_reads_only_the_rulebook(tree: Path) -> None:
    """Читаются коммиты, тронувшие СВОД, а не вся история.

    Без сужения по путям гейт назвал бы правкой свода любой коммит, и отказ его
    стал бы шумом, в котором настоящая правка не видна (016).
    """
    commit(tree, "работа, свода не трогавшая", day=0.2)
    edit_rulebook(tree, "а вот это правка свода", day=0.4, session=WINDOW_B)
    found = module.touching("main", module.RULEBOOK, cwd=str(tree))
    assert len(found) == 2, "в выборку попали коммиты, свода не трогавшие"


def test_changed_under_bounds_the_window_on_both_sides(tree: Path) -> None:
    """Предикат ограничен с ОБЕИХ сторон: начало окна и голова.

    Снизу — правка, которую окно прочитало при старте. Сверху — правка, которой
    этому изменению ещё не видно. Обе границы названы, потому что каждая по
    отдельности давала бы ложное красное (195).
    """
    start = module.window.commits("main", cwd=str(tree))[0]
    edit_rulebook(tree, "правка внутри жизни окна", day=0.5, session=WINDOW_B)
    edit_rulebook(tree, "правка уже после головы", day=9, session=WINDOW_B)
    head = next(
        one
        for one in module.window.commits("main", cwd=str(tree))
        if one.message.startswith("правка внутри")
    )
    found = module.changed_under(WINDOW_A, start, head, "main", cwd=str(tree))
    assert [one.message.splitlines()[0] for one in found] == ["правка внутри жизни окна"], (
        "граница не удержала: в находку попало то, что вне жизни окна"
    )


# --- навык: форма и связь с гейтом --------------------------------------------


def skills() -> list[Path]:
    """Навыки дерева — по объявлению, а не по списку имён (005)."""
    return sorted(SKILL_DIR.glob("*/SKILL.md"))


def test_the_tree_declares_a_skill_at_all() -> None:
    """Навык найден: без него проверки ниже — поверхность без предмета (075)."""
    assert skills(), f"в {SKILL_DIR} нет ни одного SKILL.md"


@pytest.mark.parametrize("path", skills(), ids=lambda p: p.parent.name)
def test_a_skill_declares_its_name_and_description(path: Path) -> None:
    """У навыка есть frontmatter с непустыми `name` и `description`.

    Навык без описания площадка не позовёт: описание — единственное, по чему
    окно решает, применим ли он. Пустое описание снаружи неотличимо от
    заполненного (045).
    """
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: нет frontmatter"
    head = yaml.safe_load(text.split("---", 2)[1])
    assert isinstance(head, dict), f"{path}: frontmatter не разбирается"
    assert str(head.get("name") or "").strip(), f"{path}: имя не объявлено"
    assert str(head.get("description") or "").strip(), f"{path}: описание не объявлено"
    assert head["name"] == path.parent.name, (
        f"{path}: имя «{head['name']}» разошлось с каталогом «{path.parent.name}» — "
        "два имени у одного навыка расходятся молча (022)"
    )


def test_the_gate_and_the_skill_name_each_other() -> None:
    """Гейт зовёт навык по имени, и навык этим именем существует.

    Иначе отказ гейта называл бы починку, которой нет, — а это хуже молчания:
    читатель пойдёт искать (154).
    """
    assert (SKILL_DIR / module.SKILL / "SKILL.md").is_file(), (
        f"гейт зовёт навык «{module.SKILL}», а его в дереве нет"
    )


def test_the_skill_names_the_rule_it_closes() -> None:
    """Навык называет правило, машинную половину которого он и есть."""
    text = (SKILL_DIR / module.SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "047" in text, "навык не называет правила, ради которого заведён"
    for name in module.RULEBOOK:
        assert name in text, f"навык не называет {name} — перечитывать нечего"
