"""Классы проверок проверяются тем, что механизм обязан отвергнуть.

Правило 140: гейт проверяется отказом, а не тем, что он пропускает зелёное.
Здесь предмет двойной — разбор ответа проекта (`.pipeline.yml`) и сверка
ответа с деревом, — и оба проверяются подделанными расхождениями.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import Run, RunScript, load_script

policy = load_script("pipeline_checks.py")

#: Шапка ответа проекта: схема и диапазон совместимости — их требует разбор.
HEAD = 'schema: 4\ncontract: ">=0.1,<0.2"\n'

GOOD = """
schema: 4
contract: ">=0.1,<0.2"
checks:
  lint: required
  review:
    class: advisory
    why: внешний взгляд слияния не держит
    addressee: "#23"
"""

WORKFLOW = """
name: ci
on:
  pull_request:
    types: [opened]
jobs:
  lint:
    name: lint
    steps: []
  ci-complete:
    name: ci-complete
    steps: []
"""

REVIEW = """
name: review
on: [pull_request]
jobs:
  review:
    name: review
    steps: []
"""

#: Прогон ЗА ПРЕДЕЛАМИ ИЗМЕНЕНИЯ: события — толчок в общую ветку и кнопка.
#: Записи на голове изменения он не оставляет, и спрашивается вторым разделом.
NIGHTLY = """
name: nightly
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  nightly:
    name: nightly
    steps: []
"""

#: Ответ по нему — тот же по форме, что и по проверке изменения.
BEYOND_OK = """
beyond_the_change:
  nightly:
    class: advisory
    why: идёт по толчку в общую ветку, слияния не касается
    addressee: "#23"
"""


def tree(root: Path, answer: str, *workflows: str) -> Path:
    """Собирает дерево из ответа и прогонов; отдаёт путь ответа."""
    answer_path = root / ".pipeline.yml"
    answer_path.write_text(answer, encoding="utf-8")
    directory = root / "workflows"
    directory.mkdir(exist_ok=True)
    for index, body in enumerate(workflows, start=1):
        (directory / f"w{index}.yml").write_text(body, encoding="utf-8")
    return answer_path


def gate(run_script: RunScript, root: Path) -> Run:
    """Запускает сверку на подделанном дереве."""
    return run_script(
        "check_pipeline.py",
        "--policy",
        str(root / ".pipeline.yml"),
        "--workflows",
        str(root / "workflows"),
    )


def test_off_written_as_a_word_is_read_as_a_class(tmp_path: Path) -> None:
    """`off` в YAML 1.1 — булево, и ответ, написанный по-человечески, принимается."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + "checks:\n  e2e:\n    class: off\n    why: нет окружения\n",
        "utf-8",
    )
    assert policy.load(path)["e2e"].klass == policy.OFF


def test_unknown_class_is_refused(tmp_path: Path) -> None:
    """Класс разбирается списком разрешённого: неизвестное — отказ, а не «наверное»."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(HEAD + "checks:\n  lint: maybe\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="неизвестен"):
        policy.load(path)


@pytest.mark.parametrize("klass", ["advisory", "off"])
def test_silent_class_without_a_reason_is_refused(tmp_path: Path, klass: str) -> None:
    """«Не подключено» и «отключено сознательно» снаружи неотличимы (154)."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + f"checks:\n  lint:\n    class: {klass}\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="без причины"):
        policy.load(path)


def test_unreviewed_needs_no_reason(tmp_path: Path) -> None:
    """Неразобранная причины не требует: это очередь, а не решение."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(HEAD + "checks:\n  lint: unreviewed\n", encoding="utf-8")
    check = policy.load(path)["lint"]
    assert not check.answered and not check.holds_merge


def test_matrix_cell_as_an_answer_is_refused(tmp_path: Path) -> None:
    """Ответ даётся по имени джоба: имя ячейки меняет договор при новой версии."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(HEAD + 'checks:\n  "test (3.12)": required\n', encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="матричной ячейки"):
        policy.load(path)


