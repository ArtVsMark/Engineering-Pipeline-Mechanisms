"""Список проверок, аннотаций или заданий читается до конца, а не первой страницей.

НАХОДКИ ВНЕШНЕГО ВЗГЛЯДА НА #675 (`771da9b`, `4b70f97`): источник дрейфа читал
проверки головы одной страницей в сто, а аннотации — страницей по умолчанию в
тридцать. Предупреждение за краем пропало бы молча.

ЗАМЕР ПО ДЕРЕВУ 23.09.2026, ДО ПОЧИНКИ: тот же приём стоял в ШЕСТИ вызовах
пяти шагов — `agent_pr` (проверки головы), `hail` и `stuck` (проверки
изменения), `runs_series` (аннотации упавшего задания), `drift` (оба списка);
плюс задания прогона в `runs_series` (страница в тридцать). На голове общей
ветки проверок под девяносто (518 на шесть голов) — до края страницы недалеко,
и шагнуть за него значит потерять красное или предупреждение без единой
строки. Общий обходчик `ghrest.paginate` в дереве давно есть.

ГРАНИЦА НАЗВАНА. Прочие списки, читаемые одной страницей, — намеренные
пределы: свежие N прогонов (`main_red`, `ci_complete`), изменения с одной
головы (`check_branch_revival`), сам постраничный помощник `ghrest`. На замере
их шесть, и судит их не этот гейт: первая страница там — вопрос, а не промах
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, walk

#: Списки, которые обязаны читаться до конца: проверки коммита, аннотации
#: проверки, задания прогона. Путь сверяется по концу — до `?` или конца строки:
#: одиночная проверка `check-runs/<id>` списком не является.
LIST_RE: Final = re.compile(r"/check-runs(?:\?|$)|/annotations(?:\?|$)|/jobs(?:\?|$)")

#: Где живут механизмы, ходящие к площадке.
PLACES: Final = (ROOT / "scripts", ROOT / "packages" / "transport")


def literal(node: ast.expr) -> str | None:
    """Путь запроса как текст: подстановки f-строки заменены на `{}`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "{}"
            for part in node.values
        )
    return None


def single_reads(path: Path) -> list[str]:
    """Вызовы `request(…)`, читающие список одним запросом: `файл:строка путь`.

    Имя вызова берётся и голым, и через точку: `ghrest.request(…)` и местная
    переменная `request = ask or ghrest.request` — одна и та же форма, и
    источник дрейфа стоял именно во второй.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", None))
        said = literal(node.args[1])
        if name == "request" and said and LIST_RE.search(said):
            found.append(f"{path.name}:{node.lineno} {said}")
    return found


@pytest.mark.parametrize(
    ("said", "list_read"),
    [
        ("repos/{}/commits/{}/check-runs?per_page=100", True),
        ("repos/{}/commits/{}/check-runs", True),
        ("repos/{}/check-runs/{}/annotations", True),
        ("repos/{}/actions/runs/{}/jobs", True),
        ("repos/{}/check-runs/{}", False),
        ("repos/{}/actions/jobs/{}", False),
        ("repos/{}/issues/{}/comments", False),
    ],
)
def test_the_predicate_tells_a_list_from_a_single_record(said: str, list_read: bool) -> None:
    """Обе половины предиката: список узнаётся, одиночная запись — нет."""
    assert bool(LIST_RE.search(said)) is list_read


def test_no_list_of_checks_annotations_or_jobs_is_read_one_page() -> None:
    """В дереве нет ни одного такого списка, прочитанного одним запросом."""
    scripts = [one for place in PLACES for one in walk(place, "*.py")]
    offenders = [line for path in scripts for line in single_reads(path)]
    assert not offenders, (
        "список читается одной страницей — всё за её краем пропадёт молча; "
        "читать через `ghrest.paginate`: " + "; ".join(offenders)
    )
