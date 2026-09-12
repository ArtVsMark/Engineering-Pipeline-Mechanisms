"""Поверхность контракта: что гейт обязан поймать и что обязан пропустить.

Оба вида ошибки здесь одинаково дороги. Пропущенная правка поверхности ломает
потребителя молча — он узнаёт об этом красной защитой ветки на своей стороне и
починить у себя не может. Лишнее красное на переставленном комментарии учит
обходить гейт, и тогда он не ловит уже ничего
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script

contract = load_script("contract.py")
policy = load_script("pipeline_checks.py")
gate = load_script("check_contract.py")

WORKFLOW = """
name: ci
on:
  pull_request:
    types: [opened]
  workflow_dispatch:
    inputs:
      pr:
        description: "номер"
        required: true
        type: string
jobs:
  lint:
    name: lint
    steps: []
"""

ANSWER = 'schema: 4\ncontract: ">=0.1,<0.2"\nchecks:\n  lint: required\n'


def tree(root: Path, workflow: str | None = WORKFLOW, answer: str = ANSWER) -> Path:
    """Собирает дерево с одним прогоном и ответом проекта.

    `workflow=None` значит «прогонов нет вовсе»: так подделывается снятие
    прогона целиком — иначе примету «прогон удалён» не печатает никто, а
    проверить её иначе нечем.
    """
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    if workflow is not None:
        (directory / "ci.yml").write_text(workflow, encoding="utf-8")
    (root / ".pipeline.yml").write_text(answer, encoding="utf-8")
    return root


def test_the_surface_is_taken_from_the_tree(tmp_path: Path) -> None:
    """Снимок собирается с дерева, а не ведётся списком руками.

    Список руками отстаёт молча: новый прогон добавляется файлом, и о нём никто
    не вспомнит (049).
    """
    shape = contract.surface(tree(tmp_path))
    assert shape["workflows"]["ci.yml"]["jobs"] == ["lint"]
    assert shape["answer"]["checks"] == {"lint": "required"}


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (lambda text: text.replace("name: lint", "name: linter"), "джоб"),
        (lambda text: text.replace("      pr:", "      number:"), "входы"),
        (lambda text: text.replace("required: true", "required: false"), "входы"),
        (
            lambda text: text.replace("    types: [opened]", "    types: [opened, closed]"),
            "события",
        ),
    ],
    ids=["имя джоба", "имя входа", "обязательность входа", "события"],
)
def test_a_visible_change_is_caught(tmp_path: Path, edit: Any, expected: str) -> None:
    """Правка того, что видит потребитель, считается изменением поверхности.

    Имя джоба уезжает в чужую защиту ветки дословно, вход кнопки — в чужой
    вызов, событие — в чужое понимание, когда шаг сработает.
    """
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(tree(tmp_path / "after", workflow=edit(WORKFLOW)))
    changes = contract.differences(before, after)
    assert changes, "правка поверхности не замечена"
    assert any(expected in line for line in changes), changes


@pytest.mark.parametrize(
    "edit",
    [
        lambda text: text.replace("jobs:", "# пояснение для читателя\njobs:"),
        lambda text: text.replace("    steps: []", "    steps: []\n    timeout-minutes: 10"),
        lambda text: text.replace('        description: "номер"', '        description: "иначе"'),
    ],
    ids=["комментарий", "предел времени", "описание входа"],
)
def test_an_internal_change_is_not_the_surface(tmp_path: Path, edit: Any) -> None:
    """Внутреннее меняется свободно: контракт от каждой правки не двигается.

    Предел времени, комментарий и описание входа потребителю не видны и в его
    вызовы не попадают. Красное на них научило бы обходить гейт.
    """
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(tree(tmp_path / "after", workflow=edit(WORKFLOW)))
    assert contract.differences(before, after) == []


def test_a_class_change_is_the_surface(tmp_path: Path) -> None:
    """Класс проверки — форма чужого ответа: его правка видна потребителю."""
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(
        tree(tmp_path / "after", answer=ANSWER.replace("required", "advisory"))
    )
    assert any("lint" in line for line in contract.differences(before, after))


def test_the_answer_schema_is_the_surface(tmp_path: Path) -> None:
    """Схема ответа — тоже поверхность: по ней потребитель пишет свой файл."""
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(
        tree(tmp_path / "after", answer=ANSWER.replace("schema: 4", "schema: 5"))
    )
    assert any("схема" in line for line in contract.differences(before, after))


# --- диапазон совместимости ---------------------------------------------------


@pytest.mark.parametrize(
    ("span", "version", "fits"),
    [
        (">=0.1,<0.2", "0.1.4", True),
        (">=0.1,<0.2", "0.1.99", True),
        (">=0.1,<0.2", "0.2.0", False),
        (">=0.1,<0.2", "0.0.9", False),
        (">=1.0,<2.0", "1.9.0", True),
    ],
)
def test_the_range_decides_by_major_minor(span: str, version: str, fits: bool) -> None:
    """Сравниваются MAJOR.MINOR: патч поверхности не трогает по построению.

    Требовать совпадения патча значило бы тревожить потребителя выпуском,
    который его не касается, — и канал перестали бы читать.
    """
    assert policy.compatible(span, version) is fits


@pytest.mark.parametrize(
    "span", [">=0.1", "0.1", ">=0.1,<=0.2", "любая", "", ">0.1,<0.2"], ids=lambda s: s or "пусто"
)
def test_a_range_without_an_upper_bound_is_refused(span: str) -> None:
    """Верхняя граница обязательна: без неё несовместимое применяется молча (073).

    Потребитель, объявивший только «не старше», однажды получает поверхность,
    о которой не знает, и узнаёт об этом красным на ровном месте.
    """
    with pytest.raises(policy.BadPolicy):
        policy.compatible(span, "0.1.4")


def test_an_answer_without_a_range_is_refused(tmp_path: Path) -> None:
    """Ответ без диапазона отвергается: «подходит любая» — молчание, а не состояние."""
    path = tmp_path / ".pipeline.yml"
    path.write_text("schema: 4\nchecks:\n  lint: required\n", encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="диапазон"):
        policy.load(path)


def test_a_contract_outside_the_range_is_refused(tmp_path: Path) -> None:
    """Контракт вне диапазона — красное, и оно зовёт перечитать ответы (157).

    Не «подвинь границу»: механическое поднятие числа оставляет ненужный обход
    жить вечно, а смысл перечитывания ровно в том, чтобы его снять.
    """
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    path = tmp_path / ".pipeline.yml"
    path.write_text(ANSWER, encoding="utf-8")
    with pytest.raises(policy.BadPolicy, match="перечитайте ответы"):
        policy.load(path)


# --- сам гейт -----------------------------------------------------------------


def test_the_project_answer_declares_its_range() -> None:
    """Ответ САМОГО проекта несёт диапазон, а не только подделки (075)."""
    text = (ROOT / ".pipeline.yml").read_text(encoding="utf-8")
    assert "contract:" in text, "проект не объявил, с каким контрактом он совместим"


def test_the_gate_shows_the_surface(run_script: RunScript) -> None:
    """Снимок можно посмотреть глазами: иначе спор «что тут контрактного» нечем закрыть."""
    run = run_script("check_contract.py", "--show")
    assert run.code == 0, run.text
    assert "workflows" in run.text and "answer" in run.text


def test_the_gate_is_declared_required() -> None:
    """Гейт объявлен держащим слияние: правка поверхности ломает потребителя молча."""
    checks = policy.load()
    assert checks["contract"].klass == policy.REQUIRED


#: Что документ обязан назвать, говоря о поверхности, — по одному слову на род
#: снимка. Слово, а не фраза: проза правится, состав снимка — нет.
SURFACE_WORDS = {
    "jobs": "джоб",
    "events": "событ",
    "inputs": "вход",
    "checks": "проверок",
}


def test_the_release_doc_names_the_same_surface_as_the_mechanism() -> None:
    """Список поверхности в договоре о выпуске — один и сверен с механизмом.

    Прежде их было два подряд, перекрывающихся: «имена шагов и их входы» рядом
    с «имена джобов» и «входы ручного запуска», «форма .pipeline.yml» рядом с
    «имена проверок в .pipeline.yml». Первый список к тому же говорил о ШАГАХ,
    а снимок берёт джобы — то есть документ противоречил и себе, и
    `contract.py`. Нашёл разбор на #108.
    """
    text = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    head = text.index("В снимок входит")
    said = text[head : text.index("\n\n", text.index("- ", head) + 200)]
    for field, word in SURFACE_WORDS.items():
        assert word in said.lower(), f"поверхность не названа по роду «{field}»"
    assert "имена шагов" not in said, "шаг — термин договора, а снимок берёт джобы"
    assert said.count("`.pipeline.yml`") == 1, "ответ проекта назван в списке дважды"


# --- несовместимое объявляет переход -----------------------------------------


def test_a_removed_job_is_a_breaking_change() -> None:
    """Удалённый джоб ломает потребителя, добавленный — нет.

    Имя джоба потребитель держит в защите ветки ДОСЛОВНО: удалённое превращает
    её в вечное ожидание контекста, которого никто не выдаст. Добавленного он
    может не заметить и ничего не потерять — требовать перехода от обоих значило
    бы объявлять миграцию на каждое расширение (051).
    """
    assert contract.breaking(["ci.yml: джобов не стало — ['test']"])
    assert not contract.breaking(["ci.yml: добавлены джобы — ['drift']"])


def test_a_changed_answer_schema_is_breaking() -> None:
    """Смена схемы ответа ломает всех: по ней потребитель отвечает."""
    assert contract.breaking(["схема ответа: 2 → 3"])


def test_a_new_run_is_not_breaking() -> None:
    """Новый прогон ничего у потребителя не отнимает."""
    assert not contract.breaking(["drift.yml: новый прогон, джобы ['drift']"])


def test_a_fragment_without_a_migration_is_not_enough(tmp_path: Path) -> None:
    """У несовместимой правки фрагмент обязан назвать переход, а не факт.

    «Поверхность изменилась» — это сообщение о погоде: потребитель живёт на
    своей версии, и миграция идёт ОТ НЕЁ, а не от нуля (114).
    """
    said = tmp_path / "a.contract.md"
    said.write_text("Поверхность изменилась, обновите механизмы.\n", encoding="utf-8")
    assert gate.migration_named([said]) is False


def test_a_fragment_that_names_what_was_is_enough(tmp_path: Path) -> None:
    """Названо «было → стало» — этого достаточно, форма прозы не диктуется."""
    said = tmp_path / "a.contract.md"
    said.write_text("Джоб `test-matrix` переименован: было `matrix`.\n", encoding="utf-8")
    assert gate.migration_named([said]) is True


def test_the_word_was_alone_is_not_a_transition(tmp_path: Path) -> None:
    """«Было» в одиночку переходом НЕ является — это частое слово прозы.

    «Раньше это было неудобно» проходило гейт, не сказав потребителю ничего.
    Переход называет обе стороны: что было И что стало. Нашёл внешний взгляд на
    #142; закреплено здесь, иначе послабление вернулось бы молча
    ([114](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/114-migrate-from-the-current-version-not-from-zero.md)).
    """
    said = tmp_path / "a.contract.md"
    said.write_text("Раньше это было неудобно, теперь удобнее.\n", encoding="utf-8")
    assert gate.migration_named([said]) is False


def test_the_pair_was_and_became_is_a_transition(tmp_path: Path) -> None:
    """Пара «было … стало» переход называет — обе стороны на месте."""
    said = tmp_path / "a.contract.md"
    said.write_text("было: `matrix`\nстало: `test-matrix`\n", encoding="utf-8")
    assert gate.migration_named([said]) is True


def test_every_single_word_mark_names_a_transition_by_itself() -> None:
    """Каждая одиночная примета перехода что-то говорит о ПРЕЖНЕМ состоянии.

    Список одиночных примет — утверждение «этого слова достаточно», и проверять
    его надо каждым словом, а не первым: ровно так в списке и осталось «было»,
    которого достаточно НЕ было (145).
    """
    for mark in gate.MIGRATION_MARKS:
        assert mark not in {"было", "стало"}, (
            f"«{mark}» одиночной приметой быть не может: слово называет одну "
            "сторону перехода, и в прозе встречается само по себе"
        )


def test_the_gate_declares_the_third_outcome_when_files_are_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ чтения тронутых файлов — третий исход, а не «нашёл находки».

    `declared()` зовут уже ПОСЛЕ разбора поверхности, где перехват позади:
    необработанное исключение вышло бы кодом 1 — «гейт нашёл находки», — хотя
    гейт не отработал вовсе (039). Правка приехала без регрессионного теста;
    нашёл внешний взгляд на #159.
    """

    def falls(*_: object, **__: object) -> list[str]:
        raise gate.journal.NotRun("дерева базы нет")

    monkeypatch.setattr(gate.journal, "changed_files", falls)
    with pytest.raises(gate.NotRun, match="не прочитаны"):
        gate.declared("origin/main")


