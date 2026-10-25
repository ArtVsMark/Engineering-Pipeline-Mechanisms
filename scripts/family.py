#!/usr/bin/env python3
"""Мерило общих механизмов: сколько правил семьи держится гейтом НАШЕГО происхождения.

ПОЧЕМУ ЭТО ОТДЕЛЬНАЯ ОСЬ. Порядок переноса в эпике выведен из размера кода и
расхождения копий — это цена выноса. Но у выноса есть и вторая сторона: сколько
машинного соблюдения он приносит с собой. Оси разные и дают разный порядок:
транспорт по строкам первый, а по числу закрываемых правил — шестой. Ни одна из
них не отменяет другую, но вторая до сих пор была не видна.

ВТОРОГО СБОРЩИКА НЕ ЗАВОДИТСЯ. Данные уже собраны каталогом: `export/where.json`
несёт по каждому потребителю ключ `holds` — правило → вид механизма и его адрес.
Читать `.rules/bindings.json` пяти проектов заново не нужно и не следует: два
сборщика одних данных разошлись бы молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Здесь только разрез над готовым.

СЧИТАЮТСЯ МЕХАНИЗМЫ, А НЕ ДОКУМЕНТЫ, И ЭТО НЕ ПРИДИРКА. Без фильтра по виду
топ забивают `CLAUDE.md`, `README.md` и `bindings.json`; на 10.09.2026 это 80
правил у пятерых, 25 и 20 соответственно. Формально они механизмы в ответах
каталога
(`mechanism: document`), фактически — текст, который выносить некуда: сводка со
всеми видами показывает не механизмы, а объём документации.

ПРОИСХОЖДЕНИЕ ОБЪЯВЛЯЕТ ПОТРЕБИТЕЛЬ, А НЕ УГАДЫВАЕТ РАЗРЕЗ (решение
владельца 07.10.2026, #1199). Прежде механизм считался «общим» по совпадению
имени файла у двух проектов — и засчитывал в общие пять РАЗНЫХ `ci.yml` и
разошедшиеся копии, то есть ровно расхождение, ради устранения которого проект
заведён. С формы сводки 1.6 запись держания несёт `origin` и `origin_kind`,
объявленные самим потребителем; правило держится гейтом нашего происхождения,
если `origin` ведёт в наш репозиторий. Совпадение имён снято совсем — ни
числом, ни полем фактов. Угадывание копий по содержимому отвергнуто: порог
сходства назначался бы рукой.

ЧИСЛО НЕ РЕШАЕТ ЗА ЧЕЛОВЕКА. Механизм, держащий одно правило, бывает
необходим; держащий восемнадцать — оставаться домашним, если правила про
предмет одного проекта.
"""

import json
from pathlib import Path
from typing import Any, Final

import family_uptake
import kinds

