"""Гейт опасных форм прогонов: форма краснеет, законное молчит, исключения не копятся (#1430)."""

import json
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import load_script

module = load_script("check_workflow_forms.py")

ROOT = Path(__file__).resolve().parent.parent
SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
CHECKOUT = f"actions/checkout@{SHA}"

CLEAN = f"""on: push
permissions:
  contents: read
jobs:
  a:
    permissions:
      issues: write
    steps:
      - uses: {CHECKOUT}
        with:
          persist-credentials: false
      - uses: ArtVsMark/Engineering-Incidents-Playbook@v2.1.0
"""


def tree(root: Path, flows: dict[str, str]) -> Path:
    """Дерево с прогонами `flows`."""
    folder = root / module.WORKFLOWS
    folder.mkdir(parents=True)
    for name, text in flows.items():
        (folder / name).write_text(text, encoding="utf-8")
    return root


def found(root: Path) -> list[str]:
    """Находки гейта по дереву."""
    said: list[str] = module.look(root)
    return said


def test_a_clean_workflow_is_silent(tmp_path: Path) -> None:
    """Права объявлены, токен не оставлен, стороннее на sha, своё по тегу — тишина."""
    assert found(tree(tmp_path, {"a.yml": CLEAN})) == []


@pytest.mark.parametrize(
    ("before", "after", "said"),
    [
        (
            "        with:\n          persist-credentials: false\n",
            "",
            "без явного persist-credentials",
        ),
        ("persist-credentials: false", "persist-credentials: true", "true без причины"),
        ("on: push", "on: [push, pull_request_target]", "pull_request_target"),
        (
            "    permissions:\n      issues: write\n",
            "    permissions: write-all\n",
            "write-all у джоба",
        ),
        ("permissions:\n  contents: read\n", "permissions: write-all\n", "write-all у файла"),
        (f"@{SHA}", "@v7", "стороннее действие не на полном sha"),
        ("@v2.1.0", "@main", "семейное не по тегу выпуска"),
    ],
    ids=[
        "токен-оставлен",
        "true-без-причины",
        "target",
        "write-all-джоб",
        "write-all-файл",
        "стороннее-по-тегу",
        "семейное-по-ветке",
    ],
)
def test_each_form_turns_red(tmp_path: Path, before: str, after: str, said: str) -> None:
    """Каждая форма перечня краснеет на своём нарушении — откат каждой половины."""
    assert before in CLEAN
    text = CLEAN.replace(before, after)
    told = found(tree(tmp_path, {"a.yml": text}))
    assert any(said in one for one in told), told


def test_a_job_without_any_rights_turns_red(tmp_path: Path) -> None:
    """Прав не объявлено ни у джоба, ни у файла — умолчание площадки шире нужного."""
    text = CLEAN.replace("permissions:\n  contents: read\n", "").replace(
        "    permissions:\n      issues: write\n", ""
    )
    assert any("прав не объявлено" in one for one in found(tree(tmp_path, {"a.yml": text})))


def test_true_with_a_reason_is_legal(tmp_path: Path) -> None:
    """`true` с причиной комментарием на строке — решение, а не забытый ключ."""
    text = CLEAN.replace("persist-credentials: false", "persist-credentials: true # толкает ветку")
    assert found(tree(tmp_path, {"a.yml": text})) == []


def test_a_read_only_job_may_keep_the_default(tmp_path: Path) -> None:
    """Джоб без права записи токена записи не держит — ключ ему не обязателен."""
    text = CLEAN.replace("      issues: write\n", "      issues: read\n").replace(
        "        with:\n          persist-credentials: false\n", ""
    )
    assert found(tree(tmp_path, {"a.yml": text})) == []


def test_a_composite_action_names_the_key_always(tmp_path: Path) -> None:
    """Составное действие прав не объявляет — его выгрузка судится как с правом записи."""
    folder = tmp_path / module.ACTIONS / "x"
    folder.mkdir(parents=True)
    (folder / "action.yml").write_text(
        f"runs:\n  using: composite\n  steps:\n    - uses: {CHECKOUT}\n", encoding="utf-8"
    )
    assert any("без явного" in one for one in found(tmp_path))


def exceptions(root: Path, said: object) -> None:
    """Кладёт файл исключений проекта."""
    (root / module.paths.WORKFLOW_FORMS).parent.mkdir(parents=True, exist_ok=True)
    (root / module.paths.WORKFLOW_FORMS).write_text(json.dumps(said), encoding="utf-8")


def test_an_exception_with_its_place_allows_and_a_stale_one_turns_red(tmp_path: Path) -> None:
    """Исключение с местом разрешает; пережившее место — находка, а не тихое разрешение (195)."""
    uses = "ArtVsMark/Engineering-Incidents-Playbook@main"
    root = tree(tmp_path, {"a.yml": CLEAN.replace("@v2.1.0", "@main")})
    where = ".github/workflows/a.yml"
    exceptions(root, {"branch": [{"file": where, "uses": uses, "why": "причина"}]})
    assert module.look(root) == []
    (root / module.WORKFLOWS / "a.yml").write_text(CLEAN, encoding="utf-8")
    assert module.look(root) == [f"исключение пережило место: {where} → {uses}"]


