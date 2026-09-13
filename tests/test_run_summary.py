"""Шаг, который принимает решение, говорит о нём не только в лог.

ЧТО ЗДЕСЬ ПРЕДМЕТ. Лог прогона читается не из всякого окна: облачному
хранилище закрыто, и от захода остаётся код возврата, по которому не
разобрать ничего. Шаг, чей вывод — РАЗБОР (почему голова пропущена, кто
взведён, что признано пустым), обязан положить его туда, что отдаёт REST, —
в сводку джоба.

ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ПРИВЫЧКА. 13.09.2026 починку пустой головы нечем было
подтвердить: механизм отработал, а показать это было нечем — очередь свой
разбор в сводку не писала (#287). Правило прямое: механизм подтверждается
прогоном
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)),
а подтвердить нечем, если прогон молчит наружу.

Список разрешительный
([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)):
шаг попадает сюда осознанно. Сводку пишет не всякий — гейту довольно кода и
аннотации; здесь только те, чей вывод разбирают задним числом.
"""

from __future__ import annotations

from typing import Final

import pytest

from tests.conftest import ROOT

#: Прогоны, чей вывод — разбор решения, а не отметка «прошло».
SPEAKS_OUT: Final = ("automerge.yml", "ci-complete.yml")

SUMMARY: Final = "GITHUB_STEP_SUMMARY"


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_a_deciding_step_writes_its_reasoning_to_the_summary(run: str) -> None:
    """Разбор уходит в сводку джоба, а не только в лог."""
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert SUMMARY in text, (
        f"{run} печатает разбор только в лог: из окна, которому закрыто хранилище "
        "прогонов, от захода останется один код возврата"
    )


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_the_log_keeps_the_output_too(run: str) -> None:
    """Перенаправление в файл не уносит вывод из лога: `cat` возвращает его.

    Иначе сводка появляется ценой лога, и тот, у кого лог есть, теряет вывод.
    """
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert "cat " in text, f"{run} увёл вывод в файл и не вернул его в лог"