# --- что гейт обязан назвать НЕСОВМЕСТИМЫМ -----------------------------------


def changed(tmp_path: Path, *, workflow: str | None = WORKFLOW, answer: str = ANSWER) -> list[str]:
    """Различия поверхности между образцом и правкой."""
    before = contract.surface(tree(tmp_path / "before"))
    after = contract.surface(tree(tmp_path / "after", workflow=workflow, answer=answer))
    found: list[str] = contract.differences(before, after)
    return found


def test_a_removed_check_is_breaking(tmp_path: Path) -> None:
    """Снятая проверка — несовместимая правка, а не «класс изменился».

    Потребитель держит её имя в защите ветки ДОСЛОВНО, и защита начинает ждать
    контекста, которого никто не выдаст. Примета была в списке и раньше —
    словами «проверки не стало», — но таких слов не печатал никто: снятие
    выходило строкой «проверка «x»: required → —» и проходило мимо списка.
    МЁРТВАЯ ПРИМЕТА ХУЖЕ ОТСУТСТВУЮЩЕЙ: список выглядел полным. Нашёл внешний
    взгляд на #142.
    """
    changes = changed(tmp_path, answer='schema: 4\ncontract: ">=0.1,<0.2"\nchecks: {}\n')
    assert changes, "снятие проверки не замечено вовсе"
    assert contract.breaking(changes), f"снятие не названо несовместимым: {changes}"