#: Виды, которые считаются механизмом, — из общего места (`scripts/kinds.py`).
#: Своё имя для того же набора было ЧЕТВЁРТОЙ копией и вторым именем разом.
KINDS: Final = kinds.MACHINE
#: Версия сводки каталога, под которую написан этот разрез. Подъём — повод
#: перечитать разрез, а не подвинуть число
#: ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).
#:
#: ПЕРЕЧИТАНО 17.09.2026 ПОД 1.3. Подъём принёс ровно одно: в словарь
#: механизмов сводки добавлен `skill`. Для разреза это значит, что у соседа
#: может встретиться вид, которого в `kinds.MACHINE` нет, — и не должно быть:
#: навык не краснеет, и общим механизмом он не считается. Разрез не меняется,
#: и это ВЫВОД перечитывания, а не отказ от него.
#:
#: ЧТО ПРИНЁС ПОДЪЁМ 1.1 → 1.2, перечитано тем же заходом: у среза появился
#: ключ `findings` — находки каталога о НАШЕМ ответе. Дыра была названа здесь и
#: ЗАКРЫТА 17.09.2026: находки доезжают до реестра дрейфа
#: (`scripts/drift.py::catalogue_found`).
#:
#: ПЕРЕЧИТАНО 17.09.2026 ПОД 1.4, И ВЫВОД ЗДЕСЬ НЕ «РАЗРЕЗ НЕ МЕНЯЕТСЯ». Подъём
#: принёс у среза два поля: `trails` — сколько правил каталога называют след у
#: этого потребителя, `born` — сколько правил у него РОДИЛОСЬ. Разрезу они не
#: нужны: он отвечает «чем держится семья», а это вопрос о механизмах, тогда как
#: оба поля — о происхождении правил. Но у них нет читателя ВООБЩЕ, и это дыра,
#: а не отсутствие предмета: замер 17.09.2026 по живой сводке — у нас `born` = 8
#: и `trails` = 9, у грейдера 132 и 187. Восемь правил каталога родились здесь, и
#: проект об этом числе не говорит нигде. Адрес, где оно должно стоять, назван:
#: `scripts/build_facts.py` собирает факты проекта и уже читает эту же сводку
#: ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
#:
#: ПОДЪЁМ 1.3 → 1.4 У ИЗДАТЕЛЯ НЕ ЗАПИСАН. Его `scripts/aggregate_bindings.py`
#: ведёт историю формы комментарием и называет, что принесли 1.1, 1.2 и 1.3;
#: на 1.4 запись обрывается, хотя тот же комментарий собственным доводом требует
#: обратного — «состав полей изменился, и молчание об этом сделало бы номер
#: бесполезным». Что принесло 1.4, здесь установлено ЧТЕНИЕМ ЕГО КОДА, а не
#: объявлением, и это стоило захода.
#:
#: ПЕРЕЧИТАНО 26.09.2026 ПОД 1.5 (дрейф #193). Подъём принёс у записи держания
#: поле `skill` — адрес навыка, как его назвал ответ потребителя; навык плагина
#: каталога издатель сверяет со своим деревом сам. ИСТОЧНИК — издатель, а не
#: догадка: запись журнала каталога `changelog.d/summary-carries-skill.added.md`
#: («Сводка „где действует“ 1.4 → 1.5: запись держания несёт `skill`») и
#: `SUMMARY_SCHEMA = "1.5"` в его `scripts/aggregate_bindings.py`, прочитанные
#: на `main` каталога 26.09.2026 (взгляд на #886).
#:
#: ЧИСЛО ОТВЕЧАЕТ ЗА ВСЕХ ЧИТАТЕЛЕЙ СВОДКИ, и их перечень — `SUMMARY_READERS`
#: ниже, а не абзац: рукописный перечень потерял четвёртого читателя в первый же
#: день (взгляд на #888, 005). Его сверяет с деревом
#: `tests/test_family.py::test_every_summary_reader_is_declared`. Под 1.5
#: перечитаны все: этот разрез; `build_facts` (тот же `load`); в `drift`
#: `snapshot_is_stale` (у записи держания — только `mechanism`) и
#: `catalogue_found` (раздел `findings`, 1.5 его не трогал); `family_uptake`
#: (только `consumers[].repo`). Подъём следующей формы перечитывает всех.
#:
#: Разрез читает у записи только
#: `mechanism` и `where` и только у машинных видов (`kinds.MACHINE`), а навык в
#: них не входит и общим механизмом не считается (см. выше, 1.3). Разрез не
#: меняется. ДЫРА НАЗВАНА (046): кто из семьи держит правила навыком плагина,
#: здесь не читает никто — число печатает сам издатель рядом с разобранностью.
#:
#: ПЕРЕЧИТАНО 08.10.2026 ПОД 1.6 (дрейф #193, #1199). Подъём принёс у записи
#: держания `origin` и `origin_kind` — откуда механизм взят и как: вызван,
#: скопирован, переделан (журнал каталога v1.7.0, #701 каталога). Разрез их
#: ЧИТАЕТ: `adopted` считает правила семьи, держащиеся гейтом нашего
#: происхождения. Остальные читатели перечитаны: `build_facts` — тем же `load`;
#: `drift` — только `mechanism` и `findings`; `family_uptake` — только
#: `consumers[].repo`. Им подъём ничего не меняет.
#:
#: ПЕРЕЧИТАНО 09.10.2026 ПОД 1.7 (дрейф #193, #1274). Подъём прибавил раздел
#: `notes` — заметки и замеры проектов по правилам — и у ответов 1.9 слово
#: `origin_kind: own` без `origin`. `adopted` считает по `origin`, ведущему к
#: нам: `own` без адреса в него не входит, то есть «разработан здесь» у соседа
#: нашим не засчитывается. Прочие читатели тех полей не трогают.
#:
#: С 14.10.2026 РАЗРЕЗ ЧИТАЕТ `notes` (решение владельца, #1274): «не ломается
#: на разделе» для 1.7 мало — мысль соседа о правиле и его замер и есть то,
#: ради чего раздел заведён. `notes` собирает их поимённо, без своих.
READS_SCHEMA: Final = "1.7"
#: Модули, читающие сводку семьи: через `family.load` или по адресу
#: `catalogue.WHERE_URL`. Перечень, а не счёт в прозе — его держит тест.
SUMMARY_READERS: Final = frozenset(
    {"family", "build_facts", "drift", "family_uptake", "family_gates"}
)


