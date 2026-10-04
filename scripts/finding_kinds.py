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

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

import changerefs
import findings
import paths
import trunk_log

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
#: Слово берётся у разбора тела коммита (`changerefs.WINDOW_WORD`), где ту же
#: встречу пишут строкой `Род:`: два написания одного слова разошлись бы молча
#: (022, #1022). Пробел после слова — часть формы словаря, а не слова.
IN_WINDOW: Final = f"{changerefs.WINDOW_WORD} "
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
    # Пустое имя — ключ записей архива без рода (`NO_KIND`), и родом словаря
    # быть не может: иначе записи без рода печатались бы дважды (взгляд на #830).
    if NO_KIND in kinds:
        raise NotRun(f"{where}: у рода пустое имя")
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


def twin_roots(record: changerefs.Resolution) -> list[tuple[str, frozenset[str]]]:
    """Встречи одного снятия: корень цепочки дублей и все её отпечатки.

    ОДНА ВСТРЕЧА НА КОРЕНЬ, А НЕ НА ОТПЕЧАТОК (#1022): дубль — один дефект,
    названный дважды, и «A дубль B» — одна встреча рода, «A дубль B, C дубль
    D» — две. Цепочки — компоненты связи `twin_of`; корень — отпечаток, у
    которого двойника нет, а у круга (`A дубль A`) — первый названный.
    """
    links = record.twin_of
    groups: dict[str, set[str]] = {mark: {mark} for mark in record.marks}
    for mark, twin in links.items():
        joined = groups[mark] | groups.get(twin, {twin})
        for one in joined:
            groups[one] = joined
    found: list[tuple[str, frozenset[str]]] = []
    for mark in record.marks:
        group = frozenset(groups[mark])
        if any(group == seen for _, seen in found):
            continue
        roots = [one for one in record.marks if one in group and one not in links]
        found.append((roots[0] if roots else mark, group))
    return found


def met_in_history(bodies: Iterable[str], kinds: dict[str, Any]) -> dict[str, list[str]]:
    """Род → встречи, названные строками `Род:` в телах слитых коммитов (#1022).

    ВСТРЕЧА ЕДЕТ С РАБОТОЙ, А НЕ ПРАВКОЙ СЛОВАРЯ. Прежде отпечаток дописывали в
    `встречен`, и конец одних и тех же списков правило почти каждое изменение:
    каждое слияние давало конфликт у всех открытых веток (замер 03.10.2026 —
    30 из 34 слитых изменений трогали словарь). Теперь встреча — строка
    `Род:` под снятием, и считает её одна функция для архива, плана и гейта
    рождения правила (022).

    ВТОРОЙ РАЗ НЕ СЧИТАЕТСЯ: цепочка, чей отпечаток уже стоит в `встречен`
    словаря или раньше в истории, — та же встреча; встреча в окне — та же
    пара «род, место». `Род: нет — <причина>` — ответ без рода, и встречей он
    не становится (154).
    """
    seen = {str(met).strip("`") for body in kinds.values() for met in body.get("встречен") or []}
    found: dict[str, list[str]] = {}
    for body in bodies:
        for record in changerefs.resolutions_parsed(body):
            if not record.kind or said_no(record.kind):
                continue
            for root, group in twin_roots(record):
                if group & seen:
                    continue
                seen |= group
                found.setdefault(record.kind, []).append(root)
        for meeting in changerefs.window_meetings_in(body):
            said = f"{IN_WINDOW}{meeting.place}"
            if said in found.get(meeting.kind, []) or said in seen:
                continue
            found.setdefault(meeting.kind, []).append(said)
    return found