def test_foreign_schema_is_refused(tmp_path: Path) -> None:
    """Чужая схема — отказ: механизм не догадывается, что значат её поля."""
    path = tmp_path / ".pipeline.yml"
    path.write_text("schema: 99\nchecks:\n  lint: required\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="схема"):
        policy.load(path)


@pytest.mark.parametrize(
    "body",
    [HEAD + "checks: {}\n", 'schema: 4\ncontract: ">=0.1,<0.2"\n'],
)
def test_empty_answer_is_an_input_error(tmp_path: Path, body: str) -> None:
    """Пустой ответ — ошибка входа, а не «нечего опрашивать» (075)."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(policy.BadPolicy):
        policy.load(path)


def test_missing_answer_is_an_input_error(tmp_path: Path) -> None:
    """Отсутствие файла не зеленит: предмета проверки нет (075)."""
    with pytest.raises(policy.BadPolicy):
        policy.load(tmp_path / "нет.yml")


def test_only_checks_of_the_change_are_collected(tmp_path: Path) -> None:
    """Договор — про проверки НА ИЗМЕНЕНИИ: расписание записи на голове не даёт."""
    directory = tmp_path / "workflows"
    directory.mkdir()
    (directory / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    (directory / "nightly.yml").write_text(
        "name: n\non:\n  schedule:\n    - cron: '0 6 * * *'\njobs:\n  n:\n    steps: []\n",
        encoding="utf-8",
    )
    assert set(policy.declared_jobs(directory, skip="ci-complete")) == {"lint"}


def test_one_name_from_two_workflows_is_refused(tmp_path: Path) -> None:
    """Одно имя из двух прогонов — неоднозначный вердикт, а не удвоенная строгость."""
    directory = tmp_path / "workflows"
    directory.mkdir()
    (directory / "a.yml").write_text(REVIEW, encoding="utf-8")
    (directory / "b.yml").write_text(REVIEW, encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="выдают двое"):
        policy.declared_jobs(directory)


def test_tree_without_change_checks_is_refused(tmp_path: Path) -> None:
    """Дерево без единой проверки на изменении — ошибка входа, а не «чисто»."""
    directory = tmp_path / "workflows"
    directory.mkdir()
    (directory / "n.yml").write_text(
        "name: n\non: [push]\njobs:\n  n:\n    steps: []\n", encoding="utf-8"
    )
    with pytest.raises(policy.BadPolicy):
        policy.declared_jobs(directory)


def test_gate_passes_a_matching_tree(run_script: RunScript, tmp_path: Path) -> None:
    """На сошедшемся дереве сверка зелёная и называет состав вслух."""
    tree(tmp_path, GOOD, WORKFLOW, REVIEW)
    run = gate(run_script, tmp_path)
    assert run.code == 0, run.text
    assert "держат слияние:    lint" in run.text


def test_gate_refuses_a_check_without_an_answer(run_script: RunScript, tmp_path: Path) -> None:
    """Новая проверка не становится обязательной молча — и незамеченной тоже."""
    tree(tmp_path, HEAD + "checks:\n  lint: required\n", WORKFLOW, REVIEW)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "review" in run.text


def test_gate_refuses_an_answer_without_a_check(run_script: RunScript, tmp_path: Path) -> None:
    """Ответ по несуществующей проверке оставил бы сводный в вечном ожидании."""
    tree(tmp_path, GOOD + "  e2e: required\n", WORKFLOW, REVIEW)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "e2e" in run.text


def test_gate_refuses_a_required_matrix(run_script: RunScript, tmp_path: Path) -> None:
    """Матричные имена в список обязательных не попадают никогда."""
    matrix = WORKFLOW.replace(
        "  lint:\n    name: lint\n    steps: []\n",
        "  lint:\n    name: lint\n    strategy:\n      matrix:\n        v: [1, 2]\n    steps: []\n",
    )
    tree(tmp_path, GOOD, matrix, REVIEW)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "матрица" in run.text


def test_gate_refuses_an_answer_holding_nothing(run_script: RunScript, tmp_path: Path) -> None:
    """Без единой обязательной сводный гейт зелен всегда — это не «чисто» (075)."""
    answer = (
        HEAD + "checks:\n  lint:\n    class: advisory\n    why: пока смотрим\n    addressee: none\n"
    )
    tree(tmp_path, answer, WORKFLOW)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "обязательной" in run.text


def test_gate_refuses_the_summary_answering_for_itself(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Сводный сам себя не опрашивает, и класса у него нет: он задан построением."""
    tree(tmp_path, GOOD + "  ci-complete: required\n", WORKFLOW, REVIEW)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "сам за себя" in run.text


def test_gate_says_when_it_did_not_run(run_script: RunScript, tmp_path: Path) -> None:
    """Сломанный вход отдаёт третий исход, а не «совпадает»."""
    run = run_script("check_pipeline.py", "--policy", str(tmp_path / "нет.yml"))
    assert run.code == 2, run.text


# --- адресат совещательной ----------------------------------------------------
#
# Красное, которому негде пережить слияние, делает «совещательную» вежливым
# «выключена» (142). Требование к адресу то же, что каталог предъявил полю
# `where` в ответе потребителя: проза рядом законна, вместо адреса — нет.


def test_an_advisory_without_an_addressee_is_refused(tmp_path: Path) -> None:
    """Совещательная без адресата отвергается: иначе класс ничего не значит."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + "checks:\n  review:\n    class: advisory\n    why: смотрим\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="без адресата"):
        policy.load(path)


def test_prose_instead_of_an_address_is_refused(tmp_path: Path) -> None:
    """Адресат — разрешимый адрес, а не рассказ о том, где искать.

    Проза вместо адреса даёт ровно то, чего от неё ждут: канал выглядит
    совещательным осознанно, а записи нет нигде. Замер семьи — у каталога это
    стоило разбора 44 ответов регулярным выражением по прозе.
    """
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + "checks:\n  review:\n    class: advisory\n"
        "    why: смотрим\n    addressee: находки живут в живой задаче\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="не разрешается"):
        policy.load(path)


def test_a_missing_path_is_not_an_address(tmp_path: Path) -> None:
    """Путь, которого в дереве нет, адресом не считается.

    Проверяется существование, а не похожесть на путь: `scripts/было.py`
    выглядит адресом и разрешается ни во что.
    """
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + "checks:\n  review:\n    class: advisory\n"
        "    why: смотрим\n    addressee: scripts/nowhere.py\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="не разрешается"):
        policy.load(path)


@pytest.mark.parametrize(
    "address", ["#23", "ArtVsMark/Engineering-Incidents-Playbook#15", "scripts/here.py", "*.py"]
)
def test_a_resolvable_address_is_accepted(tmp_path: Path, address: str) -> None:
    """Задача, чужая задача, существующий путь и образец — адреса."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "here.py").write_text("", encoding="utf-8")
    (tmp_path / "some.py").write_text("", encoding="utf-8")
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + f"checks:\n  review:\n    class: advisory\n"
        f'    why: смотрим\n    addressee: "{address}"\n',
        encoding="utf-8",
    )
    assert policy.load(path)["review"].records is True


