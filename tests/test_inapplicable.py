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
import sys
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
    # `python3` — ИНТЕРПРЕТАТОР НАБОРА, а не первый из PATH: тот бывает старше
    # планки, и предикат краснел бы отказом, к ответу не относящимся (взгляд
    # на #1177).
    run = [sys.executable, *argv[1:]] if argv[:1] == ["python3"] else argv
    done = subprocess.run(
        run, cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
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


def test_every_predicate_names_the_border_it_holds() -> None:
    """Предикат цитирует границу ответа, которую держит, — у КАЖДОГО правила (взгляд на #1177).

    Прежде гейт смотрел одно 066 и подстроки в собственном `why` предиката:
    связь предиката с ответом не проверялась ничем, и у 120 вторая половина
    границы осталась без предиката. Теперь `border` — дословная цитата из
    ответа в `.rules/bindings.json`: правка границы в ответе без правки
    предиката краснеет.

    ПРЕДЕЛ НАЗВАН: полноту — все ли половины границы названы — держит
    чтение: перечислить половины прозы разбор не умеет.
    """
    said = answers()
    off = [
        f"{rule}: «{one.get('border', '')}»"
        for rule in predicates()["predicates"]
        for one in checks(rule)
        if not one.get("border") or one["border"] not in said[rule]["why"]
    ]
    assert not off, f"предикат не цитирует границу своего ответа: {off}"


@pytest.mark.parametrize(
    ("rule", "borders"),
    [("066", 2), ("120", 2)],
    ids=["блокировка и второй писатель", "корпус правил и указатель решений"],
)
def test_a_composite_border_has_a_predicate_per_half(rule: str, borders: int) -> None:
    """Составная граница держится по половине на предикат: обе половины 066 и 120 названы."""
    assert len({one["border"] for one in checks(rule)}) == borders


def test_a_new_replace_inside_a_known_file_arrives(tmp_path: Path) -> None:
    """Вторая подмена в уже известном файле меняет вывод: сверяется строка, а не файл."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "scripts").mkdir()
    known = "    os.replace(a, b)\n"
    (tmp_path / "scripts" / "x.py").write_text(known, encoding="utf-8")
    git("add", "-A")
    argv = checks("066")[1]["argv"]
    before = hits(argv, tmp_path)
    (tmp_path / "scripts" / "x.py").write_text(known + "    os.replace(c, d)\n", encoding="utf-8")
    git("add", "-A")
    assert set(hits(argv, tmp_path)) - set(before), "новая подмена в известном файле не видна"


def test_a_script_that_calls_the_findings_base_is_a_second_writer(tmp_path: Path) -> None:
    """Скрипт, зовущий базу находок, — второй писатель, даже если прогон зовёт не её саму."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "findings_db.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts" / "prose.py").write_text('"""Зовёт `findings_db` рукой."""\n', "utf-8")
    git("add", "-A")
    argv = checks("066")[2]["argv"]
    assert hits(argv, tmp_path) == [], "упоминание в прозе — не вызов"
    (tmp_path / "scripts" / "nightly.py").write_text("import findings_db\n", encoding="utf-8")
    git("add", "-A")
    assert hits(argv, tmp_path) == ["scripts/nightly.py"]


def test_python3_runs_as_the_suite_interpreter(tmp_path: Path) -> None:
    """Предикат `python3` исполняется интерпретатором набора, а не первым из PATH."""
    said = hits(["python3", "-c", "import sys; print(sys.executable)"], tmp_path)
    assert said == [sys.executable]


def test_a_path_keeps_its_edges(tmp_path: Path) -> None:
    """Путь с пробелом по краю читается как есть, а не обрезанным (взгляд на #1177)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / " x.po").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    assert hits(["git", "ls-files", "-z", "*.po"], tmp_path) == [" x.po"]
