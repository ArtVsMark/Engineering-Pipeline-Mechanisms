#!/usr/bin/env python3
"""Собирает факты о проекте и один значок для ветки `badges`.

Факты о проекте публикует сам проект
([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)):
соседу, каталогу правил и витрине нужно знать, на какой версии контракта стоит
проект и сколько правил он держит, — и узнавать это чтением его дерева никто не
обязан.

ПРОИЗВОДНОЕ НЕ ЖИВЁТ РЯДОМ С ИСТОЧНИКОМ
([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-generated-file-is-not-a-store.md)).
Вывод этого механизма уезжает в отдельную ветку `badges` и там перезаписывается
целиком: его можно удалить и собрать заново, ничего не потеряв. В общей ветке
он протухал бы молча — и число из него разошлось бы с источником на первой же
правке
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

Числа берутся из источников, а не из памяти: `CONTRACT_VERSION`,
`.rules/bindings.json`, `.pipeline.yml`. Источник у каждого числа один
([035](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/035-version-is-never-edited-by-hand.md)).

Исходы: ``0`` собрано · ``2`` не собрать. Третьего здесь нет, и это названо, а
не пропущено: состояние «собрано, но с находками» у сборки фактов отсутствует —
источники проверяют их собственные гейты, а этот механизм либо прочитал их и
собрал, либо не смог. Правило 039 требует, чтобы исходы были объявлены и
различались, а не чтобы их было ровно три
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple

import family
import kinds
import paths
import pipeline_checks as policy
import version

VERSION_FILE: Final = paths.VERSION
BINDINGS: Final = paths.BINDINGS
FACTS: Final = "facts.json"
#: ГДЕ ЛЕЖАТ ФАКТЫ И ЗНАЧКИ — ПО КОНТРАКТУ СЕМЬИ, а не по своей раскладке:
#: ветка `badges`, путь `.github/badges/` — как у грейдера, каталога, токенов и
#: глоссария (контракт фактов витрины, `ArtVsMark/ArtVsMark` ·
#: `.rules/facts-contract.md`; решение владельца 24.09.2026, #759). До этого
#: файл лежал в корне ветки, и витрина считала, что фактов у проекта нет.
PUBLISHED_DIR: Final = paths.BADGES_DIR
#: Версия формата — СТРОКОЙ, как требует контракт: число не различает `1.0` и
#: `1.10`. Мажор — контракта семьи, а не наш: наши собственные разделы едут
#: рядом незнакомыми ему ключами, и их он игнорирует.
SCHEMA: Final = "1.2"
SCHEMA_OF: Final = (
    "контракт фактов витрины семьи: "
    "https://github.com/ArtVsMark/ArtVsMark/blob/main/.rules/facts-contract.md"
)

#: Список разрешённого (068): статус, которого здесь нет, — это дефект ответа,
#: а не новая тонкость, о которой механизм обязан догадаться.
STATUSES: Final = ("active", "rejected", "not-applicable", "unreviewed")

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Сборка не отработала: третий исход, а не пустые факты."""


def contract_version(path: Path = VERSION_FILE) -> str:
    """Читает версию контракта из единственного её источника."""
    if not path.is_file():
        raise NotRun(f"нет версии контракта: {path}")
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise NotRun(f"{path} пуст — это ошибка входа, а не «версии нет» (075)")
    return version


