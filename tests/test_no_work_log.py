"""В действующем документе нет журнала работ, а число в нём — не из памяти.

Два правила на один предмет — текст, который читают как действительность.

**024**: журнал сделанного живёт в `CHANGELOG.md`, статусы — в трекере, а
действующий документ говорит, как есть СЕЙЧАС. Раздел «что мы уже сделали»
внутри него превращает канон в летопись: читатель не может отличить описание
устройства от рассказа о пути к нему, и с каждым заходом такой раздел растёт.

**005**: число, вписанное в прозу руками, устаревает молча. У ответов каталогу
это особенно дорого: их читает не только окно, но и сам каталог, и устаревшее
число там выглядит утверждением проекта о себе.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.conftest import ROOT

#: Действующие документы: те, что описывают устройство СЕЙЧАС. Журнал и
#: фрагменты сюда не входят — они и есть летопись по построению.
LIVE_DOCS = sorted(
    [
        *(ROOT / "docs").rglob("*.md"),
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "README.md",
    ]
)
#: Заголовки, которыми журнал работ заводится в документе. Список закрытый и
#: назван словами: «похоже на историю» отвергло бы раздел «История решения» в
#: записи решения, где летопись как раз уместна (043).
LOG_HEADINGS = (
    "что сделано",
    "что уже сделано",
    "журнал работ",
    "история изменений",
    "хронология",
    "changelog",
)
HEADING_RE = re.compile(r"^#{1,4}\s*(?P<text>.+?)\s*$", re.M)


@pytest.mark.parametrize("path", LIVE_DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_a_live_document_has_no_work_log(path: Path) -> None:
    """У действующего документа нет раздела-летописи (024).

    Решения — исключение по построению: `docs/decisions/*` фиксируют, ЧТО было
    решено и почему, и их раздел «Последствия» — не журнал работ, а часть
    записи. Поэтому список заголовков закрытый, а не «всё, похожее на историю».
    """
    said = path.read_text(encoding="utf-8").lower()
    found = [
        heading.group("text")
        for heading in HEADING_RE.finditer(said)
        if any(mark in heading.group("text") for mark in LOG_HEADINGS)
    ]
    assert not found, (
        f"{path.relative_to(ROOT)}: раздел-летопись {found} — журнал сделанного живёт в "
        "CHANGELOG.md, а действующий документ говорит, как есть сейчас (024)"
    )


def test_the_answer_about_the_skeleton_matches_the_tree() -> None:
    """Число шагов в ответе каталогу совпадает с таблицей договора.

    Ответ по правилу 019 называл «четырнадцать шагов скелета», когда их стало
    шестнадцать. Такое число читает не только окно, но и сам каталог — там оно
    выглядит утверждением проекта о себе, и рассыхается молча (005).
    """
    answer = json.loads((ROOT / ".rules" / "bindings.json").read_text(encoding="utf-8"))
    said = str(answer["rules"]["019"].get("where") or "")
    doc = (ROOT / "docs" / "pipeline.md").read_text(encoding="utf-8")
    heading = next(line for line in doc.splitlines() if line.startswith("## Скелет:"))
    steps = {
        found.group()
        for row in doc.splitlines()
        if (found := re.match(r"\d+", row.strip("|").split("|")[0].strip()))
    }
    spelled = {14: "четырнадцать", 15: "пятнадцать", 16: "шестнадцать", 17: "семнадцать"}
    lowered = said.lower()
    wrong = [word for count, word in spelled.items() if word in lowered and count != len(steps)]
    assert not wrong, (
        f"ответ по 019 называет «{wrong[0]}» шагов, а в договоре их {len(steps)} "
        f"(«{heading}»). Число в прозе устаревает молча (005)"
    )
