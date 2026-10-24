"""Перепись правил о механизмах держит форму и называет живые гейты (220, #1459).

ЧТО СУДИТСЯ. Перепись `.rules/mechanism-rules.json` отвечает по каждому
правилу о механизмах, чем держится каждое место дерева: путь гейта, «исключено:
причина» или «не построено: что — замер». Навык
`.claude/skills/a-gate-obeys-every-rule` проходит гейт по ней, а не по памяти,
поэтому перепись обязана называть то, что есть: гейт, которого нет в дереве,
или гейт, в чьём коде места не видно, — ответ, на который навык опереться не
может (182).

ГРАНИЦА НАЗВАНА (046, 195). Полноту переписи гейт не судит: новое правило о
механизмах или новое место дописывается рукой. Охват гейта судится признаком —
словом места в его коде, — а не разбором того, что гейт с этим местом делает:
признак `hooks` совпал бы и с прозой о хуках. Образец формы — перепись
каталога (его `scripts/check_mechanism_scope.py`), взят приёмом, а не копией.
"""

import ast
import json
import re
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

paths = load_script("paths.py")
CENSUS: Final = ROOT / paths.MECHANISM_RULES
SKILL: Final = ROOT / ".claude" / "skills" / "a-gate-obeys-every-rule" / "SKILL.md"
#: Места дерева, где живут механизмы: ключи `места` и каждой записи правила.
PLACES: Final = frozenset({"paths.SOURCES", ".claude/hooks", ".github", "kit/data"})
#: Два ответа словом. После двоеточия — причина, у «не построено» — с замером.
EXCLUDED: Final = "исключено: "
UNBUILT: Final = "не построено: "
#: Замер у «не построено» — число и дата: без них долг неотличим от «не смотрели» (213).
MEASURED_RE: Final = re.compile(r"замер\s+\d{2}\.\d{2}\.\d{4}.*?\d")
RULE_RE: Final = re.compile(r"^\d{3}$")
#: Довод обхода, которым гейт ИСКЛЮЧАЕТ место: признак места его поглощает
#: («hooks» стоит и в `with_hooks=False`), и гейт, хуки явно исключивший, иначе
#: прошёл бы проверку «видит место» (взгляд на #1466).
#:
#: ОТНОШЕНИЕ, А НЕ ПОДСТРОКА (взгляд на #1471, правило 210). Прежде искалась
#: подстрока «with_hooks=False» во всём файле, и докстрока, называющая это
#: слово, делала гейт «исключившим» хуки: так у `tests/test_live_references.py`.
#: Теперь судится вызов: именованный довод `with_hooks` со значением `False`.
EXCLUDED_BY: Final = {".claude/hooks": "with_hooks"}