def rules_facts(path: Path = BINDINGS) -> dict[str, Any]:
    """Считает ответ проекта по правилам каталога.

    Считается не «сколько правил хороших», а чем они держатся: механизм и
    документ — оба законные ответы, и разница между ними видна только числом.
    """
    if not path.is_file():
        raise NotRun(f"нет ответа каталогу: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc

    rules = document.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise NotRun(f"{path}: раздел rules пуст — предмет счёта не найден (075)")

    statuses: Counter[str] = Counter()
    mechanisms: Counter[str] = Counter()
    for number, answer in rules.items():
        if not isinstance(answer, dict):
            raise NotRun(f"{path}: ответ по правилу {number} не отображение")
        status = str(answer.get("status", "")).strip()
        if status not in STATUSES:
            raise NotRun(f"{path}: правило {number} несёт статус «{status}», которого нет в схеме")
        statuses[status] += 1
        if status == "active":
            mechanism = str(answer.get("mechanism", "")).strip()
            if not mechanism:
                raise NotRun(f"{path}: правило {number} действует, но чем — не сказано")
            mechanisms[mechanism] += 1

    return {
        "total": len(rules),
        "answered": len(rules) - statuses["unreviewed"],
        "by_status": {status: statuses[status] for status in STATUSES},
        "by_mechanism": dict(sorted(mechanisms.items())),
    }


def checks_facts(path: Path = policy.DEFAULT_PATH) -> dict[str, Any]:
    """Проверки на изменении: число, имена и разбивка по классам.

    ОТВЕЧАЕТ НА ВОПРОС КОНТРАКТА — «сколько проверок стоит на изменении»
    (`checks_per_pr`, #759), и потому считает ПЕРВЫЙ раздел `.pipeline.yml`,
    а не весь конвейер. Прежний ключ `checks` считал оба раздела — прогоны вне
    изменения туда входили, и витрина получала на свой вопрос не то число.
    Имена едут рядом с числом: контракт даёт их, чтобы число проверяли, а не
    принимали на веру.
    """
    try:
        checks = policy.load(path)
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc
    by_class = {klass: policy.names_of(checks, klass) for klass in policy.CLASSES}
    names = sorted(name for found in by_class.values() for name in found)
    return {
        "count": len(names),
        "names": names,
        "by_class": {klass: len(found) for klass, found in by_class.items()},
    }


def family_facts(
    path: Path | None, *, mine: str = "", answers: Path | None = None
) -> dict[str, Any]:
    """Разрез по общим механизмам семьи — вторая ось приоритета переноса.

    ПОЧЕМУ ЭТО ЗДЕСЬ, А НЕ У КАТАЛОГА. Решение владельца 09.09.2026: считает и
    публикует проект механизмов, потому что вопрос его — «окупается ли общий
    модуль». Данные при этом чужие и уже собранные: второй сборщик тех же
    чисел разошёлся бы с первым молча (022).

    СВОДКИ МОЖЕТ НЕ БЫТЬ, И ЭТО СОСТОЯНИЕ, А НЕ НОЛЬ. Ветка каталога
    недоступна, файл не скачался, форма разошлась — во всех случаях числа
    НЕИЗВЕСТНЫ, и нулевая доля выглядела бы как «общие механизмы ничего не
    закрывают»
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    if path is None or not path.is_file():
        return {"read": False, "why": "сводка семьи не прочитана — числа неизвестны, а не нулевые"}
    try:
        # Разбор ОДИН: `family.load` читал файл дважды за вызов — для разреза и
        # для отставания, — и второе чтение могло прийти уже другим (022).
        # Нашёл внешний взгляд на #240.
        summary_read = family.load(path)
        picture = family.picture(summary_read)
    except family.NotRun as exc:
        return {"read": False, "why": str(exc)}
    # Форма чужая: её подъём — повод перечитать разрез, а не подвинуть число
    # (157). Расхождение называется рядом с числами, а не прячется.
    picture["read"] = True
    picture["schema_expected"] = family.READS_SCHEMA
    picture["schema_agrees"] = picture["schema_read"] == family.READS_SCHEMA
    # ОТСТАВАНИЕ ОТ СЕМЬИ — ВТОРОЕ ЧИСЛО ЭТОГО РАЗРЕЗА, И ОНО ПРО НАС. Доля
    # общих механизмов отвечает «окупается ли вынос», а это — «удовлетворяет ли
    # конвейер потребности семьи»: сколько правил сосед закрывает машиной там,
    # где у нас документ или «неприменимо». Цель без числа остаётся ощущением
    # (`docs/decisions/016-family-completeness-outranks-the-release-number.md`).
    #
    # НАШИ ОТВЕТЫ ЧИТАЮТСЯ ИЗ ДЕРЕВА, а соседей — из снимка: снимок наших
    # отстаёт на смену, и «отставание» вышло бы завышенным на нашу же работу.
    if not mine or answers is None or not answers.is_file():
        # НЕПОСЧИТАННОЕ НАЗЫВАЕТСЯ. Молчание здесь читалось бы как «отставания
        # нет», а отсутствие числа и нулевое число — разные состояния (045).
        # Нашёл внешний взгляд на #240.
        picture["behind_read"] = False
        picture["behind_why"] = (
            "отставание не посчитано: не названо наше имя у площадки (--repo) "
            f"либо не найден файл ответов ({answers})"
        )
        return picture
    try:
        ours = json.loads(answers.read_text(encoding="utf-8"))["rules"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        # ДЕФЕКТНЫЙ ОТВЕТ — ОТКАЗ, А НЕ ПУСТОЙ СЛОВАРЬ. Пустой дал бы
        # отставание, равное числу ВСЕХ машинных ответов семьи: правдоподобное
        # число, которое ложь. Нашёл внешний взгляд на #240.
        picture["behind_read"] = False
        picture["behind_why"] = f"наши ответы не прочитаны: {exc}"
        return picture
    if not isinstance(ours, dict) or not ours:
        picture["behind_read"] = False
        picture["behind_why"] = "в наших ответах нет ни одного правила — считать нечего (075)"
        return picture
    left = family.behind(summary_read, mine=mine, ours=ours)
    picture["behind_read"] = True
    picture["behind"] = len(left)
    picture["behind_rules"] = left
    return picture


def test_counts(root: Path) -> dict[str, int]:
    """Сколько тестов и тестовых модулей в наборе.

    Считается ПО ДЕРЕВУ, а не прогоном: прогон даёт то же число дороже и не в
    том месте. Тест узнаётся по объявлению `def test_`; второго счётчика той же
    территории не заводится (022). Имена ключей — контракта семьи:
    `functions` и `modules` (#759).
    """
    modules = sorted((root / "tests").glob("test_*.py"))
    total = 0
    for path in modules:
        lines = path.read_text(encoding="utf-8").splitlines()
        total += sum(1 for line in lines if line.startswith("def test_"))
    return {"functions": total, "modules": len(modules)}


def script_runs(root: Path) -> dict[str, int]:
    """Сколько механизмов набор запускает ОТДЕЛЬНЫМ ПРОЦЕССОМ — и сколько их всего.

    ПОЧЕМУ ЭТО ОТДЕЛЬНОЕ ЧИСЛО, А НЕ ЧАСТЬ ПОКРЫТИЯ. Гейт проверяется запуском:
    тест зовёт модуль процессом и смотрит ИСХОД — то, ради чего гейт и
    существует. Счётчик покрытия про такой прогон долго не знал вовсе, и четыре
    полностью проверенных модуля показывали ноль. Число ниже считается по
    дереву и не зависит ни от счётчика, ни от того, включён ли замер.

    ЗНАМЕНАТЕЛЬ — ЗАПУСКАЕМЫЕ, А НЕ ВСЕ. Модуль без точки входа процессом не
    запускается по устройству (`paths.py`, `journal.py`), и требовать от него
    такого прогона значило бы мерить долг там, где его нет
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    # ГДЕ ЖИВЁТ КОД — ЧИТАЕТСЯ, а не перечисляется здесь: второе написание
    # состава расходится с первым молча (022, 090). Число от этого не меняется —
    # у общего низа точки входа нет, — но литерал был четвёртым по счёту, и
    # именно такой выпал бы при следующем переносе.
    # ИМЯ — НЕ ТОЖДЕСТВО МОДУЛЯ, когда каталогов два. Прежде множество ключевалось
    # `path.name`, и одноимённый модуль с точкой входа в обоих каталогах схлопнулся
    # бы МОЛЧА: знаменатель уменьшился, а витрина показала бы покрытие лучше
    # настоящего. Нашёл внешний взгляд находкой `2ce9aef` на #411 — риск, а не
    # дефект: одноимённых сегодня нет, и это проверено.
    #
    # Столкновение НАЗЫВАЕТСЯ, а не чинится подстановкой: набор зовёт механизм по
    # имени файла (`run_script("имя")`), и при двух одноимённых неизвестно, какой
    # из них прогнан. Выбрать за человека значило бы отчитаться о непроверенном
    # (045, 154).
    found: dict[str, list[str]] = {}
    for where in paths.SOURCES:
        for path in sorted((root / where).glob("*.py")):
            if any(
                isinstance(node, ast.FunctionDef) and node.name == "main"
                for node in ast.parse(path.read_text(encoding="utf-8")).body
            ):
                found.setdefault(path.name, []).append(f"{where.as_posix()}/{path.name}")
    # ИМЯ `where` выше означало КАТАЛОГ, здесь означало бы СПИСОК ПУТЕЙ. Одно
    # имя на два предмета в соседних строках читается как одно (нашёл внешний
    # взгляд на #412), поэтому список зовётся своим именем.
    same = {name: places for name, places in found.items() if len(places) > 1}
    if same:
        print(
            "::warning::одноимённые механизмы с точкой входа в разных каталогах: "
            + "; ".join(f"{name} — {', '.join(places)}" for name, places in sorted(same.items()))
            + ". Набор зовёт их по имени файла, и какой из них прогнан — неизвестно",
            file=sys.stderr,
        )
    tests = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((root / "tests").glob("*.py"))
    )
    started = {name for name in found if f'run_script("{name}"' in tests}
    # Знаменатель считается по МОДУЛЯМ, а числитель — по именам, которые набор
    # умеет позвать: это разные единицы, и при столкновении первое больше второго.
    return {"runnable": sum(len(where) for where in found.values()), "started": len(started)}


def coverage_facts(path: Path | None) -> dict[str, Any]:
    """Покрытие строк из отчёта счётчика; без отчёта — «не прочитано».

    ЧИСЛО ПРИХОДИТ ИЗ ПРОГОНА, А НЕ СЧИТАЕТСЯ ЗДЕСЬ. Считать покрытие по дереву
    нельзя: оно про исполнение, а не про текст. Отчёта нет — так и говорится;
    ноль вместо незнания читался бы как «ничего не покрыто» (045).

    ЗАМЕР ОБЯЗАН ВИДЕТЬ ПОДПРОЦЕССЫ. Гейты проверяются запуском, и счётчик без
    этого показывал ноль у полностью проверенных модулей: 66% против настоящих
    77%. Держит это `tests/conftest.py` (`under_counter`), а не договорённость.

    ДОЛЯ ЕДЕТ ВМЕСТЕ С ДВУМЯ ЧИСЛАМИ, ИЗ КОТОРЫХ СДЕЛАНА. «77 %» отвечает на
    вопрос «много ли», но не на «много ЧЕГО»: та же доля у дерева в сто строк и
    в десять тысяч значит разное, а падение с 77 до 70 бывает и новым кодом без
    проверок, и удалением покрытого
    ([041](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/041-two-honest-numbers-beat-one-averaged.md)).
    До 18.09.2026 витрина публиковала ОДНУ долю покрытия — единственное
    усреднённое число во всём наборе фактов, и единственное без своих слагаемых:
    у семьи доля стоит рядом с `closed_by_shared` из `held_by_machine`, у правил
    вместо доли пара «отвечено из всего».

    ОТСУТСТВИЕ ЧИСЕЛ — ОТКАЗ, А НЕ МОЛЧАНИЕ, и той же породы, что у доли выше:
    форма чужого отчёта меняется, и опубликовать долю без слагаемых значило бы
    вернуться к тому, что здесь и чинится (045).
    """
    if path is None or not path.is_file():
        return {"read": False}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise NotRun(f"отчёт покрытия не разобрался: {exc}") from exc
    totals = report.get("totals") or {}
    percent = totals.get("percent_covered")
    if percent is None:
        raise NotRun(f"{path}: в отчёте нет доли покрытия — форма ответа изменилась")
    covered, lines = totals.get("covered_lines"), totals.get("num_statements")
    if covered is None or lines is None:
        raise NotRun(
            f"{path}: в отчёте нет чисел, из которых сделана доля — форма ответа изменилась"
        )
    return {
        "read": True,
        "percent": round(float(percent), 1),
        "covered": int(covered),
        "lines": int(lines),
    }


def contract_coverage(said: dict[str, Any]) -> dict[str, Any]:
    """Покрытие в форме контракта: доля — наверху, слагаемые — в `coverage`.

    ДОЛЯ ОДНА, А НЕ ДВЕ: `coverage_percent` контракта заменяет прежнее
    `coverage.percent`, а не дублирует его (#759). Не прочитано — ключа
    `coverage_percent` нет вовсе, а причина стоит в `none.coverage_percent`:
    договор фактов 1.2 требует по каждому показателю значение или причину, и
    молчание третьим исходом не считается (#1001). Ноль читался бы как ответ.
    """
    parts = {key: value for key, value in said.items() if key != "percent"}
    if not said.get("read"):
        why = "отчёт покрытия этого прогона не прочитан — доля не мерилась, а не равна нулю"
        return {"coverage": parts, "none": {"coverage_percent": why}}
    return {"coverage": parts, "coverage_percent": said["percent"]}


#: Прогон CI, чей статус витрина спрашивает у площадки по имени файла: свой
#: красный файл фактов честно сказать не может (договор фактов 1.2, #1001).
CI_FLOW: Final = paths.WORKFLOWS / "ci.yml"
#: Джобы матрицы версий: поддерживаемые и пробные. Версии берутся из самой
#: матрицы, а не пишутся второй раз (005).
SUPPORTED_JOB: Final = "test-matrix"
EXPERIMENTAL_JOB: Final = "test-next"


def python_facts(path: Path = CI_FLOW) -> dict[str, list[str]]:
    """Версии Python, на которых проект гоняется, — из матрицы CI, а не по памяти.

    `supported` — матрица `test-matrix`, `experimental` — `test-next` из
    `python-next.yml`, `os` —
    образы, на которых они идут. Договор фактов витрины 1.2 требует раздел
    `python` либо причину в `none.python` (#1001): матрица у нас есть, поэтому
    раздел, а не причина. Матрицу читает `pipeline_checks` — читатель прогонов
    один; не прочитана — `policy.BadPolicy` с причиной.
    """
    supported, first = policy.matrix_axis(path, SUPPORTED_JOB, "python")
    # Предрелизная — своим прогоном рядом с `ci.yml` (#1018).
    experimental, second = policy.matrix_axis(
        path.with_name(paths.PYTHON_NEXT.name), EXPERIMENTAL_JOB, "python"
    )
    return {"supported": supported, "experimental": experimental, "os": sorted({first, second})}


def collect(
    root: Path,
    sha: str,
    summary: Path | None = None,
    coverage: Path | None = None,
    mine: str = "",
) -> dict[str, Any]:
    """Собирает все факты о проекте в одно отображение.

    `mine` — наше каноничное имя у площадки. Оно нужно ровно одному числу:
    отставанию от семьи, где своё надо отличить от чужого. Пусто — число не
    считается и говорит об этом, а не выходит нулём (045).
    """
    # ВЕРСИЯ ПРОЕКТА И ВЕРСИЯ КОНТРАКТА — РАЗНЫЕ ЧИСЛА, И ОБА НУЖНЫ. Контракт
    # объявляет поверхность механизмов и поднимается решением человека; версия
    # проекта СЧИТАЕТСЯ по истории — «столько изменений принято после выпуска».
    # Свести их в одно значило бы либо скрыть работу, либо объявить выпуском
    # каждое изменение (035).
    number, whole = version.version(root)
    # ЗНАЧЕНИЕ ИЛИ ПРИЧИНА, ТРЕТЬЕГО НЕТ (договор фактов 1.2, #1001): показатель,
    # который не прочитан, уходит причиной в `none`, а не пропадает молча.
    none: dict[str, str] = {}
    try:
        python: dict[str, list[str]] | None = python_facts(root / CI_FLOW)
    except policy.BadPolicy as exc:
        python, none["python"] = None, str(exc)
    covered = contract_coverage(coverage_facts(coverage))
    none.update(covered.pop("none", {}))
    said = {
        # МИНИМУМ КОНТРАКТА СЕМЬИ: версия формата строкой, о ком файл и когда
        # собран — с поясом, чтобы витрина могла сказать «факты устарели»
        # вместо того, чтобы показывать прошлое как настоящее (#759).
        "schema": SCHEMA,
        "schema_of": SCHEMA_OF,
        "repo": mine,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": sha,
        # Статус CI витрина спрашивает у площадки по имени файла (договор 1.2).
        "ci": {"workflow": CI_FLOW.name},
        **({"python": python} if python is not None else {}),
        "contract": contract_version(root / VERSION_FILE),
        "version": number,
        # Неполнота названа рядом с числом, а не выброшена: клон без тегов даёт
        # правдоподобное число, которое ложь (045).
        "version_whole": whole,
        # ВЫПУСК И ВЕРСИЯ ГОЛОВЫ — РАЗНЫЕ ЧИСЛА. Голова уходит вперёд каждым
        # изменением, потребитель живёт на выпущенном; одно вместо другого
        # обещало бы ему то, чего он не получал.
        "release": version.release_tag(root) or "",
        # Числа для вопросов СОПРОВОЖДАЮЩЕГО из .rules/showcase.json: значок им
        # не нужен и вреден — они дёргаются от каждого изменения, — но живой
        # адрес обязателен, и вот он (049).
        "tests": test_counts(root),
        # Гейты проверяются ЗАПУСКОМ, и это отдельный предмет от покрытия строк:
        # исход процесса — то, ради чего гейт существует.
        "scripts": script_runs(root),
        # Покрытие строк приходит из прогона: по дереву его не сосчитать.
        **covered,
        "rules": rules_facts(root / BINDINGS),
        "checks_per_pr": checks_facts(root / policy.DEFAULT_PATH),
        "family": family_facts(summary, mine=mine, answers=root / BINDINGS),
    }
    if none:
        said["none"] = none
    return said


class Badge(NamedTuple):
    """Значок как данные: подпись, значение и цвет — одна запись на два вывода."""

    label: str
    message: str
    color: str


def badge(label: str, value: str, color: str) -> Badge:
    """Значок из своих чисел; как его показать, решает вывод, а не рисовалка."""
    return Badge(label, value, color)


def svg(drawn: Badge) -> str:
    """Рисует значок сам, без обращения к чужой службе.

    Значок с чужого сервиса — это внешняя зависимость витрины: она отвалится
    молча и оставит вместо числа пустое место, которое читается как «всё в
    порядке». Здесь SVG собирается из своих же чисел и лежит рядом с ними.
    """
    label, value, color = drawn
    # Ширина считается по числу знаков: точной метрики шрифта у нас нет, а
    # приблизительная лучше, чем обрезанный текст.
    left = 8 * len(label) + 12
    right = 8 * len(value) + 12
    width = left + right
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" '
        f'role="img" aria-label="{label}: {value}">'
        f"<title>{label}: {value}</title>"
        f'<rect width="{left}" height="20" fill="#555"/>'
        f'<rect x="{left}" width="{right}" height="20" fill="{color}"/>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{left / 2}" y="14">{label}</text>'
        f'<text x="{left + right / 2}" y="14">{value}</text>'
        f"</g></svg>"
    )


