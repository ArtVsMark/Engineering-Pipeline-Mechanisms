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
import json
import os
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, NamedTuple

import facts_common as common
import family
import family_uptake
import kinds
import paths
import pipeline_checks as policy
import report
import version as version

# ОБЩАЯ ЧАСТЬ ПОДНЯТА В `facts_common` (#1001, 090); имена остаются и здесь:
# их читают наши тесты и соседи, а смысл у них тот же — источник один.
from facts_common import SCHEMA as SCHEMA
from facts_common import SCHEMA_OF as SCHEMA_OF
from facts_common import STATUSES as STATUSES
from facts_common import NotRun as NotRun
from facts_common import contract_coverage as contract_coverage
from facts_common import coverage_facts as coverage_facts
from facts_common import release_series as release_series
from facts_common import rules_facts as rules_facts

VERSION_FILE: Final = paths.VERSION
BINDINGS: Final = paths.BINDINGS
FACTS: Final = "facts.json"
#: Коммит фактов — ПОЛНЫЙ хэш: так его пишет сборка (`git rev-parse HEAD`).
#: Строгое правило вместо перечня плохих форм (находка `0a6fab3`, правило 210):
#: `"HEAD"` или имя ветки проходили бы `git cat-file` и давали дерево головы.
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
#: Сколько кривых записей соседей сборка называет строками; остальное — числом.
WRONG_SHOWN: Final = 20
#: ГДЕ ЛЕЖАТ ФАКТЫ И ЗНАЧКИ — ПО КОНТРАКТУ СЕМЬИ, а не по своей раскладке:
#: ветка `badges`, путь `.github/badges/` — как у грейдера, каталога, токенов и
#: глоссария (договор фактов семьи — `SCHEMA_OF`, его держит каталог;
#: решение владельца 24.09.2026, #759). До этого файл лежал в корне ветки, и
#: витрина считала, что фактов у проекта нет. Адрес договора назван одним
#: именем, а не вторым (находка `bda792d`): прежде здесь стоял адрес витрины.
PUBLISHED_DIR: Final = paths.BADGES_DIR

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


#: Чем кончается чтение файла фактов, который не разобрать: нет файла, чужая
#: кодировка, не JSON, глубже предела разборщика. Один перечень на всех
#: читающих (`facts_file`) — прежде у трёх была узкая ловля без двух последних.
UNREADABLE: Final = (OSError, ValueError, RecursionError)


