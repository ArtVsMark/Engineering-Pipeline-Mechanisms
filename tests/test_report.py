"""Обрезка вывода: сказать, что урезано, и насколько.

Молчаливая обрезка выглядит как полный ответ — читатель ищет причину в первых
трёхстах знаках, когда она в четырёхсот первом. Копий обрезки было четыре, у
каждого механизма своя; здесь проверяется и поведение, и то, что копия одна.
"""

from __future__ import annotations

import ast
import re

import pytest
import report
import yaml

from tests.conftest import ROOT, walk

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


#: Файл, собранный из ОБОИХ потоков: `>"$ИМЯ" 2>&1`.
MERGED_RE = re.compile(r'>\s*"\$\{?(?P<name>[A-Za-z_]+)\}?"\s*2>&1')
#: Файл, отправленный в выходы шага: `cat "$ИМЯ" >> "$GITHUB_OUTPUT"`.
TO_OUTPUT_RE = re.compile(r'cat\s+"\$\{?(?P<name>[A-Za-z_]+)\}?"\s*>>\s*"\$GITHUB_OUTPUT"')


def test_a_file_sent_to_the_step_outputs_carries_only_the_answer() -> None:
    """Файл, уходящий в `$GITHUB_OUTPUT`, не собирается из обоих потоков.

    Механизм разводит потоки сам (`report.announce` пишет в `stderr`), и
    шаг прогона не вправе слить их обратно. Замер 23.09.2026: ровно так
    верификатор взгляда отвечал «Invalid format» на каждом запуске — `2>&1`
    увозил приставку пробного захода в выходы шага (#673). В дереве такое
    место было одно.
    """
    found: list[str] = []
    for path in walk(ROOT / ".github" / "workflows", "*.yml"):
        for job, body in (
            yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}
        ).items():
            for step in body.get("steps") or []:
                run = str(step.get("run") or "")
                merged = {m["name"] for m in MERGED_RE.finditer(run)}
                sent = {m["name"] for m in TO_OUTPUT_RE.finditer(run)}
                if merged & sent:
                    names = ", ".join(sorted(merged & sent))
                    found.append(f"{path.name}:{job} «{step.get('name')}»: {names}")
    assert not found, "в выходы шага уходит файл из обоих потоков: " + "; ".join(found)
