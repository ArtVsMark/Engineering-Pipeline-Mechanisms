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


def test_the_span_is_parsed_in_one_place() -> None:
    """Диапазон разбирает ОДНА функция, и её же зовёт проверка ответа.

    Первая редакция завела второе чтение файла — и оно уже расходилось с
    проверкой формы, оставаясь правдоподобным: докстрока обещала общий разбор,
    а разбора было два
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    Нашёл внешний взгляд на #253.
    """
    assert policy.span_of({"contract": ">=1.2,<1.3"}) == ">=1.2,<1.3"
    assert policy.span_of({"contract": "  >=1.2,<1.3  "}) == ">=1.2,<1.3"


def test_an_unnamed_span_is_a_refusal_not_a_blank() -> None:
    """Диапазона нет — отказ с причиной, а не пустая строка.

    «Подходит любая версия» — не состояние, а молчание
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    for raw in ({}, {"contract": ""}, {"contract": "   "}, {"contract": None}):
        with pytest.raises(policy.BadPolicy) as caught:
            policy.span_of(raw)
        assert "диапазон" in str(caught.value).lower()


# --- вызываемый прогон: третий род ------------------------------------------

#: Вызывающий: обычный прогон на изменении, чей джоб не делает шагов, а зовёт.
#: ИМЕНА У ДЖОБОВ РАЗНЫЕ НАМЕРЕННО. Прежде оба звались `debt`, и составное имя
#: выходило «debt / debt» — по нему ПОРЯДОК неразличим: перестановка доводов в
#: `check_names` оставила бы приёмку зелёной. Замер порядка был только один,
#: внешним прогоном на #549 (`outer`/`inner`), а набор его не держал — то есть
#: проверено было на выборке, где разницы не видно
#: ([107](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/107-it-works-for-the-author-means-tested-on-the-authors-sample.md)).
#: Нашёл внешний взгляд на #550; до реестра находка не доехала — её потерял
#: разбор обзора (#612).
CALLER = """name: caller
on: [pull_request]
jobs:
  снаружи:
    name: снаружи
    uses: ./.github/workflows/step-debt.yml
"""
#: Вызываемый: событие у него ОДНО, и сам он не идёт никогда.
CALLEE = """name: step-debt
on:
  workflow_call:
jobs:
  внутри:
    name: внутри
    runs-on: ubuntu-latest
    steps: []
"""


def called_tree(tmp_path: Path, caller: str = CALLER, callee: str = CALLEE) -> Path:
    """Дерево прогонов, где один зовёт другого — по настоящим путям.

    Путь `./.github/workflows/…` разрешается относительно КОРНЯ дерева, а не
    каталога прогонов, поэтому тут воспроизводится вся раскладка: разбор,
    проверенный на плоском каталоге, соврал бы о настоящем (170).
    """
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "caller.yml").write_text(caller, encoding="utf-8")
    (directory / "step-debt.yml").write_text(callee, encoding="utf-8")
    return directory


def test_a_called_job_gets_a_composed_name(tmp_path: Path) -> None:
    """Имя проверки у вызванного джоба составное: «вызывающий / вызванный».

    ЗАМЕР ПРОГОНОМ НА ЖИВОЙ ПЛОЩАДКЕ, а не догадка: изменение #549, вызывающий
    `outer`, вызванный `inner` — запись пришла именем «outer / inner». Голого
    имени не бывает. Документация площадки из окна недоступна, поэтому ответ
    взят прогоном
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

    Вписать сюда прежнее имя значило бы объявить проверку под именем, которого
    площадка не выдаст, — и сводный гейт ждал бы её вечно (045).

    ПОРЯДОК ПРОВЕРЯЕТСЯ, А НЕ ПОДРАЗУМЕВАЕТСЯ. Образцы зовут свои джобы РАЗНО —
    «снаружи» и «внутри», — поэтому обратный порядок здесь краснеет. Пока оба
    звались `debt`, ожидание «debt / debt» держалось при любой перестановке.
    """
    directory = called_tree(tmp_path)
    assert set(policy.declared_jobs(directory)) == {f"снаружи{policy.COMPOSED}внутри"}
    assert "внутри / снаружи" not in set(policy.declared_jobs(directory)), (
        "обратный порядок прошёл бы незамеченным"
    )


def test_a_called_run_is_not_a_check_of_its_own(tmp_path: Path) -> None:
    """Вызываемый прогон не числится ни на изменении, ни вне его.

    Родов три, а не два. Пока их было два, джоб вызываемого попадал в раздел
    «вне изменения», а вызывающий — в «на изменении», и разбор объявлял одно и
    то же имя неоднозначным: две проверки там, где она одна.
    """
    directory = called_tree(tmp_path)
    assert policy.beyond_jobs(directory) == {}


def test_a_foreign_call_keeps_its_own_name(tmp_path: Path) -> None:
    """Чужой вызов читать нечем — вызывающий остаётся со своим именем.

    Прогона чужого проекта в дереве нет, и имена его джобов неизвестны.
    Придумать их значило бы объявить проверку, которой может не быть; поэтому
    имя остаётся неполным и это названо, а не угадано
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    directory = called_tree(
        tmp_path,
        caller="name: c\non: [pull_request]\njobs:\n  debt:\n"
        "    name: debt\n    uses: someone/else/.github/workflows/x.yml@v1\n",
    )
    assert set(policy.declared_jobs(directory)) == {"debt"}


