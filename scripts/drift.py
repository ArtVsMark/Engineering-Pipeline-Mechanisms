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

import catalogue
import family
import findings
import ghrest
import kinds
import paths
import pipeline_checks
import protection
import report

MARKER: Final = findings.marker("drift")
TITLE: Final = "Дрейф: внешнее состояние сдвинулось"

EXIT_NOTHING: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RECORDED: Final = 3

#: Выгрузка каталога и сводка потребителей. Оба — СНИМКИ: каталог собирает их
#: своим прогоном, и читаются они по сети, а не из дерева. В этом весь предмет
#: механизма: дерево не менялось, а снимок — да.
EXPORT_URL: Final = catalogue.EXPORT_URL
WHERE_URL: Final = catalogue.WHERE_URL
CATALOGUE: Final = catalogue.REPO

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


def ours_file(path: Path, *, missing: str) -> dict[str, Any]:
    """Наш ответ каталогу из дерева: читает, проверяет форму, зовёт третий исход.

    ОБОБЩЕНО ПО ТРЕТЬЕМУ СЛУЧАЮ, А НЕ ПО ВТОРОМУ
    ([093](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/093-seam-early-generalisation-late.md)).
    Два файла читались порознь законно: одинаковая форма ещё не общий приём.
    Третий — набор вопросов витрины, заведённый 13.09.2026, — и стал поводом;
    нашёл его замер по всем 473 функциям дерева, а не глаз.

    ЧЕГО ЗДЕСЬ НЕТ. Что делать с прочитанным, решает зовущий: у ответов
    каталогу, предложений и витрины общее только чтение. Свести их разбор
    значило бы связать три разных предмета одной формой.
    """
    if not path.is_file():
        raise NotRun(f"нет {path}: {missing} (075)")
    said = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(said, dict):
        raise NotRun(f"{path}: прочитанное не словарь")
    return said


def ours_proposals() -> dict[str, Any]:
    """Наши предложения каталогу — из дерева."""
    return ours_file(paths.PROPOSALS, missing="канал предложений не подключён")


def ours() -> dict[str, Any]:
    """Наш живой ответ каталогу — из дерева, а не из чужого снимка."""
    return ours_file(paths.BINDINGS, missing="сверять снимок не с чем")


#: Наши файлы, отвечающие контрактам каталога: имя контракта → путь и ключ
#: версии. Контракт `consumers` сюда не входит — это файл САМОГО каталога
#: (реестр потребителей), и своего номера у нас против него нет.
#:
#: ПРО `where` ЗДЕСЬ СТОЯЛА ОПРОВЕРГНУТАЯ ПРЕМИСА. Было написано: «это файлы
#: самого каталога, и сверять нам в них нечего». Первое верно, второе — нет:
#: файл чужой, но ЧИТАТЕЛЬ наш, и у него есть объявленный номер —
#: `family.READS_SCHEMA`. Цена премисы измерена: сводка ушла на 1.3 восьмого
#: сентября, разрез остался под 1.2, и девять дней об этом не сказал никто —
#: расхождение считалось в `build_facts` и никуда не печаталось. Сверяется
#: `where` теперь там, где сводка и читается, — в `reader_is_behind`, а не
#: здесь: предмет у него другой, не наш файл, а наш читатель (044).
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


def reader_is_behind(where: dict[str, Any]) -> list[Drift]:
    """Сводка семьи сменила форму, а разрез написан под прежнюю.

    ЧУЖОЙ ФАЙЛ, НО СВОЙ ЧИТАТЕЛЬ. Сводку пишет каталог, и править её нам
    нечего — а вот номер, под который написан наш разрез, наш целиком
    (`family.READS_SCHEMA`). Подъём означает перечитать разрез, а не подвинуть
    число
    ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).

    ЗАМЕР, ИЗ КОТОРОГО ЭТА СВЕРКА ВЫРОСЛА: 8 сентября сводка ушла на 1.3,
    разрез остался под 1.2, и расхождение прожило девять дней. Считалось оно
    всё это время — `build_facts` клал его в факты ключом `schema_agrees`, — и
    не печаталось нигде. Вычисленное и несказанное равно несчитанному (046).

    Номер отсутствует — сверять нечего, и это не «ноль»: ключа нет значит «не
    прочитали» (045). То же соглашение у самого каталога.
    """
    theirs = str(where.get("schema") or "")
    if not theirs or theirs == family.READS_SCHEMA:
        return []
    return [
        Drift(
            "family-schema",
            f"сводка семьи отдаётся по форме {theirs}, разрез написан под {family.READS_SCHEMA}",
            "перечитать `scripts/family.py` под новую форму, затем поднять "
            "`READS_SCHEMA` — механическое поднятие числа оставляет разрез "
            "отвечать на прежний вопрос (157)",
        )
    ]


