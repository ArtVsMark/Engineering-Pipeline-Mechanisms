#!/usr/bin/env python3
"""Роды находок: что повторяется и чем это закрыто.

Находка разбирается поштучно и уходит из реестра вместе с починкой — а КЛАСС
ошибки остаётся и приходит снова под другим адресом. Третий случай одного рода
неотличим от первого, пока роды живут в памяти окна
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

ПОЧЕМУ РОД НАЗЫВАЕТ ЧЕЛОВЕК, А НЕ РАЗБОР. Классификатор пробовался и ОТВЕРГНУТ
замером 18.09.2026: из 73 находок на 60 слитых изменениях разбор по словам
опознал 21, по адресу файла — 32 при наибольшем повторе 4. Механизм на таком
признаке угадывал бы, а проверка, отвергающая верное, не держит ничего
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
Род называет тот, кто разобрал находку; здесь считаются повторы и проверяется
форма.

ВСТРЕЧА НАЗЫВАЕТ СВОЁ ПРОИСХОЖДЕНИЕ, и это не украшение счёта. Отпечаток —
находка внешнего взгляда: род ДОШЁЛ до общей ветки. Запись «окно: <адрес>» —
тот же род, пойманный собственным откатом до толчка. Совокупности разные, и
слитые в одно число они врут в обе стороны: до 18.09.2026 поле принимало только
отпечатки, то есть род, дважды пойманный в окне, выглядел встреченным ноль раз
и порога не достигал никогда.

К ПОРОГУ ИДУТ ОБЕ, А СОСТАВ ПЕЧАТАЕТСЯ. Порог отвечает на вопрос «род жив и не
держится ничем», а не «род проскочил ревью»: пойманный в окне стоит работы
каждый раз, и держит его дисциплина, то есть человек, — ровно то состояние,
которое правило 002 называет правилом без механизма. Но и уравнивать их нельзя:
род, встречаемый только в окне, до общей ветки не доходил ни разу, и это меняет
срочность, а не наличие долга. Поэтому счёт один, а состав виден.

ПРОШЛЫЕ ВСТРЕЧИ В ОКНЕ НЕ ВОССТАНАВЛИВАЮТСЯ. Их след живёт в памяти окна, а не
в дереве, и выписать их «по воспоминанию» значит вписать число, которого никто
не мерил
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
Счёт таких встреч начат днём, когда форма их приняла.

ЧТО СЧИТАЕТСЯ ДОЛГОМ. Род, встреченный **трижды и чаще** и не закрытый
механизмом, — вход в гейт или в предложение правила каталогу. Механизм его
НАЗЫВАЕТ и не краснеет: решение, строить ли гейт, остаётся человеку, а проверка,
краснеющая на законном, приучает себя обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

Исходы (правило 039): ``0`` роды названы · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

import findings
import paths

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Со скольких встреч род считается повторяющимся. Два — совпадение, три — ряд:
#: то же число, которым проект отделяет случай от повадки в разборе миганий.
REPEATED_AT: Final = 3
#: Слово, которым род говорит «механизма нет». Причина обязательна рядом (154).
NO_MECHANISM: Final = "нет"
#: Приставка встречи, пойманной в окне до толчка. Отпечатка у неё нет и быть не
#: может: находка внешнего взгляда живёт в реестре #23 и опознаётся хешем, а эта
#: до общей ветки не дошла. Вместо хеша — адрес места, где род себя показал.
IN_WINDOW: Final = "окно: "
#: Поле «что из рода ВЫРОСЛО»: заведённый гейт, предложенное правило, навык.
#: Отдельно от «чем закрыт»: род бывает закрыт чужим, давно стоявшим механизмом,
#: а бывает — тем, который из него и родился. Разница видна только если её
#: записать: иначе повторный род выглядит бесплодным, хотя из него вышло правило.
BORN: Final = "породил"
#: Поле ответа каталогу у рода, встреченного не реже порога (#650). Три вида, и
#: все названы: «предложено — <слаг из очереди>», «своё — <причина>», «есть —
#: <номер правила каталога>». Третий вид здесь нужнее, чем у записей решений:
#: повторяющийся класс ошибки чаще всего уже назван общим правилом, и ответ
#: «правило есть, мы его нарушали» — не молчание, а адрес.
CATALOGUE: Final = "каталогу"
FATE_RE: Final = re.compile(r"^(?P<kind>предложено|своё|есть)\s+—\s+(?P<said>\S.*)$")


class NotRun(RuntimeError):
    """Механизм не отработал: третий исход, а не «родов нет»."""


def kinds_in(text: str, where: str) -> dict[str, Any]:
    """Роды находок из текста словаря; раздела нет — пусто, не та форма — отказ.

    ОДИН РАЗБОР НА ДИСК И НА ИСТОРИЮ. План читает словарь с диска, гейт
    рождения правила — у базы и у головы через git, и прежде каждый разбирал
    сам: `dict(kinds)` над строкой или списком бросал `ValueError`, который
    ловил только один читатель из трёх (`19fe125`, `948f893`). Здесь любая
    чужая форма — `NotRun`, и её ловят все.
    """
    try:
        said = json.loads(text)
    except json.JSONDecodeError as exc:
        # Битый словарь — третий исход, а не падение читателя: гейт рождения
        # правила и план ловят `NotRun`, а сырой `JSONDecodeError` прошёл бы
        # мимо обоих. Нашёл внешний взгляд на #692 (`ff0aeef`).
        raise NotRun(f"{where} не разбирается: {exc}") from exc
    if not isinstance(said, dict):
        raise NotRun(f"{where}: словарь родов не объект JSON")
    kinds = said.get("kinds") or {}
    if not isinstance(kinds, dict):
        raise NotRun(f"{where}: раздел kinds не словарь, а {type(kinds).__name__}")
    return dict(kinds)


def read(path: Path | None = None) -> dict[str, Any]:
    """Объявленные роды находок."""
    where = path or paths.FINDING_KINDS
    if not where.is_file():
        raise NotRun(f"нет {where}: роды находок взять неоткуда (075)")
    try:
        text = where.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise NotRun(f"{where} не разбирается: {exc}") from exc
    kinds = kinds_in(text, str(where))
    if not kinds:
        raise NotRun(f"{where}: раздел kinds пуст — предмет счёта не найден (075)")
    return kinds


def queued(path: Path | None = None) -> str:
    """Очередь предложений одной строкой — в ней и ищется слаг.

    Ищется ВХОЖДЕНИЕМ, а не разбором поля: форму записи задаёт контракт
    КАТАЛОГА (`export/README.md`), а не мы, и свой разбор его полей разошёлся бы
    с ним молча — это уже случалось, когда набор искал вердикты под чужим ключом
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).

    ОЧЕРЕДИ НЕТ — ОТКАЗ, А НЕ ПУСТАЯ ОЧЕРЕДЬ, у гейта и у плана одинаково.
    План прежде читал отсутствующий файл как `""`, и каждый род с ответом
    «предложено» вставал строкой «без ответа», пока гейт в том же случае
    отказывал (`dd1da87`).
    """
    where = path or paths.PROPOSALS
    try:
        return where.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise NotRun(f"очередь предложений не прочитана ({where}): {exc}") from exc


def origins(body: dict[str, Any]) -> tuple[int, int]:
    """Состав встреч рода: сколько пришло взглядом, сколько поймано в окне.

    Считается СЛОЖЕНИЕМ из самих записей, а не вторым списком рядом: два списка
    одного разошлись бы молча
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    met = [str(one) for one in (body.get("встречен") or [])]
    in_window = sum(1 for one in met if one.startswith(IN_WINDOW))
    return len(met) - in_window, in_window


