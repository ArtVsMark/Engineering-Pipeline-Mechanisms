"""Где бы набор ни прогонялся, он прогоняется ТЕМ ЖЕ составом.

ЗАМЕР 15.09.2026, из-за которого проверка и написана. Шаг значков считал
покрытие так: ставил счётчик и звал `python -m coverage run … -m pytest`. Самого
набора в том окружении не было вовсе — `pytest` там никто не ставил, — и заход
падал на первом же шаге. Механизм при этом вёл себя честно: объявлял покрытие НЕ
ПРОЧИТАННЫМ, а не нулевым
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)),
и значок витрины так и говорил — «покрытие: не прочитано». Но единственным
следом причины было предупреждение в логе прогона, которого часть окон не видит
вовсе, и число не публиковалось НИ РАЗУ с появления счётчика 12.09. Локальный
замер того же дня: набор под счётчиком зелен, покрытие 87.3 %.

ПРЕДМЕТ — ШАГ, КОТОРЫЙ ЗОВЁТ НАБОР, а не джоб, который его РАЗРЕШАЕТ. У ревью и
обращения в списке разрешённых команд агента `pytest` тоже стоит, и они ставят
его себе сами — но их собственные шаги набор не запускают, и требовать от них
состава прогонщика значило бы судить чужой предмет
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

СОСТАВ БЕРЁТСЯ ИЗ ДЕРЕВА, А НЕ ОБЪЯВЛЯЕТСЯ ЗДЕСЬ ВТОРЫМ СПИСКОМ: канон — строка
установки прогонщика набора на изменении. Второй список тех же имён разошёлся бы
с первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import yaml

from tests.conftest import ROOT, load_script, walk

WORKFLOWS: Final = ROOT / ".github" / "workflows"
#: Прогонщик набора на изменении: его строка установки и есть канон состава.
CANON: Final = (".github/workflows/ci.yml", "test-matrix")
#: Вызов набора в команде шага: `pytest`, `python -m pytest`, в том числе под
#: счётчиком. Слово ищется как команда, а не как подстрока: `pytest-randomly` в
#: строке установки вызовом не является.
CALL_RE: Final = re.compile(r"(?:^|[\s;&|])(?:python3?\s+-m\s+)?pytest(?:$|[\s;&|])")
#: Одно требование строки установки: имя пакета в кавычках с границами версий.
NEED_RE: Final = re.compile(r'"([A-Za-z][\w.-]*)(?:[<>=!~][^"]*)?"')


def workflows() -> list[Path]:
    """Прогоны дерева — все, а не перечисленные: новый попадает сам."""
    return walk(WORKFLOWS, "*.y*ml")


def steps_of(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Шаги джоба, у которых есть команда."""
    return [step for step in (job or {}).get("steps") or [] if isinstance(step, dict)]


def commands(step: dict[str, Any]) -> list[str]:
    """Строки команды без пояснений, с развёрнутыми переносами.

    ПОЯСНЕНИЕ ВЫЗОВОМ НЕ ЯВЛЯЕТСЯ. Без этого проверка ловила бы саму себя:
    комментарий к правке, называющий `pytest`, читался бы как вызов набора (044).

    ПЕРЕНОС СТРОКИ ОБРАТНЫМ СЛЕШЕМ РАЗВЁРНУТ. Команда, разбитая для читаемости,
    остаётся одной командой: разбор по физическим строкам объявил бы строку
    установки пустой — имена пакетов уехали бы на следующую. Замер 15.09.2026:
    ровно так проверка и промахнулась на первой же своей правке.
    """
    said: list[str] = []
    joined = ""
    for line in str(step.get("run") or "").splitlines():
        bare = line.strip()
        if not bare or bare.startswith("#"):
            continue
        if bare.endswith("\\"):
            joined += bare[:-1].strip() + " "
            continue
        said.append((joined + bare).strip())
        joined = ""
    if joined:
        said.append(joined.strip())
    return said


