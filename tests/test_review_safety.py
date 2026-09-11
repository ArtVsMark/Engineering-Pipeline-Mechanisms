"""Условия безопасности ревью держатся тестом, а не внимательностью.

Ревью — единственный механизм проекта, который исполняет промпт, собранный в
том числе из чужого текста, и делает это токеном владельца. Всё, что здесь
проверяется, — из разряда «правка выглядит безобидно, а периметр открывается»:
такое правило обязано иметь механизм (002), иначе оно обещание.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
AUTO_REVIEW = WORKFLOWS / "review.yml"
ON_MENTION = WORKFLOWS / "claude.yml"
SHA_PIN = re.compile(r"@[0-9a-f]{40}\b")
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")


def load(path: Path) -> dict[Any, Any]:
    """Читает описание прогона; ключ событий в YAML 1.1 — булево True."""
    document: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_no_workflow_uses_pull_request_target(path: Path) -> None:
    """`pull_request_target` не используется НИГДЕ.

    Он исполняется в контексте общей ветки и отдаёт секреты прогону, запущенному
    по коду постороннего автора. На изменении из форка авто-ревью не идёт — это
    осознанное ограничение, а не поломка, которую чинят этим триггером.
    """
    assert "pull_request_target" not in load(path)[True]


def test_auto_review_skips_forks_explicitly() -> None:
    """Форк пропускается явно, а не ломается молча на шаге агента (027)."""
    condition = load(AUTO_REVIEW)["jobs"]["review"]["if"]
    assert "head.repo.full_name == github.repository" in condition


def test_auto_review_cancellation_group_names_the_head() -> None:
    """Группа отмены называет голову, а не только номер изменения (179)."""
    group = load(AUTO_REVIEW)["concurrency"]["group"]
    assert "head.sha" in group


def test_the_group_names_the_subject_of_a_manual_run_too() -> None:
    """У ручного запуска предмет называет ВХОД, а не событие.

    При `workflow_dispatch` `pull_request` пуст, и без `inputs.pr` группа
    схлопывается в одну на все номера: поздние взгляды по разным изменениям
    гасят друг друга. Замер 10.09.2026 — владелец запустил пять заходов подряд
    по разным номерам, до конца дошёл один, четыре отменены. Снаружи это
    выглядело как «механизм не работает», хотя не работала группа.
    """
    document = load(AUTO_REVIEW)
    group = document["concurrency"]["group"]
    events = document[True] if True in document else document["on"]
    if "workflow_dispatch" not in events:
        return
    inputs = (events["workflow_dispatch"] or {}).get("inputs") or {}
    for name in inputs:
        assert f"inputs.{name}" in group, (
            f"вход «{name}» задаёт предмет ручного запуска, а в группе отмены его нет (179)"
        )


def test_mention_review_requires_a_trusted_author() -> None:
    """Обращение обслуживается только от доверенного автора — по всем событиям.

    Список разрешённого (068): упоминания мало, потому что триггеры задач
    открыты всему интернету, а агент запускается токеном владельца.
    """
    document = load(ON_MENTION)
    condition = document["jobs"]["respond"]["if"]
    for role in TRUSTED:
        assert role in condition
    # Каждое объявленное событие обязано попасть под требование к автору:
    # событие без своей ветки в условии — это открытая дверь.
    for event in document[True]:
        assert f"github.event_name == '{event}'" in condition, f"{event} без гейта автора"


@pytest.mark.parametrize("path", [AUTO_REVIEW, ON_MENTION], ids=lambda p: p.name)
def test_agent_jobs_have_a_timeout(path: Path) -> None:
    """У джоба агента есть предел: умолчание площадки — шесть часов молчания."""
    for name, job in load(path)["jobs"].items():
        assert job.get("timeout-minutes"), f"{path.name}: у джоба {name} нет предела"


@pytest.mark.parametrize("path", [AUTO_REVIEW, ON_MENTION], ids=lambda p: p.name)
def test_actions_that_receive_the_token_are_pinned_by_sha(path: Path) -> None:
    """Действия ревью закреплены по SHA, а не по подвижной метке (152).

    Здесь это не про дрейф, а про доверие: действие получает токен и исполняет
    промпт, и метка означает, что исполняемый код может смениться без нашего
    ведома.
    """
    for step in [s for job in load(path)["jobs"].values() for s in job["steps"]]:
        uses = step.get("uses")
        if uses:
            assert SHA_PIN.search(uses), f"{path.name}: {uses} закреплено меткой, а не SHA"


def agent_steps(path: Path) -> list[dict[str, Any]]:
    """Шаги, запускающие агента: у них есть `claude_args`."""
    return [
        step
        for job in load(path)["jobs"].values()
        for step in job["steps"]
        if "claude_args" in (step.get("with") or {})
    ]


def declared_tools(path: Path) -> list[tuple[str, list[str]]]:
    """Списки инструментов агента — ВСЕ, а не первый попавшийся.

    Читается значение ключа, а не файл целиком: в комментариях рядом слово
    «Bash» встречается по делу, и поиск по тексту дал бы находку на пояснении,
    а не на списке.

    ПОЧЕМУ ВСЕ. Прогон ревью держит больше одного шага агента — взгляд на
    изменение и поздний взгляд по общей ветке, — и у каждого свой список.
    Проверка первого зеленела бы на втором, сколько бы там ни было разрешено:
    ровно тот случай, когда гейт смотрит не туда, где предмет (075).
    """
    found = [
        (str(step.get("name") or "без имени"), match)
        for step in agent_steps(path)
        if (match := re.search(r'--allowedTools\s+"([^"]+)"', step["with"]["claude_args"]))
    ]
    assert len(found) == len(agent_steps(path)), (
        f"{path.name}: у шага агента список инструментов не объявлен"
    )
    assert found, f"{path.name}: список инструментов агента не объявлен"
    return [
        (name, [tool.strip() for tool in match.group(1).split(",") if tool.strip()])
        for name, match in found
    ]


@pytest.mark.parametrize("path", [AUTO_REVIEW, ON_MENTION], ids=lambda p: p.name)
def test_agent_tools_are_an_allowlist_without_bare_bash(path: Path) -> None:
    """Инструменты агента — закрытый список, и голого `Bash` в нём нет.

    Список инструментов — единственный барьер против указания «выполни команду и
    отправь результат наружу», пришедшего из проверяемого текста (085).
    """
    for name, tools in declared_tools(path):
        assert tools, f"{path.name}, «{name}»: список пуст — это не ограничение, а его отсутствие"
        bare = [tool for tool in tools if tool == "Bash" or tool.startswith("Bash ")]
        assert not bare, f"{path.name}, «{name}»: разрешён Bash без ограничения команды: {bare}"
        for tool in tools:
            if tool.startswith("Bash"):
                assert tool.startswith("Bash(") and tool.endswith(")"), f"{path.name}: {tool}"


#: Инструменты, которыми агент пишет в площадку или наружу. Список
#: запретительный намеренно: разрешительный здесь пришлось бы держать полным
#: списком безобидного, а безобидное растёт быстрее опасного.
WRITING_TOOLS = ("Write", "Edit", "WebFetch", "WebSearch", "Bash(gh ", "Bash(curl ")


@pytest.mark.parametrize("path", [AUTO_REVIEW], ids=lambda p: p.name)
def test_the_reviewer_stays_a_reader(path: Path) -> None:
    """Ревьюер не пишет ни в площадку, ни наружу — за него это делает механизм.

    Вход ревью собран из проверяемого текста, и право записи в этом канале
    означает, что чужой текст сможет им воспользоваться (085). Поздний взгляд
    по общей ветке — самое место, где такое право хочется выдать: адресата у
    него нет по построению. Поэтому ответ переносит `late_look.py`, а не агент.
    """
    for name, tools in declared_tools(path):
        writing = [tool for tool in tools if tool.startswith(WRITING_TOOLS)]
        assert not writing, (
            f"{path.name}, «{name}»: ревьюеру разрешена запись: {writing} — "
            "ответ обязан переносить механизм, а не агент"
        )


def test_review_is_not_a_required_context() -> None:
    """Ревью слияния не держит — и это НАЗВАНО, а не выражено отсутствием.

    Класс проверки объявлен данными проекта, поэтому и проверяется он в данных.
    Простое «ревью нет среди обязательных» здесь недостаточно: молчание
    неотличимо от «забыли объявить», а объявленный класс `advisory` говорит,
    что канал совещательный намеренно, и обязывает красное оставить запись
    адресату, переживающему слияние (142).
    """
    checks = yaml.safe_load((ROOT / ".pipeline.yml").read_text(encoding="utf-8"))["checks"]
    answer = checks.get("review")
    assert answer is not None, (
        "ревью не названо в ответе проекта: «не держит» неотличимо от «забыли»"
    )
    klass = answer["class"] if isinstance(answer, dict) else answer
    assert klass == "advisory", f"ревью объявлено «{klass}», а обязано быть совещательным"


# --- прогон и его зависимости ------------------------------------------------


@pytest.mark.parametrize("path", [AUTO_REVIEW, ON_MENTION], ids=lambda p: p.name)
def test_a_permitted_run_is_actually_possible(path: Path) -> None:
    """Что список разрешает запускать, то прогон обязан поставить.

    Замер: список позволял `python -m pytest`, но в джобе не было ни
    интерпретатора, ни самих проверок. Разрешение оставалось обещанием, ревью
    тихо съезжало на чтение — и вердикт «находок 0» после прогона выглядел так
    же, как после беглого просмотра (045). Отчёт по #32 прямо сказал, что
    прогнать не смог, и всё равно вынес вердикт.
    """
    tools = [tool for _, allowed in declared_tools(path) for tool in allowed]
    runs_python = [tool for tool in tools if tool.startswith(("Bash(python ", "Bash(python3 "))]
    if not runs_python:
        return

    text = path.read_text(encoding="utf-8")
    assert "setup-python" in text, f"{path.name}: разрешён запуск python, а его в джобе нет"
    assert "pytest" not in " ".join(runs_python) or "pip install" in text, (
        f"{path.name}: разрешён прогон тестов, но проверки не ставятся"
    )


@pytest.mark.parametrize("path", [AUTO_REVIEW, ON_MENTION], ids=lambda p: p.name)
def test_both_interpreter_names_are_permitted(path: Path) -> None:
    """Разрешение выдаётся по началу команды, и `python3` — другая строка.

    Ровно на этом ревью и осталось без прогона: разрешение у него было, а
    позвало оно другое имя.
    """
    for name, tools in declared_tools(path):
        for tool in tools:
            if not tool.startswith("Bash(python "):
                continue
            twin = tool.replace("Bash(python ", "Bash(python3 ", 1)
            assert twin in tools, (
                f"{path.name}, «{name}»: разрешено «{tool}», а его двойника с python3 нет"
            )


def scripts_called_by(path: Path) -> set[str]:
    """Имена скриптов проекта, которые зовёт этот прогон."""
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"python scripts/(\w+\.py)", text))


#: Импорт соседнего механизма: `import ghrest`, `import labels as x`.
LOCAL_IMPORT_RE = re.compile(r"^import (\w+)|^from (\w+) import", re.M)


def reads_yaml(name: str, seen: frozenset[str] = frozenset()) -> bool:
    """Нужен ли этому механизму разбор YAML — прямо ИЛИ через соседей.

    ПОЧЕМУ ОБХОД, А НЕ СПИСОК ИМЁН. Прежняя редакция смотрела прямой `import
    yaml` и одно имя соседа, вписанное руками. Список руками отстаёт от дерева
    молча: 10.09.2026 шаг `debt` стал звать `main_red`, тот тянет разбор
    состава проверок, а установку в прогон не добавили — и шаг упал на импорте,
    ДО входа в скрипт, то есть свой третий исход выдать не мог. На общей ветке
    это увидел не набор, а `main-red`
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

    Обход по дереву держится сам: новый сосед добавляется импортом, и гейт
    узнаёт о нём в тот же момент, что и интерпретатор.
    """
    script = ROOT / "scripts" / name
    if name in seen or not script.is_file():
        return False
    source = script.read_text(encoding="utf-8")
    if "import yaml" in source:
        return True
    return any(
        reads_yaml(f"{found}.py", seen | {name})
        for line in LOCAL_IMPORT_RE.findall(source)
        for found in line
        if found
    )


def jobs_of(path: Path) -> list[tuple[str, str]]:
    """Джобы прогона парами «имя, его текст».

    Текстом, а не разобранным деревом: предмет проверки — команды установки и
    запуска, они живут строками внутри `run:`, и собирать их обратно из дерева
    пришлось бы тем же разбором.

    ГРАНИЦА БЕРЁТСЯ ПО ВЛОЖЕННОСТИ ПОД `jobs:`, А НЕ ПО ОТСТУПУ. Ключи события
    — `push:`, `pull_request:`, `workflow_dispatch:` — тоже стоят на двух
    пробелах, и раздел `on:` считался тремя джобами: проверка ходила по чужому
    тексту и молчала бы о настоящем джобе, окажись он за ними. Замер 10.09.2026
    на `ci.yml`: «джобов» находилось 14 при 11 настоящих. Нашёл внешний взгляд
    на #100.
    """
    text = path.read_text(encoding="utf-8")
    head = re.search(r"^jobs:$", text, re.M)
    if head is None:
        return []
    body = text[head.end() :]
    found: list[tuple[str, str]] = []
    starts = [match.start() for match in re.finditer(r"^  (\w[\w-]*):$", body, re.M)]
    for place, start in enumerate(starts):
        finish = starts[place + 1] if place + 1 < len(starts) else len(body)
        piece = body[start:finish]
        found.append((piece.splitlines()[0].strip(" :"), piece))
    return found


def test_jobs_are_read_from_under_jobs(tmp_path: Path) -> None:
    """Ключи события джобами не считаются, а джоб за ними — находится.

    `push:` и соседи стоят на тех же двух пробелах, что и джобы, и раздел `on:`
    читался тремя джобами. Проверка ходила по чужому тексту — и молчала бы о
    настоящем джобе, окажись он за ними. Нашёл внешний взгляд на #100.
    """
    path = tmp_path / "w.yml"
    path.write_text(
        "name: x\non:\n  push:\n    branches: [main]\n  workflow_dispatch:\n"
        "jobs:\n  один:\n    steps: []\n  два:\n    steps: []\n",
        encoding="utf-8",
    )
    assert [name for name, _ in jobs_of(path)] == ["один", "два"]


def test_the_install_gate_is_red_on_a_broken_job(tmp_path: Path) -> None:
    """Гейт установки проверяется тем, что он ОБЯЗАН отвергнуть (140).

    Прежде он был подтверждён лишь тем, что проходит на сегодняшнем `ci.yml`, —
    а это говорит о `ci.yml`, а не о гейте. Синтетический вход: джоб зовёт
    скрипт с разбором YAML и не ставит его. Нашёл внешний взгляд на #100.
    """
    broken = tmp_path / "broken.yml"
    hungry = next(name for name in ROOT.glob("scripts/*.py") if reads_yaml(name.name))
    broken.write_text(
        "name: x\non:\n  push:\n    branches: [main]\n"
        "jobs:\n  голодный:\n    steps:\n"
        "      - name: поставить\n        run: python -m pip install --quiet pytest\n"
        f"      - name: работа\n        run: python scripts/{hungry.name}\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="не ставит его"):
        test_workflow_installs_what_its_scripts_import(broken)


def test_the_install_gate_is_green_when_the_job_installs(tmp_path: Path) -> None:
    """И зелёный, когда джоб ставит разбор сам — иначе гейт красен всегда."""
    whole = tmp_path / "whole.yml"
    hungry = next(name for name in ROOT.glob("scripts/*.py") if reads_yaml(name.name))
    whole.write_text(
        "name: x\non:\n  push:\n    branches: [main]\n"
        "jobs:\n  сытый:\n    steps:\n"
        '      - name: поставить\n        run: python -m pip install --quiet "pyyaml>=6,<7"\n'
        f"      - name: работа\n        run: python scripts/{hungry.name}\n",
        encoding="utf-8",
    )
    test_workflow_installs_what_its_scripts_import(whole)


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_workflow_installs_what_its_scripts_import(path: Path) -> None:
    """ДЖОБ ставит то, что нужно зовомому им скрипту — не файл, а джоб.

    Замер 09.09: `agent-pr` стал звать механизм, читающий состав меток, а
    установку разбора YAML в прогон не добавили. Шаг упал на импорте — ДО входа
    в скрипт, поэтому свой третий исход выдать не мог, — и прогон прочитал сбой
    как объявленное «секрет не задан», оставшись зелёным.

    Замер 10.09, ровно тот же класс и уже при живом гейте: шаг `debt` стал
    звать `main_red`, тот тянет разбор состава проверок. Гейт смотрел ФАЙЛ
    прогона, а `pyyaml` в `ci.yml` ставился соседним джобом — и проверка была
    зелёной на сломанном. Джобы окружений не делят
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    for name, text in jobs_of(path):
        hungry = sorted(
            item for item in re.findall(r"python scripts/(\w+\.py)", text) if reads_yaml(item)
        )
        if hungry:
            assert "pyyaml" in text.lower(), (
                f"{path.name}, джоб «{name}» зовёт скрипт с разбором YAML, "
                f"но не ставит его: {sorted(set(hungry))}"
            )


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_exit_codes_are_read_as_an_allowlist(path: Path) -> None:
    """Зелёными считаются только объявленные коды, всё прочее — отказ.

    Обратный порядок — «красным считаем перечисленное» — уже стоил зелёного
    прогона на сломанном шаге: Python отдал единицу при необработанном сбое, а
    она в разборе значила объявленное состояние (068, 045).
    """
    text = path.read_text(encoding="utf-8")
    if "|| rc=$?" not in text:
        return
    assert 'case "$rc"' in text, (
        f"{path.name} разбирает код возврата условиями вместо списка разрешённого"
    )