class NotRun(RuntimeError):
    """Разрез не отработал: третий исход, а не «нашего никто не взял»."""


#: Наш адрес в объявлении происхождения: `<владелец>/<репо>:<путь>@<версия>`.
#: Одно место на оба мерила — то же имя ищет обход клонов (022).
OURS_ORIGIN: Final = f"{family_uptake.OURS}:"


def load(path: Path) -> dict[str, Any]:
    """Читает сводку каталога, отвергая любой дефект входа."""
    if not path.is_file():
        raise NotRun(f"сводки семьи нет: {path} — считать нечего (075)")
    try:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        # ГЛУБЖЕ ПРЕДЕЛА РАЗБОРЩИКА — ТОЖЕ «НЕ РАЗБИРАЕТСЯ» (находки `88edc0f`,
        # `9846074`): C-разборщик JSON бросает `RecursionError` на вложенности
        # в сотни тысяч уровней, и он проходил мимо `NotRun`, роняя сборку
        # фактов целиком вместо «read: False». Нечитаемый файл и чужая
        # кодировка (`OSError`, `UnicodeDecodeError`) — тот же третий исход.
        raise NotRun(f"{path} не разбирается: {exc!r}") from exc
    if not document.get("consumers"):
        raise NotRun(f"{path}: в сводке нет ни одного потребителя — предмет не найден (075)")
    return document


def schema_of(summary: dict[str, Any]) -> str:
    """Версия формы сводки — как её объявил каталог."""
    return str(summary.get("schema") or "")


def adopted(summary: dict[str, Any], *, mine: str = "") -> dict[str, Any]:
    """Правила семьи, держащиеся гейтом НАШЕГО происхождения, из всех машинных.

    Считается по объявлению потребителя (`origin`), а не по совпадению имён:
    имя `ci.yml` у пяти проектов — пять разных файлов. Свои ответы не
    считаются — мерило о семье, а не о нас. Поимённо — кем и что взято.
    """
    by: list[dict[str, str]] = []
    total = 0
    for consumer in summary.get("consumers") or []:
        repo = str(consumer.get("repo") or "")
        if repo.casefold() == (mine or family_uptake.OURS).casefold():
            continue
        for number, answer in sorted((consumer.get("holds") or {}).items()):
            if not isinstance(answer, dict) or answer.get("mechanism") not in KINDS:
                continue
            total += 1
            origin = str(answer.get("origin") or "")
            # Площадка имена репозиториев различает без регистра: объявленное
            # строчными — тоже наше, а не ноль без слова (взгляд на #1241).
            if origin.casefold().startswith(OURS_ORIGIN.casefold()):
                kind = str(answer.get("origin_kind") or "")
                by.append({"repo": repo, "rule": str(number), "origin": origin, "kind": kind})
    return {"ours": len(by), "of": total, "by": by}


#: Как взят механизм — по объявлению потребителя (`origin_kind`, #701 каталога).
#: «Взяты» — без переделки, вызовом или копией; «переделаны» — под себя
#: (решение владельца 12.10.2026, #1325). `own` нашим не бывает: у него нет адреса.
TAKEN_KINDS: Final = ("called", "copied")
ADAPTED_KIND: Final = "adapted"
#: Порядок, в котором пара с разными объявлениями у разных правил получает одно
#: слово: дальше от нашего кода — сильнее. Переделка у одного правила делает
#: переделанным весь механизм у проекта, а не половину его.
KIND_ORDER: Final = (ADAPTED_KIND, "copied", "called")
#: Слово пары, у которой ни одно правило не сказало, как механизм взят.
UNDECLARED: Final = "undeclared"