def our_slice(where: dict[str, Any], project: str) -> dict[str, Any] | None:
    """Наш срез в сводке семьи — один поиск на всех, кто в него смотрит.

    СЕБЯ УЗНАЁМ ПО ПОЛНОМУ АДРЕСУ, А НЕ ПО ХВОСТУ ИМЕНИ. Сверка по хвосту
    («…заканчивается на Engineering-Pipeline-Mechanisms») принимает за нас форк
    или одноимённый репозиторий другого владельца — и тогда разрез приоритета
    считается по ЧУЖОЙ сводке, а мы получаем «нас нет в сводке» ровно тогда,
    когда мы в ней есть. Имя без владельца вообще не идентификатор, и слабее
    необходимого оно здесь без всякой причины: полный адрес у нас есть. Нашёл
    внешний взгляд на #119.

    ССЫЛКА НА 194 ЗДЕСЬ СТОЯЛА И СНЯТА. Правило «имя не доказывает владения»
    говорит о ВНЕШНИХ РЕЕСТРАХ, где имя занимает первый пришедший, и само
    оговаривает, что не работает там, где реестр удостоверяет принадлежность.
    Реестр потребителей каталога — закрытый и разрешительный, имя в нём никто
    не занимает, и наш ответ «неприменимо» верен. Требование здесь своё:
    сравнивать полный адрес, а не хвост.

    Читателей у среза стало двое — устаревший снимок и находки каталога о нашем
    ответе, — и вторая копия этого поиска разошлась бы с первой молча (090).
    """
    return next(
        (
            consumer
            for consumer in where.get("consumers") or []
            if str(consumer.get("repo") or "").lower() == project.lower()
        ),
        None,
    )


def catalogue_found(where: dict[str, Any], project: str) -> list[Drift]:
    """Находки каталога о НАШЕМ ответе доезжают до того, кто их чинит.

    КАНАЛ БЫЛ ПОСТРОЕН С ТОЙ СТОРОНЫ И НЕ ЧИТАЛСЯ С ЭТОЙ. Ключ `findings`
    завёлся в форме сводки 1.2 восьмого сентября ровно ради адресата: до него
    находки каталога о чужих ответах печатались у него же в логе прогона
    разделом «правятся не здесь» и жили ровно там — у находки не было того, кто
    её чинит
    ([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)).
    Замер 17.09.2026: живых находок каталога о потребителях девять, у нас одна,
    и ни одна не читалась ни строкой кода — девять дней.

    ЧУЖОЙ ТЕКСТ ЕДЕТ ЦИТАТОЙ, А НЕ КОМАНДОЙ. Находка приходит из соседнего
    репозитория и ложится в тело нашей задачи; исполняемого в ней нет ничего, а
    переносы строк из неё убираются — иначе одна находка разъехалась бы на
    несколько строк, и разбор тела прочитал бы обрывок как отдельную запись
    ([085](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/085-content-from-the-subject-is-untrusted-input-to-the-prompt.md)).
    Обрезка общая и говорит, насколько обрезала (016).

    ПУСТО — ЭТО СОСТОЯНИЕ, А НЕ ПРОВАЛ ЧТЕНИЯ. Каталог не нашёл у нас ничего —
    записи нет, и заводить её не из чего
    ([027](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/027-empty-state-is-a-state.md)).
    А «нас нет в сводке вовсе» — находка, и называет её сосед по файлу: второй
    раз то же самое здесь было бы вторым счётом одного (022).

    ЧИНИТСЯ У НАС, А НЕ У КАТАЛОГА. Находка о нашем ответе правится в
    `.rules/bindings.json`; ставит её каталог, а закрываем мы
    ([086](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/086-the-finder-does-not-grade-the-finding.md)).
    """
    us = our_slice(where, project)
    if us is None:
        return []
    said = us.get("findings")
    if not isinstance(said, list):
        # `null` каталог ставит себе сам — находок о себе у него нет. Это
        # «не нашли», а не «не прочитали», и молчание здесь законно.
        return []
    return [
        Drift(
            "catalogue-finding",
            f"каталог нашёл в нашем ответе: {report.cut(' '.join(str(one).split()))}",
            "перечитать ответ по этой находке и поправить `.rules/bindings.json` — "
            "ставит её каталог, а закрываем мы (086)",
        )
        for one in said
        if str(one).strip()
    ]