#: Действие соседа, к ВЕРСИИ КОНТРАКТА которого проект прибит сознательно.
#: Здесь тег — не подвижная метка, а предмет договора: потребитель прибивается к
#: тегу, а не к общей ветке, и подъём версии обязан быть перечитыванием ответов,
#: а не тихой подменой кода
#: ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).
#: Список разрешительный и с причиной: тихого исключения здесь нет (068).
BY_CONTRACT_TAG = ("ArtVsMark/Engineering-Incidents-Playbook@",)

#: События, на которых площадка берёт файл прогона с ОБЩЕЙ ветки, а не из
#: изменения. Ровно там закрепление вызываемого что-то значит.
SHARED_CALLER = ("workflow_run", "pull_request_target", "schedule")


def shared_caller(document: dict[Any, Any]) -> bool:
    """Берётся ли файл этого прогона с общей ветки."""
    events = document[True]
    names = set(events) if isinstance(events, dict) else set(events or [])
    return bool(names & set(SHARED_CALLER))


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_a_shared_caller_pins_what_it_calls(path: Path) -> None:
    """Где вызывающий берётся с общей ветки, вызываемое закреплено по SHA.

    Правило [152](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/152-pinning-callee-without-caller.md)
    ставит вопрос не «закреплять ли вообще», а «где это что-то значит». На
    `pull_request` площадка берёт файл прогона ИЗ ИЗМЕНЕНИЯ: кто правит
    изменение, правит и шаг целиком, и закрепление ничего не добавляет. На
    `workflow_run` и `pull_request_target` рассуждение переворачивается — файл
    берётся с общей ветки, и подвижная метка меняет исполняемый код без нашего
    ведома.

    ЗАМЕР 10.09.2026, найден разбором соседей: у `automerge` и `main-red` —
    обоих на `workflow_run` — действия стояли на метках `@v4` и `@v5`, тогда
    как в прогоне ревью те же действия давно закреплены по SHA. Правило
    держалось там, где о нём помнили, и не держалось там, где оно как раз
    и работает.
    """
    document = load(path)
    if not shared_caller(document):
        return
    unpinned = [
        step["uses"]
        for job in document["jobs"].values()
        for step in job.get("steps") or []
        if step.get("uses")
        and not SHA_PIN.search(step["uses"])
        and not step["uses"].startswith(BY_CONTRACT_TAG)
    ]
    assert not unpinned, (
        f"{path.name} идёт от общей ветки, а вызывает незакреплённое: {unpinned} — "
        "подвижная метка здесь меняет исполняемый код без нашего ведома (152)"
    )


