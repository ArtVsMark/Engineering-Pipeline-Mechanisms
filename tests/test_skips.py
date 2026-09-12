"""Пропущенная проверка называет причину — иначе это забытый тест.

Правило 040: пропуск без причины неотличим от забытого. Через месяц никто не
знает, ждёт ли он внешнего условия или его выключили «на время» — а набор при
этом зелёный, и зелёный он честно: пропущенное не падает.

ГЕЙТ ЖИВЁТ НАБОРОМ, А НЕ ОТДЕЛЬНЫМ СКРИПТОМ. Предмет здесь — свойство самого
дерева тестов, и такие свойства проект уже держит набором (`test_docs_shape`,
`test_review_safety`, `test_live_references`). Отдельный скрипт понадобился бы
ради собственного джоба, то есть ради имени в защите ветки, — а имя это ничего
нового не сказало бы: красное пришло бы оттуда же, откуда и остальные свойства
дерева. У соседа-каталога то же самое сделано скриптом `check_skips.py`, и
разница здесь в форме, а не в существе
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Final

import pytest

from tests.conftest import ROOT

TESTS: Final = ROOT / "tests"

#: Пометки, выключающие проверку целиком или заранее объявляющие её падение.
#: Список РАЗРЕШИТЕЛЬНЫЙ: неизвестная пометка молча не проходит (068).
MUTING: Final = frozenset({"skip", "skipif", "xfail"})


@dataclass(frozen=True, slots=True)
class Muted:
    """Одно выключение: где, какой формы и названа ли причина."""

    where: str
    line: int
    form: str
    named: bool

    def said(self) -> str:
        return f"{self.where}:{self.line} — {self.form} без причины"


#: Формы, у которых ПЕРВЫЙ довод — условие, а не причина. Прочитать его как
#: причину значило бы засчитывать `skipif(нет_истории)` за названное: условие
#: говорит, КОГДА выключено, и ни слова о том, ЗАЧЕМ.
CONDITIONAL: Final = frozenset({"skipif", "xfail"})


def named_in(node: ast.Call, form: str) -> bool:
    """Названа ли причина у вызова пометки или у `pytest.skip`.

    Причина считается названной, если она НЕПУСТАЯ строка: `reason=""` — то же
    молчание, только записанное (154). Выражение, которое нельзя прочесть
    статически, считается названным: судить о его содержимом отсюда нечем, и
    объявлять его молчанием значило бы краснеть по незнанию
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    for keyword in node.keywords:
        if keyword.arg == "reason":
            said = keyword.value
            return not (isinstance(said, ast.Constant) and not str(said.value or "").strip())
    if form in CONDITIONAL:
        return False
    if node.args:
        said = node.args[0]
        if isinstance(said, ast.Constant):
            return bool(str(said.value or "").strip())
        return True
    return False


def tail_of(node: ast.expr) -> str:
    """Последнее имя выражения: `pytest.mark.skipif` → `skipif`."""
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")


def muted_in(source: str, where: str = "<подделка>") -> list[Muted]:
    """Все выключения в разобранном тексте — и названные, и молчащие.

    Отдаются ОБА рода: без названных нельзя проверить, что разбор вообще что-то
    находит, и гейт зеленел бы на файле, который не сумел прочесть
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    tree = ast.parse(source)
    # ПОМЕТКА СО СКОБКАМИ РАЗБИРАЕТСЯ КАК ВЫЗОВ, И ДВАЖДЫ ЕЁ СЧИТАТЬ НЕЛЬЗЯ.
    # Обход дерева видит и вызов, и его имя отдельным узлом: без этой памяти
    # `pytest.mark.skipif(..., reason=...)` попадал бы в список вторым разом —
    # уже как «голая пометка», то есть названное читалось бы молчащим.
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    found: list[Muted] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = tail_of(node.func)
            if name in MUTING or (name == "skip" and "pytest" in ast.dump(node.func)):
                found.append(Muted(where, node.lineno, name, named_in(node, name)))
        elif isinstance(node, ast.Attribute) and node.attr in MUTING and id(node) not in called:
            # Голая пометка без скобок: `@pytest.mark.skip` — причины нет по
            # построению, и сказать её негде.
            if isinstance(node.value, ast.Attribute) and node.value.attr == "mark":
                found.append(Muted(where, node.lineno, f"{node.attr} без скобок", False))
    return found


def live() -> list[Muted]:
    """Выключения живого дерева проверок."""
    found: list[Muted] = []
    for path in sorted(TESTS.glob("*.py")):
        found.extend(muted_in(path.read_text(encoding="utf-8"), path.name))
    return found


def test_the_live_tree_mutes_nothing_without_a_reason() -> None:
    """Ни один пропуск в дереве не молчит о своей причине (040)."""
    mute = [item.said() for item in live() if not item.named]
    assert not mute, "выключено без названной причины:\n  " + "\n  ".join(mute)


def test_the_scan_finds_the_subject_in_the_live_tree() -> None:
    """Предмет найден: выключения в дереве ЕСТЬ.

    Без этого соседняя проверка зеленела бы и на разборе, который не находит
    ничего — например, сломавшись о новую форму записи (075).
    """
    assert live(), "в дереве не найдено ни одного выключения — разбор не находит предмета"


PLANTED: Final = (
    ("@pytest.mark.skip\ndef test_a(): ...", False, "голая пометка"),
    ('@pytest.mark.skip(reason="ждём тега")\ndef test_a(): ...', True, "названная пометка"),
    ('@pytest.mark.skip("ждём тега")\ndef test_a(): ...', True, "причина первым доводом"),
    ('@pytest.mark.skip(reason="")\ndef test_a(): ...', False, "пустая причина"),
    ("@pytest.mark.skipif(нет_истории)\ndef test_a(): ...", False, "условие без причины"),
    (
        '@pytest.mark.skipif(нет_истории, reason="мелкий клон")\ndef test_a(): ...',
        True,
        "условие с причиной",
    ),
    ("@pytest.mark.xfail\ndef test_a(): ...", False, "ожидаемое падение без причины"),
    ('def test_a():\n    pytest.skip("история обрезана")', True, "пропуск по ходу"),
    ("def test_a():\n    pytest.skip()", False, "пропуск по ходу без слов"),
)


@pytest.mark.parametrize(("source", "named", "about"), PLANTED, ids=[one[2] for one in PLANTED])
def test_a_planted_form_is_read_as_it_reads(source: str, named: bool, about: str) -> None:
    """Разбор проверяется тем, что обязан отвергнуть, — подделкой каждой формы.

    Форм записи выключения в pytest больше одной, и гейт, знающий половину,
    хуже отсутствующего: он даёт уверенность там, где её нет
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    found = muted_in(source)
    assert found, f"{about}: выключение не найдено вовсе"
    assert found[0].named is named, (
        f"{about}: прочитано как {'названное' if found[0].named else 'молчащее'}"
    )
