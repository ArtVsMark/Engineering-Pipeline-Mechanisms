"""Вызов процесса в механизме несёт дедлайн и ловит его истечение (100, 220, #1439).

Предикат живёт в `scripts/check_deadline.py` — одна реализация на семью (214):
потребитель получает тот же разбор шагом в джобе `pipeline`. Здесь он судит
наше дерево строго, а шапка скрипта говорит, что и почему он ловит.

КОРНИ — ОДИН СПИСОК (находка `5a5a96a`, правило 071): механизмы — это
`code_files(with_hooks=True)`, то есть `paths.SOURCES` и хуки окна, обходом
по `git ls-files`, а не свой каталог хуков рядом.
"""

import ast
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.conftest import ROOT, code_files, load_script

gate = load_script("check_deadline.py")
undeadlined = gate.undeadlined
is_spawn = gate.is_spawn


def mechanisms() -> list[Path]:
    """Код механизмов: источники проекта и хуки окна (220) — одним списком корней."""
    return code_files(with_hooks=True)


def test_every_spawn_has_a_deadline_and_catches_it() -> None:
    """Каждый вызов процесса в механизмах несёт `timeout=` и ловит его истечение."""
    found = {
        path.relative_to(ROOT).as_posix(): bad
        for path in mechanisms()
        if (bad := undeadlined(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"вызов процесса без дедлайна или без его поимки (100, 039): {found}. "
        "Назовите timeout= и ловите subprocess.TimeoutExpired тем же исходом, что OSError"
    )


def test_the_predicate_sees_spawns_in_the_tree() -> None:
    """У гейта есть предмет: вызовы процесса в механизмах есть (075)."""
    seen = sum(
        is_spawn(node, set())
        for path in mechanisms()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
    )
    assert seen > 10, f"вызовов процесса найдено {seen} — предикат смотрит не туда"


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        (
            "import subprocess\ntry:\n    subprocess.run(['x'], timeout=5)\n"
            "except subprocess.TimeoutExpired:\n    pass\n",
            False,
        ),
        (
            "import subprocess\ntry:\n    subprocess.run(['x'], timeout=5)\n"
            "except (OSError, subprocess.SubprocessError):\n    pass\n",
            False,
        ),
        ("import subprocess\ntry:\n    subprocess.run(['x'])\nexcept Exception:\n    pass\n", True),
        ("import subprocess\nsubprocess.run(['x'], timeout=5)\n", True),
        (
            "import subprocess\ntry:\n    subprocess.run(['x'], timeout=5)\n"
            "except OSError:\n    pass\n",
            True,
        ),
        ("from subprocess import check_output as co\nco(['x'])\n", True),
        ("import subprocess\nsubprocess.Popen(['x'])\n", True),
        (
            "import subprocess\ndef f():\n    p = subprocess.Popen(['x'])\n    try:\n"
            "        p.communicate(timeout=5)\n"
            "    except subprocess.TimeoutExpired:\n        pass\n",
            False,
        ),
        (
            "import subprocess\ndef f():\n    p = subprocess.Popen(['x'])\n    p.wait(timeout=5)\n",
            True,
        ),
        (
            "import subprocess\ndef f():\n    p = subprocess.Popen(['x'])\n"
            "def g(p):\n    try:\n        p.wait(timeout=5)\n"
            "    except subprocess.TimeoutExpired:\n        pass\n",
            True,
        ),
        ("import re\nre.compile('x').search('y')\nrun = 1\n", False),
        (
            "import subprocess\ntry:\n    def later():\n        subprocess.run(['x'], timeout=5)\n"
            "except subprocess.TimeoutExpired:\n    pass\n",
            True,
        ),
        (
            "import subprocess\ntry:\n    f = lambda: subprocess.run(['x'], timeout=5)\n"
            "except subprocess.TimeoutExpired:\n    pass\n",
            True,
        ),
        (
            "import subprocess\ndef later():\n    try:\n        subprocess.run(['x'], timeout=5)\n"
            "    except subprocess.TimeoutExpired:\n        pass\n",
            False,
        ),
        ("import subprocess as sp\nsp.run(['x'], timeout=5)\n", True),
        (
            "import subprocess as sp\ntry:\n    sp.run(['x'], timeout=5)\n"
            "except sp.TimeoutExpired:\n    pass\n",
            False,
        ),
    ],
    ids=[
        "дедлайн и поимка",
        "предок в кортеже",
        "поимка без дедлайна",
        "дедлайн без поимки",
        "поимка не того класса",
        "импорт под другим именем",
        "Popen",
        "Popen-с-пойманным-communicate",
        "Popen-с-wait-без-поимки",
        "Popen-ожидание-в-другой-функции",
        "не процесс",
        "def-в-теле-try",
        "lambda-в-теле-try",
        "try-внутри-def",
        "модуль-под-другим-именем",
        "модуль-под-другим-именем-пойман",
    ],
)
def test_the_predicate_has_both_halves(source: str, bad: bool) -> None:
    """Гейт ловит и пропуск дедлайна, и пропуск поимки — и не трогает чужое."""
    assert bool(undeadlined(source)) is bad


