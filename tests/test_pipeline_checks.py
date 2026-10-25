"""Классы проверок проверяются тем, что механизм обязан отвергнуть.

Правило 140: гейт проверяется отказом, а не тем, что он пропускает зелёное.
Здесь предмет двойной — разбор ответа проекта (`.pipeline.yml`) и сверка
ответа с деревом, — и оба проверяются подделанными расхождениями.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FAKE_VERSION, Run, RunScript, load_script

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


# --- окно контракта: под какую версию проверяется ответ (#1387) ---------------


def answered(root: Path) -> Path:
    """Ответ проекта с окном `>=0.1,<0.2` и одной проверкой — без своей версии контракта."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".pipeline.yml"
    path.write_text(HEAD + "checks:\n  lint: unreviewed\n", encoding="utf-8")
    return path


def supplier_at(root: Path, contract: str | None) -> Path:
    """Выкачка поставщика: код конвейера на коммите позванного тега и его версия."""
    root.mkdir(parents=True, exist_ok=True)
    if contract is not None:
        (root / "CONTRACT_VERSION").write_text(f"{contract}\n", encoding="utf-8")
    return root


def test_a_called_tag_outside_the_window_is_refused_at_the_consumer(tmp_path: Path) -> None:
    """У потребителя версия контракта — у ПОЗВАННОГО тега (`$MECHANISMS`), а не в его дереве.

    Дерево потребителя своего `CONTRACT_VERSION` не несёт: он наш. Прежде сверка
    искала файл только рядом с `.pipeline.yml` и у потребителя молча не шла —
    тег, поднятый Dependabot за окно `contract:`, проходил зелёным (045). Нашла
    проба пути подъёма из #1387, п. 3.
    """
    path = answered(tmp_path / "consumer")
    supplier = supplier_at(tmp_path / "mechanisms", FAKE_VERSION)
    with pytest.raises(policy.BadPolicy, match="вне объявленного диапазона"):
        policy.load(path, supplier=supplier)


def test_a_called_tag_inside_the_window_passes(tmp_path: Path) -> None:
    """Тег в окне ответа проходит: отказ держится версией, а не присутствием поставщика."""
    path = answered(tmp_path / "consumer")
    supplier = supplier_at(tmp_path / "mechanisms", "0.1.7")
    assert "lint" in policy.load(path, supplier=supplier)


def test_a_supplier_without_its_version_is_refused(tmp_path: Path) -> None:
    """Выкачка без `CONTRACT_VERSION` — отказ, а не «сверять не с чем» (075)."""
    path = answered(tmp_path / "consumer")
    supplier = supplier_at(tmp_path / "mechanisms", None)
    with pytest.raises(policy.BadPolicy, match="версия контракта"):
        policy.load(path, supplier=supplier)


def test_the_own_contract_comes_first_and_the_called_tag_second(tmp_path: Path) -> None:
    """`contract_of`: дерево со своей версией — поставщик; без неё — версия позванного тега.

    Своя версия первее выкачки: проба передачи зовёт прошлый тег на нашем
    дереве, и выкачка первой красила бы её на каждом выпуске (взгляд на #1498).
    Ни своей, ни поставщика — `None`; поставщик без версии — отказ (045).
    """
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "CONTRACT_VERSION").write_text("0.1.0\n", encoding="utf-8")
    supplier = supplier_at(tmp_path / "mechanisms", FAKE_VERSION)
    assert policy.contract_of(tree, supplier) == "0.1.0"
    assert policy.contract_of(tree, None) == "0.1.0"
    assert policy.contract_of(tmp_path / "bare", supplier) == FAKE_VERSION
    assert policy.contract_of(tmp_path / "bare", None) is None
    with pytest.raises(policy.BadPolicy, match="версия контракта позванного тега"):
        policy.contract_of(tmp_path / "bare", supplier_at(tmp_path / "empty", None))


