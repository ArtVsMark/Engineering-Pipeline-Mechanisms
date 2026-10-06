"""Ответ «неприменимо» держится исполняемым предикатом, а не ручным перемером (#1171).

Ответ называет границу, при которой станет ложным (184), и предикат по дереву
(205). Пока предикат жил прозой в `.rules/bindings.json`, его перемеряли рукой
— и пропустили: подмена файла появилась 05.10.2026 (#1154), ответ на 066 после
перемера 02.10 говорил «станет ложным на первой подмене», и никто его не
перечитал. Здесь каждая команда из `.rules/inapplicable.json` исполняется на
каждом изменении, и новая строка вывода — красное: условие вступления
наступило, ответ перечитывается.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

paths = load_script("paths.py")

#: Ответ, чей предикат исполняется здесь.
INAPPLICABLE_STATUS: Final = "not-applicable"


def predicates() -> dict[str, Any]:
    """Таблица предикатов: исполняемые и названные немеханизуемыми."""
    said: dict[str, Any] = json.loads((ROOT / paths.INAPPLICABLE).read_text(encoding="utf-8"))
    return said


def answers() -> dict[str, Any]:
    """Ответы проекта по правилам каталога."""
    said: dict[str, Any] = json.loads((ROOT / paths.BINDINGS).read_text(encoding="utf-8"))
    return dict(said["rules"])


def hits(argv: list[str], root: Path) -> list[str]:
    """Строки вывода команды предиката: отсортированные, без пустых.

    У `git grep` код 1 — «совпадений нет», законный вход; прочий отказ —
    отказ, а не пустота: молчание сломанной команды читалось бы как «условие не
    наступило» (045).
    """
    done = subprocess.run(
        argv, cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )
    nothing = argv[:2] == ["git", "grep"] and done.returncode == 1 and not done.stderr.strip()
    if done.returncode != 0 and not nothing:
        raise AssertionError(f"предикат не исполнился ({done.returncode}): {argv}: {done.stderr}")
    # СПИСОК ПУТЕЙ — ПО NUL: путь с переводом строки законен, и построчный
    # разбор развалил бы его надвое (`tests/test_source_hygiene.py`).
    # Строка вывода не обрезается: путь с пробелом по краю законен и иначе
    # не совпал бы со своей записью в `allowed` (взгляд на #1177).
    parts = done.stdout.split("\0") if "-z" in argv else done.stdout.splitlines()
    return sorted({one for one in parts if one.strip()})


def checks(rule: str) -> list[dict[str, Any]]:
    """Предикаты правила: один или несколько — по половине границы ответа на каждый."""
    said = predicates()["predicates"][rule]
    return list(said) if isinstance(said, list) else [said]


def arrived(rule: str, root: Path = ROOT) -> list[str]:
    """Строки вывода сверх законных по всем предикатам правила: не пусто — условие наступило."""
    return [
        line
        for one in checks(rule)
        for line in hits(one["argv"], root)
        if line not in one["allowed"]
    ]


def test_every_inapplicable_answer_is_held_here_and_nothing_else_is() -> None:
    """Каждое «неприменимо» стоит ровно в одном разделе, и ничего лишнего (обе стороны, 154)."""
    table = predicates()
    run, named = set(table["predicates"]), set(table["unmechanized"])
    inapplicable = {
        rule for rule, one in answers().items() if one.get("status") == INAPPLICABLE_STATUS
    }
    assert inapplicable, "ответов «неприменимо» нет — предмет исчез (075)"
    assert not run & named, f"номер в обоих разделах: {sorted(run & named)}"
    assert inapplicable == run | named, (
        f"без предиката: {sorted(inapplicable - run - named)}; "
        f"предикат у ответа, который не «неприменимо»: {sorted((run | named) - inapplicable)}"
    )


@pytest.mark.parametrize("rule", sorted(predicates()["predicates"]))
def test_the_condition_of_entry_has_not_arrived(rule: str) -> None:
    """Предикат ответа не нашёл нового: правило по-прежнему без предмета в дереве.

    Красное здесь — не дефект кода, а наступившее условие: ответ в
    `.rules/bindings.json` перечитывается (навык `answer-a-rule`), и либо
    правило становится действующим, либо новая строка уходит в `allowed` с
    причиной.
    """
    new = arrived(rule)
    assert not new, (
        f"ответ «неприменимо» на {rule}: условие вступления наступило — {new}. "
        "Перечитайте ответ, а не расширяйте allowed молча"
    )


@pytest.mark.parametrize("rule", sorted(predicates()["predicates"]))
def test_every_allowed_line_is_still_found(rule: str) -> None:
    """Законная строка, которой больше нет, снимается: список законного не копит мёртвое (005)."""
    gone = sorted(
        line for one in checks(rule) for line in set(one["allowed"]) - set(hits(one["argv"], ROOT))
    )
    assert not gone, f"{rule}: в allowed строки, которых вывод больше не даёт: {gone}"


def test_a_planted_condition_turns_the_gate_red(tmp_path: Path) -> None:
    """Обе половины на настоящем git: чистое дерево зелёное, файл перевода — красное."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "x.py").write_text("print(1)\n", encoding="utf-8")
    git("add", "-A")
    argv = checks("077")[0]["argv"]
    assert hits(argv, tmp_path) == []
    (tmp_path / "ru.po").write_text('msgid "x"\n', encoding="utf-8")
    git("add", "-A")
    assert hits(argv, tmp_path) == ["ru.po"]
    assert "-z" in argv, "список путей предиката читается не по NUL"
    grep = ["git", "grep", "-nE", "flock", "--", "."]
    assert hits(grep, tmp_path) == [], "«совпадений нет» у git grep — не отказ"


def test_a_broken_command_is_a_refusal_not_silence(tmp_path: Path) -> None:
    """Сломанная команда — отказ, а не «условие не наступило» (045)."""
    with pytest.raises(AssertionError, match="не исполнился"):
        hits(["git", "rev-parse", "--verify", "HEAD"], tmp_path)


def test_every_half_of_a_border_has_its_own_predicate() -> None:
    """Граница 066 — блокировка и второй писатель; держатся обе половины (взгляд на #1177)."""
    whys = " ".join(one["why"] for one in checks("066"))
    assert len(checks("066")) >= 2, "у 066 предикат одной половины границы"
    assert "блокировк" in whys and "писател" in whys, "половина границы 066 без предиката"


def test_a_path_keeps_its_edges(tmp_path: Path) -> None:
    """Путь с пробелом по краю читается как есть, а не обрезанным (взгляд на #1177)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / " x.po").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    assert hits(["git", "ls-files", "-z", "*.po"], tmp_path) == [" x.po"]