def unversioned(origin: str) -> str:
    """Адрес механизма без `@версии`: одна пара — один механизм, на каком бы теге он ни был."""
    return origin.rsplit("@", 1)[0] if "@" in origin else origin


def origins(summary: dict[str, Any], *, mine: str = "") -> dict[str, Any]:
    """Механизмы НАШЕГО происхождения у семьи — парами «проект × механизм» (#1325).

    РЕШЕНИЕ ВЛАДЕЛЬЦА 12.10.2026. Единица — пара: один наш механизм у двух
    проектов — два взятия, механизм, держащий у проекта два правила, — одно.
    `adopted` считает ответы по правилам и на этот вопрос не отвечает.

    Пара без слова о том, как взята (`origin_kind` нет или он не из
    известных), — «не объявлено», а не ноль в «взяты» (045). Знаменатель
    проектов — потребители сводки без нас: мерило о семье.

    МЕХАНИЗМ — МАШИННЫЙ ОТВЕТ, КАК У `adopted` (взгляд на #1346): документ с
    нашим `origin` механизмом не держится, и в «проектов N/M» он не входит.
    Два разреза одной сводки читают одно множество видов (`KINDS`).
    """
    me = (mine or family_uptake.OURS).casefold()
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    family_size = 0
    for consumer in summary.get("consumers") or []:
        repo = str(consumer.get("repo") or "")
        if repo.casefold() == me:
            continue
        family_size += 1
        for number, answer in sorted((consumer.get("holds") or {}).items()):
            if not isinstance(answer, dict) or answer.get("mechanism") not in KINDS:
                continue
            origin = str(answer.get("origin") or "")
            if not origin.casefold().startswith(OURS_ORIGIN.casefold()):
                continue
            mechanism = unversioned(origin)
            pair = pairs.setdefault(
                (repo, mechanism.casefold()),
                {"repo": repo, "mechanism": mechanism, "kinds": set(), "rules": []},
            )
            pair["kinds"].add(str(answer.get("origin_kind") or ""))
            pair["rules"].append(str(number))
    by = [
        {
            "repo": pair["repo"],
            "mechanism": pair["mechanism"],
            "kind": next((one for one in KIND_ORDER if one in pair["kinds"]), UNDECLARED),
            "rules": pair["rules"],
        }
        for pair in pairs.values()
    ]
    by.sort(key=lambda one: (one["repo"].casefold(), one["mechanism"].casefold()))
    count = {kind: sum(1 for one in by if one["kind"] == kind) for kind in KIND_ORDER}
    return {
        "pairs": len(by),
        "taken": sum(count[kind] for kind in TAKEN_KINDS),
        "adapted": count[ADAPTED_KIND],
        "by_kind": count,
        "undeclared": sum(1 for one in by if one["kind"] == UNDECLARED),
        "projects": {"took": len({one["repo"].casefold() for one in by}), "of": family_size},
        "by": by,
    }