#: Форма значка, которую читает shields.io по адресу `endpoint?url=…`.
ENDPOINT_SCHEMA: Final = 1


def endpoint(drawn: Badge) -> dict[str, Any]:
    """Значок формой shields-endpoint: так значки показывает вся семья (#998).

    ЧУЖАЯ СЛУЖБА — ЦЕНА, И ОНА ПРИНЯТА (владелец, 01.10.2026). Довод `svg`
    против неё в силе, но отказ здесь не молчит: не ответившая служба
    показывает подпись картинки или «inaccessible», а не правдоподобное число.
    Числа по-прежнему наши: служба лишь рисует то, что лежит в этом файле.
    """
    return {
        "schemaVersion": ENDPOINT_SCHEMA,
        "label": drawn.label,
        "message": drawn.message,
        "color": drawn.color.lstrip("#"),
    }


def endpoint_name(name: str) -> str:
    """Имя файла shields-endpoint рядом со значком: то же имя, расширение `.json`."""
    return str(Path(name).with_suffix(".json"))


def published_names() -> list[str]:
    """Всё, что сборка кладёт в каталог публикации: факты, значки и их endpoint."""
    return [FACTS, *BADGES, *map(endpoint_name, BADGES)]


def clashing_names() -> list[str]:
    """Имена вывода, которые встречаются дважды (взгляд на #1002).

    Endpoint выводится из имени значка, а каталог публикации общий с фактами:
    значок `facts.svg` дал бы `facts.json` и молча затёр бы контракт фактов
    семьи. Столкновение — отказ сборки, а не перезапись.
    """
    names = published_names()
    return sorted({name for name in names if names.count(name) > 1})


