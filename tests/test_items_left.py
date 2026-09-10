"""Открытый пункт, за которым уже есть работа, — и задача, которая молчит.

Счёт по пунктам шёл в одну сторону: `debt` называл задачу, у которой все пункты
закрыты, а сама она открыта. Обратное — пункт открыт, а работа сделана — не
видел никто, и копилось именно оно.

Проверяется здесь то, без чего оба признака были бы напоминанием:

* сильный признак опирается на «появилось ПОСЛЕ постановки», а не на «названо и
  существует»: файл, живший до задачи, не доказывает ничего;
* слабый молчит там, где сработал сильный, — один долг, названный дважды,
  читается как два (022);
* оба проверены отказом: сказано, при каких данных они НЕ срабатывают (140).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests.conftest import load_script

module = load_script("items_left.py")
items = load_script("items.py")

DAY_ONE = datetime(2026, 9, 1, tzinfo=UTC)
DAY_TEN = datetime(2026, 9, 10, tzinfo=UTC)


def repo_with(tmp_path: Path, name: str, when: datetime, body: str = "x = 1\n") -> Path:
    """Дерево под git с одним файлом, добавленным в назначенный день."""
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "первый"],
        cwd=tmp_path,
        check=True,
        env={
            "GIT_AUTHOR_DATE": when.isoformat(),
            "GIT_COMMITTER_DATE": when.isoformat(),
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
        },
    )
    return tmp_path


def issue(number: int, body: str, created: datetime, updated: datetime) -> dict[str, Any]:
    """Задача в том виде, в каком её отдаёт площадка."""
    return {
        "number": number,
        "title": f"задача {number}",
        "body": body,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "updated_at": updated.isoformat().replace("+00:00", "Z"),
    }


def test_a_file_born_after_the_task_is_evidence(tmp_path: Path) -> None:
    """Названный пунктом файл, которого на день постановки не было, — находка."""
    root = repo_with(tmp_path, "scripts/check_thing.py", DAY_TEN)
    found = module.evidence(
        "- [ ] гейт живёт в `scripts/check_thing.py`", DAY_ONE, module.tracked(root), root
    )
    assert found == ["scripts/check_thing.py"]


def test_a_file_older_than_the_task_proves_nothing(tmp_path: Path) -> None:
    """Файл, живший до постановки, находкой НЕ является.

    Пункт часто называет файл как МЕСТО будущей работы: «добавить счёт в
    `scripts/debt.py`». Считать это сделанным значило бы объявлять готовым всё
    с первого дня — напоминание, которое звучит всегда, перестаёт что-либо
    значить (051).
    """
    root = repo_with(tmp_path, "scripts/debt.py", DAY_ONE)
    found = module.evidence(
        "- [ ] добавить счёт в `scripts/debt.py`", DAY_TEN, module.tracked(root), root
    )
    assert found == []


def test_a_named_file_absent_from_the_tree_proves_nothing(tmp_path: Path) -> None:
    """Названного в дереве нет — значит работа не сделана, а имя чужое.

    Живой случай: эпик называет `gh_rest.py` соседа, у нас файл зовётся иначе.
    Совпадения по прозе тут быть не должно.
    """
    root = repo_with(tmp_path, "scripts/ghrest.py", DAY_TEN)
    found = module.evidence(
        "- [ ] перенести `gh_rest.py` пакетом", DAY_ONE, module.tracked(root), root
    )
    assert found == []


def test_a_test_name_is_looked_up_by_its_definition(tmp_path: Path) -> None:
    """Имя теста ищется как ОБЪЯВЛЕНИЕ, а не как упоминание.

    Имя теста встречается и в прозе задачи, и в сообщении чужого коммита;
    искать любое вхождение значило бы считать находкой собственный пересказ.
    """
    root = repo_with(tmp_path, "tests/test_x.py", DAY_TEN, "def test_a_gate_is_red():\n    pass\n")
    found = module.evidence(
        "- [ ] проверено отказом: `test_a_gate_is_red`", DAY_ONE, module.tracked(root), root
    )
    assert found == ["test_a_gate_is_red()"]


def test_the_quiet_count_stays_silent_where_the_strong_one_spoke(tmp_path: Path) -> None:
    """Задача, попавшая в сильный счёт, во второй не попадает.

    Один долг, названный дважды, читается как два, а списки того же самого
    расходятся молча (022).
    """
    root = repo_with(tmp_path, "scripts/check_thing.py", DAY_TEN)
    long_ago = DAY_TEN - timedelta(days=30)
    tasks = [issue(1, "- [ ] гейт в `scripts/check_thing.py`", DAY_ONE, long_ago)]
    built, quiet = module.look(tasks, items.open_items, now=DAY_TEN + timedelta(days=1), root=root)
    assert [c.number for c in built] == [1]
    assert quiet == []


def test_a_task_without_events_is_the_weak_signal(tmp_path: Path) -> None:
    """Пункт ничего не называет — задачу видно только по молчанию."""
    root = repo_with(tmp_path, "scripts/other.py", DAY_ONE)
    long_ago = DAY_TEN - timedelta(days=30)
    tasks = [issue(2, "- [ ] шаблон обращения трёх видов", DAY_ONE, long_ago)]
    built, quiet = module.look(tasks, items.open_items, now=DAY_TEN + timedelta(days=1), root=root)
    assert built == []
    assert [(q.number, q.left) for q in quiet] == [(2, 1)]


def test_a_task_without_open_items_is_not_quiet(tmp_path: Path) -> None:
    """Молчание задачи БЕЗ открытых пунктов долгом не является.

    Иначе в счёт попадает всё, что просто лежит, — и число перестаёт значить
    «есть что доделать».
    """
    root = repo_with(tmp_path, "scripts/other.py", DAY_ONE)
    long_ago = DAY_TEN - timedelta(days=30)
    tasks = [issue(3, "- [x] всё сделано", DAY_ONE, long_ago)]
    built, quiet = module.look(tasks, items.open_items, now=DAY_TEN + timedelta(days=1), root=root)
    assert (built, quiet) == ([], [])


def test_a_recently_touched_task_is_not_quiet(tmp_path: Path) -> None:
    """Свежая задача в слабый счёт не попадает — срок объявлен, а не подразумевается."""
    root = repo_with(tmp_path, "scripts/other.py", DAY_ONE)
    tasks = [issue(4, "- [ ] что-то", DAY_ONE, DAY_TEN)]
    built, quiet = module.look(tasks, items.open_items, now=DAY_TEN + timedelta(days=1), root=root)
    assert (built, quiet) == ([], [])
