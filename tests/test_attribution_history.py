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

import os
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import needs_history

#: Общий шаг, который подключает гейт каталога и читает отметку (#1556).
STEP: Final = Path(".github/workflows/step-attribution-history.yml")

#: Шаг, подключающий гейт каталога.
GATE: Final = "attribution@"

#: Шаг, который называет отметку: его `run` исполняется здесь как есть.
SINCE_STEP: Final = "since"


def step_jobs() -> list[dict[str, Any]]:
    """Шаги джобов общего шага атрибуции."""
    run = yaml.safe_load(STEP.read_text(encoding="utf-8"))
    return [dict(step) for job in run["jobs"].values() for step in job["steps"]]


def gate_step() -> dict[str, Any]:
    """Шаг подключения гейта из общего шага — вместе со всеми его входами."""
    for step in step_jobs():
        if GATE in str(step.get("uses", "")):
            return step
    raise AssertionError(f"в {STEP} нет шага, подключающего гейт атрибуции")


def named_since(tree: Path) -> tuple[int, str]:
    """(код, отметка): шаг «отметка атрибуции» общего шага, исполненный на дереве."""
    code, since, _ = since_run(tree)
    return code, since


def since_run(tree: Path) -> tuple[int, str, str]:
    """(код, отметка, вывод шага): исполнение шага «отметка атрибуции» на дереве.

    ИСПОЛНЯЕТСЯ САМ ШАГ, А НЕ ВТОРОЙ РАЗБОР ФАЙЛА ОТМЕТКИ (090). Отметку
    читает `run` шага на площадке; разбор, написанный здесь заново, мог бы
    разойтись с ним молча — и тест проверял бы не то, что идёт в прогоне.
    """
    script = next((str(step["run"]) for step in step_jobs() if step.get("id") == SINCE_STEP), None)
    assert script, f"в {STEP} нет шага с id «{SINCE_STEP}» — отметку называть некому"
    out = tree / ".step-output"
    out.write_text("", encoding="utf-8")
    try:
        done = subprocess.run(
            ["bash", "-c", script],
            cwd=tree,
            env={**os.environ, "GITHUB_OUTPUT": str(out)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
        said = dict(
            line.split("=", 1)
            for line in out.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    finally:
        out.unlink()
    return done.returncode, said.get("since", ""), done.stdout + done.stderr


def boundary() -> str:
    """Отметка, которую шаг называет на нашем дереве; пусто — вся история."""
    code, since = named_since(Path("."))
    assert code == 0, "шаг отметки отказал на нашем дереве"
    return since


def test_the_step_hands_the_boundary_to_the_gate() -> None:
    """Отметка, названная шагом, доходит до гейта, а не теряется по дороге.

    Без этого файл отметки был бы украшением: гейт с пустым `since` спрашивал
    бы всю историю, и вечное красное стояло бы у каждого потребителя с хвостом
    до подключения (051).
    """
    assert gate_step()["with"].get("since") == "${{ steps.since.outputs.since }}"


def git(tree: Path, *args: str) -> str:
    """Команда git во временном дереве; вывод без пробелов по краям."""
    return subprocess.run(
        ["git", "-C", str(tree), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    ).stdout.strip()


def test_without_the_file_the_boundary_is_the_connection(tmp_path: Path) -> None:
    """У потребителя файла нет — отметка его коммит подключения, а не наш (#1556).

    Наш коммит в его истории не разбирается, и гейт каталога дал бы третий
    исход «диапазон не разобран» на каждом заходе (039). Коммит подключения
    — тот, что добавил `.pipeline.yml`: всё до него механизмы не держали.
    """
    git(tmp_path, "init", "-q")
    git(
        tmp_path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "до",
    )
    (tmp_path / ".pipeline.yml").write_text("checks: {}\n", encoding="utf-8")
    git(tmp_path, "add", ".pipeline.yml")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "подключение")
    connected = git(tmp_path, "rev-parse", "HEAD")
    git(
        tmp_path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "после",
    )
    assert named_since(tmp_path) == (0, connected)


def test_the_file_names_the_boundary_and_an_empty_one_refuses(tmp_path: Path) -> None:
    """Файл отметки побеждает коммит подключения; файл без коммита — отказ (045).

    Пустой файл молча означал бы «вся история», а объявленное, но ничего не
    называющее — не решение проекта, а его пропуск.
    """
    git(tmp_path, "init", "-q")
    (tmp_path / ".github").mkdir()
    declared = tmp_path / ".github" / "attribution-since"
    declared.write_text("# пояснение\nabc123\n", encoding="utf-8")
    assert named_since(tmp_path) == (0, "abc123")
    # ОТКАЗ НАЗВАН, А НЕ ОБОРВАН (взгляд на #1574, 107): ненулевой код дал бы и
    # `grep` без строк под `pipefail` — сверяется причина в выводе шага.
    for text in ("# одно пояснение\n", ""):
        declared.write_text(text, encoding="utf-8")
        code, _, said = since_run(tmp_path)
        assert code != 0 and "отметка объявлена, но не названа" in said, repr(text)


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
    since = boundary()
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
    since = boundary()
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
    since = boundary()
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