def test_an_added_check_is_not_breaking(tmp_path: Path) -> None:
    """Добавленную проверку потребитель может не заметить и не потерять ничего.

    Требовать миграцию от каждого расширения значит приучить писать её
    формально (051).
    """
    answer = 'schema: 4\ncontract: ">=0.1,<0.2"\nchecks:\n  lint: required\n  test: required\n'
    changes = changed(tmp_path, answer=answer)
    assert changes and not contract.breaking(changes), changes


def test_a_removed_event_is_breaking(tmp_path: Path) -> None:
    """Снятое событие превращает работающий шаг в молчащий.

    Снаружи это неотличимо от «шаг сломался»: прежде обе стороны — снятие и
    добавление — накрывались одной строкой «события или входы изменились», и
    несовместимое проходило как расширение.
    """
    without = WORKFLOW.replace("  pull_request:\n    types: [opened]\n", "")
    changes = changed(tmp_path, workflow=without)
    assert contract.breaking(changes), f"снятие события не названо несовместимым: {changes}"


def test_a_removed_event_type_is_breaking(tmp_path: Path) -> None:
    """Снятый ТИП события — то же самое, только тише."""
    narrowed = WORKFLOW.replace("    types: [opened]", "    types: []")
    changes = changed(tmp_path, workflow=narrowed)
    assert contract.breaking(changes), f"снятие типа не названо несовместимым: {changes}"


