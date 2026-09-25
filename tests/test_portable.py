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
import re
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
    # Площадка исполняет прогон и с расширением `.yaml`: без него такой прогон
    # не попал бы в инвентарь, и полнота осталась бы зелёной молча (#768).
    for pattern in ("*.yml", "*.yaml"):
        found |= {p.relative_to(root).as_posix() for p in (root / paths.WORKFLOWS).glob(pattern)}
    found |= {p.relative_to(root).as_posix() for p in (root / ".rules").glob("*.json")}
    found |= {p.relative_to(root).as_posix() for p in (root / paths.SKILLS).iterdir() if p.is_dir()}
    found |= {p.relative_to(root).as_posix() for p in (root / "packages").iterdir() if p.is_dir()}
    return found


def issue_re(issues: list[int]) -> re.Pattern[str]:
    """Номер живой задачи буквами: `#23` и `issues/23`, но не `#230` и не `##23`.

    Форма адресом (`../../issues/23`) в проекте есть, и номер в ней прибит так
    же, как с решёткой (взгляд на #783, 195).
    """
    return re.compile(r"(?:(?<![\w#])#|\bissues/)(?:" + "|".join(map(str, issues)) + r")\b")


#: Метка плана пишется строкой, а не через `findings.marker`.
PLAN_MARKER_RE: Final = re.compile(r"<!-- (work-plan): ")
#: Метка реестра, объявленная механизмом.
REGISTRY_MARKER_RE: Final = re.compile(r"\bmarker\(\"([a-z-]+)\"\)")


def registry_markers(root: Path = ROOT) -> set[str]:
    """Метки живых задач, которые механизмы дерева ведут."""
    found: set[str] = set()
    for one in (root / paths.SCRIPTS).glob("*.py"):
        text = one.read_text(encoding="utf-8")
        found |= set(REGISTRY_MARKER_RE.findall(text)) | set(PLAN_MARKER_RE.findall(text))
    return found


def own_issue_numbers(data: dict[str, Any]) -> list[int]:
    """Номера живых задач, уже заведённых у площадки."""
    return sorted(number for number in data["own_issues"].values() if number)


def pinned_in(
    text: str, suffix: str, own: list[str], family: list[str], issues: list[int] | None = None
) -> list[int]:
    """Строки, где буквами стоит своё: имя проекта или номер его живой задачи.

    В коде докстроки и комментарии не считаются — это проза. В прогоне не
    считаются комментарии. В навыке и прочей прозе, которую читает агент,
    считается всё: там строка и есть инструкция. Общие для семьи имена
    вычитаются прежде поиска: `ArtVsMark/` внутри адреса каталога — не своё имя.
    """
    number = issue_re(issues) if issues else None

    def own_in(value: str) -> bool:
        if number and number.search(value):
            return True
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
    prose = suffix == ".md"
    return [
        at
        for at, line in enumerate(text.splitlines(), 1)
        if (prose or not line.strip().startswith("#")) and own_in(line)
    ]


def files_of(path: Path) -> list[Path]:
    """Файлы механизма: сам файл либо всё содержимое каталога (навык, пакет)."""
    if path.is_file():
        return [path]
    kinds = {".py", ".md", ".yml", ".yaml", ".json", ".toml"}
    return sorted(
        one
        for one in path.rglob("*")
        if one.is_file() and one.suffix in kinds and "__pycache__" not in one.parts
    )


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
        why = str(said.get("why", ""))
        if why.startswith("@") and why[1:] not in inventory().get("reasons", {}):
            wrong.append(f"{name}: ссылка на причину {why} никуда не ведёт")
    assert not wrong, "\n".join(wrong)


def test_a_mechanism_with_our_own_name_in_it_is_not_as_is() -> None:
    """Своё имя буквами — у соседа оно другое, и «как есть» было бы неправдой."""
    data = inventory()
    own, family, issues = data["own"], data["family"], own_issue_numbers(data)
    assert own and issues, "своих имён или номеров не объявлено — мерить прибитое нечем"
    wrong = []
    for name, said in data["answers"].items():
        if said["answer"] != "as-is":
            continue
        # КАТАЛОГ МЕРЯЕТСЯ ЦЕЛИКОМ, а не пропускается: навыки и пакеты — каталоги,
        # и прежде они отвечали `as-is` без замера (находка на #768).
        files = files_of(ROOT / name)
        assert files, f"{name}: у механизма нет ни одного файла — мерить нечего (075)"
        for one in files:
            text = one.read_text(encoding="utf-8")
            lines = pinned_in(text, one.suffix, own, family, issues)
            if lines:
                wrong.append(f"{one.relative_to(ROOT).as_posix()}:{lines}")
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