def with_history(
    kinds: dict[str, Any], bodies: Iterable[str]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Словарь, у которого `встречен` — замороженный список плюс встречи истории.

    Вторым отдаются встречи родов, которых в словаре нет: опечатка имени или
    переименованный род не пропадают молча, а называются (045). Остальные
    читатели словаря — порог, долг, ответ каталогу — работают над первым без
    правок: число встреч у них по-прежнему длина `встречен`.
    """
    met = met_in_history(bodies, kinds)
    merged = {
        name: {**body, "встречен": [*(body.get("встречен") or []), *met.get(name, [])]}
        for name, body in kinds.items()
    }
    return merged, {name: one for name, one in met.items() if name not in kinds}


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


#: Начало отказа «ответы каталогу не прочитаны» — одной константой: тесты
#: сверяются с ней, а не с переписанными буквами (209, взгляд на #893).
ANSWERS_UNREAD: Final = "ответы каталогу не прочитаны"


def rule_numbers(text: str) -> frozenset[str]:
    """Номера правил из текста `.rules/bindings.json` — один разбор для тех, кому нужны номера.

    Его зовут план (с диска) и гейт рождения правила (у головы): два разбора
    одной формы разошлись бы при первой её смене (взгляд на #887, 214). Тем же
    разбором формы (`rule_answers`) читает сами ОТВЕТЫ `audit_profile` (#902);
    `drift` и `review_map` читают раздел своим путём — предел назван у
    `rule_answers` (взгляды на #893, поздний на #902, 195). Текст не разбирается, не объект, раздела
    `rules` нет или он не объект — `ValueError`, отказ называет зовущий.

    РАЗДЕЛА НЕТ — ОТКАЗ, А НЕ «НОМЕРОВ НЕТ» (045, взгляд на #899): `{}` иначе
    молча давал пустое множество, и опечатка номера в ответе «есть» не
    краснела бы ни в гейте, ни в плане. Пустой раздел `{"rules": {}}` —
    сказанное состояние «ответов нет», и он читается пустым.

    Разбор формы — `rule_answers`, общий с теми, кому нужны сами ответы.
    """
    return frozenset(str(number) for number in rule_answers(text))


def rule_answers(text: str) -> dict[str, Any]:
    """Раздел `rules` текста `.rules/bindings.json`; чужая форма — `ValueError`.

    Один разбор формы на всех, кто читает ответы НЕ из дерева: номера
    (`rule_numbers` — гейт у головы изменения и план по пути рядом с
    `--kinds`) и сами ответы (`audit_profile --answers` с любым путём, взгляд
    на #900). Раздела нет или он не объект — отказ, а не «ответов нет» (045).

    ПРЕДЕЛ НАЗВАН (195): `review_map.split`, `drift.catalogue_moved`,
    `drift.snapshot_is_stale` и `drift.gaps_naming_a_task` читают отсутствие
    раздела пустотой (`get("rules") or {}`). Оставлено намеренно: путь у них
    один — `paths.BINDINGS` дерева, а его форму держит `tests/test_bindings.py`
    (`load()["rules"]` падает на файле без раздела, и такое дерево не
    сольётся). Соседи названы функциями, а не номерами строк: номера сбились
    бы при первой правке (005, взгляд на #900).
    """
    said = json.loads(text)
    rules = said.get("rules") if isinstance(said, dict) else None
    if not isinstance(rules, dict):
        raise ValueError("ожидался объект с разделом rules")
    # Ответ читатели разбирают как объект (`answer.get`), и запись другой формы
    # падала у них трассой (взгляд на #902).
    if not all(isinstance(one, dict) for one in rules.values()):
        raise ValueError("ответ в разделе rules — не объект")
    return rules


def known_rules(path: Path | None = None) -> frozenset[str]:
    """Номера правил каталога, на которые проект отвечает, — из `.rules/bindings.json`.

    Файла нет или он не читается — пустое множество не выдаётся за «номеров
    нет»: это отказ (045).
    """
    where = path or paths.BINDINGS
    try:
        return rule_numbers(where.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotRun(f"{ANSWERS_UNREAD} ({where}): {exc}") from exc


def answer_problem(
    body: dict[str, Any], queue: str, known: frozenset[str] | None = None
) -> str | None:
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
    if kind != "есть":
        return None
    found = RULE_NUMBER_RE.match(what)
    if found is None:
        return "ответ «есть», а номера правила первым словом нет"
    # Номер — из совпадения образца, а не срезом его ширины, и сверяется с
    # ответами каталогу: опечатка «211» вместо «212» иначе прошла бы зелёной
    # (взгляд на #887).
    number = found.group(0)
    if known is not None and number not in known:
        return f"ответ «есть — {number}», а правила {number} в {paths.BINDINGS} нет"
    return None


def unanswered(
    kinds: dict[str, Any], queue: str, known: frozenset[str] | None = None
) -> list[tuple[str, int]]:
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
        if answer_problem(kinds[name], queue, known) is not None
    ]


#: Ключ записей архива без рода. Пустой намеренно: пустое имя родом словаря
#: быть не может, и записи без рода не сольются с настоящим родом, как слились
#: бы под словами «без рода» (взгляд на #822).
NO_KIND: Final = ""
#: Начала строк счёта архива: тест отличает запись без рода от рода вне
#: словаря по ним, а не по переписанным буквам (взгляд на #830, 209).
OUTSIDE: Final = "род архива вне словаря:"
KINDLESS: Final = "записей архива без рода:"
#: Строка о встречах, пришедших строками `Род:` из истории (#1022).
HISTORY_SAID: Final = "из них строками «Род:» истории"
#: Начало строки о слияниях без уплотнения: их строк `Род:` история не отдаёт.
UNSEEN_SAID: Final = "слияний без уплотнения, чьих строк «Род:» счёт не видит:"
#: Начало строки о роде, названном в истории, но не объявленном в словаре.
OUTSIDE_HISTORY: Final = "род истории вне словаря:"
#: Хвост строки замера дублей: тест узнаёт её по нему, а не по буквам (209).
TWIN_SHARE: Final = "от разобранных"
#: Сколько изменений отрезка архив учёл — первым числом строки замера: отрезок,
#: покрытый частично (`855-8900`), иначе читался бы целиком (взгляд на #897).
SPAN_SEEN: Final = "учтено изменений"
#: Форма отрезка `--twins`: её называет отказ на чужой записи.
SPAN_FORM: Final = "ПЕРВЫЙ-ПОСЛЕДНИЙ"
#: Отказ на перевёрнутом отрезке: тест отличает его от отказа по форме (209).
SPAN_INVERTED: Final = "первый номер больше последнего"


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
        # Запись без рода не выпадает молча, а считается под пустым ключом и
        # печатается своей строкой (взгляд на #822).
        name = str(entry.get("род") or "") or NO_KIND
        total, worked, twinned = found.get(name, (0, 0, 0))
        resolved = bool(entry.get("resolved_by"))
        twin = resolved and bool(entry.get("twin_of"))
        found[name] = (total + 1, worked + (resolved and not twin), twinned + twin)
    return found, findings.unfilled(archive)


def span(text: str) -> tuple[int, int]:
    """Отрезок `--twins` из записи `ПЕРВЫЙ-ПОСЛЕДНИЙ`; чужая форма — `ValueError` с формой.

    Перевёрнутый отрезок — отказ, а не «находок 0»: пустой ответ на опечатку
    читался бы замером (взгляд на #891).
    """
    first, dash, final = text.partition("-")
    if not (dash and first.isdecimal() and final.isdecimal()):
        raise ValueError(f"отрезок «{text}» не по форме {SPAN_FORM}, например 855-890")
    if int(first) > int(final):
        raise ValueError(f"отрезок «{text}» перевёрнут: {SPAN_INVERTED}")
    return int(first), int(final)


def twins_between(path: Path, first: int, final: int) -> tuple[tuple[int, int, int, int, int], str]:
    """Отрезок `first`–`final`: (учтено изменений, находок, разобрано, проверкой починки, дублем).

    Вторым отдаётся строка о неполноте архива.

    Замер #859 командой, а не разовым сценарием окна (005): доля дублей
    считается от РАЗОБРАННЫХ — неразобранная находка дублем ещё не снята и
    нулём не свидетельствует (взгляд на #891). Архив читается тем же
    `findings.read_archive`, что у `in_archive`, и строка о неполном
    наполнении отдаётся так же: без неё ноль дублей выглядел бы полным
    счётом (045, взгляд на #891).

    ОТРЕЗОК, КОТОРОГО АРХИВ НЕ УЧЁЛ, — ОТКАЗ, а не «находок 0»: опечатка
    `8550-8900` или ещё не слитый отрезок иначе печатали бы ноль замером.
    Так же отказывает соседний `finding_chains` (045, взгляд на #895).
    Отрезок, покрытый ЧАСТИЧНО, не отказ — но число учтённых в нём изменений
    отдаётся первым и печатается, как у `finding_chains` (взгляд на #897).
    """
    try:
        archive = findings.read_archive(path)
    except ValueError as exc:
        raise NotRun(str(exc)) from exc
    solved = archive.get("resolutions")
    solved = {} if solved is None else solved
    if not isinstance(solved, dict) or not all(isinstance(one, dict) for one in solved.values()):
        raise NotRun("`resolutions` в архиве — не словарь записей")
    seen = len({number for number in archive.get("counted") or [] if first <= number <= final})
    if not seen:
        raise NotRun(findings.NONE_COUNTED)
    marks = [
        mark
        for mark, one in (archive.get("findings") or {}).items()
        if first <= int(one.get("pr") or 0) <= final
    ]
    done = [mark for mark in marks if mark in solved]
    checked = sum(1 for mark in done if solved[mark].get("fix_check"))
    twins = sum(1 for mark in done if solved[mark].get("twin_of"))
    return (seen, len(marks), len(done), checked, twins), findings.unfilled(archive)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает роды, повторы и долг."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kinds", default=None, help="объявление родов вместо дерева")
    parser.add_argument(
        "--archive", default=None, help="архив находок (findings.json): встречи рода в нём"
    )
    parser.add_argument(
        "--trunk",
        default=trunk_log.TRUNK_REF,
        help="чья история несёт встречи строками «Род:» (#1022); по умолчанию — общая ветка",
    )
    parser.add_argument(
        "--twins",
        default="",
        metavar=SPAN_FORM,
        help="доля дублей среди находок отрезка изменений по архиву (#859)",
    )
    args = parser.parse_args(argv)
    if args.twins:
        if not args.archive:
            print("доля дублей считается по архиву: нужен --archive", file=sys.stderr)
            return EXIT_BROKEN
        try:
            first, final = span(args.twins)
            counts, gap = twins_between(Path(args.archive), first, final)
        except (NotRun, ValueError) as refusal:
            print(f"доля дублей не сосчитана: {refusal}", file=sys.stderr)
            return EXIT_BROKEN
        if gap:
            print(f"{findings.UNFILLED_SAID} {gap} — числа архива ниже неполные")
        seen, total, done, checked, twins = counts
        share = f"{twins / done:.0%}" if done else "—"
        print(
            f"#{first}–#{final}: {SPAN_SEEN} {seen}, находок {total}, разобрано {done} "
            f"(проверкой починки {checked}), дублем {twins} — {share} {TWIN_SHARE}"
        )
        return EXIT_OK
    try:
        frozen = read(Path(args.kinds) if args.kinds else None)
        kinds, outside = with_history(frozen, trunk_log.merged_bodies(ref=args.trunk))
        unseen = trunk_log.unseen(ref=args.trunk)
        archived, gap = in_archive(Path(args.archive)) if args.archive else ({}, "")
    except (NotRun, trunk_log.NotRun) as refusal:
        print(f"роды не сосчитаны: {refusal}", file=sys.stderr)
        return EXIT_BROKEN

    meetings = sum(len(body.get("встречен") or []) for body in kinds.values())
    told = meetings - sum(len(body.get("встречен") or []) for body in frozen.values())
    print(f"родов {len(kinds)}, встреч {meetings} ({HISTORY_SAID} {args.trunk} — {told})")
    # РОД ИСТОРИИ ВНЕ СЛОВАРЯ НЕ ВЫПАДАЕТ МОЛЧА: опечатка в строке `Род:` иначе
    # уносила бы встречу из счёта без слова (045).
    for name in sorted(outside):
        print(f"  {OUTSIDE_HISTORY} {name} — встреч {len(outside[name])}")
    if unseen:
        print(f"  {UNSEEN_SAID} {unseen}")
    if gap:
        print(f"{findings.UNFILLED_SAID} {gap} — числа архива ниже неполные")
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
    for name in sorted(set(archived) - set(kinds) - {NO_KIND}):
        total, worked, twinned = archived[name]
        print(f"  {OUTSIDE} {name} — архив: {total}, снято работой {worked}, дублем {twinned}")
    # ЗАПИСИ БЕЗ РОДА — СВОЕЙ СТРОКОЙ: рода у них нет вовсе, и «вне словаря»
    # назвало бы другую причину — переименованный или снятый род.
    if NO_KIND in archived:
        total, worked, twinned = archived[NO_KIND]
        print(f"  {KINDLESS} {total} — снято работой {worked}, дублем {twinned}")

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
