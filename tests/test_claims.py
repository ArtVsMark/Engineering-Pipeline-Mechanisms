"""Исключительные утверждения: объявленные сверяются с деревом, а не помнятся.

Правило [181](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/181-an-exclusive-claim-binds-the-document.md):
исключительное утверждение связывает ВЕСЬ документ — «единственное право на
запись во всём конвейере» говорит не о своём абзаце, а о дереве целиком. Ломается
оно молча: кто-то добавляет второго, и утверждение остаётся стоять.

Замер 15.09.2026, стоивший этой проверки: `badges.yml` утверждал единственность
права на запись, и в тот же день появился второй прогон, пишущий в свою
ветку-сироту. Нашёл это не гейт — правка, которая второго и добавила.

ОТВЕРГАЕМОЕ ЗДЕСЬ ДВОЙНОЕ, и обе ошибки выглядят снаружи одинаково зелено:

* **утверждение разошлось с деревом** — число в прозе устаревает молча
  ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md));
* **реестр разошёлся с текстом** — цитату переписали, запись осталась, и гейт
  сверяет то, чего в документе уже нет
  ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

ЧЕГО ГЕЙТ НЕ ДЕЛАЕТ: не ищет исключительные утверждения в прозе. «Единственный
читатель этой метки — человек» и «единственный обязательный контекст защиты»
отличаются не словами, а предметом, и красное на каждом «единственный» учат
обходить ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Поиск остаётся работой человека, и это названный пробел, а не отсутствие
предмета (046).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, load_script

CLAIMS = ROOT / load_script("paths.py").CLAIMS
WORKFLOWS = ROOT / ".github" / "workflows"

#: Отсутствие механизма говорится СЛОВОМ, а не пропуском поля (154).
NO_KEEPER = "none"


def declared() -> list[dict[str, Any]]:
    """Объявленные утверждения — из данных, а не из этого файла."""
    said = json.loads(CLAIMS.read_text(encoding="utf-8"))
    return list(said.get("claims") or [])


def workflows_with_permission(arg: str) -> int:
    """Сколько прогонов дерева просят названное право — `contents: write`.

    Считаются права и прогона целиком, и его джобов: право, выданное джобу,
    ничем не слабее выданного файлу.
    """
    name, _, value = (part.strip() for part in arg.partition(":"))
    found = 0
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        places = [document.get("permissions")]
        places += [(job or {}).get("permissions") for job in (document.get("jobs") or {}).values()]
        if any(isinstance(place, dict) and str(place.get(name, "")) == value for place in places):
            found += 1
    return found


def branch_filters_with(arg: str) -> int:
    """Сколько прогонов дерева СЛУШАЮТ названную приставку ветки.

    Считаются фильтры событий, а не текст файла: приставка, названная в
    пояснении к её снятию («стояла здесь как переходная»), конвейером не
    слушается, и считать её значило бы краснеть на объяснении причины (051, 044).
    """
    found = 0
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        # `on` YAML читает как True: ключ-слово, а не строка.
        events = document.get("on", document.get(True))
        if not isinstance(events, dict):
            continue
        for event in events.values():
            names = (event or {}).get("branches") if isinstance(event, dict) else None
            if isinstance(names, list) and arg in [str(name) for name in names]:
                found += 1
                break
    return found


def triggers_of(arg: str) -> int:
    """Сколько событий ведёт в названный прогон: ключи раздела `on`."""
    document = yaml.safe_load((ROOT / arg).read_text(encoding="utf-8"))
    # `on` YAML читает как True: ключ-слово, а не строка. Спрашиваются оба вида,
    # иначе счётчик молча получал бы ноль событий (045).
    said = document.get("on", document.get(True)) if isinstance(document, dict) else None
    return len(said) if isinstance(said, dict) else 0


#: Чем умеет считать гейт. Список РАЗРЕШИТЕЛЬНЫЙ: неизвестное имя предиката —
#: находка, а не пропуск записи (068).
COUNTERS = {
    "workflows_with_permission": workflows_with_permission,
    "branch_filters_with": branch_filters_with,
    "triggers_of": triggers_of,
}


def problems(claims: list[dict[str, Any]], root: Path = ROOT) -> list[str]:
    """Что не сходится: форма записи, цитата в документе или само число.

    Один разбор на живой реестр и на прогон отказа: две записи того же сравнения
    разошлись бы молча, и отказ проверял бы не тот вопрос (090, 140).
    """
    found: list[str] = []
    for claim in claims:
        name = str(claim.get("id") or "без имени")
        where, quote = str(claim.get("where") or ""), str(claim.get("quote") or "")
        counted, keeper = claim.get("count"), claim.get("held_by")
        if bool(counted) == bool(keeper):
            found.append(f"{name}: у записи обязано быть ровно одно из `count` и `held_by`")
            continue
        if not where or not quote:
            found.append(f"{name}: не сказано, где утверждение стоит и как оно звучит")
            continue
        place = root / where
        if not place.is_file():
            found.append(f"{name}: документа {where} в дереве нет")
            continue
        if quote not in place.read_text(encoding="utf-8"):
            found.append(f"{name}: цитаты «{quote}» в {where} больше нет — реестр отстал от текста")
            continue
        if keeper:
            if keeper == NO_KEEPER:
                if not str(claim.get("why") or "").strip():
                    found.append(f"{name}: механизма нет, и причина не названа (154)")
            elif not (root / str(keeper)).is_file():
                found.append(f"{name}: держателем назван {keeper}, которого в дереве нет")
            continue
        what = str((counted or {}).get("what") or "")
        counter = COUNTERS.get(what)
        if counter is None:
            found.append(f"{name}: считать нечем — предикат «{what}» гейту неизвестен (068)")
            continue
        said = counter(str((counted or {}).get("arg") or ""))
        expected = int((counted or {}).get("expected", -1))
        if said != expected:
            found.append(f"{name}: объявлено {expected}, в дереве {said} — утверждение устарело")
    return found


def test_the_registry_is_not_empty() -> None:
    """Предмет проверки найден: утверждения объявлены, и их больше нуля (075)."""
    claims = declared()
    assert claims, "реестр исключительных утверждений пуст — гейту нечего сверять"
    assert len({str(claim.get("id")) for claim in claims}) == len(claims), (
        "имена утверждений повторяются: запись перестаёт быть адресуемой"
    )


def test_every_declared_claim_still_holds() -> None:
    """Каждое объявленное утверждение сходится с деревом — или называет держателя."""
    assert problems(declared()) == []


@pytest.mark.parametrize(
    "claim, признак",
    [
        pytest.param(
            {
                "id": "счёт",
                "where": ".github/workflows/main-red.yml",
                "quote": "единственное, ради чего это право здесь",
                "count": {
                    "what": "workflows_with_permission",
                    "arg": "actions: write",
                    "expected": 9,
                },
            },
            "устарело",
            id="число разошлось с деревом",
        ),
        pytest.param(
            {
                "id": "цитата",
                "where": ".github/workflows/badges.yml",
                "quote": "такой строки в файле нет",
                "count": {"what": "branch_filters_with", "arg": "claude/**", "expected": 0},
            },
            "реестр отстал от текста",
            id="цитату переписали",
        ),
        pytest.param(
            {
                "id": "предикат",
                "where": ".pipeline.yml",
                "quote": "единственный обязательный контекст защиты",
                "count": {"what": "посчитай-как-нибудь", "arg": "", "expected": 1},
            },
            "неизвестен",
            id="считать нечем",
        ),
        pytest.param(
            {
                "id": "оба",
                "where": ".pipeline.yml",
                "quote": "единственный обязательный контекст защиты",
                "count": {"what": "triggers_of", "arg": ".github/workflows/arm.yml", "expected": 1},
                "held_by": "scripts/check_version.py",
            },
            "ровно одно",
            id="и число, и держатель",
        ),
        pytest.param(
            {
                "id": "ни того ни другого",
                "where": ".pipeline.yml",
                "quote": "единственный обязательный контекст защиты",
            },
            "ровно одно",
            id="ни числа, ни держателя",
        ),
        pytest.param(
            {
                "id": "молчание",
                "where": "AGENTS.md",
                "quote": "Трекер — единственный источник статусов",
                "held_by": "none",
                "why": "  ",
            },
            "причина не названа",
            id="нет механизма и нет причины",
        ),
        pytest.param(
            {
                "id": "выдуманный держатель",
                "where": "AGENTS.md",
                "quote": "Трекер — единственный источник статусов",
                "held_by": "scripts/нет_такого.py",
            },
            "которого в дереве нет",
            id="держателя нет в дереве",
        ),
        pytest.param(
            {
                "id": "нет документа",
                "where": "docs/нет-такого.md",
                "quote": "что угодно",
                "held_by": "scripts/check_version.py",
            },
            "в дереве нет",
            id="документа нет",
        ),
    ],
)
def test_the_gate_rejects_what_it_must(claim: dict[str, Any], признак: str) -> None:
    """Гейт проверяется тем, что он обязан отвергнуть (140).

    Объявив несколько исходов, механизм прогоняется по каждому (145): здесь их
    столько, сколько способов соврать о единственности.
    """
    (said,) = problems([claim])
    assert признак in said, f"причина отказа названа не тем словом: {said}"


def test_the_counters_are_an_allowlist() -> None:
    """Считать умеет ровно объявленное, и каждый предикат зовётся из реестра.

    Предикат, которым никто не считает, — мёртвый код в гейте: он выглядит
    работающим и не проверяется ничем (075).
    """
    used = {str((claim.get("count") or {}).get("what") or "") for claim in declared()}
    assert set(COUNTERS) == used - {""}, (
        f"предикаты гейта и реестра расходятся: в гейте {sorted(COUNTERS)},"
        f" в реестре {sorted(used)}"
    )