def test_an_exception_is_keyed_by_the_path_not_the_name(tmp_path: Path) -> None:
    """Исключение одного файла не разрешает форму в одноимённом другом (взгляд на #1634)."""
    uses = "ArtVsMark/Engineering-Incidents-Playbook@main"
    text = CLEAN.replace("@v2.1.0", "@main")
    root = tree(tmp_path, {"a.yml": text})
    exceptions(root, {"branch": [{"file": "a.yml", "uses": uses, "why": "имя, а не путь"}]})
    told = module.look(root)
    assert any(one.startswith(".github/workflows/a.yml:a:") for one in told), told


@pytest.mark.parametrize(
    "line",
    [
        'persist-credentials: "true"',
        "persist-credentials: 'true'",
        "persist-credentials: true #",
        "persist-credentials: true #   ",
    ],
    ids=["кавычки", "одинарные", "голая-решётка", "решётка-с-пробелами"],
)
def test_true_without_words_of_reason_turns_red(tmp_path: Path, line: str) -> None:
    """`true` в кавычках или с пустым комментарием — без причины (взгляд на #1634)."""
    text = CLEAN.replace("persist-credentials: false", line)
    assert any("без причины" in one for one in found(tree(tmp_path, {"a.yml": text})))


def test_true_in_a_flow_mapping_is_judged_too(tmp_path: Path) -> None:
    """Запись в строку `{persist-credentials: true}` судится, как блочная."""
    text = CLEAN.replace(
        "        with:\n          persist-credentials: false\n",
        "        with: {persist-credentials: true}\n",
    )
    assert any("без причины" in one for one in found(tree(tmp_path, {"a.yml": text})))


@pytest.mark.parametrize(
    "said",
    [[], {"branch": [{"file": "a.yml", "uses": "x@main"}]}, {"target": ["a.yml"]}],
    ids=["не-словарь", "без-причины", "не-запись"],
)
def test_a_bad_exceptions_file_is_not_run(tmp_path: Path, said: object) -> None:
    """Исключение без причины или не той формы — «не отработал», а не разрешение (045)."""
    root = tree(tmp_path, {"a.yml": CLEAN})
    exceptions(root, said)
    with pytest.raises(module.NotRun):
        module.allowed(root)


def test_an_unparsed_file_is_not_run(tmp_path: Path) -> None:
    """Битый YAML — «не отработал», а не «чисто» и не «найдено» (039)."""
    tree(tmp_path, {"a.yml": "on: [\n"})
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN


def test_our_tree_is_clean() -> None:
    """Дерево механизмов проходит свой гейт: перечень починен, исключения живы."""
    assert module.look(ROOT) == []
    assert module.main(["--root", str(ROOT)]) == module.EXIT_OK


def test_the_gate_refuses_a_red_tree_with_its_exit(tmp_path: Path) -> None:
    """Прогон отказа: дерево с формой при `--enforce` — «отвергнуто», а не «чисто» (140)."""
    root = tree(tmp_path, {"a.yml": CLEAN.replace("@v2.1.0", "@main")})
    assert module.main(["--root", str(root), "--enforce"]) == module.EXIT_REJECTED