def cloned(where: Path, origin: str) -> Path:
    """Выкачка поставщика — настоящий клон с `origin`, как её оставляет `actions/checkout`."""
    where.mkdir(parents=True, exist_ok=True)
    for args in (["init", "--quiet"], ["remote", "add", "origin", origin]):
        subprocess.run(["git", "-C", str(where), *args], check=True, timeout=30)
    (where / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    return where


@pytest.mark.parametrize(
    ("running", "origin", "taken"),
    [
        ("Owner/Consumer", "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms", "tag"),
        ("owner/consumer", "git@github.com:ArtVsMark/Engineering-Pipeline-Mechanisms.git", "tag"),
        (
            "ArtVsMark/Engineering-Pipeline-Mechanisms",
            "https://github.com/artvsmark/engineering-pipeline-mechanisms.git",
            "own",
        ),
        ("", "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms", "own"),
    ],
    ids=["чужой-https", "чужой-ssh", "свой-регистр", "прогон-не-назван"],
)
def test_a_consumers_own_contract_is_not_the_suppliers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: str, origin: str, taken: str
) -> None:
    """Своя версия контракта — только у самого поставщика, а не у дерева с файлом (`169baca`)."""
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "CONTRACT_VERSION").write_text("0.1.0\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", running)
    # Каталог запуска — дерево без `origin`: без имени прогона своя сторона
    # иначе читалась бы у того клона, откуда позван набор (среда прогона, 018).
    monkeypatch.chdir(tree)
    supplier = cloned(tmp_path / "mechanisms", origin)
    assert policy.contract_of(tree, supplier) == (FAKE_VERSION if taken == "tag" else "0.1.0")


def test_the_supplier_is_named_by_the_origin_of_its_clone(tmp_path: Path) -> None:
    """`supplier_repo` — `владелец/репозиторий` строчными из `origin`; не клон — пусто (045)."""
    https = cloned(tmp_path / "a", "https://github.com/Owner/Repo.git")
    ssh = cloned(tmp_path / "b", "git@github.com:Owner/Repo")
    assert policy.supplier_repo(https) == policy.supplier_repo(ssh) == "owner/repo"
    (tmp_path / "bare").mkdir()
    assert policy.supplier_repo(tmp_path / "bare") == ""


def test_the_own_version_outside_the_window_is_refused(tmp_path: Path) -> None:
    """У поставщика без выкачки версия — своя, из дерева: окно сверяется и у нас."""
    path = answered(tmp_path)
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="вне объявленного диапазона"):
        policy.load(path)


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


TAG_CALL = "ArtVsMark/Engineering-Pipeline-Mechanisms/.github/workflows/step-meta.yml@v1.9.0"
TRUNK_CALL = "ArtVsMark/Engineering-Pipeline-Mechanisms/.github/workflows/step-meta.yml@main"
STEP_META = "name: step\non:\n  workflow_call:\njobs:\n  meta:\n    name: pr-meta\n    steps: []\n"


