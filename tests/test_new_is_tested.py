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


def test_a_mention_is_not_a_run() -> None:
    """Предмет — ВЫЗОВ имени, а не упоминание его где угодно.

    Первая редакция искала имя отдельным словом по всему набору, и короткие
    обычные имена засчитывались сами собой: `at` и `touched` встречаются в
    чужой прозе и чужих данных, и обе функции гейт объявил проверенными, не
    имея по ним ни одного прогона. Нашёл внешний взгляд на #225.
    """
    assert module.told_by_tests("red", "scripts/x.py", "module.red_of(runs)") is False
    assert module.told_by_tests("red", "scripts/x.py", "module.red(runs)") is True
    # Имя в прозе прогоном не становится — иначе достаточно было бы о нём
    # написать (139).
    assert module.told_by_tests("touched", "scripts/x.py", '"""Тронутые пути."""') is False
    assert module.told_by_tests("at", "scripts/x.py", 'facts["generated"]["at"]') is False
    assert module.told_by_tests("at", "scripts/x.py", "module.at(base, path)") is True


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


def _git(where: Path, *args: str) -> None:
    """Команда git в подготовленном дереве; отказ виден сразу."""
    __import__("subprocess").run(
        ["git", *args], cwd=where, check=True, capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Дерево с одним механизмом на общей ветке и веткой изменения."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "them@example.com")
    _git(tmp_path, "config", "user.name", "Кто-то")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "thing.py").write_text("def was():\n    pass\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prose.md").write_text("проза\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "механизм и проза")
    _git(tmp_path, "checkout", "-q", "-b", "change")
    return tmp_path


def test_only_mechanisms_are_judged(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Предмет — модули механизмов; проза и набор судятся не здесь.

    Изменение, тронувшее только документы, не обязано нести прогонов: гейт
    краснел бы на правке запятой (051).
    """
    monkeypatch.chdir(repo)
    (repo / "docs" / "prose.md").write_text("проза правленая\n", encoding="utf-8")
    (repo / "scripts" / "thing.py").write_text(
        "def was():\n    pass\n\n\ndef added():\n    pass\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "правка")
    assert module.touched("main") == ["scripts/thing.py"]


def test_only_what_the_change_added_is_named(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Имена базы не считаются добавленными: их прогонов гейт не требует.

    В дереве 75 имён из 327 без прогонов, и судить их значило бы краснеть на
    чужой работе — то есть учить себя обходить гейт (051).
    """
    monkeypatch.chdir(repo)
    (repo / "scripts" / "thing.py").write_text(
        "def was():\n    pass\n\n\ndef added():\n    pass\n\n\ndef _hidden():\n    pass\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "правка")
    assert module.added_names("main", "scripts/thing.py") == {"added"}


def test_a_new_module_is_added_whole(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Модуля на базе нет — добавленным считается всё его содержимое.

    Отсутствие файла на базе — не отказ: это и есть «модуль новый целиком».
    """
    monkeypatch.chdir(repo)
    (repo / "scripts" / "fresh.py").write_text("def one():\n    pass\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "новый модуль")
    assert module.at("main", "scripts/fresh.py") == ""
    assert module.added_names("main", "scripts/fresh.py") == {"one"}


def test_a_missing_base_is_a_refusal(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Общей точки с базой нет — третий исход, а не «нового нет» (075)."""
    monkeypatch.chdir(repo)
    with pytest.raises(module.NotRun):
        module.touched("origin/нет-такой-ветки")


# --- имя, переданное как значение, тоже прогнано -----------------------------

HANDED = {
    "декоратором": "@порядок\ndef x() -> None: ...",
    "в списке": "[порядок]",
    "ключом сортировки": "sorted(rows, key=порядок)",
    "аргументом": "call(порядок, rows)",
    "последним аргументом": "call(rows, порядок)",
    "подменой в стенде": "monkeypatch.setattr(mod, 'x', порядок)",
}

NOT_HANDED = {
    "прозой": "Функция порядок делает то и это.",
    "частью слова": "порядковый(1)",
    "сравнением": "assert порядок == 1",
    "в докстроке": '"""Смотри порядок ниже."""',
    # ПРИСВАИВАНИЕ ИМЕНИ — НЕ ПЕРЕДАЧА ЕГО. Первая редакция признака искала знак
    # ПОСЛЕ имени (`имя=`) и засчитывала это прогоном: знак перед именем
    # говорит «имя отдают», знак после — «имени присваивают». Нашёл внешний
    # взгляд на #247.
    "присваиванием": "порядок = 5",
    "присваиванием через точку": "mod.порядок = 5",
    # СРАВНЕНИЕ — НЕ ПЕРЕДАЧА. Знак `=` перед именем бывает хвостом сравнения,
    # и вторая редакция признака их засчитывала: чинила `имя=` и заводила
    # `==имя`. Нашёл внешний взгляд на #249.
    "равенством": "assert x == порядок",
    "неравенством": "assert x != порядок",
    "«не меньше»": "assert x >= порядок",
    "«не больше»": "assert x <= порядок",
}


@pytest.mark.parametrize("said", sorted(HANDED.values()), ids=sorted(HANDED))
def test_a_name_handed_to_someone_else_counts_as_run(said: str) -> None:
    """Имя, ОТДАННОЕ вызывающему, прогнано — скобок рядом с ним нет.

    Обработчик, ключ сортировки, декоратор, подмена в стенде: вызывает их не
    тест, а тот, кому их отдали. Сужение до `имя(` объявляло такое
    непрогнанным — ложная находка, которая учит обходить гейт (051). Нашёл
    внешний взгляд на #227.
    """
    assert module.told_by_tests("порядок", "scripts/x.py", said) is True


@pytest.mark.parametrize("said", sorted(NOT_HANDED.values()), ids=sorted(NOT_HANDED))
def test_a_mention_is_still_not_a_run(said: str) -> None:
    """Упоминание прогоном не стало: расширение назвало соседей, а не сняло их.

    После имени обязан стоять знак, которым его зовут или отдают, — а не пробел
    и точка. Иначе вернулась бы первая редакция гейта, где `at` и `touched`
    засчитывались из чужой прозы
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    assert module.told_by_tests("порядок", "scripts/x.py", said) is False