def said_no(held: str) -> bool:
    """Говорит ли поле «закрыт» слово «нет» — ЦЕЛЫМ словом, а не приставкой.

    `startswith("нет")` читает «нетронутый» и «нетривиально» как объявление
    отсутствия механизма: род с живым механизмом ушёл бы в долг по первой букве.
    «Нет-нет» в этот список НЕ входит — там первое слово и есть «нет», то есть
    отказ настоящий; разделитель слов здесь дефис, и разбор обязан его знать
    ([141](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/141-a-marker-is-matched-whole-not-by-prefix.md)).
    """
    first = re.split(r"[^\w]+", held.strip().lower(), maxsplit=1)[0]
    return first == NO_MECHANISM


def repeated(kinds: dict[str, Any]) -> list[tuple[str, int]]:
    """Роды, встреченные не реже :data:`REPEATED_AT` раз, — от частых к редким."""
    counted = [(name, len(body.get("встречен") or [])) for name, body in kinds.items()]
    return sorted(
        ((name, times) for name, times in counted if times >= REPEATED_AT),
        key=lambda one: (-one[1], one[0]),
    )


def unheld(kinds: dict[str, Any]) -> list[tuple[str, int]]:
    """Повторяющиеся роды, которые не закрыты механизмом, — это и есть долг."""
    return [
        (name, times)
        for name, times in repeated(kinds)
        if said_no(str(kinds[name].get("закрыт", "")))
    ]


