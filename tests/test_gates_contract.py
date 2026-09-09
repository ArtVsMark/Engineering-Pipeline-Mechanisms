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
    rows = re.findall(
        r"^\|\s*\d+[a-z]?\s*\|.*$", CONTRACT.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert rows, "в договоре не нашлось таблицы шагов — предмет сверки отсутствует"
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


def test_label_events_reach_the_gates() -> None:
    """Разметка — вход механизма, значит её правка обязана менять вердикт."""
    # `on:` — булев ключ, см. load_gates.
    triggers = load_gates()[True]["pull_request"]["types"]
    assert {"labeled", "unlabeled"} <= set(triggers)
