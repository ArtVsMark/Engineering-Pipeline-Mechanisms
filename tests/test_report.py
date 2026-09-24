"""Обрезка вывода: сказать, что урезано, и насколько.

Молчаливая обрезка выглядит как полный ответ — читатель ищет причину в первых
трёхстах знаках, когда она в четырёхсот первом. Копий обрезки было четыре, у
каждого механизма своя; здесь проверяется и поведение, и то, что копия одна.
"""

from __future__ import annotations

import ast
from typing import Final

import pytest
import report
import yaml

from tests.conftest import ROOT, load_script, walk

runs_series = load_script("runs_series.py")

SCRIPTS = ROOT / "scripts"


def test_short_text_is_left_alone() -> None:
    """Короткий вывод не трогают: обрезки не было — и говорить не о чем."""
    assert report.cut("коротко") == "коротко"


def test_long_text_says_how_much_was_cut() -> None:
    """Урезанный вывод называет полный объём, а не ставит многоточие."""
    cut = report.cut("я" * 400)
    assert cut.endswith("(обрезано, всего 400 знаков)")
    assert len(cut) < 400 + 40


def test_the_limit_is_the_boundary_not_a_suggestion() -> None:
    """На самой границе обрезки нет: 300 знаков — ещё полный ответ."""
    assert report.cut("я" * report.LIMIT) == "я" * report.LIMIT


def test_no_mechanism_cuts_output_silently() -> None:
    """Гейт на дрейф: срез строки-вывода не пишут заново в каждом механизме.

    Копий было четыре — шаг открытия, гейт журнала, транспорт и сборка тела
    уплотнения, — и каждая обрезала молча. Разошлись бы они так же молча.
    """
    for path in walk(SCRIPTS, "*.py"):
        if path.name == "report.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
                continue
            upper = node.slice.upper
            if (
                isinstance(upper, ast.Constant)
                and isinstance(upper.value, int)
                and upper.value >= 100
            ):
                raise AssertionError(f"{path.name}: вывод режется на месте, а не общим механизмом")


def test_the_mode_prefix_speaks_in_the_diagnostic_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Приставка режима идёт в `stderr`, а не в ответ механизма.

    ЭТО ПРО ПОТОК, А НЕ ПРО ТЕКСТ. У части механизмов `stdout` читает не
    человек, а оболочка: шаг взгляда берёт очередь как
    ``numbers=$(python scripts/unlooked.py --queue)``. Приставка на том же
    потоке давала ВТОРУЮ строку, обе уезжали в `$GITHUB_OUTPUT`, площадка
    отвечала ``Invalid format '[]'`` и роняла джоб — 18 и 19.09.2026.
    """
    report.announce(True)
    said = capsys.readouterr()
    assert report.DRY in said.err, "приставка режима не названа вовсе (045)"
    assert said.out == "", f"приставка режима попала в ответ механизма: {said.out!r}"


def test_a_live_run_names_nothing_in_either_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Вторая половина: боевой заход молчит в ОБОИХ потоках.

    Без неё проверка прошла бы и у приставки, стоящей всегда, — а такая ничего
    не различает (051).
    """
    report.announce(False)
    said = capsys.readouterr()
    assert said.out == "" and said.err == ""


#: Как оболочка сливает `stderr` в `stdout`: `2>&1`, `&>` и `|&`. Последний
#: разбор команд режет по черте, и от него остаётся команда, начатая с `&`.
MERGES: Final = ("2>&1", "&>")


def merges_streams(command: str) -> bool:
    """Сливает ли команда оба потока в один."""
    return any(one in command for one in MERGES) or command.startswith("&")


def run_steps() -> list[tuple[str, list[str]]]:
    """Все шаги прогонов с их командами — комментарии вынуты."""
    found: list[tuple[str, list[str]]] = []
    for path in walk(ROOT / ".github" / "workflows", "*.yml"):
        for job, body in (
            yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}
        ).items():
            for step in body.get("steps") or []:
                said = runs_series.commands(str(step.get("run") or ""))
                where = f"{path.name}:{job} «{step.get('name')}»"
                found.append((where, said))
    return found


def test_a_step_writing_its_outputs_never_merges_the_streams() -> None:
    """Шаг, пишущий в `$GITHUB_OUTPUT`, не сливает потоки ни в одной команде.

    Механизм разводит потоки сам (`report.announce` пишет в `stderr`), и
    шаг прогона не вправе слить их обратно. Замер 23.09.2026: ровно так
    верификатор взгляда отвечал «Invalid format» на каждом запуске — `2>&1`
    увозил приставку пробного захода в выходы шага (#673).

    СУДИТСЯ ШАГ, А НЕ ФОРМА ЗАПИСИ. Прежняя редакция ловила одну — файл
    `>"$ИМЯ" 2>&1` и затем `cat "$ИМЯ" >> "$GITHUB_OUTPUT"`; переменная
    `x=$(cmd 2>&1)` с `echo "k=$x"`, скобки `{ …; } 2>&1`, `|& tee` и
    прямое `cmd >> "$GITHUB_OUTPUT" 2>&1` проходили (`9a59aa8`). Проследить
    поток до выходов по всем формам оболочки нельзя, а шаг, пишущий выходы,
    сливать потоки не обязан ни для чего — поэтому запрет на весь шаг.
    Комментарии вынуты тем же разбором, что у счёта цены прогонов.

    Замер 24.09.2026: шагов в прогонах 187, пишущих выходы — 12, сливающих
    потоки — 15, и оба сразу — ни одного. Слова `2>&1` и `GITHUB_OUTPUT`
    вместе стоят в одном шаге, и `2>&1` там — только в комментарии.

    ГРАНИЦА: слияние, собранное из частей (`exec 2>&1` в начале шага тоже
    ловится, а переменная с текстом `2>&1` — нет), машина не видит (057).
    """
    steps = run_steps()
    writing = [(where, said) for where, said in steps if any("GITHUB_OUTPUT" in c for c in said)]
    assert writing, "шагов, пишущих $GITHUB_OUTPUT, нет — предмет проверки исчез (075)"
    merging = [where for where, said in steps if any(merges_streams(c) for c in said)]
    assert merging, "шагов со слиянием потоков нет вовсе — вторая половина проверки пуста (075)"
    found = [where for where, said in writing if any(merges_streams(c) for c in said)]
    assert not found, "шаг пишет выходы и сливает потоки: " + "; ".join(found)
