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

ВТОРОЙ ПРЕДМЕТ ЗДЕСЬ — НЕПУСТОТА ДИАПАЗОНА. Отметку двигают вперёд, и доехав
до головы, она гасит прогон целиком: гейт каталога на пустом диапазоне говорит
«проверять нечего» и возвращает ноль. Снаружи такая зелень неотличима от
проверенной истории, и это ровно тот случай, о котором 192: гейт, заведённый
вместе с правкой, обязан ловить и НОЛЬ.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import needs_history

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


@needs_history
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


def first_parents_after(since: str, ref: str) -> list[str] | None:
    """Первопредки в диапазоне ``since..ref``; ``None`` — история недоступна."""
    done = subprocess.run(
        ["git", "log", "--first-parent", "--format=%h", f"{since}..{ref}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        return None
    return [line for line in done.stdout.splitlines() if line.strip()]


def test_the_boundary_leaves_a_subject_behind_it() -> None:
    """После отметки есть что проверять: пустой диапазон — гейт без предмета.

    ГЕЙТ ОБЯЗАН ЛОВИТЬ И НОЛЬ
    ([192](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/192-changing-the-actor-invalidates-the-measurement.md)).
    Гейт каталога на пустом диапазоне печатает «новых коммитов нет — проверять
    нечего» и возвращает ноль — законно для него самого, но снаружи вечная
    зелень неотличима от проверенной истории
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    ЭТО НЕ ОПАСЕНИЕ. Отметку двигали трижды — 09.09, 10.09 и 13.09, — и каждый
    раз вперёд: доехав до головы, она погасила бы прогон целиком, и ни одна
    проверка этого не заметила бы. Соседняя проверка чистоты истории на пустом
    списке тоже проходит: ей нечего перебирать.

    Замер 13.09.2026: после отметки `77a5c72` — 25 первопредков.
    """
    since = str(gate_step()["with"].get("since", "")).strip()
    if revision(since) is None:
        pytest.skip("отметка не разрешима — об этом говорит соседняя проверка")
    seen = first_parents_after(since, shared_branch())
    if seen is None:
        pytest.skip("история недоступна: мелкий клон")
    assert seen, (
        f"после отметки «{since}» в {shared_branch()} нет ни одного первопредка: "
        "прогон атрибуции зелен потому, что ему нечего смотреть, а не потому, что "
        "история чиста. Отметка доехала до головы — верните её назад либо признайте, "
        "что механизм больше ничего не держит"
    )


def test_an_empty_range_is_what_the_check_must_refuse() -> None:
    """Проверка непустоты отвергает то, ради чего заведена (140).

    Без этого «зелено» означало бы лишь, что предикат не умеет краснеть:
    диапазон от головы до головы пуст всегда, и такой ответ обязан читаться
    как отсутствие предмета, а не как чистая история.
    """
    assert first_parents_after("HEAD", "HEAD") == []
    assert first_parents_after("несуществующая-ревизия", "HEAD") is None, (
        "нечитаемый диапазон — не «пусто»: это незнание, и оно называется отдельно (045)"
    )


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
