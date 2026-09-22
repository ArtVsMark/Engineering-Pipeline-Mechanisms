"""Правка файла прогона глушит агента — и об этом говорят ДО толчка.

21.09.2026 изменение #614 правило `.github/workflows/review.yml` и уехало в
общую ветку без внешнего взгляда. Площадка отказала действию агента — файл
прогона обязан совпадать с версией на общей ветке, — но шаг объявлен
`continue-on-error`, поэтому он остался ЗЕЛЁНЫМ. Тишина не покраснела нигде, и
узналось это из реестра #89 уже после слияния.

Проверяется здесь то, без чего предупреждение было бы догадкой:

* носители действия берутся ИЗ ДЕРЕВА по вызову, а не перечисляются именами:
  их три, и четвёртый появился бы молча;
* состав носителей спрашивается у ОБЩЕЙ ветки — с нею площадка и сравнивает;
* нетронутый прогон предупреждения не даёт: гейт, кричащий на здоровом, учат
  обходить (051);
* отсутствие носителей вовсе — третий исход, а не «чисто» (075).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("check_agent_silenced.py")

#: Прогон, который в дереве действие агента НЕ объявляет: правка такого файла
#: взгляда не глушит, и предупреждать о ней значило бы кричать на здоровом.
INNOCENT = ".github/workflows/ci.yml"


def tree(tmp_path: Path, carriers: dict[str, str], touched: dict[str, str]) -> Path:
    """Дерево с общей веткой и правкой поверх неё — настоящим git, а не подделкой.

    ПОДДЕЛКИ ЗДЕСЬ БЫТЬ НЕ МОЖЕТ: предмет проверки — два вопроса К GIT
    (`grep` по базе и `diff` против неё), и заменив их, проверялся бы не
    механизм, а заглушка
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    root = tmp_path / "дерево"
    (root / ".github" / "workflows").mkdir(parents=True)

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "проба@example.invalid")
    run("config", "user.name", "проба")
    for name, text in carriers.items():
        (root / name).write_text(text, encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "общая ветка")
    run("branch", "база")
    for name, text in touched.items():
        (root / name).write_text(text, encoding="utf-8")
    if touched:
        run("add", "-A")
        run("commit", "-qm", "правка")
    return root


CARRIER = f"шаг:\n  uses: {module.ACTION}@v1\n"


def test_a_touched_carrier_warns_that_the_look_will_be_silent(tmp_path: Path) -> None:
    """Правка носителя названа — с именем файла и с ценой (154)."""
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER, INNOCENT: "шаг: тесты\n"},
        {".github/workflows/review.yml": CARRIER + "# правка\n"},
    )
    code, said = module.look(root, "база")
    assert code == module.EXIT_SILENCED, said
    assert "review.yml" in said, "имя файла не названо — искать придётся вслепую"
    assert "НЕ БУДЕТ" in said, "цена правки не названа"


def test_an_untouched_carrier_stays_quiet(tmp_path: Path) -> None:
    """Вторая половина: тронут прогон БЕЗ действия — предупреждения нет.

    Без неё проверка неотличима от «изменение трогает `.github/workflows/`» —
    такая кричала бы на всякой правке конвейера, и её научились бы пролистывать
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER, INNOCENT: "шаг: тесты\n"},
        {INNOCENT: "шаг: тесты\n# правка\n"},
    )
    code, said = module.look(root, "база")
    assert code == module.EXIT_OK, said
    assert "не тронуты" in said


def test_the_carriers_come_from_the_tree_not_from_a_list(tmp_path: Path) -> None:
    """Носители находятся ПО ВЫЗОВУ, а любое имя файла — законное.

    Список именами устарел бы молча: действие объявляют три прогона, и четвёртый
    получил бы тишину без предупреждения
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    """
    свой = ".github/workflows/совсем-другое-имя.yml"
    root = tree(tmp_path, {свой: CARRIER}, {свой: CARRIER + "# правка\n"})
    code, said = module.look(root, "база")
    assert code == module.EXIT_SILENCED, said
    assert "совсем-другое-имя.yml" in said


def test_a_tree_without_the_action_is_the_third_outcome(tmp_path: Path) -> None:
    """Носителей нет вовсе — отказ, а не «чисто».

    Предикат, не находящий предмета, доказывает только себя
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    root = tree(tmp_path, {INNOCENT: "шаг: тесты\n"}, {INNOCENT: "шаг: тесты\n# правка\n"})
    with pytest.raises(module.NotRun, match="предмета у проверки нет"):
        module.look(root, "база")


def test_the_carriers_are_read_from_the_shared_branch(tmp_path: Path) -> None:
    """Состав носителей спрашивается у ОБЩЕЙ ветки, а не у рабочего дерева.

    Прогон, заведённый САМИМ изменением, на общей ветке ещё не объявлен, и
    площадке сравнивать его не с чем — предупреждать о нём значило бы обещать
    отказ, которого не будет. Держит это `carriers(root, base)`: он спрашивает
    базу, и подмена её рабочим деревом здесь краснеет.
    """
    новый = ".github/workflows/заведён-этим-изменением.yml"
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER, INNOCENT: "шаг: тесты\n"},
        {новый: CARRIER},
    )
    assert module.carriers(root, "база") == {".github/workflows/review.yml"}
    code, said = module.look(root, "база")
    assert code == module.EXIT_OK, said


def test_the_refusal_of_git_is_not_an_empty_answer(tmp_path: Path) -> None:
    """Отказ git — третий исход, а не пустой список файлов (045)."""
    root = tmp_path / "не-дерево"
    root.mkdir()
    with pytest.raises(module.NotRun, match="git"):
        module.look(root, "база")


def test_the_run_returns_the_declared_outcome(tmp_path: Path) -> None:
    """Заход отдаёт объявленный исход отказа, а не просто печатает (039, 140)."""
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER},
        {".github/workflows/review.yml": CARRIER + "# правка\n"},
    )
    assert module.main(["--root", str(root), "--base", "база"]) == module.EXIT_SILENCED
    assert module.main(["--root", str(tmp_path / "нет"), "--base", "база"]) == module.EXIT_BROKEN
