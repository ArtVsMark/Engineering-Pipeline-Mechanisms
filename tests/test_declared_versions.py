"""Версия, объявленная в дереве, живёт в одном месте — и это МЕРЯЕТСЯ.

Правило 035 обобщает себя своей же применимостью: «любое значение,
дублирующееся по необходимости… поддерживаемые версии зависимостей. Один
источник плюс проверка»
([035](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/035-version-is-never-edited-by-hand.md)).
У проекта этих значений два рода, и оба вписаны руками десятки раз.

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Версия истолкователя стояла в
шагах прогонов **30 раз в 18 объявлениях**; границы `pyyaml` — 23 раза,
`pytest` — 6. Проверка была ровно на ДВУХ джобах `ci.yml` (версии берутся из
матрицы, `tests/test_drift.py`), остальные тридцать не держались ничем. Уход
пола вперёд оставил бы отставший шаг зелёным на старом истолкователе — то
расхождение, которое правило называет обнаруживаемым «после публикации».

ЧТО ЗДЕСЬ НЕ ЗАВОДИТСЯ ЗАНОВО. Разбор строк установки уже написан и живёт у
`check_env.py`: `needs()` читает границы инструментов из прогонов и сама
отвергает одно имя, объявленное по-разному. Второй такой разбор разошёлся бы с
первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
Не хватало не разбора, а **места прогона**: `check_env.py` — гейт ОКНА, его не
зовёт ни один прогон площадки, и до сегодня расхождение границ краснело только
у того, кто запустит сверку руками. Набор идёт в конвейере — здесь этот разбор
и ставится на площадку
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ГРАНИЦА НАЗВАНА, А НЕ ВЫРОВНЕНА. Ячейки матрицы (`3.12`, `3.13`, `3.14`,
предрелизная `3.15`) — НЕ дубли пола: матрица гоняет набор на нескольких
версиях нарочно, и держит её `tests/test_drift.py`. Предмет здесь другой —
версия, вписанная в ОДИНОЧНЫЙ шаг, где выбора нет и подразумевается пол
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, load_script

env = load_script("check_env.py")
paths = load_script("paths.py")

WORKFLOWS: Final = ROOT / paths.WORKFLOWS

#: Значение, взятое из матрицы, а не вписанное: `${{ matrix.python }}`.
FROM_MATRIX: Final = "matrix."


def declared_versions() -> list[tuple[str, str, str]]:
    """Все `python-version` шагов: объявление, имя джоба, значение.

    Читается разбором YAML, а не подстрокой по тексту: «шаг ставит версию» —
    отношение, и присутствие строки его не доказывает
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    """
    found: list[tuple[str, str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job, body in (document.get("jobs") or {}).items():
            for step in (body or {}).get("steps") or []:
                said = ((step or {}).get("with") or {}).get("python-version")
                if said is not None:
                    found.append((path.name, str(job), str(said)))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    assert WORKFLOWS.is_dir(), f"нет {WORKFLOWS}: предмет сверки не найден"
    assert declared_versions(), "ни один шаг не ставит версию истолкователя — сверять нечего"


def test_every_hand_written_language_version_is_the_declared_floor() -> None:
    """Версия, вписанная в одиночный шаг, равна полу `requires-python`.

    Выбора у одиночного шага нет: он ставит «ту самую» версию, и какая она —
    объявлено один раз, в `pyproject.toml`. Вписанная рядом копия этого числа
    отстанет молча, и узнают об этом не здесь, а на шаге, который продолжит
    работать на старом истолкователе.
    """
    major, minor = env.python_floor(ROOT)
    floor = f"{major}.{minor}"
    wrong = [
        f"{name}:{job} ставит {said}, а пол дерева — {floor}"
        for name, job, said in declared_versions()
        if FROM_MATRIX not in said and said != floor
    ]
    assert not wrong, "версия истолкователя разошлась с объявленным полом (035):\n  " + "\n  ".join(
        wrong
    )


def test_a_matrix_cell_is_not_counted_as_a_duplicate() -> None:
    """Граница гейта названа замером: матричные шаги есть, и они не предмет.

    Довод «матрица — не дубль» держится тем, что матричные шаги в дереве
    действительно есть. Исчезнут они — довод станет пустым, и это увидит
    проверка, а не читатель докстроки
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    from_matrix = [one for one in declared_versions() if FROM_MATRIX in one[2]]
    assert from_matrix, "ни один шаг не берёт версию из матрицы — довод про границу пуст"


def test_one_tool_is_bounded_the_same_way_everywhere() -> None:
    """Границы инструмента совпадают во всех прогонах — РАЗБОРОМ, а не глазом.

    Сам разбор живёт у `check_env.py` и отвергает расхождение отказом. Здесь он
    ставится на площадку: гейт окна на площадке не идёт, и до этой проверки
    разошедшиеся границы краснели только у того, кто запустит сверку руками.
    """
    try:
        found = env.needs(ROOT)
    except env.NotRun as отказ:  # pragma: no cover — ветка прогоняется откатом
        pytest.fail(f"границы инструментов разошлись между прогонами (035, 022): {отказ}")
    assert found, "в прогонах нет ни одной строки установки — предмет сверки не найден (075)"


def test_every_tool_declares_an_upper_bound() -> None:
    """У каждой объявленной границы есть ВЕРХ: иначе местный вердикт ничего не значит.

    Правило 073 требует верхнего предела у инструмента, чей вердикт сравнивают
    между машинами: без него `ruff` мажорной версией вперёд находит другое, и «у
    меня локально чисто» перестаёт предсказывать сборку
    ([073](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/073-tool-version-from-one-source-with-an-upper-bound.md)).

    ЗАМЕР 18.09.2026: верх есть у всех пяти объявленных требований — то есть
    требование исполнялось и не держалось ничем. Добавленное шестым «requests>=2»
    не покраснело бы нигде
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

    ГРАНИЦА НАЗВАНА ЗАМЕРОМ, А НЕ ОБОЙДЕНА. Само правило исключает библиотеки
    времени выполнения: там верхний предел мешает получать исправления
    безопасности. Таких у нас **ноль** — все пять либо зовутся командой в прогоне
    (`ruff`, `mypy`, `pytest`), либо меняют вердикт набора (`pytest-randomly`
    задаёт порядок сбора), либо читают объявления самих механизмов (`pyyaml`).
    Поэтому предикат здесь ОДИН на всех, а не список избранных: появится первая
    библиотека времени выполнения — предикат придётся разделить, и отказ гейта
    говорит об этом сам, вместо того чтобы звать снять проверку
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md),
    [104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md)).
    """
    open_ended = [
        f"{need.name} объявлен как «{need.bounds or '—'}» в {need.where}"
        for need in env.needs(ROOT).values()
        if "<" not in need.bounds
    ]
    assert not open_ended, (
        "объявленная версия без верхней границы (073):\n  "
        + "\n  ".join(open_ended)
        + "\n  Инструменту, чей вердикт сравнивают между машинами, верх обязателен."
        + "\n  Если это библиотека времени выполнения — верх мешает ей получать"
        + " исправления безопасности:\n  разделите предикат и назовите исключение,"
        + " а не снимайте проверку."
    )