def test_no_addressee_is_said_with_a_word(tmp_path: Path) -> None:
    """«Записи нет» говорится словом, а не пропуском поля.

    Пропуск неотличим от «забыли ответить»; слово видно и в данных, и в
    отчёте — тот же приём, что `mechanism: none` в ответе каталогу (154).
    """
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + "checks:\n  debt:\n    class: advisory\n"
        "    why: печатает уже записанное другими\n    addressee: none\n",
        encoding="utf-8",
    )
    answer = policy.load(path)["debt"]
    assert answer.addressee == policy.NO_ADDRESSEE
    assert answer.records is False


def test_the_project_answer_declares_an_addressee_for_every_advisory() -> None:
    """Ответ САМОГО проекта проходит это требование, а не только подделки.

    Гейт, проверенный только на подделках, зелен на дереве, которого нет:
    предметом обязан быть живой ответ проекта (075).
    """
    checks = policy.load()
    advisory = [item for item in checks.values() if item.klass == policy.ADVISORY]
    assert advisory, "совещательных проверок в ответе проекта нет — предмет не найден"
    assert all(item.addressee for item in advisory), "совещательная без адресата"


# --- прогоны за пределами изменения ------------------------------------------


def test_a_run_beyond_the_change_needs_an_answer(run_script: RunScript, tmp_path: Path) -> None:
    """Прогон вне изменения без ответа — находка, а не «его не спрашивают».

    До второго раздела таких джобов у нас было десять, и класса у них не было
    нигде: `main_red` считал совещательным всё, чего нет среди обязательных, —
    то есть выводил ответ из молчания (154).
    """
    tree(tmp_path, GOOD, WORKFLOW, REVIEW, NIGHTLY)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "nightly" in run.text


