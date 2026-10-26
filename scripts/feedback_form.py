"""Форма раздела `feedback:` ответа проекта: что сосед говорит нам о наших механизмах (#1665).

КАНАЛ ОТ СОСЕДЕЙ К НАМ — КОНТРАКТ, А НЕ ПРОЗА (решение владельца 25.10.2026).
Наши механизмы уезжают к соседям, а ложный отказ, ложный пропуск, неполная
проверка или доработка у себя оставались у соседа в трекере или в копии кода —
мы узнавали последними. Теперь сосед пишет запись в свой `.pipeline.yml`,
рядом с ответом по шагам: факты о проекте публикует сам проект (174), а обход
семьи его файл уже читает.

ОДНА ЗАПИСЬ — ОДИН ПРЕДМЕТ: механизм, версия, на которой замечено, вид,
замер и след — адрес задачи в трекере соседа (185). Вердикт по записи пишем
мы, у себя, по ключу `потребитель:вид/слаг` — здесь его нет.

Разбор уже прочитанного значения раздела, а не файла: YAML ответа читает один
модуль, `pipeline_checks` (090), — тем же приёмом, что `shipped_form`.
"""

import re
from dataclasses import dataclass
from typing import Any, Final

import version


class NotRun(RuntimeError):
    """Раздел не той формы: отказ с причиной, а не молчаливое умолчание (045)."""


#: Раздел ответа проекта.
SECTION: Final = "feedback"
#: Версия формы раздела: меняется — сверка называет, какую ждёт.
VERSION: Final = 1
#: Виды записи — закрытый перечень (068): слаг → что значит.
KINDS: Final = {
    "false-refusal": "ложный отказ — красное на законном",
    "false-pass": "ложный пропуск — зелёное на нарушении",
    "not-run": "не отработал — падение, третий исход (039)",
    "partial": "неполнота — правило держится частью, названо, какой (182)",
    "rework": "доработка — нужен вход или настройка, механизм переписан у себя",
    "bypass": "обход — связь с объявленным «обойдён» в ответе по шагам",
}
#: Поля записи: все обязательны.
FIELDS: Final = ("slug", "mechanism", "version", "kind", "measured", "trace")
#: Слаг записи: ключ вердикта `потребитель:вид/слаг`, поэтому без пробелов.
SLUG_RE: Final = re.compile(r"[a-z0-9][a-z0-9-]*")
#: Механизм — имя нашего общего шага (`step-journal`), путь скрипта
#: (`scripts/check_journal.py`) или навыка и хука окна (`.claude/skills/…`).
#: Сверяется форма, а не существование: дерево поставщика у соседа видит только
#: выкачка шага, и опечатку внутри верной формы ловит наш вердикт (взгляд на #1702).
MECHANISM_RE: Final = re.compile(
    r"step-[a-z0-9-]+|scripts/[a-z0-9_]+\.py|\.claude/(?:skills|hooks)/[\w.-]+(?:/[\w.-]+)*"
)
#: След — задача у соседа: `владелец/репозиторий#N` или полный адрес.
TRACE_RE: Final = re.compile(r"[\w.-]+/[\w.-]+#\d+|https://\S+")


@dataclass(frozen=True)
class Record:
    """Запись соседа о нашем механизме."""

    slug: str
    mechanism: str
    version: str
    kind: str
    measured: str
    trace: str


def form_of(section: Any) -> list[Record]:
    """Записи из раздела `feedback:`; раздела нет (`None`) — записей нет.

    Отказ называет запись и поле: сосед чинит свой файл по сообщению, а не по
    нашему коду.
    """
    if section is None:
        return []
    if not isinstance(section, dict):
        raise NotRun(f"раздел {SECTION}: ожидалось отображение, пришло {type(section).__name__}")
    unknown = sorted(str(key) for key in set(section) - {"version", "records"})
    if unknown:
        raise NotRun(
            f"раздел {SECTION}: незнакомые ключи {', '.join(unknown)} — читаются version и records"
        )
    if section.get("version") != VERSION:
        raise NotRun(f"раздел {SECTION}: version {section.get('version')!r} — ждётся {VERSION}")
    raw = section.get("records", [])
    if not isinstance(raw, list):
        raise NotRun(f"раздел {SECTION}: records — список записей")
    found: list[Record] = []
    for index, one in enumerate(raw, 1):
        found.append(record_of(one, index))
    slugs = [one.slug for one in found]
    if twice := sorted({slug for slug in slugs if slugs.count(slug) > 1}):
        raise NotRun(f"раздел {SECTION}: слаг записи дважды — {', '.join(twice)}")
    return found