def test_without_enforce_a_form_is_a_warning_with_its_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """У потребителя без `--enforce` форма — предупреждение, а не красный шаг (`c6f9696`).

    Дерево, писанное без гейта, иначе краснело бы с первым подъёмом тега (051);
    найденное при этом не молчит: аннотация на каждую форму и итог числом.
    """
    root = tree(tmp_path, {"a.yml": CLEAN.replace("@v2.1.0", "@main")})
    assert module.main(["--root", str(root)]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert said.count("::warning::") == len(found(root)) >= 1, said
    assert "предупреждено: опасных форм прогонов" in said, said


@pytest.mark.parametrize(
    ("uses", "said"),
    [
        ("./local", ""),
        ("docker://alpine:3", "образ контейнера не по digest"),
        ("docker://alpine@sha256:" + "a" * 64, ""),
        (CHECKOUT, ""),
        ("actions/checkout@v7", "стороннее действие не на полном sha"),
        ("ArtVsMark/X/.github/workflows/s.yml@v1.10.0", ""),
        ("artvsmark/X@main", "семейное не по тегу выпуска и не по sha"),
        ("ArtVsMark/X@v1", "семейное не по тегу выпуска и не по sha"),
        ("ArtVsMark/X@v1.10", "семейное не по тегу выпуска и не по sha"),
    ],
)
def test_pin_problem_names_each_kind(uses: str, said: str) -> None:
    """Своё по пути и `sha` законны, семейное — по тегу, стороннее — только `sha`."""
    assert module.pin_problem(uses) == said


def test_writes_and_uses_of_read_the_job() -> None:
    """Право записи — любое `write` или `write-all`; `uses:` — вызов прогона и шаги."""
    assert module.writes("write-all") and module.writes({"issues": "write"})
    assert not module.writes({"contents": "read"}) and not module.writes(None)
    job = {"uses": "o/r/.github/workflows/s.yml@v1", "steps": [{"uses": "a/b@c"}, {"run": "x"}]}
    assert module.uses_of(job) == ["o/r/.github/workflows/s.yml@v1", "a/b@c"]
    assert module.uses_of({"steps": "не список"}) == []


def test_an_expression_instead_of_a_value_turns_red(tmp_path: Path) -> None:
    """`persist-credentials: ${{ inputs.x }}` — выражение без причины, не значение (`c4b082e`)."""
    text = CLEAN.replace("persist-credentials: false", "persist-credentials: ${{ inputs.keep }}")
    assert any("выражение вместо значения" in one for one in found(tree(tmp_path, {"a.yml": text})))


@pytest.mark.parametrize(
    "extra",
    [
        "      # persist-credentials: true здесь нужен бы для толчка\n",
        "      - run: |\n          echo persist-credentials: true\n",
    ],
    ids=["комментарий", "тело-run"],
)
def test_true_outside_a_key_is_not_a_form(tmp_path: Path, extra: str) -> None:
    """Слова `persist-credentials: true` в комментарии или в теле `run:` — не запись (`016a18a`).

    Значение у выгрузки — `false`; прежний разбор по всему тексту краснел и тут.
    """
    text = CLEAN + extra
    assert found(tree(tmp_path, {"a.yml": text})) == []


def test_true_among_other_keys_of_a_flow_mapping_is_judged(tmp_path: Path) -> None:
    """`with: {fetch-depth: 0, persist-credentials: true}` — ключ не первым, судится тоже."""
    text = CLEAN.replace(
        "        with:\n          persist-credentials: false\n",
        "        with: {fetch-depth: 0, persist-credentials: true}\n",
    )
    assert any("без причины" in one for one in found(tree(tmp_path, {"a.yml": text})))


STEP: Final = f"      - uses: {CHECKOUT}\n        with:\n          persist-credentials: false\n"


@pytest.mark.parametrize(
    ("step", "red"),
    [
        (f"      - {{uses: {CHECKOUT}, with: {{persist-credentials: true}}}}\n", True),
        (f"      - {{uses: {CHECKOUT}, with: {{persist-credentials: true}}}} # толкает\n", False),
        (
            f"      - uses: {CHECKOUT}\n        with:\n          persist-credentials:\n"
            "            true\n",
            True,
        ),
        (
            f"      - uses: {CHECKOUT}\n        with:\n          persist-credentials:\n"
            "            true # причина на строке значения\n",
            False,
        ),
        (
            f"      - uses: {CHECKOUT}\n        with: &keep\n"
            "          persist-credentials: true # толкает\n"
            f"      - uses: {CHECKOUT}\n        with: *keep\n",
            False,
        ),
        (
            f"      - uses: {CHECKOUT}\n        with: &keep\n"
            "          persist-credentials: true\n"
            f"      - uses: {CHECKOUT}\n        with: *keep\n",
            True,
        ),
    ],
    ids=[
        "в-строку-без-причины",
        "в-строку-с-причиной",
        "ниже-без-причины",
        "ниже-с-причиной",
        "якорь-с-причиной",
        "якорь-без-причины",
    ],
)
def test_a_true_is_judged_on_the_line_of_its_value(tmp_path: Path, step: str, red: bool) -> None:
    """Строку значения даёт разбор: шаг в строку, значение ниже, якорь (взгляды на #1650).

    Прежде строку ключа искали образцом по тексту, и каждая из этих форм
    уходила без суда либо краснела законная; теперь их судит метка узла.
    """
    text = CLEAN.replace(STEP, step)
    assert text != CLEAN
    told = found(tree(tmp_path, {"a.yml": text}))
    assert any("без причины" in one for one in told) is red, told


def test_a_reason_on_another_actions_key_does_not_cover_a_checkout(tmp_path: Path) -> None:
    """`persist-credentials: true # …` у чужого действия не прикрывает выгрузку (взгляд на #1650).

    Сверка счётом строк уравнивалась такой строкой, и выгрузка в строку
    уходила без суда; метка узла видит только значение у `actions/checkout`.
    """
    other = (
        "      - uses: some/other@" + SHA + "\n        with:\n"
        "          persist-credentials: true # не выгрузка\n"
    )
    step = f"      - {{uses: {CHECKOUT}, with: {{persist-credentials: true}}}}\n"
    text = CLEAN.replace(STEP, other + step)
    told = found(tree(tmp_path, {"a.yml": text}))
    assert any("без причины" in one for one in told), told
