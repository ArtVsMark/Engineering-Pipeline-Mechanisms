#!/usr/bin/env python3
"""Семейный значок: проект сам сверяет, что он отдаёт и что берёт, со свежими версиями семьи.

ПЕРЕЕХАЛО ИЗ КАТАЛОГА (#1563, этап 3 ArtVsMark/Engineering-Incidents-Playbook#930).
Ответ тот же, опоры свои: форма манифеста — `family_contract`, картинка —
`python_badge.picture`, обращения `uses:` — общий разбор YAML
`pipeline_checks.run_of`, диапазон `contract:` — `pipeline_checks.span_said` и
`span_bounds`, полный SHA — `drift.HASH_RE`, последний выпуск дерева —
`version.release_tag`, сводка по адресу — `ghrest.raw_json`. Второй разбор
той же формы был бы вторым её пониманием
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md),
[214](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/214-one-territory-one-parse.md)).

СЕГМЕНТЫ, И У КАЖДОГО СВОЙ ЦВЕТ:
  gives    — отдаю: свой манифест против опубликованного в сводке и против
             последнего выпуска дерева; у проекта без манифеста — серый;
  family   — беру у семьи: прибитые `uses: <издатель>/…@<ссылка>` в прогонах и
             действиях, номер ответа `.rules/bindings.json` (`schema`,
             `answers_to`), номер фактов `.github/badges/facts.json`, диапазон
             `contract:` в `.pipeline.yml` против `steps` механизмов;
  pairs    — беру парно: связи `takes` своего манифеста;
  external — внешний мир по СВОИМ фактам: метка исполнителя `…-latest` в
             `python.os` отстаёт — ОС сменится без изменения в дереве.

ЦВЕТ. Семья и пары: любое отставание — красный, минор тоже: выпуск минора у
издателя и есть смена контракта. Нечего сверять или не прочитано — серый
(039): серый в зелёный не засчитывается.

ДИАПАЗОН ШАГОВ — НАШЕЙ ФОРМЫ. У каталога диапазон разбирался своим образцом и
допускал любые условия; здесь — тем же `span_bounds`, что судит ответ
потребителя: `>=X.Y,<A.B` с обязательной верхней границей (073). Иная форма —
серый с причиной: такой ответ не примет и сам конвейер.

ГРАНИЦА: ссылка `@<sha>` сверяется только на равенство с коммитом последнего
выпуска — SHA старого выпуска отсюда не отличить от произвольного коммита, и он
идёт в «отстаёт», а не в «неизвестно».

Исходы:
  0 — значок и разбор записаны (какого бы цвета ни был значок);
  2 — не записаны: сводка семьи не прочитана либо не той формы.
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import build_facts
import catalogue
import drift
import family_contract
import family_uptake
import ghrest
import paths
import pipeline_checks
import python_badge
import version

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Дерево проекта — рабочий каталог, как у прочих механизмов (096).
ROOT: Final = Path()
#: Сводка семьи по умолчанию — там, где её публикует каталог.
SUMMARY_URL: Final = f"{catalogue.RAW}/badges/export/family.json"
SVG: Final = paths.BADGES_DIR / "family.svg"
VERDICT: Final = paths.BADGES_DIR / "family-check.json"
FACTS: Final = paths.BADGES_DIR / build_facts.FACTS
ANSWER: Final = paths.BINDINGS
PIPELINE: Final = paths.PIPELINE

#: Значение `uses:` с чужим репозиторием: `владелец/репозиторий[/путь]@ссылка`.
USES_RE: Final = re.compile(r"^([\w.-]+)/([\w.-]+)(?:/[^@\s]*)?@(\S+)$")

SEGMENTS: Final = ("gives", "family", "pairs", "external")
SEGMENT_LABEL: Final = {"gives": "gives", "family": "family", "pairs": "pairs", "external": "ext"}
#: Состояние → цвет и знак (вариант Б, решение владельца 09.10). `none` — связи
#: с издателем нет и отказ не объявлен: красный; `skipped` — отказ объявлен с
#: причиной: серый; `partial` — у механизмов шаги взяты, а конвейер не подключён.
COLOR: Final = {
    "ok": "#1a7f37",
    "behind": "#cf222e",
    "unknown": "#6e7781",
    "none": "#cf222e",
    "skipped": "#6e7781",
    "partial": "#6e7781",
}
SIGN: Final = {
    "ok": "✓",
    "behind": "✗",
    "unknown": "?",
    "none": "—",
    "skipped": "·",
    "partial": "◐",
}

#: Издатели контрактов семьи и их короткие имена на значке. Список закрытый и
#: с причиной (068): правила, ответы и договор фактов (каталог), шаги конвейера
#: (механизмы). Парный издатель (глоссарий) сюда не входит: его связь видна в
#: сегменте `pairs`.
PUBLISHERS: Final = {catalogue.REPO: "EIP", family_uptake.OURS: "EPM"}
#: Чем издатель узнаётся в сводке, когда его имя разошлось с умолчанием:
#: механизмы — тот, кто отдаёт `steps`.
PUBLISHER_MARK: Final = {"EPM": "steps"}
#: Переезд договора фактов (каталог #843): мажор 1 у витрины и мажор 2 —
#: одна форма. Номер 1.x при договоре 2.x — подъём, который ждёт читателя:
#: серый с причиной, а не красный (051).
FACTS_MOVE: Final = ("1", "2")
#: Номер версии в теге или номере контракта: `v1.10.0`, `facts-v1.5.0`, `1.9`.
NUMBER_RE: Final = re.compile(r"(\d+(?:\.\d+)*)$")
#: Плавающая метка исполнителя: площадка сама решает, какая ОС под ней.
FLOATING_RE: Final = re.compile(r"-latest$")
#: Состояния связи, при которых проект на издателя перешёл: связь есть, свежая,
#: отставшая, частичная или с несверенной свежестью. `none` и `skipped` — нет.
TAKEN: Final = frozenset({"ok", "behind", "partial", "unknown"})


@dataclass(frozen=True)
class Link:
    """Одна сверка: что, у кого, что держу я, что свежее, где это лежит."""

    segment: str
    publisher: str
    what: str
    mine: str | None
    latest: str | None
    where: str
    state: str  # ok · behind · unknown
    why: str = ""


def number(said: str) -> tuple[int, ...] | None:
    """Числа версии для сравнения; None — не версия (SHA, ветка)."""
    found = NUMBER_RE.search(said)
    # не проза: номер версии, разрез по точке.
    return tuple(int(piece) for piece in found[1].split(".")) if found else None


def compare(
    segment: str,
    publisher: str,
    what: str,
    mine: object,
    latest: object,
    where: str,
    sha: object = None,
) -> Link:
    """Одна связь: равенство — ok; нет стороны — unknown; моё старше — behind.

    Моё НОВЕЕ свежего — unknown (каталог, обзор #807): опережение значит, что
    сводка отстала от издателя, а не что отстал я.

    НЕ СТРОКА — НЕ ТА ФОРМА, А НЕ ТРАССА (взгляд на #1567). Номер числом в
    дереве (`"schema": 2`) или в сводке ронял сравнение в `TypeError`, а
    обещаны исходы 0 и 2: такая связь серая с названной причиной (039).
    """
    strange = [
        f"{side} «{said}»"
        for side, said in (("у себя", mine), ("у издателя", latest))
        if said is not None and not isinstance(said, str)
    ]
    mine = mine if isinstance(mine, str) else None
    latest = latest if isinstance(latest, str) else None
    if strange:
        why = f"{', '.join(strange)} не строка — не та форма, сверять нечего"
        return Link(segment, publisher, what, mine, latest, where, "unknown", why)
    sha = sha if isinstance(sha, str) else None
    if mine is None or latest is None:
        why = "у издателя не опубликовано" if latest is None else "у себя не найдено"
        return Link(segment, publisher, what, mine, latest, where, "unknown", why)
    if mine == latest or (sha is not None and mine == sha):
        return Link(segment, publisher, what, mine, latest, where, "ok")
    if drift.HASH_RE.match(mine):
        return Link(
            segment,
            publisher,
            what,
            mine,
            latest,
            where,
            "behind",
            "прибит не к последнему выпуску",
        )
    own, fresh = number(mine), number(latest)
    if own is not None and fresh is not None and own > fresh:
        return Link(
            segment,
            publisher,
            what,
            mine,
            latest,
            where,
            "unknown",
            "опережает опубликованное — сводка отстала от издателя",
        )
    return Link(segment, publisher, what, mine, latest, where, "behind")


def compare_facts(mine: str | None, latest: str | None) -> Link:
    """Номер своих фактов против договора; переезд 1 → 2 — серый с причиной."""
    link = compare("family", catalogue.REPO, "facts", mine, latest, str(FACTS))
    # не проза: номер версии «мажор.минор».
    majors = (str(mine).split(".")[0], str(latest).split(".")[0])
    if link.state == "behind" and majors == FACTS_MOVE:
        return Link(
            **{
                **asdict(link),
                "state": "unknown",
                "why": "договор фактов 2.0 той же формы: подъём номера ждёт, "
                "пока витрина читает мажор 2 (каталог #845)",
            }
        )
    return link


def published(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Опубликованные манифесты сводки по имени проекта в нижнем регистре."""
    return {
        one["repo"].lower(): one
        for one in summary.get("projects", [])
        if isinstance(one, dict)
        and isinstance(one.get("repo"), str)
        and one.get("state") == "published"
    }


def known(summary: dict[str, Any]) -> set[str]:
    """Имена всех проектов сводки в нижнем регистре — прочитанных и нет.

    Запись без строкового `repo` — не проект (взгляд на #1567): сводка —
    чужие данные, и её запись не той формы не роняет разбор `KeyError`.
    """
    return {
        one["repo"].lower()
        for one in summary.get("projects", [])
        if isinstance(one, dict) and isinstance(one.get("repo"), str)
    }


def claimants(summary: dict[str, Any], contract: str) -> list[str]:
    """Проекты сводки, отдающие контракт, — все, а не первый (каталог #473)."""
    return sorted(
        str(one["repo"])
        for one in published(summary).values()
        if contract in (one.get("gives") or {})
    )


def family_publishers(summary: dict[str, Any]) -> dict[str, str]:
    """`владелец/имя` → код издателя; переименованного узнаёт по контракту.

    Претендента нет или их два и больше — остаётся имя по умолчанию: выбрать
    роль первым совпадением значило бы решить молча. Спор виден связью
    `publisher` (`publisher_disputes`).
    """
    out = dict(PUBLISHERS)
    for code, contract in PUBLISHER_MARK.items():
        who = claimants(summary, contract)
        if len(who) == 1:
            out = {repo: one for repo, one in out.items() if one != code} | {who[0]: code}
    return out


def publisher_disputes(summary: dict[str, Any]) -> list[Link]:
    """Контракт роли отдают несколько проектов — серая связь с их именами."""
    out = []
    for code, contract in PUBLISHER_MARK.items():
        if len(who := claimants(summary, contract)) > 1:
            out.append(
                Link(
                    "family",
                    code,
                    "publisher",
                    None,
                    None,
                    "сводка семьи",
                    "unknown",
                    f"контракт {contract} отдают {len(who)}: {', '.join(who)} — "
                    f"издатель {code} не выбран",
                )
            )
    return out


def _uses_of(document: dict[Any, Any]) -> Iterator[str]:
    """Значения `uses:` прогона или действия: работы, их шаги, шаги действия."""
    jobs = document.get("jobs")
    bodies = list(jobs.values()) if isinstance(jobs, dict) else []
    runs = document.get("runs")
    if isinstance(runs, dict):
        bodies.append(runs)
    for body in bodies:
        if not isinstance(body, dict):
            continue
        if isinstance(body.get("uses"), str):
            yield body["uses"]
        steps = body.get("steps")
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                yield step["uses"]


def pinned(root: Path) -> tuple[list[tuple[str, str, str]], list[str]]:
    """(владелец/репозиторий, ссылка, файл) каждого чужого `uses:`; и неразобранные файлы.

    Файл, который не разбирается, — не «связей нет», а «не прочитано»:
    вызывающий называет его серой связью с причиной (039).
    """
    files = [
        *sorted((root / paths.WORKFLOWS).glob("*.y*ml")),
        *sorted((root / paths.ACTIONS).glob("*/action.y*ml")),
    ]
    found: list[tuple[str, str, str]] = []
    refused: list[str] = []
    for path in files:
        where = str(path.relative_to(root))
        try:
            document = pipeline_checks.run_of(path)
        except pipeline_checks.BadPolicy as exc:
            refused.append(f"{where}: {exc}")
            continue
        for said in _uses_of(document):
            if match := USES_RE.match(said.strip()):
                found.append((f"{match[1]}/{match[2]}", match[3], where))
    return found, refused


def _json(path: Path) -> Any:
    """Документ JSON с диска; None — файла нет или он не разбирается."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


def family_links(root: Path, summary: dict[str, Any], own: str) -> list[Link]:
    """Что проект берёт у семьи — найдено в его дереве."""
    known_ones, publishers = known(summary), published(summary)
    links: list[Link] = []
    pins, refused = pinned(root)
    for repo, ref, where in pins:
        key = repo.lower()
        if key == own.lower() or key not in known_ones:
            continue  # своё и чужое вне семьи — не здесь
        release = (publishers.get(key) or {}).get("release") or {}
        # Выпуск не объектом — не опубликован, а не `AttributeError` (взгляд на #1567).
        if not isinstance(release, dict):
            release = {}
        links.append(
            compare("family", repo, "release", ref, release.get("tag"), where, release.get("sha"))
        )
    for why in refused:
        links.append(Link("family", "?", "uses", None, None, why.split(":")[0], "unknown", why))
    eip = (publishers.get(catalogue.REPO.lower()) or {}).get("gives") or {}
    # Файл не объект — не та форма: сверять нечего, а не падение.
    if isinstance(answer := _json(root / ANSWER), dict):
        links.append(
            compare(
                "family",
                catalogue.REPO,
                "bindings",
                answer.get("schema"),
                eip.get("bindings"),
                str(ANSWER),
            )
        )
        links.append(
            compare(
                "family",
                catalogue.REPO,
                "export",
                answer.get("answers_to"),
                eip.get("export"),
                str(ANSWER),
            )
        )
    if isinstance(facts := _json(root / FACTS), dict):
        links.append(compare_facts(facts.get("schema"), eip.get("facts")))
    return links + steps_links(root, summary)


def steps_links(root: Path, summary: dict[str, Any]) -> list[Link]:
    """Диапазон контракта шагов проекта против `steps` механизмов.

    Нет `.pipeline.yml` — связи нет; диапазон не объявлен или не нашей формы,
    номер не опубликован, спор о роли — серый с причиной; свежий в диапазоне —
    сходится; ниже нижней границы — серый (сводка отстала); иначе — отстаёт.
    """
    path = root / PIPELINE
    if not path.is_file():
        return []  # шагов механизмов не берёт
    who = next((repo for repo, code in family_publishers(summary).items() if code == "EPM"), "EPM")
    where = f"{PIPELINE}:contract"

    def grey(declared: str | None, why: str) -> list[Link]:
        return [Link("family", who, "steps", declared, None, where, "unknown", why)]

    try:
        text = pipeline_checks.file_text(path, "ответ проекта")
    except pipeline_checks.BadPolicy as exc:
        return grey(None, str(exc))
    declared = pipeline_checks.span_said(text)
    if declared is None:
        return grey(None, "диапазон контракта шагов не объявлен или ответ не разбирается")
    try:
        low, high = pipeline_checks.span_bounds(declared)
    except pipeline_checks.BadPolicy:
        return grey(declared, "диапазон не той формы: ждётся >=X.Y,<A.B")
    if len(claimants(summary, PUBLISHER_MARK["EPM"])) > 1:
        return grey(declared, "контракт steps отдают несколько проектов — сверять не с кем")
    fresh = ((published(summary).get(who.lower()) or {}).get("gives") or {}).get("steps")
    digits = number(fresh) if isinstance(fresh, str) else None
    if digits is None or len(digits) < 2:
        return grey(declared, "у издателя не опубликовано")
    now = (digits[0], digits[1])
    if low <= now < high:
        return [Link("family", who, "steps", declared, fresh, where, "ok")]
    if now < low:
        return [
            Link(
                "family",
                who,
                "steps",
                declared,
                fresh,
                where,
                "unknown",
                "диапазон опережает опубликованное — сводка отстала от издателя",
            )
        ]
    return [
        Link(
            "family",
            who,
            "steps",
            declared,
            fresh,
            where,
            "behind",
            "свежий контракт шагов вне объявленного диапазона",
        )
    ]


def external_links(root: Path) -> tuple[list[Link], str]:
    """Метки исполнителей из своих фактов: (связи, причина пустоты).

    Судятся данные фактов, а не дерево заново: `python.os` уже собран из
    `runs-on` генератором фактов, и второй разбор прогонов разошёлся бы с ним.
    """
    facts = _json(root / FACTS)
    if facts is None:
        return [], f"фактов нет: {FACTS} не прочитан"
    python = facts.get("python") if isinstance(facts, dict) else None
    labels = python.get("os") if isinstance(python, dict) else None
    if not isinstance(labels, list) or not labels:
        return [], "в фактах нет python.os — меток исполнителей"
    if not all(isinstance(label, str) for label in labels):
        return [], "python.os не той формы: метка исполнителя не строка"
    where = f"{FACTS}:python.os"
    links = []
    for label in labels:
        if FLOATING_RE.search(label):
            links.append(
                Link(
                    "external",
                    "runner",
                    label,
                    label,
                    None,
                    where,
                    "behind",
                    "плавающая метка: ОС сменится без изменения в дереве",
                )
            )
        else:
            links.append(Link("external", "runner", label, label, label, where, "ok"))
    return links, ""


def pair_links(root: Path, summary: dict[str, Any], manifest: Any) -> list[Link]:
    """Парные связи, объявленные в `takes` своего манифеста."""
    publishers = published(summary)
    links = []
    takes = manifest.get("takes", []) if isinstance(manifest, dict) else []
    for one in takes if isinstance(takes, list) else []:
        if not isinstance(one, dict) or not all(
            isinstance(one.get(key), str) for key in ("from", "contract", "where", "field")
        ):
            # Неполная запись — данные, а не падение (каталог, обзор #807).
            source = str(one.get("from", "?")) if isinstance(one, dict) else "?"
            links.append(
                Link(
                    "pairs",
                    source,
                    "takes",
                    None,
                    None,
                    str(family_contract.MANIFEST),
                    "unknown",
                    "запись takes неполна: нужны from, contract, where, field",
                )
            )
            continue
        said = _json(root / one["where"])
        mine = said.get(one["field"]) if isinstance(said, dict) else None
        latest = ((publishers.get(one["from"].lower()) or {}).get("gives") or {}).get(
            one["contract"]
        )
        links.append(
            compare(
                "pairs",
                one["from"],
                one["contract"],
                mine,
                latest,
                f"{one['where']}:{one['field']}",
            )
        )
    return links


def gives_links(root: Path, summary: dict[str, Any], own: str, manifest: Any) -> list[Link]:
    """Манифест издателя: той ли формы, называет ли последний выпуск, дошёл ли до сводки.

    РАСХОЖДЕНИЕ С ОПУБЛИКОВАННЫМ — СЕРОЕ (каталог, обзоры #807, #808): сводка
    собрана ночью, а манифест — сейчас, и разошлись они — значит, сводка ещё не
    перечитала манифест; это не отставание проекта.
    """
    if manifest is None:
        return []  # не издатель — сегмент серый
    where = str(family_contract.MANIFEST)
    release = manifest.get("release") if isinstance(manifest, dict) else None
    tag = release.get("tag") if isinstance(release, dict) else None
    links = [compare("gives", own, "release", tag, version.release_tag(root), where)]
    flaw = family_contract.form_flaw(manifest)
    schema = manifest.get("schema") if isinstance(manifest, dict) else None
    links.append(
        Link(
            "gives",
            own,
            "form",
            schema,
            family_contract.FAMILY_SCHEMA,
            where,
            "behind" if flaw else "ok",
            flaw or "",
        )
    )
    there = published(summary).get(own.lower())
    if there is None:
        links.append(
            Link(
                "gives",
                own,
                "published",
                None,
                "yes",
                "сводка семьи",
                "unknown",
                "манифеста нет в сводке семьи",
            )
        )
        return links
    gives = manifest.get("gives") if isinstance(manifest, dict) else None
    for contract, said in sorted((gives if isinstance(gives, dict) else {}).items()):
        theirs = (there.get("gives") or {}).get(contract)
        same = theirs == said
        links.append(
            Link(
                "gives",
                own,
                contract,
                said,
                theirs,
                "сводка семьи",
                "ok" if same else "unknown",
                "" if same else "сводка ещё не перечитала манифест",
            )
        )
    return links


def verdict(links: list[Link]) -> str:
    """Цвет сегмента: отстаёт хоть одна — красный; неизвестна или сверять нечего — серый."""
    if any(one.state == "behind" for one in links):
        return "behind"
    if not links or any(one.state == "unknown" for one in links):
        return "unknown"
    return "ok"


def skip_flaws(manifest: Any, publishers: dict[str, str], links: list[Link]) -> list[Link]:
    """Отказы `skips`, которые молча не работали бы (каталог, обзор #809).

    Ключ вне списка издателей — опечатка; отказ при живой связи — противоречие.
    """
    out = []
    codes = {code.lower(): repo for repo, code in publishers.items()}
    names = {repo.lower(): repo for repo in publishers}
    skips = manifest.get("skips") if isinstance(manifest, dict) else None
    for key, _why in (skips if isinstance(skips, dict) else {}).items():
        repo = codes.get(str(key).lower()) or names.get(str(key).lower())
        if repo is None:
            out.append(
                Link(
                    "gives",
                    str(key),
                    "skips",
                    str(key),
                    None,
                    str(family_contract.MANIFEST),
                    "behind",
                    f"отказ от «{key}», а такого издателя нет: "
                    f"{', '.join(sorted(publishers.values()))}",
                )
            )
        elif any(one.publisher.lower() == repo.lower() for one in links):
            out.append(
                Link(
                    "gives",
                    repo,
                    "skips",
                    "отказ",
                    "связь есть",
                    str(family_contract.MANIFEST),
                    "behind",
                    f"отказ от {key} объявлен, а связь с ним в дереве есть",
                )
            )
    return out


def lag(own_links: list[dict[str, Any]]) -> str:
    """Подсказка издателя: одно отставание — одна строка, с числом связей и файлами.

    Повтор читался как вторая беда (каталог, 21.10): два шага на одном старом
    выпуске давали две одинаковые строки рядом с `family ✗2`. Число связей
    остаётся, но названо один раз и с адресом, где поднимать.
    """
    groups: dict[tuple[str, str, str], list[str]] = {}
    for one in own_links:
        if one["state"] != "ok":
            key = (str(one["what"]), str(one["mine"]), str(one["latest"]))
            groups.setdefault(key, []).append(str(one["where"]))
    parts = []
    for (what, was, now), where in groups.items():
        files = ", ".join(sorted(set(where)))
        count = f"связей {len(where)}, " if len(where) > 1 else ""
        parts.append(f"{what}: {was} → {now} ({count}{files})")
    return "; ".join(parts)


def by_publisher(
    analysis: dict[str, Any],
    own: str,
    manifest: Any,
    publishers: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Состояние связи проекта с каждым издателем семьи (решение владельца 09.10).

    Связи — из сегментов `family` и `pairs`. Нет ни одной — красный `—`, если
    отказ не объявлен в `skips` с причиной; объявлен — серый с этой причиной.
    Свой издатель показывает состояние сегмента `gives`. У механизмов
    «подключён» — это конвейер, а не пин (14.10): без связи `steps` свежие
    пины — частичная связь `◐`; отставший пин остаётся `✗`.
    """
    raw = manifest.get("skips") if isinstance(manifest, dict) else None
    skips = {
        str(key).lower(): str(why) for key, why in (raw if isinstance(raw, dict) else {}).items()
    }
    links = [one for name in ("family", "pairs") for one in analysis["segments"][name]["links"]]
    out = []
    for repo, code in (publishers or PUBLISHERS).items():
        if repo.lower() == own.lower():
            out.append(
                {
                    "code": code,
                    "repo": repo,
                    "state": analysis["segments"]["gives"]["state"],
                    "why": "свой: состояние отдачи",
                }
            )
            continue
        theirs = [one for one in links if one["publisher"].lower() == repo.lower()]
        why = skips.get(code.lower()) or skips.get(repo.lower())
        if not theirs:
            out.append(
                {
                    "code": code,
                    "repo": repo,
                    "state": "skipped" if why else "none",
                    "why": why or "связи с издателем нет и отказ не объявлен",
                }
            )
            continue
        state = verdict([Link(**one) for one in theirs])
        if (
            code == "EPM"
            and state != "behind"
            and not any(one["what"] == "steps" for one in theirs)
        ):
            count = sum(one["what"] == "release" for one in theirs)
            out.append(
                {
                    "code": code,
                    "repo": repo,
                    "state": "partial",
                    "why": f"связей с механизмами {count}, конвейер не подключён "
                    "(.pipeline.yml нет)",
                }
            )
            continue
        out.append({"code": code, "repo": repo, "state": state, "why": lag(theirs)})
    return out


def uptake(summary: dict[str, Any], own: str, publishers: dict[str, str]) -> dict[str, Any] | None:
    """Сколько проектов семьи перешли на издателя `own` (каталог #844).

    Только у издателя. Считается по полю `links` сводки — тому, что каждый
    проект опубликовал о своих связях. Проект без `links` — не прочитан: в
    «перешли» не идёт, но и «не перешёл» о нём не утверждается (039).
    """
    code = next((one for repo, one in publishers.items() if repo.lower() == own.lower()), None)
    if code is None:
        return None
    others = [
        one
        for one in summary.get("projects", [])
        if isinstance(one, dict) and str(one.get("repo", "")).lower() != own.lower()
    ]
    read = [one for one in others if isinstance(one.get("links"), dict)]
    took = sorted(str(one["repo"]) for one in read if one["links"].get(code) in TAKEN)
    return {
        "code": code,
        "taken": len(took),
        "of": len(others),
        "unread": len(others) - len(read),
        "by": took,
    }


def analyse(root: Path, summary: dict[str, Any], own: str) -> dict[str, Any]:
    """Разбор по сегментам: состояние и связи, из которых оно сложилось."""
    manifest = _json(root / family_contract.MANIFEST)
    publishers = family_publishers(summary)
    outside = external_links(root)
    by_segment = {
        "gives": gives_links(root, summary, own, manifest),
        "family": family_links(root, summary, own) + publisher_disputes(summary),
        "pairs": pair_links(root, summary, manifest),
        "external": outside[0],
    }
    by_segment["gives"] += skip_flaws(
        manifest, publishers, by_segment["family"] + by_segment["pairs"]
    )
    reasons = {
        "gives": "манифеста нет — проект не издатель" if manifest is None else "",
        "pairs": "парных связей не объявлено",
        "external": outside[1],
    }
    analysis: dict[str, Any] = {
        "schema": family_contract.FAMILY_SCHEMA,
        "project": own,
        "segments": {
            name: {
                "state": verdict(by_segment[name]),
                "why": reasons.get(name, "") if not by_segment[name] else "",
                "links": [asdict(one) for one in by_segment[name]],
            }
            for name in SEGMENTS
        },
    }
    analysis["publishers"] = by_publisher(analysis, own, manifest, publishers)
    if (taken := uptake(summary, own, publishers)) is not None:
        analysis["uptake"] = taken
    return analysis


def caption(segment: str, said: dict[str, Any]) -> str:
    """`family ✗2`: имя сегмента, знак состояния и число отстающих связей."""
    behind = sum(one["state"] == "behind" for one in said["links"])
    tail = str(behind) if said["state"] == "behind" else ""
    return f"{SEGMENT_LABEL[segment]} {SIGN[said['state']]}{tail}"


def uptake_zone(taken: dict[str, Any]) -> list[python_badge.Part]:
    """`uptake │ 3/5`: сколько проектов семьи перешли на этого издателя."""
    why = f"перешли на {taken['code']}: {', '.join(taken['by']) or 'никто'}" + (
        f"; не прочитано у {taken['unread']}" if taken["unread"] else ""
    )
    color = COLOR["unknown"] if taken["unread"] == taken["of"] else python_badge.BLUE
    return [
        ("uptake", python_badge.LABEL, ""),
        (f"{taken['taken']}/{taken['of']}", color, why),
    ]


def zones(analysis: dict[str, Any]) -> list[list[python_badge.Part]]:
    """Зоны семейного значка: подпись, сегменты, издатели, переход на издателя."""
    out = [
        [("family", python_badge.LABEL, "")],
        [
            (caption(name, said), COLOR[said["state"]], said["why"] or said["state"])
            for name, said in analysis["segments"].items()
        ],
        [
            (f"{one['code']} {SIGN[one['state']]}", COLOR[one["state"]], one["why"] or one["state"])
            for one in analysis["publishers"]
        ],
    ]
    if (taken := analysis.get("uptake")) is not None:
        out.append(uptake_zone(taken))
    return out


def badge(analysis: dict[str, Any]) -> str:
    """Картинка значка — общей функцией значков (214)."""
    return python_badge.picture(zones(analysis))


#: ФОРМА ЗАПИСИ СВОДКИ — ВСЕ ПОЛЯ, КОТОРЫЕ МОДУЛЬ ЧИТАЕТ, И ИХ ТИП (#1567).
#: Две находки подряд по одному месту — форме чужой записи — чинились по
#: одному полю (`repo`, потом `release`), и третье, `gives`, осталось открытым
#: (правило 210). Теперь запись разбирается на входе целиком: поле не той
#: формы снимается с предупреждением, и читатели ниже видят только законную
#: форму либо отсутствие поля, у которого исход уже есть («не опубликовано»).
RECORD_FORM: Final = {
    "repo": str,
    "state": str,
    "release": dict,
    "gives": dict,
    "links": dict,
}


def formed(projects: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Записи сводки в форме `RECORD_FORM` и названные отказы формы.

    Запись не словарь или без строкового `repo` — не проект: имени, по
    которому её сверять, нет. Прочее поле не той формы снимается: отсутствие
    у каждого читателя уже значит «не опубликовано», а не падение.
    """
    kept: list[dict[str, Any]] = []
    refused: list[str] = []
    for n, one in enumerate(projects):
        if not isinstance(one, dict) or not isinstance(one.get("repo"), str):
            refused.append(f"запись {n} — без строкового repo, не проект")
            continue
        clean = dict(one)
        for field, kind in RECORD_FORM.items():
            if field in clean and clean[field] is not None and not isinstance(clean[field], kind):
                refused.append(f"{one['repo']}: поле {field} не {kind.__name__} — снято")
                del clean[field]
            elif isinstance(clean.get(field), dict):
                # ВЛОЖЕННОЕ ТОЖЕ (взгляд на #1576, третья находка по месту): у
                # словарных полей значения — строки (`links` — состояние связи,
                # `gives` — номер контракта, `release` — тег и коммит). Иное
                # снимается: `links: {"EPM": ["ok"]}` ронял `uptake` в TypeError.
                inner = {key: said for key, said in clean[field].items() if isinstance(said, str)}
                for key in sorted(set(clean[field]) - set(inner), key=str):
                    refused.append(f"{one['repo']}: {field}.{key} не строка — снято")
                clean[field] = inner
        kept.append(clean)
    return kept, refused


def read_summary(
    source: str, fetch: Callable[[str], dict[str, Any]] = ghrest.raw_json
) -> tuple[dict[str, Any] | None, str]:
    """Сводка семьи по адресу или пути; (сводка, беда).

    Записи приходят разобранными по `RECORD_FORM`: отказы формы печатаются
    предупреждением, а не роняют разбор (039).
    """
    if source.startswith("https://"):
        try:
            doc: Any = fetch(source)
        except ghrest.TransportError as exc:
            return None, f"сводка семьи {source}: {exc}"
    else:
        doc = _json(Path(source))
        if doc is None:
            return None, f"сводка семьи {source}: не прочитан файл"
    if not isinstance(doc, dict) or not isinstance(doc.get("projects"), list):
        return None, f"сводка семьи {source}: нет списка projects"
    projects, refused = formed(doc["projects"])
    for why in refused:
        print(f"::warning::сводка семьи {source}: {why}", file=sys.stderr)
    return {**doc, "projects": projects}, ""


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверить дерево с семьёй, записать значок и разбор рядом."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--family", default=SUMMARY_URL, help="адрес или путь сводки семьи")
    # ИМЯ ПРОЕКТА — ЕГО, А НЕ НАШЕ (взгляд на #1567). Умолчанием стояло имя
    # механизмов, и сосед без `--repo` сверял бы себя как поставщика. Теперь
    # имя берётся у площадки (`GITHUB_REPOSITORY`), а без неё — отказ.
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="владелец/имя проекта; по умолчанию GITHUB_REPOSITORY",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"куда положить SVG (по умолчанию {SVG} под --root); "
        f"разбор {VERDICT.name} ложится рядом с ним",
    )
    args = parser.parse_args(argv)
    if not args.repo:
        print(
            "значок не собран: проект не назван — нет ни --repo, ни GITHUB_REPOSITORY",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    summary, trouble = read_summary(args.family)
    if summary is None:
        print(f"значок не собран: {trouble}", file=sys.stderr)
        return EXIT_BROKEN
    analysis = analyse(args.root, summary, args.repo)
    svg = args.out or args.root / SVG
    family_contract.write(svg.with_name(VERDICT.name), analysis)
    svg.write_text(badge(analysis), encoding="utf-8")
    print(
        "издатели: "
        + " ".join(f"{one['code']} {SIGN[one['state']]}" for one in analysis["publishers"])
    )
    for name, said in analysis["segments"].items():
        print(caption(name, said) + (f" — {said['why']}" if said["why"] else ""))
        for one in said["links"]:
            if one["state"] != "ok":
                print(
                    f"  · {one['publisher']} {one['what']}: у себя {one['mine']}, "
                    f"свежее {one['latest']} ({one['where']}) {one['why']}".rstrip()
                )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