def test_the_pinning_gate_found_its_subject() -> None:
    """Предмет проверки найден: прогоны от общей ветки в дереве есть (075)."""
    from_shared = [path.name for path in WORKFLOWS.glob("*.yml") if shared_caller(load(path))]
    assert from_shared, "ни один прогон не идёт от общей ветки — проверять нечего"


# --- карта взгляда -----------------------------------------------------------

#: Образец ссылки на правило внутри промпта: «(039)», «(005, 127)». Ровно та
#: форма, которой был написан прежний рукописный список.
RULE_IN_PROMPT = re.compile(r"\((\d{3})(?:,\s*\d{3})*\)")
#: Правила, которые промпт называть ВПРАВЕ и после появления карты: они говорят
#: не «что проверить», а как устроен сам канал взгляда. Список закрытый, и
#: каждое имя здесь названо с причиной — иначе он снова станет свалкой.
PROMPT_MAY_NAME = {
    "085": "недоверенный вход: этим абзацем канал признаёт отсутствие изоляции",
    "142": "у находки есть адресат — про устройство канала, а не про предмет",
    "152": "почему изменение, правящее сам прогон, ревью не получает",
    "084": "почему красное ревью не держит слияние",
    "090": "почему карта собирается механизмом, а не пишется руками",
}


