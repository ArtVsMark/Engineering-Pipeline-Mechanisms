#!/usr/bin/env python3
"""Версии Python, которые объявляют прогоны дерева, — одним разбором YAML на всех.

ПЕРЕЕХАЛО ИЗ КАТАЛОГА (#1563, этап 3 ArtVsMark/Engineering-Incidents-Playbook#930):
значку Python нужно знать, на каких версиях проект гоняет набор. У каталога
это отвечал `check_python_version.in_workflows` — построчным разбором текста
прогона по отступам. Здесь ответ тот же, а разбор — общий `pipeline_checks.run_of`:
второй разбор той же формы был бы вторым её пониманием
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md),
[214](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/214-one-territory-one-parse.md)).

ЧТО СЧИТАЕТСЯ ОБЪЯВЛЕНИЕМ. Шаг с `with.python-version`:
  * число `X.Y` (в кавычках или без) — эта версия;
  * `${{ matrix.<ось> }}` — каждая ячейка оси матрицы своей работы и ячейки
    `include:` с этой осью (каталог #926); форма оси — список, одно значение,
    столбец — решает YAML, а не отступы;
  * многострочный блок (`python-version: |`) — каждая его строка, как выше;
  * `allow-prereleases: true` в том же `with:` — версия предварительная.

И ВЫЗОВ ОБЩЕГО ШАГА ПРОБЫ (#1556). Работа, зовущая `step-python-next.yml`
со входом `python`, объявляет версию тем же разбором строки — ось её
матрицы или число — и всегда предварительную: шаг ставит её с
`allow-prereleases`. Матрица у вызывающего, а `setup-python` — в шаге, и без
этого правила версия выпала бы из значка молча.

`python-version-file` без `python-version` — отказ с адресом: файл версии
разбор не читает, и версия из него не выводится. Строка не числом и не осью
(`3.x`, `pypy3.11`) версией не считается: со значком её не сравнить.

ЧИСЛО БЕЗ КАВЫЧЕК ЧИТАЕТСЯ ТАК, КАК ЕГО ПРОЧТЁТ ПЛОЩАДКА. `python: [3.10]` YAML
даёт числом 3.1, и площадка передаст setup-python именно `3.1`. Каталог
находил здесь 3.10 по тексту — то, чего прогон не гоняет. Здесь ячейка берётся
значением разбора: что объявлено, то и гоняется.

ОТКАЗ, А НЕ МОЛЧАНИЕ (045). Ось не разобралась — матрицы у работы нет, оси нет,
значение — выражение (`fromJSON(…)`), ячейка не формы X.Y, — это отказ с
адресом прогона и работы. Версия из него не выводится, а вызывающий называет
его: значок — предупреждением, гейт — находкой. `exclude:` не разбирается —
это граница: вычеркнуть версию целиком им можно, но так не пишут.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import paths
import pipeline_checks

#: Где прогоны лежат от корня дерева — адрес объявлен в `paths` (096).
WORKFLOWS: Final = paths.WORKFLOWS
#: Число версии в начале значения: `3.14`, `"3.14"`, `3.14-dev` — как у каталога.
LITERAL_RE: Final = re.compile(r"^(\d+)\.(\d+)")
#: Ячейка матрицы — ровно `X.Y`: иное (`3.x`, `pypy3.11`) со значком не сравнить.
CELL_RE: Final = re.compile(r"^(\d+)\.(\d+)$")
#: Версия из матрицы работы: `${{ matrix.python }}`.
FROM_MATRIX_RE: Final = re.compile(r"^\$\{\{\s*matrix\.([\w-]+)\s*\}\}$")
#: Выражение площадки вместо значения.
EXPRESSION: Final = "${{"
#: Общий шаг пробы предрелизной ветки: его вход `python` — объявление версии.
NEXT_STEP: Final = "step-python-next.yml"


@dataclass(frozen=True)
class Declared:
    """Версия, объявленная шагом прогона."""

    flow: str
    job: str
    version: tuple[int, int]
    preview: bool


@dataclass(frozen=True)
class Refused:
    """Ось матрицы, из которой версию вывести нельзя, — с адресом."""

    flow: str
    job: str
    why: str

    def __str__(self) -> str:
        return f"{WORKFLOWS / self.flow}: работа {self.job}: {self.why}"


def _flows(root: Path) -> list[Path]:
    """Прогоны дерева по имени — `.yml` и `.yaml`, как их читает площадка."""
    folder = root / WORKFLOWS
    return sorted(folder.glob("*.y*ml")) if folder.is_dir() else []


def _steps(job: Any) -> Iterator[dict[str, Any]]:
    """Шаги работы, которые словари: прочее разбор пропускает, а не падает на нём."""
    steps = (job.get("steps") or []) if isinstance(job, dict) else []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            yield step


def _preview(given: dict[str, Any]) -> bool:
    """Пометка предварительной: `allow-prereleases: true` в том же `with:`."""
    return str(given.get("allow-prereleases", "")).strip().lower() == "true"


def _cells(job: dict[str, Any], axis: str) -> tuple[list[str], str | None]:
    """Сырые ячейки оси матрицы работы и её `include:`; (ячейки, отказ)."""
    strategy = job.get("strategy")
    matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
    if not isinstance(matrix, dict):
        if isinstance(matrix, str) and matrix.strip().startswith(EXPRESSION):
            return [], "матрица — выражение, а не список: версии не с чем сверить"
        return [], f"python-version из matrix.{axis}, а матрицы у работы нет"
    cells: list[str] = []
    found = False
    if axis in matrix:
        found = True
        said = matrix[axis]
        if isinstance(said, str) and said.strip().startswith(EXPRESSION):
            return [], f"matrix.{axis} — выражение, а не список: версии не с чем сверить"
        cells += [str(one) for one in (said if isinstance(said, list) else [said])]
    include = matrix.get("include")
    for cell in include if isinstance(include, list) else []:
        if isinstance(cell, dict) and axis in cell:
            found = True
            said = cell[axis]
            if isinstance(said, str) and said.strip().startswith(EXPRESSION):
                return [], f"ячейка include с matrix.{axis} — выражение, а не версия"
            cells.append(str(said))
    if not found:
        return [], f"python-version из matrix.{axis}, а оси {axis} в матрице нет"
    return cells, None


def axis_versions(job: dict[str, Any], axis: str) -> tuple[list[tuple[int, int]], str | None]:
    """Номера оси `strategy.matrix.<axis>` работы и её ячеек `include:`; (номера, отказ)."""
    cells, why = _cells(job, axis)
    if why:
        return [], why
    versions: list[tuple[int, int]] = []
    for raw in cells:
        found = CELL_RE.match(raw.strip())
        if found is None:
            return [], f"ячейка matrix.{axis} «{raw}» не формы X.Y"
        versions.append((int(found[1]), int(found[2])))
    return versions, None


def read(root: Path) -> tuple[list[Declared], list[Refused]]:
    """Все объявленные версии прогонов дерева и отказы: осей матриц и файлов версии.

    Прогон, который не разбирается, — `pipeline_checks.BadPolicy` у вызывающего:
    это ошибка входа, а не «версий нет» (075).
    """
    declared: list[Declared] = []
    refused: list[Refused] = []
    for path in _flows(root):
        document = pipeline_checks.run_of(path)
        for name, job in (document.get("jobs") or {}).items():
            declared += _called(path, str(name), job, refused)
            for step in _steps(job):
                raw = step.get("with")
                given: dict[str, Any] = raw if isinstance(raw, dict) else {}
                if "python-version" not in given:
                    if "python-version-file" in given:
                        refused.append(
                            Refused(
                                path.name,
                                str(name),
                                f"версия из файла {given['python-version-file']} — "
                                "файл версии не читается, только python-version",
                            )
                        )
                    continue
                preview = _preview(given)
                # Строк может быть несколько: setup-python ставит каждую версию
                # многострочного блока (`python-version: |`), и каждая — объявление
                # (взгляд на #1565: прежде читалась только первая).
                for said in str(given["python-version"]).splitlines():
                    found, why = _said(job, said.strip())
                    if why:
                        refused.append(Refused(path.name, str(name), why))
                    declared += [Declared(path.name, str(name), one, preview) for one in found]
    return declared, refused


def _called(path: Path, name: str, job: Any, refused: list[Refused]) -> list[Declared]:
    """Версии, переданные вызовом общего шага пробы; не вызов — пусто."""
    if not isinstance(job, dict):
        return []
    if not str(job.get("uses") or "").split("@")[0].endswith(f"/{NEXT_STEP}"):
        return []
    given = job.get("with")
    said = str(given.get("python", "")).strip() if isinstance(given, dict) else ""
    if not said:
        refused.append(Refused(path.name, name, f"{NEXT_STEP} позван без входа python"))
        return []
    found, why = _said(job, said)
    if why:
        refused.append(Refused(path.name, name, why))
    return [Declared(path.name, name, one, True) for one in found]


def _said(job: Any, said: str) -> tuple[list[tuple[int, int]], str | None]:
    """Версии одной строки `python-version`: ось матрицы или число; иное — ни то ни другое.

    Строка не числом и не осью (`3.x`, `pypy3.11`, пустая) версией не считается
    и не отказ: со значком её не сравнить, а сломанным прогон от неё не стал.
    """
    if not said:
        return [], None
    axis = FROM_MATRIX_RE.match(said)
    if axis:
        return axis_versions(job, axis[1]) if isinstance(job, dict) else ([], "работа не словарь")
    literal = LITERAL_RE.match(said)
    return ([(int(literal[1]), int(literal[2]))] if literal else []), None