def snapshot_is_stale(where: dict[str, Any], mine: dict[str, Any], project: str) -> list[Drift]:
    """Сводка семьи показывает нас не тем, чем мы стали.

    Это не косметика: по этой сводке соседи выбирают, у кого перенимать
    механизм, а разрез приоритета — наш собственный — считает по ней же. Замер
    10.09.2026: снимок семичасовой давности показывал шесть правил документами,
    когда они уже держались гейтами, и разрез назвал их «долгом», которого нет.
    """
    us = our_slice(where, project)
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


def family_summary(where: dict[str, Any], mine: dict[str, Any], project: str) -> list[Drift]:
    """Три вопроса к одной сводке — и слить их нельзя.

    «Разрез читает не ту форму» чинится у нас правкой кода; «каталог нашёл в
    нашем ответе» — правкой ответа; «снимок отстал» — прогоном каталога, и
    нашей работы там нет вовсе. Адресат у каждого свой (142), а значит и запись
    своя. Читается при этом ОДИН ответ: второе чтение того же адреса могло бы
    прийти уже другим (022).
    """
    return (
        reader_is_behind(where)
        + catalogue_found(where, project)
        + snapshot_is_stale(where, mine, project)
    )


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
    """Объявленная защита общей ветки — из дерева.

    Чтение общее с сверкой обязательного контекста (`scripts/protection.py`): два
    понимания одной настройки уже расходились — сверка спрашивала классическую
    защиту, дрейф набор правил, — и одно из них объявляло находку на здоровой
    настройке (090, 022).
    """
    try:
        return protection.declared(where)
    except protection.NotRead as exc:
        raise NotRun(str(exc)) from exc


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

    # ОТКАЗ ОБЩЕГО ЧТЕНИЯ — ТРЕТИЙ ИСХОД ЭТОГО ИСТОЧНИКА, А НЕ ПАДЕНИЕ ЗАХОДА.
    # `protection.live` говорит о непрочитанном своим исключением, и пропустить
    # его наружу значило бы уронить весь дрейф из-за одной осечки сети: прочие
    # источники к ней отношения не имеют (084, 039). Нашёл внешний взгляд (74a6c07).
    try:
        rules = protection.live(repo, branch, token)
    except protection.NotRead as exc:
        raise NotRun(str(exc)) from exc
    kinds_now = protection.kinds(rules)
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


