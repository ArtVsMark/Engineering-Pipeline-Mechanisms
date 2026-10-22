"""Версии Python из прогонов дерева — общим разбором YAML, во всех формах матрицы.

Переехало из каталога вместе с читателем версий значка (#1563). Формы — из
справки площадки «Using a matrix for your jobs» (210) и набора каталога:
список в строку с любыми кавычками, список столбцом, одно значение, ячейки
`include:`, комментарии у ячеек. Отказ — выражение вместо списка, ячейка не
формы X.Y, оси нет, матрицы нет: с адресом, а не молчанием (045).
"""

from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("python_versions.py")
policy = load_script("pipeline_checks.py")


def in_workflows(root: Path, *, preview: bool = False) -> list[tuple[str, tuple[int, int]]]:
    """(файл, версия) объявлений дерева — закрывающих или предварительных."""
    return [(one.flow, one.version) for one in module.read(root)[0] if one.preview == preview]


def refusals(root: Path) -> list[str]:
    """Отказы разбора дерева строкой с адресом."""
    return [str(one) for one in module.read(root)[1]]


def flow(root: Path, text: str, name: str = "ci.yml") -> Path:
    """Кладёт прогон в дерево и отдаёт корень."""
    folder = root / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return root


def matrix_flow(root: Path, matrix: str, extra: str = "") -> Path:
    """Прогон с одной матричной работой; версия шага — `${{ matrix.python }}`."""
    return flow(
        root,
        "on: push\njobs:\n  test-matrix:\n    runs-on: ubuntu-latest\n"
        "    strategy:\n      fail-fast: false\n" + matrix + "    steps:\n"
        "      - uses: actions/setup-python@v6\n        with:\n"
        "          python-version: ${{ matrix.python }}\n" + extra,
    )


def test_a_literal_version_is_read(tmp_path: Path) -> None:
    """Число буквой в любых кавычках — версия шага."""
    root = flow(
        tmp_path,
        "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n"
        "      - uses: actions/setup-python@v6\n        with:\n          python-version: '3.12'\n"
        "      - uses: actions/setup-python@v6\n        with:\n          python-version: 3.13\n",
    )
    assert in_workflows(root) == [("ci.yml", (3, 12)), ("ci.yml", (3, 13))]
    assert refusals(root) == []


def test_an_unquoted_ten_is_read_as_the_platform_reads_it(tmp_path: Path) -> None:
    """`3.10` без кавычек YAML и площадка читают как 3.1 — что гоняется, то и названо."""
    root = matrix_flow(tmp_path, "      matrix:\n        python: [3.10]\n")
    assert in_workflows(root) == [("ci.yml", (3, 1))]


def test_the_preview_mark_is_read_only_in_its_own_with(tmp_path: Path) -> None:
    """Пометка `allow-prereleases` — свойство своего `with:`, а не всего прогона."""
    root = flow(
        tmp_path,
        "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n"
        "      - uses: actions/setup-python@v6\n        with:\n          python-version: '3.14'\n"
        "      - uses: actions/setup-python@v6\n        with:\n"
        "          allow-prereleases: true\n          python-version: '3.15'\n",
    )
    assert in_workflows(root) == [("ci.yml", (3, 14))]
    assert in_workflows(root, preview=True) == [("ci.yml", (3, 15))]


@pytest.mark.parametrize(
    ("matrix", "versions"),
    [
        ('      matrix:\n        python: ["3.14", "3.15"]\n', [(3, 14), (3, 15)]),
        ("      matrix:\n        python: ['3.14', '3.15']\n", [(3, 14), (3, 15)]),
        ("      matrix:\n        python: [3.14, 3.15]\n", [(3, 14), (3, 15)]),
        (
            '      matrix:\n        python:\n          - "3.14"\n          - "3.15"\n',
            [(3, 14), (3, 15)],
        ),
        (
            '      matrix:\n        python: [\n          "3.14",\n          "3.15"]\n',
            [(3, 14), (3, 15)],
        ),
        ('      matrix:\n        python: "3.14"\n', [(3, 14)]),
        (
            '      matrix:\n        os: [ubuntu-latest]\n        python: ["3.14"]\n'
            '        include:\n          - python: "3.15"\n            os: ubuntu-latest\n',
            [(3, 14), (3, 15)],
        ),
        (
            "      matrix:\n        include:\n"
            '          - os: ubuntu-latest\n            python: "3.14"\n',
            [(3, 14)],
        ),
        (
            "      matrix:\n        python:\n"
            '          - "3.14"  # планка\n          - 3.15 # обязательная\n',
            [(3, 14), (3, 15)],
        ),
        ('      matrix:\n        python: ["3.14"]  # основные\n', [(3, 14)]),
    ],
)
def test_the_matrix_axis_is_read_in_every_form(
    tmp_path: Path, matrix: str, versions: list[tuple[int, int]]
) -> None:
    """Ось матрицы разбирается во всех формах справки площадки — их решает YAML, а не отступы."""
    root = matrix_flow(tmp_path, matrix)
    assert sorted(one for _, one in in_workflows(root)) == versions
    assert refusals(root) == []