def fate(body: dict[str, Any]) -> tuple[str, str] | None:
    """Ответ рода каталогу: вид и сказанное; ``None`` — ответа нет или он не по форме."""
    found = FATE_RE.match(str(body.get(CATALOGUE) or "").strip())
    return (found["kind"], found["said"].strip()) if found else None


#: Оформление вокруг слага: обратные кавычки, кавычки-ёлочки и знак конца
#: предложения. Снимается ДО сверки с очередью.
AROUND_SLUG: Final = "`\"'«».,;:()[]"
#: Номер правила каталога в ответе «есть»: три цифры первым словом.
RULE_NUMBER_RE: Final = re.compile(r"^\d{3}\b")


def slug_of(said: str) -> str:
    """Слаг из строки ответа — без оформления вокруг него.

    Живёт здесь, а не у гейта рождения правила: его зовут и записи решений, и
    роды находок, и план, — одна разборка на всех (022). История —
    прежней редакции гейта:

    ГЕЙТ СУДИТ СУЩЕСТВО, А НЕ РАЗМЕТКУ. Первое слово строки бралось целиком, и
    слаг, записанный в обратных кавычках — то есть ровно так, как имя пишут в
    документе этого проекта повсюду, — не сходился с очередью: гейт видел
    «`имя`.» и честного ответа не признавал. Красное на законном учит обходить
    красное
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Поймано 17.09.2026 на ПЕРВОЙ же записи с ответом «предложено» — до неё у
    этой ветки разбора не было живого предмета вовсе.
    """
    first = said.split()[0] if said.split() else ""
    return first.strip(AROUND_SLUG)


def answer_problem(body: dict[str, Any], queue: str) -> str | None:
    """Чем ответ рода каталогу не годится; ``None`` — годится.

    ОДНА ПРОВЕРКА ОТВЕТА НА ГЕЙТ И НА ПЛАН. Прежде гейт сверял слаг с очередью
    и номер правила, а план принимал любой ответ по форме — и род с
    неотправленным предложением из плана исчезал. Нашёл внешний взгляд на #692
    (`72397b3`).
    """
    said = fate(body)
    if said is None:
        return (
            f"поля «{CATALOGUE}» нет или оно не по форме: «предложено — <слаг>», "
            "«своё — <причина>» или «есть — <номер правила>»"
        )
    kind, what = said
    if kind == "предложено":
        slug = slug_of(what)
        if not slug or slug not in queue:
            return f"назван слаг «{slug}», а в очереди предложений ({paths.PROPOSALS}) его нет"
    if kind == "есть" and not RULE_NUMBER_RE.match(what):
        return "ответ «есть», а номера правила первым словом нет"
    return None


def unanswered(kinds: dict[str, Any], queue: str) -> list[tuple[str, int]]:
    """Повторяющиеся роды без ответа каталогу — поводы для правила без решения.

    ПОВОД ДЛЯ ПРАВИЛА РОЖДАЕТСЯ В ИНЦИДЕНТАХ, А ВОПРОС ЗАДАВАЛСЯ НАИТИЕМ (#650).
    У записей решений момент вопроса есть — гейт `check_rule_birth`; у класса
    ошибки, повторившегося трижды, его не было: род чинили, закрывали
    механизмом — и на этом всё. Замер 23.09.2026: родов у порога восемь, все
    держатся механизмами, и ни у одного нет ответа каталогу.
    """
    return [
        (name, times)
        for name, times in repeated(kinds)
        if answer_problem(kinds[name], queue) is not None
    ]


