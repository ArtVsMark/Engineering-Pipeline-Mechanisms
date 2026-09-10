"""Работа въезжает в общую ветку уплотнением, и никак иначе.

РЕШЕНИЕ 006 ГОВОРИТ «УПЛОТНЕНИЕМ», А ДЕРЖАЛОСЬ ОНО НИЧЕМ. Наш шаг 8 сливает
уплотнением и составляет тело сам — трейлеры доезжают до первопредка. Но
слияние может пройти и мимо очереди: у площадки есть своя кнопка авто-мержа, и
включённая на изменении она сливает **обычным мержем**. Тело такого коммита
составляет площадка, трейлеров оно не несёт, и переписать это нечем — история
общей ветки не правится.

Замер 10.09.2026: изменение #154 уехало именно так. Атрибуция в итоговой
истории сломалась, прогон `attribution-history` покраснел, а вместе с ним и
общая ветка — на пустом месте, потому что работа была здоровой.

Гейт смотрит ПЕРВОПРЕДКОВ после объявленной отметки: тема вида «Merge pull
request #N» означает, что уплотнения не было. Отметка та же, что у прогона
атрибуции, и берётся она оттуда же — второй список того же разошёлся бы с
первым молча (022).
"""

from __future__ import annotations

import re
import subprocess
from typing import Final

import pytest
import yaml

from tests.conftest import ROOT

#: Прогон, из которого берётся объявленная отметка.
RUN: Final = ROOT / ".github" / "workflows" / "attribution-history.yml"
#: Тема коммита, которую составляет площадка при обычном мерже.
PLATFORM_MERGE_RE: Final = re.compile(r"^Merge pull request #\d+ from ")


def boundary() -> str:
    """Объявленная отметка — из прогона атрибуции, а не из второго списка."""
    run = yaml.safe_load(RUN.read_text(encoding="utf-8"))
    for job in run["jobs"].values():
        for step in job["steps"]:
            if "attribution@" in str(step.get("uses", "")):
                return str(step["with"]["since"]).strip()
    raise AssertionError(f"в {RUN.name} нет шага атрибуции — отметку взять неоткуда (075)")


def first_parents(since: str) -> list[tuple[str, str]]:
    """Первопредки общей ветки после отметки парами «отпечаток, тема»."""
    for ref in ("origin/main", "main", "HEAD"):
        done = subprocess.run(
            ["git", "log", "--first-parent", "--format=%h|%s", f"{since}..{ref}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if done.returncode == 0:
            return [
                (line.split("|", 1)[0], line.split("|", 1)[1])
                for line in done.stdout.splitlines()
                if "|" in line
            ]
    return []


def test_no_platform_merge_after_the_boundary() -> None:
    """После отметки нет ни одного коммита обычного мержа.

    Это не вкус оформления: тело мерж-коммита составляет площадка, и трейлеров
    оно не несёт. Атрибуция ломается там, где переписать её уже нечем (123).
    """
    since = boundary()
    known = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", since], capture_output=True, check=False
    )
    if known.returncode:
        pytest.skip("отметка недоступна: обрезанный чекаут")
    merges = [
        f"{mark} {said}" for mark, said in first_parents(since) if PLATFORM_MERGE_RE.match(said)
    ]
    assert not merges, (
        "работа въехала в общую ветку обычным мержем, а не уплотнением: "
        + "; ".join(merges)
        + ". Так сливает авто-мерж площадки — его включают кнопкой на изменении, "
        "и он обходит очередь целиком (решение 006)"
    )


def test_the_gate_is_red_on_a_platform_merge() -> None:
    """Проверено тем, что гейт обязан отвергнуть (140)."""
    assert PLATFORM_MERGE_RE.match("Merge pull request #154 from ArtVsMark/agent/x")
    assert not PLATFORM_MERGE_RE.match("fix(gates): работа уехала уплотнением (#154)")
    assert not PLATFORM_MERGE_RE.match("Merge branch 'main' into agent/x")
