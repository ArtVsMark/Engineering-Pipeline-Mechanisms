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
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import family
import paths
import pipeline_checks as policy
import version

VERSION_FILE: Final = paths.VERSION
BINDINGS: Final = paths.BINDINGS
FACTS: Final = "facts.json"
#: Значки ветки `badges`: имя файла → как его собрать. Списком, а не тремя
#: вызовами подряд: добавить значок должно быть правкой данных, а не кода (049).
BADGE: Final = "rules.svg"
FAMILY_BADGE: Final = "family.svg"
VERSION_BADGE: Final = "version.svg"
RELEASE_BADGE: Final = "release.svg"

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


def checks_facts(path: Path = policy.DEFAULT_PATH) -> dict[str, int]:
    """Считает классы проверок из ответа проекта — по ОБОИМ разделам.

    Факты публикуются наружу и говорят о конвейере целиком, а не о его половине
    на изменении. Умолчание у `names_of` — первый раздел, и без явного «из
    любого» число совещательных здесь молча занизилось бы на десять: ровно на
    те прогоны, которые второй раздел и завёл. Нашёл внешний взгляд на #155 —
    на том же изменении, которое умолчание и ввело.
    """
    try:
        checks = policy.load(path)
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc
    return {klass: len(policy.names_of(checks, klass, beyond=None)) for klass in policy.CLASSES}


def family_facts(path: Path | None) -> dict[str, Any]:
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
        picture = family.picture(family.load(path))
    except family.NotRun as exc:
        return {"read": False, "why": str(exc)}
    # Форма чужая: её подъём — повод перечитать разрез, а не подвинуть число
    # (157). Расхождение называется рядом с числами, а не прячется.
    picture["read"] = True
    picture["schema_expected"] = family.READS_SCHEMA
    picture["schema_agrees"] = picture["schema_read"] == family.READS_SCHEMA
    return picture


def test_counts(root: Path) -> dict[str, int]:
    """Сколько тестов и тестовых модулей в наборе.

    Считается ПО ДЕРЕВУ, а не прогоном: прогон даёт то же число дороже и не в
    том месте. Тест узнаётся по объявлению `def test_`; второго счётчика той же
    территории не заводится (022).
    """
    modules = sorted((root / "tests").glob("test_*.py"))
    total = 0
    for path in modules:
        lines = path.read_text(encoding="utf-8").splitlines()
        total += sum(1 for line in lines if line.startswith("def test_"))
    return {"total": total, "modules": len(modules)}


def collect(root: Path, sha: str, summary: Path | None = None) -> dict[str, Any]:
    """Собирает все факты о проекте в одно отображение."""
    # ВЕРСИЯ ПРОЕКТА И ВЕРСИЯ КОНТРАКТА — РАЗНЫЕ ЧИСЛА, И ОБА НУЖНЫ. Контракт
    # объявляет поверхность механизмов и поднимается решением человека; версия
    # проекта СЧИТАЕТСЯ по истории — «столько изменений принято после выпуска».
    # Свести их в одно значило бы либо скрыть работу, либо объявить выпуском
    # каждое изменение (035).
    number, whole = version.version()
    return {
        "schema": 1,
        "contract": contract_version(root / VERSION_FILE),
        "version": number,
        # Неполнота названа рядом с числом, а не выброшена: клон без тегов даёт
        # правдоподобное число, которое ложь (045).
        "version_whole": whole,
        # ВЫПУСК И ВЕРСИЯ ГОЛОВЫ — РАЗНЫЕ ЧИСЛА. Голова уходит вперёд каждым
        # изменением, потребитель живёт на выпущенном; одно вместо другого
        # обещало бы ему то, чего он не получал.
        "release": version.release_tag() or "",
        # Числа для вопросов СОПРОВОЖДАЮЩЕГО из .rules/showcase.json: значок им
        # не нужен и вреден — они дёргаются от каждого изменения, — но живой
        # адрес обязателен, и вот он (049).
        "tests": test_counts(root),
        "rules": rules_facts(root / BINDINGS),
        "checks": checks_facts(root / policy.DEFAULT_PATH),
        "family": family_facts(summary),
        "generated": {
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha": sha,
        },
    }


def badge(label: str, value: str, color: str) -> str:
    """Рисует значок сам, без обращения к чужой службе.

    Значок с чужого сервиса — это внешняя зависимость витрины: она отвалится
    молча и оставит вместо числа пустое место, которое читается как «всё в
    порядке». Здесь SVG собирается из своих же чисел и лежит рядом с ними.
    """
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


#: Роды ответа, означающие «держит машина». Тот же состав, что у разреза семьи
#: и у дрейфа: три понимания одного слова разошлись бы молча (090).
MACHINE: Final = frozenset({"gate", "pipeline", "code"})


def rules_badge(facts: dict[str, Any]) -> str:
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


def family_badge(facts: dict[str, Any]) -> str:
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


def release_badge(facts: dict[str, Any]) -> str:
    """Последний выпуск: то, к чему потребитель прибивается тегом.

    Версия головы и выпуск — РАЗНЫЕ числа, и оба нужны: голова уходит вперёд
    каждым изменением, а потребитель живёт на выпущенном. Показывать одно
    вместо другого значило бы обещать ему то, чего он не получал.

    Выпусков ещё не было — сказано словом: пустой значок и «не выпускался»
    снаружи одинаковы (045).
    """
    said = str(facts.get("release") or "")
    return badge("выпуск", said, "#4c1") if said else badge("выпуск", "не выпускался", "#9f9f9f")


def version_badge(facts: dict[str, Any]) -> str:
    """Версия проекта: она СЧИТАЕТСЯ по истории, и значок показывает счёт.

    Неполнота названа цветом и словом: клон без тегов даёт правдоподобное
    число, которое ложь, и молчать об этом нельзя (045).
    """
    number = str(facts.get("version") or "?")
    whole = bool(facts.get("version_whole"))
    said = number if whole else f"{number} (неполно)"
    return badge("версия", said, "#4c1" if whole else "#dfb317")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает факты и значок в каталог вывода."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="корень дерева, откуда читаются источники")
    parser.add_argument("--out-dir", required=True, help="куда положить производное")
    parser.add_argument("--sha", default="", help="голова, на которой собрано")
    parser.add_argument("--family", default="", help="сводка каталога export/where.json")
    args = parser.parse_args(argv)

    try:
        facts = collect(Path(args.root), args.sha, Path(args.family) if args.family else None)
    except NotRun as exc:
        print(f"факты не собраны: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / FACTS).write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", "utf-8")
    for name, draw in (
        (BADGE, rules_badge),
        (FAMILY_BADGE, family_badge),
        (VERSION_BADGE, version_badge),
        (RELEASE_BADGE, release_badge),
    ):
        (out / name).write_text(draw(facts) + "\n", encoding="utf-8")

    rules = facts["rules"]
    print(
        f"собрано: контракт {facts['contract']}, "
        f"правил {rules['answered']} из {rules['total']}, "
        f"проверок обязательных {facts['checks']['required']}"
    )
    kin = facts["family"]
    if kin.get("read"):
        print(
            f"общих механизмов семьи: {kin['shared']} из {kin['mechanisms']}, "
            f"они держат {kin['closed_by_shared']} правил из {kin['held_by_machine']} "
            f"({kin['share']:.0%} машинного соблюдения)"
        )
    else:
        print(f"сводка семьи: {kin['why']}", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
