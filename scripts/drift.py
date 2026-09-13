#!/usr/bin/env python3
"""Дрейф: мир сдвинулся, а дерево не менялось.

ЧЕГО НЕ ВИДИТ НИ ОДИН ГЕЙТ. Проверка на изменении смотрит дерево и диф, и
этого хватает, пока красное приходит от НАШЕЙ правки. Но часть входов лежит
снаружи: каталог правил движется, его выгрузка меняет схему, сводка семьи
стареет, действие выпускает новую версию. Такое красное не приходит никогда —
не потому, что его нет, а потому, что никто не спрашивает.

ПОЧЕМУ НЕ «ГОНЯТЬ ВСЕ ГЕЙТЫ ПО РАСПИСАНИЮ». Гейт, читающий только дерево,
детерминирован: между изменениями он даёт тот же ответ, и заход по расписанию
— холостая работа. Замер соседа, из-за которого очередь двигает только голову:
21 холостой прогон против 12 полезных на шести изменениях. Здесь спрашивается
ровно то, чей вход СНАРУЖИ, и каждая проверка называет, откуда её вход.

ПОЧЕМУ СОВЕЩАТЕЛЬНЫЙ, А НЕ ОБЯЗАТЕЛЬНЫЙ. Дрейф — это источник работы, а не
здоровье общей ветки: каталог, выпустивший новое правило, ничего у нас не
сломал. Держать слияние за движение соседа значило бы заморозить работу по
чужому расписанию
([084](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/084-best-effort-channels-never-block-the-main-path.md)).
Критичное станет обязательным поимённо и внутри сводного гейта, а не новым
именем в защите ветки: имена в защите — договор с потребителем, и каждое
лишнее однажды даёт вечное ожидание.

У НАХОДКИ ЕСТЬ АДРЕСАТ, ПЕРЕЖИВАЮЩИЙ ЗАХОД
([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)).
Красное по расписанию без адресата — это шум, который учат пролистывать. Записи
идут в живую задачу тем же механизмом, что и находки внешнего взгляда: свой
маркер, одно тело, снятие строкой в изменении.

Исходы (правило 039): ``0`` дрейфа нет · ``2`` шаг не отработал · ``3`` дрейф
записан.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import findings
import ghrest
import kinds
import paths
import pipeline_checks
import report

MARKER: Final = findings.marker("drift")
TITLE: Final = "Дрейф: внешнее состояние сдвинулось"

EXIT_NOTHING: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RECORDED: Final = 3

#: Выгрузка каталога и сводка потребителей. Оба — СНИМКИ: каталог собирает их
#: своим прогоном, и читаются они по сети, а не из дерева. В этом весь предмет
#: механизма: дерево не менялось, а снимок — да.
EXPORT_URL: Final = (
    "https://raw.githubusercontent.com/ArtVsMark/Engineering-Incidents-Playbook"
    "/main/export/rules.json"
)
WHERE_URL: Final = (
    "https://raw.githubusercontent.com/ArtVsMark/Engineering-Incidents-Playbook"
    "/badges/export/where.json"
)
CATALOGUE: Final = "ArtVsMark/Engineering-Incidents-Playbook"

#: Подключение действия каталога — с подпутём и без него. Обе формы законны и
#: обе живут в дереве: `<repo>/.github/actions/<имя>@<тег>` подключает одно
#: действие, `<repo>@<тег>` — действие из корня. Прежняя редакция искала подстроку
#: `<repo>/` и вторую форму теряла: `rules-inbox.yml` выпадал из счёта молча, а
#: совпадение тегов у обоих подключений это маскировало. Нашёл разбор на #119.
PINNED_RE: Final = re.compile(rf"{re.escape(CATALOGUE)}(?:/[^@\s]+)?@(?P<tag>v[^\s#'\"]+)")

#: Манифест версий, которые умеет ставить `actions/setup-python`. Источник
#: выбран не «самый правдивый о языке», а САМЫЙ БЛИЗКИЙ К ПРЕДМЕТУ: вопрос здесь
#: не «что выпустил CPython», а «что сможет поставить наш прогон». Между этими
#: двумя ответами бывает несколько дней, и красное о версии, которой у площадки
#: ещё нет, — это красное о чужом расписании.
#:
#: ГРАНИЦА ИСТОЧНИКА, КОТОРУЮ НАДО ЗНАТЬ: он не говорит о КОНЦЕ поддержки.
#: Версия, снятая с поддержки, остаётся в манифесте, и «3.9 давно не
#: поддерживается» отсюда не выводится. Это отдельный вход, и его тут нет (154).
PYTHON_MANIFEST: Final = (
    "https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json"
)

#: Механизмами считаются эти три рода ответа. Тот же состав, что у разреза
#: семьи: два понимания слова «держится машиной» разошлись бы молча (090).
#: Виды механизма — из общего места (`scripts/kinds.py`), а не своей копией.
MACHINE: Final = kinds.MACHINE


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «дрейфа нет»."""