def test_an_answered_run_beyond_the_change_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Названный класс снимает находку — и печатается отдельным разделом."""
    tree(tmp_path, GOOD + BEYOND_OK, WORKFLOW, REVIEW, NIGHTLY)
    run = gate(run_script, tmp_path)
    assert run.code == 0, run.text
    assert "вне изменения" in run.text


def test_required_is_refused_beyond_the_change(run_script: RunScript, tmp_path: Path) -> None:
    """`required` во втором разделе запрещён построением, а не вкусом.

    Держать слияние такому прогону нечем: сводный гейт опрашивает голову
    изменения, а записи он там не оставляет. Защита ветки сверяет ИМЯ записи, а
    не исход (187), — объявленное обязательным имя, которое никто не выдаёт,
    ждали бы вечно.
    """
    bad = BEYOND_OK.replace(
        "    class: advisory\n    why: идёт по толчку в общую ветку, слияния не касается\n"
        '    addressee: "#23"\n',
        "    class: required\n",
    )
    tree(tmp_path, GOOD + bad, WORKFLOW, REVIEW, NIGHTLY)
    run = gate(run_script, tmp_path)
    assert run.code == 2, run.text
    assert "required" in run.text


def test_an_answer_in_the_wrong_section_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Ответ, попавший не в свой раздел, читается как здоровый — и не должен.

    Имя в дереве есть, класс допустим, а предмет разный: ответ по прогону вне
    изменения, положенный в первый раздел, объявляет обязательным то, что
    записи на голове не даёт, — сводный ждал бы её вечно.
    """
    answer = (
        GOOD
        + """  nightly:
    class: advisory
    why: не в своём разделе
    addressee: "#23"
"""
    )
    tree(tmp_path, answer, WORKFLOW, REVIEW, NIGHTLY)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "не в своём разделе" in run.text


def test_one_name_in_both_sections_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Одно имя в обоих разделах — два ответа по одной проверке (022)."""
    answer = (
        GOOD
        + BEYOND_OK
        + """  lint:
    class: advisory
    why: второй ответ по тому же имени
    addressee: "#23"