def notes(summary: dict[str, Any], *, mine: str = "") -> dict[str, Any]:
    """Заметки и замеры соседей по правилам — раздел `notes` сводки 1.7, поимённо.

    ФОРМА — ИЗ ИСТОЧНИКА, А НЕ ИЗ ПОДДЕЛКИ (взгляд на #1340). Раздел кладёт
    сборщик каталога: `scripts/aggregate_bindings.py`, `entry["notes"] =
    заметки(rules)` — словарь «правило → {note, metric}» у КАЖДОГО потребителя
    (тег `v1.11.0`). Живой сводки с непустыми заметками нет ни у кого (замер
    14.10.2026), поэтому ноль различается на три исхода, а не сливается в
    один: `read` — у скольких потребителей раздел есть и той формы;
    `unread` — у скольких его нет вовсе; `wrong_shape` — у скольких он не
    словарь. Иная раскладка у каталога дала бы ненулевой `wrong_shape` или
    `unread`, а не тихий ноль (045).

    Свои не считаются: мерило о семье, а свои мысли живут в нашем ответе.
    Запись не той формы внутри раздела в разрез не идёт, но и не валит его:
    раздел совещательный, и одна кривая строка соседа не должна гасить
    числа всех остальных (039).

    ПРОПУСК СЧИТАЕТСЯ И НАЗЫВАЕТСЯ (взгляд на #1340, вторая находка по
    месту — 210). Различать ноль только на уровне раздела мало: иная
    раскладка записи дала бы тот же тихий ноль. Формы, которые вход
    допускает, перечислены в `entry_wrong`, и каждая кривая запись идёт в
    `wrong_entries` с причиной; годная половина записи (заметка при кривом
    замере) при этом читается.
    """
    by: list[dict[str, Any]] = []
    wrong_entries: list[dict[str, str]] = []
    read = unread = wrong_shape = 0
    for consumer in summary.get("consumers") or []:
        repo = str(consumer.get("repo") or "")
        if repo.casefold() == (mine or family_uptake.OURS).casefold():
            continue
        said = consumer.get("notes")
        if "notes" not in consumer:
            unread += 1
            continue
        if not isinstance(said, dict):
            wrong_shape += 1
            continue
        read += 1
        for number, entry in sorted(said.items()):
            why = entry_wrong(entry)
            if why:
                wrong_entries.append({"repo": repo, "rule": str(number), "why": why})
            if not isinstance(entry, dict):
                continue
            row: dict[str, Any] = {"repo": repo, "rule": str(number)}
            if isinstance(entry.get("note"), str) and entry["note"].strip():
                row["note"] = entry["note"].strip()
            # Пустой замер в `by` не идёт: в `count` он прибавил бы запись, где
            # читать нечего (взгляд на #1352).
            if filled(entry.get("metric")):
                row["metric"] = entry["metric"]
            if len(row) > 2:
                by.append(row)
    return {
        "count": len(by),
        "read": read,
        "unread": unread,
        "wrong_shape": wrong_shape,
        "wrong_entries": len(wrong_entries),
        "wrong_entries_by": wrong_entries,
        "by": by,
    }


#: Ключи записи раздела `notes` — как их кладёт сборщик каталога
#: (`aggregate_bindings.py`, тег `v1.11.0`): «правило → {note, metric}».
NOTE_KEYS: Final = frozenset({"note", "metric"})


def hollow(value: object) -> bool:
    """Значение, в котором читать нечего: `None`, пробельная строка или пустое вглубь.

    Список и словарь пусты, когда пусты все их элементы: `[" "]` и
    `{"x": None}` — тот же соседний с `""` случай уровнем глубже (взгляд на
    #1366, правило 195). Ноль и `False` — значения.

    Обход идёт явным стеком, а не рекурсией: разборщик JSON держит вложенность
    в тысячи уровней, рекурсия падала уже на пятистах, и `RecursionError` одной
    записи соседа гасил сборку фактов целиком (поздний взгляд на #1366, 039).
    СОСЕД НАЗВАН (находка `9846074`, 195): вход глубже предела САМОГО
    разборщика сюда не доходит — его отвергает `load` третьим исходом, и это
    держит набор.
    """
    pending: list[object] = [value]
    while pending:
        one = pending.pop()
        if one is None:
            continue
        if isinstance(one, str):
            if one.strip():
                return False
        elif isinstance(one, dict):
            pending.extend(one.values())
        elif isinstance(one, list):
            pending.extend(one)
        else:
            return False
    return True


def filled(metric: object) -> bool:
    """Замер, в котором есть что читать: словарь хотя бы с одним непустым значением.

    `{}` и `{"value": None}` — не замер (взгляд на #1352 и #1358): читать в них
    нечего. Пустота меряется вглубь (`hollow`): пробельная строка и вложенный
    пустой список или словарь — тоже не замер. Пустой замер при годной заметке
    записи не портит — заметка читается, а замер в `by` не идёт; это решение,
    а не пропуск.
    """
    return isinstance(metric, dict) and not hollow(metric)


