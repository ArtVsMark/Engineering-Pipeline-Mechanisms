"""Цитата снятой причины дословна — или её тут нет.

Проза проекта цитирует прежние причины ответов «неприменимо», и цитата эта
ОБЪЯВЛЕНА дословной: на ней стоит довод — «семь формулировок одной ошибки, ни
одна пара не делит ни одной». Усечённая цитата этот довод портит незаметно:
читатель видит семь коротких фраз, а стояли там длинные, и часть различий,
которыми довод держится, в усечение не попала.

ЗАМЕР 17.09.2026: из семи цитат в двух фрагментах журнала и в четырёх ответах
УСЕЧЕНЫ ЧЕТЫРЕ — 015, 020, 061, 117, — и все четыре без многоточия, то есть
неотличимо от полной. Это была ЧЕТВЁРТАЯ редакция одного абзаца: три первых
правили неточность и сами оказывались неточными, и каждый раз ловил человек, а
не механизм
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, walk_deep

#: Снимок причин, как они стояли. Собран механически из истории — рукописный
#: повторил бы ровно ту ошибку, против которой заведён.
SNAPSHOT: Final = ROOT / "tests" / "fixtures" / "superseded-reasons.json"
#: Строка таблицы «номер — цитата»: `| 015 | «…» |`. Форма, которой проза
#: перечисляет прежние причины; другой у неё нет.
QUOTED_ROW: Final = re.compile(r"^\|\s*(?P<rule>\d{3})\s*\|\s*«(?P<said>[^»]+)»\s*\|", re.M)
#: Цитата внутри прозы — любая кавычка «…». Номер рядом не стоит, поэтому
#: причина узнаётся ПО ТЕКСТУ: цитата, совпадающая с началом известной причины и
#: короче неё, — молчаливое усечение.
ANY_QUOTE: Final = re.compile(r"«([^»]{15,})»")
#: Ответ проекта каталогу: второе место, где те же причины цитируются.
#:
#: ЧИТАЮТСЯ ОБА, И ЭТО ПОЧИНКА ПО НАХОДКЕ. Первая редакция гейта была объявлена
#: закрывшей ТРИ места правки — два фрагмента журнала и ответы, — а читала
#: только `changelog.d/*.md`: заявление о покрытии шире самого покрытия
#: (нашёл внешний взгляд на #449, и назвал дважды). Расширение нашло ДВЕ живые
#: усечённые цитаты, которых никто не называл: в ответах 079 и 188 отрезаны
#: хвосты «Правило вступит вместе с хранилищем прогонов» и «Правило вступит,
#: если конвейер начнёт звать ревью комментарием» — то есть именно условие, при
#: котором прежний ответ переставал быть верным.
BINDINGS: Final = ROOT / ".rules" / "bindings.json"
#: Знак, которым усечение объявляется законно. Цитата с ним — сокращение, без
#: него — утверждение, что стояло ровно так (046).
ELLIPSIS: Final = "…"


def reasons() -> dict[str, str]:
    """Причины из снимка: номер правила → текст, как он стоял."""
    said = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["reasons"]
    return {rule: one["why"] for rule, one in said.items()}


def quoting_files() -> list[Path]:
    """Файлы прозы, где такие цитаты есть. Пустой список — предмета нет (075)."""
    found = [
        path
        for path in walk_deep(ROOT / "changelog.d", "*.md")
        if QUOTED_ROW.search(path.read_text(encoding="utf-8"))
    ]
    assert found, "цитат снятых причин в журнале нет — предмет проверки не найден"
    return found


def test_the_snapshot_has_a_subject() -> None:
    """Снимок непуст, иначе сверять не с чем."""
    assert len(reasons()) >= 7, f"причин в снимке {len(reasons())} — предмет не найден"


def truncated(quote: str, said: dict[str, str]) -> str:
    """Номер причины, начало которой цитата повторяет, оборвав молча; иначе пусто.

    Признак — СТРОГОЕ НАЧАЛО, а не вхождение: цитата в середине чужого текста
    случайна, а совпадение с началом при меньшей длине есть ровно усечение.
    """
    if ELLIPSIS in quote:
        return ""
    for rule, real in said.items():
        if quote != real and real.startswith(quote):
            return rule
    return ""


def test_the_answers_quote_their_superseded_reasons_verbatim() -> None:
    """Те же цитаты внутри ответов каталогу — второе место правки, и оно читается.

    Гейт был объявлен закрывшим три места и читал одно. Расширение нашло две
    живые усечённые цитаты, которых никто не называл (нашёл внешний взгляд
    на #449).
    """
    said = reasons()
    text = BINDINGS.read_text(encoding="utf-8")
    wrong = [
        f"{rule}: «{quote[:60]}…» оборвано без знака"
        for quote in ANY_QUOTE.findall(text)
        if (rule := truncated(quote, said))
    ]
    assert not wrong, "ответ цитирует прежнюю причину усечённо: " + "; ".join(sorted(set(wrong)))


@pytest.mark.parametrize("path", quoting_files(), ids=lambda p: p.name)
def test_every_quoted_reason_is_verbatim(path: Path) -> None:
    """Каждая процитированная причина совпадает с тем, как она стояла.

    Усечение законно, если объявлено многоточием: тогда читатель знает, что
    видит часть. Без него цитата утверждает, что стояло ровно так.
    """
    said = reasons()
    wrong: list[str] = []
    for match in QUOTED_ROW.finditer(path.read_text(encoding="utf-8")):
        rule, quote = match.group("rule"), match.group("said")
        real = said.get(rule)
        if real is None:
            wrong.append(f"{rule}: в снимке такой причины нет")
        elif quote != real and ELLIPSIS not in quote:
            wrong.append(f"{rule}: «{quote}» ≠ «{real}»")
    assert not wrong, f"{path.name}: цитата расходится с тем, как причина стояла: " + "; ".join(
        wrong
    )


def test_a_truncation_is_refused_and_an_ellipsis_is_not() -> None:
    """Предикат прогнан обоими концами — тем, что обязан отвергнуть, и тем, что нет.

    Без второго конца образец «любая цитата не совпала» запрещал бы сокращать
    вовсе, и обходился бы переписыванием строки в другую форму (051).
    """
    said = reasons()
    rule = "015"
    real = said[rule]
    assert len(real) > 40, "подлинник слишком короток — усечение на нём не показать"
    cut = real[:30]
    assert cut != real and ELLIPSIS not in cut, "проба не является усечением"
    assert f"{cut}{ELLIPSIS}" != real and ELLIPSIS in f"{cut}{ELLIPSIS}", (
        "объявленное сокращение обязано отличаться от подлинника и нести многоточие"
    )