def test_an_added_event_is_not_breaking(tmp_path: Path) -> None:
    """Добавленное событие — расширение: шаг сработает чаще, ломаться нечему."""
    wider = WORKFLOW.replace("  workflow_dispatch:", "  push:\n  workflow_dispatch:")
    changes = changed(tmp_path, workflow=wider)
    assert changes and not contract.breaking(changes), changes


def test_a_newly_required_input_is_breaking(tmp_path: Path) -> None:
    """Вход, ставший обязательным, отвергает существующий вызов кнопки.

    И новый обязательный ломает так же, как ужесточённый: у потребителя кнопка
    вызывается без него.
    """
    tightened = WORKFLOW.replace(
        '      pr:\n        description: "номер"\n        required: true\n        type: string\n',
        '      pr:\n        description: "номер"\n        required: true\n        type: string\n'
        '      why:\n        description: "зачем"\n        required: true\n        type: string\n',
    )
    changes = changed(tmp_path, workflow=tightened)
    assert contract.breaking(changes), f"новый обязательный вход не назван: {changes}"


def test_a_loosened_input_is_not_breaking(tmp_path: Path) -> None:
    """Послабление видно, но не ломает: прежний вызов остаётся верным."""
    loosened = WORKFLOW.replace("required: true", "required: false")
    changes = changed(tmp_path, workflow=loosened)
    assert changes and not contract.breaking(changes), changes


