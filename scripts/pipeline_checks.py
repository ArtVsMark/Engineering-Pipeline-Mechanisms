"""Классы проверок: чем проект отвечает по каждой проверке своего конвейера.

Класс проверки — свойство **потребителя**, а не механизма. Одна и та же
проверка у разных проектов принадлежит разным классам: объём документа
обязателен там, где документ выпускается наружу, и совещателен там, где он
внутренний; у текстового проекта проверки прозы и есть предмет, а `test` может
отсутствовать вовсе; e2e невозможен у проекта без внешнего окружения. Общий
конвейер видит только имя проверки, и знать этого за проект он не может
([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)).

Отсюда форма ответа: по **каждой** проверке, а не по подключённым — как в
`.rules/bindings.json` по каждому правилу каталога
([129](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/129-a-catalogue-needs-a-consumption-contract.md)).
Неотвеченная проверка получает `unreviewed`: объявленную очередь разбора, а не
молчание, — и слияния не держит.

Классы:

* ``required`` — держит слияние, входит в опрос сводного гейта;
* ``advisory`` — слияния не держит, но красное обязано оставить запись
  адресату, переживающему слияние
  ([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)):
  иначе «совещательная» — это вежливое «выключена»;
* ``off`` — выключена **с названной причиной**
  ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)):
  «не подключено» и «отключено сознательно» снаружи неотличимы;
* ``unreviewed`` — ответа ещё нет, и это видно.

ЛОВУШКА YAML, КОТОРУЮ ЧТЕНИЕ НЕ ДАЁТ. В YAML 1.1 `off` — булево `False`, и
запись `class: off` приходит сюда не строкой; тем же образом `on:` в файле
прогона лежит под ключом `True`, а не под строкой «on». Разбор принимает обе
формы: ответ, написанный ровно так, как он читается человеком, не должен
отвергаться с невнятной причиной.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import paths
import yaml

DEFAULT_PATH: Final = paths.PIPELINE
WORKFLOWS: Final = paths.WORKFLOWS
SCHEMA: Final = 3

REQUIRED: Final = "required"
ADVISORY: Final = "advisory"
OFF: Final = "off"
UNREVIEWED: Final = "unreviewed"
#: Список разрешённого, а не список запрещённого: неизвестное значение —
#: отказ, а не «наверное, что-то безобидное» (068).
CLASSES: Final = (REQUIRED, ADVISORY, OFF, UNREVIEWED)
NEEDS_REASON: Final = frozenset({ADVISORY, OFF})
#: Класс, у которого обязан быть назван адресат: совещательное красное слияния
#: не держит, и если его записи негде пережить слияние, «совещательная» — это
#: вежливое «выключена» (142).
NEEDS_ADDRESSEE: Final = frozenset({ADVISORY})
#: Записи нет, и это сказано СЛОВОМ, а не пропуском поля. Приём взят у
#: `mechanism: none` в ответе каталогу: «не замечается ничем» — объявленное
#: состояние, а молчание неотличимо от «забыли ответить» (154).
NO_ADDRESSEE: Final = "none"
#: Диапазон совместимости с контрактом механизмов: `>=X.Y,<A.B`.
#: ВЕРХНЯЯ ГРАНИЦА ОБЯЗАТЕЛЬНА. Без неё несовместимая версия применяется молча
#: ([073](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/073-tool-version-from-one-source-with-an-upper-bound.md)):
#: потребитель, объявивший только «не старше», однажды получает поверхность, о
#: которой не знает, и узнаёт об этом красным на ровном месте.
RANGE_RE: Final = re.compile(r"^>=\s*(\d+)\.(\d+)\s*,\s*<\s*(\d+)\.(\d+)$")

#: Разрешимый адрес задачи: `#12` в своём трекере или `владелец/репо#12`.
ISSUE_RE: Final = re.compile(r"^(?:[\w.-]+/[\w.-]+)?#\d+$")
#: Знаки образца пути: адрес вида `.github/workflows/*.yml` разрешается тем,
#: что он ДЕЙСТВИТЕЛЬНО что-то находит в дереве, а не тем, что похож на путь.
GLOB_MARKS: Final = "*?["
#: Событие, от которого проверка выдаёт запись на голове изменения. Прогоны по
#: расписанию и по толчку сюда не входят: у них другой предмет и другой
#: адресат, и слияния они не касаются.
ON_CHANGE: Final = "pull_request"


class BadPolicy(RuntimeError):
    """Ответ по проверкам не разбирается или не проходит проверку.

    Ошибка входа, а не пустой результат: механизм, не нашедший предмета
    проверки, обязан падать
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """


@dataclass(frozen=True, slots=True)
class Check:
    """Ответ проекта по одной проверке: имя, класс, причина и адресат."""

    name: str
    klass: str
    why: str = ""
    #: Где красное этой проверки переживает слияние: задача или файл механизма,
    #: который ведёт запись. Слово `none` значит «записи нет» — состояние, а не
    #: пропуск.
    addressee: str = ""

    @property
    def records(self) -> bool:
        """Оставляет ли красное этой проверки запись, переживающую слияние."""
        return bool(self.addressee) and self.addressee != NO_ADDRESSEE

    @property
    def holds_merge(self) -> bool:
        """Держит ли эта проверка слияние."""
        return self.klass == REQUIRED

    @property
    def answered(self) -> bool:
        """Дан ли по проверке ответ — или она лежит в очереди разбора."""
        return self.klass != UNREVIEWED


@dataclass(frozen=True, slots=True)
class Job:
    """Джоб прогона, выдающий запись проверки на голове изменения."""

    name: str
    workflow: str
    matrix: bool


def _text_of(value: Any) -> str:
    """Приводит значение класса к строке, разбирая булевы YAML 1.1."""
    if value is False:
        return OFF
    if value is True:
        return "on"
    return str(value if value is not None else "").strip()


def _triggers_of(document: dict[Any, Any]) -> list[str]:
    """Отдаёт имена событий прогона.

    Раздел событий лежит под ключом `True`, а не под строкой «on»: YAML 1.1
    читает `on:` булевым. Оба ключа разбираются, иначе механизм молча решил бы,
    что событий у прогона нет вовсе.
    """
    raw = document.get("on", document.get(True))
    if isinstance(raw, dict):
        return [str(key) for key in raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return [str(raw)] if raw else []


def compatible(declared: str, version: str) -> bool:
    """Попадает ли версия контракта в объявленный потребителем диапазон.

    Сравниваются MAJOR.MINOR: патч контракта поверхности не трогает по
    построению, и требовать его совпадения значило бы тревожить потребителя
    выпуском, который его не касается.
    """
    bounds = RANGE_RE.match(declared.strip())
    if bounds is None:
        raise BadPolicy(
            f"диапазон совместимости «{declared}» не разбирается — нужен вид "
            '">=X.Y,<A.B" с ОБЯЗАТЕЛЬНОЙ верхней границей (073)'
        )
    low = (int(bounds.group(1)), int(bounds.group(2)))
    high = (int(bounds.group(3)), int(bounds.group(4)))
    parts = version.split(".")
    if len(parts) < 2 or not all(piece.isdigit() for piece in parts[:2]):
        raise BadPolicy(f"версия контракта «{version}» не разбирается")
    now = (int(parts[0]), int(parts[1]))
    return low <= now < high


def resolves(address: str, root: Path = Path()) -> bool:
    """Разрешается ли адрес адресата: задача, существующий путь или образец.

    Проза адресом не считается. Требование то же, что каталог предъявил полю
    `where` в ответе потребителя, и по той же причине: канал, чей адресат
    нельзя назвать, обычно и не имеет адресата — а снаружи это выглядит как
    осознанный совещательный класс
    ([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md)).
    """
    if ISSUE_RE.match(address):
        return True
    if any(mark in address for mark in GLOB_MARKS):
        return any(root.glob(address))
    return (root / address).exists()


def load(path: Path = DEFAULT_PATH) -> dict[str, Check]:
    """Читает ответ проекта по проверкам, отвергая любой дефект входа."""
    if not path.is_file():
        raise BadPolicy(f"ответа по проверкам нет: {path} — ошибка входа, а не «нечего опрашивать»")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BadPolicy(f"ответ по проверкам не разбирается: {exc}") from exc

    if not isinstance(raw, dict):
        raise BadPolicy(f"{path}: ожидалось отображение, пришло {type(raw).__name__}")
    if raw.get("schema") != SCHEMA:
        raise BadPolicy(
            f"{path}: схема «{raw.get('schema')}» не та, что читает механизм ({SCHEMA})"
        )

    span = str(raw.get("contract") or "").strip()
    if not span:
        raise BadPolicy(
            f"{path}: не объявлен диапазон совместимости с контрактом механизмов. "
            "«Подходит любая версия» — не состояние, а молчание (154)"
        )
    version_file = path.parent / paths.VERSION
    if version_file.is_file():
        now = version_file.read_text(encoding="utf-8").strip()
        if not compatible(span, now):
            raise BadPolicy(
                f"{path}: контракт механизмов {now} вне объявленного диапазона «{span}» — "
                "перечитайте ответы под новый контракт (157), а не двигайте границу"
            )

    declared = raw.get("checks")
    if not isinstance(declared, dict) or not declared:
        raise BadPolicy(f"{path}: раздел checks пуст — предмет опроса не найден (075)")

    checks: dict[str, Check] = {}
    problems: list[str] = []
    for key, item in declared.items():
        name = str(key).strip()
        if isinstance(item, dict):
            klass = _text_of(item.get("class"))
            why = str(item.get("why") or "").strip()
            addressee = str(item.get("addressee") or "").strip()
        else:
            klass = _text_of(item)
            why = ""
            addressee = ""

        if "(" in name or ")" in name:
            problems.append(
                f"{name}: это имя матричной ячейки, а ответ даётся по имени джоба — "
                "иначе добавление версии в матрицу меняет договор молча"
            )
            continue
        if klass not in CLASSES:
            problems.append(f"{name}: класс «{klass}» неизвестен, из {', '.join(CLASSES)}")
            continue
        if klass in NEEDS_REASON and not why:
            problems.append(
                f"{name}: класс «{klass}» без причины — «не подключено» и «отключено "
                "сознательно» снаружи неотличимы (154)"
            )
            continue
        if klass in NEEDS_ADDRESSEE and not addressee:
            problems.append(
                f"{name}: класс «{klass}» без адресата — красное, которому негде "
                f"пережить слияние, делает совещательную проверку вежливо выключенной "
                f"(142). Адрес задачи, путь механизма или слово «{NO_ADDRESSEE}»"
            )
            continue
        if addressee and addressee != NO_ADDRESSEE and not resolves(addressee, path.parent):
            problems.append(
                f"{name}: адресат «{addressee}» не разрешается — ни задача, ни путь в "
                "дереве. Проза рядом с адресом законна, вместо адреса — нет"
            )
            continue
        checks[name] = Check(name, klass, why, addressee)

    if problems:
        raise BadPolicy("ответ по проверкам не проходит проверку:\n  " + "\n  ".join(problems))
    return checks


def names_of(checks: dict[str, Check], klass: str) -> list[str]:
    """Отдаёт имена проверок одного класса в порядке объявления."""
    if klass not in CLASSES:
        raise BadPolicy(f"класс «{klass}» неизвестен, из {', '.join(CLASSES)}")
    return [check.name for check in checks.values() if check.klass == klass]


def declared_jobs(directory: Path = WORKFLOWS, *, skip: str = "") -> dict[str, Job]:
    """Собирает проверки, выдающие запись на голове изменения.

    Предмет договора — не все прогоны проекта, а те, что идут **на изменении**:
    запись на голове появляется только от них, и только по ним есть что
    отвечать. Имя проверки — имя джоба (`name:`, а при его отсутствии
    идентификатор), потому что именно оно попадает в контекст.
    """
    if not directory.is_dir():
        raise BadPolicy(f"нет описания прогонов: {directory} — предмет сверки не найден (075)")

    jobs: dict[str, Job] = {}
    for path in sorted(directory.glob("*.y*ml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise BadPolicy(f"{path} не разбирается: {exc}") from exc
        if not isinstance(document, dict):
            raise BadPolicy(f"{path}: ожидалось отображение, пришло {type(document).__name__}")
        if ON_CHANGE not in _triggers_of(document):
            continue

        for job_id, body in (document.get("jobs") or {}).items():
            job = body or {}
            name = str(job.get("name") or job_id)
            if name == skip:
                continue
            matrix = bool((job.get("strategy") or {}).get("matrix"))
            if name in jobs:
                raise BadPolicy(
                    f"имя проверки «{name}» выдают двое: {jobs[name].workflow} и {path.name} — "
                    "вердикт по такому имени неоднозначен"
                )
            jobs[name] = Job(name, path.name, matrix)

    if not jobs:
        raise BadPolicy(
            f"в {directory} нет ни одной проверки на событие «{ON_CHANGE}» — "
            "это ошибка входа, а не «проверять нечего» (075)"
        )
    return jobs
