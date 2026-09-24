"""Инвентарь переносимого: ответ по каждому механизму, и прибитое не зовётся «как есть».

ЗАЧЕМ ОН ЕСТЬ. Проект переносится к соседям целиком, а переноса не было ни разу:
«переносимо» было словом, а не замером (139, #642). Инвентарь — это
`.rules/portable.json`, по образцу `.pipeline.yml`: ответ по КАЖДОМУ механизму,
а не по вспомненным (129), и молчание состоянием не является (154).

ЧТО ДЕРЖИТ ГЕЙТ. Полноту (новый механизм без ответа краснеет), форму ответа
(`configured` называет файл, `ours` — причину) и одно измеримое: механизм, в
строках которого буквами стоит СВОЁ имя проекта, ответом `as-is` быть не может —
у соседа это имя другое, и переезд сломал бы его молча. Верен ли ответ `as-is`
у остального, машина не знает: это чтение, и оно за человеком.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Final

from tests.conftest import ROOT, load_script

paths = load_script("paths.py")

ANSWERS: Final = frozenset({"as-is", "configured", "ours", "unreviewed"})


def inventory() -> dict[str, Any]:
    """Инвентарь как он лежит в дереве."""
    data: dict[str, Any] = json.loads((ROOT / paths.PORTABLE).read_text(encoding="utf-8"))
    return data


def subjects(root: Path = ROOT) -> set[str]:
    """Механизмы дерева, о которых инвентарь обязан ответить."""
    found = {p.relative_to(root).as_posix() for p in (root / paths.SCRIPTS).glob("*.py")}
    found |= {p.relative_to(root).as_posix() for p in (root / paths.WORKFLOWS).glob("*.yml")}
    found |= {p.relative_to(root).as_posix() for p in (root / ".rules").glob("*.json")}
    found |= {p.relative_to(root).as_posix() for p in (root / paths.SKILLS).iterdir() if p.is_dir()}
    found |= {p.relative_to(root).as_posix() for p in (root / "packages").iterdir() if p.is_dir()}
    return found


def pinned_in(text: str, suffix: str, own: list[str], family: list[str]) -> list[int]:
    """Строки, где буквами стоит своё имя проекта: константы кода или строки прогона.

    Докстроки и комментарии не считаются — это проза. Общие для семьи имена
    вычитаются прежде поиска: `ArtVsMark/` внутри адреса каталога — не своё имя.
    """

    def own_in(value: str) -> bool:
        for name in family:
            value = value.replace(name, "")
        return any(name in value for name in own)

    if suffix == ".py":
        tree = ast.parse(text)
        docs = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
        }
        return sorted(
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docs
            and own_in(node.value)
        )
    return [
        number
        for number, line in enumerate(text.splitlines(), 1)
        if not line.strip().startswith("#") and own_in(line)
    ]


def test_every_mechanism_has_an_answer_and_no_answer_is_orphaned() -> None:
    """Ответ по каждому механизму и ни одного — о несуществующем (129, 154)."""
    declared = set(inventory()["answers"])
    tree = subjects()
    assert tree, "предмета нет — гейт доказывал бы только себя (075)"
    assert not tree - declared, f"механизмы без ответа о переносе: {sorted(tree - declared)}"
    assert not declared - tree, f"ответы о том, чего в дереве нет: {sorted(declared - tree)}"


def test_every_answer_has_its_form() -> None:
    """`configured` называет файлы, и они есть; `ours` называет причину."""
    wrong: list[str] = []
    for name, said in inventory()["answers"].items():
        answer = said.get("answer")
        if answer not in ANSWERS:
            wrong.append(f"{name}: ответ «{answer}» вне {sorted(ANSWERS)}")
        elif answer == "configured":
            where = said.get("where") or []
            missing = [one for one in where if not (ROOT / one).exists()]
            if not where or missing:
                wrong.append(
                    f"{name}: `configured` без файла ответа или с несуществующим {missing}"
                )
        elif answer == "ours" and not str(said.get("why", "")).strip():
            wrong.append(f"{name}: `ours` без причины — неотличимо от «не дошли руки»")
    assert not wrong, "\n".join(wrong)


def test_a_mechanism_with_our_own_name_in_it_is_not_as_is() -> None:
    """Своё имя буквами — у соседа оно другое, и «как есть» было бы неправдой."""
    data = inventory()
    own, family = data["own"], data["family"]
    assert own, "своих имён не объявлено — мерить прибитое нечем"
    wrong = []
    for name, said in data["answers"].items():
        path = ROOT / name
        if not path.is_file() or said["answer"] != "as-is":
            continue
        lines = pinned_in(path.read_text(encoding="utf-8"), path.suffix, own, family)
        if lines:
            wrong.append(f"{name}:{lines}")
    assert not wrong, f"своё имя буквами при ответе `as-is`: {wrong}"


def test_the_pinning_measure_sees_code_and_skips_prose() -> None:
    """Мерило прибитого: константа кода видна, докстрока и адрес каталога — нет."""
    own, family = ["Me/Project", "Me/"], ["Me/Catalogue"]
    code = (
        '"""Me/Project в прозе."""\nOURS = "Me/Project"\nCAT = "Me/Catalogue"\nPREFIX = ("Me/",)\n'
    )
    assert pinned_in(code, ".py", own, family) == [2, 4]
    flow = "# Me/Project в комментарии\nuses: Me/Project/.github/x.yml@v1\nuses: Me/Catalogue@v1\n"
    assert pinned_in(flow, ".yml", own, family) == [2]


def test_the_seams_of_the_filling_and_the_port_check_are_named() -> None:
    """Три шва наполнения и проверка переноса названы: файлом или словом `none` с причиной."""
    data = inventory()
    for part in ("filling", "verified_by"):
        named = {key: value for key, value in data[part].items() if key != "_"}
        assert named, f"{part}: пусто"
        for key, value in named.items():
            assert value.get("where"), f"{part}.{key}: без адреса"
            assert str(value.get("why", "")).strip(), f"{part}.{key}: без причины"
            if value["where"] != "none":
                assert (ROOT / value["where"]).exists(), f"{part}.{key}: {value['where']} нет"
    assert set(data["filling"]) - {"_"} == {
        "what-is-checked",
        "inner-approaches",
        "required-and-advisory",
    }