#: Роды ответа, означающие «держит машина». Тот же состав, что у разреза семьи
#: и у дрейфа: три понимания одного слова разошлись бы молча (090).
#: Виды механизма — из общего места (`scripts/kinds.py`), а не своей копией.
MACHINE: Final = kinds.MACHINE


def rules_badge(facts: dict[str, Any]) -> Badge:
    """Сколько ДЕЙСТВУЮЩИХ правил держится машиной, а не документом.

    ПОЧЕМУ НЕ «ОТВЕЧЕНО». Прежняя редакция показывала `answered/total` и
    подписывала это «правил держится». Число было `195/195` и не могло стать
    другим: проект отвечает по каждому правилу каталога по построению (129).
    Значок, который не движется, — украшение: он не говорит, где проект стоит, и
    не может сказать, что тот сдвинулся. Нашёл это владелец, спросив, почему
    статистика собирается не вся.

    ЗНАМЕНАТЕЛЬ — ДЕЙСТВУЮЩИЕ, А НЕ ВСЕ. Неприменимое правило машиной не
    держится и держаться не должно; считать его в знаменателе значило бы
    занижать долю за то, у чего нет предмета (154).
    """
    kinds = facts["rules"]["by_mechanism"]
    machine = sum(int(count) for name, count in kinds.items() if name in MACHINE)
    active = sum(int(count) for count in kinds.values())
    share = machine / active if active else 0.0
    color = "#e05d44" if share < 0.34 else "#dfb317" if share < 0.67 else "#4c1"
    return badge("держится машиной", f"{machine}/{active}", color)