def in_archive(path: Path) -> tuple[dict[str, tuple[int, int, int]], str]:
    """Род → (находок рода в архиве, снято работой, снято дублем) и строка неполноты (#778).

    Род у находки архив берёт из этого же словаря (`встречен`), так что число
    здесь не второй счёт встреч, а их СУДЬБА: сколько из них в истории и чем
    они сняты. Дубль закрыт связью с другой находкой, а не работой, и в «снято
    работой» не входит (взгляд на #817). Вторым отдаётся строка архива о
    неполном наполнении: без неё счёт печатался бы как полный (045).
    """
    try:
        archive = findings.read_archive(path)
    except ValueError as exc:
        raise NotRun(str(exc)) from exc
    found: dict[str, tuple[int, int, int]] = {}
    for entry in (archive.get("findings") or {}).values():
        name = str(entry.get("род") or "")
        if not name:
            continue
        total, worked, twinned = found.get(name, (0, 0, 0))
        resolved = bool(entry.get("resolved_by"))
        twin = resolved and bool(entry.get("twin_of"))
        found[name] = (total + 1, worked + (resolved and not twin), twinned + twin)
    return found, findings.unfilled(archive)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает роды, повторы и долг."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kinds", default=None, help="объявление родов вместо дерева")
    parser.add_argument(
        "--archive", default=None, help="архив находок (findings.json): встречи рода в нём"
    )
    args = parser.parse_args(argv)
    try:
        kinds = read(Path(args.kinds) if args.kinds else None)
        archived, gap = in_archive(Path(args.archive)) if args.archive else ({}, "")
    except NotRun as refusal:
        print(f"роды не сосчитаны: {refusal}", file=sys.stderr)
        return EXIT_BROKEN

    meetings = sum(len(body.get("встречен") or []) for body in kinds.values())
    print(f"родов {len(kinds)}, встреч {meetings}")
    if gap:
        print(f"АРХИВ НЕПОЛОН: {gap} — числа архива ниже неполные")
    if archived and args.kinds:
        # Род в записи архива заморожен на момент сборки: другой словарь
        # родов сводит встречи иначе, и счёт с архивом расходится (взгляд на #817).
        print("роды архива — по словарю на момент его сборки, не по --kinds")
    for name, body in sorted(kinds.items(), key=lambda one: -len(one[1].get("встречен") or [])):
        times = len(body.get("встречен") or [])
        held = str(body.get("закрыт", "")).strip()
        mark = "—" if said_no(held) else "держится"
        born = [str(one) for one in (body.get(BORN) or [])]
        seen, caught = origins(body)
        split = f" (взгляд {seen}, окно {caught})" if caught else ""
        kept = archived.get(name)
        stored = f"  архив: {kept[0]}, снято работой {kept[1]}, дублем {kept[2]}" if kept else ""
        print(f"  {times:>2}  {name}{split}  [{mark}]{stored}")
        if born:
            print(f"      породил: {'; '.join(born)}")
    # РОД АРХИВА ВНЕ СЛОВАРЯ НЕ ВЫПАДАЕТ МОЛЧА: переименованный, снятый или
    # чужой по `--kinds` род иначе уменьшал бы сумму архива без слова (взгляд
    # на #817).
    for name in sorted(set(archived) - set(kinds)):
        total, worked, twinned = archived[name]
        print(
            f"  род архива вне словаря: {name} — архив: {total},"
            f" снято работой {worked}, дублем {twinned}"
        )

    debt = unheld(kinds)
    if not debt:
        print(f"\nповторяющихся родов без механизма нет (порог — {REPEATED_AT} встречи)")
        return EXIT_OK
    print(f"\nПОВТОРЯЕТСЯ И НЕ ДЕРЖИТСЯ НИЧЕМ (от {REPEATED_AT} встреч):")
    for name, times in debt:
        seen, caught = origins(kinds[name])
        split = f" (взгляд {seen}, окно {caught})" if caught else ""
        print(f"  {times}× {name}{split}")
        print(f"      {kinds[name].get('признак', '')}")
    print(
        "\nТакой род — вход в гейт или в предложение правила каталогу."
        "\nРешение за человеком: механизм называет величину и не краснеет (051)."
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — точка входа процессом
    raise SystemExit(main())