def excludes(code: str, keyword: str) -> bool:
    """Зовёт ли код что-либо с доводом `keyword=False` — по разбору, а не по тексту."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return any(
        one.arg == keyword and isinstance(one.value, ast.Constant) and one.value.value is False
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for one in node.keywords
    )


def census() -> dict[str, Any]:
    """Перепись целиком; не разбирается — отказ, а не пустота (075)."""
    said = json.loads(CENSUS.read_text(encoding="utf-8"))
    assert isinstance(said, dict), f"{CENSUS.name}: не словарь"
    return said


def judged(value: object, place: str, signs: dict[str, str], root: Path = ROOT) -> str:
    """Что не так со значением места; годное — пустая строка."""
    if isinstance(value, str) and value.startswith(EXCLUDED):
        return "" if value.removeprefix(EXCLUDED).strip() else "«исключено» без причины"
    if isinstance(value, str) and value.startswith(UNBUILT):
        return "" if MEASURED_RE.search(value) else "«не построено» без замера с датой и числом"
    if isinstance(value, dict):
        gate, sign = value.get("гейт"), value.get("признак")
    else:
        gate, sign = value, signs.get(place)
    if not isinstance(gate, str) or not isinstance(sign, str) or not sign:
        return f"значение не той формы: {value!r}"
    path = root / gate
    if not path.is_file():
        return f"гейта {gate} в дереве нет"
    code = path.read_text(encoding="utf-8")
    if sign not in code:
        return f"в коде {gate} нет признака места «{sign}»"
    if (excluding := EXCLUDED_BY.get(place)) and excludes(code, excluding):
        return f"гейт {gate} исключает место доводом «{excluding}=False»"
    return ""


def test_the_census_names_its_places_and_every_rule_once() -> None:
    """Места — объявленные, номер правила — в одном разделе, у правила — все места."""
    said = census()
    assert set(said.get("места") or {}) == PLACES, (
        f"места переписи: {sorted(said.get('места') or {})}"
    )
    rules, judgement = said.get("rules") or {}, said.get("суждение") or {}
    assert rules, "правил в переписи нет — навыку проходить нечем (075)"
    twice = sorted(set(rules) & set(judgement))
    assert not twice, f"правило и в переписи, и в суждении: {twice}"
    shapeless = sorted(one for one in (*rules, *judgement) if not RULE_RE.match(one))
    assert not shapeless, f"номер правила не той формы: {shapeless}"
    partial = {
        number: sorted(PLACES - set(one)) for number, one in rules.items() if set(one) != PLACES
    }
    assert not partial, f"у правила названы не все места: {partial}"
    empty = sorted(number for number, why in judgement.items() if not str(why).strip())
    assert not empty, f"суждение без причины: {empty}"


def test_every_gate_of_the_census_exists_and_sees_its_place() -> None:
    """Названный гейт есть в дереве, и признак места стоит в его коде (182)."""
    said = census()
    signs = said["места"]
    wrong = {
        f"{number} · {place}": problem
        for number, one in said["rules"].items()
        for place, value in one.items()
        if (problem := judged(value, place, signs))
    }
    assert not wrong, f"перепись называет то, на что навык опереться не может: {wrong}"
    gates = sum(
        not (isinstance(value, str) and value.startswith((EXCLUDED, UNBUILT)))
        for one in said["rules"].values()
        for value in one.values()
    )
    assert gates >= 10, f"гейтов в переписи {gates} — предикат смотрит не туда (075)"


def test_the_skill_reads_the_census() -> None:
    """Навык ссылается на перепись: читатель у данных есть, и он назван (155)."""
    assert CENSUS.relative_to(ROOT).as_posix() in SKILL.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "bad"),
    [
        ("исключено: хуки списков площадки не читают", False),
        ("исключено: ", True),
        ("не построено: ничто не судит — замер 17.10.2026: нарушений 0", False),
        ("не построено: ничто не судит", True),
        ("tests/conftest.py", False),
        ("tests/нет-такого.py", True),
        ({"гейт": "tests/conftest.py", "признак": "def code_files"}, False),
        ({"гейт": "tests/conftest.py", "признак": "слово, которого там нет"}, True),
        (7, True),
    ],
    ids=[
        "исключено",
        "исключено-без-причины",
        "не-построено",
        "не-построено-без-замера",
        "гейт",
        "гейта-нет",
        "гейт-с-признаком",
        "признака-нет",
        "не-та-форма",
    ],
)
def test_the_judge_tells_each_form(value: object, bad: bool) -> None:
    """Каждая из трёх форм значения судится, и каждый изъян называется."""
    assert bool(judged(value, "paths.SOURCES", {"paths.SOURCES": "code_files("})) is bad


def test_the_skill_path_is_a_live_skill() -> None:
    """Путь навыка — живой каталог навыков окна, а не придуманный адрес."""
    assert SKILL.is_file(), f"навыка {SKILL.relative_to(ROOT)} нет"
    assert Path(SKILL.parent).name == "a-gate-obeys-every-rule"


def test_a_gate_excluding_the_hooks_does_not_see_them(tmp_path: Path) -> None:
    """Признак «hooks» стоит и в `with_hooks=False`: исключивший хуки гейт их не видит (#1466)."""
    (tmp_path / "seeing.py").write_text("code_files()  # hooks\n", encoding="utf-8")
    (tmp_path / "blind.py").write_text("code_files(with_hooks=False)  # hooks\n", encoding="utf-8")
    sign = {".claude/hooks": "hooks"}
    assert judged("seeing.py", ".claude/hooks", sign, tmp_path) == ""
    assert "исключает" in judged("blind.py", ".claude/hooks", sign, tmp_path)


def test_a_gate_naming_the_exclusion_in_prose_still_sees_the_hooks(tmp_path: Path) -> None:
    """Слово `with_hooks=False` в докстроке — не исключение: судится вызов (`874ec3c`)."""
    (tmp_path / "prose.py").write_text(
        '"""Исключить хуки — только явным `with_hooks=False`."""\ncode_files()  # hooks\n',
        encoding="utf-8",
    )
    assert judged("prose.py", ".claude/hooks", {".claude/hooks": "hooks"}, tmp_path) == ""