def matrix_of(jobs: dict[str, Any], job: str, path: Path) -> list[str]:
    """Ветки языка из матрицы названного джоба; пусто — третий исход, а не «нет».

    ОБА ДЖОБА НАЗЫВАЮТ ВЕРСИИ МАТРИЦЕЙ, и читаются они одинаково. У предрелизного
    ячейка одна, и она же даёт версию в ИМЕНИ записи проверки — `test-next
    (3.15)`, — то есть в списке проверок изменения видно, на чём прогнали.
    Прежде версия предрелизного жила в шаге, а разбор читал шаг: после переезда
    в матрицу он молча получал бы `${{ matrix.python }}` и дрейф предрелизной
    ветки не находился бы вовсе
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md),
    [090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    said = (((jobs.get(job) or {}).get("strategy") or {}).get("matrix") or {}).get("python")
    if not isinstance(said, list) or not said:
        raise NotRun(
            f"{path}: матрица версий у джоба «{job}» не разобралась — сверять нечего (075)"
        )
    return [str(one) for one in said]


def declared_versions() -> tuple[list[str], str]:
    """Что гоняет прогон: ветки обязательной матрицы и предрелизная ветка.

    ПРЕДРЕЛИЗНОЙ СЧИТАЕТСЯ НОВЕЙШАЯ ячейка предрелизного джоба. Сегодня она одна,
    но ячеек может стать больше — тогда сверять со стабильными надо ту, что впереди
    всех; выбор назван здесь, а не оставлен на «как получится» (154).
    """
    path = paths.WORKFLOWS / "ci.yml"
    # Читается общим разбором, а не своим: форма прогона одна на всех, и
    # второе её понимание разошлось бы с первым молча (090).
    jobs = pipeline_checks.run_of(path).get("jobs") or {}
    matrix = matrix_of(jobs, "test-matrix", path)
    ahead = sorted(matrix_of(jobs, "test-next", path), key=order)[-1]
    return matrix, ahead


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
CATALOGUE_PROPOSALS: Final = catalogue.PROPOSALS_URL
CATALOGUE_SHOWCASE: Final = catalogue.SHOWCASE_URL
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


def ours_showcase() -> dict[str, Any]:
    """Наш набор вопросов витрины — из дерева."""
    return ours_file(paths.SHOWCASE, missing="сверять набор вопросов не с чем")


def asked_ids(said: dict[str, Any]) -> list[str]:
    """Имена вопросов в объявленном порядке; пустой список — не ответ (075)."""
    questions = said.get("questions")
    if not isinstance(questions, list) or not questions:
        raise NotRun("в наборе витрины нет ни одного вопроса")
    return [str(one.get("id") or "") for one in questions if isinstance(one, dict)]


def showcase_questions_moved(theirs: dict[str, Any], mine: dict[str, Any]) -> list[Drift]:
    """Набор вопросов витрины разошёлся с эталоном каталога.

    ЭТАЛОН ЗДЕСЬ ЧУЖОЙ, А КОПИЯ НАША. Список вопросов один на все проекты
    семьи — иначе витрины не сравнить, — и живёт он у каталога; наш файл снят
    с него рукой. Пока сверялся только НОМЕР контракта, состав мог разойтись
    молча: каталог вправе добавить вопрос, не тронув схему, и обе стороны видят
    своё зелёное
    ([055](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/055-your-own-expectations-are-a-hypothesis.md)).

    СУДИТСЯ СОСТАВ, А НЕ ПОРЯДОК И НЕ ОТВЕТЫ. Порядок вопросов — оформление
    витрины, а ответ по каждому — наш и обязан быть нашим: сверять его с чужим
    значило бы требовать одинаковых проектов
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    theirs_ids, ours_ids = set(asked_ids(theirs)), set(asked_ids(mine))
    found: list[Drift] = []
    added = sorted(theirs_ids - ours_ids)
    if added:
        found.append(
            Drift(
                "showcase-questions",
                f"каталог спрашивает то, чего у нас нет: {', '.join(added)}",
                "ответить по новым вопросам витрины — `absent` с причиной тоже ответ (154)",
            )
        )
    gone = sorted(ours_ids - theirs_ids)
    if gone:
        found.append(
            Drift(
                "showcase-extra",
                f"у нас отвечено то, чего каталог не спрашивает: {', '.join(gone)}",
                "снять свой вопрос либо предложить его каталогу — второй список расходится молча",
            )
        )
    return found


#: Утверждение о пробеле в ответе каталогу: «пока не может», «ещё не сделана».
#: Образец узкий НАМЕРЕННО. Замер 13.09.2026 по 203 ответам: слов о пробеле —
#: одиннадцать, и десять из них законны (внешних участников нет, получателя вне
#: дерева нет, вторая половина правила не построена). Красное на них приучало
#: бы пролистывать
#: ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
GAP_RE: Final = re.compile(r"пока (?:не|нет)\b|ещё не\b", re.IGNORECASE)

#: Номер задачи рядом с утверждением о пробеле — в пределах этого окна знаков.
#: Дальше по тексту задача говорит уже о другом: ответы длинные, и номер из
#: соседнего абзаца к пробелу отношения не имеет.
GAP_WINDOW: Final = 160
TASK_RE: Final = re.compile(r"#(?P<number>\d{1,4})\b")


