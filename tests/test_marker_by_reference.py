"""Метка, по которой механизм находит свою запись, цитируется ссылкой, а не буквами (209).

Метка живой задачи или комментария — константа: по ней механизм узнаёт свою
запись среди чужих. Переписанные буквами в другом месте, они совпадают с
константой в день записи и расходятся при первой её правке. Молча: читатель
по буквам просто перестаёт находить, а тест по буквам проверяет старую метку.

ПРЕДМЕТ ЗАКРЫТ И ВЫВОДИТСЯ ИЗ ДЕРЕВА, а не перечислен здесь (005). Метка — это
значение константы `*MARKER` уровня модуля в `scripts/`: строка, начатая
комментарием разметки, или вызов `findings.marker("<имя>")`. Начало метки —
открытие комментария и имя до двоеточия. Замер 01.10.2026: таких меток 12
(десять меток живых задач, которые называет ответ на 209, и две метки
комментариев: проверки премисы и застрявшего взгляда).

ДВЕ ФОРМЫ ПЕРЕПИСЫВАНИЯ, обе судятся в `scripts/`, `tests/` и `.github/`:

* начало метки буквами в строке — в коде, данных, докстроке, прогоне;
* вызов `marker("<имя>")` вне определения константы, если имя объявлено
  меткой, — та же метка, собранная заново: переименуй её — и копия молча
  разойдётся. Вымышленное имя (`marker("x")` в данных проверки) — не копия:
  метки с таким именем нет, и судить нечего (первая редакция назвала два таких
  места `tests/test_work_plan.py` и была сужена прогоном).

Законно ровно одно место — определение константы. Замер 01.10.2026, до
починки: семь мест вне определений. Начало метки буквами — четыре: два
контрпримера (`tests/test_findings.py`, `tests/test_work_plan.py`) и две
цитаты в докстроках (`tests/test_items_left.py`, `tests/test_work_plan.py`).
Пересборка из имени — три в `tests/test_task_shape.py`. Контрпримеры теперь
выводятся из константы, цитаты называют её имя, пересборка заменена ссылкой.

ГРАНИЦА НАЗВАНА (195). Обход — всё, что читает машина: `scripts/`, `tests/`,
весь `.github/` и `.pipeline.yml`. Проза для людей — `docs/`, `.claude/`,
корневые документы — в обход не входит: там метку называют именем константы,
а буквы цитаты законны в истории. Замер 01.10.2026 по ним: начала меток — 0.
Метка, разобранная по частям (`"<!-" + "- имя"`),
и метка, которую константа не объявляет, гейтом не видны; прочие
константы-тексты (`FIXCHECK_MARKER`, пометки прогонов) держит чтение, как и
говорит само правило: «общего гейта нет и не будет».
"""

import ast
import re
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, walk, walk_deep

#: Где объявляются метки — рабочий код.
DECLARED_IN: Final = ROOT / "scripts"

#: Где метку могли бы переписать: код, проверки, прогоны и прочее, что читает
#: машина, — весь `.github/` (не только `*.yml`) и `.pipeline.yml` (взгляд на
#: #1009).
JUDGED: Final = (ROOT / "scripts", ROOT / "tests", ROOT / ".github")
JUDGED_FILES: Final = (ROOT / ".pipeline.yml",)

#: Открытие комментария разметки: с него начинается каждая метка.
OPENING: Final = "<!-- "

#: Имя метки сразу за открытием комментария. Начало метки — открытие и имя,
#: а не «всё до двоеточия»: метка без двоеточия иначе стала бы своим началом
#: целиком, и читатель буквами `"<!-- имя" in body` прошёл бы мимо гейта
#: (взгляд на #1009).
NAME_AFTER_OPENING: Final = re.compile(rf"^{re.escape(OPENING)}([\w-]+)")

#: Имя функции, собирающей метку из имени (`findings.marker`).
BUILDER: Final = "marker"


def builder_name(call: ast.AST) -> str | None:
    """Имя, из которого вызов `marker("<имя>")` собирает метку, — или `None`."""
    if not isinstance(call, ast.Call) or len(call.args) != 1:
        return None
    func = call.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    first = call.args[0]
    if called == BUILDER and isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def declared(path: Path) -> dict[str, int]:
    """Начала меток, объявленных модулем, и строка определения каждой."""
    found: dict[str, int] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        target: ast.expr | None = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        value = getattr(node, "value", None)
        if not isinstance(target, ast.Name) or not target.id.endswith("MARKER") or value is None:
            continue
        name = builder_name(value)
        if name is not None:
            found[OPENING + name] = node.lineno
        elif isinstance(value, ast.Constant) and (
            named := NAME_AFTER_OPENING.match(str(value.value))
        ):
            found[OPENING + named.group(1)] = node.lineno
    return found


