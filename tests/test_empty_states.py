"""Пустое состояние живой задачи называет ДЕНЬ обхода, а не только пустоту.

Правило 027 разводит два вида молчания: «здесь сейчас пусто, дата» — это
информация, просто пустой раздел — неоднозначность
([027](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/027-empty-state-is-a-state.md)).
Цена различия у живой задачи наибольшая: тело переписывается поверх прежнего
каждым заходом, и застывшее тело снаружи выглядит ровно как свежее. «Ничего не
нашлось» и «заход не состоялся» становятся одной строкой.

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Тело живой задачи собирают
шесть механизмов, и пустоту объявляют все шесть. День обхода стоял у трёх —
`review_findings` строкой «Убрано до», `schedules_seen` и `stuck` строкой
«Обход». Молчали `drift`, `main_red` и `unlooked`: первые два не называли
времени вовсе, третий называл КУРСОР («Просмотрено до: #N») — ответ на другой
вопрос. Докуда дошли и когда заходили — разные величины: остановившийся
механизм держит тот же курсор сколько угодно долго.

ПРЕДМЕТ СУЖЕН ЗАМЕРОМ, А НЕ ВКУСОМ. Первая редакция предиката брала любую
функцию, в тексте которой встречается слово «Пусто», — и назвала четыре места,
где слово стоит в ДОКСТРОКЕ («Пусто, если подпись честна») либо в производном
файле, чья пустота датирована заголовком выпуска. Это тот самый род
«признак шире своего предмета», уже встреченный в `.rules/finding-kinds.json`.
Здесь предмет — функция, собирающая тело ЖИВОЙ задачи: модуль объявляет
`MARKER`, по которому механизм находит своё тело и переписывает его
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md),
[195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

СОСЕД У СУЖЕНИЯ НАЗВАН: пустой раздел журнала (`build_changelog.py`) остаётся
вне предмета намеренно. Журнал производен и датирован выпуском, под которым
лежит раздел, а «Не выпущено» пусто ровно тогда, когда в `changelog.d/` нет
фрагментов, — это видно клоном, а не только телом.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, load_script

paths = load_script("paths.py")

SCRIPTS: Final = ROOT / "scripts"

#: Объявление, по которому механизм узнаёт СВОЁ тело живой задачи.
MARKER: Final = "MARKER"

#: Слово, которым объявляют пустоту. Регистр значим: «пусто» строчной буквой
#: встречается внутри сообщений об отказе, и это другой предмет.
EMPTINESS: Final = "Пусто"

#: Чем называют день обхода: собранный сейчас либо принесённый курсором дня.
A_DAY: Final = re.compile(r"strftime|isoformat|Убрано до")


def publishers() -> list[Path]:
    """Механизмы, переписывающие тело живой задачи поверх прежнего."""
    return [
        path
        for path in sorted(SCRIPTS.glob("*.py"))
        if re.search(rf"^{MARKER}\b", path.read_text(encoding="utf-8"), re.M)
    ]


def without_docstring(node: ast.FunctionDef) -> str:
    """Тело функции БЕЗ докстроки: слово в объяснении — не объявление пустоты.

    Разбором, а не подстрокой: «функция объявляет пустоту» — отношение, и
    присутствие слова в тексте его не доказывает
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    """
    first = node.body[0] if node.body else None
    doc = (
        first
        if isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
        else None
    )
    return "\n".join(ast.unparse(one) for one in node.body if one is not doc)


def bodies() -> list[tuple[Path, ast.FunctionDef, str]]:
    """Функции живых механизмов, объявляющие пустоту строкой тела."""
    found: list[tuple[Path, ast.FunctionDef, str]] = []
    for path in publishers():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            text = without_docstring(node)
            if EMPTINESS in text:
                found.append((path, node, text))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    assert publishers(), "ни один механизм не объявляет MARKER — тел живых задач в дереве нет"
    assert bodies(), "ни одно тело живой задачи не объявляет пустоту — сверять нечего"


def test_an_empty_state_says_when_it_was_looked_at() -> None:
    """Рядом с пустотой живой задачи стоит день обхода.

    Тело переписывается поверх прежнего, и внешнего следа у прошлого захода не
    остаётся. Без дня «нашёл и ничего нет» неотличимо от «не заходил с июля» —
    причём молчаливо и тем дольше, чем спокойнее выглядит пустой список: у
    застывшего механизма он ровно такой же
    ([027](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/027-empty-state-is-a-state.md)).
    """
    mute = [
        f"{path.relative_to(ROOT)}:{node.lineno} — {node.name}"
        for path, node, text in bodies()
        if not A_DAY.search(text)
    ]
    assert not mute, (
        "пустота живой задачи объявлена без дня обхода — «ничего не нашлось»"
        " неотличимо от «не заходили» (027):\n  "
        + "\n  ".join(mute)
        + "\n  Поставьте день рядом: собранный сейчас либо принесённый курсором дня."
    )


def test_a_cursor_is_not_counted_as_a_day() -> None:
    """Граница названа замером: курсор в дереве есть, и днём он не считается.

    `unlooked.py` печатает «Просмотрено до: #N» — докуда дошёл обход. Величина
    законная и нужная, но на вопрос «когда» она не отвечает: остановившийся
    механизм держит её неизменной. Исчезнет курсор из дерева — довод про
    границу станет пустым, и это увидит проверка, а не читатель докстроки
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    cursors = [
        path.name for path, _, text in bodies() if "Просмотрено до" in text or "watermark" in text
    ]
    assert cursors, "курсора обхода в дереве нет — довод про границу пуст"
    assert not A_DAY.search("Просмотрено до: #123"), "курсор опознаётся как день — граница стёрта"