#: Поимка у вызывающего (#1569): вызов процесса без своей поимки, функция,
#: где он стоит, и её вызывающие.
SPAWN = "import subprocess\ndef f():\n    subprocess.run(['x'], timeout=5)\n"
CATCH = "    except subprocess.TimeoutExpired:\n        pass\n"


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        (SPAWN + "def main():\n    try:\n        f()\n" + CATCH, False),
        (
            SPAWN + "def g():\n    f()\ndef main():\n    try:\n        g()\n" + CATCH,
            False,
        ),
        (
            SPAWN + "def main():\n    try:\n        f()\n" + CATCH + "def other():\n    f()\n",
            True,
        ),
        (SPAWN + "def main():\n    try:\n        f()\n" + CATCH + "HANDLERS = {'x': f}\n", True),
        (SPAWN, True),
        (
            SPAWN + "def main():\n    try:\n        later = lambda: f()\n" + CATCH,
            True,
        ),
        (
            SPAWN + "def main():\n    try:\n        f()\n"
            "    except subprocess.TimeoutExpired:\n        return 2\n"
            "    except OSError:\n        return 1\n"
            "if __name__ == '__main__':\n    raise SystemExit(main())\n",
            False,
        ),
        (SPAWN + "def g():\n    g()\n    f()\n", True),
        (
            SPAWN + "def main():\n    try:\n        f()\n" + CATCH + "def other(o):\n    o.f()\n",
            True,
        ),
    ],
    ids=[
        "пойман-у-единственного-вызывающего",
        "цепочка-из-двух",
        "второй-вызывающий-не-ловит",
        "передана-значением",
        "вызовов-нет",
        "вызов-в-lambda-внутри-try",
        "форма-хука-каталога",
        "цикл-без-поимки",
        "вызов-через-точку",
    ],
)
def test_a_catch_at_every_caller_counts(source: str, bad: bool) -> None:
    """Поимка у каждого вызывающего засчитывается; передача значением и пропуск — нет (#1569)."""
    assert bool(undeadlined(source)) is bad


def test_caught_by_callers_marks_the_body_of_the_caught_function() -> None:
    """`caught_by_callers` отдаёт узлы тела засчитанной функции — и только её."""
    tree = ast.parse(SPAWN + "def main():\n    try:\n        f()\n" + CATCH)
    marked = gate.caught_by_callers(tree, gate.guarded(tree))
    f, main = tree.body[1], tree.body[2]
    assert isinstance(f, ast.FunctionDef) and isinstance(main, ast.FunctionDef)
    assert all(id(node) in marked for node in ast.walk(f.body[0]))
    assert id(main.body[0]) not in marked


def test_executed_stops_at_nested_scopes() -> None:
    """Исполняемое на месте — без тел `def`, `lambda` и `class`: внешний `try` их не держит."""
    tree = ast.parse("def f():\n    g()\nh()\n")
    names = {
        gate.spawned_name(node.func)
        for one in tree.body
        for node in gate.executed(one)
        if isinstance(node, ast.Call)
    }
    assert names == {"h"}