def calls_the_suite(step: dict[str, Any]) -> bool:
    """Зовёт ли шаг набор."""
    return any(CALL_RE.search(line) for line in commands(step))


def installs_of(job: dict[str, Any]) -> set[str]:
    """Имена пакетов, которые джоб ставит себе — из всех его строк установки."""
    found: set[str] = set()
    for step in steps_of(job):
        for line in commands(step):
            if "pip install" in line:
                found.update(NEED_RE.findall(line))
    return found


def jobs_of(path: Path) -> dict[str, dict[str, Any]]:
    """Джобы прогона: имя ключа → тело."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return {}
    return {str(name): job or {} for name, job in (document.get("jobs") or {}).items()}


def runners() -> list[tuple[str, str, dict[str, Any]]]:
    """Джобы дерева, чьи шаги зовут набор: файл, имя, тело."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in workflows():
        for name, job in jobs_of(path).items():
            if any(calls_the_suite(step) for step in steps_of(job)):
                found.append((path.name, name, job))
    return found


def canon_kit() -> set[str]:
    """Состав набора по канону — строка установки прогонщика на изменении."""
    path, name = CANON
    job = jobs_of(ROOT / path).get(name) or {}
    kit = installs_of(job)
    assert kit, f"{path}:{name} — канонной строки установки нет, сверять нечем (075)"
    return kit


def test_the_canon_runner_is_found() -> None:
    """Предмет проверки найден: канон существует и зовёт набор (075)."""
    path, name = CANON
    job = jobs_of(ROOT / path).get(name)
    assert job is not None, f"в {path} нет джоба {name}"
    assert any(calls_the_suite(step) for step in steps_of(job)), (
        f"{path}:{name} больше не зовёт набор — канон состава стоит не там"
    )
    assert "pytest" in canon_kit(), "канонный состав обязан включать сам набор"


def test_the_canon_kit_carries_the_tree_packages() -> None:
    """Состав набора включает пакеты САМОГО дерева, а не только инструменты.

    ЗАМЕР 15.09.2026, стоивший красного изменения. Общий низ конвейера уехал в
    пакет, и набор стал его импортировать — а прогонщики набора пакет не ставили:
    `test-matrix` упал с кодом 2, то есть на СБОРЕ, не дойдя ни до одного теста.
    Проверка «каждый прогонщик ставит канон» при этом молчала: канон сам его не
    называл. Требование читается из объявления пакета, а не из второго списка
    рядом (022, 090).
    """
    env = load_script("check_env.py")
    ours = env.local_packages(ROOT)
    assert ours, "пакетов дерева не найдено — сверять нечего (075)"
    path, name = CANON
    job = jobs_of(ROOT / path).get(name) or {}
    installs = "\n".join(
        line for step in steps_of(job) for line in commands(step) if "pip install" in line
    )
    for _, where in ours:
        assert f"./{where.relative_to(ROOT).as_posix()}" in installs, (
            f"{path}:{name} не ставит пакет дерева {where.relative_to(ROOT)}: набор его "
            "импортирует, и сбор упадёт раньше первого теста"
        )


def test_every_step_that_runs_the_suite_installs_it() -> None:
    """У каждого прогонщика набора в окружении есть то, чем набор ходит.

    Иначе заход падает не на тесте, а на «модуля нет», и читается это как
    «замер не получился» вместо «набор сломан».
    """
    kit = canon_kit()
    lacking = {
        f"{where}:{name}": sorted(kit - installs_of(job))
        for where, name, job in runners()
        if kit - installs_of(job)
    }
    assert not lacking, f"прогонщик набора без его состава: {lacking}"


