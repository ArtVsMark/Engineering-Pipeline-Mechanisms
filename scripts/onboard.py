#!/usr/bin/env python3
"""Команда подключения: собирает потребителю заготовку вызова, а не инструкцию.

ОТДАЁТСЯ НАРУЖУ: этим заходом проект подключают к себе.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ АБЗАЦ В README. Порядок подключения, живущий прозой,
исполняется по-разному каждым, кто его прочёл: один забудет объявить класс
проверки, другой напишет имя записи голым, третий прибьётся к подвижной метке
вместо версии. Ровно так и разошлись конвейеры семьи — замер копий в договоре,
`docs/use/pipeline.md`
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

СОСТАВ ВЫВОДИТСЯ ИЗ ДЕРЕВА, А НЕ ПЕРЕЧИСЛЯЕТСЯ ЗДЕСЬ. Шаги берутся те, что
помечены маркером «отдаётся наружу» (`scripts/check_shipped.py`), прибивка —
тег ВЫПУСКА из истории (`pin_of` ниже говорит, почему не `CONTRACT_VERSION`).
Второй список тех же имён отстал бы на первом же вынесенном
шаге, и отстал бы молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

ШАГ КОНВЕЙЕРА И УПРАВЛЯЮЩИЙ МЕХАНИЗМ ПОДКЛЮЧАЮТСЯ ПО-РАЗНОМУ, И РАЗНИЦА
ВЫВОДИТСЯ ИЗ ДЕРЕВА (#993). Шаг конвейера зовёт `ci.yml` — его заготовка
джоб в своём `ci.yml`. Управляющий механизм (план работ и соседи) зовёт свой
прогон со своими событиями и правами: джобом в `ci.yml` он шёл бы на каждом
изменении и без права записи в задачу. Поэтому шаг, у которого в нашем
дереве есть СВОЙ вызывающий прогон, печатается этим прогоном целиком, с
адресом по тегу вместо внутреннего пути (`own_callers`). Второго списка
таких шагов нет: вызывающий и есть ответ.

ИМЯ ЗАПИСИ ПРОВЕРКИ СОСТАВНОЕ, И ЗАГОТОВКА НАЗЫВАЕТ ЕГО ПРАВИЛЬНО. Площадка
зовёт запись вызванного джоба `<имя вызывающего> / <имя вызванного>` — замер
прогоном на живой площадке. Потребитель, написавший в своём ответе голое имя,
получил бы сводный гейт, ждущий записи, которой никто не выдаст
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЗАГОТОВКА НЕ РЕШАЕТ ЗА ПОТРЕБИТЕЛЯ, КАКОЙ КЛАСС У ПРОВЕРКИ. Класс — свойство
потребителя, а не механизма: объём документа обязателен там, где документ
выпускается наружу, и совещателен там, где он внутренний
(174).
Поэтому все шаги выходят с классом «в очереди разбора» — объявленным
состоянием, а не молчанием, — и потребитель отвечает по каждому сам.

ЗАГОТОВКА НЕ ПЕЧАТАЕТСЯ, ПОКА ПРИБИВКА ЕЁ НЕ НЕСЁТ. Вызов по адресу с
версией работает ровно тогда, когда названный тег этот файл содержит, и это
НЕ следует из того, что файл лежит у нас: работа слита, выпуск не нарезан —
самый обычный день. Замер 20.09.2026: помечено наружу одиннадцать файлов, в
выпуске `v1.1.0` их ноль, то есть заготовка была нерабочей целиком, и узнал
бы об этом потребитель на СВОЁМ красном
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Третий исход называет предмет: нарезать выпуск
([158](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/158-the-third-outcome-names-its-subject.md)).

ЧЕГО ЗАХОД НЕ ДЕЛАЕТ: не правит чужое дерево и не трогает защиту ветки.
По умолчанию он печатает, а потребитель кладёт. С ключом `--write` (решение
владельца 04.10.2026 по #992, вариант 3) он кладёт заготовку сам — но только
в свободные пути: файл, который уже есть, называется, и не пишется ни один.
Иначе «подключено» и «подправлено на ходу» стали бы неотличимы. Сводный гейт
`ci-complete.yml` кладётся тонким прогоном: его джоб `ci-complete` зовёт
составное действие `.github/actions/ci-complete` адресом с прибивкой (#1385),
и имя в защите ветки остаётся `ci-complete`.

СВОД ОКНА КЛАДЁТСЯ ЗАГОТОВКОЙ, И ЗАНЯТЫЙ СВОД ЗАКЛАДКУ НЕ ДЕРЖИТ (#995,
пункт 1). Окно потребителя работает с конвейером по своду, и общая часть
приходит из `kit/` — сверенной с нашим сводом (`tests/test_rulebook_kit.py`),
с заглушками наполнения. Но свод у живого проекта почти всегда уже есть: он —
наполнение владельца, а не файл заготовки. Поэтому занятый `AGENTS.md` или
`CLAUDE.md` не пишется и называется, а прочая заготовка кладётся: правило «ни
одного файла при занятом» держит половину ВЫЗОВА, а свод вызовом не является.

ДАННЫЕ ВЗГЛЯДА И `dependabot.yml` КЛАДУТСЯ ЗАГОТОВКАМИ (#1386, решение
владельца 17.10.2026). Карта взгляда читает из дерева потребителя таблицу ролей,
процедуру, профили и таблицу областей; без них взгляд идёт без ролей. Скелеты
лежат в `kit/data/` и ложатся обеими дверями, `--write` и `--update`, только в
свободные пути: занятый путь — своё проекта, отказа он не даёт. Ответ каталогу
`.rules/bindings.json` заготовкой не кладётся — его форму ведёт каталог, — и
заход называет, что без него карта не собирается.

Исходы (правило 039): ``0`` заготовка собрана · ``2`` не отработал ·
``3`` отдавать нечего: ни один шаг не помечен · ``4`` прибивка не несёт
помеченного: выпуск отстал от дерева · ``5`` с ``--write``: путь заготовки в
дереве потребителя уже занят · ``6`` общая ветка потребителя не ``main`` ·
``7`` с ``--update``: наш файл правлен по существу, не записано ничего.

СВОЙ ПУТЬ НАЗЫВАЕТСЯ КЛЮЧОМ, А НЕ УБИРАЕТСЯ РУКАМИ (#1503, решение владельца
18.10.2026). У живого проекта часть путей заготовки уже занята своим файлом с
другим предметом — свой выпуск пакета, свои значки. `--write --keep ПУТЬ`
этот путь не пишет и не считает занятым. Путь прогона механизма проект
заменяет своим, и проверки этого прогона ложатся в ответ классом `off` с
причиной: молча проверка не пропадает. Оставлен и сам ответ — строки `off`
печатаются в выводе захода, вписать их в свой `.pipeline.yml`. Прочие пути —
`ci.yml`, сводный гейт, ответ, свод — проект сводит со своим, их проверки не
трогаются. Путь, которого заготовка не кладёт, — отказ: опечатка в ключе иначе
прошла бы молча (045).

ОБНОВЛЕНИЕ — ВТОРАЯ ДВЕРЬ, `--update` (#1386). Наш файл сверяется с заготовкой
СВОЕГО тега по существу вызова, а не по тексту; совпал — переписывается новой
заготовкой, разошёлся — отказ на всё обновление с разницей для поставщика.
Подробно — у функции `update`.
"""

import argparse
import ast
import contextlib
import difflib
import hashlib
import io
import itertools
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import check_env
import check_rulebook_fresh
import check_shipped
import check_workflow_forms
import findings
import gitcall
import main_guard
import paths
import pipeline_checks as policy
import publish_facts
import review_map
import version
import yaml

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_NOTHING: Final = 3
#: Прибивка есть, а помеченного в ней нет. Отдельный исход, а не «нечего
#: отдавать»: предмет тот же, причина и выход РАЗНЫЕ (039, 104).
EXIT_UNREACHABLE: Final = 4
#: Заход с `--write` нашёл файл, который положил бы: чужое не перезаписывается,
#: а называется (#992). Выход — свой: убрать файл или сверить его руками.
EXIT_OCCUPIED: Final = 5
#: Общая ветка потребителя — не `paths.TRUNK`. Механизмы её имя не угадывают:
#: база гейтов, предмет дрейфа и цель выпуска оказались бы чужими (#1220).
EXIT_FOREIGN_TRUNK: Final = 6
#: С `--update`: наш файл у потребителя правлен по существу. Обновление не
#: пишет ни одного файла — половина обновления хуже никакого (#1386).
EXIT_HAND_EDITED: Final = 7

