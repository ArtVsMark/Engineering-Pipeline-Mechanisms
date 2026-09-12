"""Гейт «новое приезжает со своим прогоном» проверяется тем, что обязан найти.

Дважды за смену 12.09.2026 дефект жил ровно в таком имени: путь отказа у
состояния приёмки и разбор миганий на изменении. Оба нашёл внешний взгляд, а не
набор — то есть класс существует и измерен
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("check_new_is_tested.py")


def test_an_internal_name_is_not_demanded_a_run() -> None:
    """Внутреннее имя (`_имя`) прогона не требует: его зовут соседние строки."""
    assert module.names_in("def _helper():\n    pass\n") == set()
    assert module.names_in("def helper():\n    pass\n") == {"helper"}
    assert module.names_in("class Thing:\n    pass\n") == {"Thing"}


def test_a_substring_is_not_a_mention() -> None:
    """Имя ищется словом, а не подстрокой.

    Иначе `red` нашлось бы внутри `red_of` и засчитало бы ненаписанный прогон.
    """
    assert module.told_by_tests("red", "scripts/x.py", "module.red_of(runs)") is False
    assert module.told_by_tests("red", "scripts/x.py", "module.red(runs)") is True


def test_an_entry_point_is_told_by_the_file_that_runs_it() -> None:
    """`main` засчитывается упоминанием ФАЙЛА: так проверяются гейты.

    Тест гейта запускает его отдельным процессом и внутренних имён не видит.
    Требовать от него другого значило бы требовать переписать способ проверки
    гейтов ради формы этой проверки.
    """
    said = 'run_script("check_version.py", cwd=repo)'
    assert module.told_by_tests("main", "scripts/check_version.py", said) is True
    # Прочим именам файла недостаточно: их тест обязан назвать.
    assert module.told_by_tests("declared", "scripts/check_version.py", said) is False


def test_an_empty_test_folder_is_a_refusal(tmp_path: Path) -> None:
    """Набора нет — это ошибка входа, а не «всё названо» (075)."""
    with pytest.raises(module.NotRun):
        module.tests_text(tmp_path)


def test_the_gate_judges_only_what_the_change_added() -> None:
    """Судится добавленное, а не всё дерево.

    В дереве 75 имён из 327 не названы ни одним прогоном; краснеть на них
    значило бы судить чужую работу и учить себя обходить (051). Долг называет
    шаг `debt`, а не красное на каждом изменении.
    """
    source = module.__doc__ or ""
    assert "ТОЛЬКО ДОБАВЛЕННОЕ" in source
    assert "added_names" in __import__("inspect").getsource(module.main)


def test_the_base_is_the_shared_branch_of_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """База берётся у площадки, а не назначается «main» навсегда.

    Изменение может идти в другую ветку, и судить его относительно `main`
    значило бы считать добавленным всё, что есть у его настоящей базы.
    """
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    assert module.base_ref() == "origin/main"
    monkeypatch.setenv("GITHUB_BASE_REF", "release/0.2")
    assert module.base_ref() == "origin/release/0.2"