@dataclass(frozen=True, slots=True)
class Drift:
    """Одна находка дрейфа: чей вход сдвинулся, что видно и что делать."""

    #: Короткое имя источника — по нему запись узнаётся снова и снимается.
    source: str
    #: Что именно разошлось, числами: «было X, стало Y», а не «устарело».
    said: str
    #: Что с этим делать. Без этого запись — сообщение о погоде (142).
    next_step: str

    def __str__(self) -> str:
        """Строка записи ровно того вида, который читает разбор тела задачи."""
        return f"- `{self.source}` — {self.said} · **что делать:** {self.next_step}"


#: Чтение чужого снимка — общим транспортом, а не своим. Второй транспорт
#: вырастает из фразы «мне нужен всего один запрос», и гейт `test_ghrest.py`
#: поймал здесь ровно это (090).
fetch = ghrest.raw_json


def ours_proposals() -> dict[str, Any]:
    """Наши предложения каталогу — из дерева."""
    path = paths.PROPOSALS
    if not path.is_file():
        raise NotRun(f"нет {path}: канал предложений не подключён (075)")
    said = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(said, dict):
        raise NotRun(f"{path}: предложения не словарь")
    return said


def ours() -> dict[str, Any]:
    """Наш живой ответ каталогу — из дерева, а не из чужого снимка."""
    path = paths.BINDINGS
    if not path.is_file():
        raise NotRun(f"нет {path}: сверять снимок не с чем (075)")
    answer = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(answer, dict):
        raise NotRun(f"{path}: ответ каталогу не словарь")
    return answer


#: Наши файлы, отвечающие контрактам каталога: имя контракта → путь и ключ
#: версии. Контракты `consumers` и `where` сюда не входят — это файлы САМОГО
#: каталога (реестр потребителей и карта «где действует правило»), и сверять
#: нам в них нечего.
OUR_CONTRACTS: Final = (
    ("bindings", paths.BINDINGS.as_posix()),
    ("proposals", paths.PROPOSALS.as_posix()),
    ("showcase", paths.SHOWCASE.as_posix()),
)


