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
HEAD = 'schema: 3\ncontract: ">=0.1,<0.2"\n'

GOOD = """
schema: 3
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
    [HEAD + "checks: {}\n", 'schema: 3\ncontract: ">=0.1,<0.2"\n'],
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
    assert "держат слияние: lint" in run.text


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
