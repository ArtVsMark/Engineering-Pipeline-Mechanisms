"""Счёт частей изменения проверяется тем, что он обязан отвергнуть.

Механизм не краснеет — он называет число (051). Ошибиться он может тихо: на
пустом входе отдать «одна часть» вместо отказа, и тогда «граница соблюдена»
прозвучало бы там, где предмета не было вовсе
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script

module = load_script("change_parts.py")


def test_files_touched_by_one_commit_are_one_part() -> None:
    """Файлы одного коммита связаны — это и есть признак границы (133)."""
    assert module.parts([["а.py", "б.py", "в.py"]]) == [["а.py", "б.py", "в.py"]]


def test_commits_with_no_common_file_fall_apart() -> None:
    """Коммиты без общего файла дают РАЗНЫЕ части: работа сшита не пересечением."""
    said = module.parts([["а.py"], ["б.py"], ["в.py"]])
    assert len(said) == 3, said


def test_a_shared_file_sews_two_commits_together() -> None:
    """Один общий файл связывает коммиты: предмет у них общий."""
    said = module.parts([["а.py", "общий.py"], ["общий.py", "б.py"]])
    assert said == [["а.py", "б.py", "общий.py"]], said


def test_a_chain_through_a_third_commit_still_connects() -> None:
    """Связность ПЕРЕХОДНАЯ: а—б и б—в делают одну часть, а не две.

    Разбор, сравнивающий только пары соседних коммитов, насчитал бы здесь две
    части и звал бы резать то, что связано через третий файл.
    """
    said = module.parts([["а.py", "б.py"], ["б.py", "в.py"]])
    assert said == [["а.py", "б.py", "в.py"]], said


def test_parts_come_biggest_first() -> None:
    """Части идут от крупной к мелкой: читателю нужна главная, а не первая попавшаяся."""
    said = module.parts([["а.py"], ["б.py", "в.py", "г.py"]])
    assert [len(one) for one in said] == [3, 1], said


def test_an_empty_change_is_the_third_outcome() -> None:
    """Коммитов нет — отказ, а не «одна часть».

    «Одна часть» на пустом входе прозвучало бы как «граница соблюдена» — то
    есть отказ входа выдал бы себя за вердикт (045).
    """
    with pytest.raises(module.NotRun, match="считать нечего"):
        module.parts([])


def test_commits_that_touched_nothing_are_a_state_not_a_refusal() -> None:
    """Коммиты есть, а файлов не тронуто — СОСТОЯНИЕ, и у него своё имя.

    Так выглядит коммит с `--allow-empty`, которым отмечают пункт задачи
    трейлером. Прежде он давал отказ, и проверка живого дерева краснела по
    причине, к работе отношения не имеющей: механизм краснел на законном
    (051). Нашёл внешний взгляд на #562.
    """
    assert module.parts([[], []]) == []


def test_an_empty_result_is_told_apart_from_an_empty_input() -> None:
    """Вторая половина: пустой ВХОД по-прежнему отказ.

    Без неё починка съела бы и настоящий отказ: «коммитов ветки не видно» и
    «коммиты были, файлов не тронули» — разные ответы, и выход из них разный
    (045).
    """
    with pytest.raises(module.NotRun):
        module.parts([])
    assert module.parts([[], []]) == []


def test_the_walk_agrees_with_the_live_branch(run_script) -> None:  # type: ignore[no-untyped-def]
    """Заход процессом сходится с тем, что в ветке на самом деле (139).

    ЦВЕТ НЕ ЗАКРЕПЛЁН, И ЭТО УСИЛЕНИЕ. Последний коммит ветки бывает пустым —
    так отмечают пункт задачи, — и требовать нуля именно тогда значило бы
    держать красное на законном приёме. Проверяется большее: исход СХОДИТСЯ с
    тем, тронул ли последний коммит файлы, и названы обе ветки.
    """
    done = run_script("change_parts.py", "--base", "HEAD~1")
    if done.code == module.EXIT_NOTHING:
        assert "не тронуло файлов" in done.out, done.out
        return
    assert done.code == module.EXIT_OK, done.err
    assert "частей" in done.out, done.out


def test_a_base_that_is_not_a_commit_is_the_third_outcome(run_script) -> None:  # type: ignore[no-untyped-def]
    """База не разрешается — отказ с причиной, а не «одна часть» (075).

    Опечатка в имени базы снаружи неотличима от цельного изменения: обе дают
    ноль частей. Поэтому отказ git доезжает до кода возврата, а не гасится.
    """
    done = run_script("change_parts.py", "--base", "нет-такой-базы")
    assert done.code == module.EXIT_BROKEN, done.out
    assert "не сосчитаны" in done.err, done.err


def test_paths_are_read_by_nul_not_by_newline() -> None:
    """Пути из git читаются по NUL: имя с пробелом иначе выпадает молча (165).

    В дереве имена по-русски, и первая редакция звала `git show --name-only` без
    `-z`: git экранировал бы такие имена, путь не разрешался, файл выпадал из
    счёта — а счёт частей на неполном списке даёт правдоподобное число. Поймал
    гейт чистоты источников, а не вычитка.
    """
    source = (ROOT / "scripts" / "change_parts.py").read_text(encoding="utf-8")
    assert '"-z"' in source, "перечисление путей идёт без -z"
    assert 'split("\\0")' in source, "вывод разбирается не по NUL"


def test_a_merge_commit_does_not_hide_its_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Файлы merge-коммита в счёт попадают, а не прячутся комбинированным диффом.

    `git show` у слияния печатает КОМБИНИРОВАННЫЙ дифф — только то, что отлично
    от ОБОИХ родителей, — и файлы, совпавшие с одним из них, выпадают молча.
    Замер 18.09.2026 по трём слияниям дерева: комбинированный дал НОЛЬ файлов
    там, где против первого родителя их четыре и два. Счёт частей на таком
    списке отвечает правдоподобным числом (045). Нашёл внешний взгляд.
    """
    import subprocess

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    subprocess.run(["git", "init", "--quiet", "-b", "main", str(tmp_path)], check=True)
    run("config", "user.email", "кто@то")
    run("config", "user.name", "кто-то")
    (tmp_path / "общий").write_text("раз", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "первый")
    run("checkout", "--quiet", "-b", "сосед")
    (tmp_path / "соседский").write_text("два", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "у соседа")
    run("checkout", "--quiet", "main")
    (tmp_path / "свой").write_text("три", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "у себя")
    run("merge", "--no-ff", "--quiet", "-m", "слияние", "сосед")
    # ПРЕДМЕТ ИЗОЛИРОВАН ДО ОДНОГО КОММИТА. Первая редакция брала диапазон, но
    # `A..B` несёт и коммит соседа — он достижим через ВТОРОГО родителя, — и
    # файл был виден оттуда: проверка говорила о слиянии, не проверяя слияния
    # ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    here = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        видно = set(module.files_of("HEAD"))
    finally:
        os.chdir(here)
    assert "соседский" in видно, (
        "файл слияния выпал из счёта: комбинированный дифф прячет то, что совпало"
        f" с родителем — видно только {sorted(видно)}"
    )