def prompts_of(path: Path) -> list[str]:
    """Тексты промптов агента в прогоне: их и проверяем."""
    text = path.read_text(encoding="utf-8")
    if "prompt: |" not in text:
        return []
    found: list[str] = []
    for chunk in text.split("prompt: |")[1:]:
        lines: list[str] = []
        for line in chunk.splitlines()[1:]:
            if line.strip() and not line.startswith(" " * 12):
                break
            lines.append(line)
        found.append("\n".join(lines))
    return found


def test_the_prompt_does_not_keep_its_own_list_of_rules() -> None:
    """Список правил в промпте не ведётся руками: он приходит картой.

    Замер 10.09.2026: в промпте стояли десять правил «спрашивай по существу», и
    семь из них к тому дню уже держались гейтами — то есть внешний взгляд звали
    на работу, которую машина делает точнее. Рукописный список устаревает молча
    (005), а второе место, где то же знание ведётся отдельно, расходится с
    первым (090).
    """
    said: dict[str, set[str]] = {}
    for path in WORKFLOWS.glob("*.yml"):
        for prompt in prompts_of(path):
            if "steps.map.outputs" not in prompt:
                continue
            names = {
                number
                for found in RULE_IN_PROMPT.finditer(prompt)
                for number in re.findall(r"\d{3}", found.group())
            }
            extra = names - set(PROMPT_MAY_NAME)
            if extra:
                said[path.name] = extra
    assert not said, f"промпт снова ведёт свой список правил: {said}"