"""
    )
    tree(tmp_path, answer, WORKFLOW, REVIEW, NIGHTLY)
    run = gate(run_script, tmp_path)
    assert run.code == 2, run.text
    assert "в обоих разделах" in run.text


def test_no_runs_beyond_the_change_is_lawful(run_script: RunScript, tmp_path: Path) -> None:
    """Ни одного прогона вне изменения — законное состояние, а не ошибка входа.

    Здесь второй раздел отличается от первого: без проверок НА изменении
    конвейера нет вовсе (075), а расписаний и публикаций у проекта может не
    быть ни одной — требовать их значило бы требовать того, чем проект не
    обязан пользоваться.
    """
    tree(tmp_path, GOOD, WORKFLOW, REVIEW)
    run = gate(run_script, tmp_path)
    assert run.code == 0, run.text


def test_advisory_names_do_not_cross_the_sections(tmp_path: Path) -> None:
    """Имя из второго раздела не попадает в список совещательных первого.

    Сводный гейт опрашивает голову ИЗМЕНЕНИЯ по этому списку. Прогон вне
    изменения записи там не оставляет — а `agent-pr` всё же оставляет, он идёт
    по толчку той же ветки, — и его красное приезжало в вердикт по изменению
    как совещательная проверка. Нашёл внешний взгляд на #150.
    """
    path = tree(tmp_path, GOOD + BEYOND_OK, WORKFLOW, REVIEW, NIGHTLY)
    checks = policy.load(path)
    assert "nightly" not in policy.names_of(checks, policy.ADVISORY)
    assert "nightly" in policy.names_of(checks, policy.ADVISORY, beyond=True)
    assert "nightly" in policy.names_of(checks, policy.ADVISORY, beyond=None)
    assert "review" in policy.names_of(checks, policy.ADVISORY)


def test_one_name_on_both_sides_of_the_tree_is_refused(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Одно имя у прогона на изменении и вне его — неоднозначность.

    Внутри каждого раздела совпадение отвергает разбор, а между разделами не
    проверял никто: ответ на такое имя один, а предметов два. Нашёл внешний
    взгляд на #150.
    """
    twin = NIGHTLY.replace("  nightly:\n    name: nightly", "  twin:\n    name: lint")
    tree(tmp_path, GOOD, WORKFLOW, REVIEW, twin)
    run = gate(run_script, tmp_path)
    assert run.code == 3, run.text
    assert "и прогон на изменении" in run.text


# --- прочтение формы прогона: одно на всех ------------------------------------


def test_run_of_refuses_a_missing_file(tmp_path: Path) -> None:
    """Нет файла — ошибка входа, а не пустой прогон (075).

    У соседней `load()` такие исходы проверены давно, а у этой не было ни
    одного прямого теста. Нашёл внешний взгляд на #121.
    """
    with pytest.raises(policy.BadPolicy, match="нет прогона"):
        policy.run_of(tmp_path / "нет-такого.yml")


def test_run_of_refuses_broken_yaml(tmp_path: Path) -> None:
    """Битый YAML называется битым, а не читается как пустота."""
    path = tmp_path / "w.yml"
    path.write_text("jobs:\n  x:\n   - [не закрыт\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="не разбирается"):
        policy.run_of(path)


def test_run_of_refuses_a_non_mapping(tmp_path: Path) -> None:
    """Список вместо отображения — читать нечего, и это сказано."""
    path = tmp_path / "w.yml"
    path.write_text("- один\n- два\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="не словарь"):
        policy.run_of(path)


def test_the_events_key_is_read_in_one_place(tmp_path: Path) -> None:
    """Ловушка `on:` → `True` разбирается одной функцией на всех читателей.

    Второе понимание той же формы расходится с первым молча (090). Нашёл
    внешний взгляд на #108: то же место было переписано в `contract.py`.
    """
    contract = load_script("contract.py")
    assert contract.policy.events_raw is policy.events_raw
    path = tmp_path / "w.yml"
    path.write_text("on:\n  push:\n    branches: [main]\njobs:\n  x:\n    steps: []\n", "utf-8")
    assert "push" in policy.events_raw(policy.run_of(path))


def test_needs_naming_a_stranger_is_refused(tmp_path: Path) -> None:
    """`needs` мимо джобов прогона — отказ, а не тихая потеря связи.

    Подстановка строки вместо связи оставила бы дежурного по общей ветке без
    предмета: он решает по ней, одно ли это падение. Нашёл внешний взгляд
    на #160.
    """
    directory = tmp_path / "workflows"
    directory.mkdir()
    (directory / "w.yml").write_text(
        "on: [pull_request]\njobs:\n  свой:\n    name: свой\n    steps: []\n"
        "  агрегат:\n    name: агрегат\n    needs: чужой\n    steps: []\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="названа мимо"):
        policy.feeds(directory)