@pytest.mark.parametrize(
    ("matrix", "why"),
    [
        ("      matrix:\n        python: ${{ fromJSON(needs.a.outputs.v) }}\n", "выражение"),
        ("      matrix: ${{ fromJSON(needs.a.outputs.m) }}\n", "выражение"),
        ('      matrix:\n        python: ["3.14", "3.x"]\n', "не формы X.Y"),
        ('      matrix:\n        py: ["3.14"]\n', "оси python в матрице нет"),
        ("      max-parallel: 1\n", "матрицы у работы нет"),
        (
            '      matrix:\n        python: ["3.14"]\n        include:\n'
            "          - python: ${{ fromJSON(needs.a.outputs.v) }}\n",
            "ячейка include",
        ),
    ],
)
def test_an_unreadable_axis_is_refused_with_its_address(
    tmp_path: Path, matrix: str, why: str
) -> None:
    """Ось не разобралась — отказ с адресом прогона и работы, а не молчаливый пропуск (045)."""
    root = matrix_flow(tmp_path, matrix)
    refused = refusals(root)
    assert len(refused) == 1 and why in refused[0], refused
    assert refused[0].startswith(".github/workflows/ci.yml: работа test-matrix:")
    assert in_workflows(root) == []


def test_a_preview_matrix_is_read_as_preview(tmp_path: Path) -> None:
    """`allow-prereleases` рядом с выражением матрицы — предварительная, число буквой не нужно."""
    root = matrix_flow(
        tmp_path, '      matrix:\n        python: ["3.16"]\n', "          allow-prereleases: true\n"
    )
    assert in_workflows(root) == []
    assert in_workflows(root, preview=True) == [("ci.yml", (3, 16))]


def test_an_unparsable_flow_is_an_input_error(tmp_path: Path) -> None:
    """Прогон не разбирается — ошибка входа общего разбора, а не «версий нет» (075)."""
    root = flow(tmp_path, "on: [push\n")
    with pytest.raises(policy.BadPolicy, match="не разбирается"):
        module.read(root)


def test_a_tree_without_workflows_declares_nothing(tmp_path: Path) -> None:
    """Прогонов нет — объявлений нет; судить это «нечем» — дело вызывающего (075)."""
    assert module.read(tmp_path) == ([], [])


def test_our_own_tree_declares_its_matrix(tmp_path: Path) -> None:
    """Живое дерево: читатель видит обязательную матрицу `ci.yml` и предрелиз `python-next.yml`."""
    root = Path(__file__).resolve().parent.parent
    cells, _ = policy.matrix_axis(
        root / ".github" / "workflows" / "ci.yml", "test-matrix", "python"
    )
    declared = {f"{a}.{b}" for flow_, (a, b) in in_workflows(root) if flow_ == "ci.yml"}
    assert set(cells) <= declared, (cells, declared)
    assert in_workflows(root, preview=True), "предрелизной версии в дереве не найдено"
    assert refusals(root) == []


def test_axis_versions_read_a_job_directly() -> None:
    """`axis_versions` судит разобранную работу: ячейки оси и include — номерами."""
    job = {"strategy": {"matrix": {"python": ["3.14"], "include": [{"python": "3.15"}]}}}
    assert module.axis_versions(job, "python") == ([(3, 14), (3, 15)], None)
    assert (
        module.axis_versions({}, "python")[1]
        == "python-version из matrix.python, а матрицы у работы нет"
    )


def test_a_declared_version_names_its_flow_job_and_kind(tmp_path: Path) -> None:
    """`Declared` несёт прогон, работу, версию и пометку предварительной."""
    root = matrix_flow(
        tmp_path, '      matrix:\n        python: ["3.16"]\n', "          allow-prereleases: true\n"
    )
    assert module.read(root)[0] == [module.Declared("ci.yml", "test-matrix", (3, 16), True)]


def test_a_multiline_version_declares_every_line(tmp_path: Path) -> None:
    """`python-version: |` — каждая строка блока, а не первая (взгляд на #1565)."""
    root = flow(
        tmp_path,
        "on: push\njobs:\n  t:\n    runs-on: ubuntu-26.04\n    steps:\n"
        "      - uses: actions/setup-python@v6\n        with:\n"
        "          python-version: |\n            3.13\n            3.14\n",
    )
    assert in_workflows(root) == [("ci.yml", (3, 13)), ("ci.yml", (3, 14))]
    assert refusals(root) == []


def test_a_version_file_is_a_refusal_with_address(tmp_path: Path) -> None:
    """`python-version-file` без `python-version` — отказ с адресом, а не «версий нет»."""
    root = flow(
        tmp_path,
        "on: push\njobs:\n  t:\n    runs-on: ubuntu-26.04\n    steps:\n"
        "      - uses: actions/setup-python@v6\n        with:\n"
        "          python-version-file: .python-version\n",
    )
    assert in_workflows(root) == []
    assert refusals(root) == [
        ".github/workflows/ci.yml: работа t: версия из файла .python-version — "
        "файл версии не читается, только python-version"
    ]