def family_badge(facts: dict[str, Any]) -> Badge:
    """Доля машинного соблюдения семьи, которую закрывают ОБЩИЕ механизмы.

    Это прямое мерило «второго исхода» эпика #2: если общий модуль окупается,
    доля растёт; если нет — стоит на месте, и это видно числом, а не ощущением.
    Снимок не пришёл — значок не выдумывается, а говорит «нет данных» (045).
    """
    picture = facts.get("family") or {}
    share = picture.get("share")
    if not isinstance(share, int | float) or not picture.get("consumers"):
        return badge("общие механизмы", "нет данных", "#9f9f9f")
    percent = round(float(share) * 100)
    color = "#e05d44" if percent < 30 else "#dfb317" if percent < 60 else "#4c1"
    return badge("общие механизмы", f"{percent}% семьи", color)


def scripts_badge(facts: dict[str, Any]) -> Badge:
    """Сколько запускаемых механизмов набор гоняет процессом.

    Порог здесь не назначен, а взят у того же правила, что и прочие значки:
    цвет говорит о доле, а решает человек. Число без знаменателя ничего не
    значит, поэтому показываются оба (005).
    """
    counts = facts.get("scripts") or {}
    runnable = int(counts.get("runnable") or 0)
    started = int(counts.get("started") or 0)
    if not runnable:
        return badge("гейты прогоном", "нет данных", "#9f9f9f")
    share = started / runnable
    color = "#4c1" if share >= 0.8 else "#dfb317" if share >= 0.5 else "#e05d44"
    return badge("гейты прогоном", f"{started}/{runnable}", color)


