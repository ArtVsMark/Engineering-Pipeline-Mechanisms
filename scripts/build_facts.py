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

import argparse
import ast
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any, Final, NamedTuple

import facts_common as common
import family
import kinds
import paths
import pipeline_checks as policy
import version as version

# ОБЩАЯ ЧАСТЬ ПОДНЯТА В `facts_common` (#1001, 090); имена остаются и здесь:
# их читают наши тесты и соседи, а смысл у них тот же — источник один.
from facts_common import SCHEMA as SCHEMA
from facts_common import SCHEMA_OF as SCHEMA_OF
from facts_common import NotRun as NotRun
from facts_common import contract_coverage as contract_coverage
from facts_common import coverage_facts as coverage_facts
from facts_common import release_series as release_series

VERSION_FILE: Final = paths.VERSION
BINDINGS: Final = paths.BINDINGS
FACTS: Final = "facts.json"
#: ГДЕ ЛЕЖАТ ФАКТЫ И ЗНАЧКИ — ПО КОНТРАКТУ СЕМЬИ, а не по своей раскладке:
#: ветка `badges`, путь `.github/badges/` — как у грейдера, каталога, токенов и
#: глоссария (контракт фактов витрины, `ArtVsMark/ArtVsMark` ·
#: `.rules/facts-contract.md`; решение владельца 24.09.2026, #759). До этого
#: файл лежал в корне ветки, и витрина считала, что фактов у проекта нет.
PUBLISHED_DIR: Final = paths.BADGES_DIR
#: Список разрешённого (068): статус, которого здесь нет, — это дефект ответа,
#: а не новая тонкость, о которой механизм обязан догадаться.
STATUSES: Final = ("active", "rejected", "not-applicable", "unreviewed")

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


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


#: Причина у непрочитанной сводки семьи — одна для любого отказа: файла нет,
#: не скачался, не разобрался. Подробность отказа уходит в поток диагностики,
#: а не к читателю витрины (взгляд на #1014, 195).
NO_FAMILY: Final = "сводка семьи не прочитана — числа неизвестны, а не нулевые"
#: Обход клонов не дал чисел — «взяли вызовом» неизвестно, а не ноль (045).
NO_UPTAKE: Final = "обход клонов семьи не прочитан — кто взял наши шаги, неизвестно, а не «никто»"