def heads(root: Path = DECLARED_IN) -> dict[str, tuple[str, int]]:
    """Все начала меток дерева: начало → место определения."""
    return {
        head: (path.relative_to(ROOT).as_posix(), line)
        for path in walk(root, "*.py")
        for head, line in declared(path).items()
    }


def mentions(text: str, head: str) -> bool:
    """Строка называет начало метки целиком, а не префикс другого имени."""
    return re.search(re.escape(head) + r"(?![\w-])", text) is not None


def respelled_in(path: Path, known: dict[str, tuple[str, int]], root: Path = ROOT) -> list[str]:
    """Места модуля или прогона, где метка написана буквами или собрана из имени."""
    where = path.relative_to(root).as_posix()
    own = {line for head, (at, line) in known.items() if at == where}
    text = path.read_text(encoding="utf-8")
    found: list[str] = []
    if path.suffix != ".py":
        for number, line in enumerate(text.splitlines(), 1):
            found += [f"{where}:{number}: {head}" for head in known if mentions(line, head)]
        return found
    for node in ast.walk(ast.parse(text)):
        at = int(getattr(node, "lineno", 0))
        if at in own:
            continue
        name = builder_name(node)
        if name is not None and OPENING + name in known:
            found.append(f"{where}:{at}: {BUILDER}({name!r})")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [f"{where}:{at}: {head}" for head in known if mentions(node.value, head)]
    return found


def judged() -> list[Path]:
    """Файлы, где метку могли переписать: модули, проверки, прогоны, настройки."""
    found = [
        path
        for place in JUDGED
        for path in walk_deep(place, "*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    return [*found, *JUDGED_FILES]


def test_the_gate_found_its_subject() -> None:
    """Меток в дереве десяток, а не ноль: иначе гейт судил бы пустоту (075)."""
    assert len(heads()) >= 10


def test_no_marker_is_respelled() -> None:
    """Метку берут у константы: ни букв её начала, ни пересборки из имени (209)."""
    known = heads()
    found = [one for path in judged() for one in respelled_in(path, known)]
    assert not found, "метка переписана, а не взята у константы (209):\n  " + "\n  ".join(found)


def test_both_forms_are_seen_and_a_reference_is_not(tmp_path: Path) -> None:
    """Обе формы краснеют, ссылка на константу и чужое имя с тем же началом — нет."""
    head = OPENING + "probe"
    (tmp_path / "mark.py").write_text(
        f'MARKER = "{head}: держит механизм -->"\nOTHER_MARKER = marker("built")\n',
        encoding="utf-8",
    )
    known = {head: ("mark.py", 1), OPENING + "built": ("mark.py", 2)}
    assert respelled_in(tmp_path / "mark.py", known, tmp_path) == []
    reader = tmp_path / "reader.py"
    reader.write_text(
        f'import mark\nA = mark.MARKER\nB = "{head}er -->"\nC = marker("x")\n', encoding="utf-8"
    )
    assert respelled_in(reader, known, tmp_path) == [], "чужое или вымышленное имя названо"
    reader.write_text(f'A = "{head} -->"\nB = findings.marker("built")\n', encoding="utf-8")
    assert respelled_in(reader, known, tmp_path) == [
        f"reader.py:1: {head}",
        "reader.py:2: marker('built')",
    ]
    flow = tmp_path / "flow.yml"
    flow.write_text(f"run: grep '{head}' body\n", encoding="utf-8")
    assert respelled_in(flow, known, tmp_path) == [f"flow.yml:1: {head}"]


def test_a_marker_is_found_by_either_declaration(tmp_path: Path) -> None:
    """Метка объявляется строкой или вызовом `marker`, а прочие константы не метки."""
    (tmp_path / "mod.py").write_text(
        'from typing import Final\nA_MARKER: Final = "<!-- a: x -->"\nB_MARKER = marker("b")\n'
        'FIX_MARKER = "ЗАХОД: проверка"\nNOT_A_NAME = "<!-- c: y -->"\n',
        encoding="utf-8",
    )
    assert declared(tmp_path / "mod.py") == {"<!-- a": 2, "<!-- b": 3}


def test_a_marker_without_a_colon_has_its_name_for_a_head(tmp_path: Path) -> None:
    """Начало метки — открытие и имя, а не вся строка без двоеточия (#1009)."""
    (tmp_path / "mod.py").write_text('C_MARKER = "<!-- c держит механизм -->"\n', encoding="utf-8")
    assert declared(tmp_path / "mod.py") == {"<!-- c": 1}