def test_waits_with_deadline_marks_only_the_scope_of_the_wait() -> None:
    """Пойманное ожидание с `timeout=` делает законной свою область, а не соседнюю функцию."""
    tree = ast.parse(
        "import subprocess\ndef f():\n    try:\n        p.wait(timeout=1)\n"
        "    except subprocess.TimeoutExpired:\n        pass\ndef g():\n    q()\n"
    )
    allowed = gate.waits_with_deadline(tree, gate.guarded(tree))
    calls = {
        gate.spawned_name(node.func): id(node) in allowed
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert calls == {"wait": True, "q": False}


def git(cwd: Path, *args: str) -> None:
    """git в подделке потребителя."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=30)


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """Дерево потребителя: один механизм с вызовом без дедлайна, тест с таким же."""
    git(tmp_path, "init", "-q")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "gate.py").write_text(
        "import subprocess\nsubprocess.run(['git'])\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import subprocess\nsubprocess.run(['git'])\n", encoding="utf-8"
    )
    return tmp_path


def test_a_consumer_is_warned_by_default(
    consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """У потребителя по умолчанию — предупреждение на строке, исход 0 (решение 18.10.2026, (б))."""
    assert gate.main(["--root", str(consumer)]) == gate.EXIT_OK
    said = capsys.readouterr().out
    assert "::warning file=scripts/gate.py,line=2::без timeout=" in said
    assert "tests/" not in said, "набор тестов не механизм — судить его не просили"


def test_enforce_turns_the_warning_into_a_refusal(
    consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """С `--enforce` найденное — отказ с аннотацией ошибки."""
    assert gate.main(["--root", str(consumer), "--enforce"]) == gate.EXIT_FOUND
    assert "::error file=scripts/gate.py,line=2::" in capsys.readouterr().out


def test_the_places_are_an_input(consumer: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Места кода — вход (пункт (в)): названный иной каталог судится, умолчание — нет."""
    assert gate.main(["--root", str(consumer), "--paths", "tests", "--enforce"]) == gate.EXIT_FOUND
    assert "tests/test_x.py" in capsys.readouterr().out


def test_a_named_place_that_is_not_there_does_not_run(consumer: Path) -> None:
    """Опечатка в местах — «не отработал», а не «неприменимо», и со строгим ключом (#1530)."""
    assert (
        gate.main(["--root", str(consumer), "--paths", "scirpts", "--enforce"]) == gate.EXIT_BROKEN
    )


def test_a_default_place_that_is_not_there_is_skipped(
    consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Хуков окна у потребителя нет — умолчание их пропускает и судит `scripts/`."""
    assert not (consumer / ".claude").exists()
    assert gate.main(["--root", str(consumer), "--enforce"]) == gate.EXIT_FOUND
    assert "scripts/gate.py" in capsys.readouterr().out


def test_the_annotation_escapes_its_properties() -> None:
    """Запятая и двоеточие в имени файла не ломают команду площадки (взгляд на #1530)."""
    assert gate.escaped("a,b:c%.py", prop=True) == "a%2Cb%3Ac%25.py"
    assert gate.escaped("без timeout=: да", prop=False) == "без timeout=: да"


def test_a_tree_without_code_is_inapplicable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Кода под местами нет — неприменимо с причиной, а не «чисто» (154).

    Дерево не пустое: `.py` с вызовом без дедлайна лежит ВНЕ мест умолчания.
    На пустом дереве тест проходил и при обходе всего репозитория — так
    `git ls-files --` без путей и судил бы `tests/` потребителя (поздний
    взгляд на #1530).
    """
    git(tmp_path, "init", "-q")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "probe.py").write_text(
        "import subprocess\nsubprocess.run(['x'])\n", encoding="utf-8"
    )
    assert gate.main(["--root", str(tmp_path), "--enforce"]) == gate.EXIT_OK
    assert "неприменимо" in capsys.readouterr().out


def test_no_places_means_no_files(consumer: Path) -> None:
    """Пустой перечень мест — пустой перечень файлов, а не всё дерево (#1530)."""
    assert gate.code_of(consumer, []) == []
    assert gate.code_of(consumer, ["scripts"]), "предмет пуст — проверка ничего не различает (075)"


def test_an_unparsed_file_warns_without_enforce(
    consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Неразобранный файл без `--enforce` — предупреждение с адресом, а не красный джоб (#1530).

    Решение (б): дерево, писанное без гейта, не краснеет с первым подъёмом
    тега. Шаблон `.py`, синтаксис Python 2, чужая кодировка — такой файл
    называется и считается, но джоб не роняет. Строгий проект своё разбирать
    обязан: с `--enforce` это «не отработал» (039).
    """
    (consumer / "scripts" / "broken.py").write_text("def (:\n", encoding="utf-8")
    (consumer / "scripts" / "legacy.py").write_bytes("# \xe9\n".encode("latin-1"))
    assert gate.main(["--root", str(consumer)]) == gate.EXIT_OK
    out = capsys.readouterr().out
    assert "::warning file=scripts/broken.py::файл не разобран" in out, out
    assert "::warning file=scripts/legacy.py::файл не разобран" in out, out
    assert "не разобрано файлов: 2" in out, out
    assert gate.main(["--root", str(consumer), "--enforce"]) == gate.EXIT_BROKEN


def test_nothing_parsed_is_inapplicable_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ни один файл не разобран — «неприменимо», а не зелёное «дедлайн у каждого» (#1546)."""
    git(tmp_path, "init", "-q")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "broken.py").write_text("def (:\n", encoding="utf-8")
    assert gate.main(["--root", str(tmp_path)]) == gate.EXIT_OK
    out = capsys.readouterr().out
    assert "неприменимо: ни один из файлов 1 не разобран" in out, out
    assert "дедлайн у каждого" not in out, out


def test_the_counts_name_only_the_parsed_files(
    consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Счёт находок и чистого исхода — по разобранным файлам, одним знаменателем (#1546)."""
    (consumer / "scripts" / "broken.py").write_text("def (:\n", encoding="utf-8")
    assert gate.main(["--root", str(consumer)]) == gate.EXIT_OK
    out = capsys.readouterr().out
    assert "не разобрано файлов: 1 из 2" in out, out
    assert "в разобранных файлах 1" in out, out


def test_outside_a_repository_it_does_not_run(tmp_path: Path) -> None:
    """Без git дерево не прочитать — «не отработал», а не «кода нет»."""
    assert gate.main(["--root", str(tmp_path)]) == gate.EXIT_BROKEN


def test_inside_git_dir_it_does_not_run(tmp_path: Path) -> None:
    """Внутри `.git` рабочего дерева нет — «не отработал», хотя git выходит с кодом 0 (#1538)."""
    git(tmp_path, "init", "-q")
    assert gate.main(["--root", str(tmp_path / ".git")]) == gate.EXIT_BROKEN


def test_our_tree_is_clean_under_the_step(capsys: pytest.CaptureFixture[str]) -> None:
    """Шаг в нашем `ci.yml` видит все источники и хуки и строг — и наше дерево под ним зелено.

    Места читаются из входа шага, а не списком здесь: второй список разошёлся
    бы с первым молча (022). Сверка с якорем — `paths.SOURCES` и хуки окна.
    """
    given = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    said = given["jobs"]["pipeline"]["with"]
    places = str(said["mechanism-paths"]).split()
    sources = {one.as_posix() for one in load_script("paths.py").SOURCES}
    assert set(places) == sources | {".claude/hooks"}, f"места шага {places} разошлись с якорем"
    assert said["mechanism-gates-enforce"] is True, "у себя мета-гейт строгий"
    code = gate.main(["--root", str(ROOT), "--paths", " ".join(places), "--enforce"])
    assert code == gate.EXIT_OK, capsys.readouterr().out