def test_a_shared_reason_is_written_once() -> None:
    """Причина, общая для нескольких ответов, — один раз в `reasons`, а не копией (071)."""
    answers = inventory()["answers"].values()
    whys = [str(one.get("why", "")) for one in answers if one.get("why")]
    repeated = {why for why in whys if not why.startswith("@") and whys.count(why) > 1}
    assert not repeated, f"одна причина переписана в несколько ответов: {sorted(repeated)}"


def test_the_measure_sees_our_issue_numbers_in_prose_the_agent_reads() -> None:
    """Номер живой задачи в строке навыка — прибитое; `#230` и комментарий прогона — нет."""
    assert pinned_in("реестр #23 и #230\n", ".md", ["Me/P"], [], [23]) == [1]
    assert pinned_in("о #230 и ##23\n", ".md", ["Me/P"], [], [23]) == []
    assert pinned_in("# реестр #23\nrun: echo #23\n", ".yml", ["Me/P"], [], [23]) == [2]
    code = '"""реестр #23 в прозе."""\nNOTE = "см. #23"\n'
    assert pinned_in(code, ".py", ["Me/P"], [], [23]) == [2]


def test_subjects_see_yaml_flows_and_directories(tmp_path: Path) -> None:
    """Предмет инвентаря: прогон `.yaml` и каталог навыка входят в него (#768)."""
    for part in ("scripts", ".github/workflows", ".rules", ".claude/skills/one", "packages/p"):
        (tmp_path / part).mkdir(parents=True)
    (tmp_path / ".github/workflows/a.yaml").write_text("on: push\n", encoding="utf-8")
    (tmp_path / ".github/workflows/b.yml").write_text("on: push\n", encoding="utf-8")
    found = subjects(tmp_path)
    assert ".github/workflows/a.yaml" in found, "прогон `.yaml` выпал из инвентаря"
    assert {".github/workflows/b.yml", ".claude/skills/one", "packages/p"} <= found


def test_a_directory_is_measured_by_its_files(tmp_path: Path) -> None:
    """Каталог механизма меряется по всем своим файлам, а не пропускается (#768)."""
    skill = tmp_path / "skill"
    (skill / "deep").mkdir(parents=True)
    (skill / "SKILL.md").write_text("чисто\n", encoding="utf-8")
    (skill / "deep" / "note.md").write_text("реестр #23\n", encoding="utf-8")
    (skill / "__pycache__").mkdir()
    (skill / "__pycache__" / "x.py").write_text("", encoding="utf-8")
    files = files_of(skill)
    assert [one.name for one in files] == ["SKILL.md", "note.md"]
    hits = [
        one
        for one in files
        if pinned_in(one.read_text(encoding="utf-8"), one.suffix, ["Me/P"], [], [23])
    ]
    assert [one.name for one in hits] == ["note.md"]


def test_every_registry_of_the_tree_has_its_number_line() -> None:
    """Реестр, объявленный меткой в scripts/, стоит в `own_issues` — с номером или `null`.

    Список номеров писался от руки: реестров с метками в scripts/ было девять
    (с планом), номеров в списке — шесть, и живой реестр дрейфа #193 выпал из
    замера (взгляд на #783). Теперь ключ — метка, и набор меток сверяется с
    деревом в обе стороны (005).
    """
    declared = set(inventory()["own_issues"])
    tree = registry_markers()
    assert tree, "меток в дереве не найдено — гейт доказывал бы только себя (075)"
    assert not tree - declared, f"реестры без строки в own_issues: {sorted(tree - declared)}"
    assert not declared - tree, (
        f"строки о реестрах, которых в дереве нет: {sorted(declared - tree)}"
    )


def test_the_measure_sees_an_issue_number_in_an_address() -> None:
    """Номер в адресе `issues/23` прибит так же, как `#23`; `issues/230` — нет."""
    number = issue_re([23])
    assert number.search("[#23](../../issues/23)")
    assert number.search("см. ../../issues/23")
    assert not number.search("../../issues/230")
    assert not number.search("tissues/23")
