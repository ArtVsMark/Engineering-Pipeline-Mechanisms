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
    # Неразобранный не прячет находки по разобранным (находка `ada8c4e`).
    assert "::error file=scripts/gate.py,line=2::без timeout=" in capsys.readouterr().out


@pytest.mark.parametrize(
    "raw",
    [
        b"# -*- coding: latin-1 -*-\nimport subprocess\nsubprocess.run(['\xe9'])\n",
        b"\xef\xbb\xbfimport subprocess\nsubprocess.run(['git'])\n",
    ],
    ids=["объявленная-кодировка", "utf-8-с-BOM"],
)
def test_a_declared_encoding_is_parsed_not_foreign(
    consumer: Path, raw: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    """PEP 263 и BOM — законный Python: файл разбирается и судится (находки `a2800cb`, `92c21ec`).

    Сосед — файл без объявления в latin-1: он по-прежнему «не разобран»
    (`test_an_unparsed_file_warns_without_enforce`).
    """
    (consumer / "scripts" / "declared.py").write_bytes(raw)
    assert gate.main(["--root", str(consumer), "--enforce"]) == gate.EXIT_FOUND
    out = capsys.readouterr().out
    assert "не разобран" not in out, out
    assert "::error file=scripts/declared.py,line=" in out, out
    assert undeadlined(raw) == [f"{raw.count(b'\n')}: без timeout="]


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


#: Вызов процесса с дедлайном без своей поимки — тело функции для случаев ниже.
SPAWN_BODY = "    subprocess.run(['git'], timeout=5)\n"


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        (
            "import subprocess\n\ndef f():\n" + SPAWN_BODY + "    yield 1\n\n"
            "def main():\n    try:\n        gen = f()\n    except subprocess.TimeoutExpired:\n"
            "        return 2\n    return list(gen)\n",
            True,
        ),
        (
            "import subprocess\n\nasync def f():\n" + SPAWN_BODY + "\n"
            "async def main():\n    try:\n        coro = f()\n"
            "    except subprocess.TimeoutExpired:\n        return 2\n    return await coro\n",
            True,
        ),
        (
            "import subprocess\n\ndef f():\n" + SPAWN_BODY + "\n"
            "def main():\n    try:\n        f()\n    except subprocess.TimeoutExpired:\n"
            "        return 2\n",
            False,
        ),
    ],
    ids=["генератор", "сопрограмма", "обычная-функция"],
)
def test_a_generator_or_coroutine_is_not_caught_at_the_call(source: str, bad: bool) -> None:
    """Генератор и `async def` исполняются не в месте вызова — засчёта нет (взгляд на #1589)."""
    assert bool(undeadlined(source)) is bad