@pytest.mark.parametrize("call", [TAG_CALL, TRUNK_CALL], ids=["тег", "общая-ветка"])
@pytest.mark.parametrize(
    ("running", "origin", "named"),
    [
        (
            "Owner/Consumer",
            "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms",
            {"pr-meta / pr-meta"},
        ),
        # Выкачка — другой репозиторий: адрес вызова к ней не относится.
        ("Owner/Consumer", "https://github.com/someone/else", {"pr-meta"}),
        # Наше дерево: вызов по тегу — проба передачи, имена намеренно неизвестны.
        (
            "ArtVsMark/Engineering-Pipeline-Mechanisms",
            "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms",
            {"pr-meta"},
        ),
    ],
    ids=["потребитель", "чужая-выкачка", "своё-дерево"],
)
def test_a_tag_call_at_the_consumer_is_named_from_the_supplier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    running: str,
    origin: str,
    named: set[str],
    call: str,
) -> None:
    """У потребителя вызов по тегу читается из выкачки поставщика (#1568).

    Заготовка `onboard.py` пишет `pr-meta / pr-meta` — так запись и называет
    площадка, — а сверка давала голое `pr-meta`, и потребитель получал по
    находке на каждый свой шаг.
    """
    supplier = cloned(tmp_path / "mechanisms", origin)
    (supplier / ".github" / "workflows").mkdir(parents=True)
    (supplier / ".github" / "workflows" / "step-meta.yml").write_text(STEP_META, encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", running)
    monkeypatch.setenv(policy.SUPPLIER_ENV, str(supplier))
    directory = called_tree(
        tmp_path / "consumer",
        caller="name: c\non: [pull_request]\njobs:\n  meta:\n    name: pr-meta\n"
        f"    uses: {call}\n",
    )
    assert set(policy.declared_jobs(directory)) == named


def test_running_repo_is_the_platform_then_the_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Свой репозиторий: площадка первее, вне её — `origin`; регистр не важен (`68511bc`)."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "Owner/Consumer")
    assert policy.running_repo() == "owner/consumer"
    monkeypatch.delenv("GITHUB_REPOSITORY")
    clone = cloned(tmp_path / "свой", "https://github.com/Some/Where")
    monkeypatch.chdir(clone)
    assert policy.running_repo() == "some/where"


def test_a_trunk_call_to_a_file_the_consumer_also_has_reads_the_supplier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`…@main` поставщика при одноимённом файле у потребителя — имена выкачки (`68511bc`).

    Свой прогон потребителя назван иначе: прочитай сверка его — имя было бы
    `pr-meta / свой`, а площадка запишет джоб поставщика.
    """
    supplier = cloned(
        tmp_path / "mechanisms", "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms"
    )
    (supplier / ".github" / "workflows").mkdir(parents=True)
    (supplier / ".github" / "workflows" / "step-meta.yml").write_text(STEP_META, encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Owner/Consumer")
    monkeypatch.setenv(policy.SUPPLIER_ENV, str(supplier))
    directory = called_tree(
        tmp_path / "consumer",
        caller="name: c\non: [pull_request]\njobs:\n  meta:\n    name: pr-meta\n"
        f"    uses: {TRUNK_CALL}\n",
    )
    (directory / "step-meta.yml").write_text(
        STEP_META.replace("name: pr-meta", "name: свой"), encoding="utf-8"
    )
    assert set(policy.declared_jobs(directory)) == {"pr-meta / pr-meta"}
    monkeypatch.setenv("GITHUB_REPOSITORY", "ArtVsMark/Engineering-Pipeline-Mechanisms")
    assert set(policy.declared_jobs(directory)) == {"pr-meta / свой"}, "своё дерево — своё"


def test_a_tag_call_to_a_file_the_supplier_lacks_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Прогона нет и в выкачке — отказ, а не голое имя молча (045)."""
    supplier = cloned(
        tmp_path / "mechanisms", "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms"
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "Owner/Consumer")
    monkeypatch.setenv(policy.SUPPLIER_ENV, str(supplier))
    with pytest.raises(policy.BadPolicy, match="нет и в выкачке"):
        policy.supplied_jobs(TAG_CALL)


def test_jobs_of_called_names_every_job_of_a_called_run(tmp_path: Path) -> None:
    """`jobs_of_called`: имя джоба — его `name`, без имени — ключ; без `workflow_call` — отказ."""
    run = tmp_path / "step.yml"
    run.write_text(
        "on:\n  workflow_call:\njobs:\n"
        "  a:\n    name: первый\n    steps: []\n  b:\n    steps: []\n",
        encoding="utf-8",
    )
    assert policy.jobs_of_called(run) == ["первый", "b"]
    run.write_text("on: [push]\njobs:\n  a:\n    steps: []\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="workflow_call"):
        policy.jobs_of_called(run)


def test_a_supplied_run_without_workflow_call_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Прогон из выкачки судится тем же разбором, что из дерева: без `workflow_call` — отказ."""
    supplier = cloned(
        tmp_path / "mechanisms", "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms"
    )
    (supplier / ".github" / "workflows").mkdir(parents=True)
    (supplier / ".github" / "workflows" / "step-meta.yml").write_text(
        STEP_META.replace("workflow_call", "pull_request"), encoding="utf-8"
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "Owner/Consumer")
    monkeypatch.setenv(policy.SUPPLIER_ENV, str(supplier))
    with pytest.raises(policy.BadPolicy, match="workflow_call"):
        policy.supplied_jobs(TAG_CALL)


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


def test_an_own_call_by_the_trunk_address_is_read_from_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Свой вызов адресом с общей веткой читается деревом, по тегу — нет (#993).

    Так `review.yml` зовёт тело взгляда, чтобы карта не исполняла код головы;
    имя его записи площадка собирает составным, как у `./`. Вызов по тегу —
    выпуск, а не дерево, и его имена остаются неизвестными (046); адрес, чьего
    файла в дереве нет, — чужой вызов, а не отказ.
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "о/р")  # свой — тот, кого адрес называет
    directory = called_tree(tmp_path)
    trunk = f"О/Р/.github/workflows/step-debt.yml@{policy.paths.TRUNK}"
    assert policy.called_jobs(trunk, directory) == ["внутри"]
    assert policy.called_jobs("О/Р/.github/workflows/step-debt.yml@v1.4.0", directory) is None
    absent = f"О/Р/.github/workflows/нет-такого.yml@{policy.paths.TRUNK}"
    assert policy.called_jobs(absent, directory) is None


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


def test_a_matrix_axis_is_read_or_refused(tmp_path: Path) -> None:
    """Ось матрицы читается со своим образом, а отсутствие — отказ с причиной (#1001)."""
    flow = tmp_path / "ci.yml"
    flow.write_text(
        "jobs:\n  t:\n    runs-on: img\n    strategy:\n"
        "      matrix:\n        python: ['3.12', 3.13]\n",
        encoding="utf-8",
    )
    assert policy.matrix_axis(flow, "t", "python") == (["3.12", "3.13"], "img")
    with pytest.raises(policy.BadPolicy, match="не прочитана"):
        policy.matrix_axis(flow, "нет", "python")


CALLED_STEP = (
    "on:\n  workflow_call:\n    inputs:\n      python:\n        type: string\n"
    "        required: true\n      test:\n        type: string\n        default: pytest\n"
    "jobs:\n  inner:\n    name: inner\n    runs-on: img\n    steps:\n"
    "      - uses: actions/setup-python@v6\n        with:\n"
    "          python-version: ${{ inputs.python }}\n"
    '      - env:\n          TEST: ${{ inputs.test }}\n        run: bash -c "$TEST"\n'
)


def calling_tree(tmp_path: Path, uses: str = "./.github/workflows/step-x.yml") -> Path:
    """Дерево с вызывающим прогоном `x.yml` и вызванным шагом `step-x.yml`."""
    flows = tmp_path / ".github" / "workflows"
    flows.mkdir(parents=True)
    (flows / "step-x.yml").write_text(CALLED_STEP, encoding="utf-8")
    (flows / "x.yml").write_text(
        "on: push\njobs:\n  t:\n    strategy:\n      matrix:\n        python: ['3.16']\n"
        f"    uses: {uses}\n    with:\n      python: ${{{{ matrix.python }}}}\n",
        encoding="utf-8",
    )
    return flows / "x.yml"


def test_a_calling_job_resolves_to_the_called_body(tmp_path: Path) -> None:
    """Джоб-вызов читается телом шага: образ и шаги у шага, матрица у вызова (#1556).

    Вход берётся из `with:` вызова, а без него — умолчанием шага: ровно то, что
    подставит площадка. Без этого читатели образа и `setup-python` теряли
    предмет молча, как только джоб выносили в общий шаг.
    """
    path = calling_tree(tmp_path)
    body = policy.resolved_job(path, "t")
    assert body["runs-on"] == "img"
    assert body["name"] == "t"
    assert body["strategy"]["matrix"]["python"] == ["3.16"]
    assert body["steps"][0]["with"]["python-version"] == "${{ matrix.python }}"
    assert body["steps"][1]["env"]["TEST"] == "pytest"
    assert policy.matrix_axis(path, "t", "python") == (["3.16"], "img")


def test_a_plain_job_resolves_to_itself_and_a_remote_call_is_refused(tmp_path: Path) -> None:
    """Обычный джоб — как есть; удалённый вызов — отказ, а не джоб без шагов (075)."""
    path = calling_tree(tmp_path, uses="o/r/.github/workflows/step-x.yml@v1")
    assert policy.remote_call({"uses": "o/r/.github/workflows/step-x.yml@v1"})
    assert not policy.remote_call({"uses": "./.github/workflows/step-x.yml"})
    assert not policy.remote_call({"runs-on": "img"})
    with pytest.raises(policy.BadPolicy, match="удалённый"):
        policy.resolved_job(path, "t")
    plain = tmp_path / ".github" / "workflows" / "step-x.yml"
    assert policy.resolved_job(plain, "inner")["runs-on"] == "img"
    with pytest.raises(policy.BadPolicy, match="нет джоба"):
        policy.resolved_job(plain, "нет")


def test_a_called_step_with_two_jobs_is_ambiguous(tmp_path: Path) -> None:
    """Два джоба в вызванном шаге — отказ: какой из них тело, неизвестно (045)."""
    path = calling_tree(tmp_path)
    step = path.with_name("step-x.yml")
    step.write_text(
        step.read_text(encoding="utf-8") + "  other:\n    runs-on: img\n    steps: []\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="неоднозначно"):
        policy.resolved_job(path, "t")


def test_a_mechanism_path_resolves_in_the_supplier_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Путь механизма, которого нет в дереве, ищется в коде поставщика `$MECHANISMS` (#990).

    У потребителя наших `scripts/` нет: управляющий шаг зовёт их из своей
    выкачки, и адресат «путь механизма» лежит там же.
    """
    tree, supplier = tmp_path / "tree", supplier_at(tmp_path / "supplier", "0.1.7")
    (supplier / "scripts").mkdir(parents=True)
    (supplier / "scripts" / "main_red.py").write_text("", encoding="utf-8")
    tree.mkdir()
    path = tree / ".pipeline.yml"
    path.write_text(
        HEAD + "checks:\n  review:\n    class: advisory\n"
        "    why: смотрим\n    addressee: scripts/main_red.py\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="не разрешается"):
        policy.load(path)
    monkeypatch.setenv(policy.SUPPLIER_ENV, str(supplier))
    assert policy.load(path)["review"].records is True
    assert policy.resolves("scripts/*.py", tree, supplier)
    assert not policy.resolves("scripts/nowhere.py", tree, supplier)
    assert not policy.resolves("scripts/main_red.py", tree), "окружение прочитано в resolves"


def test_a_refusal_names_both_places(tmp_path: Path) -> None:
    """С поставщиком отказ называет и дерево, и код конвейера — искать надо в обоих."""
    path = tmp_path / ".pipeline.yml"
    path.write_text(
        HEAD + "checks:\n  review:\n    class: advisory\n"
        "    why: смотрим\n    addressee: scripts/nowhere.py\n",
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="в дереве и в коде конвейера"):
        policy.load(path, supplier=supplier_at(tmp_path / "supplier", "0.1.7"))


def test_the_supplier_is_read_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`supplier_of` — `$MECHANISMS` общего шага; не задан или пуст — поставщика нет."""
    assert policy.supplier_of() is None
    monkeypatch.setenv(policy.SUPPLIER_ENV, "")
    assert policy.supplier_of() is None
    monkeypatch.setenv(policy.SUPPLIER_ENV, str(tmp_path))
    assert policy.supplier_of() == tmp_path


def test_only_mechanism_code_is_looked_up_at_the_supplier(tmp_path: Path) -> None:
    """У поставщика ищется код механизмов, а не его документы и набор (#1163)."""
    tree, supplier = tmp_path / "tree", tmp_path / "supplier"
    tree.mkdir()
    for name in ("scripts/main_red.py", "docs/runbook.md", "README.md"):
        (supplier / name).parent.mkdir(parents=True, exist_ok=True)
        (supplier / name).write_text("", encoding="utf-8")
    assert policy.resolves("scripts/main_red.py", tree, supplier)
    assert not policy.resolves("docs/runbook.md", tree, supplier), "документ поставщика засчитан"
    assert not policy.resolves("README.md", tree, supplier)
    assert not policy.resolves("docs/*.md", tree, supplier), "образец по документам поставщика"


def test_a_pattern_found_only_at_the_supplier_needs_the_supplier(tmp_path: Path) -> None:
    """Образец, совпавший лишь у поставщика, без поставщика не разрешается (#1163)."""
    tree, supplier = tmp_path / "tree", tmp_path / "supplier"
    tree.mkdir()
    (supplier / "scripts").mkdir(parents=True)
    (supplier / "scripts" / "stuck.py").write_text("", encoding="utf-8")
    assert policy.resolves("scripts/*.py", tree, supplier)
    assert not policy.resolves("scripts/*.py", tree), "без поставщика образец разрешился"


def test_a_climb_out_of_the_mechanism_dirs_is_not_looked_up_at_the_supplier(
    tmp_path: Path,
) -> None:
    """`scripts/../docs/x.md` начинается с каталога механизмов, но к поставщику не идёт (#1167)."""
    tree, supplier = tmp_path / "tree", tmp_path / "supplier"
    tree.mkdir()
    for name in ("scripts/main_red.py", "docs/runbook.md"):
        (supplier / name).parent.mkdir(parents=True, exist_ok=True)
        (supplier / name).write_text("", encoding="utf-8")
    assert not policy.resolves("scripts/../docs/runbook.md", tree, supplier)
    assert not policy.resolves("scripts/../docs/*.md", tree, supplier)
    assert policy.resolves("scripts/main_red.py", tree, supplier)


@pytest.mark.parametrize(
    ("section", "passes"),
    [
        ("journal:\n  tail: '^> правило'\n  link: body\n", True),
        ("journal:\n  tail: '(незакрытая'\n", False),
        ("journal:\n  link: anywhere\n", False),
    ],
    ids=["форма-каталога", "битый-образец", "неизвестный-link"],
)
def test_the_journal_section_is_judged_with_the_answer(
    tmp_path: Path, section: str, passes: bool
) -> None:
    """Раздел формы фрагмента судится сверкой ответа — раньше, чем шагом журнала (#1570)."""
    path = answered(tmp_path / "tree")
    path.write_text(path.read_text(encoding="utf-8") + section, encoding="utf-8")
    supplier = supplier_at(tmp_path / "mechanisms", "0.1.0")
    if passes:
        policy.load(path, supplier=supplier)
    else:
        with pytest.raises(policy.BadPolicy, match="раздел journal"):
            policy.load(path, supplier=supplier)


@pytest.mark.parametrize(
    "read",
    [
        lambda path: policy.run_of(path),
        lambda path: policy.load(path),
        lambda path: policy.span(path),
    ],
    ids=["прогон", "ответ", "диапазон"],
)
def test_a_file_not_in_utf8_is_a_refusal_not_a_trace(tmp_path: Path, read: Any) -> None:
    """Файл не в UTF-8 — `BadPolicy` с причиной, а не `UnicodeDecodeError` (взгляд на #1567)."""
    path = tmp_path / "x.yml"
    path.write_bytes("name: ы\n".encode("cp1251"))
    with pytest.raises(policy.BadPolicy, match="не прочитан"):
        read(path)


def test_file_text_reads_utf8_and_names_the_refusal(tmp_path: Path) -> None:
    """`file_text` — текст в UTF-8; каталог вместо файла — отказ с названным предметом."""
    path = tmp_path / "x.yml"
    path.write_text("ы\n", encoding="utf-8")
    assert policy.file_text(path, "прогон") == "ы\n"
    with pytest.raises(policy.BadPolicy, match="прогон"):
        policy.file_text(tmp_path, "прогон")


def test_span_names_a_broken_yaml(tmp_path: Path) -> None:
    """Битый YAML у `span` — `BadPolicy`, а не трасса `YAMLError`."""
    path = tmp_path / ".pipeline.yml"
    path.write_text("contract: [\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="не разбирается"):
        policy.span(path)


def test_a_contract_version_not_in_utf8_is_a_refusal(tmp_path: Path) -> None:
    """`CONTRACT_VERSION` не в UTF-8 — `BadPolicy` у `contract_of` (взгляд на #1593)."""
    (tmp_path / "CONTRACT_VERSION").write_bytes("1.0.0 ы\n".encode("cp1251"))
    with pytest.raises(policy.BadPolicy, match="версия контракта"):
        policy.contract_of(tmp_path, None)


def test_fragment_form_of_a_file_not_in_utf8_is_named(tmp_path: Path) -> None:
    """`fragment_form` читает тем же `file_text`: не UTF-8 — `journal.NotRun` с причиной."""
    path = tmp_path / ".pipeline.yml"
    path.write_bytes("journal: ы\n".encode("cp1251"))
    with pytest.raises(policy.journal.NotRun, match="не прочитан"):
        policy.fragment_form(path)


@pytest.mark.parametrize(
    ("section", "passes"),
    [
        ("scopes:\n  web:\n    paths: ['web/**']\n    tests: ['tests/web/**']\n", True),
        ("scopes:\n  web:\n    paths: ['web/**']\n", False),
        ("scopes:\n  web:\n    paths: []\n    tests: ['tests/web/**']\n", False),
        ("scopes:\n  web:\n    paths: ['web/**']\n    tests: ['t']\n    why: x\n", False),
        ("scopes: [web]\n", False),
    ],
    ids=["область", "без-тестов", "пустые-пути", "чужой-ключ", "не-отображение"],
)
def test_the_scopes_section_is_judged_with_the_answer(
    tmp_path: Path, section: str, passes: bool
) -> None:
    """Раздел областей судится сверкой ответа — раньше первого прогона тестов (#1600)."""
    path = answered(tmp_path / "tree")
    path.write_text(path.read_text(encoding="utf-8") + section, encoding="utf-8")
    supplier = supplier_at(tmp_path / "mechanisms", "0.1.0")
    if passes:
        policy.load(path, supplier=supplier)
        assert [area.name for area in policy.areas_for_tests(path)] == ["web"]
    else:
        with pytest.raises(policy.BadPolicy, match="раздел scopes"):
            policy.load(path, supplier=supplier)


def test_areas_without_a_file_or_a_section_are_none(tmp_path: Path) -> None:
    """Нет файла или раздела — областей нет; битый YAML — отказ с причиной."""
    assert policy.areas_for_tests(tmp_path / "нет.yml") == ()
    plain = tmp_path / "plain.yml"
    plain.write_text("schema: 4\n", encoding="utf-8")
    assert policy.areas_for_tests(plain) == ()
    broken = tmp_path / "broken.yml"
    broken.write_text("scopes: [\n", encoding="utf-8")
    with pytest.raises(policy.scope_areas.BadAreas, match="не прочитан"):
        policy.areas_for_tests(broken)


# --- таблица путей проекта (#1630) -----------------------------------------


def test_the_path_table_defaults_to_the_old_anchors() -> None:
    """19 ключей, и умолчание каждого — прежняя константа якоря."""
    anchors = policy.paths
    assert len(anchors.PROJECT) == 19
    assert anchors.PROJECT["roles"] == anchors.ROLES
    assert anchors.PROJECT["review-roles"] == anchors.REVIEW_ROLES
    assert anchors.table_of(None) == anchors.PROJECT


@pytest.mark.parametrize(
    ("section", "said"),
    [
        ({"rolez": "x.md"}, "такого ключа нет"),
        ({"roles": "/abs/roles.md"}, "вне дерева"),
        ({"roles": "../up/roles.md"}, "вне дерева"),
        ({"roles": ""}, "непустая строка"),
        ({"roles": "."}, "корень дерева"),
        (["roles"], "ожидалось отображение"),
    ],
    ids=["неизвестный-ключ", "абсолютный", "выше-корня", "пустой", "корень", "не-словарь"],
)
def test_a_bad_paths_section_is_refused_with_its_reason(section: object, said: str) -> None:
    """Дефект раздела путей — отказ с причиной, а не тихое умолчание (045)."""
    with pytest.raises(policy.paths.BadPaths, match=said):
        policy.paths.table_of(section)


def test_project_path_reads_the_override_and_falls_back_to_the_default(tmp_path: Path) -> None:
    """Раздел `paths:` переопределяет адрес; без файла и без раздела — умолчание."""
    anchors = policy.paths
    assert policy.project_path("roles", tmp_path) == anchors.ROLES
    (tmp_path / ".pipeline.yml").write_text("schema: 4\nchecks: {}\n", encoding="utf-8")
    assert policy.project_path("roles", tmp_path) == anchors.ROLES
    (tmp_path / ".pipeline.yml").write_text(
        "schema: 4\nchecks: {}\npaths:\n  roles: handbook/roles.md\n", encoding="utf-8"
    )
    assert policy.project_path("roles", tmp_path) == Path("handbook/roles.md")
    assert policy.project_path("labels", tmp_path) == anchors.LABELS
    assert policy.project_paths(tmp_path / ".pipeline.yml")["roles"] == Path("handbook/roles.md")


def test_the_paths_entry_point_prints_the_address_of_a_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`paths.py <ключ>` печатает адрес по таблице дерева; чужой ключ и битая — отказ (#1623)."""
    anchors = policy.paths
    (tmp_path / ".pipeline.yml").write_text("paths:\n  bindings: cfg/answer.json\n", "utf-8")
    assert anchors.main(["bindings", "--root", str(tmp_path)]) == anchors.EXIT_OK
    assert capsys.readouterr().out.strip() == "cfg/answer.json"
    assert anchors.main(["roles", "--root", str(tmp_path)]) == anchors.EXIT_OK
    assert capsys.readouterr().out.strip() == anchors.ROLES.as_posix()
    assert anchors.main(["nope", "--root", str(tmp_path)]) == anchors.EXIT_BROKEN
    assert "ключа «nope»" in capsys.readouterr().err
    (tmp_path / ".pipeline.yml").write_text("paths:\n  bindings: /abs.json\n", "utf-8")
    assert anchors.main(["bindings", "--root", str(tmp_path)]) == anchors.EXIT_BROKEN
    assert "вне дерева" in capsys.readouterr().err


def test_the_paths_script_refuses_a_broken_table_with_its_exit(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Скриптом, как зовёт навык: битая таблица — отказ с причиной и кодом 2, а не трасса.

    Под `python scripts/paths.py` модуль — `__main__`, и отказ `pipeline_checks`
    приходит из второго экземпляра `paths` (взгляд на #1653): вызов функцией
    этого не видит.
    """
    (tmp_path / ".pipeline.yml").write_text("paths:\n  bindings: /abs.json\n", "utf-8")
    said = run_script("paths.py", "bindings", "--root", str(tmp_path))
    assert said.code == policy.paths.EXIT_BROKEN
    assert "не разобрана" in said.err
    assert "Traceback" not in said.err


def test_project_paths_of_reads_text_and_names_a_broken_answer() -> None:
    """Из текста ответа — та же таблица; не разобранный YAML — `BadPaths` с местом."""
    said = policy.project_paths_of("paths:\n  review-roles: cfg/roles.json\n", "main:.pipeline.yml")
    assert said["review-roles"] == Path("cfg/roles.json")
    with pytest.raises(policy.paths.BadPaths, match=r"main:\.pipeline\.yml"):
        policy.project_paths_of("paths: [\n", "main:.pipeline.yml")


def test_the_answer_check_refuses_a_bad_paths_section_early(tmp_path: Path) -> None:
    """Сверка ответа (`load`) отвергает битый раздел путей — раньше первого читателя."""
    answer = tmp_path / ".pipeline.yml"
    answer.write_text(
        'schema: 4\ncontract: ">=0.1,<99"\nchecks:\n  lint: required\npaths:\n  rolez: x\n',
        encoding="utf-8",
    )
    with pytest.raises(policy.BadPolicy, match="такого ключа нет"):
        policy.load(answer, supplier=None)