def coverage_badge(facts: dict[str, Any]) -> Badge:
    """Доля покрытых строк — или прямое «не прочитано»."""
    if "coverage_percent" not in facts:
        return badge("покрытие", "не прочитано", "#9f9f9f")
    percent = float(facts["coverage_percent"])
    color = "#4c1" if percent >= 85 else "#dfb317" if percent >= 70 else "#e05d44"
    return badge("покрытие", f"{percent:g}%", color)


def release_badge(facts: dict[str, Any]) -> Badge:
    """Последний выпуск: то, к чему потребитель прибивается тегом.

    Версия головы и выпуск — РАЗНЫЕ числа, и оба нужны: голова уходит вперёд
    каждым изменением, а потребитель живёт на выпущенном. Показывать одно
    вместо другого значило бы обещать ему то, чего он не получал.

    Выпусков ещё не было — сказано словом: пустой значок и «не выпускался»
    снаружи одинаковы (045).
    """
    said = str(facts.get("release") or "")
    return badge("выпуск", said, "#4c1") if said else badge("выпуск", "не выпускался", "#9f9f9f")


def version_badge(facts: dict[str, Any]) -> Badge:
    """Версия проекта: она СЧИТАЕТСЯ по истории, и значок показывает счёт.

    Неполнота названа цветом и словом: клон без тегов даёт правдоподобное
    число, которое ложь, и молчать об этом нельзя (045).
    """
    number = str(facts.get("version") or "?")
    whole = bool(facts.get("version_whole"))
    said = number if whole else f"{number} (неполно)"
    return badge("версия", said, "#4c1" if whole else "#dfb317")