def test_a_name_taken_by_another_module_is_not_caught_here(tmp_path: Path) -> None:
    """Имя, которое берёт другой модуль, не засчитывается по одним здешним вызовам (#1589).

    `hook.f` ловится в `main()` своего файла, но `other.py` зовёт `f` без `try`:
    истечение у второго вызывающего не поймано, и гейт обязан это сказать.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "hook.py").write_text(
        "import subprocess\n\ndef f():\n" + SPAWN_BODY + "\n"
        "def main():\n    try:\n        f()\n    except subprocess.TimeoutExpired:\n"
        "        return 2\n",
        encoding="utf-8",
    )
    found, _, _ = gate.look(tmp_path, ["scripts"])
    assert found == []
    (tmp_path / "scripts" / "other.py").write_text("from hook import f\n\nf()\n", encoding="utf-8")
    found, _, _ = gate.look(tmp_path, ["scripts"])
    assert [(name, what) for name, _, what in found] == [
        ("scripts/hook.py", "TimeoutExpired не пойман")
    ]


def test_exported_names_and_yields_name_their_subject() -> None:
    """`exported_names` видит обе формы импорта; `yields` — только своё тело."""
    trees = {
        "hook": ast.parse("def f(): pass\n"),
        "a": ast.parse("from hook import f\n"),
        "b": ast.parse("import hook as h\nh.g()\n"),
    }
    assert gate.exported_names(trees)["hook"] == frozenset({"f", "g"})
    own = ast.parse("def f():\n    yield 1\n").body[0]
    nested = ast.parse("def f():\n    def g():\n        yield 1\n").body[0]
    assert isinstance(own, ast.FunctionDef) and isinstance(nested, ast.FunctionDef)
    assert gate.yields(own) and not gate.yields(nested)


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        (
            "import subprocess\ntry:\n    g = (subprocess.run(['x'], timeout=5) for _ in 'a')\n"
            "except subprocess.TimeoutExpired:\n    pass\nlist(g)\n",
            True,
        ),
        (
            "import subprocess\ntry:\n    g = [subprocess.run(['x'], timeout=5) for _ in 'a']\n"
            "except subprocess.TimeoutExpired:\n    pass\n",
            False,
        ),
    ],
    ids=["выражение-генератор-в-try", "списковое-включение-в-try"],
)
def test_a_generator_expression_runs_outside_the_try(source: str, bad: bool) -> None:
    """Выражение-генератор исполняется при обходе, а не в `try` (находка `c97d776`).

    Сосед — списковое включение: оно исполняется сразу и засчитывается.
    """
    assert bool(undeadlined(source)) is bad


@pytest.mark.parametrize(
    ("wrap", "bad"),
    [("all", False), ("any", False), ("list", False), ("next", False), ("keep", True)],
)
def test_a_generator_consumed_on_the_spot_runs_in_the_try(wrap: str, bad: bool) -> None:
    """Генератор, тут же обойдённый встроенным, исполняется в `try` (взгляд на #1603).

    Отданный иному вызову (`keep`) судится строго: тот вправе обойти его позже.
    """
    source = (
        "import subprocess\ntry:\n"
        f"    {wrap}(subprocess.run(['x'], timeout=5) for _ in 'a')\n"
        "except subprocess.TimeoutExpired:\n    pass\n"
    )
    assert bool(undeadlined(source)) is bad


HOOK = (
    "import subprocess\n\ndef f():\n" + SPAWN_BODY + "\n"
    "def main():\n    try:\n        f()\n    except subprocess.TimeoutExpired:\n"
    "        return 2\n"
)


@pytest.mark.parametrize(
    "other",
    [
        "import hook\nhook.f()\n",
        "import hook as h\nh.f()\n",
        "import scripts.hook\nscripts.hook.f()\n",
        "from hook import f\nf()\n",
        "from hook import f as g\ng()\n",
        "from .hook import f\nf()\n",
        "from scripts import hook\nhook.f()\n",
        "from . import hook\nhook.f()\n",
        "from scripts import hook as h\nh.f()\n",
        "from hook import *\nf()\n",
    ],
    ids=[
        "import-m",
        "import-m-as-a",
        "import-p.m",
        "from-m-import-f",
        "from-m-import-f-as-g",
        "from-.m-import-f",
        "from-p-import-m",
        "from-.-import-m",
        "from-p-import-m-as-a",
        "from-m-import-*",
    ],
)
def test_every_import_form_takes_the_name(other: str) -> None:
    """Каждая форма импорта делает `f` внешним (находки `ede4ee7`, `9600e6c`, `6d792d1`)."""
    trees = {"hook": ast.parse(HOOK), "other": ast.parse(other)}
    taken = gate.exported_names(trees)["hook"]
    assert "f" in taken
    assert undeadlined(HOOK, taken) == ["4: TimeoutExpired не пойман"]
    assert not undeadlined(HOOK), "без внешнего вызывающего поимка в main засчитана"


def test_dotted_names_a_chain_over_a_name() -> None:
    """`dotted` собирает `a.b.c`, а у выражения не над именем — пусто."""
    assert gate.dotted(ast.parse("a.b.c", mode="eval").body) == "a.b.c"
    assert gate.dotted(ast.parse("f().b", mode="eval").body) == ""


def test_modules_with_one_name_share_the_taken_names(tmp_path: Path) -> None:
    """Два `other.py` в разных местах не вытесняют друг друга (находка `4936ee9`)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    (tmp_path / "scripts" / "hook.py").write_text(HOOK, encoding="utf-8")
    (tmp_path / "scripts" / "other.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".claude" / "hooks" / "other.py").write_text(
        "from hook import f\n\nf()\n", encoding="utf-8"
    )
    found, _, _ = gate.look(tmp_path, ["scripts", ".claude/hooks"])
    assert [(name, what) for name, _, what in found] == [
        ("scripts/hook.py", "TimeoutExpired не пойман")
    ]