def record_of(one: Any, index: int) -> Record:
    """Одна запись раздела; поле без значения или чужой вид — отказ с местом."""
    where = f"раздел {SECTION}, запись {index}"
    if not isinstance(one, dict):
        raise NotRun(f"{where}: ожидалось отображение")
    unknown = sorted(str(key) for key in set(one) - set(FIELDS))
    if unknown:
        raise NotRun(f"{where}: незнакомые поля {', '.join(unknown)}")
    said: dict[str, str] = {}
    for field in FIELDS:
        value = one.get(field)
        if value is not None and not isinstance(value, str):
            # YAML читает `1.11` числом: отказ называет пришедшее и как его
            # записать, иначе «непустая строка» о непустом значении не читается.
            raise NotRun(
                f"{where}: {field} {value!r} прочитан как {type(value).__name__}, "
                "а ждётся строка — возьмите значение в кавычки"
            )
        if not isinstance(value, str) or not value.strip():
            raise NotRun(f"{where}: {field} — непустая строка")
        said[field] = value.strip()
    if not SLUG_RE.fullmatch(said["slug"]):
        raise NotRun(f"{where}: slug «{said['slug']}» — строчные латинские, цифры и дефис")
    if not MECHANISM_RE.fullmatch(said["mechanism"]):
        raise NotRun(
            f"{where}: mechanism «{said['mechanism']}» — имя шага `step-…`, "
            "путь `scripts/….py` или `.claude/skills|hooks/…`"
        )
    # Тег выпуска судит один признак — `version.is_release_tag` (214).
    if not version.is_release_tag(said["version"]):
        raise NotRun(f"{where}: version «{said['version']}» — тег нашего выпуска, `vX.Y.Z`")
    if said["kind"] not in KINDS:
        raise NotRun(f"{where}: вид «{said['kind']}» — один из {', '.join(KINDS)}")
    if not TRACE_RE.fullmatch(said["trace"]):
        raise NotRun(
            f"{where}: trace «{said['trace']}» — `владелец/репозиторий#N` или адрес https://"
        )
    return Record(**said)


#: ВЕРДИКТ — НАШ, И ЛЕЖИТ У НАС (п. 4 #1665). Сосед пишет запись в своём
#: `.pipeline.yml`, мы отвечаем по ключу записи в файле вердиктов
#: поставщика (его читает `feedback_registry`): один файл на всю семью, а не правка чужого.
#: Исход — закрытый перечень (068): слаг → какое поле он требует.
VERDICTS: Final = {
    "accepted": "release",
    "rejected": "why",
    "duplicate": "of",
    "fixed": "release",
}
#: Версия формы файла вердиктов.
VERDICTS_VERSION: Final = 1
#: Ключ вердикта: `владелец/репозиторий:вид/слаг`. Имя репозитория соседа —
#: часть ключа, и переименование соседа рвёт связь: вердикт осиротеет, и
#: реестр назовёт его сиротой, а не потеряет молча (045).
KEY_RE: Final = re.compile(
    rf"[\w.-]+/[\w.-]+:(?:{'|'.join(KINDS)})/{SLUG_RE.pattern}", re.IGNORECASE
)


@dataclass(frozen=True)
class Verdict:
    """Наш ответ на запись соседа: исход и то, что он требует."""

    verdict: str
    #: Значение поля, которое требует исход: тег выпуска, причина или ключ.
    said: str


def key_of(repo: str, record: Record) -> str:
    """Ключ вердикта записи соседа: `владелец/репозиторий:вид/слаг`."""
    return f"{repo.lower()}:{record.kind}/{record.slug}"


def verdicts_of(data: Any) -> dict[str, Verdict]:
    """Вердикты из прочитанного файла; дефект формы — отказ с ключом и полем.

    Отклонение без причины — отказ, а не «отклонено»: «нет» говорится с
    доводом (154, 026). Дубль ссылается на ключ, который есть в этом же файле
    или будет в реестре, — сверяется форма ключа, а не его жизнь: запись
    соседа живёт у него.
    """
    if not isinstance(data, dict):
        raise NotRun("вердикты: ожидалось отображение")
    if data.get("version") != VERDICTS_VERSION or isinstance(data.get("version"), bool):
        raise NotRun(f"вердикты: version {data.get('version')!r} — ждётся {VERDICTS_VERSION}")
    raw = data.get("verdicts", {})
    if not isinstance(raw, dict):
        raise NotRun("вердикты: verdicts — отображение «ключ → вердикт»")
    found: dict[str, Verdict] = {}
    for key, one in raw.items():
        where = f"вердикт {key}"
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            raise NotRun(
                f"{where}: ключ — `владелец/репозиторий:вид/слаг`, вид из {', '.join(KINDS)}"
            )
        if not isinstance(one, dict):
            raise NotRun(f"{where}: ожидалось отображение")
        verdict = one.get("verdict")
        if verdict not in VERDICTS:
            raise NotRun(f"{where}: исход «{verdict}» — один из {', '.join(VERDICTS)}")
        field = VERDICTS[verdict]
        unknown = sorted(str(name) for name in set(one) - {"verdict", field})
        if unknown:
            raise NotRun(
                f"{where}: незнакомые поля {', '.join(unknown)} — у «{verdict}» поле {field}"
            )
        value = one.get(field)
        if not isinstance(value, str) or not value.strip():
            raise NotRun(f"{where}: у «{verdict}» поле {field} — непустая строка")
        value = value.strip()
        if field == "release" and not version.is_release_tag(value):
            raise NotRun(f"{where}: release «{value}» — тег нашего выпуска, `vX.Y.Z`")
        if field == "of" and (not KEY_RE.fullmatch(value) or value.lower() == key.lower()):
            raise NotRun(f"{where}: of «{value}» — ключ другой записи")
        found[key.lower()] = Verdict(verdict, value)
    return found