def entry_wrong(entry: object) -> str:
    """Почему запись `notes` не той формы — все причины через «; »; пусто — годится.

    Перечень форм, которые вход допускает (210): не словарь; чужой ключ;
    `note` не строкой; `metric` не словарём; ни заметки, ни замера — в том
    числе пустая или пробельная `note` и замер без значений (`filled`): такую запись
    разрез не читает, и её пропуск обязан быть назван (взгляд на #1352). Причины
    называются все, а не первая: иначе починка у соседа шла бы в два захода.
    """
    if not isinstance(entry, dict):
        return "запись не словарь"
    reasons: list[str] = []
    alien = sorted(set(entry) - NOTE_KEYS)
    if alien:
        reasons.append(f"чужие ключи: {', '.join(alien)}")
    note, metric = entry.get("note"), entry.get("metric")
    if "note" in entry and not isinstance(note, str):
        reasons.append("note не строка")
    if "metric" in entry and not isinstance(metric, dict):
        reasons.append("metric не словарь")
    said = isinstance(note, str) and bool(note.strip())
    # ПУСТОЙ ЗАМЕР — НЕ ЗАМЕР, как пустая заметка — не заметка: `metric: {}`
    # нечего читать, и запись без заметки с таким замером кривая (взгляд на #1352).
    measured = filled(metric)
    if not said and not measured:
        reasons.append("ни заметки, ни замера")
    return "; ".join(reasons)


def held_by_machine(summary: dict[str, Any]) -> int:
    """Сколько ответов сводки держатся машиной — объём сводки, НАШИ ВКЛЮЧИТЕЛЬНО.

    Не знаменатель: доли по именам больше нет (#1199). Знаменатель «гейтом
    нашего происхождения» — `adopted(...)["of"]`, и он наших не считает,
    потому что мерило о семье. Два числа различаются намеренно и названы
    здесь, а не расходятся молча (взгляд на #1241).
    """
    return sum(
        1
        for consumer in summary.get("consumers") or []
        for answer in (consumer.get("holds") or {}).values()
        if isinstance(answer, dict) and answer.get("mechanism") in KINDS
    )


def behind(summary: dict[str, Any], *, mine: str, ours: dict[str, Any]) -> list[str]:
    """Правила, которые кто-то в семье держит МАШИНОЙ, а мы — нет.

    ЧТО ЭТО ЗА МЕРИЛО. «Конвейер удовлетворяет потребности семьи» — цель, и
    пока у неё нет числа, она остаётся ощущением. Число здесь честное: правило,
    которое сосед закрывает гейтом, а мы документом или «неприменимо», — это
    либо наш пробел, либо наш устаревший ответ. Оба случая требуют работы, и
    оба до сих пор были не видны
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).

    НАШИ ОТВЕТЫ БЕРУТСЯ НЕ ИЗ СНИМКА. Сводка каталога снимается ночью, и наши
    ответы в ней отстают на смену: замер 10.09.2026 показал восемь наших правил
    документами, когда они уже держались гейтами. Поэтому соседи читаются из
    снимка, а мы — из живого дерева, и это названо, а не умолчано
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

    ЧИСЛО НЕ РЕШАЕТ ЗА ЧЕЛОВЕКА. Правило, закрытое соседом гейтом, у нас может
    быть неприменимо по существу — у проектов разные предметы. Мерило говорит,
    ГДЕ смотреть, а перечитывание ответа остаётся работой человека.
    """
    theirs: set[str] = set()
    for consumer in summary.get("consumers") or []:
        if str(consumer.get("repo") or "") == mine:
            continue
        for number, answer in (consumer.get("holds") or {}).items():
            if isinstance(answer, dict) and answer.get("mechanism") in KINDS:
                theirs.add(str(number))
    return sorted(
        number for number in theirs if (ours.get(number) or {}).get("mechanism") not in KINDS
    )


def picture(summary: dict[str, Any], *, mine: str = "") -> dict[str, Any]:
    """Разрез целиком: числа, которые публикуются фактом."""
    return {
        "schema_read": schema_of(summary),
        # КОГДА СНЯТ СНИМОК, ПО КОТОРОМУ ЭТО ПОСЧИТАНО. Числа ниже — не о
        # сегодняшнем дне семьи, а о том, каким её видел последний ночной заход
        # каталога. Замер 10.09.2026: сводка семичасовой давности показывала
        # восемь наших правил документами, когда они уже держались гейтами, и
        # разрез приоритета по ней назвал долгом то, чего нет (005).
        "snapshot_at": str(summary.get("generated_at") or ""),
        "consumers": len(summary.get("consumers") or []),
        "held_by_machine": held_by_machine(summary),
        "adopted": adopted(summary, mine=mine),
        "origins": origins(summary, mine=mine),
        "notes": notes(summary, mine=mine),
    }