#: Прогон, который И вызываемый, И идёт сам. Площадка такое не запрещает, а
#: разбор до #612 пропускал его ЦЕЛИКОМ — оба раздела читали `workflow_call`
#: как повод не смотреть дальше.
BOTH_WORLDS = """name: и-туда-и-сюда
on:
  workflow_call:
  pull_request:
jobs:
  двойной:
    name: двойной
    steps: []
"""


def test_a_run_that_is_both_called_and_self_starting_is_refused(tmp_path: Path) -> None:
    """Прогон с обоими событиями — отказ, а не тихий пропуск обоими разделами.

    ЧТО БЫЛО. `declared_jobs` и `beyond_jobs` оба читали `workflow_call` как
    повод пропустить документ целиком, и джобы такого прогона не попадали
    НИКУДА — без единого красного. Докстрока соседа при этом обещала, что
    «джоб попадает ровно в один раздел, и „не спросили" перестаёт быть
    возможным состоянием»: обещание было шире кода
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    ПОЧЕМУ ОТКАЗ, А НЕ ВЫБОР РАЗДЕЛА. Джобы такого прогона дают запись ДВУМЯ
    именами сразу — простым и составным, — и какое считать проверкой, из
    документа не следует. Молчаливый выбор объявил бы проверку там, где их две,
    либо не объявил бы ни одной (045).

    ПРЕДМЕТА В ДЕРЕВЕ НЕТ, и это замер: 22.09.2026 из тридцати прогонов ни один
    не несёт обоих событий. Находка внешнего взгляда на #550 верно взвешена
    риском; до реестра она не доехала — её потерял разбор обзора (#612).
    """
    directory = tmp_path / "workflows"
    directory.mkdir()
    (directory / "оба.yml").write_text(BOTH_WORLDS, encoding="utf-8")
    (directory / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    for читатель in (policy.declared_jobs, policy.beyond_jobs):
        with pytest.raises(policy.BadPolicy, match="двумя именами сразу"):
            читатель(directory)


def test_a_plain_callee_is_still_skipped_quietly(tmp_path: Path) -> None:
    """Вторая половина: вызываемый С ОДНИМ событием отказа НЕ даёт.

    Без неё отказ превращается в «упомянут `workflow_call`» — и девять
    вызываемых прогонов дерева покраснели бы разом, хотя каждый из них исправен
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    directory = called_tree(tmp_path)
    assert set(policy.declared_jobs(directory)) == {f"снаружи{policy.COMPOSED}внутри"}
    assert policy.beyond_jobs(directory) == {}


def test_a_call_that_points_nowhere_is_refused(tmp_path: Path) -> None:
    """Вызов своего прогона, которого нет, — отказ, а не тихое старое имя.

    Проверка по такому вызову не появится вовсе, и красного об этом не будет:
    площадка просто не запустит несуществующее
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    directory = called_tree(
        tmp_path,
        caller="name: c\non: [pull_request]\njobs:\n  debt:\n"
        "    name: debt\n    uses: ./.github/workflows/нет-такого.yml\n",
    )
    with pytest.raises(policy.BadPolicy, match="которого в дереве нет"):
        policy.declared_jobs(directory)


def test_a_callee_without_its_event_is_refused(tmp_path: Path) -> None:
    """Вызываемый без `workflow_call` — отказ: площадка такой вызов отвергнет."""
    directory = called_tree(
        tmp_path,
        callee="name: step-debt\non: [push]\njobs:\n  debt:\n    name: debt\n    steps: []\n",
    )
    with pytest.raises(policy.BadPolicy, match="workflow_call"):
        policy.declared_jobs(directory)


def test_the_leading_dot_slash_is_not_normalised_away(tmp_path: Path) -> None:
    """Адрес вызова остаётся СТРОКОЙ, и ведущее «./» не теряется.

    `Path("./x")` нормализует «./» прочь, и признак «свой вызов» переставал
    срабатывать: составное имя не собиралось, а проверка молча числилась под
    старым именем — под тем, которого площадка не выдаст. Поймано первым же
    прогоном разбора по дереву, и закреплено здесь, чтобы не вернулось
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    directory = called_tree(tmp_path)
    assert policy.called_jobs("./.github/workflows/step-debt.yml", directory) == ["внутри"]
    assert policy.called_jobs(".github/workflows/step-debt.yml", directory) is None


# --- разбор ответа: один на своё дерево и на чужое ---------------------------


def test_the_off_class_survives_the_yaml_boolean() -> None:
    """`off` в YAML 1.1 читается БУЛЕВЫМ, и разбор это знает.

    Та же ловушка, что с `on:` в прогонах, и цена у неё та же: класс, ставший
    `False`, не равен строке «off» ни при каком сравнении, и объявленный обход
    стал бы невидимым ровно там, где он объявлен
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

    ИМЯ ПУБЛИЧНОЕ ПОТОМУ, ЧТО ЧИТАТЕЛЕЙ ДВОЕ: свой ответ и ответ потребителя у
    сверки. Приватное имя заставило бы второго завести своё понимание той же
    формы (090).
    """
    assert policy.text_of(False) == policy.OFF
    assert policy.text_of(True) == "on"
    assert policy.text_of("advisory") == policy.ADVISORY
    assert policy.text_of(None) == ""
    assert policy.text_of("  required  ") == policy.REQUIRED


def test_a_foreign_answer_is_parsed_from_text() -> None:
    """Ответ ЧУЖОГО дерева приходит строкой, и разбирается тем же разбором.

    Соседний `load` читает файл своего дерева; ответ потребителя приходит из
    площадки, и файла у нас нет. Второй разбор той же формы разошёлся бы с
    первым молча (090).
    """
    said = policy.answer_text('checks:\n  "lint / lint": off\n', "o/r")
    assert policy.text_of(said["checks"]["lint / lint"]) == policy.OFF


def test_a_foreign_answer_that_is_not_a_mapping_is_refused() -> None:
    """Не словарь — отказ входа, а не пустой ответ: «нет обходов» и «не
    прочитали» снаружи неотличимы (045)."""
    with pytest.raises(policy.BadPolicy, match="не словарь"):
        policy.answer_text("- просто список\n", "o/r")


def test_a_foreign_answer_that_does_not_parse_is_refused() -> None:
    """Сломанный YAML чужого дерева — отказ с адресом, а не тихая пустота."""
    with pytest.raises(policy.BadPolicy, match="o/r"):
        policy.answer_text("checks:\n  - [непарная\n", "o/r")