def gaps_naming_a_task(mine: dict[str, Any]) -> list[tuple[str, int]]:
    """Пары «правило → задача», где пробел подкреплён номером задачи."""
    found: list[tuple[str, int]] = []
    for number, answer in sorted((mine.get("rules") or {}).items()):
        if not isinstance(answer, dict):
            continue
        text = f"{answer.get('where') or ''} {answer.get('why') or ''}"
        for said in GAP_RE.finditer(text):
            рядом = text[said.start() : said.end() + GAP_WINDOW]
            for task in TASK_RE.finditer(рядом):
                pair = (str(number), int(task.group("number")))
                if pair not in found:
                    found.append(pair)
    return found


def gap_tasks_closed(repo: str, token: str, mine: dict[str, Any]) -> list[Drift]:
    """Ответ обещает пробел и называет задачу, а задача закрыта.

    ПОЧЕМУ ЭТО ДРЕЙФ, А НЕ ГЕЙТ. Задачу закрывают снаружи и в своё время; наша
    правка при этом ничего не делает, и события об этом не приходит. Ответ
    остаётся стоять и обещает читателю пробел, которого больше нет, — а
    счётчику машинного соблюдения занижает нашу же работу
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

    ЭТО ЗАМЕР, А НЕ ОПАСЕНИЕ. 13.09.2026 разбор пункта 5.1 нашёл ровно такую
    пару: ответ по 032 говорил «у роли этого пока нет — названо задачей #33», а
    #33 закрыта 09.09 вместе с починкой; тем же номером обещал пробел и ответ
    по 105. Обе — четвёртый случай одного класса за смену, и все четыре нашёл
    человек, а не механизм.

    ЗАКРЫТАЯ ЗАДАЧА САМА ПО СЕБЕ НЕ НАХОДКА. Ответы законно ссылаются на
    закрытые задачи как на ИСТОРИЮ — так в одиннадцати ссылках девять, — и
    судится здесь только соседство с утверждением о пробеле
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    found: list[Drift] = []
    for rule, number in gaps_naming_a_task(mine):
        # НЕРАЗРЕШИМЫЙ НОМЕР ГАСИТ ТОЛЬКО СВОЮ ПАРУ. Номера берутся из ПРОЗЫ, и
        # там попадается всё: чужой репозиторий, опечатка, номер, которого ещё
        # нет. Один такой ронял весь источник за заход — то есть молчание об
        # опечатке выглядело как «дрейфа нет» по всем остальным парам (045).
        try:
            task = ghrest.request("GET", f"repos/{repo}/issues/{number}", token) or {}
        except ghrest.TransportError as exc:
            print(f"::warning::#{number} из ответа по {rule} не прочитан: {report.cut(str(exc))}")
            continue
        state = str(task.get("state") or "")
        if state != "closed":
            continue
        found.append(
            Drift(
                f"gap-{rule}",
                f"ответ по правилу {rule} обещает пробел и называет #{number}, а она закрыта",
                "перечитать ответ: пробел либо закрыт вместе с задачей, либо назван не тем "
                "номером — читателю он обещан до сих пор",
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
        print(f"{report.DRY} {'обновил бы' if number else 'завёл бы'} задачу дрейфа")
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
    "набор вопросов витрины",
    "пробелы, названные задачей",
)


def look(repo: str, token: str, mine: dict[str, Any]) -> tuple[list[Drift], list[str]]:
    """Спрашивает все источники; отдаёт находки и имена тех, кто не ответил."""
    found: list[Drift] = []
    silent: list[str] = []
    asks: tuple[tuple[str, Any], ...] = (
        ("каталог", lambda: catalogue_moved(fetch(EXPORT_URL), mine)),
        (
            # ФЕТЧ ОДИН НА ОБА ВОПРОСА. Второе чтение того же адреса могло бы
            # прийти уже другим, и два вердикта разошлись бы молча (022) —
            # ровно та поломка, которую внешний взгляд нашёл в `build_facts`
            # на #240.
            "сводка семьи",
            lambda: family_summary(fetch(WHERE_URL), mine, str(mine.get("project") or repo)),
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
        (
            "набор вопросов витрины",
            lambda: showcase_questions_moved(fetch(CATALOGUE_SHOWCASE), ours_showcase()),
        ),
        ("пробелы, названные задачей", lambda: gap_tasks_closed(repo, token, mine)),
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
