"""Дерево сверяется с договором о конвейере.

Настройка защиты ветки живёт вне дерева, и её расхождение с прогоном не видит
ни ревью, ни сам прогон. Единственное, что можно удержать здесь, — чтобы имена
в дереве и в договоре не разъезжались: тогда расхождение с площадкой сводится
к одному имени, а не к поиску по всем файлам.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
GATES = ROOT / ".github" / "workflows" / "ci.yml"
CONTRACT = ROOT / "docs" / "pipeline.md"
SUMMARY = "ci-complete"


def load_gates() -> dict[Any, Any]:
    """Читает описание гейтов.

    Ключи здесь не только строки: YAML 1.1 читает `on:` как булево `True`, и
    раздел событий лежит под этим ключом, а не под строкой «on». Тип словаря
    назван честно, чтобы это не всплыло на первой же правке теста.
    """
    document: dict[Any, Any] = yaml.safe_load(GATES.read_text(encoding="utf-8"))
    return document


def contract_jobs() -> set[str]:
    """Вынимает имена джобов из таблицы шагов договора."""
    # Номер шага бывает с буквой: `6a`, `12a` — подшаг того же шага скелета.
    # Без буквы в образце подшаг молча выпадал бы из сверки, и джоб, которого
    # нет в договоре, считался бы описанным.
    text = CONTRACT.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*\d+[a-z]?\s*\|.*$", text, re.MULTILINE)
    assert rows, "в договоре не нашлось таблицы шагов — предмет сверки отсутствует"

    # БУКВА ПОДШАГА — ЛАТИНСКАЯ, И ПРОВЕРЯЕТСЯ ЭТО ЗДЕСЬ. Кириллическая «а»
    # выглядит точно так же, строка молча выпадает из сверки, и джоб, которого
    # нет в договоре, считается описанным. Поймано на себе 10.09.2026: шаги
    # матрицы версий были записаны кириллицей и в сверку не попали (075).
    stray = re.findall(r"^\|\s*\d+[а-яё]\s*\|", text, re.MULTILINE | re.IGNORECASE)
    assert not stray, (
        f"номер подшага записан кириллицей: {stray} — такая строка выпадает "
        "из сверки молча, буква обязана быть латинской"
    )
    jobs: set[str] = set()
    for row in rows:
        cells = [cell.strip().strip("`*") for cell in row.split("|")]
        if len(cells) < 6 or cells[3] != "ci.yml":
            continue
        jobs.add(cells[4])
    return jobs


def test_jobs_match_the_contract() -> None:
    """Джобы дерева и джобы договора совпадают, а не «примерно соответствуют»."""
    assert set(load_gates()["jobs"]) == contract_jobs()


def test_summary_has_no_needs() -> None:
    """Сводный гейт собран опросом: `needs` превращает отказ соседа в пропуск."""
    assert "needs" not in load_gates()["jobs"][SUMMARY]


def test_job_name_equals_context_name() -> None:
    """Имя джоба и имя контекста совпадают: иначе в защите окажется имя-призрак."""
    for job_id, job in load_gates()["jobs"].items():
        assert job.get("name", job_id) == job_id, f"джоб {job_id} выдаёт другое имя контекста"


def test_summary_is_not_a_matrix() -> None:
    """Матричные имена в список обязательных не попадают никогда."""
    assert "strategy" not in load_gates()["jobs"][SUMMARY]


def test_summary_takes_its_subject_from_data() -> None:
    """Наполнение опроса приходит из данных проекта, а не из файла прогона.

    Список именами, вписанный в прогон, делает класс проверки свойством
    механизма. Он свойство проекта: у одного `e2e` обязателен, у другого
    невозможен, и подключение к общему конвейеру не должно требовать правки
    workflow.
    """
    step = load_gates()["jobs"][SUMMARY]["steps"][-1]["run"]
    assert "--policy" in step, "сводный джоб не называет, откуда берёт наполнение"
    assert "--required" not in step, "список именами в прогоне — это класс проверки в механизме"


def test_every_job_of_the_tree_is_answered() -> None:
    """По каждому джобу дерева есть ответ, а не только по обязательным."""
    checks = yaml.safe_load((ROOT / ".pipeline.yml").read_text(encoding="utf-8"))["checks"]
    assert set(load_gates()["jobs"]) - {SUMMARY} <= set(checks)


def test_summary_does_not_answer_for_itself() -> None:
    """Сводный гейт в ответе не объявляется: его класс задан построением."""
    checks = yaml.safe_load((ROOT / ".pipeline.yml").read_text(encoding="utf-8"))["checks"]
    assert SUMMARY not in checks


def test_the_shared_branch_is_checked_too() -> None:
    """Гейты идут и на общей ветке, а не только на изменении.

    Замер 09.09: на `main` не шло ни одной проверки, кроме публикации фактов.
    Два изменения, зелёных по отдельности, после слияния могли дать красное, и
    узнать об этом было неоткуда — а «красная общая ветка» стоит источником 0 в
    порядке работ. Источник без сигнала не источник.
    """
    triggers = load_gates()[True]
    assert "push" in triggers, "общая ветка не проверяется ничем"
    assert triggers["push"]["branches"] == ["main"]


#: Условие, которым объявляется «шаг идёт только на изменении». Сверяется
#: равенством, а не вхождением слова: подстрока «push» есть и у перевёрнутого
#: `== 'push'`, то есть у шага, который пойдёт ТОЛЬКО на общей ветке.
CHANGE_ONLY = "github.event_name != 'push'"


def runs_only_on_a_change(condition: str) -> bool:
    """Объявляет ли условие «этот шаг идёт только на изменении»."""
    return " ".join(condition.split()) == CHANGE_ONLY


def test_change_only_jobs_do_not_run_on_the_shared_branch() -> None:
    """Шаги, чей предмет — изменение, на общей ветке не идут.

    У них там нет предмета: разметки изменения, фрагмента относительно базы и
    вердикта по изменению на `main` не существует. Пропуск объявлен условием, а
    не молчаливым отказом внутри шага (154).

    Проверяется НАПРАВЛЕНИЕ условия, а не наличие в нём слова «push». Прежняя
    проверка искала подстроку и пропустила бы перевёрнутую полярность: шаг с
    `== 'push'` идёт ровно наоборот — только там, где предмета нет, — и такую
    подмену набор не заметил бы вовсе.

    На это условие опирается и очередь: `scripts/automerge.py` считает пропуск
    на общей ветке объявленным состоянием, а не краснотой, — и держится это
    именно здесь.
    """
    jobs = load_gates()["jobs"]
    for name in ("pr-meta", "journal", "attribution", SUMMARY):
        condition = str(jobs[name].get("if", ""))
        assert runs_only_on_a_change(condition), (
            f"{name}: условие «{condition}» не объявляет «только на изменении» — "
            f"ожидалось «{CHANGE_ONLY}»"
        )


def test_an_inverted_condition_would_be_caught() -> None:
    """Перевёрнутая полярность отвергается, а не проходит по вхождению слова.

    Гейт проверяется тем, что обязан отвергнуть (140): подстрока «push» есть в
    обоих условиях, и разводит их только направление.
    """
    assert runs_only_on_a_change("github.event_name != 'push'")
    assert not runs_only_on_a_change("github.event_name == 'push'")
    assert not runs_only_on_a_change("")


def test_label_events_reach_the_gates() -> None:
    """Разметка — вход механизма, значит её правка обязана менять вердикт."""
    # `on:` — булев ключ, см. load_gates.
    triggers = load_gates()[True]["pull_request"]["types"]
    assert {"labeled", "unlabeled"} <= set(triggers)


#: Программа, встроенная прямо в шаг прогона: оболочка меняет экранирование по
#: дороге, и один и тот же код в файле и в строке ведёт себя по-разному (013).
EMBEDDED_CODE_RE = re.compile(r"python3?\s+(?:-c\b|-\s*<<)|<<\s*['\"]?(?:PY|PYTHON|EOF_PY)")


def test_workflows_do_not_embed_code() -> None:
    """Логика зовётся файлом, а не встраивается строкой в шаг прогона (013).

    Escape-последовательности проходят через оболочку и меняются, а встроенный
    код вдобавок не виден ни линтеру, ни типизации, ни набору тестов: три гейта
    разом перестают его касаться.
    """
    embedded = [
        path.name
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        if EMBEDDED_CODE_RE.search(path.read_text(encoding="utf-8"))
    ]
    assert not embedded, f"код встроен в прогон, а не вызван файлом: {embedded}"


def test_branch_prefixes_match_the_workflow() -> None:
    """Приставка ветки — вход механизма, и она одна и та же у прогона и у скрипта.

    Разъехавшись, они дают худший из отказов: прогон стартует, скрипт отвечает
    «ветка без объявленной приставки» и выходит нулём — изменение не открыто, и
    красного нигде нет (003, 094).
    """
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "agent-pr.yml").read_text("utf-8"))
    # `on` в YAML читается как True: ключ приходится искать по обоим написаниям.
    triggers = workflow.get("on") or workflow.get(True)
    branches = list(triggers["push"]["branches"])

    source = (ROOT / "scripts" / "agent_pr.py").read_text(encoding="utf-8")
    declared = re.search(r"PREFIXES: Final = \(([^)]*)\)", source)
    assert declared, "в scripts/agent_pr.py не нашлось PREFIXES — предмет проверки не найден (075)"
    prefixes = re.findall(r'"([^"]+)"', declared.group(1))

    assert [f"{prefix}**" for prefix in prefixes] == branches, (
        f"приставки разъехались: прогон слушает {branches}, скрипт берёт {prefixes}"
    )
