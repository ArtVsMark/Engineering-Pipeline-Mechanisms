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
        if not isinstance(value, str) or not value.strip():
            raise NotRun(f"{where}: {field} — непустая строка")
        said[field] = value.strip()
    if not SLUG_RE.fullmatch(said["slug"]):
        raise NotRun(f"{where}: slug «{said['slug']}» — строчные латинские, цифры и дефис")
    if said["kind"] not in KINDS:
        raise NotRun(f"{where}: вид «{said['kind']}» — один из {', '.join(KINDS)}")
    if not TRACE_RE.fullmatch(said["trace"]):
        raise NotRun(
            f"{where}: trace «{said['trace']}» — `владелец/репозиторий#N` или адрес https://"
        )
    return Record(**said)