def test_the_predicate_names_the_suite_and_not_its_permission() -> None:
    """Считается вызов набора, а не разрешение агенту его звать (195).

    Граница названа проверкой, а не прозой: список разрешённых команд агента
    (`Bash(python -m pytest:*)`) вызовом не считается, иначе от ревью требовался
    бы состав прогонщика — чужой предмет.
    """
    assert calls_the_suite({"run": "python -m coverage run --source=scripts -m pytest -q"})
    assert calls_the_suite({"run": "pytest --strict-markers"})
    assert not calls_the_suite({"run": "# сюда нельзя: python -m pytest в пояснении"})
    assert not calls_the_suite({"run": 'python -m pip install --quiet "pytest-randomly>=3,<4"'})
    assert not calls_the_suite({"with": {"allowed_tools": "Bash(python -m pytest:*)"}})


def test_an_empty_parametrisation_is_a_refusal_not_a_skip() -> None:
    """Гейт по пустому списку из дерева ОТКАЗЫВАЕТ, а не собирает ноль случаев.

    Проверка, идущая по списку из дерева, при пустом списке собирает НОЛЬ
    случаев и зеленеет — снаружи она неотличима от прошедшей. Умолчание pytest
    помечает такой набор ПРОПУСКОМ, то есть тем же молчанием
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md),
    [045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

    ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ПРОВЕРКА И НАПИСАНА: пояснение над
    `addopts` требовало этого с самого начала — «гейт, не нашедший предмета,
    обязан падать», — а ключа, который держит требование, в настройках не было.
    Обходов дерева в наборе 88 в 51 модуле, и любой из них мог опустеть молча
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    Числа получены `grep -roE '(^|[^.[:alnum:]_])(walk|walk_deep|found_by)[(]'
    tests/*.py --exclude=conftest.py | wc -l` (модули — тот же grep с `-rl`),
    замер 19.09.2026; голое имя отделяет обходчики набора от `ast.walk`.

    ЗНАЧЕНИЕ СВЕРЯЕТСЯ С ЖИВОЙ НАСТРОЙКОЙ, а не с текстом файла: `pytest` мог бы
    прочесть его иначе, и тогда проверка утверждала бы написанное вместо
    действующего
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    """
    import _pytest.config

    config = _pytest.config.get_config([str(ROOT)])
    config.parse([str(ROOT / "tests")])
    said = config.getini("empty_parameter_set_mark")
    assert said == "fail_at_collect", (
        f"пустая параметризация помечена «{said}»: гейт по пустому списку из дерева"
        " собрал бы ноль случаев и был бы зелёным. Нужно «fail_at_collect»"
    )


def test_the_measuring_runner_is_among_them() -> None:
    """Шаг значков, считающий покрытие, — прогонщик набора, а не сосед.

    Это и есть находка 15.09.2026: он зовёт набор, и состав ему нужен тот же.
    Без этой проверки он снова окажется вне сверки — от одной правки строки.
    """
    assert ("badges.yml", "badges") in [(where, name) for where, name, _ in runners()]


def test_an_import_under_another_name_keeps_both(tmp_path: Path) -> None:
    """`from x import имя as другое` употребляет ОБА имени, а не одно из двух.

    Разборчик `names_used` отбирает файлы, которые механизм действительно
    употребляют. Прежде он брал `asname or name`, и настоящее имя терялось:
    файл, импортирующий механизм под псевдонимом, выпадал из отбора МОЛЧА.
    Промах отбора опаснее промаха предиката — гейт остаётся зелёным, ничего не
    проверив
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд (`71621f8`).

    ЗАМЕР 19.09.2026: импортов под другим именем в дереве НОЛЬ. Правится
    расхождение обещания с механизмом — докстрока разборчика называет эту форму
    прямо, — а не найденный пропуск
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    from tests.conftest import names_used

    образец = tmp_path / "образец.py"
    образец.write_text(
        "from соседний import механизм as псевдоним\nпсевдоним()\n",
        encoding="utf-8",
    )

    видно = names_used(образец)

    assert "механизм" in видно, "настоящее имя потеряно — файл выпадет из отбора молча"
    assert "псевдоним" in видно, "имя, под которым механизм зовут здесь, тоже употребление"