#: Приставка вынесенного шага. Помеченным бывает и не шаг — пакет, действие, —
#: а заготовку вызова собирают только из прогонов, которые ЗОВУТ.
STEP_PREFIX: Final = "step-"
#: Что читается ответом «выпусков ещё не было». Пустота тут законна и обязана
#: быть названа, а не выдана за версию (154).
NO_RELEASE: Final = "выпусков ещё не было"
#: Внутренний путь, которым наш прогон зовёт наш же шаг. В заготовке он
#: заменяется адресом с тегом: потребитель ходит внешним путём.
LOCAL_CALL: Final = "./.github/workflows/"
#: Прогон, джобами которого подключаются шаги конвейера.
PIPELINE_FLOW: Final = "ci.yml"
#: Шаги ОБ ИЗМЕНЕНИИ: на толчке в общую ветку изменения нет, и вызов идёт с
#: `ON_CHANGE_ONLY`. Одна таблица на заготовку и наш `ci.yml` — сверяет тест
#: (#1663, 214): прежде условие стояло у нас руками, а заготовка звала шаги и
#: на толчке, и у потребителя краснела общая ветка.
ABOUT_A_CHANGE: Final = frozenset(
    {"attribution", "contract", "journal", "pr-meta", "rulebook-fresh", "window-lifetime"}
)
#: Условие вызова шага об изменении — дословно как в нашем `ci.yml`.
ON_CHANGE_ONLY: Final = "github.event_name != 'push'"
#: Сводный гейт: заготовка его не кладёт, а называет — он пока копируется.
SUMMARY_FLOW: Final = "ci-complete.yml"
#: Значок проекта на ветке `badges` потребителя: его кладёт общий шаг фактов
#: (#1282, изменение #1327). Путь — тот, что шаг публикует
#: (`publish_facts.PUBLISHES`); совпадение сверяет тест, а не память.
BADGE: Final = paths.BADGES_DIR / "project.svg"
#: Условие, при котором строка значка не работает, — печатается рядом с ней.
PRIVATE_NOTE: Final = (
    "в закрытом репозитории ссылка на raw.githubusercontent.com без токена не отдаётся — "
    "значок в README там не покажется"
)
#: Имя репозитория, пока его не знает заход: печать без `--write` идёт без дерева.
REPO_PLACEHOLDER: Final = "<владелец>/<репо>"


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не пустая заготовка."""


def steps(root: Path) -> list[str]:
    """Имена вынесенных шагов — из пометок дерева, а не списком.

    Имя шага — это имя его файла без приставки и расширения, и оно же имя
    джоба внутри: составное имя записи собирается из них двоих.
    """
    found = [
        Path(said).stem[len(STEP_PREFIX) :]
        for said in check_shipped.shipped_here(root)
        if Path(said).name.startswith(STEP_PREFIX) and Path(said).suffix in {".yml", ".yaml"}
    ]
    return sorted(found)


#: Шаги, которые выпуск отдаёт, а заготовка `ci.yml` НЕ кладёт: они нужны
#: проекту, который сам отдаёт общие шаги, а прочим отвечают «поверхность
#: пуста». Такой проект зовёт шаг одной строкой сам; `--update` поднимает его
#: тег и советует снять вызов тому, кто своих общих шагов не отдаёт (решение
#: владельца 25.10.2026, #1652).
OPT_IN: Final = {
    "contract": "поверхность контракта общих шагов — договор поставщика с семьёй; "
    "у проекта без своих общих шагов она пуста",
}
#: Как общий шаг зовёт наш скрипт: из выкачки механизмов, а не из дерева потребителя.
CALLED_SCRIPT: Final = re.compile(r"(?:\$MECHANISMS|\$\{\{ env\.MECHANISMS \}\})/scripts/(\w+)\.py")


def step_texts(flow: Path) -> list[str]:
    """Значения шагов прогона — `run:` и входы `with:`, без комментариев файла.

    СТРОГОЕ ПРАВИЛО, А НЕ ФОРМА (третий заход по месту — взгляды на #1196 и
    #1201; 210). Вызов нашего скрипта — любое значение шага: `run:` зовёт
    сам шаг, а вход действия зовёт агент взгляда по своим разрешениям
    (`check_version.py`, `check_pipeline.py` в дереве потребителя). Не вызов —
    только комментарий файла: его разбор YAML и не отдаёт.
    """
    try:
        document = policy.run_of(flow)
    except policy.BadPolicy as exc:
        raise NotRun(f"{flow.name} не прочитан: {exc}") from exc
    found: list[str] = []
    for job in (document.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if not isinstance(step, dict):
                continue
            if step.get("run"):
                found.append(str(step["run"]))
            found += [str(value) for value in (step.get("with") or {}).values()]
    return found


def called_scripts(root: Path, names: list[str]) -> set[str]:
    """Имена наших скриптов, которые зовут вынесенные шаги, — вместе с их импортами.

    Импорт обходится транзитивно и только по нашему `scripts/`: `agent_pr`
    сам меток не читает, их читает импортированный `labels`, и без обхода
    данные соседа выпали бы из перечня молча (045).
    """
    queue = sorted(
        {
            match.group(1)
            for name in names
            for line in step_texts(root / paths.WORKFLOWS / f"{STEP_PREFIX}{name}.yml")
            for match in CALLED_SCRIPT.finditer(line)
        }
    )
    seen: set[str] = set()
    while queue:
        one = queue.pop()
        source = root / paths.SCRIPTS / f"{one}.py"
        if one in seen or not source.is_file():
            continue
        seen.add(one)
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                queue += [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                queue.append(node.module.split(".")[0])
    return seen


def consumer_data(root: Path, names: list[str], laid: set[Path]) -> list[str] | None:
    """Данные, которые вынесенные шаги читают из дерева потребителя, а заготовка не кладёт.

    ПЕРЕЧЕНЬ ВЫВОДИТСЯ, А НЕ ПИШЕТСЯ (решение владельца 07.10.2026 по #996).
    Источник один — ответ `configured` инвентаря переноса у самого шага и у
    скриптов, которые он зовёт: там названо, где потребитель его
    настраивает. Шаг читает данные и мимо скриптов — входом действия
    (`authors:` у атрибуции, взгляд на #1196); такой вход обязан стоять в
    ответе шага, и это держит `tests/test_portable.py`. Свои пути скрипта и
    прогоны в перечень не идут — первые едут выкачкой, вторые кладёт
    заготовка. Инвентаря нет — `None`: перечень не выведен, и это говорится,
    а не подменяется пустым (045). Ответ не той формы — отказ, а не перечень
    по буквам.
    """
    inventory = root / paths.PORTABLE
    if not inventory.is_file():
        return None
    try:
        answers = json.loads(inventory.read_text(encoding="utf-8"))["answers"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise NotRun(f"`{paths.PORTABLE}` не разобран: {exc!r}") from exc
    if not isinstance(answers, dict):
        raise NotRun(f"`{paths.PORTABLE}`: поле answers — не словарь")
    skip = {str(path) for path in laid}
    ours = (f"{paths.SCRIPTS.as_posix()}/", f"{paths.WORKFLOWS}/")
    keys = [f"{paths.WORKFLOWS}/{STEP_PREFIX}{name}.yml" for name in names] + [
        f"{paths.SCRIPTS.as_posix()}/{one}.py" for one in called_scripts(root, names)
    ]
    found: set[str] = set()
    for key in keys:
        said = answers.get(key, {})
        if not isinstance(said, dict):
            raise NotRun(f"`{paths.PORTABLE}`: ответ «{key}» — не словарь")
        if said.get("answer") != "configured":
            continue
        where = said.get("where")
        if not isinstance(where, list) or not all(isinstance(one, str) for one in where):
            raise NotRun(f"`{paths.PORTABLE}`: у «{key}» where — не список путей")
        found |= {one for one in where if not one.startswith(ours) and one not in skip}
    return sorted(found)


def step_called(said: str) -> str:
    """Имя шага, который зовёт этот `uses:` из нашего дерева; пусто — не наш шаг.

    Форм ДВЕ: внутренний путь `./.github/workflows/step-<имя>.yml` и адрес с
    общей веткой (`pipeline_checks.ADDRESSED_CALL`): так свой вызов взгляда
    прибит к общей ветке, чтобы карта не исполняла код головы (#993).
    """
    if said.startswith(f"{LOCAL_CALL}{STEP_PREFIX}"):
        where = said[len(LOCAL_CALL) :]
    elif found := policy.ADDRESSED_CALL.match(said):
        where = Path(found["path"]).name
    else:
        return ""
    if not where.startswith(STEP_PREFIX) or Path(where).suffix != ".yml":
        return ""
    return Path(where).stem[len(STEP_PREFIX) :]


def own_callers(root: Path, names: list[str]) -> dict[str, Path]:
    """Шаги со СВОИМ вызывающим прогоном в нашем дереве: имя шага → файл прогона.

    Вызывающий ищется по вызову шага (`step_called`: внутренний путь или адрес
    с общей веткой) у прогонов дерева, кроме самих шагов. Нечитаемый прогон — третий исход, а
    не «вызывающего нет»: молча он перевёл бы управляющий механизм в джоб
    `ci.yml` (045).

    ЗОВЁТ `ci.yml` — ЗНАЧИТ ШАГ КОНВЕЙЕРА, кто бы ещё его ни звал (взгляд на
    #1050). Иначе любой соседний прогон, позвавший шаг локально, молча вывел бы
    его из джобов `ci.yml` в заготовке и из пробы передачи. Управляющий механизм
    — шаг, которого `ci.yml` не зовёт, а зовёт ровно один свой прогон. Два своих
    прогона у одного шага — неоднозначность, и это отказ, а не выбор первого.

    ПРОГОН ЧИТАЕТСЯ ПОД ОБОИМИ РАСШИРЕНИЯМИ, как его читает площадка (находка
    `e8e7fb3`, правило 195). Двойник признан у всех дверей захода (`standing`),
    а здесь прогон искался только как `*.yml`, и `ci.yaml` не был бы `ci.yml`:
    свой прогон под `.yaml` выпал бы из поиска вызывающего молча.
    """
    wanted = set(names)
    callers: dict[str, list[Path]] = {}
    entries = (root / paths.WORKFLOWS).glob("*")
    for flow in sorted(one for one in entries if one.suffix in YAML_TWINS):
        if flow.name.startswith(STEP_PREFIX):
            continue
        try:
            said = policy.run_of(flow)
        except policy.BadPolicy as exc:
            raise NotRun(f"{flow.name} не прочитан: {exc}") from exc
        for job in (said.get("jobs") or {}).values():
            name = step_called(str((job or {}).get("uses") or ""))
            if name in wanted and flow not in callers.setdefault(name, []):
                callers[name].append(flow)
    found: dict[str, Path] = {}
    for name, flows in callers.items():
        if any(flow.with_suffix(".yml").name == PIPELINE_FLOW for flow in flows):
            continue
        if len(flows) > 1:
            raise NotRun(
                f"шаг {STEP_PREFIX}{name} зовут несколько своих прогонов "
                f"({', '.join(flow.name for flow in flows)}) — какой из них заготовка, неизвестно"
            )
        found[name] = flows[0]
    return found


def own_kit(flow: Path, name: str, repo: str, pin: str) -> str:
    """Свой прогон управляющего механизма — с адресом по тегу вместо внутреннего пути.

    ПОДМЕНА СВЕРЯЕТСЯ С РАЗБОРОМ (взгляд на #1050). Вызывающего находит разбор
    YAML, а переписывается текст; вызов, записанный иной формой (`uses:
    "./…"`, два пробела), разбор признал бы, а подмена пропустила бы — и
    внутренний путь молча ушёл бы в заготовку. Поэтому число подмен обязано
    равняться числу вызовов по разбору; не равно — отказ с названной формой.
    """
    outer = f"uses: {repo}/.github/workflows/{STEP_PREFIX}{name}.yml@{pin}"
    try:
        document = policy.run_of(flow)
    except policy.BadPolicy as exc:
        raise NotRun(f"{flow.name} не прочитан: {exc}") from exc
    every = document.get("jobs") or {}
    jobs = every.values()
    if any(step_called(str((job or {}).get("uses") or "")) != name for job in jobs):
        return calling_part(flow.name, document, name, outer)
    said = [
        str((job or {}).get("uses") or "")
        for job in jobs
        if step_called(str((job or {}).get("uses") or "")) == name
    ]
    text = flow.read_text(encoding="utf-8")
    inner = sorted({f"uses: {one}" for one in said})
    if sum(text.count(one) for one in inner) != len(said):
        raise NotRun(
            f"{flow.name}: вызов {STEP_PREFIX}{name} записан не формой «uses: <адрес>» — "
            "заготовка не перепишет его на адрес по тегу, а наш адрес потребителю не годится"
        )
    for one in inner:
        text = text.replace(one, outer)
    return text


def calling_part(source: str, document: dict[Any, Any], name: str, outer: str) -> str:
    """Заготовка из вызывающего, у которого есть СВОИ джобы: только джобы, зовущие шаг.

    Свои джобы вызывающего — наполнение поставщика: у нас `badges.yml` перед
    общим шагом фактов собирает свои разделы нашими скриптами, и в заготовке
    потребителя они вели бы в пустоту (#1001). Поэтому едут события, права,
    очередь и джобы вызова — с адресом по тегу и без `needs` на снятые джобы;
    входы вызова остаются как есть: это данные, и правит их потребитель.

    СНЯТЫЙ `needs` НЕ УНОСИТ С СОБОЙ ТО, ЧТО НА НЁМ ДЕРЖАЛОСЬ (взгляд на #1183).
    Условие снятого джоба переходит на джоб вызова (`inherited_guard`): у нас
    фильтр будящих событий стоит на `inputs`, и без него `facts` с правом
    записи шёл бы на любое завершение `ci`. Вход, называющий артефакт снятого
    джоба (`artifacts_of`), в заготовку не едет: у потребителя его некому
    выгрузить, и шаг предупреждал бы на каждом заходе.

    СТРОГОЕ ПРАВИЛО, А НЕ ПЕРЕЧЕНЬ (четвёртый заход по месту — взгляды на
    #1189 и #1195; 210). У вызова снимаются ровно те `needs`, что ведут на
    снятые джобы; `needs` на другой джоб вызова остаётся, иначе два вызова
    потеряли бы порядок; через снятого посредника `needs` тоже ведёт на вызов
    (`kept_needs`). Отказ с причиной, а не склейка, в двух случаях:
    выражение площадки (`if` целиком, остальное — внутри `${{ }}`) ссылается
    на снятый джоб — в заготовке оно вело бы в пустоту; или `needs` снят, а
    в своём либо перенесённом условии стоит статусная функция — она судила
    бы исход другого множества джобов. Условие снятого переносится без
    обёртки `${{ }}`: обёрнутая склейка — непустая строка, а строка истинна.
    Вход с именем артефакта или со ссылкой на снятый джоб не едет и назван в
    шапке заготовки.
    """
    jobs = document.get("jobs") or {}
    calls = [
        key for key, job in jobs.items() if step_called(str((job or {}).get("uses") or "")) == name
    ]
    gone = {str(key) for key in jobs} - {str(key) for key in calls}
    lost = artifacts_of(jobs, gone)
    kept: dict[str, Any] = {}
    dropped: list[str] = []
    for key in calls:
        job = jobs[key] or {}
        body = {one: value for one, value in job.items() if one != "needs"}
        stays = kept_needs(jobs, key, gone)
        if stays:
            body = {"needs": stays[0] if len(stays) == 1 else stays, **body}
        body["uses"] = outer.removeprefix("uses: ")
        guard = inherited_guard(jobs, key, gone)
        if guard:
            body["if"] = guard
        said_with: dict[str, Any] = {}
        for one, value in (body.get("with") or {}).items():
            if value in lost or any(leans_on(one, gone) for one in expressions(value)):
                dropped.append(f"{key}.{one}")
            else:
                said_with[one] = value
        if said_with:
            body["with"] = said_with
        else:
            body.pop("with", None)
        dangling = [
            one
            for one, value in body.items()
            if any(
                leans_on(said, gone)
                for said in ([bare_condition(str(value))] if one == "if" else expressions(value))
            )
        ]
        if dangling:
            raise NotRun(
                f"у вызова `{key}` {', '.join(sorted(dangling))} ссылается на снятый джоб "
                f"({', '.join(sorted(gone))}) — в заготовке это вело бы в пустоту, "
                "перенесите руками"
            )
        kept[str(key)] = body
    said: dict[str, Any] = {"name": document.get("name") or Path(source).stem}
    said["on"] = policy.events_raw(document)
    for one in ("permissions", "concurrency"):
        if one in document:
            said[one] = document[one]
    said["jobs"] = kept
    head = (
        f"# Заготовка собрана `scripts/onboard.py` поставщика из его `{source}`:\n"
        "# только джобы вызова общего шага. Свои джобы поставщика не едут —\n"
        "# входы вызова (`with:`) — данные, правьте их под свой проект.\n"
    )
    if dropped:
        head += (
            "# Не едут входы, которые называют снятое (артефакт или выход\n"
            f"# снятого джоба): {', '.join(dropped)}.\n"
        )
    return head + str(yaml.safe_dump(said, allow_unicode=True, sort_keys=False))


def kept_needs(jobs: dict[Any, Any], key: Any, gone: set[str]) -> list[str]:
    """Джобы заготовки, на которых вызов стоит — прямо или через снятых посредников.

    ПОРЯДОК ЧЕРЕЗ СНЯТОГО НЕ ТЕРЯЕТСЯ (взгляд на #1195). Вызов, стоящий на
    снятом джобе, который сам стоит на другом вызове, после снятия обязан
    стоять на том вызове: иначе два вызова теряют порядок молча.
    """
    found: list[str] = []
    queue = needed_by(jobs, key)
    seen: set[str] = set()
    while queue:
        one = queue.pop(0)
        if one in seen:
            continue
        seen.add(one)
        if one in gone:
            queue += needed_by(jobs, one)
        elif one not in found:
            found.append(one)
    return found


def needed_by(jobs: dict[Any, Any], key: Any) -> list[str]:
    """Имена джобов, от которых зависит `key` (`needs` строкой или списком)."""
    said = (jobs.get(key) or {}).get("needs") or []
    return [str(one) for one in ([said] if isinstance(said, str) else said)]


#: Ссылка выражения площадки на выходы и исходы соседних джобов.
NEEDS_REF: Final = re.compile(r"\bneeds\.")
#: Статусные функции: они судят исход `needs`, и при снятом `needs` меняют смысл.
STATUS_CALL: Final = re.compile(r"\b(?:always|cancelled|success|failure)\s*\(")


def bare_condition(text: str) -> str:
    """Условие без обёртки `${{ }}`: в склейке обёртка дала бы строку, а строка истинна."""
    said = text.strip()
    if said.startswith("${{") and said.endswith("}}"):
        return said[3:-2].strip()
    return said


#: Выражение площадки внутри строки: вне `${{ }}` слово `needs.` — литерал.
EXPRESSION: Final = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)


def expressions(value: Any) -> list[str]:
    """Все выражения `${{ }}` в значении — в строках, списках и словарях на любой глубине."""
    if isinstance(value, dict):
        return [one for inner in value.values() for one in expressions(inner)]
    if isinstance(value, list):
        return [one for inner in value for one in expressions(inner)]
    return [match.group(1) for match in EXPRESSION.finditer(str(value))]


def leans_on(text: str, gone: set[str]) -> bool:
    """Ссылается ли выражение на выход или исход одного из снятых джобов."""
    return any(re.search(rf"\bneeds\.{re.escape(one)}\b", text) for one in gone)


def inherited_guard(jobs: dict[Any, Any], key: Any, gone: set[str]) -> str:
    """Условие джоба вызова вместе с условиями снятых джобов, на которых он стоял.

    Обход транзитивный: снятый джоб может сам стоять на снятом, и его условие
    держало вызов так же. Порядок — от ближнего к дальнему, без повторов.
    Чего честно не перенести — отказ с причиной (`NotRun`), а не склейка:
    условие снятого со ссылкой на `needs.` в новом месте ведёт в пустоту, а
    статусная функция своего условия при снятом `needs` судила бы другое.
    """
    found: list[str] = []
    own = (jobs.get(key) or {}).get("if")
    if own:
        found.append(bare_condition(str(own)))
    queue = [one for one in needed_by(jobs, key) if one in gone]
    cut = bool(queue)
    seen: set[str] = set()
    while queue:
        one = queue.pop(0)
        if one in seen:
            continue
        seen.add(one)
        raw = (jobs.get(one) or {}).get("if")
        condition = bare_condition(str(raw)) if raw else ""
        if condition and NEEDS_REF.search(condition):
            raise NotRun(
                f"условие снятого джоба `{one}` ссылается на `needs.`: «{condition}» — "
                f"на вызове `{key}` оно вело бы в пустоту, перенесите его руками"
            )
        if condition and condition not in found:
            found.append(condition)
        queue += [more for more in needed_by(jobs, one) if more in gone]
    status = [one for one in found if STATUS_CALL.search(one)]
    if cut and status:
        raise NotRun(
            f"у вызова `{key}` условие со статусной функцией: «{status[0]}» — без `needs` "
            "она судит другое, и склейка изменила бы смысл, разберите руками"
        )
    if len(found) < 2:
        return found[0] if found else ""
    return " && ".join(f"({one})" for one in found)


def artifacts_of(jobs: dict[Any, Any], gone: set[str]) -> set[str]:
    """Имена артефактов, которые выгружают снятые джобы (`actions/upload-artifact`)."""
    names: set[str] = set()
    for key, job in jobs.items():
        if str(key) not in gone:
            continue
        for step in (job or {}).get("steps") or []:
            if "actions/upload-artifact" in str(step.get("uses") or ""):
                said = (step.get("with") or {}).get("name")
                if said:
                    names.add(str(said))
    return names


def thin_ci(names: list[str], repo: str, pin: str) -> str:
    """Тонкий `ci.yml` потребителя: вызовы шагов по тегу — и ничего своего (#992).

    РЕШЕНИЕ ВЛАДЕЛЬЦА 04.10.2026 по #992, вариант 3. «Что проверяется» у
    потребителя — набор этих вызовов, а класс каждой проверки — его
    `.pipeline.yml`. Сверяет одно с другим общий шаг `pipeline`
    (`check_pipeline.py`): у каждой проверки дерева есть ответ, у каждого
    ответа — проверка. Поэтому вызовы и есть данные, и второго списка «что
    включено» не заводится.

    СОБЫТИЯ И ОЧЕРЕДЬ — КАК У НАШЕГО `ci.yml` (взгляд на #1114). `push` на
    общую ветку нужен заготовке дежурного (`main-red.yml`): она ждёт
    `workflow_run` прогона `ci` на `main`, и без него сигнал не пришёл бы ни
    разу. Голова в группе очереди (179): последнее слово остаётся за прогоном
    последнего коммита, а не устаревшего.

    Пустой набор — отказ: прогон без джобов площадка не примет, а заход
    назвал бы его готовым.
    """
    if not names:
        raise NotRun("шагов к подключению в ci.yml нет — тонкий ci.yml был бы прогоном без джобов")
    head = (
        "# Тонкий вызов шагов конвейера: собран `scripts/onboard.py` поставщика.\n"
        "# Что проверяется — эти вызовы; класс каждой проверки — `.pipeline.yml`.\n"
        "# Сверяет одно с другим шаг `pipeline`: правьте оба вместе.\n"
        "name: ci\n\n"
        "on:\n"
        "  push:\n"
        f"    branches: [{paths.TRUNK}]\n"
        "  pull_request:\n"
        "    types: [opened, synchronize, reopened, labeled, unlabeled, edited]\n"
        "  workflow_dispatch:\n\n"
        "permissions:\n"
        "  contents: read\n"
        "  checks: read\n"
        "  pull-requests: read\n"
        "  issues: read\n\n"
        "concurrency:\n"
        "  group: ci-${{ github.event.pull_request.number || github.ref }}"
        "-${{ github.event.pull_request.head.sha || github.sha }}\n"
        "  cancel-in-progress: true\n\n"
        "jobs:\n"
    )
    return head + "\n".join(caller(one, repo, pin) for one in names)


def trunk_of(root: Path) -> str:
    """Общая ветка дерева потребителя по `origin/HEAD`; пусто — клон её не знает.

    ТРЕБОВАНИЕ, А НЕ УГАДЫВАНИЕ (решение по #1220). Имя общей ветки механизмы
    берут из `paths.TRUNK` и у потребителя его не ищут: перехват толчка прошёл
    пять форм одной беды на угадывании (#1218). Здесь ветка только СВЕРЯЕТСЯ
    при подключении — замер 09.10.2026: у всех шести проектов семьи она `main`.

    Сверяется ЛОКАЛЬНЫЙ кэш клона: `origin/HEAD` ставится клонированием, и
    `git fetch` его не обновляет — поэтому зовущий называет это в выводе.
    Дерево, не являющееся корнем своего клона, — тоже пусто: иначе git поднялся
    бы к внешнему репозиторию и сверил бы чужую ветку.
    """
    top = version.git("rev-parse", "--show-toplevel", root=root)
    if top is None or Path(top).resolve() != root.resolve():
        return ""
    said = version.git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", root=root)
    return (said or "").removeprefix("origin/")


#: Хост площадки. Отдельной константой, а не адресом в образце: адрес в
#: исходнике читает предикат ответа 095 как исходящий (`.rules/inapplicable.json`).
GITHUB_HOST: Final = "github.com"
_HOST = re.escape(GITHUB_HOST)

#: Адрес `origin`, из которого имя репозитория читается: площадка по `https`,
#: по `ssh` и прокси облачной сессии (`…@127.0.0.1:порт/git/владелец/репо`).
GITHUB_ORIGIN_RE: Final = re.compile(
    rf"^(?:https?:/{{2}}(?:[^/@]+@)?(?:www\.)?{_HOST}/|git@{_HOST}:|ssh:/{{2}}git@{_HOST}/"
    r"|https?:/{2}[^/@]+@(?:127\.0\.0\.1|localhost)(?::\d+)?/git/)"
    r"(?P<repo>[^/:]+/[^/:]+?)(?:\.git)?/?$"
)


def repo_of(root: Path) -> str:
    """Имя `владелец/репо` по адресу `origin` клона; пусто — клон его не называет.

    ИМЯ ЧИТАЕТСЯ ТОЛЬКО У АДРЕСА ПЛОЩАДКИ (взгляд на #1328, `d3639d2`). Две
    последние части ЛЮБОГО адреса давали имя и локальному пути
    (`/srv/git/repo`), и чужому хосту — и строка значка уверенно вела на
    несуществующий репозиторий. Теперь адрес вне `GITHUB_ORIGIN_RE` — пусто,
    и заход печатает заглушку. Дерево, не являющееся корнем своего клона, —
    тоже пусто, тем же приёмом, что у `trunk_of`.

    СОСЕДНИЕ РАЗБОРЫ `origin` НАЗВАНЫ, А НЕ СЛИТЫ (195, `61b15d5`):
    `check_branch_revival.repo_of` и `check_own_name.canon` отвечают на
    вопрос гейта о СВОЁМ клоне. Признак у них остался широким — две последние
    части любого адреса, `/srv/git/o/r` даёт `o/r` (взгляд на #1338), — и
    отказывают (`NotRun`) они, только когда частей меньше двух. Там это
    терпимо: имя идёт в запрос к площадке, и чужой адрес вернёт её отказ.
    Здесь имя уходит строкой в README потребителя, и ошибка не всплывёт —
    поэтому признак узкий, а неразбор даёт заглушку.

    ФОРМЫ АДРЕСА ПЛОЩАДКИ (`GITHUB_ORIGIN_RE`): `https` и `http`, с токеном
    перед хостом (`x-access-token@…` — так пишет `actions/checkout`) и с
    `www.`; `git@…:` и `ssh://git@…/`; прокси облачной сессии. Свой сервер
    площадки (GHE) и прочие хосты — заглушка.
    """
    top = version.git("rev-parse", "--show-toplevel", root=root)
    if top is None or Path(top).resolve() != root.resolve():
        return ""
    said = (version.git("remote", "get-url", "origin", root=root) or "").strip()
    found = GITHUB_ORIGIN_RE.match(said)
    return found.group("repo") if found else ""


def badge_line(repo: str) -> str:
    """Строка значка проекта для README потребителя — markdown со ссылкой на ветку значков.

    README ЗАХОД НЕ ПРАВИТ (решение владельца 12.10.2026, #1282): он почти
    всегда уже есть, а чужое заход не трогает. Строку кладёт владелец.

    ЗАКРЫТЫЙ РЕПОЗИТОРИЙ ЭТУ ССЫЛКУ НЕ ОТДАСТ: `raw.githubusercontent.com` без
    токена в приватном репозитории — всегда 404 (`scripts/badges_read.py`), и
    значок в README там не покажется. Условие печатается рядом со строкой
    (`PRIVATE_NOTE`), а не выясняется битой картинкой.
    """
    # Ветка — та, куда публикует общий шаг, а не вписанная рукой (`df6d81f`).
    branch = publish_facts.BRANCH
    return f"![проект](https://raw.githubusercontent.com/{repo}/{branch}/{BADGE.as_posix()})"


def occupied(root: Path, files: dict[Path, str]) -> list[Path]:
    """Файлы заготовки, которые в дереве потребителя уже есть — сами или двойником YAML.

    Их заход не трогает. Двойник — тоже «есть» (`standing`): свой `ci.yaml`
    рядом с положенным `ci.yml` дал бы два прогона (находка `1f2ca12`).
    """
    return sorted(path for path in files if (root / standing(root, path)).exists())


#: Строка лицензии в заготовке, которая уезжает к потребителю копией (#1470,
#: решение владельца 17.10.2026). MIT требует уведомления «во всех копиях или
#: существенных частях». Шаги по тегу и пакет транспорта лицензию несут сами:
#: потребитель читает их из нашего дерева. Положенное же в чужое дерево
#: становится его файлом, и без строки лицензия до него не доходит.
LICENSE_ID: Final = "SPDX-License-Identifier: MIT"
#: Как строка лицензии записывается в файле каждого рода, который кладёт заход.
#: JSON комментариев не знает, и строка там — поле `_license` первым ключом:
#: поля с `_` читатели наших таблиц пропускают.
LICENSE_FORMS: Final = {
    ".yml": "# {line}\n",
    ".yaml": "# {line}\n",
    ".md": "<!-- {line} -->\n",
    # Загрузчик зовётся `bash <путь>`, а не как исполняемый: строка лицензии
    # первой не отнимает у него `#!` (#1553).
    ".sh": "# {line}\n",
    ".py": "# {line}\n",
}
#: Первая строка исполняемого файла: строка лицензии идёт ПОСЛЕ неё (#1554) —
#: хук, который площадка зовёт как исполняемый, без `#!` первой не запустится.
SHEBANG: Final = "#!"


def split_shebang(text: str) -> tuple[str, str]:
    """`#!`-строка (с переводом строки) и остальное; без неё — пустая и весь текст."""
    if not text.startswith(SHEBANG):
        return "", text
    first, _, rest = text.partition("\n")
    return first + "\n", rest


#: Граница заголовка YAML у навыка: `SKILL.md` начинается с `---`, и площадка
#: читает навык, только если заголовок стоит первым (#1552).
FRONTMATTER: Final = "---\n"


def split_head(text: str) -> tuple[str, str]:
    """Что обязано стоять первым — `#!` или заголовок YAML — и остальное.

    Строка лицензии встаёт после этой головы: перед `#!` хук не запустился бы,
    перед заголовком навык не прочёлся бы. Нет головы — пустая и весь текст.
    """
    if text.startswith(FRONTMATTER):
        end = text.find("\n" + FRONTMATTER, len(FRONTMATTER) - 1)
        if end != -1:
            cut = end + 1 + len(FRONTMATTER)
            return text[:cut], text[cut:]
    return split_shebang(text)


def is_signed(path: Path, text: str) -> bool:
    """Подписана ли заготовка: строка лицензии стоит ПЕРВОЙ в форме своего рода.

    ПОДПИСЬ — МЕСТО, А НЕ УПОМИНАНИЕ (находки `c12022f`, `e776e88`). Прежде
    подписанной считалась заготовка, где идентификатор встречался где угодно:
    названный в тексте или в значении JSON, он отпускал файл к потребителю без
    строки, и гейты полноты подписи, судившие тем же упоминанием, молчали. У
    JSON подпись — поле `_license` первым ключом, у прочих родов — первая
    строка в форме `LICENSE_FORMS`.
    """
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError:
            return False
        first = next(iter(data), None) if isinstance(data, dict) else None
        return first == "_license" and str(data[first]).startswith(LICENSE_ID)
    form = LICENSE_FORMS.get(path.suffix)
    head = split_head(text)[1].split("\n", 1)[0]
    return form is not None and head.startswith(form.split("{line}", 1)[0] + LICENSE_ID)


def licensed(path: Path, text: str, repo: str) -> str:
    """Заготовка со строкой лицензии в форме своего рода; рода без формы — `NotRun`.

    Род без формы — отказ, а не файл без строки: новая заготовка другого рода
    ушла бы к потребителю молча неподписанной (045). Уже подписанная
    (`is_signed`) — как есть.
    """
    line = f"{LICENSE_ID} — https://github.com/{repo}"
    if is_signed(path, text):
        return text
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise NotRun(f"{path}: заготовка не разбирается как JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise NotRun(f"{path}: строку лицензии в JSON класть некуда — это не словарь")
        signed = {"_license": line, **data}
        return json.dumps(signed, ensure_ascii=False, indent=2) + "\n"
    form = LICENSE_FORMS.get(path.suffix)
    if form is None:
        raise NotRun(
            f"{path}: строку лицензии в файл рода «{path.suffix}» класть нечем — "
            "заготовка ушла бы к потребителю без неё (#1470)"
        )
    first, body = split_head(text)
    return first + form.format(line=line) + body


#: Что заход кладёт, но что становится файлом ПРОЕКТА, а не нашей заготовкой:
#: тонкий `ci.yml`, куда проект дописывает свои джобы (поздний взгляд на #1487,
#: `a4c2cc0`). Строку лицензии поставщика он не несёт ни при первой кладке, ни
#: при обновлении, ни двойником `.yaml` (`of_the_project`).
#: Настройки окна — туда же (#1554): проект дописывает в них свои разрешения, а
#: JSON настроек поля лицензии не ждёт.
#: `.gitignore` проекта: заход дописывает в него строку, а не кладёт свой (#1769).
IGNORE_FILE: Final = paths.GITIGNORE
OWN_BY_PROJECT: Final = frozenset({paths.WORKFLOWS / PIPELINE_FLOW, paths.SETTINGS, IGNORE_FILE})


def of_the_project(path: Path) -> bool:
    """Файл проекта, а не наша заготовка: строки лицензии поставщика он не несёт.

    ОДИН ПРИЗНАК НА ВСЕ ДВЕРИ (находка `215204f`, правило 210). Чей файл,
    решалось по месту: `theirs` плана обновления, отдельная оговорка у печати,
    `OWN_BY_PROJECT` у кладки — и каждая новая дверь находила свой хвост
    (`6316c1f`, `b803933`, `a4c2cc0`). Двойник YAML — тот же файл.
    """
    return path in OWN_BY_PROJECT or path.with_suffix(".yml") in OWN_BY_PROJECT


def signed_all(files: dict[Path, str], repo: str) -> dict[Path, str]:
    """Все заготовки со строкой лицензии — разом; отказ одной — `NotRun` до записи.

    Зовётся и ДО первой записи, внутри перехвата отказов захода: половина
    положенной заготовки хуже никакой, а `NotRun` вне перехвата ушёл бы трассой
    с кодом 1 вместо исхода «не отработал» (039). Файл проекта
    (`of_the_project`) идёт как есть.
    """
    return {
        path: text if of_the_project(path) else licensed(path, text, repo)
        for path, text in files.items()
    }


def lay(root: Path, files: dict[Path, str], repo: str) -> None:
    """Кладёт заготовку в дерево потребителя, каждую — со строкой лицензии (#1470).

    Занятое проверяет зовущий (`occupied`). Подпись ставится здесь, на единственном
    пути ЗАПИСИ к потребителю, а не в каждой заготовке: путь записи один, а
    заготовки собираются в нескольких местах, и новое место ушло бы мимо. Второй
    путь заготовки к потребителю — печать захода без ключей; она подписывает
    целые файлы тем же `signed_all`. Файл проекта (`of_the_project`) не
    подписывается: строка поставщика в нём объявила бы его чужим.
    """
    kitted = {path: blob_of(text) for path, text in files.items() if path in LAID_KINDS}
    # ПЕРЕЧЕНЬ ЧИТАЕТСЯ ДО ЗАПИСИ (взгляд на #1651, `41c6027`): битый
    # `.claude/kit-laid.json` прежде обнаруживался после того, как хуки и навыки
    # уже легли, — файлы лежали, перечень не записан, заход кончался отказом.
    # Теперь отказ случается до первого файла, и дерево остаётся прежним.
    laid = laid_of(root) if kitted else {}
    for path, text in signed_all(files, repo).items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
        # Файл с `#!` площадка зовёт как исполняемый (`.claude/settings.json`):
        # без права на исполнение хук не запустился бы (#1554).
        if text.startswith(SHEBANG):
            (root / path).chmod(0o755)
    if kitted:
        write_laid(root, {**laid, **kitted}, repo)


#: Пояснение в самом перечне: файл лежит у потребителя, и читает его человек.
LAID_NOTE: Final = (
    "Перечень положенного заходом подключения механизмов: путь → имя git-объекта "
    "текста, положенного последним (без строки лицензии). По нему обновление "
    "узнаёт неправленую копию. Руками не правится; удалённый — обновление судит "
    "по истории поставщика, как прежде."
)


def laid_of(consumer: Path) -> dict[Path, str]:
    """Перечень положенного у потребителя; нет файла — пусто, битый — `NotRun` (045)."""
    where = consumer / paths.KIT_LAID
    if not where.is_file():
        return {}
    try:
        said = json.loads(where.read_text(encoding="utf-8"))
        laid = said["laid"]
        # Имя объекта — полный sha: образец один на дерево (214), у гейта форм.
        if not isinstance(laid, dict) or not all(
            isinstance(one, str) and check_workflow_forms.SHA_RE.fullmatch(one)
            for one in laid.values()
        ):
            raise ValueError("«laid» — не отображение путей в имена объектов")
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise NotRun(
            f"`{paths.KIT_LAID}` не разобран: {exc} — удалите его, и обновление "
            "будет судить копии по истории поставщика"
        ) from exc
    return {Path(path): blob for path, blob in laid.items()}


def write_laid(consumer: Path, laid: dict[Path, str], repo: str) -> None:
    """Пишет перечень положенного — по путям в порядке и с подписью, как прочие заготовки."""
    (consumer / paths.KIT_LAID).parent.mkdir(parents=True, exist_ok=True)
    body = {"_": LAID_NOTE, "laid": {str(path): laid[path] for path in sorted(laid)}}
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    (consumer / paths.KIT_LAID).write_text(licensed(paths.KIT_LAID, text, repo), encoding="utf-8")


def rulebook_kit(root: Path) -> dict[Path, str]:
    """Заготовка свода окна: файл `kit/<имя>` ложится у потребителя под `<имя>`.

    Состав — из дерева, а не списком: второй перечень имён свода отстал бы молча
    (022). Пустой `kit/` — отказ: заход назвал бы подключение полным без свода.
    """
    found = {
        Path(one.name): one.read_text(encoding="utf-8")
        for one in sorted((root / paths.KIT).glob("*.md"))
    }
    if not found:
        raise NotRun(f"заготовки свода нет: {paths.KIT}/ пуст — окну потребителя нечем работать")
    return found


#: Заготовки данных, которые общие шаги читают из дерева потребителя (#1386):
#: `kit/data/<путь>` ложится у потребителя под `<путь>`, только в свободное.
DATA_KIT: Final = paths.KIT / "data"
#: Что кладётся из `DATA_KIT` — перечень объявленных якорей, а не обход
#: каталога: решение владельца назвало состав поимённо, а якорь у каждого пути
#: уже есть. Таблица областей сюда не входит — она собирается (`area_kit`).
#: Совпадение перечня с `kit/data/` держит `tests/test_onboard.py`.
DATA_KITTED: Final = (
    paths.REVIEW_ROLES,
    paths.REVIEW_PROCEDURE,
    paths.ROLES,
    paths.DEPENDABOT,
    # #1557: почти целиком общие — состав меток и словарь родов находок; форма
    # без наполнения — очередь предложений, перезапуск; требование конвейера —
    # объявление защиты ветки; наши числа как умолчание — границы ряда прогонов.
    paths.LABELS,
    paths.FINDING_KINDS,
    paths.PROPOSALS,
    paths.PROTECTION,
    paths.SERIES,
    paths.RERUN,
    # #1645: карта направлений и перепись механизмов — форма с пустым
    # наполнением: направления и правила общие, исходы и места — проекта.
    paths.DIRECTIONS,
    paths.MECHANISM_RULES,
    # #1553: предполётная у потребителя — загрузчик, а не копии скриптов (090).
    paths.PREFLIGHT_LOADER,
    # #1552: запускатель — общий вход к скриптам механизмов у потребителя.
    paths.LAUNCHER,
    # #1554: хуки с ответом `configured` — заготовкой со слотом, а не нашим
    # наполнением: число планки ставит заход, окружение проверки — проект.
    paths.FLOOR,
    paths.SESSION_START,
    # #1763: порядок источников работы читают навыки окна (`paths.py behaviour`);
    # заготовка — форма с местами «Наполнение проекта», порядок — проекта.
    paths.BEHAVIOUR,
)
#: Что кладётся из НАШЕГО дерева как есть (#1554): хуки окна с ответом `as-is`
#: и настройки, что подключают их к событиям площадки. Копия в `kit/data/` была
#: бы второй реализацией (214) — кладётся сам файл. Совпадение с ответами
#: `as-is` под `.claude/` держит `tests/test_onboard.py`.
TREE_KITTED: Final = (
    paths.SETTINGS,
    paths.HOOKS / "push_guard.py",
    paths.HOOKS / "push_guard.sh",
    paths.HOOKS / "skill_log.py",
    paths.HOOKS / "skill_log.sh",
    # #1708: совет о пачке при нарезке `agent/…` — зовёт разбор стража толчка.
    paths.HOOKS / "bundle_hint.py",
    paths.HOOKS / "bundle_hint.sh",
    paths.HOOKS / "install_floor.sh",
)
#: Навыки окна, которые кладутся копией (#1552, решение владельца 24.10.2026;
#: четыре навыка `@skill-tree` добавлены по #1645 — их ссылки на наше дерево
#: переводит подстановка, а карта направлений и перепись механизмов ложатся
#: заготовкой). Совпадение с ответами `as-is` держит `tests/test_onboard.py`.
SKILLS_KITTED: Final = tuple(
    paths.SKILLS / name / "SKILL.md"
    for name in (
        "a-gate-obeys-every-rule",
        "a-task-before-the-work",
        "answer-a-rule",
        "audit-the-answers",
        "build-a-gate",
        "bundle-the-work",
        "close-a-finding",
        "direction-coverage",
        "propose-a-rule",
        "restart-the-window",
        "retell-from-the-source",
        "role-profile",
        "rulebook-keeps-how-to-work",
        "rulebook-reread",
        "tell-the-supplier",
        "what-the-graph-misses",
        "work-the-plan",
    )
)
#: Что записывается в перечень положенного: то, что `plan_tree` судит как
#: устаревшее или правленое, — хуки и навыки. Настройки окна — файл проекта
#: (`of_the_project`), `plan_tree` их не судит, и запись о них никто бы не
#: прочёл (взгляд на #1651).
LAID_KINDS: Final = frozenset(
    path for path in (*TREE_KITTED, *SKILLS_KITTED) if not of_the_project(path)
)
#: Команда скрипта в тексте навыка: у потребителя скриптов в дереве нет, и она
#: зовётся запускателем (`paths.LAUNCHER`).
SKILL_CALL: Final = re.compile(r"\bpython3? scripts/([A-Za-z0-9_]+\.py)")
#: Имя кода, теста или документа поставщика в тексте навыка: у потребителя таких
#: путей нет, и навык ведёт к ним ссылкой на дерево поставщика (#1637). Имя,
#: уже подписанное «поставщика» в исходнике, подпись теряет и получает адрес;
#: имя внутри ссылки разметки (`[` перед ним) — уже адрес, и оно не трогается.
SUPPLIER_REF: Final = re.compile(r"(?<!\[)`((?:scripts|tests|docs)/[^`\s]+)`(?: поставщика)?")
#: Подпись ссылки разметки — `[…](`: имя внутри неё уже часть адреса, где бы в
#: подписи оно ни стояло (`[см. \`scripts/x.py\`](…)`), и в ссылку не оборачивается:
#: иначе вышла бы ссылка в ссылке (взгляд на #1639, `c2f998a`).
LINK_LABEL: Final = re.compile(r"\[[^\[\]\n]*\]\(")
#: Относительная ссылка разметки в тексте навыка: цель отсчитывается от его каталога.
SKILL_LINK: Final = re.compile(r"\]\((?P<target>\.\./[^)\s#]+)(?P<anchor>#[^)\s]*)?\)")
#: Каталог навыка от корня дерева: `.claude/skills/<имя>/` — у всех навыков один.
SKILL_DEPTH: Final = 3
#: Голый номер задачи в тексте навыка: у потребителя `#639` вёл бы в ЕГО трекер.
BARE_ISSUE: Final = re.compile(r"(?<![\w/#&])#(\d+)\b")


def skill_kit(text: str, repo: str) -> str:
    """Навык в форме потребителя: команды — запускателем, наши файлы — адресом поставщика.

    Голый номер задачи становится полным адресом трекера поставщика `repo`.
    Функция текста и имени поставщика, без прибивки: копию из любой версии
    истории `plan_tree` узнаёт той же подстановкой.
    """

    def call(found: re.Match[str]) -> str:
        script = found[1]
        return (
            f"bash {paths.PREFLIGHT_LOADER}"
            if script == "preflight.py"
            else (f"bash {paths.LAUNCHER} {script}")
        )

    def ref(found: re.Match[str]) -> str:
        if any(start < found.start() < end for start, end in labels):
            return found[0]
        # Документ, который заход кладёт потребителю (`docs/agent/roles.md`), —
        # его собственный: ссылка на него ведёт в его дерево.
        file = found[1].split("::", 1)[0]
        if Path(file) in DATA_KITTED:
            return found[0]
        # Имя без адреса потребителю открыть нечем (#1637): ссылка — на общую
        # ветку, как у относительных ссылок ниже, и по той же причине.
        address = f"https://github.com/{repo}/blob/{paths.TRUNK}/{file}"
        return f"[`{found[1]}`]({address}) поставщика"

    def link(found: re.Match[str]) -> str:
        # Цель вне дерева потребителя ведёт в дерево поставщика полным адресом:
        # подпись «поставщика» при относительной цели вела бы в пустоту (взгляд
        # на #1626). Общая ветка, а не прибивка: подстановка не зависит от тега,
        # и старую копию `plan_tree` узнаёт той же функцией.
        target = Path(found["target"]).parts
        ups = len(list(itertools.takewhile(lambda part: part == "..", target)))
        rest = "/".join(target[ups:]) + (found["anchor"] or "")
        # Выше корня дерева — адрес площадки (`../../../../../issues/767`: подъём
        # навыка к площадке — пять звеньев, гейт ссылок, #1692).
        if ups > SKILL_DEPTH:
            return f"](https://github.com/{repo}/{rest})"
        base = SKILLS_KITTED[0].parent.parts[: SKILL_DEPTH - ups]
        where = Path(*base, *target[ups:])
        if where in laid_at_the_consumer():
            return found[0]
        prefix = "".join(f"{part}/" for part in base)
        return f"](https://github.com/{repo}/blob/{paths.TRUNK}/{prefix}{rest})"

    called = SKILL_CALL.sub(call, text)
    labels = [one.span() for one in LINK_LABEL.finditer(called)]
    shaped = SUPPLIER_REF.sub(ref, called)
    shaped = SKILL_LINK.sub(link, shaped)
    return BARE_ISSUE.sub(rf"{repo}#\1", shaped)


def laid_at_the_consumer() -> set[Path]:
    """Что заход кладёт потребителю: данные, хуки, навыки и свод (#1552)."""
    # Состав свода — у гейта его свежести, а не второй список здесь (022).
    rulebook = {Path(one) for one in check_rulebook_fresh.RULEBOOK}
    return {*DATA_KITTED, *TREE_KITTED, *SKILLS_KITTED, *rulebook}


def shape_of(path: Path, repo: str) -> Callable[[str], str]:
    """Как наш файл выглядит у потребителя: навык — подстановкой, остальное — как есть."""
    if path in SKILLS_KITTED:
        return lambda text: skill_kit(text, repo)
    return lambda text: text


#: Слот планки в заготовке `floor.sh`: число ставит заход из НАШЕГО
#: `requires-python` — код хуков наш и исполняется на нашей планке (#1554).
FLOOR_SLOT: Final = "@floor@"
#: Данные потребителя, которым заготовки НЕТ, — с причиной (#1557). Каждый путь
#: `consumer_data` стоит либо в `DATA_KITTED`, либо здесь; держит это
#: `tests/test_onboard.py`, и путь, исчезнувший из перечня, здесь не переживает.
KIT_REFUSED: Final = {
    paths.ATTRIBUTION_SINCE: "отметка — коммит ВАШЕЙ истории, с которого атрибуция обязательна",
    paths.AUTHORS: "имена — ваших людей; наши дали бы чужим право подписи",
    paths.BINDINGS: "ответ проекта каталогу: его форму ведёт каталог (решение 17.10.2026)",
    paths.SCHEDULES: "цена и роль ВАШИХ прогонов по расписанию: состав знает только ваше дерево",
    paths.SHOWCASE: "вопросы вашей витрины: наш набор отвечал бы о нашем проекте",
    paths.VENDOR_WATCH: "знание, снятое с кода ваших закреплений действий, а не наших",
    paths.WORKFLOW_FORMS: "исключения ваших прогонов, с вашими причинами; нет файла — нет их",
    paths.RELEASE_DOC: "шаги называют документ ссылкой в сообщении; порядок выпуска — ваш",
    paths.DECISIONS: "записи ваших решений; пустой каталог законен",
    paths.ENTRANCE: "ваш вход: он называет ВАШЕ отданное; другой файл — разделом shipped",
    paths.PORTABLE: "перепись того, что ВЫ отдаёте; нет файла — нет её раздела на странице выпуска",
    paths.FEEDBACK_VERDICTS: (
        "вердикты по записям соседей о ВАШИХ механизмах; нет файла — нет раздела выпуска"
    ),
}
#: Пути области в заготовке: ЛЮБОЙ путь — в корне и вглубь (`review_map.matches`).
#: Не пустые: пустой `paths` карта читает «поверхности нет» и правила области
#: роли не отдаёт, то есть незаполненная заготовка давала бы роли МЕНЬШЕ, чем
#: отсутствие таблицы (взгляд на #1455). Любой путь — то же, что без таблицы.
AREA_ANY: Final = ("*", "**/*")
#: Где ведётся роль «правила каталога» и её недельная отдача по семье — полным
#: адресом: потребитель читает строку у себя, и голый номер вёл бы в ЕГО трекер.
ROLE_HOME: Final = "https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms/issues/1277"
#: Пояснение области в заготовке: что заполнять.
AREA_FILL: Final = (
    "заготовка: область задевает любой путь, и роль получает все её правила, как без "
    "таблицы. Наполнение проекта: образцы путей своего дерева, которые область "
    "задевает, или пустой список с причиной, почему поверхности у неё нет"
)


def area_kit(root: Path) -> str:
    """Заготовка таблицы «область каталога → пути»: области — наши, пути — пустые с причиной.

    ОБЛАСТИ ВЫВОДЯТСЯ ИЗ НАШЕЙ ТАБЛИЦЫ, А НЕ ПИШУТСЯ ВТОРЫМ СПИСКОМ (022): её
    покрытие областей каталога сверяет `tests/test_area_paths.py`. Пути — свои у
    каждого дерева; до наполнения область задевает любой путь (`AREA_ANY`).
    """
    try:
        table = policy.project_path("area-paths", root)
    except paths.BadPaths as exc:
        raise NotRun(f"таблица путей не разобрана: {exc}") from exc
    try:
        areas = json.loads((root / table).read_text(encoding="utf-8"))["areas"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise NotRun(f"`{table}` не разобран: {exc!r}") from exc
    if not isinstance(areas, dict) or not areas:
        raise NotRun(f"`{table}`: нет словаря `areas` — областей для заготовки нет")
    kit = {
        "_": (
            "Области каталога → пути этого дерева — заготовка механизмов (#1386). Роль "
            "взгляда «правила каталога» получает только правила, чьи области задеты "
            "тронутыми путями. Ключи — английские имена областей выгрузки каталога."
        ),
        "schema": 1,
        "areas": {str(name): {"paths": list(AREA_ANY), "why": AREA_FILL} for name in sorted(areas)},
    }
    return json.dumps(kit, ensure_ascii=False, indent=2) + "\n"


#: Слот владельца в заготовке `dependabot.yml`: своя семья у потребителя — это
#: владелец механизмов, которые он зовёт, а не наше имя буквами (у соседа
#: оно другое). Заход ставит на его место владельца из `--repo`.
FAMILY_SLOT: Final = "OWNER/*"

#: Форма `--repo`, как её принимает площадка: владелец — латиница, цифры и
#: дефис без ведущего и замыкающего, не длиннее 39; имя — `[A-Za-z0-9._-]+`.
#: Ровно одна косая: `a/b/c` владельцем семьи не является.
REPO_RE: Final = re.compile(
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/(?P<name>[A-Za-z0-9._-]+)"
)


def data_kit(root: Path, repo: str) -> dict[Path, str]:
    """Заготовки данных потребителя: `kit/data/<путь>` → `<путь>` (#1386, #1557).

    Состав — `DATA_KITTED`; недостающий файл — отказ, а не тихий пропуск (045).
    `bindings.json` заготовкой не кладётся
    (решение владельца 17.10.2026): это ответ проекта каталогу, и его форму
    ведёт каталог — наш скелет стал бы вторым источником формы (022).
    """
    missing = [path for path in DATA_KITTED if not (root / DATA_KIT / path).is_file()]
    if missing:
        raise NotRun(
            f"заготовок данных нет в {DATA_KIT}/: "
            + ", ".join(str(one) for one in missing)
            + " — шаги, что читают эти данные, у потребителя не отработали бы"
        )
    found = {path: (root / DATA_KIT / path).read_text(encoding="utf-8") for path in DATA_KITTED}
    said = found[paths.DEPENDABOT]
    if f'"{FAMILY_SLOT}"' not in said:
        raise NotRun(
            f"в заготовке {paths.DEPENDABOT} нет слота семьи «{FAMILY_SLOT}» — "
            "выпуск механизмов ждал бы у потребителя выдержку чужого"
        )
    shaped = REPO_RE.fullmatch(repo)
    if shaped is None:
        # Без формы «владелец/имя» владельца нет: `Mechanisms` дал бы слот
        # «Mechanisms/*», и выпуск семьи молча ждал бы выдержку чужого (045).
        # Сверяется ФОРМА имени, а не непустота частей: `a/b/c` давал слот
        # `a/*`, а владелец с пробелом или кавычкой ломал YAML заготовки.
        raise NotRun(
            f"--repo «{repo}» не «владелец/имя» — владельца семьи для {paths.DEPENDABOT} не взять"
        )
    found[paths.DEPENDABOT] = said.replace(f'"{FAMILY_SLOT}"', f'"{shaped["owner"]}/*"')
    found[paths.FLOOR] = floor_kit(root, found[paths.FLOOR])
    return found | {paths.AREA_PATHS: area_kit(root)} | tree_kit(root, repo)


def floor_kit(root: Path, said: str) -> str:
    """Заготовка `floor.sh` с числом НАШЕЙ планки на месте слота (#1554).

    Планка читается тем же разборщиком, что у хука старта и предполётной, —
    `check_env.python_floor` (214). Нет слота — отказ: заготовка ушла бы с
    чужим или пустым числом, и страж закрыл бы каждый толчок потребителя.
    """
    if FLOOR_SLOT not in said:
        raise NotRun(f"в заготовке {paths.FLOOR} нет слота планки «{FLOOR_SLOT}»")
    try:
        major, minor = check_env.python_floor(root)
    except check_env.NotRun as exc:
        raise NotRun(f"планка для {paths.FLOOR} не прочитана: {exc}") from exc
    return said.replace(FLOOR_SLOT, f"{major}.{minor}")


def tree_kit(root: Path, repo: str) -> dict[Path, str]:
    """Хуки окна и настройки из нашего дерева — как есть (`TREE_KITTED`, #1554).

    Недостающий файл — отказ, а не тихий пропуск (045): настройки звали бы хук,
    которого у потребителя нет.
    """
    missing = [path for path in (*TREE_KITTED, *SKILLS_KITTED) if not (root / path).is_file()]
    if missing:
        raise NotRun(
            "файлов окна нет в нашем дереве: "
            + ", ".join(str(one) for one in missing)
            + " — окно потребителя звало бы отсутствующее"
        )
    return {path: (root / path).read_text(encoding="utf-8") for path in TREE_KITTED} | {
        path: skill_kit((root / path).read_text(encoding="utf-8"), repo) for path in SKILLS_KITTED
    }


def settings_note(consumer: Path, laid: list[Path], repo: str, pin: str) -> str:
    """Свои настройки окна у потребителя не тронуты — и хуки к ним не подключены.

    Сказано вслух (045): хуки лежат, но площадка их не зовёт, пока проект не
    перенесёт раздел `hooks` из наших настроек в свои. Адрес — файл поставщика
    на прибивке: печать захода настроек не выводит (взгляд на #1619).
    """
    if paths.SETTINGS in laid or not (consumer / paths.SETTINGS).exists():
        return ""
    return (
        f"`{paths.SETTINGS}` уже есть и не тронут: хуки окна в {paths.HOOKS}/ не "
        "подключены, пока вы не перенесёте в него раздел `hooks` из настроек "
        f"поставщика — https://github.com/{repo}/blob/{pin}/{paths.SETTINGS.as_posix()}"
    )


def unsigned(path: Path, text: str) -> str:
    """Заготовка без строки лицензии, которую поставил `licensed`: та, что лежит у нас."""
    if not is_signed(path, text) or path.suffix == ".json":
        return text
    first, body = split_head(text)
    return first + body.partition("\n")[2]


def blob_of(text: str) -> str:
    """Имя git-объекта для текста — как `git hash-object`, без вызова git."""
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def blobs_in_history(root: Path, path: Path, shape: Callable[[str], str]) -> set[str]:
    """Все содержимые нашего файла по истории поставщика — в форме потребителя (`shape`).

    Так узнаётся устаревшая копия: она равна одной из прежних версий, пропущенной
    через ту же подстановку, что и новая (#1552). Мелкий клон всей истории не
    знает, и неправленая старая копия выглядела бы правленой — поэтому он отказ
    с названной причиной, а не совет нести задачу поставщику (взгляд на #1619).
    """

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=gitcall.LOCAL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotRun(f"история {path} не прочитана: {exc}") from exc

    shallow = git("rev-parse", "--is-shallow-repository")
    if shallow.stdout.strip() == "true":
        raise NotRun(
            f"клон поставщика мелкий — по его истории устаревшую копию {path} не узнать; "
            "позовите обновление из полного клона (`git fetch --unshallow`)"
        )
    done = git("log", "--format=%H", "--", str(path))
    if done.returncode:
        raise NotRun(f"история {path} не прочитана: {done.stderr.strip() or done.returncode}")
    found: set[str] = set()
    for commit in done.stdout.split():
        said = git("show", f"{commit}:{path.as_posix()}")
        # Коммит, удаливший файл, содержимого не несёт — он не версия.
        if said.returncode == 0:
            found.add(blob_of(shape(said.stdout)))
    return found


def plan_floor(update: Update, consumer: Path, ours: str) -> None:
    """`floor.sh` потребителя ниже нашей планки — поднять число, не трогая остального.

    Код хуков наш и идёт на нашей планке: старый `want` потребителя после подъёма
    стража дал бы `SyntaxError`, а такой отказ площадка считает неблокирующим
    (взгляд на #1619, 195). Выше нашей — выбор проекта, файл не трогается.
    """
    target = consumer / paths.FLOOR
    wanted = WANT_LINE.search(ours)
    if not target.is_file() or wanted is None:
        return
    mine = target.read_text(encoding="utf-8")
    have = WANT_LINE.search(mine)
    if have is None:
        # Файл проекта, а не наша копия: отказ на всё обновление с советом нести
        # разницу поставщику назвал бы не ту причину (взгляд на #1626). Строка
        # вывода — и обновление идёт дальше.
        update.notes.append(
            f"`{paths.FLOOR}`: строки want=X.Y не нашлось — планку хуков сверьте сами, "
            f"механизмам нужна не ниже {wanted[2]}"
        )
    elif version_of(have[2]) < version_of(wanted[2]):
        # Меняется только число: кавычки и хвостовой комментарий — проекта.
        start, end = have.span(2)
        update.write[paths.FLOOR] = mine[:start] + wanted[2] + mine[end:]
    else:
        update.current.append(paths.FLOOR)


#: Строка планки в `floor.sh`: одно присваивание `want=X.Y`.
WANT_LINE: Final = re.compile(r"^want=([\"']?)(\d+\.\d+)\1[ \t]*(?:#.*)?$", re.M)


def version_of(said: str) -> tuple[int, ...]:
    """`3.14` → `(3, 14)`: планки сравниваются числами, а не строками («3.9» > «3.14»)."""
    return tuple(int(part) for part in said.split("."))


def plan_tree(update: Update, consumer: Path, tree: dict[Path, str], root: Path, repo: str) -> None:
    """Хуки окна как есть: устаревшая копия переписывается, правленая — отказ (взгляд на #1619).

    Без этого однажды положенный страж толчка не обновлялся бы никогда: `--update`
    кладёт заготовки данных только в свободное, и починка стража до потребителя
    не дошла бы (214). Устаревшая — та, что совпала с записью перечня
    положенного (`paths.KIT_LAID`), либо та, чьё содержимое было нашим в какой-то
    момент истории. ПЕРЕЧЕНЬ ПЕРВЕЕ ИСТОРИИ (находка `f7e5ee4`): история
    пропускается через НЫНЕШНЮЮ подстановку `skill_kit`, и копия, положенная до
    её правки, ни с одной версией не совпала бы — `--update` отказал бы целиком
    на неправленом. Перечень хранит то, что положено на самом деле; копии,
    положенные до перечня, по-прежнему узнаёт история. Настройки окна — файл
    проекта (`of_the_project`) и здесь не судятся.
    """
    laid = laid_of(consumer)
    for path, ours in sorted(tree.items()):
        target = consumer / path
        if of_the_project(path) or not target.is_file():
            continue
        mine = unsigned(path, target.read_text(encoding="utf-8"))
        if mine == ours:
            update.current.append(path)
        elif blob_of(mine) == laid.get(path) or blob_of(mine) in blobs_in_history(
            root, path, shape_of(path, repo)
        ):
            update.write[path] = ours
        else:
            update.edited[path] = "".join(
                difflib.unified_diff(
                    ours.splitlines(keepends=True),
                    mine.splitlines(keepends=True),
                    "поставщик",
                    "ваш",
                )
            )


#: Расширения YAML, которые площадка читает одинаково: `dependabot.yaml` занимает
#: место `dependabot.yml`, и второй файл рядом дал бы два конфига (взгляд на #1455).
YAML_TWINS: Final = {".yml": ".yaml", ".yaml": ".yml"}


def read_by_the_platform(path: Path) -> bool:
    """Файл, который площадка читает под ЛЮБЫМ из двух расширений: прогон и `dependabot`.

    Свои файлы механизмов (`.pipeline.yml`, данные `.rules/`) читаются точным
    именем: двойник им места не занимает — механизм его не увидел бы.
    """
    return path.parent == paths.WORKFLOWS or path.with_suffix(".yml") == paths.DEPENDABOT


def standing(consumer: Path, path: Path) -> Path:
    """Путь, под которым файл заготовки стоит у потребителя: сам, двойник YAML или сам.

    ОДИН РАЗБОР НА ВСЕ ДВЕРИ (находка `1f2ca12`, правило 195). Двойника видела
    только заготовка данных, а `--write` клал `ci.yml` рядом со своим
    `ci.yaml`, и `--update` — тоже: два прогона на одно событие. Нет ни
    файла, ни двойника — сам путь: туда и ляжет.
    """
    if (consumer / path).exists() or not read_by_the_platform(path):
        return path
    twin = path.with_suffix(YAML_TWINS.get(path.suffix, path.suffix))
    return twin if (consumer / twin).exists() else path


def taken_by_twin(consumer: Path, path: Path) -> bool:
    """Путь занят файлом-двойником с другим расширением YAML."""
    return standing(consumer, path) != path


def lay_free(consumer: Path, kit: dict[Path, str], repo: str) -> list[Path]:
    """Кладёт заготовку только в свободные пути; возвращает положенное."""
    taken = set(occupied(consumer, kit))
    free = {path: text for path, text in kit.items() if path not in taken}
    lay(consumer, free, repo)
    return sorted(free)


#: Состояние окна, которое пишут положенные хуки: журнал навыков (#1769).
STATE_IGNORE: Final = f"{paths.SKILL_RUNS.parent.as_posix()}/"
#: Строки `.gitignore`, уже закрывающие состояние окна, — без `/` по краям.
STATE_COVERED: Final = frozenset({paths.SKILL_RUNS.parent.as_posix(), paths.SKILL_RUNS.parts[0]})


def ignore_state(consumer: Path) -> bool:
    """Дописывает `.claude/state/` в `.gitignore` потребителя; True — дописано.

    Хуки окна, что кладёт заход, пишут журнал навыков туда, и без строки
    стоп-хук просил закоммитить состояние окна (#1769, замер на EPL). Чужие
    строки не трогаются, уже стоящая не дублируется; файла нет — создаётся.
    """
    ignore = consumer / IGNORE_FILE
    text = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    # Уже закрыто — и родительской строкой, и формой с корневым `/` или без
    # хвостового `/` (взгляд на #1775): дописанная поверх была бы дублем.
    if any(line.strip().strip("/") in STATE_COVERED for line in text.splitlines()):
        return False
    tail = "" if not text or text.endswith("\n") else "\n"
    ignore.write_text(f"{text}{tail}{STATE_IGNORE}\n", encoding="utf-8")
    return True


def bindings_note(consumer: Path) -> str:
    """Названное отсутствие ответа каталогу: без него карта взгляда не собирается.

    Адрес — по таблице путей потребителя (#1632): ответ, переназначенный им,
    ищется там, где он его положил.
    """
    try:
        answer = policy.project_path("bindings", consumer)
    except paths.BadPaths as exc:
        return f"Ответ каталогу не проверен: раздел путей не разобран — {exc}"
    if (consumer / answer).exists():
        return ""
    return (
        f"`{answer}` нет: без него карта взгляда не собирается, `audit_profile.py` "
        "отказывает, а навыки `answer-a-rule`, `audit-the-answers` и `close-a-finding` "
        "молчат. Заготовкой он не кладётся — это ответ проекта каталогу правил: скелет "
        f"собирает заход подключения КАТАЛОГА (`onboard_consumer.py --repo "
        f"<владелец/имя> --out <папка>` в клоне {CATALOGUE_REPO}, его `CONNECT.md`), "
        "а заявка `consumer-announce` подаётся каталогу, когда ответ лёг на вашу "
        "общую ветку (#1763)."
    )


def data_note(data: list[str]) -> str:
    """Данные общих шагов, которых заготовка не кладёт, — построчно и с причиной.

    Голый перечень путей через запятую не говорил, почему заготовки нет и что
    заводить (#1763): причина берётся из `KIT_REFUSED`, у пути без неё —
    только путь.
    """
    return "Данных общих шагов заготовка не кладёт — заведите их у себя:\n" + "\n".join(
        f"  - {one}" + (f" — {KIT_REFUSED[Path(one)]}" if Path(one) in KIT_REFUSED else "")
        for one in data
    )


#: Метка места, которое заготовка оставляет проекту: свод и данные её несут (#1763).
FILLING: Final = "Наполнение проекта"


def filling_note(consumer: Path, laid: Iterable[Path]) -> str:
    """Положенные заготовки с местами «Наполнение проекта» — путь и число мест.

    Заготовка кладёт форму, а перечень захода о её пустых местах молчал
    (#1763): свод с девятью незаполненными разделами выглядел подключённым.
    Пусто — пустая строка: о незаполненном нечего сказать.
    """
    counted = [
        (one, text.count(FILLING))
        for one in sorted(set(laid))
        if (consumer / one).is_file()
        and (text := (consumer / one).read_text(encoding="utf-8")).count(FILLING)
    ]
    if not counted:
        return ""
    return f"Места «{FILLING}» в положенном — заполните их своим:\n" + "\n".join(
        f"  - {one}: {count}" for one, count in counted
    )


#: Каталог правил: подключение к нему и список семьи ведёт он (#1763).
CATALOGUE_REPO: Final = "ArtVsMark/Engineering-Incidents-Playbook"


def family_steps_note() -> str:
    """Что заводится на площадке после захода — задача плана и объявления (#1763).

    Заход идёт без площадки и ничего на ней не заводит (154), поэтому называет:
    без живой задачи плана сборщик `work-plan` отказывает; без объявления у нас
    смена контракта до вас не дойдёт, без объявления в каталоге проект не
    виден списку семьи и значкам (`uptake`). Замер — проба #1558 на EPL.
    """
    return (
        "На площадке заведите сами (заход туда не пишет, 154):\n"
        "  - живую задачу плана работ — задачу с первой строкой тела "
        f"`{findings.PLAN_MARKER}`: без неё прогон `work-plan` отказывает «живой "
        "задачи плана нет»; тело дальше пишет сборщик;\n"
        "  - объявление у поставщика механизмов — строкой в `.rules/consumers.json` "
        "или обращением «подключился» (`docs/use/onboarding.md`, «Объявитесь»): иначе "
        "оповещение о смене контракта до вас не дойдёт;\n"
        f"  - объявление в каталоге правил ({CATALOGUE_REPO}, заявка "
        "`consumer-announce`): иначе проект не виден списку семьи и значкам."
    )


def dormant_areas_note(consumer: Path) -> str:
    """Названная спячка таблицы областей: роль, которой она отдаёт правила, не объявлена.

    СКЕЛЕТ РОЛЬ ОБЪЯВЛЯЕТ С РАСКАТКИ (решение владельца 26.10.2026, #1277):
    заготовка таблицы ролей кладёт «правила каталога» в `required`. Но проект,
    подключённый раньше, свою таблицу ролей держит сам — `--update` её не
    переписывает, — и у него таблица областей ложится, а действует только
    после объявления роли. Это говорится, а не выясняется пустой картой.
    Нечитаемая таблица ролей — «не объявлена», как у карты
    (`review_map.role_declared`). Адреса — по таблице путей ПОТРЕБИТЕЛЯ
    (#1630): переназначенную им таблицу карта читает там же.

    ОБЪЯВЛЕНИЯ МАЛО — НУЖЕН ПРОФИЛЬ (находка взгляда на #1696). Карта профилей
    тоже данные: `--update` кладёт её, только если файла нет, и проект,
    подключённый раньше, вписав одну строку в `required`, остался бы без
    профиля. Взгляд узнаёт роль находки по заголовку профиля
    (`findings.roles`), и без него находки роли лягут без роли — а заход
    молчал бы. Поэтому тишина — только при обоих: роль объявлена и профиль есть.
    """
    try:
        areas = policy.project_path("area-paths", consumer)
        table = policy.project_path("review-roles", consumer)
        profiles = policy.project_path("roles", consumer)
    except paths.BadPaths as exc:
        return f"Спячка таблицы областей не проверена: раздел путей не разобран — {exc}"
    if not (consumer / areas).exists():
        return ""
    try:
        roles = json.loads((consumer / table).read_text(encoding="utf-8"))
        declared = review_map.declares_role(review_map.table_shape(roles))
    except OSError, ValueError, review_map.NotRun:
        declared = False
    # НЕЧИТАЕМАЯ КАРТА ПРОФИЛЕЙ — «ПРОФИЛЯ НЕТ», как нечитаемая таблица ролей
    # строкой выше (взгляд на #1696, `534ecc4`): прежде `roles.md` не в UTF-8
    # ронял заход уже после того, как он положил файлы, вместо названной спячки.
    try:
        profiled = review_map.CATALOGUE_ROLE in findings.roles(consumer / profiles)
    except OSError, ValueError:
        profiled = False
    if declared and profiled:
        return ""
    missing = " и ".join(
        said
        for said, gone in (
            (f"в `{table}` эта роль не объявлена", not declared),
            (f"в `{profiles}` у неё нет профиля", not profiled),
        )
        if gone
    )
    return (
        f"`{areas}` спит: карта взгляда отдаёт по ней правила роли "
        f"«{review_map.CATALOGUE_ROLE}», а {missing}. "
        "Таблица начнёт действовать, когда проект впишет роль в `required` или `by_path` и "
        f"даст ей профиль в `{profiles}`. Роль раскатана на семью: {ROLE_HOME}"
    )


def pin_of(root: Path) -> str:
    """Тег ВЫПУСКА, к которому прибивается потребитель, — из истории.

    НЕ `CONTRACT_VERSION`, И РАЗНИЦА СТОИЛА БЫ НЕРАБОЧЕЙ ЗАГОТОВКИ. Там лежит
    версия ПОВЕРХНОСТИ, а выпуски помечены своими тегами, и это РАЗНЫЕ числа:
    прибивка к первой указала бы на тег, которого нет, и вызов
    отказал бы у потребителя, а не у нас
    ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).

    Тег читается ТЕМ ЖЕ разбором, что у механизма версии: второй разбор той же
    формы — это второе её понимание, и расходятся они молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    tag = version.release_tag(root or None)
    if tag is None:
        raise NotRun(
            f"{NO_RELEASE}: прибиваться потребителю не к чему. Заготовка с подвижной"
            " меткой вместо версии меняла бы у него исполняемый код без его ведома (152)"
        )
    return tag


#: Вызов сводного гейта в нашем прогоне — внутренним путём; у потребителя он
#: становится адресом с прибивкой.
SUMMARY_CALL: Final = f"uses: ./{paths.SUMMARY_ACTION.parent.as_posix()}"


def summary_kit(root: Path, repo: str, pin: str) -> str:
    """Тонкий `ci-complete.yml` потребителя — наш прогон с адресом действия вместо `./`.

    Берётся НАШ файл, а не пишется второй рядом (022): события, группа отмены и
    права у потребителя те же, что проверены здесь. Вызов действия в нём ровно
    один — иначе подмена адреса была бы угадыванием (075).
    """
    try:
        source = (root / paths.WORKFLOWS / SUMMARY_FLOW).read_text(encoding="utf-8")
    except OSError as exc:
        raise NotRun(f"{SUMMARY_FLOW} не прочитан: {exc}") from exc
    if source.count(SUMMARY_CALL) != 1:
        raise NotRun(
            f"вызовов «{SUMMARY_CALL}» в {SUMMARY_FLOW}: {source.count(SUMMARY_CALL)}, ждали один"
        )
    outward = f"uses: {repo}/{paths.SUMMARY_ACTION.parent.as_posix()}@{pin}"
    return source.replace(SUMMARY_CALL, outward)


def caller(name: str, repo: str, pin: str) -> str:
    """Джоб вызывающего для одного шага — то, что потребитель кладёт к себе."""
    when = f"    if: {ON_CHANGE_ONLY}\n" if name in ABOUT_A_CHANGE else ""
    return (
        f"  {name}:\n"
        f"    name: {name}\n"
        f"{when}"
        f"    uses: {repo}/.github/workflows/{STEP_PREFIX}{name}.yml@{pin}\n"
        f"    permissions:\n"
        f"      contents: read\n"
        f"      checks: read\n"
        f"      pull-requests: read\n"
        f"      issues: read\n"
    )


# --- обновление (#1386) ------------------------------------------------------


def our_uses(repo: str) -> re.Pattern[str]:
    """Вызов нашего адреса с тегом: `address` — без тега, `tag` — сам тег."""
    return re.compile(rf"(?P<address>{re.escape(repo)}/[^@\s'\"]+)@(?P<tag>[^\s'\"#]+)")


def events(document: dict[Any, Any]) -> dict[str, Any]:
    """События прогона одной формой — словарём, как бы они ни были записаны."""
    raw = policy.events_raw(document)
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    if isinstance(raw, list):
        return {str(one): None for one in raw}
    return {str(raw): None} if raw else {}


def calls_of(document: dict[Any, Any], repo: str) -> list[dict[str, Any]]:
    """Вызовы наших шагов и действий в прогоне — без тега и в порядке, не зависящем от записи."""
    pattern = our_uses(repo)
    found: list[dict[str, Any]] = []
    for job in (document.get("jobs") or {}).values():
        body = job if isinstance(job, dict) else {}
        said = pattern.fullmatch(str(body.get("uses") or ""))
        if said:
            found.append(
                {
                    "uses": said["address"],
                    "secrets": body.get("secrets") or {},
                    "permissions": body.get("permissions") or {},
                }
            )
        for step in body.get("steps") or []:
            if not isinstance(step, dict):
                continue
            said = pattern.fullmatch(str(step.get("uses") or ""))
            if said:
                found.append({"uses": said["address"]})
    return sorted(found, key=lambda one: json.dumps(one, sort_keys=True, default=str))


def callers_in(document: dict[Any, Any], repo: str) -> list[tuple[str, dict[Any, Any]]]:
    """Узлы вызова наших шагов и действий в порядке записи: адрес без тега и сам узел."""
    pattern = our_uses(repo)
    found: list[tuple[str, dict[Any, Any]]] = []
    for job in (document.get("jobs") or {}).values():
        body = job if isinstance(job, dict) else {}
        said = pattern.fullmatch(str(body.get("uses") or ""))
        if said:
            found.append((said["address"], body))
        for step in body.get("steps") or []:
            said = (
                pattern.fullmatch(str(step.get("uses") or "")) if isinstance(step, dict) else None
            )
            if said and isinstance(step, dict):
                found.append((said["address"], step))
    return found


def accepted_inputs(root: Path, address: str, repo: str) -> set[str] | None:
    """Входы, которые наш шаг или действие объявляет, — по его файлу в нашем дереве.

    `None` — файл не прочитан или входы не объявлены списком: тогда судить,
    принимает ли шаг вход потребителя, нечем, и его вход сохраняется (045).
    """
    path = root / address.removeprefix(f"{repo}/")
    if path.is_dir():
        path = path / "action.yml"
    try:
        document = policy.run_of(path)
    except policy.BadPolicy:
        return None
    if path.name == "action.yml":
        inputs = document.get("inputs")
    else:
        events = policy.events_raw(document)
        call = events.get("workflow_call") if isinstance(events, dict) else None
        inputs = call.get("inputs") if isinstance(call, dict) else None
    return {str(one) for one in inputs} if isinstance(inputs, dict) else None


def merged_inputs(
    kit: dict[str, Any] | None, theirs: dict[str, Any] | None, accepted: set[str] | None
) -> tuple[dict[str, Any], list[str]]:
    """Входы новой заготовки, поверх них — значения потребителя; и что снято.

    Вход, добавленный выпуском, остаётся (взгляд на #1438): прежде входы
    потребителя заменяли `with:` целиком, и новый — обязательный тоже —
    терялся. Свой вход потребителя сохраняется, если шаг его объявляет;
    необъявленный снимается и называется: площадка отвергла бы вызов.
    """
    said = dict(kit or {})
    dropped: list[str] = []
    for key, value in (theirs or {}).items():
        if accepted is None or key in said or key in accepted:
            said[key] = value
        else:
            dropped.append(str(key))
    return said, dropped


def keep_inputs(new: str, mine: str, repo: str, where: Path, root: Path) -> str:
    """Новая заготовка с ВХОДАМИ потребителя: `with:` — его данные, обновление их не трогает.

    РЕШЕНИЕ ВЛАДЕЛЬЦА 16.10.2026 ПО #1386: заготовка сама приглашает править
    входы под проект, поэтому входы не судятся и переносятся. Вызовы
    сопоставляются по адресу и ПОРЯДКОВОМУ НОМЕРУ — и в сверке, и в переносе
    (взгляд на #1438: сверка шла с первым набором адреса). Совпало всё —
    текст заготовки как есть, с её пояснениями; нет — пересборка разбором.
    """
    try:
        fresh = policy.run_text(new, str(where))
        theirs = policy.run_text(mine, str(where))
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc
    given: dict[str, list[Any]] = {}
    for address, node in callers_in(theirs, repo):
        given.setdefault(address, []).append(node.get("with"))
    seen: dict[str, int] = {}
    changed = False
    dropped: list[str] = []
    for address, node in callers_in(fresh, repo):
        at = seen.get(address, 0)
        seen[address] = at + 1
        said = given.get(address) or []
        if at >= len(said):
            continue
        inputs, lost = merged_inputs(
            node.get("with"), said[at], accepted_inputs(root, address, repo)
        )
        dropped += lost
        if inputs != (node.get("with") or {}):
            changed = True
            node["with"] = inputs
    if not changed:
        return new
    body = {("on" if key is True else key): value for key, value in fresh.items()}
    head = (
        "# Заготовка `scripts/onboard.py --update`: входы `with:` — ваши поверх входов\n"
        "# выпуска; остальное — заготовка поставщика.\n"
    )
    if dropped:
        head += f"# Сняты входы, которых шаг не объявляет: {', '.join(sorted(dropped))}.\n"
    return head + str(yaml.safe_dump(body, allow_unicode=True, sort_keys=False))


def essence(text: str, repo: str, where: Path) -> dict[str, Any]:
    """Существо вызывающего прогона: что сравнивается, а что — форма записи.

    РЕШЕНИЯ ВЛАДЕЛЬЦА 16.10.2026 ПО #1386. Сравниваются адрес вызова без тега,
    секреты, события и права. Входы `with:` — данные потребителя, их правит он
    сам, и они переносятся (`keep_inputs`), а не судятся. Комментарии, порядок
    и форма записи не в счёт: вызывающие у живого потребителя пишутся рукой, и сравнение
    байт в байт отказывало бы витрине на каждом файле — замер в #1386.
    """
    try:
        document = policy.run_text(text, str(where))
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc
    return {
        "on": events(document),
        "permissions": document.get("permissions") or {},
        "calls": calls_of(document, repo),
    }


def owned(root: Path, repo: str, pin: str) -> dict[Path, str]:
    """Целиком наши файлы заготовки: свои прогоны механизмов и сводный гейт."""
    names = steps(root)
    files = {
        paths.WORKFLOWS / flow.name: own_kit(flow, one, repo, pin)
        for one, flow in sorted(own_callers(root, names).items())
    }
    files[paths.WORKFLOWS / SUMMARY_FLOW] = summary_kit(root, repo, pin)
    return files


def owned_at(root: Path, tag: str, repo: str) -> dict[Path, str]:
    """Наши файлы заготовки, какими их клал выпуск `tag`: с ними сверяется дерево потребителя.

    Дерево выпуска выгружается из истории поставщика, а собирается ТЕМ ЖЕ
    кодом, что и новая заготовка: иначе разница кода выдала бы себя за правку
    потребителя. Файл, которого тот выпуск не собирает (сводного гейта до
    #1385 не было), в ответ не входит: сверить его не с чем, и это решает
    зовущий.
    """
    try:
        archive = subprocess.run(
            ["git", "-C", str(root), "archive", "--format=tar", tag],
            capture_output=True,
            check=False,
            timeout=gitcall.LOCAL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotRun(f"git не запустился: {exc}") from exc
    if archive.returncode:
        said = archive.stderr.decode("utf-8", "replace").strip()
        raise NotRun(f"дерево выпуска {tag} не выгружено: {said or archive.returncode}")
    with tempfile.TemporaryDirectory() as where:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(where, filter="data")
        old = Path(where)
        try:
            names = steps(old)
            files = {
                paths.WORKFLOWS / flow.name: own_kit(flow, one, repo, tag)
                for one, flow in sorted(own_callers(old, names).items())
            }
        except check_shipped.NotRun as exc:
            raise NotRun(f"заготовка выпуска {tag} не собрана: {exc}") from exc
        # Не собран — значит тот выпуск его не клал; что это значит для файла
        # потребителя, решает зовущий: «сверить не с чем» (045).
        with contextlib.suppress(NotRun):
            files[paths.WORKFLOWS / SUMMARY_FLOW] = summary_kit(old, repo, tag)
    return files


def gap(before: str, after: str, path: Path, repo: str) -> str:
    """Разница по существу между заготовкой и файлом потребителя — строками для печати."""
    said = [
        yaml.safe_dump(essence(text, repo, path), allow_unicode=True, sort_keys=True)
        for text in (before, after)
    ]
    return "".join(
        difflib.unified_diff(
            said[0].splitlines(keepends=True),
            said[1].splitlines(keepends=True),
            fromfile=f"заготовка/{path}",
            tofile=f"ваш/{path}",
        )
    )


@dataclass
class Update:
    """Что обновление сделает с деревом потребителя — решено целиком до первой записи."""

    write: dict[Path, str] = field(default_factory=dict)
    #: Наш файл правлен по существу: путь → разница с заготовкой его тега.
    edited: dict[Path, str] = field(default_factory=dict)
    #: Своя копия под нашим именем, не зовущая наш шаг: не трогается, а называется.
    copies: list[Path] = field(default_factory=list)
    #: Уже на новой прибивке и по существу совпадает с заготовкой.
    current: list[Path] = field(default_factory=list)
    #: Что заход называет, но не пишет: новые и снятые шаги `ci.yml`, ответы.
    notes: list[str] = field(default_factory=list)


def plan_owned(update: Update, consumer: Path, new: dict[Path, str], root: Path, repo: str) -> None:
    """Целиком наши файлы: переписать, если совпадают по существу с заготовкой своего тега."""
    pin_old: dict[str, dict[Path, str]] = {}
    for path, text in sorted(new.items()):
        # Двойник `.yaml` — тот же файл под своим именем: правится он, а не
        # кладётся второй рядом (`standing`, находка `1f2ca12`).
        where = standing(consumer, path)
        target = consumer / where
        if not target.is_file():
            update.write[path] = text
            continue
        mine = target.read_text(encoding="utf-8")
        tags = sorted({said["tag"] for said in our_uses(repo).finditer(mine)})
        if not tags:
            update.copies.append(where)
            continue
        if len(tags) > 1:
            update.edited[where] = f"вызовы прибиты к разным тегам: {', '.join(tags)}\n"
            continue
        if essence(mine, repo, path) == essence(text, repo, path):
            if tags[0] == new_tag(text, repo):
                update.current.append(where)
            else:
                update.write[where] = keep_inputs(text, mine, repo, path, root)
            continue
        if tags[0] not in pin_old:
            pin_old[tags[0]] = owned_at(root, tags[0], repo)
        before = pin_old[tags[0]].get(path)
        if before is None:
            update.edited[where] = f"выпуск {tags[0]} такого файла не клал — сверить не с чем\n"
        elif essence(mine, repo, path) != essence(before, repo, path):
            update.edited[where] = gap(before, mine, path, repo)
        else:
            update.write[where] = keep_inputs(text, mine, repo, path, root)


def new_tag(text: str, repo: str) -> str:
    """Тег, к которому прибита заготовка: в ней он один по построению."""
    found = our_uses(repo).search(text)
    return found["tag"] if found else ""


def plan_ci(update: Update, consumer: Path, pipeline: list[str], repo: str, pin: str) -> None:
    """Смешанный `ci.yml`: тег поднимается в наших строках, новые шаги называются.

    В `ci.yml` у потребителя свои джобы, и вписывать в него заход не берётся
    (решение владельца по #1386): новый шаг печатается готовым джобом, снятый —
    называется. Переписываются только теги в строках вызова наших шагов.
    """
    where = standing(consumer, paths.WORKFLOWS / PIPELINE_FLOW)
    target = consumer / where
    # `ci.yml` — ФАЙЛ ПРОЕКТА В ОБОИХ СЛУЧАЯХ (поздний взгляд на #1487,
    # `49976c1`): положенный тонким завтра получит свои джобы проекта, и строка
    # поставщика в нём осталась бы в чужом файле. Решает `of_the_project`, а не
    # пометка здесь: признак один на все двери (`215204f`).
    if not target.is_file():
        update.write[where] = thin_ci(pipeline, repo, pin)
        return
    text = target.read_text(encoding="utf-8")
    called = {
        Path(said["address"]).stem[len(STEP_PREFIX) :]
        for said in our_uses(repo).finditer(text)
        if Path(said["address"]).name.startswith(STEP_PREFIX)
    }

    def lift(said: re.Match[str]) -> str:
        """Тег поднимается только у шага, который выпуск отдаёт (взгляд на #1438)."""
        name = Path(said["address"]).name
        step = Path(name).stem[len(STEP_PREFIX) :]
        gone = name.startswith(STEP_PREFIX) and step not in pipeline and step not in OPT_IN
        return said[0] if gone else f"{said['address']}@{pin}"

    lifted = our_uses(repo).sub(lift, text)
    if lifted != text:
        update.write[where] = lifted
    for one in sorted(set(pipeline) - called):
        update.notes.append(
            f"новый шаг `{one}` — джоб для вашего `{where.name}`:\n" + caller(one, repo, pin)
        )
    for one in sorted(called - set(pipeline) - set(OPT_IN)):
        update.notes.append(
            f"шаг `{one}` в выпуске {pin} не отдаётся — его вызов оставлен на прежнем теге; "
            "снимите его"
        )
    for one in sorted(called & set(OPT_IN)):
        update.notes.append(
            f"шаг `{one}` заготовка больше не кладёт: {OPT_IN[one]}. Тег поднят; "
            "не отдаёте своих общих шагов — снимите вызов"
        )


def plan_answer(update: Update, consumer: Path, wanted: list[str], contract: str, pin: str) -> None:
    """Своё проекта не трогается; названо, по каким проверкам ответа нет и покрывает ли окно выпуск.

    ОКНО СВЕРЯЕТСЯ ДО ЗАПИСИ, А НЕ ПОСЛЕ ТОЛЧКА (находки `d9b9a4f`, `4962cb3`).
    Подъём прибивки на следующий минор контракта выводит её за окно `contract:`
    — так устроено (`contract_span`): краснение зовёт перечитать ответы. Но
    прежде о нём говорил только шаг `pipeline` после толчка, а обновление
    печатало «обновлено» молча. Окно — ответ проекта, и заход его не двигает;
    он называет расхождение тем же разбором, что у механизма (`policy.compatible`).
    """
    target = consumer / paths.PIPELINE
    if not target.is_file():
        update.notes.append(f"`{paths.PIPELINE}` нет — заготовку ответа печатает заход без ключей")
        return
    try:
        said = policy.answer_text(target.read_text(encoding="utf-8"), str(paths.PIPELINE))
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc
    known = {str(name) for part in ("checks", policy.BEYOND) for name in (said.get(part) or {})}
    missing = [one for one in wanted if one not in known]
    if missing:
        update.notes.append(
            f"в `{paths.PIPELINE}` нет ответа по: {', '.join(missing)} — класс решаете вы"
        )
    declared = str(said.get("contract") or "").strip()
    if not declared:
        update.notes.append(
            f"в `{paths.PIPELINE}` нет окна `contract:` — механизмы ответа не прочтут; "
            f"окно выпуска {pin}: {contract_span(contract)}"
        )
        return
    try:
        covered = policy.compatible(declared, contract)
    except policy.BadPolicy as exc:
        raise NotRun(f"{paths.PIPELINE}: {exc}") from exc
    if not covered:
        update.notes.append(
            f"окно `contract:` в `{paths.PIPELINE}` — «{declared}» — не покрывает контракт "
            f"{contract} выпуска {pin}: после толчка шаг `pipeline` откажет. Перечитайте "
            "ответы под новый контракт (157) и тогда поднимите окно — заход его не двигает"
        )


def check_name(name: str) -> str:
    """Имя записи проверки, которое выдаст площадка, — составное."""
    return f"{name}{policy.COMPOSED}{name}"


def own_records(flow: Path, step: str = "") -> tuple[list[str], bool]:
    """Имена записей своего прогона механизма и идёт ли он на изменении.

    ИМЯ БЕРЁТСЯ У РАЗБОРА ПРОГОНА, А НЕ У ИМЕНИ ФАЙЛА ШАГА (#993). Джоб обхода
    застрявших зовётся `stuck-prs`, а шаг — `step-stuck.yml`: имя, собранное
    из файла, назвало бы запись, которой площадка не выдаст, и сводный гейт
    потребителя ждал бы её вечно (045). Разбор тот же, что у ответа по
    классам (`policy.check_names`), — второго понимания составного имени нет
    (090).

    РАЗДЕЛ ОТВЕТА ВЫВОДИТСЯ ИЗ СОБЫТИЙ, А НЕ ИЗ РОДА. Очередь — управляющий
    механизм, но идёт и на изменении: её запись живёт на голове, и ответ по ней
    обязан стоять в `checks`, а не в `beyond_the_change` — там его разбор
    потребителя отверг бы как ответ о проверке, которой вне изменения нет.
    """
    try:
        said = policy.run_of(flow)
        # Названный шаг сужает ответ до джобов, зовущих его: свои джобы
        # вызывающего в заготовку не едут (`calling_part`), и ответ о них
        # потребителю был бы ответом о проверке, которой у него нет.
        names = [
            one
            for job_id, body in (said.get("jobs") or {}).items()
            if not step or step_called(str((body or {}).get("uses") or "")) == step
            for one in policy.check_names(str(job_id), body or {}, flow.parent)
        ]
    except policy.BadPolicy as exc:
        raise NotRun(f"{flow.name} не прочитан: {exc}") from exc
    return names, policy.ON_CHANGE in policy.triggers_of(said)


def contract_at(root: Path, pin: str) -> str:
    """Версия контракта, которую несёт выпуск `pin`, — из его дерева, а не из рабочего.

    Рабочее дерево поставщика бывает впереди выпуска: окно заготовки, взятое
    оттуда, обещало бы потребителю поверхность, которой у его прибивки нет.
    """
    said = gitcall.output(
        ["show", f"{pin}:{paths.VERSION.as_posix()}"], NotRun, cwd=str(root)
    ).strip()
    try:
        version.digits(said)
    except version.NotRun as exc:
        raise NotRun(f"{pin}:{paths.VERSION}: {exc}") from exc
    return said


def contract_span(contract: str) -> str:
    """Окно совместимости заготовки: минор выпуска, и только он (073, 157).

    Минор контракта растёт, когда у поверхности появляется джоб, по которому
    потребитель обязан ответить классом (`docs/dev/release.md`). Поэтому
    следующий минор лежит за окном: подъём прибивки краснеет и зовёт перечитать
    ответы, а не принимается молча.
    """
    # Разряды — одним разбором `version.digits`, а не своим (214).
    try:
        major, minor, _ = version.digits(contract)
    except version.NotRun as exc:
        raise NotRun(f"версия контракта: {exc}") from exc
    return f">={major}.{minor},<{major}.{minor + 1}"


def kept_on_the_kit(keep: list[Path], known: set[Path]) -> tuple[list[Path], list[str]]:
    """Ключи `--keep`, сведённые к путям заготовки, и названные пути, которых она не кладёт.

    Двойник YAML прогона сводится к тому пути, который заготовка кладёт, — в
    любую сторону (взгляд на #1508): свой прогон поставщика бывает и `.yaml`
    (`own_callers`), и приведение всегда к `.yml` отказало бы верному ключу.
    """
    kept: list[Path] = []
    unknown: list[str] = []
    for one in keep:
        twin = one.with_suffix(YAML_TWINS.get(one.suffix, one.suffix))
        if one in known:
            kept.append(one)
        elif one.parent == paths.WORKFLOWS and twin in known:
            kept.append(twin)
        else:
            unknown.append(str(one))
    return kept, sorted(unknown)


def kept_records(
    keep: list[Path], own: dict[str, Path], records: dict[str, tuple[list[str], bool]]
) -> dict[str, str]:
    """Записи проверок прогонов, которые проект оставил своим: имя записи → причина `off`."""
    said: dict[str, str] = {}
    for one, flow in sorted(own.items()):
        path = paths.WORKFLOWS / flow.name
        if path in keep:
            for name in records[one][0]:
                said[name] = f"`{path}` проект оставил своим (onboard.py --keep)"
    return said


def kept_row(name: str, why: str) -> str:
    """Строка ответа `off` с причиной — одна форма для заготовки и для вывода захода."""
    return f'  "{name}": {{class: {policy.OFF}, why: "{why}"}}'


def kept_fragment(kept: dict[str, str], *, on_change: list[str], beyond: list[str]) -> str:
    """Строки `off` оставленных прогонов по разделам ответа — для своего `.pipeline.yml`.

    Раздел тот же, что у заготовки (`answer`): запись на изменении — `checks`,
    вне его — `beyond`. Пустой раздел не печатается.
    """
    parts = []
    for section, names in (("checks", on_change), (policy.BEYOND, beyond)):
        if rows := [kept_row(one, kept[one]) for one in names if one in kept]:
            parts.append(f"{section}:\n" + "\n".join(rows))
    return "\n".join(parts)


def keep_report(keep: list[Path], mechanisms: set[Path], fragment: str) -> list[str]:
    """Что заход сделал с каждым путём `--keep` — строкой на род пути.

    ВЫВОД НАЗЫВАЕТ ТО, ЧТО ПОЛОЖЕНО (взгляды на #1508 и #1539, правило 210).
    Три рода — три строки, и каждый путь назван ровно в одной: прогон
    механизма (его проверки — `off`), ответ (своё сводится с печатью захода,
    а записи оставленных прогонов — строками `off` из `fragment`) и прочие
    пути (сводятся, их проверки в ответе не трогаются). Прежде ответ попадал
    в строку прочих путей, и та спорила с напечатанным `off`.
    """
    lines: list[str] = []
    answer_kept = paths.PIPELINE in keep
    if own := sorted(str(one) for one in keep if one in mechanisms):
        where = "строки — ниже, у ответа" if answer_kept else f"в `{paths.PIPELINE}`"
        lines.append(
            "оставлены своими прогоны механизмов: "
            + ", ".join(own)
            + f" — не тронуты; их проверки — off с причиной, {where}"
        )
    if answer_kept:
        said = (
            f"`{paths.PIPELINE}` не положен (--keep): свой сведите с ответом из печати "
            "захода без ключей"
        )
        if fragment:
            said += (
                ". У записей оставленных прогонов там очередь разбора — вместо неё "
                "влейте строки off ниже в одноимённые разделы своего ответа, заголовок "
                "раздела второй раз не вставляйте: повтор ключа YAML молча теряет раздел\n"
                + fragment
            )
        lines.append(said)
    if other := sorted(str(one) for one in keep if one not in mechanisms and one != paths.PIPELINE):
        lines.append(
            "не положено по --keep: "
            + ", ".join(other)
            + " — своё сведите с заготовкой из печати захода без ключей; "
            "проверки ответа по этим путям не тронуты"
        )
    return lines


def answer(
    names: list[str],
    beyond: list[str] | None = None,
    *,
    on_change: list[str] | None = None,
    span: str,
    kept: dict[str, str] | None = None,
) -> str:
    """Заготовка ответа потребителя: схема, окно контракта и по строке на проверку.

    `unreviewed` здесь не заглушка, а объявленная очередь разбора: молча
    обязательной проверка не становится, и молча совещательной тоже.
    `names` — шаги конвейера, их имя составное из имени шага. `beyond` и
    `on_change` — уже готовые имена записей своих прогонов механизмов
    (`own_records`): вне изменения и на нём. `span` — окно контракта
    (`contract_span`): без него и без схемы ответ не читает ни один механизм
    (`pipeline_checks.load`), и потребитель краснел бы с первого прогона.
    `kept` — записи прогонов, которые проект оставил своим (`kept_records`):
    они ложатся классом `off` с причиной, а не очередью разбора.
    """

    def row(name: str) -> str:
        why = (kept or {}).get(name)
        return kept_row(name, why) if why else f'  "{name}": {policy.UNREVIEWED}'

    rows = [row(check_name(one)) for one in names]
    rows += [row(one) for one in on_change or []]
    said = f'schema: {policy.SCHEMA}\ncontract: "{span}"\n\n'
    said += "checks:\n" + "\n".join(rows) + "\n"
    if beyond:
        more = "\n".join(row(one) for one in beyond)
        said += f"{policy.BEYOND}:\n{more}\n"
    return said + FEEDBACK_SAMPLE


#: ОБРАЗЕЦ РАЗДЕЛА `feedback:` — КОММЕНТАРИЕМ (п. 9 #1665). Канал к поставщику
#: раздаётся вместе с ответом, но пустая запись была бы записью: раздел ложится
#: закомментированным, и проект раскрывает его, когда есть что сказать.
#: Заполнять — навыком `tell-the-supplier`, форму судит шаг `pipeline`.
FEEDBACK_SAMPLE: Final = """
# Что механизм поставщика сделал у вас не так — записью, а не прозой в трекере
# (навык `tell-the-supplier`, форма — договор поставщика, раздел `feedback:`).
# feedback:
#   version: 1
#   records:
#     - slug: <устойчивое-имя>
#       mechanism: <step-…, scripts/….py или .claude/…>
#       version: <тег выпуска поставщика, vX.Y.Z>
#       kind: <false-refusal | false-pass | not-run | partial | rework | bypass>
#       measured: <что видно и сколько раз>
#       trace: <владелец/репозиторий#N — ваша задача>
#       supplier: <владелец/репозиторий — только если механизм не этого поставщика>
"""


def update(
    root: Path,
    consumer: Path,
    repo: str,
    pin: str,
    pipeline: list[str],
    records: list[str],
    data: dict[Path, str],
    contract: str,
) -> int:
    """Обновление нашего в дереве потребителя до прибивки `pin` (#1386).

    РЕШЕНИЕ ВЛАДЕЛЬЦА 16.10.2026. Наш файл, совпадающий по существу с
    заготовкой своего тега, переписывается новой заготовкой. Разошедшийся —
    отказ на ВСЁ обновление: не пишется ни один файл, а разница печатается
    предложением поставщику. Своя копия под нашим именем, не зовущая наш шаг,
    не трогается и называется. В `ci.yml` поднимается только тег наших строк,
    новые шаги печатаются. `.pipeline.yml` и свод — своё проекта, их заход не
    трогает. Заготовки данных (`data`) кладутся, только если файла нет: занятый
    путь — своё проекта и отказа не даёт. `contract` — версия контракта выпуска
    `pin`: обновление сверяет с ней окно ответа проекта (`plan_answer`).
    """
    trunk = trunk_of(consumer)
    if trunk and trunk != paths.TRUNK:
        print(
            f"обновление не сделано: общая ветка дерева — «{trunk}», а механизмы "
            f"работают с «{paths.TRUNK}» (#1220)",
            file=sys.stderr,
        )
        return EXIT_FOREIGN_TRUNK
    plan = Update()
    try:
        plan_owned(plan, consumer, owned(root, repo, pin), root, repo)
        kitted = (*TREE_KITTED, *SKILLS_KITTED)
        plan_tree(plan, consumer, {path: data[path] for path in kitted if path in data}, root, repo)
        plan_floor(plan, consumer, data[paths.FLOOR])
        plan_ci(plan, consumer, pipeline, repo, pin)
        wanted = [check_name(one) for one in pipeline] + records
        plan_answer(plan, consumer, wanted, contract, pin)
        signed_all(plan.write | data, repo)
    except NotRun as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if plan.edited:
        print(
            f"обновление до {pin} не сделано: наш файл правлен по существу — "
            + ", ".join(str(one) for one in sorted(plan.edited))
            + ". Не записан ни один файл: половина обновления хуже никакой.",
            file=sys.stderr,
        )
        for path, said in sorted(plan.edited.items()):
            print(f"\n# {path}\n{said}", file=sys.stderr)
        print(
            "Если правка нужна вашему проекту — она нужна и заготовке: принесите эту "
            f"разницу задачей поставщику по шаблону `{paths.GAP_TEMPLATE}` ({repo}). Иначе "
            "верните файл к заготовке и позовите обновление заново.",
            file=sys.stderr,
        )
        return EXIT_HAND_EDITED
    lay(consumer, plan.write, repo)
    laid = lay_free(consumer, data, repo)
    if plan.write:
        print(f"обновлено до {pin}: " + ", ".join(str(one) for one in sorted(plan.write)))
    else:
        print(f"обновлять нечего: наше уже на {pin}")
    if plan.current:
        print("уже на новой прибивке: " + ", ".join(str(one) for one in sorted(plan.current)))
    for path in sorted(plan.copies):
        print(
            f"`{path}` — своя копия, наш шаг она не зовёт; не тронута. Заменить её "
            "вызовом можно заготовкой: заход без ключей печатает её целиком."
        )
    for note in plan.notes:
        print(note)
    if laid:
        print("положены заготовки данных: " + ", ".join(str(one) for one in laid))
    if unwired := settings_note(consumer, laid, repo, pin):
        print(unwired)
    if unanswered := bindings_note(consumer):
        print(unanswered)
    if dormant := dormant_areas_note(consumer):
        print(dormant)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает заготовку вызова и заготовку ответа."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень ЭТОГО дерева")
    parser.add_argument(
        "--repo",
        default="ArtVsMark/Engineering-Pipeline-Mechanisms",
        help="откуда потребитель зовёт шаги",
    )
    parser.add_argument(
        "--write",
        type=Path,
        metavar="КОРЕНЬ",
        help="положить заготовку в дерево потребителя, а не печатать; занятое не трогается",
    )
    parser.add_argument(
        "--update",
        type=Path,
        metavar="КОРЕНЬ",
        help="обновить наше в дереве потребителя до выпуска; своё и правленое не трогается",
    )
    parser.add_argument(
        "--keep",
        type=Path,
        action="append",
        default=[],
        metavar="ПУТЬ",
        help="с --write: путь от корня потребителя, который проект оставляет своим (#1503)",
    )
    args = parser.parse_args(argv)
    if args.write and args.update:
        parser.error("--write и --update — разные двери: первое подключение и обновление")
    if args.keep and not args.write:
        parser.error("--keep — ключ первого подключения: он бывает только с --write")

    try:
        names = steps(args.root)
        own = own_callers(args.root, names)
        records = {one: own_records(flow, one) for one, flow in own.items()}
        pin = pin_of(args.root)
        # Версия контракта выпуска нужна ОБЕИМ дверям (находка `d6334b4`): кладка
        # пишет по ней окно ответа, обновление сверяет с ней окно потребителя.
        contract = contract_at(args.root, pin)
        span = contract_span(contract)
        summary = summary_kit(args.root, args.repo, pin)
        rulebook = rulebook_kit(args.root)
        kit = data_kit(args.root, args.repo)
        # Перечень данных выводится ДО печати и до записи: битый инвентарь
        # отказывает выходом захода, а не трейсбеком после положенного (#996).
        data = consumer_data(args.root, names, {paths.PIPELINE, *rulebook, *kit})
    except (NotRun, check_shipped.NotRun) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not names:
        print(
            "отдавать нечего: ни один шаг не помечен как отдаваемый наружу — "
            "подключать не к чему, и это состояние, а не заготовка (075)",
            file=sys.stderr,
        )
        return EXIT_NOTHING

    # СВЕРКА ИДЁТ ДО ПЕЧАТИ, А НЕ ПОСЛЕ. Напечатанную заготовку забирают
    # целиком; предупреждение под ней читают не все, а вызов по адресу,
    # которого по названному тегу нет, отказывает у потребителя.
    try:
        missing = check_shipped.unreleased(pin, args.root)
    except (NotRun, check_shipped.NotRun) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if missing:
        print(
            f"прибивка «{pin}» не несёт помеченного наружу: {len(missing)} из "
            f"{len(check_shipped.shipped_here(args.root))} — {', '.join(missing)}.\n"
            "Заготовка с такой прибивкой отказала бы у потребителя, а не у нас (045).\n"
            f"Выход: нарезать выпуск, содержащий эти файлы, и позвать заход заново (158).",
            file=sys.stderr,
        )
        return EXIT_UNREACHABLE

    pipeline = [one for one in names if one not in own and one not in OPT_IN]
    beyond = [name for one in sorted(own) if not records[one][1] for name in records[one][0]]
    on_change = [name for one in sorted(own) if records[one][1] for name in records[one][0]]
    if args.update:
        records_all = beyond + on_change
        return update(args.root, args.update, args.repo, pin, pipeline, records_all, kit, contract)
    if args.write:
        # КЛАДЁТСЯ ТОЛЬКО ПО ЯВНОМУ КЛЮЧУ И ТОЛЬКО В СВОБОДНОЕ (#992). Чужое
        # дерево заход не правит: занятый путь называется, и не пишется ни
        # один файл — половина заготовки хуже никакой.
        # ЧТО ВПРАВЕ НАЗВАТЬ КЛЮЧ — ПУТИ ЗАГОТОВКИ, И ВСЁ (взгляд на #1508). Путь
        # прогона механизма проект заменяет своим, и проверки его прогона идут
        # `off`; прочие пути — `ci.yml`, сводный гейт, ответ, свод — проект
        # сводит со своим из печати захода, и их проверки не трогаются.
        mechanisms = {paths.WORKFLOWS / flow.name for flow in own.values()}
        known = {
            paths.WORKFLOWS / PIPELINE_FLOW,
            paths.WORKFLOWS / SUMMARY_FLOW,
            paths.PIPELINE,
            *mechanisms,
            *rulebook,
            *kit,
        }
        keep, unknown = kept_on_the_kit(args.keep, known)
        if unknown:
            print(
                "заготовка не положена: --keep называет путь, которого заготовка не кладёт — "
                + ", ".join(unknown),
                file=sys.stderr,
            )
            return EXIT_BROKEN
        kept_checks = kept_records(keep, own, records)
        try:
            files = {
                paths.WORKFLOWS / PIPELINE_FLOW: thin_ci(pipeline, args.repo, pin),
                paths.WORKFLOWS / SUMMARY_FLOW: summary,
                paths.PIPELINE: answer(
                    pipeline, beyond, on_change=on_change, span=span, kept=kept_checks
                ),
                **{
                    paths.WORKFLOWS / flow.name: own_kit(flow, one, args.repo, pin)
                    for one, flow in sorted(own.items())
                },
            }
            signed_all(files | rulebook | kit, args.repo)
        except NotRun as exc:
            print(f"заход не отработал: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        files = {path: text for path, text in files.items() if path not in keep}
        rulebook = {path: text for path, text in rulebook.items() if path not in keep}
        kit = {path: text for path, text in kit.items() if path not in keep}
        # ОБЩАЯ ВЕТКА СВЕРЯЕТСЯ ДО ЗАПИСИ (#1220): заготовка, положенная в
        # дерево с другой общей веткой, сравнивала бы гейты не с той базой.
        # Клон её не знает — это названо, а не принято за совпадение (045).
        trunk = trunk_of(args.write)
        if trunk and trunk != paths.TRUNK:
            print(
                f"заготовка не положена: общая ветка дерева — «{trunk}», а механизмы "
                f"работают с «{paths.TRUNK}» (`paths.TRUNK`). Выход: переименовать общую "
                "ветку потребителя или не подключать до решения в #1220. Сверялся "
                "локальный кэш `origin/HEAD`: если ветку на площадке уже "
                "переименовали, обновите его — `git remote set-head origin --auto`",
                file=sys.stderr,
            )
            return EXIT_FOREIGN_TRUNK
        if not trunk:
            print(
                "общая ветка дерева не проверена: дерево не корень своего клона или "
                "у клона нет `origin/HEAD` (локальный кэш — `git remote set-head origin "
                f"--auto`). Механизмы работают с «{paths.TRUNK}» — убедитесь, что она "
                "общая и у вас."
            )
        taken = occupied(args.write, files)
        if taken:
            print(
                "заготовка не положена: в дереве уже есть "
                + ", ".join(str(standing(args.write, one)) for one in taken)
                + ". Заход чужое не перезаписывает — уберите файл или сверьте его с "
                "выводом захода без --write",
                file=sys.stderr,
            )
            return EXIT_OCCUPIED
        kept = occupied(args.write, rulebook)
        free = {path: text for path, text in rulebook.items() if path not in kept}
        lay(args.write, files | free, args.repo)
        print(f"положено в {args.write}: " + ", ".join(str(one) for one in sorted(files | free)))
        for line in keep_report(
            keep, mechanisms, kept_fragment(kept_checks, on_change=on_change, beyond=beyond)
        ):
            print(line)
        # ЗАГОТОВКИ ДАННЫХ — В СВОБОДНОЕ, И ЗАНЯТОЕ ОТКАЗА НЕ ДАЁТ (#1386):
        # данные взгляда — своё проекта, как свод, а не половина вызова.
        laid = lay_free(args.write, kit, args.repo)
        if laid:
            print("положены заготовки данных: " + ", ".join(str(one) for one in laid))
        if ignore_state(args.write):
            print(f"в .gitignore дописано `{STATE_IGNORE}`: там состояние хуков окна")
        if unwired := settings_note(args.write, laid, args.repo, pin):
            print(unwired)
        if unanswered := bindings_note(args.write):
            print(unanswered)
        if unfilled := filling_note(args.write, [*files, *free, *laid]):
            print(unfilled)
        if dormant := dormant_areas_note(args.write):
            print(dormant)
        if kept:
            print(
                "свод уже есть и не тронут: " + ", ".join(str(one) for one in kept) + ". "
                f"Сверьте его общие разделы с заготовкой `{paths.KIT}/` поставщика."
            )
        print("Класс каждой проверки в .pipeline.yml — СВОЙ выбор; в защиту ветки — одно имя.")
        print(
            "Значок проекта в README — строкой ниже; README заход не трогает, а значок "
            f"появится после первого прогона общего шага фактов; {PRIVATE_NOTE}:\n"
            + badge_line(repo_of(args.write) or REPO_PLACEHOLDER)
        )
        print(
            f"Сводный гейт положен тонким `{paths.WORKFLOWS}/{SUMMARY_FLOW}`: его имя "
            "`ci-complete` и ставится в защиту ветки."
        )
        if data is None:
            print(f"Перечень данных общих шагов не выведен: нет `{paths.PORTABLE}`.")
        elif data:
            print(data_note(data))
        else:
            print(
                "Инвентарь переноса не называет данных, которые общие шаги читают из вашего дерева."
            )
        print(family_steps_note())
        return EXIT_OK

    # ПЕЧАТЬ — ВТОРОЙ ПУТЬ ЗАГОТОВКИ К ПОТРЕБИТЕЛЮ (взгляд на #1487): целый файл
    # отсюда копируют в чужое дерево так же, как его положил бы `lay`, и
    # подписывается он тем же `signed_all` — до первой строки вывода, чтобы отказ
    # подписи был исходом «не отработал», а не половиной напечатанного. Джобы
    # вызова — не файл, а строки в СВОЙ `ci.yml` потребителя: их не подписывают,
    # как и сам `ci.yml` — файл проекта (`of_the_project`).
    try:
        whole = signed_all(
            {
                **{
                    paths.WORKFLOWS / flow.name: own_kit(flow, one, args.repo, pin)
                    for one, flow in sorted(own.items())
                },
                paths.PIPELINE: answer(pipeline, beyond, on_change=on_change, span=span),
                paths.WORKFLOWS / SUMMARY_FLOW: summary,
                **rulebook,
            },
            args.repo,
        )
    except NotRun as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print(f"# шагов к подключению: {len(names)} · прибивка: {pin}\n")
    print(f"# 1. В свой `{paths.WORKFLOWS}/{PIPELINE_FLOW}` — джобы вызова:\n")
    print("jobs:")
    print("\n".join(caller(one, args.repo, pin) for one in pipeline))
    for one in sorted(set(OPT_IN) & set(names)):
        # Шаг по выбору: заготовка его не кладёт, но назвать его обязана —
        # иначе проект, который сам отдаёт общие шаги, о нём не узнает (#1652).
        print(f"\n# Шаг `{one}` — по выбору, не кладётся: {OPT_IN[one]}.")
        print("# Отдаёте свои общие шаги — добавьте вызов:\n#")
        print("\n".join(f"# {line}" for line in caller(one, args.repo, pin).splitlines()))
    for _, flow in sorted(own.items()):
        print(f"# 1. Свой `{paths.WORKFLOWS}/{flow.name}` — управляющий механизм своим прогоном:\n")
        print(whole[paths.WORKFLOWS / flow.name])
    print(f"# 2. В свой `{paths.PIPELINE}` — ответ по каждой проверке.")
    print("#    Класс — СВОЙ выбор: `required`, `advisory` или `off` с причиной.")
    print(f"#    Здесь все выходят «{policy.UNREVIEWED}»: это очередь разбора, а не умолчание.\n")
    print(whole[paths.PIPELINE])
    print(f"# 3. В защиту ветки «{paths.TRUNK}» — ОДНО имя: имя своего сводного гейта.")
    print(f"#    Общая ветка обязана зваться «{paths.TRUNK}»: механизмы её имя не угадывают.")
    print(
        f"#    Сводный гейт — свой `{paths.WORKFLOWS}/{SUMMARY_FLOW}`, его джоб зовёт действие:\n"
    )
    print(whole[paths.WORKFLOWS / SUMMARY_FLOW])
    print("#    Перечислять здесь шаги нельзя: список ломается добавлением версии")
    print("#    в матрицу, и защита начинает ждать имя, которого никто не выдаёт (168).")
    kit_names = ", ".join(f"`{path}`" for path in sorted(rulebook))
    print(f"\n# 4. Свой свод окна — {kit_names}: общая часть сверена с нашим сводом,")
    print("#    заглушки «Наполнение проекта» пишет владелец.")
    for path in sorted(rulebook):
        print(f"\n# --- `{path}` ---\n")
        print(whole[path], end="")
    print("\n# 5. Данные, которые общие шаги читают из ВАШЕГО дерева, — заготовка их не кладёт:")
    if data is None:
        print(f"#    перечень не выведен: нет `{paths.PORTABLE}`")
    for one in data or []:
        print(f"#    {one}")
    if data == []:
        print("#    (инвентарь переноса не называет ни одного)")
    print("#    Заготовки данных кладут ключи --write и --update,")
    print("#    только в свободные пути: " + ", ".join(f"`{one}`" for one in sorted(kit)))
    for path, why in sorted(KIT_REFUSED.items()):
        print(f"#    `{path}` заготовкой не кладётся: {why}.")
    print("\n# 6. В свой README — значок проекта; README заход не трогает (#1282).")
    print("#    Значок рисует общий шаг фактов на ветке `badges` после первого прогона;")
    print(f"#    {PRIVATE_NOTE}.\n")
    print(badge_line(REPO_PLACEHOLDER))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