def ours_by_contract(mine: dict[str, Any], root: Path | None = None) -> list[tuple[str, str, str]]:
    """Наши объявленные номера контрактов: имя, путь, версия.

    Ответ по правилам уже прочитан зовущим и передаётся готовым — второе чтение
    того же файла разошлось бы с первым молча (022). Остальные читаются здесь.

    Файла нет или он без `schema` — номер пустой, и сверять нечего: ключа нет
    значит «не прочитали», а не «ноль» (так же читает это сам каталог).
    """
    said: list[tuple[str, str, str]] = []
    base = root or Path()
    for name, path in OUR_CONTRACTS:
        if name == "bindings":
            said.append((name, path, str(mine.get("schema") or "")))
            continue
        try:
            answer = json.loads((base / path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        said.append((name, path, str(answer.get("schema") or "")))
    return said


def catalogue_moved(export: dict[str, Any], mine: dict[str, Any]) -> list[Drift]:
    """Каталог сдвинулся: новые правила или новая версия выгрузки.

    Отставание версии выгрузки — не про формат: подъём контракта означает, что
    ответы стоит ПЕРЕЧИТАТЬ, а не только починить схему (157). Первая редакция
    нашего ответа объявила схему по памяти, и расхождение всплыло только на
    чужом прогоне — то есть у соседа, а не у нас.
    """
    found: list[Drift] = []
    contracts = export.get("contracts") or {}
    theirs, said_ours = str(contracts.get("export") or ""), str(mine.get("answers_to") or "")
    if theirs and said_ours and theirs != said_ours:
        found.append(
            Drift(
                "export-contract",
                f"выгрузка каталога поднялась до {theirs}, ответы построены по {said_ours}",
                "перечитать ответы под новую выгрузку, затем поднять `answers_to` (157)",
            )
        )
    # СВЕРЯЮТСЯ ВСЕ НАШИ НОМЕРА, А НЕ ОДИН. Каталог отдаёт блок `contracts` со
    # всеми форматами разом, и двигаются они ПОРОЗНЬ: подъём выгрузки не
    # означает подъёма формы ответа, и наоборот. Пока сверялась одна `bindings`,
    # отставание `proposals` жило незамеченным — файл валиден, номер старый,
    # и обе стороны видят своё зелёное. Замер 11.09.2026: каталог поднял шесть
    # контрактов разом, у нас разошлись два.
    for name, path, said in ours_by_contract(mine):
        theirs_now = str(contracts.get(name) or "")
        if theirs_now and said and theirs_now != said:
            found.append(
                Drift(
                    f"{name}-schema",
                    f"каталог ждёт {name} {theirs_now}, у нас {said}",
                    f"привести `{path}` к контракту каталога и перечитать ответы (157)",
                )
            )
    theirs_count = export.get("count")
    answered = len(mine.get("rules") or {})
    if isinstance(theirs_count, int) and theirs_count != answered:
        found.append(
            Drift(
                "rules-count",
                f"правил в каталоге {theirs_count}, ответов у нас {answered}",
                "ответить по новым правилам — очередь разбора, а не молчание (129)",
            )
        )
    return found


def snapshot_is_stale(where: dict[str, Any], mine: dict[str, Any], project: str) -> list[Drift]:
    """Сводка семьи показывает нас не тем, чем мы стали.

    Это не косметика: по этой сводке соседи выбирают, у кого перенимать
    механизм, а разрез приоритета — наш собственный — считает по ней же. Замер
    10.09.2026: снимок семичасовой давности показывал шесть правил документами,
    когда они уже держались гейтами, и разрез назвал их «долгом», которого нет.
    """
    # СЕБЯ УЗНАЁМ ПО ПОЛНОМУ АДРЕСУ, А НЕ ПО ХВОСТУ ИМЕНИ. Сверка по хвосту
    # («…заканчивается на Engineering-Pipeline-Mechanisms») принимает за нас
    # форк или одноимённый репозиторий другого владельца — и тогда разрез
    # приоритета считается по ЧУЖОЙ сводке, а мы получаем «нас нет в сводке»
    # ровно тогда, когда мы в ней есть. Имя без владельца вообще не
    # идентификатор (194), и слабее необходимого оно здесь без всякой причины:
    # полный адрес у нас есть. Нашёл внешний взгляд на #119.
    us = next(
        (
            consumer
            for consumer in where.get("consumers") or []
            if str(consumer.get("repo") or "").lower() == project.lower()
        ),
        None,
    )
    if us is None:
        return [
            Drift(
                "family-snapshot",
                "нас нет в сводке семьи вовсе",
                "проверить, читает ли каталог наш ответ: `.rules/bindings.json` и его `project`",
            )
        ]
    shown = {
        rule: (answer or {}).get("mechanism")
        for rule, answer in (us.get("holds") or {}).items()
        if isinstance(answer, dict)
    }
    live = {
        rule: (answer or {}).get("mechanism") for rule, answer in (mine.get("rules") or {}).items()
    }
    behind = sorted(
        rule
        for rule, mechanism in live.items()
        if mechanism in MACHINE and shown.get(rule) not in MACHINE
    )
    if not behind:
        return []
    said = ", ".join(behind[:6]) + ("…" if len(behind) > 6 else "")
    return [
        Drift(
            "family-snapshot",
            f"сводка показывает {len(behind)} наших правил документами, "
            f"а они уже механизмы: {said}",
            "дождаться ночного прогона каталога либо позвать его кнопкой; "
            "до тех пор разрез приоритета по этой сводке врёт",
        )
    ]


def pinned_tag_moved(repo: str, token: str) -> list[Drift]:
    """Действие каталога подключено тегом, а у каталога вышел новый выпуск.

    Тег здесь оставлен намеренно (закрепление по SHA — для того, что приходит
    со стороны), но «намеренно» не значит «навсегда»: выпуск каталога может
    нести починку гейта, которым мы держим своё правило.
    """
    used: dict[str, set[str]] = {}
    for path in sorted(paths.WORKFLOWS.glob("*.yml")):
        for found in PINNED_RE.finditer(path.read_text(encoding="utf-8")):
            used.setdefault(found.group("tag"), set()).add(path.name)
    if not used:
        return []
    latest = ghrest.request("GET", f"repos/{CATALOGUE}/releases/latest", token) or {}
    newest = str(latest.get("tag_name") or "")
    behind = sorted(tag for tag in used if newest and tag != newest)
    if not behind:
        return []
    # ТЕГ НАЗЫВАЕТСЯ ВМЕСТЕ СО СВОИМИ ФАЙЛАМИ, А НЕ РЯДОМ С ЧУЖИМИ. Прежде
    # печатались два плоских списка — теги и все файлы разом, — и при разных
    # отставших тегах в разных прогонах читатель не мог понять, что где: а
    # править надо именно тот файл, где стоит именно тот тег. Нашёл внешний
    # взгляд на #122.
    where = "; ".join(f"{tag} — {', '.join(sorted(used[tag]))}" for tag in behind)
    return [
        Drift(
            "catalogue-action",
            f"подключено {where}; у каталога выпущен {newest}",
            f"прочитать журнал выпуска и поднять тег, если он нас касается: "
            f"https://github.com/{CATALOGUE}/releases/tag/{newest}",
        )
    ]


#: Версия языка вида `3.14` — по ней сравниваются матрица и манифест. Патч
#: сюда не входит намеренно: матрица гоняет ветку языка, а не выпуск.
#: Как площадка называет право обхода для спрашивающего. «never» — не вправе
#: никогда; прочие значения означают, что вправе при каких-то условиях.
NEVER: Final = "never"


def declared_protection(where: Path | None = None) -> dict[str, Any]:
    """Объявленная защита общей ветки — из дерева."""
    path = where or paths.PROTECTION
    if not path.is_file():
        raise NotRun(f"нет {path}: защита общей ветки не объявлена (075)")
    said: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not said.get("branch"):
        raise NotRun(f"{path}: ветка не названа — сравнивать не с чем (075)")
    return said


def protection_moved(repo: str, token: str) -> list[Drift]:
    """Защита общей ветки против объявленной: что ослаблено молча.

    НАСТРОЙКА ЖИВЁТ ВНЕ ДЕРЕВА, и это делает её слепым пятном: её не видит ни
    ревью, ни прогон гейтов, а ослабление не краснеет нигде. У соседа-грейдера
    то же место закрыто `check_branch_protection.py`, и там же названа причина:
    публичное утверждение «список обходов пуст» должно кем-то проверяться.

    СРАВНИВАЕТСЯ С ОБЪЯВЛЕНИЕМ, А НЕ СО ВЧЕРАШНИМ СНИМКОМ. Снимок согласился бы
    с любым изменением: он описывает, а не требует. Объявление требует, и
    потому ослабление становится правкой файла — то есть изменением, которое
    кто-то открывает и объясняет (064).

    ПРАВО ОБХОДА СПРАШИВАЕТСЯ ПРО СПРАШИВАЮЩЕГО. Площадка отдаёт
    `current_user_can_bypass` — ответ про ТОТ токен, которым задан вопрос.
    Здесь это токен прогона, и объявление говорит о нём: прогон не вправе
    толкать мимо проверок никогда. Про токен владельца поле не говорит ничего,
    и выдавать один ответ за другой значило бы назвать проверенным то, чего не
    спрашивали (046).
    """
    said = declared_protection()
    branch = str(said["branch"])
    found: list[Drift] = []

    rules = ghrest.request("GET", f"repos/{repo}/rules/branches/{branch}", token) or []
    kinds_now = sorted({str(one.get("type") or "") for one in rules})
    kinds_want = sorted(str(one) for one in said.get("rules") or [])
    gone = [name for name in kinds_want if name not in kinds_now]
    if gone:
        found.append(
            Drift(
                "защита общей ветки",
                f"правил объявлено {len(kinds_want)}, на площадке действует {len(kinds_now)}: "
                f"нет {', '.join(gone)}",
                "вернуть правило в набор либо объявить ослабление в `.rules/protection.json` "
                "с названной причиной",
            )
        )

    checks = [one for one in rules if str(one.get("type") or "") == "required_status_checks"]
    for one in checks:
        given = one.get("parameters") or {}
        names_now = sorted(
            str((item or {}).get("context") or "")
            for item in given.get("required_status_checks") or []
        )
        names_want = sorted(str(name) for name in said.get("required_contexts") or [])
        if names_now != names_want:
            found.append(
                Drift(
                    "защита общей ветки",
                    f"обязательные контексты: объявлено {names_want}, на площадке {names_now}",
                    "привести набор к объявленному либо перечитать объявление",
                )
            )
        strict_now = bool(given.get("strict_required_status_checks_policy"))
        if strict_now != bool(said.get("strict")):
            found.append(
                Drift(
                    "защита общей ветки",
                    f"свежесть относительно общей ветки: объявлено {said.get('strict')}, "
                    f"на площадке {strict_now}",
                    "вернуть требование свежести либо объявить отказ от него с причиной",
                )
            )

    # ПРАВО ОБХОДА ЧИТАЕТСЯ У КАЖДОГО НАБОРА, ПРИКРЫВАЮЩЕГО ЭТУ ВЕТКУ, А НЕ У
    # ПЕРВОГО. Наборов бывает несколько, и вправе обойти достаточно одного:
    # выйти после первого значило бы проверить самый безобидный и назвать это
    # проверкой. Нашёл внешний взгляд на #272 — докстринг обещал обход всех, а
    # код читал один.
    want = str(said.get("run_token_may_bypass") or NEVER)
    for ruleset in sorted(
        {one["ruleset_id"] for one in rules if one.get("ruleset_id") is not None}
    ):
        got = ghrest.request("GET", f"repos/{repo}/rulesets/{ruleset}", token) or {}
        can = str(got.get("current_user_can_bypass") or "")
        if not can:
            raise NotRun(
                f"набор {ruleset}: площадка не сказала про право обхода — "
                "ответ не прочитан, и «обхода нет» из этого не следует (045)"
            )
        if can != want:
            found.append(
                Drift(
                    "защита общей ветки",
                    f"право обхода у токена прогона в наборе {ruleset}: "
                    f"объявлено «{want}», площадка говорит «{can}»",
                    "снять обход у прогона либо объявить его в `.rules/protection.json` "
                    "с названной причиной — прогон мимо гейтов это путь в общую ветку",
                )
            )

    return found


MINOR_RE: Final = re.compile(r"^(?P<minor>\d+\.\d+)")


def order(minor: str) -> tuple[int, ...]:
    """Числовой порядок версии: `3.9` младше `3.10`, а по строке — старше.

    НЕЧИСЛОВАЯ ЗАПИСЬ НЕ РОНЯЕТ ЗАХОД. Матрица читается из `ci.yml`, то есть из
    правимого руками файла: опечатка вроде `3.13-dev` или `pypy3.10` дала бы
    `ValueError` — и упал бы ВЕСЬ дрейф, включая источники, к языку отношения
    не имеющие. Источники затем и разделены, чтобы отказ одного не уносил
    остальные. Непонятная запись уходит в НАЧАЛО: пустой кортеж младше любого
    номера. Это не случайность разбора, а верная сторона ошибки — непонятное
    надо увидеть, а не задвинуть в хвост; молча выбрасывать её тем более
    нельзя, тогда скрылось бы, что в матрице что-то не то.

    Найдено внешним взглядом дважды, и это два разных захода: на #159 — что
    текст расходился с кодом и с собственным тестом («в конец» вместо «в
    начало»), на #121 — что нечисловая запись роняла весь дрейф исключением.
    """
    parts: list[int] = []
    for part in minor.split("."):
        if not part.isdigit():
            return ()
        parts.append(int(part))
    return tuple(parts)


def minors(manifest: list[Any]) -> tuple[list[str], list[str]]:
    """Ветки языка из манифеста: со стабильным выпуском и пока только с пробным.

    Разница здесь и есть предмет: ветка со стабильным выпуском — та, на которой
    проект обещает работать; ветка с одними пробными — та, на которой он
    обещаний не давал. Наша матрица построена ровно на этом делении.
    """
    stable: set[str] = set()
    seen: set[str] = set()
    for one in manifest:
        if not isinstance(one, dict):
            continue
        found = MINOR_RE.match(str(one.get("version") or ""))
        if not found:
            continue
        minor = found.group("minor")
        seen.add(minor)
        if one.get("stable"):
            stable.add(minor)
    ordered = sorted(stable, key=order)
    return ordered, sorted(seen - stable, key=order)


def declared_versions() -> tuple[list[str], str]:
    """Что гоняет прогон: ветки матрицы и предрелизная ветка `test-next`."""
    path = paths.WORKFLOWS / "ci.yml"
    # Читается общим разбором, а не своим: форма прогона одна на всех, и
    # второе её понимание разошлось бы с первым молча (090).
    jobs = pipeline_checks.run_of(path).get("jobs") or {}
    matrix = (((jobs.get("test-matrix") or {}).get("strategy") or {}).get("matrix") or {}).get(
        "python"
    )
    if not isinstance(matrix, list) or not matrix:
        raise NotRun(f"{path}: матрица версий не разобралась — сверять нечего (075)")
    ahead = ""
    for step in (jobs.get("test-next") or {}).get("steps") or []:
        said = ((step or {}).get("with") or {}).get("python-version")
        if said:
            ahead = str(said)
    return [str(one) for one in matrix], ahead


def language_moved(manifest: list[Any], matrix: list[str], ahead: str) -> list[Drift]:
    """Язык выпустил версию, а прогон об этом не знает.

    ПОЧЕМУ ЭТО ДРЕЙФ, А НЕ ЗАДАЧА. Ни одна наша правка не делает 3.15
    стабильной: это происходит по расписанию CPython, между нашими изменениями,
    и не приходит ни красным, ни задачей. Замер 10.09.2026: о том, что 3.14 уже
    вышла, а предрелизной стала 3.15, механизм не узнал — это сказал владелец.
    """
    stable, pre = minors(manifest)
    if not stable:
        raise NotRun("в манифесте нет ни одной стабильной ветки — читать нечего (075)")
    found: list[Drift] = []
    newest = stable[-1]
    unknown = sorted(set(matrix) - set(stable) - set(pre), key=order)
    if unknown:
        found.append(
            Drift(
                "python-matrix",
                f"матрица называет {', '.join(unknown)}, а площадка такой ветки не знает",
                "прогон не сможет поставить эту версию — сверить матрицу с манифестом",
            )
        )
    if newest not in matrix:
        found.append(
            Drift(
                "python-stable",
                f"стабильна {newest}, матрица гоняет {', '.join(matrix)}",
                f"добавить {newest} в матрицу `test-matrix`: обязательный агрегат `test` "
                f"обещает работу на стабильных ветках",
            )
        )
    if ahead and ahead in stable:
        found.append(
            Drift(
                "python-next",
                f"{ahead} стоит предрелизной в `test-next`, а она уже стабильна",
                f"перенести {ahead} в матрицу, а `test-next` навести на следующую ветку",
            )
        )
    if pre:
        newest_pre = pre[-1]
        if ahead and ahead not in stable and order(newest_pre) > order(ahead):
            found.append(
                Drift(
                    "python-next",
                    f"предрелизная теперь {newest_pre}, а `test-next` держит {ahead}",
                    f"навести `test-next` на {newest_pre}",
                )
            )
    return found


#: Ответ каталога по предложениям потребителей: ключ «владелец/репозиторий:слаг»,
#: статус `admitted` с номером либо `rejected` с причиной. Файл каталога, а не
#: наш: он и отвечает.
CATALOGUE_PROPOSALS: Final = (
    "https://raw.githubusercontent.com/ArtVsMark/Engineering-Incidents-Playbook"
    "/main/.rules/proposals.json"
)
#: Раздел ответа, в котором каталог держит вердикты. Имя взято У КАТАЛОГА, а не
#: придумано: разбор по памяти молчал четыре раза подряд (#140).
VERDICTS: Final = "verdicts"


def proposals_answered(answer: dict[str, Any], mine: dict[str, Any], project: str) -> list[Drift]:
    """Каталог ответил по нашему предложению, а оно всё ещё числится предложением.

    ПОЧЕМУ ЭТО ДРЕЙФ. Вердикт выносит каталог, у себя и по своему расписанию —
    ни одна наша правка этого не делает, и события об этом не приходит. Принятое
    предложение перестаёт быть предложением: у него появился НОМЕР, и по нему
    теперь отвечают в `.rules/bindings.json`, а не в очереди на приём (080).
    Отвергнутое тоже: причина названа, и держать его в списке значит обещать
    отправку, которой не будет.

    Приём взят у грейдера, где он уже стоит ночным обходом (162).

    ФОРМА ОТВЕТА ЧИТАЕТСЯ У КАТАЛОГА, А НЕ ПО ПАМЯТИ. Прежняя редакция искала
    вердикты под ключом `proposals`, номер — в полях `number`/`id`, и статуса
    `merged-into` не знала вовсе. Каталог отдаёт их под `verdicts`, номер в
    поле `rule`, и третий статус у него есть. Расхождение молчало: не найдя
    ключа, обход переходил к следующему предложению — то есть источник дрейфа
    ровно так же печатал «сошлось», как если бы вердиктов и правда не было.
    Цена измерена: к 11.09.2026 каталог принял ВСЕ ЧЕТЫРЕ наших предложения
    (правила 198–201), и ни об одном источник не сказал. Нашёл внешний взгляд
    на #140 — предупредив ровно об этом и до того, как это стоило работы.

    НЕУЗНАННАЯ ФОРМА — ЭТО ЗАПИСЬ, А НЕ МОЛЧАНИЕ. «Ответа нет» и «ответ в
    незнакомом виде» снаружи одинаковы и значат разное (045, 154): первое
    штатно, второе означает, что источник ослеп.
    """
    # ПРЕДМЕТА НЕТ — И СПРАШИВАТЬ НЕ О ЧЕМ. Пустая очередь предложений законна
    # и объявлена таковой в самом файле: вердиктов по ней быть не может, и
    # разбирать форму чужого ответа незачем. Проверка формы ниже относится к
    # случаю «нам есть о чём спросить, а ответ не узнан».
    ours = [one for one in mine.get("proposals") or [] if isinstance(one, dict)]
    if not ours:
        return []
    said = answer.get(VERDICTS)
    if not isinstance(said, dict):
        return [
            Drift(
                "proposal-answer-unread",
                f"ответ каталога по предложениям без раздела «{VERDICTS}» — "
                f"форма не узнана (ключи: {report.cut(', '.join(sorted(map(str, answer))))})",
                "сверить разбор с export/README.md каталога: пока форма не узнана, "
                "источник молчит не потому, что вердиктов нет",
            )
        ]
    found: list[Drift] = []
    for one in ours:
        slug = str(one.get("slug") or "")
        verdict = said.get(f"{project}:{slug}")
        if verdict is None:
            # Каталог ещё не ответил — ожидание, а не расхождение.
            continue
        if not isinstance(verdict, dict):
            found.append(
                Drift(
                    "proposal-answer-unread",
                    f"вердикт по «{slug}» пришёл не словарём, а {type(verdict).__name__}",
                    "сверить разбор с export/README.md каталога: ответ есть, а прочитать "
                    "его нечем — молчать об этом значит выдать неразобранное за «нет ответа»",
                )
            )
            continue
        status = str(verdict.get("status") or "")
        if not status:
            # ВЕРДИКТ БЕЗ СТАТУСА — НЕ «ВЕРДИКТА НЕТ». Запись есть, ответ дан, а
            # прочитать его нечем: пропустить такую значит объявить отвеченное
            # неотвеченным и держать предложение в очереди навсегда (045).
            # Нашёл внешний взгляд на #179.
            found.append(
                Drift(
                    "proposal-answer-unread",
                    f"вердикт по «{slug}» есть, а поля «status» в нём нет "
                    f"(поля: {report.cut(', '.join(sorted(map(str, verdict))))})",
                    "сверить разбор с export/README.md каталога: ответ есть, "
                    "и молчать о нём нельзя",
                )
            )
            continue
        # Номер присваивает КАТАЛОГ и называет его полем `rule`. Наш файл
        # предложений номера не несёт и нести не может — это сказано в нём же.
        number = str(verdict.get("rule") or "?")
        why = str(verdict.get("why") or "причина не названа")
        if status == "admitted":
            found.append(
                Drift(
                    "proposal-admitted",
                    f"каталог принял «{slug}» под номером {number}",
                    f"убрать его из .rules/proposals.json и ответить по правилу {number} "
                    "в .rules/bindings.json — принятое перестаёт быть предложением",
                )
            )
        elif status == "merged-into":
            found.append(
                Drift(
                    "proposal-merged",
                    f"каталог свёл «{slug}» с правилом {number}: {report.cut(why)}",
                    f"убрать его из .rules/proposals.json и перечитать ответ по {number}: "
                    "предмет тот же, запись уже есть",
                )
            )
        elif status == "rejected":
            found.append(
                Drift(
                    "proposal-rejected",
                    f"каталог отверг «{slug}»: {report.cut(why)}",
                    "убрать его из .rules/proposals.json: держать отвергнутое значит "
                    "обещать отправку, которой не будет",
                )
            )
        elif status:
            found.append(
                Drift(
                    "proposal-answer-unread",
                    f"каталог ответил по «{slug}» статусом «{status}», которого разбор не знает",
                    "сверить список статусов с export/README.md каталога: незнакомый "
                    "статус молча уходит в «вердикта нет»",
                )
            )
    return found


def render_body(found: list[Drift], silent: list[str] | None = None) -> str:
    """Тело живой задачи: записи, неопрошенные источники и как это снимается."""
    lines = [
        MARKER,
        "",
        "> **Читатель:** окно, берущее работу. Дрейф — это источник работы, а не",
        "> красное: сдвинулся ВНЕШНИЙ вход, дерево не менялось.",
        "",
        "Запись снимается сама, когда расхождения больше нет: тело переписывается",
        "на каждом заходе целиком, и ведётся не руками, а механизмом (049).",
        "",
        "## Сдвинулось",
        "",
    ]
    if found:
        lines.extend(str(one) for one in found)
    else:
        lines.append("Пусто — внешние входы сошлись с деревом.")
    if silent:
        # Неопрошенный источник называется здесь же: без этого пустой список
        # читался бы как «всё сошлось», а он значит «половину не спросили».
        lines += [
            "",
            "## Не спрошено на последнем заходе",
            "",
            *(f"- {name}" for name in silent),
        ]
    return "\n".join(lines) + "\n"


def save(repo: str, token: str, found: list[Drift], silent: list[str], *, apply: bool) -> None:
    """Записывает живую задачу: обновляет по месту или заводит одну.

    Отказ записи шага не роняет: дрейф — совещательный канал, и потерять о нём
    сообщение хуже, чем не иметь его вовсе (084).
    """
    body = render_body(found, silent)
    number, current = findings.live_issue(repo, token, MARKER)
    if not apply:
        print(f"(пробный заход) {'обновил бы' if number else 'завёл бы'} задачу дрейфа")
        return
    try:
        if number is None:
            if not found:
                # Заводить пустую задачу незачем: пустого адресата никто не
                # читает, а его существование выглядит работой.
                return
            fresh = ghrest.request(
                "POST", f"repos/{repo}/issues", token, {"title": TITLE, "body": body}
            )
            print(f"заведена задача дрейфа #{(fresh or {}).get('number')}")
            return
        if current.strip() == body.strip():
            print(f"задача дрейфа #{number} уже описывает это состояние")
            return
        ghrest.request("PATCH", f"repos/{repo}/issues/{number}", token, {"body": body})
        print(f"задача дрейфа #{number} обновлена")
    except ghrest.TransportError as exc:
        print(f"::warning::Дрейф не записан: {report.cut(str(exc))}", file=sys.stderr)


def manifest(url: str) -> list[Any]:
    """Манифест версий приходит СПИСКОМ, а не словарём: свой разбор, не `fetch`.

    Общий транспорт один (`ghrest`), а форма ответа у снимков разная, и делать
    вид, что она одна, значило бы ронять разбор на первом же чужом файле.
    """
    text = ghrest.raw_text(url)
    try:
        said = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NotRun(f"манифест версий не разбирается ({url}): {exc}") from exc
    if not isinstance(said, list) or not said:
        raise NotRun(f"манифест версий пуст или не список ({url})")
    return said


#: Источники дрейфа: имя и то, как его спросить. Списком, а не цепочкой
#: вызовов, потому что источники НЕЗАВИСИМЫ: недоступный каталог не отменяет
#: устаревшей сводки семьи. Отказ одного источника печатается и заход идёт
#: дальше; молча пропущенный источник выглядел бы как «дрейфа нет» (045).
SOURCES: Final = (
    "каталог",
    "сводка семьи",
    "выпуск каталога",
    "версии языка",
    "вердикты по предложениям",
    "защита общей ветки",
)


def look(repo: str, token: str, mine: dict[str, Any]) -> tuple[list[Drift], list[str]]:
    """Спрашивает все источники; отдаёт находки и имена тех, кто не ответил."""
    found: list[Drift] = []
    silent: list[str] = []
    asks: tuple[tuple[str, Any], ...] = (
        ("каталог", lambda: catalogue_moved(fetch(EXPORT_URL), mine)),
        (
            "сводка семьи",
            lambda: snapshot_is_stale(fetch(WHERE_URL), mine, str(mine.get("project") or repo)),
        ),
        ("выпуск каталога", lambda: pinned_tag_moved(repo, token)),
        ("защита общей ветки", lambda: protection_moved(repo, token)),
        ("версии языка", lambda: language_moved(manifest(PYTHON_MANIFEST), *declared_versions())),
        (
            "вердикты по предложениям",
            lambda: proposals_answered(
                fetch(CATALOGUE_PROPOSALS), ours_proposals(), str(mine.get("project") or repo)
            ),
        ),
    )
    for name, ask in asks:
        try:
            found.extend(ask())
        except (NotRun, ghrest.TransportError, pipeline_checks.BadPolicy) as exc:
            silent.append(name)
            print(
                f"::warning::Источник «{name}» не ответил: {report.cut(str(exc))}", file=sys.stderr
            )
    return found, silent


def main(argv: list[str] | None = None) -> int:
    """Точка входа: спрашивает внешние входы и записывает расхождения."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="записать, а не показать")
    args = parser.parse_args(argv)

    try:
        token = ghrest.token_from_env()
        if not token:
            raise NotRun("нет токена: GH_TOKEN или GITHUB_TOKEN")
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        mine = ours()
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    found, silent = look(args.repo, token, mine)
    # Молчание ВСЕХ источников — это поломка захода, а не сошедшееся состояние:
    # «дрейфа нет» и «спросить не удалось» снаружи одинаковы (045).
    if len(silent) == len(SOURCES):
        print("шаг не отработал: ни один источник не ответил", file=sys.stderr)
        return EXIT_BROKEN

    for one in found:
        print(str(one))
    save(args.repo, token, found, silent, apply=args.apply)
    if not found:
        print("дрейфа нет: внешние входы сошлись с деревом")
        return EXIT_NOTHING
    print(f"сдвинулось внешних входов: {len(found)}")
    return EXIT_RECORDED


if __name__ == "__main__":
    raise SystemExit(main())