def test_the_map_is_taken_from_the_shared_branch() -> None:
    """Карта читается с общей ветки, а не из головы изменения.

    Голову пишет тот, кого проверяют: изменение, правящее ответ каталогу, могло
    бы объявить все правила машинными и получить взгляд, которому некуда
    смотреть (085).
    """
    text = (WORKFLOWS / "review.yml").read_text(encoding="utf-8")
    calls = [line for line in text.splitlines() if "review_map.py" in line]
    assert calls, "карта не собирается вовсе"
    for line in calls:
        words = line.split()
        assert "--base" in words, f"карта собрана без базы: {line.strip()}"
        base = words[words.index("--base") + 1]
        # `FETCH_HEAD` — это база, подтянутая шагом; `HEAD` — голова изменения.
        # Разница здесь и есть весь смысл проверки, поэтому сравнение точное.
        assert base != "HEAD", f"карта взята из головы изменения: {line.strip()}"


def test_the_registry_is_swept_outside_a_review() -> None:
    """Уборка разобранного идёт СВОИМ заходом, а не попутно с чужим разбором.

    Снятие находки объявляет тело СЛИТОГО изменения, значит и момент уборки
    задаёт слияние. Пока она шла только внутри разбора очередного изменения,
    опустевшая очередь означала, что разобранное висит в реестре навсегда: убрать
    его некому, — и приёмка «реестр пуст и держится сутки» была недостижима не
    из-за работы, а из-за устройства.
    """
    text = (WORKFLOWS / "review.yml").read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    sweeping = [
        name
        for name, job in document["jobs"].items()
        if any("--sweep" in str(step.get("run", "")) for step in job.get("steps", []))
    ]
    assert sweeping, "ключ --sweep не подключён ни к одному джобу — правило без механизма (002)"
    for name in sweeping:
        condition = str(document["jobs"][name].get("if", ""))
        assert "pull_request" not in condition, (
            f"{name}: уборка привязана к событию изменения — на пустой очереди она не пойдёт"
        )


