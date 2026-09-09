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


def declared_tools(path: Path) -> list[str]:
    """Достаёт объявленный список инструментов агента из шага прогона.

    Читается значение ключа, а не файл целиком: в комментариях рядом слово
    «Bash» встречается по делу, и поиск по тексту дал бы находку на пояснении,
    а не на списке.
    """
    for job in load(path)["jobs"].values():
        for step in job["steps"]:
            args = (step.get("with") or {}).get("claude_args", "")
            match = re.search(r'--allowedTools\s+"([^"]+)"', args)
            if match:
                return [tool.strip() for tool in match.group(1).split(",") if tool.strip()]
    raise AssertionError(f"{path.name}: список инструментов агента не объявлен")


@pytest.mark.parametrize("path", [AUTO_REVIEW, ON_MENTION], ids=lambda p: p.name)
def test_agent_tools_are_an_allowlist_without_bare_bash(path: Path) -> None:
    """Инструменты агента — закрытый список, и голого `Bash` в нём нет.

    Список инструментов — единственный барьер против указания «выполни команду и
    отправь результат наружу», пришедшего из проверяемого текста (085).
    """
    tools = declared_tools(path)
    assert tools, f"{path.name}: список пуст — это не ограничение, а его отсутствие (075)"
    bare = [tool for tool in tools if tool == "Bash" or tool.startswith("Bash ")]
    assert not bare, f"{path.name}: разрешён Bash без ограничения команды: {bare}"
    for tool in tools:
        if tool.startswith("Bash"):
            assert tool.startswith("Bash(") and tool.endswith(")"), f"{path.name}: {tool}"


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
    tools = declared_tools(path)
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
    tools = declared_tools(path)
    for tool in tools:
        if not tool.startswith("Bash(python "):
            continue
        twin = tool.replace("Bash(python ", "Bash(python3 ", 1)
        assert twin in tools, f"{path.name}: разрешено «{tool}», а его двойник с python3 — нет"


def scripts_called_by(path: Path) -> set[str]:
    """Имена скриптов проекта, которые зовёт этот прогон."""
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"python scripts/(\w+\.py)", text))


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_workflow_installs_what_its_scripts_import(path: Path) -> None:
    """Прогон ставит то, что нужно зовомому им скрипту.

    Замер: `agent-pr` стал звать механизм, читающий состав меток, а установку
    разбора YAML в прогон не добавили. Шаг упал на импорте — ДО входа в скрипт,
    поэтому свой третий исход выдать не мог, — и прогон прочитал сбой как
    объявленное «секрет не задан», оставшись зелёным.
    """
    text = path.read_text(encoding="utf-8")
    scripts_dir = ROOT / "scripts"
    needs_yaml = False
    for name in scripts_called_by(path):
        script = scripts_dir / name
        if not script.is_file():
            continue
        source = script.read_text(encoding="utf-8")
        # Прямо или через общий модуль состава — YAML нужен в обоих случаях.
        if "import yaml" in source or "import labels" in source:
            needs_yaml = True
    if needs_yaml:
        assert "pyyaml" in text.lower(), (
            f"{path.name} зовёт скрипт с разбором YAML, но не ставит его"
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
