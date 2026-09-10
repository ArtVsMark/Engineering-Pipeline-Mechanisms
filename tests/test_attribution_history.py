"""Объявленное начало отсчёта — коммит, а не дата.

Прогон `attribution-history` подключает гейт каталога и подаёт ему отметку, с
которой атрибуция обязательна. Вход называется `since`, и это располагает
подать дату: слово «начало» звучит как время. У гейта же `since` — РЕВИЗИЯ, из
неё строится диапазон `<since>..<ref>`.

Замер 10.09.2026: подключение уехало в общую ветку с датой `2026-09-09T18:20:00`
и первым же прогоном дало третий исход — «`2026-09-09T18:20:00..origin/main` не
разобран». Гейт не отработал ВООБЩЕ, и снаружи это выглядело как обычное
красное: разница между «нашёл отказ» и «не смог посмотреть» видна только в
логе (039).

Поймать это раньше было нечем: прогон идёт по событию общей ветки, и первый его
заход случается уже ПОСЛЕ слияния. Механизм, чья проверка возможна только в
общей ветке, проверяется тестом на дереве — иначе он подтверждается прогоном
задним числом (139).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

#: Прогон, чью отметку сверяем.
RUN: Final = Path(".github/workflows/attribution-history.yml")

#: Шаг, несущий отметку: подключение гейта каталога.
GATE: Final = "attribution@"


def gate_step() -> dict[str, Any]:
    """Шаг подключения гейта из прогона — вместе со всеми его входами."""
    run = yaml.safe_load(RUN.read_text(encoding="utf-8"))
    for job in run["jobs"].values():
        for step in job["steps"]:
            if GATE in str(step.get("uses", "")):
                return dict(step)
    raise AssertionError(f"в {RUN} нет шага, подключающего гейт атрибуции")


def revision(name: str) -> str | None:
    """Отпечаток, если строка — разрешимая ревизия этого дерева, иначе ``None``."""
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return done.stdout.strip() or None


def test_the_boundary_is_a_commit_not_a_date() -> None:
    """Отметка обязана разбираться как ревизия — ровно то, чем она станет.

    Проверяется НЕ форма строки, а её разрешимость деревом: запрет вида «не
    похоже на дату» ловит одно написание и молчит на остальных, а список
    разрешительный здесь строится сам собой — git либо находит коммит, либо
    нет (068).
    """
    since = str(gate_step()["with"].get("since", "")).strip()
    assert since, "отметка не задана: без неё гейт спрашивает всю историю"
    assert revision(since) is not None, (
        f"отметка «{since}» не разбирается как коммит. У гейта каталога `since` — "
        "РЕВИЗИЯ, из неё строится диапазон `<since>..<ref>`; дата даёт третий исход "
        "«диапазон не разобран», а не проверку"
    )


def shared_branch() -> str:
    """Общая ветка, как её видит прогон, — а НЕ `HEAD`.

    На изменении площадка выдаёт рабочим деревом искусственный коммит слияния
    `refs/pull/N/merge`. Он первопредок и трейлеров не несёт — их некому туда
    положить, — и проверка по `HEAD` краснела бы на КАЖДОМ изменении. Предмет
    же у прогона другой: история общей ветки, `origin/main`.
    """
    for name in (str(gate_step()["with"].get("ref", "")).strip(), "origin/main", "HEAD"):
        if name and revision(name):
            return name
    return "HEAD"


def test_nothing_after_the_boundary_lacks_attribution() -> None:
    """После отметки история общей ветки чиста — иначе прогон красен неотвратимо.

    Вечное красное не сигнал, а фон: рядом с ним не заметят настоящего (051).
    Отметка потому и объявляется руками — она отделяет то, что переписать уже
    нечем, от того, за что отвечает механизм.
    """
    since = str(gate_step()["with"].get("since", "")).strip()
    if revision(since) is None:
        pytest.skip("отметка не разрешима — об этом говорит соседняя проверка")
    done = subprocess.run(
        [
            "git",
            "log",
            "--first-parent",
            "--format=%h|%(trailers:key=Co-Authored-By,valueonly,separator=;)",
            f"{since}..{shared_branch()}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        pytest.skip("история недоступна: мелкий клон")
    bare = [
        line.split("|", 1)[0]
        for line in done.stdout.splitlines()
        if line and not line.split("|", 1)[1].strip()
    ]
    assert not bare, (
        "первопредки без строки соавтора после объявленной отметки: "
        + ", ".join(bare[:5])
        + ". Либо отметку двигают вперёд осознанно, либо чинят то, что их порождает"
    )