def test_a_job_condition_names_its_events_instead_of_excluding_them() -> None:
    """Условие джоба ПЕРЕЧИСЛЯЕТ события, а не исключает одно.

    «Не изменение» — список запрещённого: стоит завести третье событие, и джоб
    поедет на нём молча
    ([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
    Ровно это и случилось бы с уборкой, добавленной четвёртым событием.
    """
    document = yaml.safe_load((WORKFLOWS / "review.yml").read_text(encoding="utf-8"))
    denying = [
        name for name, job in document["jobs"].items() if "event_name !=" in str(job.get("if", ""))
    ]
    assert not denying, f"условие исключает событие вместо перечисления: {denying}"


def test_a_failed_fetch_never_falls_back_to_the_head() -> None:
    """Не получилась общая ветка — карта не собирается вовсе.

    Проверка `--base FETCH_HEAD` смотрит на ТЕКСТ и потому слепа к тому, ЧЕМ
    окажется `FETCH_HEAD` в прогоне. Без проверки кода возврата `git fetch`
    сбой сети оставлял бы там то, что положил `actions/checkout`, — голову
    самого изменения. Сбой превращался бы ровно в ту подмену, от которой шаг и
    заведён (085). Нашёл внешний взгляд на #120.

    Проверяются ОБА экземпляра шага — у взгляда на изменение и у позднего:
    починка одного конца из двух здесь уже стоила находки (195).
    """
    text = (WORKFLOWS / "review.yml").read_text(encoding="utf-8")
    fetches = [line for line in text.splitlines() if "git fetch" in line and "origin" in line]
    assert fetches, "общая ветка не подтягивается вовсе — предмет проверки не найден (075)"
    for line in fetches:
        assert line.strip().startswith("if git fetch"), (
            f"код возврата фетча не проверяется, и сбой подменит базу головой: {line.strip()}"
        )