def facts_file(path: Path) -> Any:
    """Разобранный `facts.json`; любая поломка чтения — `NotRun` с причиной (#1478).

    `UnicodeDecodeError` — подкласс `ValueError`, `JSONDecodeError` — тоже:
    перечень `UNREADABLE` покрывает их, а `RecursionError` C-разборщика —
    отдельно. Без этого глубокий или чужой кодировки файл уходил трассой с
    кодом 1, а не причиной (039).
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UNREADABLE as exc:
        raise NotRun(f"{path} не прочитан — {exc!r}") from exc


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
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        # Глубже предела разборщика — тоже «не разобраны», а не трасса,
        # роняющая сборку фактов (тот же род, что у `family.load`).
        print(f"warning: числа обхода не разобраны: {exc!r}", file=sys.stderr)
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
    except (*UNREADABLE, KeyError, TypeError) as exc:
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


#: Формат манифеста семьи — контракт `family` каталога (v1.11.0, #1285).
FAMILY_SCHEMA: Final = "1.1"
#: Имя отдаваемого контракта шагов: номер — MAJOR.MINOR из `CONTRACT_VERSION`.
GIVES_STEPS: Final = "steps"


def manifest_facts(root: Path) -> dict[str, Any]:
    """Выпуск (тег и его коммит) и отдаваемые контракты — из дерева `root`.

    Выпуска нет — `release: null`, как велит форма манифеста, а не выдуманный
    тег. Номер контракта — MAJOR.MINOR: выпуск минора у издателя и есть смена
    того, что он отдаёт, а патч её не меняет.

    НОМЕР ЧИТАЕТСЯ НА ДЕРЕВЕ ТЕГА, А НЕ С ГОЛОВЫ — как у `release.contract_at`
    (#299): голова уходит вперёд, и номер с неё приписал бы выпуску чужой
    контракт (взгляд на #1294). Без выпуска приписывать некому — номер с головы.
    """
    tag = version.release_tag(root)
    sha = version.git("rev-list", "-n", "1", tag, root=root) if tag else None
    released = tag if tag and sha else None
    at_tag = f"{released}:{VERSION_FILE.as_posix()}"
    said = version.git("show", at_tag, root=root) if released else None
    if released and not said:
        raise NotRun(f"версия контракта на дереве {released} не прочитана")
    full = said.strip() if said else contract_version(root / VERSION_FILE)
    major_minor = ".".join(full.split(".")[:2])
    return {
        "release": {"tag": released, "sha": sha} if released else None,
        "gives": {GIVES_STEPS: major_minor},
    }


def family_manifest(facts: dict[str, Any]) -> str:
    """Манифест семьи по фактам: что отдаём, с какого выпуска; парных связей нет.

    Форма — контракт `family` каталога: `schema`, `project`, `release`,
    `gives`, `takes`. Семейные связи (действия каталога, схема ответа) сверка
    каталога находит в дереве сама, поэтому `takes` пуст (#1285).
    """
    said = facts["manifest"]
    doc = {
        "schema": FAMILY_SCHEMA,
        "project": facts["repo"],
        "release": said["release"],
        "gives": said["gives"],
        "takes": [],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def ours(
    root: Path, summary: Path | None = None, mine: str = "", uptake: Path | None = None
) -> dict[str, Any]:
    """Свои разделы проекта — то, что общий издатель не выводит: вход `extra-facts`.

    Ответ каталогу и проверки читаются первыми: их отказ — о входе самого
    проекта, и назвать его надо раньше чужой причины.

    СЧЁТ ОТВЕТА КАТАЛОГУ ДАЁТ ОБЩИЙ ИЗДАТЕЛЬ (#1282), и раздела `rules` здесь
    нет: свой ключ, совпавший с общим, `common.merge` отвергает. Но читается
    ответ здесь по-прежнему, и его отказ — по-прежнему отказ сборки: у
    потребителя ответа может не быть, а у нас его отсутствие — сломанный вход,
    и общий издатель с его серым «не прочитано» этого бы не сказал (045).
    """
    rules_facts(root / BINDINGS)
    checks = checks_facts(root / policy.DEFAULT_PATH)
    said = manifest_facts(root)
    seen = family_facts(summary, mine=mine, answers=root / BINDINGS, uptake=uptake)
    taken = seen["uptake"]
    # НА СВЕЖЕМ ЛИ СЕМЬЯ — вопрос издателя (#1344): пины взявших против
    # нашего выпуска и их диапазоны против отдаваемого `steps`. Выпуск и
    # номер — те же, что в манифесте, а не второе чтение тега (022). Без
    # обхода поле есть и говорит «неизвестно», а не пропадает (взгляд на #1355).
    taken["fresh"] = (
        family_uptake.freshness(taken.get("by") or [], said["release"], said["gives"][GIVES_STEPS])
        if taken.get("read")
        else {"read": False, "why": family_uptake.NO_FRESHNESS}
    )
    return {
        "contract": contract_version(root / VERSION_FILE),
        # Числа для вопросов СОПРОВОЖДАЮЩЕГО из .rules/showcase.json: значок им
        # не нужен и вреден, а живой адрес обязателен (049).
        "tests": test_counts(root),
        # Гейты проверяются ЗАПУСКОМ, и это отдельный предмет от покрытия строк.
        "scripts": script_runs(root),
        "checks_per_pr": checks,
        # Разрез семьи — раздел сверх договора, и причину он несёт своей формой
        # `{"read": false, "why": NO_FAMILY}` (взгляды на #1004 и #1014, 195).
        "family": seen,
        # Что проект отдаёт семье и с какого выпуска — вход манифеста семьи
        # (`contracts.json`, #1285): номера берутся здесь, у источников, а не
        # второй копией в сборщике манифеста (049).
        "manifest": said,
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
        # Поставщик — мы сами: та же величина, что общий шаг берёт из
        # `job.workflow_repository` нашего же вызова.
        supplier=mine,
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
    """Всё, что сборка кладёт в публикацию: факты, значки, страницы, файлы для машины."""
    return [FACTS, *BADGES, *PAGES, *MACHINE_READ]


#: Архив находок на той же ветке: пишет его `findings_archive.py` шагом `badges.yml`.
ARCHIVE: Final = "findings.json"


#: Файлы общего шага `step-facts.yml` на той же ветке — его имена, а не наши:
#: шаг кладёт то, что названо `publish_facts.PUBLISHES`, и потому перечень
#: пишется литералом, а не через `FACTS`. Через `FACTS` он переименовался бы
#: вместе с нашей константой и держал бы совпадение, а не файл шага (взгляд на
#: #1227). Что литерал равен `PUBLISHES`, сверяет тест.
SHARED_STEP: Final = ("facts.json", "project.svg", "family-check.json")


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
#: через `img.shields.io/endpoint`. Инвентарей два: этот и страницы `PAGES`.
#: Гейты витрины и публикации читают оба (взгляд на #1265). Своих картинок
#: сборка больше не рисует: значок проекта рисует `scripts/project_badge.py`
#: в общем шаге фактов (#1422, решение владельца 16.10.2026; к механизмам — #1563).
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
#: ФАЙЛЫ ДЛЯ МАШИНЫ, а не для посетителя: их читает чужая сборка, и витрина на
#: них не ведёт. Инвентарь четвёртый, чтобы гейт показа страниц не требовал
#: ссылки на то, что человек не читает; гейты публикации и уборки ветки
#: читают и его (#1285).
MACHINE_READ: Final[dict[str, Callable[[dict[str, Any]], str]]] = {
    "contracts.json": family_manifest,
}
#: Картинки и страницы, которые сборка кладёт ВПРОК, до показа на витрине
#: (196): ссылка на ненарисованное попала бы в main раньше файла. Второй шаг
#: ставит картинку и убирает имя отсюда; гейты `tests/test_facts.py` требуют
#: показа у всех прочих.
AHEAD: Final = frozenset[str]()

#: ЕДИНЫЙ ЗНАЧОК РИСУЕТ НЕ СБОРКА, А `scripts/project_badge.py`: в общем шаге
#: фактов (#1422, решение владельца 16.10.2026; прежде — `python-badge` шагом
#: `badges.yml`, #1019). С #1563 рисовальщик — механизмов, а не действие
#: каталога: код исполняется из той же выкачки, что и сборка (022). Имя
#: объявлено тут, рядом с инвентарём, потому что гейт витрины спрашивает «всё
#: ли нарисованное названо» у одного места, а не у двух.
UNIFIED: Final = "project.svg"
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


def draw_endpoints(facts: dict[str, Any], out: Path) -> None:
    """Значки-конечные точки `BADGES` по фактам — в каталог вывода.

    ПИСАТЕЛЬ ОДИН НА ОБА ПУТИ: конечные точки кладут и наша публикация
    (`draw_badges`), и общий шаг фактов — входами значка каталога
    (`endpoints_drawn`). Одинаковыми их держит то, что оба зовут эту функцию.
    """
    for name, draw in BADGES.items():
        said = json.dumps(endpoint(draw(facts)), ensure_ascii=False, indent=2) + "\n"
        (out / name).write_text(said, encoding="utf-8")


def draw_badges(facts: dict[str, Any], out: Path) -> None:
    """Значки-конечные точки, страницы и файлы для машины по фактам — в каталог вывода."""
    draw_endpoints(facts, out)
    for name, page in PAGES.items():
        (out / name).write_text(page(facts), encoding="utf-8")
    for name, build in MACHINE_READ.items():
        (out / name).write_text(build(facts), encoding="utf-8")


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


def rehydrated(facts: dict[str, Any], root: Path, supplier: str = "") -> dict[str, Any]:
    """Факты для рисования: темы `exchange` — в корень, неопубликованное — из дерева.

    ОПУБЛИКОВАННЫЕ ФАКТЫ — ФОРМА ДОГОВОРА ФАКТОВ 1.6 и 2.0 (#1337): `rules`, `manifest` и
    `contract` в них не лежат, у каждого канон в другом месте
    (`facts_common.NOT_PUBLISHED`, `SUPPLIER_NOT_PUBLISHED`). Рисующему они нужны, и берутся тем же
    кодом, что считал их до публикации, — из дерева, а не второй записью.
    """
    said = common.lifted(facts)
    if "rules" not in said:
        said["rules"] = common.rules_said(root, supplier)
    said.setdefault("manifest", manifest_facts(root))
    said.setdefault("contract", contract_version(root / VERSION_FILE))
    return said


def drawn_from(path: Path, out_dir: str, root: str = ".", supplier: str = "") -> int:
    """Режим `--from-facts`: значки по опубликованному общим шагом `facts.json`.

    Значки рисуются по ТОМУ файлу, который читает витрина, а не по второй
    сборке: число на значке и в фактах иначе разошлись бы на время между
    двумя сборками (022).
    """
    if not out_dir:
        print("значки не нарисованы: не назван --out-dir", file=sys.stderr)
        return EXIT_BROKEN
    try:
        facts = facts_file(path)
    except NotRun as exc:
        print(f"значки не нарисованы: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if clashed():
        return EXIT_BROKEN
    try:
        facts = rehydrated(facts, Path(root), supplier)
    except NotRun as exc:
        print(f"значки не нарисованы: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    out = Path(out_dir) / PUBLISHED_DIR
    out.mkdir(parents=True, exist_ok=True)
    try:
        draw_badges(facts, out)
    except (KeyError, TypeError) as exc:
        print(f"значки не нарисованы: в {path} нет раздела {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print(
        f"значки нарисованы по {path}: {', '.join(sorted(BADGES))}; "
        f"страницы: {', '.join(sorted(PAGES))}; машинные: {', '.join(sorted(MACHINE_READ))}"
    )
    return EXIT_OK


def facts_text(facts: dict[str, Any]) -> str:
    """Текст публикуемых фактов: одна запись на сборку и на её проверку в наборе.

    Тест «всем путём» звал свой `json.dumps` рядом с этим (находка `dea89bd`):
    смени сборка вызов записи — тест остался бы зелёным.
    """
    return json.dumps(common.published(facts, supplier=True), ensure_ascii=False, indent=2) + "\n"


def commit_of(path: Path) -> int:
    """Режим `--commit-of`: напечатать коммит, на котором собраны готовые факты.

    Прогон значков берёт по нему дерево для неопубликованных разделов
    (`rehydrated`): факты на ветке могут отставать от головы прогона, и дерево
    головы дало бы значку числа другого коммита (взгляд на #1345). Поля нет или
    оно пусто — отказ, а не пустая строка: пустая ушла бы в git как «голова».

    ПРИЧИНА У КАЖДОЙ ФОРМЫ СВОЯ (взгляды на #1364 и #1382): факты не объект,
    поля нет, поле не строка, поле пустое — разные поломки, и общая фраза
    «нет поля» назвала бы `"commit": 123` отсутствием поля. Годное — только
    ПОЛНЫЙ хэш (`COMMIT_RE`): строка-не-хэш прошла бы `git cat-file` как
    `HEAD` или имя ветки (находка `0a6fab3`). Отсюда и пометка прогона значков:
    печатаемое здесь — только шестнадцатеричные знаки, перевода строки в нём
    не бывает (находка `4a88697`).
    """
    try:
        facts = facts_file(path)
    except NotRun as exc:
        print(f"коммит фактов не взят: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not isinstance(facts, dict):
        why = f"факты не объект, а {type(facts).__name__}"
    elif "commit" not in facts:
        why = "нет поля commit"
    elif not isinstance(facts["commit"], str):
        why = f"поле commit не строка, а {type(facts['commit']).__name__}"
    elif not facts["commit"].strip():
        why = "поле commit пустое"
    elif not COMMIT_RE.fullmatch(facts["commit"]):
        why = f"поле commit не полный хэш коммита: «{report.cut(facts['commit'])}»"
    else:
        print(facts["commit"])
        return EXIT_OK
    print(f"коммит фактов не прочитан: в {path} {why}", file=sys.stderr)
    return EXIT_BROKEN


def endpoints_drawn(path: Path, out_dir: str) -> int:
    """Режим `--endpoints-out`: только конечные точки `BADGES` по готовым фактам — плоско.

    ДЛЯ ОБЩЕГО ШАГА ФАКТОВ (#1422, решение владельца 16.10.2026). Значок
    проекта рисует `scripts/project_badge.py --parts`, а покрытие и версию он
    берёт файлами shields-endpoint — их шаг собирает здесь, по тем же фактам,
    что уйдут на ветку, а не меряет второй раз (214). У потребителя наших
    разделов в фактах нет, и их не надо: оба значка читают общие показатели,
    а непрочитанное называют «не прочитано», а не падают.
    """
    try:
        facts = facts_file(path)
    except NotRun as exc:
        print(f"конечные точки не собраны: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not isinstance(facts, dict):
        print(f"конечные точки не собраны: {path} — факты не объект", file=sys.stderr)
        return EXIT_BROKEN
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        draw_endpoints(common.lifted(facts), out)
    # Число не числом — «факты не той формы», исход 2, а не трейсбек с кодом 1.
    except (TypeError, ValueError) as exc:
        print(f"конечные точки не собраны: {path} не той формы — {exc!r}", file=sys.stderr)
        return EXIT_BROKEN
    print(f"конечные точки собраны по {path}: {', '.join(sorted(BADGES))}")
    return EXIT_OK


def plain(value: object) -> str:
    """Чужая строка для лога: пробелы и переводы строк свёрнуты, длина ограничена."""
    return report.cut(" ".join(str(value).split()))


def say_family(kin: dict[str, Any]) -> None:
    """Печатает разрез семьи рядом с числами сборки: что посчитано — сказано (046)."""
    if kin.get("read"):
        adopted = kin["adopted"]
        print(
            f"правил семьи на гейте нашего происхождения: {adopted['ours']} "
            f"из {adopted['of']} машинных"
        )
        taken = kin["origins"]
        print(
            f"механизмов нашего происхождения у семьи: пар «проект × механизм» "
            f"{taken['pairs']} (взяты {taken['taken']}, переделаны {taken['adapted']}, "
            f"не объявлено {taken['undeclared']}), проектов {taken['projects']['took']} "
            f"из {taken['projects']['of']}"
        )
        # Заметки соседей — рядом с числами, а не только в файле (взгляд на
        # #1340): ноль различается на «раздела нет» и «не той формы».
        said = kin.get("notes") or {}
        print(
            f"заметок и замеров соседей по правилам: {said.get('count', 0)} "
            f"(раздел прочитан у {said.get('read', 0)}, нет у {said.get('unread', 0)}, "
            f"не той формы у {said.get('wrong_shape', 0)}; "
            f"записей не той формы {said.get('wrong_entries', 0)})"
        )
        # Кривая запись НАЗЫВАЕТСЯ, а не только считается (взгляд на #1352):
        # причина — здесь, рядом с числом, а не лишь в файле фактов (046).
        # Строки соседа — в одну строку и с пределом: перевод строки в его
        # ключе дал бы в логе строку, которую площадка читает командой `::…`
        # (взгляд на #1358).
        # И ЧИСЛОМ СТРОК (взгляд на #1358): сосед с тысячей кривых записей дал
        # бы тысячу строк лога. Показано первые, остальное — числом; полный
        # список лежит в фактах (`wrong_entries_by`).
        wrong = said.get("wrong_entries_by") or []
        for one in wrong[:WRONG_SHOWN]:
            repo, rule, why = (plain(one.get(key)) for key in ("repo", "rule", "why"))
            print(f"  - {repo} · правило {rule}: {why}")
        if len(wrong) > WRONG_SHOWN:
            print(
                f"  … и ещё {len(wrong) - WRONG_SHOWN} — полный список в фактах, wrong_entries_by"
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
        "--endpoints-out",
        default="",
        help="с --from-facts: только конечные точки BADGES, плоско в этот каталог (общий шаг)",
    )
    parser.add_argument(
        "--commit-of", default="", help="напечатать коммит, на котором собран готовый facts.json"
    )
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
    parser.add_argument(
        "--supplier",
        default="",
        help="поставщик кода конвейера: владелец/репо — для «свои/взяты» при рисовании",
    )
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

    if args.commit_of:
        return commit_of(Path(args.commit_of))
    if args.branch_files:
        print("\n".join(branch_files()))
        return EXIT_OK
    if args.prune:
        for name in prune(Path(args.prune)):
            print(f"снято с ветки: {name} — сборка его больше не издаёт")
        return EXIT_OK
    if args.endpoints_out and not args.from_facts:
        # Пара флагов, а не один (`303d8f0`): конечные точки собираются ПО
        # ГОТОВЫМ фактам, и без них заход ушёл бы молча в полную сборку.
        print("--endpoints-out работает только вместе с --from-facts", file=sys.stderr)
        return EXIT_BROKEN
    if args.from_facts and args.endpoints_out:
        return endpoints_drawn(Path(args.from_facts), args.endpoints_out)
    if args.from_facts:
        return drawn_from(Path(args.from_facts), args.out_dir, args.root, args.supplier)
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
    (out / FACTS).write_text(facts_text(facts), "utf-8")
    draw_badges(facts, out)

    rules = facts["rules"]
    print(
        f"собрано: контракт {facts['contract']}, "
        f"правил {rules['answered']} из {rules['total']}, "
        f"проверок на изменении {facts['checks_per_pr']['count']}"
    )
    say_family(facts["family"])
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