def uptake_facts(path: Path | None) -> dict[str, Any]:
    """«Взяли вызовом» — числа обхода клонов `family_uptake.py --out` (#1199).

    Обход идёт отдельным шагом прогона: клоны — сеть, а сборка фактов читает
    только файлы. Файла нет или он не той формы — число неизвестно и названо.
    """
    if path is None or not path.is_file():
        return {"read": False, "why": NO_UPTAKE}
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
        projects, steps = said["projects"], said["steps"]
        int(projects["took"]), int(projects["of"]), int(steps["taken"]), int(steps["of"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"warning: числа обхода не разобраны: {exc}", file=sys.stderr)
        return {"read": False, "why": NO_UPTAKE}
    return {"read": True, **said}


def family_facts(
    path: Path | None,
    *,
    mine: str = "",
    answers: Path | None = None,
    uptake: Path | None = None,
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
    taken = uptake_facts(uptake)
    if path is None or not path.is_file():
        return {"read": False, "why": NO_FAMILY, "uptake": taken}
    try:
        # Разбор ОДИН: `family.load` читал файл дважды за вызов — для разреза и
        # для отставания, — и второе чтение могло прийти уже другим (022).
        # Нашёл внешний взгляд на #240.
        summary_read = family.load(path)
        picture = family.picture(summary_read, mine=mine)
    except family.NotRun as exc:
        # Причина — для читателя витрины, как у `none.python`: путь раннера и
        # `repr` ошибки разбора уходят в поток диагностики (взгляд на #1014).
        print(f"warning: {exc}", file=sys.stderr)
        return {"read": False, "why": NO_FAMILY, "uptake": taken}
    picture["uptake"] = taken
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


#: Прогон CI, чей статус витрина спрашивает у площадки по имени файла: свой
#: красный файл фактов честно сказать не может (договор фактов с 1.2, #1001).
CI_FLOW: Final = paths.WORKFLOWS / "ci.yml"
#: Причина в `none.python` — для читателя витрины, а не трасса: формулировка —
#: у общего издателя, здесь только имя нашего прогона в ней.
NO_PYTHON: Final = common.UNREAD_MATRIX.format(CI_FLOW.name)
#: Джобы матрицы версий: поддерживаемые и пробные. Версии берутся из самой
#: матрицы, а не пишутся второй раз (005).
SUPPORTED_JOB: Final = "test-matrix"
EXPERIMENTAL_JOB: Final = "test-next"


def python_facts(path: Path = CI_FLOW) -> dict[str, list[str]]:
    """Наши версии Python: `test-matrix` в `ci.yml` и пробные `test-next` рядом (#1018).

    Читает общий издатель (`facts_common.python_facts`): матрица у нас та же,
    что он назовёт потребителю, и второго чтения нет (022).
    """
    return common.python_facts(
        path, SUPPORTED_JOB, path.with_name(paths.PYTHON_NEXT.name), EXPERIMENTAL_JOB
    )


#: Наши матрицы в форме входа общего шага: `<файл прогона>:<джоб>`.
OUR_MATRIX: Final = f"{CI_FLOW.name}:{SUPPORTED_JOB}"
OUR_NEXT: Final = f"{paths.PYTHON_NEXT.name}:{EXPERIMENTAL_JOB}"


def ci_facts(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Разделы `ci` и `python` договора у нас — общим издателем, с нашими матрицами."""
    return common.ci_facts(root, CI_FLOW.name, OUR_MATRIX, OUR_NEXT)


def ours(
    root: Path, summary: Path | None = None, mine: str = "", uptake: Path | None = None
) -> dict[str, Any]:
    """Свои разделы проекта — то, что общий издатель не выводит: вход `extra-facts`.

    Ответ каталогу и проверки читаются первыми: их отказ — о входе самого
    проекта, и назвать его надо раньше чужой причины.
    """
    rules = rules_facts(root / BINDINGS)
    checks = checks_facts(root / policy.DEFAULT_PATH)
    return {
        "contract": contract_version(root / VERSION_FILE),
        # Числа для вопросов СОПРОВОЖДАЮЩЕГО из .rules/showcase.json: значок им
        # не нужен и вреден, а живой адрес обязателен (049).
        "tests": test_counts(root),
        # Гейты проверяются ЗАПУСКОМ, и это отдельный предмет от покрытия строк.
        "scripts": script_runs(root),
        "rules": rules,
        "checks_per_pr": checks,
        # Разрез семьи — раздел сверх договора, и причину он несёт своей формой
        # `{"read": false, "why": NO_FAMILY}` (взгляды на #1004 и #1014, 195).
        "family": family_facts(summary, mine=mine, answers=root / BINDINGS, uptake=uptake),
    }


def collect(
    root: Path,
    sha: str,
    summary: Path | None = None,
    coverage: Path | None = None,
    mine: str = "",
    uptake: Path | None = None,
) -> dict[str, Any]:
    """Собирает все факты о проекте: общие — общим издателем, свои — `ours`.

    `mine` — наше каноничное имя у площадки. Оно нужно ровно одному числу:
    отставанию от семьи, где своё надо отличить от чужого. Пусто — число не
    считается и говорит об этом, а не выходит нулём (045).

    СБОРКА ТА ЖЕ, ЧТО У ОБЩЕГО ШАГА (#1001): общая часть и слияние — его,
    поэтому наш файл и файл потребителя расходиться не могут (022).
    """
    mine_part = ours(root, summary, mine, uptake)
    shared = common.common(
        root,
        sha=sha,
        repo=mine,
        ci_workflow=CI_FLOW.name,
        python_matrix=OUR_MATRIX,
        python_next=OUR_NEXT,
        coverage=coverage,
    )
    return common.merge(shared, mine_part)


class Badge(NamedTuple):
    """Значок как данные: подпись, значение и цвет — то, что публикует shields-endpoint."""

    label: str
    message: str
    color: str


def badge(label: str, value: str, color: str) -> Badge:
    """Значок из своих чисел; как его показать, решает вывод, а не рисовалка."""
    return Badge(label, value, color)


#: Форма значка, которую читает shields.io по адресу `endpoint?url=…`.
ENDPOINT_SCHEMA: Final = 1


def endpoint(drawn: Badge) -> dict[str, Any]:
    """Значок формой shields-endpoint: так значки показывает вся семья (#998).

    ЧУЖАЯ СЛУЖБА — ЦЕНА, И ОНА ПРИНЯТА (владелец, 01.10.2026). Прежде значки
    рисовались своими SVG ради независимости от чужой службы; владелец снял их:
    один источник числа, а не два. Отказ здесь не молчит: не ответившая служба
    показывает подпись картинки или «inaccessible», а не правдоподобное число.
    Числа по-прежнему наши: служба лишь рисует то, что лежит в этом файле.
    """
    return {
        "schemaVersion": ENDPOINT_SCHEMA,
        "label": drawn.label,
        "message": drawn.message,
        "color": drawn.color.lstrip("#"),
    }


def published_names() -> list[str]:
    """Всё, что сборка кладёт в каталог публикации: факты, значки, картинки и страницы."""
    return [FACTS, *BADGES, *PICTURES, *PAGES]


#: Архив находок на той же ветке: пишет его `findings_archive.py` шагом `badges.yml`.
ARCHIVE: Final = "findings.json"


#: Файлы общего шага `step-facts.yml` на той же ветке — его имена, а не наши:
#: шаг кладёт то, что названо `publish_facts.PUBLISHES`, и потому перечень
#: пишется литералом, а не через `FACTS`. Через `FACTS` он переименовался бы
#: вместе с нашей константой и держал бы совпадение, а не файл шага (взгляд на
#: #1227). Что литерал равен `PUBLISHES`, сверяет тест.
SHARED_STEP: Final = ("facts.json",)


def branch_files() -> list[str]:
    """Всё, что ветка `badges` вправе держать: изданное сборкой, общий шаг, значок и архив.

    СНЯТОЕ С ВЕТКИ УХОДИТ ВМЕСТЕ С ИНВЕНТАРЁМ (взгляд на #1198). Публикация
    копирует поверх и прежде ничего не удаляла: снятый значок оставался на
    ветке с последним числом навсегда, и по адресу его нельзя было отличить
    от живого. Перечень выводится из инвентаря, а не из списка снятых по
    имени: значок, убранный из `BADGES`, уходит с ветки следующим заходом.
    """
    return sorted({*published_names(), *SHARED_STEP, UNIFIED, ARCHIVE})


def prune(directory: Path) -> list[str]:
    """Убирает из каталога публикации всё, чего нет в :func:`branch_files`; отдаёт снятое.

    УДАЛЕНИЕ — ЗДЕСЬ, А НЕ ЦИКЛОМ ОБОЛОЧКИ (взгляд на #1202). Цикл звал
    `git rm` без `-r`: подкаталог или неотслеживаемый файл в каталоге
    публикации ронял под `set -e` всю публикацию — не уезжали ни значки, ни
    архив. Здесь снимается файл или каталог целиком, а запись удаления
    делает `git add -A` прогона. И поведение проверяется прогоном, а не
    подстрокой в тексте прогона.
    """
    keep = set(branch_files())
    gone: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.name in keep:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        gone.append(path.name)
    return gone


def clashing_names() -> list[str]:
    """Имена вывода, которые встречаются дважды (взгляд на #1002).

    Каталог публикации общий с фактами: значок под именем `facts.json` молча
    затёр бы контракт фактов семьи. Столкновение — отказ сборки, а не
    перезапись.
    """
    names = published_names()
    return sorted({name for name in names if names.count(name) > 1})


#: Роды ответа, означающие «держит машина». Тот же состав, что у разреза семьи
#: и у дрейфа: три понимания одного слова разошлись бы молча (090).
#: Виды механизма — из общего места (`scripts/kinds.py`), а не своей копией.
MACHINE: Final = kinds.MACHINE


#: Что значок проекта говорит на месте числа, которого нет: незнание — не ноль (045).
UNREAD_PART: Final = "не прочитано"

#: ЗНАЧОК ПРОЕКТА РИСУЕТСЯ ТЕМ ЖЕ ВИДОМ, ЧТО ЕДИНЫЙ ЗНАЧОК КАТАЛОГА (решение
#: владельца 09.10.2026): зоны со своей подписью, просвет между зонами,
#: палитра GitHub. Рисовалка — копия `scripts/python_badge.py::рисунок`
#: каталога: действия «нарисовать произвольные зоны» у каталога нет, а строка
#: shields с тремя числами через точку читалась плохо. Копия названа здесь,
#: чтобы её было видно. Палитра — значения каталога на 09.10.2026
#: (`СОСТОЯНИЯ`, `ПОДПИСЬ`, `ЦВЕТ_ПОКРЫТИЯ`); сверки с каталогом нет — его кода
#: в нашем дереве нет, и расхождение вида видно глазом рядом с `python.svg`.
#: Часть значка: надпись, цвет, слово для подсказки.
Part = tuple[str, str, str]
#: Цвета частей — палитра каталога (GitHub), а не shields.
LABEL_COLOR: Final = "#444d56"
GREEN: Final = "#2da44e"
YELLOW: Final = "#bf8700"
RED: Final = "#cf222e"
GREY: Final = "#8c959f"
#: Просвет между зонами, как у каталога.
ZONE_GAP: Final = 4


def part_width(text: str) -> int:
    """Ширина надписи шрифтом 11px Verdana — приближение, как у shields и каталога."""
    return round(len(text) * 7.2) + 14


def drawing(zones: list[list[Part]]) -> str:
    """SVG из зон: каждая зона — скруглённая полоса своих частей (вид каталога)."""
    hint = "; ".join(f"{text}: {word}" for zone in zones for text, _, word in zone if word)
    mark = hashlib.sha1(repr(zones).encode("utf-8")).hexdigest()[:8]
    x = 0
    clips: list[str] = []
    rects: list[str] = []
    seams: list[str] = []
    texts: list[str] = []
    for number, zone in enumerate(zones):
        start = x
        for index, (text, color, _) in enumerate(zone):
            width = part_width(text)
            rects.append(
                f'<rect x="{x}" width="{width}" height="20" fill="{color}" '
                f'clip-path="url(#z{mark}{number})"/>'
            )
            if index:
                seams.append(
                    f'<rect x="{x - 1}" width="1" height="20" fill="#fff" fill-opacity=".7"/>'
                )
            middle = x + width / 2
            texts.append(
                f'<text x="{middle}" y="15" fill="#010101" fill-opacity=".3">{escape(text)}</text>'
                f'<text x="{middle}" y="14">{escape(text)}</text>'
            )
            x += width
        clips.append(
            f'<clipPath id="z{mark}{number}"><rect width="{x - start}" height="20" '
            f'rx="3" x="{start}"/></clipPath>'
        )
        x += ZONE_GAP
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{x - ZONE_GAP}" height="20" '
        f'role="img" aria-label="{escape(hint)}">'
        f"<title>{escape(hint)}</title>{''.join(clips)}"
        f"<g>{''.join(rects)}{''.join(seams)}</g>"
        '<g fill="#fff" text-anchor="middle" '
        'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f"{''.join(texts)}</g></svg>\n"
    )


def counted(numerator: int, denominator: int, *, known: bool = True) -> str:
    """Число с числителем и знаменателем и справа процент: «66/195 · 34%» (владелец, 09.10.2026).

    Доли нет — «—»: пустой знаменатель или часть знаменателя не прочитана
    (``known=False``) — процент утверждал бы о неизвестном (045).
    """
    share = f"{round(100 * numerator / denominator)}%" if denominator and known else "—"
    return f"{numerator}/{denominator} · {share}"


def share_color(numerator: int, denominator: int, *, known: bool = True) -> str:
    """Цвет доли: красный ниже трети, жёлтый ниже двух третей, иначе зелёный.

    Доли нет — серый, как незнание, а не красный, как плохой исход (045, взгляд
    на #1259): пустой знаменатель или непрочитанная часть его.
    """
    if not denominator or not known:
        return GREY
    share = numerator / denominator
    return RED if share < 0.34 else YELLOW if share < 0.67 else GREEN


def project_zones(facts: dict[str, Any]) -> list[list[Part]]:
    """Значок проекта зонами: правила машиной и семья — проекты и гейты в ходу.

    РЕШЕНИЕ ВЛАДЕЛЬЦА 08.10.2026 (#1212, #1213). Один значок заменяет два —
    «держится машиной» (`rules.json`) и «общие механизмы» (`family.json`), — и
    несёт только числа, каждое с числителем и знаменателем. «Кем» — поимённо
    в фактах (`family.uptake.by`), а не в значке. Вид — как у единого значка
    каталога, справа от каждого числа — его процент (решения владельца
    09.10.2026). Витрина перешла на него вторым изменением, после первого
    прогона публикации (196).

    «ГЕЙТ В ХОДУ» — ПО ВЫЗОВУ НАШЕГО ШАГА ПО ТЕГУ (#1199): отдаваемый шаг,
    который зовёт хотя бы один проект семьи. Объявленное потребителем
    происхождение гейта (каталог, ArtVsMark/Engineering-Incidents-Playbook#701)
    в счёт не входит, пока его нет; разрез `family.adopted` остаётся в фактах.

    Непрочитанный обход клонов — серое «не прочитано» на месте чисел семьи, а
    не ноль; непрочитанные клоны названы числом рядом (045). Цвет числа — по
    его доле.

    ПОЧЕМУ НЕ «ОТВЕЧЕНО». Прежняя редакция показывала `answered/total` и
    подписывала это «правил держится». Число было `195/195` и не могло стать
    другим: проект отвечает по каждому правилу каталога по построению (129).
    Значок, который не движется, — украшение: он не говорит, где проект стоит, и
    не может сказать, что тот сдвинулся.

    ЗНАМЕНАТЕЛЬ — ДЕЙСТВУЮЩИЕ, А НЕ ВСЕ. Неприменимое правило машиной не
    держится и держаться не должно; считать его в знаменателе значило бы
    занижать долю за то, у чего нет предмета (154).
    """
    kinds = facts["rules"]["by_mechanism"]
    machine = sum(int(count) for name, count in kinds.items() if name in MACHINE)
    active = sum(int(count) for count in kinds.values())
    rules = [
        ("правила", LABEL_COLOR, ""),
        (
            f"машиной {counted(machine, active)}",
            share_color(machine, active),
            "правил каталога держится машиной",
        ),
    ]
    taken = (facts.get("family") or {}).get("uptake") or {}
    if not taken.get("read"):
        family_zone = [
            ("семья", LABEL_COLOR, ""),
            (f"проектов {UNREAD_PART}", GREY, "обход клонов семьи не прочитан"),
            (f"шагов {UNREAD_PART}", GREY, "обход клонов семьи не прочитан"),
        ]
        return [rules, family_zone]
    projects, steps = taken["projects"], taken["steps"]
    took, of = int(projects["took"]), int(projects["of"])
    unread = f" ({projects['unread']} {UNREAD_PART})" if projects.get("unread") else ""
    # ШАГОВ, А НЕ ГЕЙТОВ (взгляд на #1265): счёт идёт по всем отдаваемым шагам
    # (`onboard.steps`), среди которых `agent-pr`, `automerge`, `review` — не
    # гейты. Подпись называет то, что посчитано.
    used, offered = int(steps["taken"]), int(steps["of"])
    family_zone = [
        ("семья", LABEL_COLOR, ""),
        (
            f"проектов {counted(took, of, known=not unread)}{unread}",
            share_color(took, of, known=not unread),
            "проектов семьи зовут наш шаг по тегу",
        ),
        (
            f"шагов {counted(used, offered)}",
            share_color(used, offered),
            "наших отдаваемых шагов в ходу у семьи",
        ),
    ]
    return [rules, family_zone]


def coverage_badge(facts: dict[str, Any]) -> Badge:
    """Доля покрытых строк — или прямое «не прочитано»."""
    if "coverage_percent" not in facts:
        return badge("покрытие", "не прочитано", "#9f9f9f")
    percent = float(facts["coverage_percent"])
    color = "#4c1" if percent >= 85 else "#dfb317" if percent >= 70 else "#e05d44"
    return badge("покрытие", f"{percent:g}%", color)


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
#: Здесь — значки формой shields-endpoint (#998), которые витрина показала бы
#: через `img.shields.io/endpoint`. Инвентарей три: этот, картинки `PICTURES`
#: (свой SVG видом единого значка каталога — значок проекта, #1213) и страницы
#: `PAGES`. Гейты витрины и публикации читают все три (взгляд на #1265).
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
    "version.json": version_badge,
    "coverage.json": coverage_badge,
}


#: КАРТИНКИ, которые сборка рисует сама — SVG зонами, видом единого значка
#: каталога, а не shields-endpoint: имя файла → чем собираются его зоны.
#: Инвентарь второй, а не общий с `BADGES`: форма вывода другая, но гейты
#: витрины, публикации и «число только из фактов» читают оба (#1213).
#: Значок проекта сменил «держится машиной» и «общие механизмы» вторым шагом
#: после того, как прогон публикации его нарисовал (196, #1259).
def who_zones(facts: dict[str, Any]) -> list[list[Part]]:
    """Таблица «кем» КАРТИНКОЙ: по зоне на проект, зовущий наш шаг по тегу.

    Картинкой, а не ссылкой на страницу: витрина ведёт в ветку `badges` только
    изображением (089) — ссылка уводила бы читателя в производное. Числа здесь
    те же, что у значка проекта, и берутся только из фактов (122). Обход не
    прочитан — так и сказано серым, а не «никто» (045).
    """
    taken = (facts.get("family") or {}).get("uptake") or {}
    if not taken.get("read"):
        return [[("кем", LABEL_COLOR, ""), (UNREAD_PART, GREY, "обход клонов семьи не прочитан")]]
    zones = [
        [
            ("кем", LABEL_COLOR, ""),
            (str(one.get("repo")), GREEN, "зовёт наш шаг по тегу"),
            (
                f"шагов {sum(1 for _ in one.get('steps') or [])}"
                + (f" · {(one.get('refs') or [''])[0]}" if one.get("refs") else ""),
                GREEN,
                "сколько наших шагов зовёт и по какому тегу",
            ),
        ]
        for one in taken.get("by") or []
    ]
    zones += [
        [("не прочитан", LABEL_COLOR, ""), (str(repo), GREY, "клон не прочитан")]
        for repo in (taken.get("projects") or {}).get("unread_repos") or []
    ]
    return zones or [
        [("кем", LABEL_COLOR, ""), ("никто", GREY, "наши шаги по тегу не зовёт никто")]
    ]


PICTURES: Final[dict[str, Callable[[dict[str, Any]], list[list[Part]]]]] = {
    "project.svg": project_zones,
    "who.svg": who_zones,
}


def who_page(facts: dict[str, Any]) -> str:
    """Таблица «кем» — кто из семьи зовёт наши шаги по тегу, из `family.uptake.by`.

    Решение по #1213 (вариант 1): таблица живёт файлом на ветке `badges`, куда
    прогон уже пишет, а не блоком README — в `main` прогон не пишет. Чисел
    здесь нет: их несёт значок проекта, страница называет только имена (122).
    Обход не прочитан — так и сказано, а не «никто» (045).
    """
    lines = [
        "# Кто взял наши механизмы",
        "",
        "> **Читатель:** посетитель витрины — кто из семьи зовёт наши шаги по тегу.",
        "",
        "Собрано сборкой фактов из `facts.json` (`family.uptake.by`); руками не правится.",
        "",
    ]
    taken = (facts.get("family") or {}).get("uptake") or {}
    if not taken.get("read"):
        return "\n".join([*lines, f"**Не прочитано:** {taken.get('why') or NO_UPTAKE}.", ""])
    by = taken.get("by") or []
    if by:
        lines += ["| проект | шаги | теги |", "|---|---|---|"]
        for one in sorted(by, key=lambda item: str(item.get("repo"))):
            steps = ", ".join(f"`{step}`" for step in one.get("steps") or []) or "—"
            refs = ", ".join(f"`{ref}`" for ref in one.get("refs") or []) or "—"
            lines.append(f"| {one.get('repo')} | {steps} | {refs} |")
    else:
        lines.append("Пока никто из прочитанных проектов семьи наши шаги по тегу не зовёт.")
    unread = (taken.get("projects") or {}).get("unread_repos") or []
    if unread:
        said = ", ".join(sorted(unread))
        lines += ["", f"**Не прочитаны клоны:** {said} — незнание, а не «не взял» (045)."]
    return "\n".join([*lines, ""])


#: СТРАНИЦЫ, которые сборка кладёт рядом со значками: имя файла → сборщик
#: текста. Инвентарь третий: не значок и не картинка, но изданное для чужого
#: прочтения — гейты публикации и уборки ветки читают и его (#1213).
PAGES: Final[dict[str, Callable[[dict[str, Any]], str]]] = {
    "who.md": who_page,
}
#: Картинки и страницы, которые сборка кладёт ВПРОК, до показа на витрине
#: (196): ссылка на ненарисованное попала бы в main раньше файла. Второй шаг
#: ставит картинку и убирает имя отсюда; гейты `tests/test_facts.py` требуют
#: показа у всех прочих. `who.md` не будет показан никогда — витрина ведёт в
#: ветку `badges` только картинкой (089), — и уйдёт вместе с `who.svg` на витрине.
AHEAD: Final = frozenset({"who.md", "who.svg"})

#: ЕДИНЫЙ ЗНАЧОК РИСУЕТ НЕ СБОРКА, А ДЕЙСТВИЕ КАТАЛОГА (#1019): «Python │ ОС │
#: coverage │ release / PyPI │ version» собирает `python-badge` шагом
#: `badges.yml`, а код его исполняется с тега каталога, а не копией здесь (022).
#: Имя объявлено тут, рядом с инвентарём, потому что гейт витрины спрашивает
#: «всё ли нарисованное названо» у одного места, а не у двух.
UNIFIED: Final = "python.svg"
#: Файлы инвентаря, из которых единый значок берёт свои зоны: покрытие и версию
#: он не меряет второй раз (214). Отдельно в витрине они больше не показываются —
#: стали бы дублями зон. Выпуск зона «release / PyPI» спрашивает у площадки
#: сама, поэтому `release.json` снят: его не показывал и не читал бы никто.
#: Что эти имена совпадают со входами шага, держит `tests/test_showcase.py`.
ZONE_INPUTS: Final = ("coverage.json", "version.json")


def zeroed(facts: dict[str, Any], root: str) -> bool:
    """Сосчитанное в ноль названо и остановлено: это обрыв обхода, а не состояние (075)."""
    counted = {
        "tests.functions": facts["tests"]["functions"],
        "tests.modules": facts["tests"]["modules"],
        "scripts.runnable": facts["scripts"]["runnable"],
    }
    empty = sorted(name for name, value in counted.items() if not value)
    if empty:
        print(
            f"факты не опубликованы: {', '.join(empty)} сосчитаны в ноль — это обрыв "
            f"обхода, а не состояние проекта (075). Корень: {root}",
            file=sys.stderr,
        )
    return bool(empty)


def clashed() -> bool:
    """Имена вывода совпадают — один файл затёр бы другой молча."""
    clash = clashing_names()
    if clash:
        print(
            f"факты не опубликованы: имена вывода совпадают — {', '.join(clash)}", file=sys.stderr
        )
    return bool(clash)


def draw_badges(facts: dict[str, Any], out: Path) -> None:
    """Значки-конечные точки по фактам — в каталог вывода."""
    for name, draw in BADGES.items():
        said = json.dumps(endpoint(draw(facts)), ensure_ascii=False, indent=2) + "\n"
        (out / name).write_text(said, encoding="utf-8")
    for name, zones in PICTURES.items():
        (out / name).write_text(drawing(zones(facts)), encoding="utf-8")
    for name, page in PAGES.items():
        (out / name).write_text(page(facts), encoding="utf-8")


def extra_written(args: argparse.Namespace) -> int:
    """Режим `--extra-out`: свои разделы проекта файлом — вход общего шага (#1001)."""
    try:
        said = ours(
            Path(args.root),
            Path(args.family) if args.family else None,
            args.repo,
            Path(args.uptake) if args.uptake else None,
        )
    except NotRun as exc:
        print(f"свои разделы не собраны: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if zeroed(said, args.root):
        return EXIT_BROKEN
    out = Path(args.extra_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(said, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"свои разделы: {out} — {', '.join(sorted(said))}")
    return EXIT_OK


def drawn_from(path: Path, out_dir: str) -> int:
    """Режим `--from-facts`: значки по опубликованному общим шагом `facts.json`.

    Значки рисуются по ТОМУ файлу, который читает витрина, а не по второй
    сборке: число на значке и в фактах иначе разошлись бы на время между
    двумя сборками (022).
    """
    if not out_dir:
        print("значки не нарисованы: не назван --out-dir", file=sys.stderr)
        return EXIT_BROKEN
    try:
        facts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"значки не нарисованы: {path} не прочитан — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if clashed():
        return EXIT_BROKEN
    out = Path(out_dir) / PUBLISHED_DIR
    out.mkdir(parents=True, exist_ok=True)
    try:
        draw_badges(facts, out)
    except (KeyError, TypeError) as exc:
        print(f"значки не нарисованы: в {path} нет раздела {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print(
        f"значки нарисованы по {path}: {', '.join(sorted([*BADGES, *PICTURES]))}; "
        f"страницы: {', '.join(sorted(PAGES))}"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает факты и значок в каталог вывода."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="корень дерева, откуда читаются источники")
    parser.add_argument("--out-dir", default="", help="куда положить производное")
    # ДВА РЕЖИМА ДЛЯ ОБЩЕГО ИЗДАТЕЛЯ (#1001, шаг 2). Наш прогон значков —
    # первый потребитель шага `step-facts.yml`: отдаёт ему свои разделы файлом
    # и рисует значки по тому `facts.json`, который шаг опубликовал, а не по
    # второй сборке тех же чисел (155, 022).
    parser.add_argument(
        "--extra-out", default="", help="записать только свои разделы — вход extra-facts шага"
    )
    parser.add_argument("--from-facts", default="", help="нарисовать значки по готовому facts.json")
    parser.add_argument(
        "--branch-files",
        action="store_true",
        help="напечатать всё, что ветка badges вправе держать, — по строке на имя",
    )
    parser.add_argument(
        "--prune",
        default="",
        help="убрать из каталога публикации всё, чего ветка badges держать не вправе",
    )
    parser.add_argument("--sha", default="", help="голова, на которой собрано")
    parser.add_argument("--family", default="", help="сводка каталога export/where.json")
    parser.add_argument("--uptake", default="", help="числа обхода клонов: family_uptake.py --out")
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

    if args.branch_files:
        print("\n".join(branch_files()))
        return EXIT_OK
    if args.prune:
        for name in prune(Path(args.prune)):
            print(f"снято с ветки: {name} — сборка его больше не издаёт")
        return EXIT_OK
    if args.from_facts:
        return drawn_from(Path(args.from_facts), args.out_dir)
    if args.extra_out:
        return extra_written(args)
    if not args.out_dir:
        print("факты не собраны: не назван --out-dir", file=sys.stderr)
        return EXIT_BROKEN
    try:
        facts = collect(
            Path(args.root),
            args.sha,
            Path(args.family) if args.family else None,
            Path(args.coverage) if args.coverage else None,
            args.repo,
            Path(args.uptake) if args.uptake else None,
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
    if zeroed(facts, args.root) or clashed():
        return EXIT_BROKEN
    out = Path(args.out_dir) / PUBLISHED_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / FACTS).write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", "utf-8")
    draw_badges(facts, out)

    rules = facts["rules"]
    print(
        f"собрано: контракт {facts['contract']}, "
        f"правил {rules['answered']} из {rules['total']}, "
        f"проверок на изменении {facts['checks_per_pr']['count']}"
    )
    kin = facts["family"]
    if kin.get("read"):
        adopted = kin["adopted"]
        print(
            f"правил семьи на гейте нашего происхождения: {adopted['ours']} "
            f"из {adopted['of']} машинных"
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