def test_the_output_delimiter_is_not_guessable() -> None:
    """Разделитель блока в `$GITHUB_OUTPUT` случаен, а не постоянен.

    В карту попадают заголовки правил, приходящие ПО СЕТИ из выгрузки соседнего
    репозитория, не закреплённой по отпечатку. Строка с ПОСТОЯННЫМ маркером
    внутри такого текста закрыла бы блок раньше времени — и дописала бы в вывод
    шага что угодно. Нашёл внешний взгляд на #120.
    """
    text = (WORKFLOWS / "review.yml").read_text(encoding="utf-8")
    heredocs = [line for line in text.splitlines() if "text<<" in line]
    assert heredocs, "блок вывода не собирается — предмет проверки не найден (075)"
    for line in heredocs:
        assert "$" in line.split("text<<", 1)[1], (
            f"разделитель постоянен и угадывается из дерева: {line.strip()}"
        )


def test_a_missing_map_does_not_stop_the_look() -> None:
    """Карта не собралась — взгляд идёт без неё, а не отменяется.

    Канал совещательный: потерять взгляд целиком из-за подсказки к нему — тот
    самый худший размен, от которого предостерегает 084.
    """
    text = (WORKFLOWS / "review.yml").read_text(encoding="utf-8")
    for chunk in text.split("id: map")[1:]:
        head = chunk[: chunk.index("- name:")] if "- name:" in chunk else chunk
        assert "continue-on-error: true" in head, "отказ сборки карты роняет шаг"