def test_work_that_arrived_by_a_merge_is_not_counted_as_ours(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Граница считается по СВОИМ коммитам, а не по всему, что видно из головы.

    `base..HEAD` берёт и то, что пришло в ветку СЛИЯНИЕМ общей: коммиты второго
    родителя, если база отстала, и сам merge-коммит, чей дифф против первого
    родителя есть ровно чужая работа. Тогда граница изменения считается по
    чужим файлам, и «одна часть» звучит там, где тем изменения две
    ([133](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/133-file-overlap-sets-the-boundary.md)).

    ЗАМЕР 19.09.2026, на живом изменении: после слияния общей ветки счёт назвал
    шесть файлов, из которых два автор не трогал вовсе. Нашёл внешний взгляд
    (`5954abc`), и в тот же день это подтвердилось своей работой.

    БАЗА ЗДЕСЬ СВЕЖАЯ — ровно та, на которую механизм и рассчитан. Чужие
    коммиты она отсекает сама; остаётся ОДИН путь, которым чужое всё равно
    доезжает, — сам merge-коммит, чей дифф против первого родителя есть вся
    принесённая работа. Его и проверяем: без `--no-merges` файл соседа попадёт
    в границу через слияние, хотя автор его не писал.
    """
    import os
    import subprocess

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    subprocess.run(["git", "init", "--quiet", "-b", "main", str(tmp_path)], check=True)
    run("config", "user.email", "кто@то")
    run("config", "user.name", "кто-то")
    (tmp_path / "начало").write_text("раз", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "начало")

    run("checkout", "--quiet", "-b", "своя")
    (tmp_path / "своё").write_text("два", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "своя работа")

    run("checkout", "--quiet", "main")
    (tmp_path / "чужое").write_text("три", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "чужая работа")

    # База берётся ПОСЛЕ чужого коммита: так выглядит свежая общая ветка,
    # которую окно подтянуло перед счётом.
    база = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()

    run("checkout", "--quiet", "своя")
    run("merge", "--no-ff", "--quiet", "-m", "слияние общей в свою", "main")

    here = Path.cwd()
    try:
        os.chdir(tmp_path)
        видно = {name for commit in module.touched(база) for name in commit}
    finally:
        os.chdir(here)

    assert видно == {"своё"}, (
        f"в границу изменения попало чужое: {sorted(видно)} — слияние общей ветки"
        " привело коммиты, которых автор не писал"
    )


def test_a_commit_without_a_parent_is_read_not_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Коммит без родителя читается: `sha^` у него не разрешается вовсе.

    Такой коммит бывает не только корнем дерева — в МЕЛКОМ клоне граничный
    выглядит так же, а мелким клонирует облачное окно и чужой прогон. Отказ
    входа там, где предмет есть и читается, — это отказ не по существу
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    Нашёл внешний взгляд (`95ec4bc`).
    """
    import os
    import subprocess

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    subprocess.run(["git", "init", "--quiet", "-b", "main", str(tmp_path)], check=True)
    run("config", "user.email", "кто@то")
    run("config", "user.name", "кто-то")
    (tmp_path / "первый").write_text("раз", encoding="utf-8")
    (tmp_path / "второй").write_text("два", encoding="utf-8")
    run("add", "-A")
    run("commit", "--quiet", "-m", "корень")

    here = Path.cwd()
    try:
        os.chdir(tmp_path)
        видно = set(module.files_of("HEAD"))
    finally:
        os.chdir(here)

    assert видно == {"первый", "второй"}, (
        f"корневой коммит прочитан неверно: {sorted(видно)} — у него нет родителя,"
        " и дифф против него не разрешается"
    )


def test_an_empty_commit_reaches_its_own_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Исход «файлов не тронуто» ПРОГОНЯЕТСЯ, а не только объявлен (039, 145).

    Он и был тем красным: обязательная проверка `test` падала на изменении,
    чей последний коммит пуст, — а пустым его делает отметка пункта задачи
    трейлером.
    """
    monkeypatch.setattr(module, "touched", lambda _base: [[], []])
    assert module.main(["--base", "HEAD~1"]) == module.EXIT_NOTHING
    assert "не тронуло файлов" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("commits", "warned"),
    [([["a.py"], ["b.py"]], True), ([["a.py", "b.py"], ["b.py"]], False)],
    ids=["две несвязанные части", "одна часть"],
)
def test_warn_marks_a_split_change_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    commits: list[list[str]],
    warned: bool,
) -> None:
    """С `--warn` распавшееся изменение даёт `::warning::`, цельное — нет (#860)."""
    monkeypatch.setattr(module, "touched", lambda base: commits)
    assert module.main(["--warn"]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert ("::warning" in said) is warned, said


def test_the_warning_names_the_decision_that_makes_mixing_legal() -> None:
    """Предупреждение отличает законное смешение от ошибки ссылкой на решение 008."""
    said = module.warning(2)
    assert "008" in said and module.DECISION_008 in said and "не держит" in said
    assert (ROOT / module.DECISION_008).is_file(), "решение 008 названо мёртвым адресом"


def test_the_parts_job_runs_on_every_change() -> None:
    """Джоб `parts` идёт на изменении и зовёт счёт с `--warn` (#860)."""
    import yaml

    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"][
        "parts"
    ]
    runs = " ".join(str(step.get("run") or "") for step in job["steps"])
    assert "change_parts.py" in runs and "--warn" in runs