#: Вход кнопки в образце и второй такой же — чтобы подделки не собирали одну и
#: ту же строку по частям в двух местах (090).
INPUT_PR: Final = (
    '      pr:\n        description: "номер"\n        required: true\n        type: string\n'
)
INPUT_WHY: Final = (
    '      why:\n        description: "зачем"\n        required: true\n        type: string\n'
)

#: Подделанные правки, каждая — ОДИН род несовместимого изменения. Список
#: закрытый и служит двум целям: проверить, что каждая примета действительно
#: печатается, и что печатает её именно этот род правки.
PLANTED: Final[dict[str, dict[str, Any]]] = {
    "джоб снят": {
        "workflow": lambda text: text.replace("  lint:\n    name: lint\n    steps: []\n", "")
    },
    "проверка снята": {"answer": 'schema: 4\ncontract: ">=0.1,<0.2"\nchecks: {}\n'},
    # Прогона нет вовсе: без этого случая примета «прогон удалён» не печаталась
    # НИКЕМ — и тест, проверяющий приметы поведением, назвал это сразу.
    "прогон снят": {"workflow": None},
    "схема ответа": {"answer": 'schema: 5\ncontract: ">=0.1,<0.2"\nchecks:\n  lint: required\n'},
    "событие снято": {
        "workflow": lambda text: text.replace("  pull_request:\n    types: [opened]\n", "")
    },
    "тип события снят": {
        "workflow": lambda text: text.replace("    types: [opened]", "    types: []")
    },
    "вход снят": {
        "workflow": lambda text: text.replace(INPUT_PR, ""),
    },
    "вход стал обязательным": {
        "workflow": lambda text: text.replace(INPUT_PR, INPUT_PR + INPUT_WHY),
    },
}


def _planted_workflow(edit: dict[str, Any]) -> str | None:
    """Прогон подделки: правка образца, снятие целиком или образец как есть."""
    if "workflow" not in edit:
        return WORKFLOW
    asked = edit["workflow"]
    return None if asked is None else str(asked(WORKFLOW))


def _planted_answer(edit: dict[str, Any]) -> str:
    """Ответ проекта в подделке — правленый либо образцовый."""
    return str(edit.get("answer") or ANSWER)


def planted_lines(tmp_path: Path) -> list[str]:
    """Все строки различий, которые механизм печатает на подделанных правках."""
    said: list[str] = []
    for name, edit in PLANTED.items():
        said += changed(
            tmp_path / name, workflow=_planted_workflow(edit), answer=_planted_answer(edit)
        )
    return said


def test_every_breaking_mark_is_actually_printed(tmp_path: Path) -> None:
    """У каждой приметы несовместимого есть ПРАВКА, на которой она печатается.

    Мёртвая примета — худший вид полноты: список выглядит закрытым, а строка,
    которую он ждёт, не появляется ни при каком изменении. Ровно это и было с
    «проверки не стало» (075).

    ПРОВЕРЯЕТСЯ ПОВЕДЕНИЕМ, А НЕ ТЕКСТОМ ФАЙЛА. Первая попытка искала приметы
    подстрокой в исходнике `contract.py` — и не могла упасть: сами приметы там
    же и перечислены, так что каждая находила себя. Гейт, который не способен
    отказать, — тот самый дефект, который этим изменением и чинится. Нашёл
    внешний взгляд на #242
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    said = planted_lines(tmp_path)
    orphans = [mark for mark in contract.BREAKING_MARKS if not any(mark in line for line in said)]
    assert not orphans, (
        f"приметы, которых не печатает ни одна подделанная правка: {orphans}. "
        f"Напечатано было:\n  " + "\n  ".join(sorted(set(said)))
    )


def test_the_planted_edits_are_each_breaking(tmp_path: Path) -> None:
    """Каждая подделанная правка признаётся несовместимой — по отдельности.

    Без этого список подделок мог бы держаться одной правкой, накрывающей все
    приметы разом, и «каждый род проверен» стало бы неправдой (145).
    """
    for name, edit in PLANTED.items():
        changes = changed(
            tmp_path / f"one-{name}",
            workflow=_planted_workflow(edit),
            answer=_planted_answer(edit),
        )
        assert contract.breaking(changes), f"«{name}» не признано несовместимым: {changes}"