#: ЧТО СБОРКА РИСУЕТ — ОБЪЯВЛЕНО ЗДЕСЬ ОДИН РАЗ: имя файла → чем его рисуют.
#: Рядом с каждым SVG публикуется его shields-endpoint (`endpoint_name`): витрина
#: переходит на него вторым изменением, после первого прогона публикации (196).
#: Порядок записей — порядок сборки.
#:
#: ПОЧЕМУ ЭТО ДАННЫЕ, А НЕ ШЕСТЬ КОНСТАНТ И КОРТЕЖ ВНУТРИ `main`. Список нужен
#: не только сборке: гейт витрины спрашивает «всё ли нарисованное названо», и
#: спросить ему было не у кого. Прежняя редакция гейта держала свой список из
#: ЧЕТЫРЁХ имён, выписанных рукой, — `scripts.svg` и `coverage.svg` в него не
#: попали, и проверка «нарисованное доезжает до витрины» два месяца сверяла
#: память автора с README, а не сборку с витриной. Тот же класс, что #183, где
#: гейт производного сверялся сам с собой. Инвентарь в одном месте убирает
#: второй список как таковой: добавить значок — правка этих строк, и обе
#: стороны узнают о нём в тот же миг
#: ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
BADGES: Final[dict[str, Callable[[dict[str, Any]], Badge]]] = {
    "rules.svg": rules_badge,
    "family.svg": family_badge,
    "version.svg": version_badge,
    "release.svg": release_badge,
    "scripts.svg": scripts_badge,
    "coverage.svg": coverage_badge,
}


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает факты и значок в каталог вывода."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="корень дерева, откуда читаются источники")
    parser.add_argument("--out-dir", required=True, help="куда положить производное")
    parser.add_argument("--sha", default="", help="голова, на которой собрано")
    parser.add_argument("--family", default="", help="сводка каталога export/where.json")
    parser.add_argument("--coverage", default="", help="отчёт счётчика покрытия, coverage.json")
    # Наше имя у площадки. Умолчание берётся у прогона, а не выдумывается:
    # выдуманное отличило бы нас от себя же и завысило отставание на все наши
    # ответы сразу.
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="наше имя у площадки — нужно, чтобы отличить свои ответы от чужих",
    )
    args = parser.parse_args(argv)

    try:
        facts = collect(
            Path(args.root),
            args.sha,
            Path(args.family) if args.family else None,
            Path(args.coverage) if args.coverage else None,
            args.repo,
        )
    except NotRun as exc:
        print(f"факты не собраны: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # ПУБЛИКОВАТЬ НОЛЬ НЕЛЬЗЯ, И ГРАНИЦА ПРОХОДИТ ЗДЕСЬ, А НЕ У СЧЁТЧИКА.
    # Счётчику ноль отдавать честно: его зовут и с синтетическим корнем, где
    # пусто законно (`tests/test_counting.py::test_a_missing_tree_is_not_a_zero`).
    # А вот ОПУБЛИКОВАННЫЙ ноль — уже утверждение о проекте: значок покажет
    # «тестов 0» так же уверенно, как показал бы 1743, и читатель не отличит
    # «посчитали» от «не нашли, где считать». Переименуй каталог набора — и
    # витрина соврёт, не покраснев нигде
    # ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md),
    # [005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
    #
    # СПИСОК СЧИТАННЫХ ЧИСЕЛ ЗАКРЫТЫЙ И НАЗВАН ЗДЕСЬ (068): это те, чей ноль
    # означает обрыв обхода, а не состояние проекта. `coverage` сюда не входит —
    # у него свой третий исход (`read: false`), и ноль там уже разведён с
    # незнанием.
    #
    # ЧИСЛА ПРАВИЛ ЗДЕСЬ НЕТ, И ЭТО НЕ ПРОПУСК. Пустой ответ каталогу отвергает
    # `rules_facts` ЗАРАНЬШЕ, своим отказом входа, — то есть до этой строки
    # `rules.total` нулём быть не может, и запись о нём была недостижима. Два
    # места, отвергающие одно, расходятся молча: починив одно, второе забывают
    # (022, 195). Сосед назван: проверку держит
    # `tests/test_facts.py::test_an_empty_answer_is_refused_before_the_count`.
    # МИНИМУМ КОНТРАКТА БЕЗ ИМЕНИ НЕ ПУБЛИКУЕТСЯ: файл «ни о ком» витрина не
    # прочтёт, а выглядит он как ответ (#759).
    if not facts["repo"]:
        print(
            "факты не опубликованы: не названо имя проекта (--repo) — это обязательный "
            "минимум контракта фактов семьи",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    counted = {
        "tests.functions": facts["tests"]["functions"],
        "tests.modules": facts["tests"]["modules"],
        "scripts.runnable": facts["scripts"]["runnable"],
    }
    empty = sorted(name for name, value in counted.items() if not value)
    if empty:
        print(
            f"факты не опубликованы: {', '.join(empty)} сосчитаны в ноль — это обрыв "
            f"обхода, а не состояние проекта (075). Корень: {args.root}",
            file=sys.stderr,
        )
        return EXIT_BROKEN

    clash = clashing_names()
    if clash:
        print(
            f"факты не опубликованы: имена вывода совпадают — {', '.join(clash)}", file=sys.stderr
        )
        return EXIT_BROKEN
    out = Path(args.out_dir) / PUBLISHED_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / FACTS).write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", "utf-8")
    for name, draw in BADGES.items():
        drawn = draw(facts)
        (out / name).write_text(svg(drawn) + "\n", encoding="utf-8")
        said = json.dumps(endpoint(drawn), ensure_ascii=False, indent=2) + "\n"
        (out / endpoint_name(name)).write_text(said, encoding="utf-8")

    rules = facts["rules"]
    print(
        f"собрано: контракт {facts['contract']}, "
        f"правил {rules['answered']} из {rules['total']}, "
        f"проверок на изменении {facts['checks_per_pr']['count']}"
    )
    kin = facts["family"]
    if kin.get("read"):
        print(
            f"общих механизмов семьи: {kin['shared']} из {kin['mechanisms']}, "
            f"они держат {kin['closed_by_shared']} правил из {kin['held_by_machine']} "
            f"({kin['share']:.0%} машинного соблюдения)"
        )
        # ВЫЧИСЛЕННОЕ И НЕСКАЗАННОЕ РАВНО НЕСЧИТАННОМУ. Расхождение формы
        # считалось здесь с 8 сентября, ложилось в факты ключом
        # `schema_agrees` — и не печаталось нигде: сводка ушла на 1.3, разрез
        # остался под 1.2, и девять дней об этом не знал никто. Число рядом с
        # числами, а не в файле, который никто не открывает (046).
        if not kin.get("schema_agrees"):
            print(
                f"форма сводки семьи разошлась: каталог отдаёт "
                f"{kin.get('schema_read') or '—'}, разрез написан под "
                f"{kin.get('schema_expected') or '—'} — перечитать разрез, "
                f"а не подвинуть число (157)",
                file=sys.stderr,
            )
    else:
        print(f"сводка семьи: {kin['why']}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
