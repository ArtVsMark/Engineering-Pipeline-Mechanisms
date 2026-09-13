"""Шаг, который принимает решение, говорит о нём не только в лог.

ЧТО ЗДЕСЬ ПРЕДМЕТ. Лог прогона читается не из всякого окна: облачному
хранилище закрыто, и от захода остаётся код возврата, по которому не
разобрать ничего. Шаг, чей вывод — РАЗБОР (почему голова пропущена, кто
взведён, что признано пустым), обязан сказать его туда, откуда его достанет
REST.

ДОСТАЁТ ИМЕННО АННОТАЦИЮ, И ЭТО ЗАМЕР, А НЕ ДОГАДКА. 13.09.2026 у джоба
`ci-complete` на изменении #290 REST отдаёт `annotations_count: 1`, а
`output.summary` — пустую строку. Сводка джоба остаётся для человека в окне
площадки; наружу говорит аннотация. Механизм, поставленный на сводку, читался
бы как работающий и не давал бы ничего (044).

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

#: Экранирование переводов строк для аннотации. Без него площадка обрежет
#: сообщение первым же переводом, и разбор снаружи станет одной строкой.
ESCAPED: Final = "%0A"


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_a_deciding_step_speaks_through_an_annotation(run: str) -> None:
    """Разбор уходит АННОТАЦИЕЙ — единственным, что отдаёт REST наружу."""
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert "::notice::" in text or "::error::" in text, (
        f"{run} печатает разбор только в лог и сводку: из окна, которому закрыто "
        "хранилище прогонов, от захода останется один код возврата"
    )
    assert ESCAPED in text, (
        f"{run} шлёт аннотацию без экранирования переводов строк — площадка обрежет "
        "разбор первой же строкой"
    )


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_a_deciding_step_also_fills_the_summary(run: str) -> None:
    """Сводка джоба остаётся: она для человека в окне площадки."""
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert SUMMARY in text, f"{run} не заполняет сводку джоба"


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_the_log_keeps_the_output_too(run: str) -> None:
    """Перенаправление в файл не уносит вывод из лога: `cat` возвращает его.

    Иначе сводка появляется ценой лога, и тот, у кого лог есть, теряет вывод.
    """
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert "cat " in text, f"{run} увёл вывод в файл и не вернул его в лог"
