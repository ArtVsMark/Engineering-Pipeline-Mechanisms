"""Тело функции не повторяется в двух модулях, а намеренный повтор подписан (071).

Копия тела совпадает с первой в день появления и расходится при первой правке
одной из них — молча: каждая исправна и покрыта своим набором. Правило 071
допускает дубль, только если он НАМЕРЕННЫЙ и это сказано: подпись называет,
с кем он и почему не сведён.

ЗАМЕР ПО ДЕРЕВУ 01.10.2026, ДО ПОЧИНКИ (#999): функции `scripts/` и
`packages/transport/` с телом от 20 узлов AST, одинаковые до узла в разных
модулях, — три группы, и ни одна не подписана. `read_version` в
`build_changelog` и `check_version` — копия уже жившего `version.declared`;
`git` в `agent_pr` и `squash_body`; `_git` в `change_parts`,
`check_decisions_edit`, `check_derived_refs`, `check_new_is_tested` — вторая
форма того же вызова, не ловившая `OSError`. Число групп одно и то же при
пороге 20, 30 и 40 узлов: предикат не шумит на мелочи. После починки первые
сведены к `version.declared`, обёртки — к `gitcall.output`, повторов ноль.

ГРАНИЦА НАЗВАНА (195). Судится тело до узла: имена, буквы, порядок. Две записи
одного предмета разными словами — `journal.git` берёт команду целиком,
`release.git` срезает вывод, `build_facts.contract_version` проверяет версию
иначе, чем `version.declared`, — гейт не видит, и это держит чтение.

СОСЕД — `tests/test_third_case.py` (093): там сравнивается ФОРМА без имён, и
законны две копии из трёх; здесь — тело до имени, и незаконна уже вторая.
Четыре копии `_git` у соседа прошли потому, что в них три оператора при его
пороге в пять: короткое, но целое тело он не меряет по замыслу. Тонкая
обёртка короче порога (`return gitcall.output(args, NotRun)`) повтором не
считается: она и есть ссылка на общий вызов.
"""

import ast
from collections import defaultdict
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, code_files

#: Тело короче этого числа узлов — обёртка или однострочник, а не разбор: их
#: повтор — ссылка на общее, а не копия. Замер 01.10.2026: при 20, 30 и 40
#: узлах находится одно и то же.
SMALLEST: Final = 20

#: Намеренные повторы — с причиной у каждого (071). Подпись ставится на НАБОР
#: мест `модуль::функция`, а не на имя: третья копия того же тела краснеет.
SIGNED: Final[dict[frozenset[str], str]] = {}


def body_of(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """Тело без докстроки: пояснение у копий законно разное."""
    body = node.body
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]
    return body


def bodies(path: Path, root: Path = ROOT) -> list[tuple[str, str]]:
    """Функции модуля не короче порога: слепок доводов и тела — и место."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = body_of(node)
        size = sum(1 for one in body for _ in ast.walk(one))
        if size < SMALLEST:
            continue
        # Доводы входят в слепок: одно тело над разными доводами — разные функции.
        signature = ast.Expr(ast.Lambda(node.args, ast.Constant(None)))
        cast = ast.dump(ast.Module(body=[signature, *body], type_ignores=[]))
        found.append((cast, f"{path.relative_to(root).as_posix()}::{node.name}"))
    return found


def repeated(
    files: list[Path], root: Path = ROOT, signed: dict[frozenset[str], str] = SIGNED
) -> list[list[str]]:
    """Тела, повторённые в нескольких модулях без подписи: места каждой группы."""
    seen: dict[str, list[str]] = defaultdict(list)
    for path in files:
        for cast, place in bodies(path, root):
            seen[cast].append(place)
    return [
        sorted(places)
        for places in seen.values()
        if len({one.split("::")[0] for one in places}) > 1 and frozenset(places) not in signed
    ]


def modules() -> list[Path]:
    """Модули рабочего кода."""
    return code_files()


def test_the_gate_found_its_subject() -> None:
    """Предмет есть: тел не короче порога в рабочем коде сотни, а не ноль (075)."""
    assert sum(len(bodies(path)) for path in modules()) >= 300


def test_no_body_is_copied_into_another_module() -> None:
    """Тело функции живёт в одном модуле, остальные его зовут (071)."""
    found = repeated(modules())
    assert not found, "тело повторено в нескольких модулях без подписи (071): " + "; ".join(
        ", ".join(places) for places in found
    )


COPIED: Final = '''
def read(path):
    """Читает."""
    if not path.is_file():
        raise NotRun(f"нет {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise NotRun(f"{path} пуст")
    return value
'''


def test_the_predicate_tells_a_copy_from_a_call(tmp_path: Path) -> None:
    """Обе половины: копия тела краснеет, вызов общего — нет; докстрока не в счёт."""
    (tmp_path / "first.py").write_text(COPIED, encoding="utf-8")
    other = COPIED.replace('"""Читает."""', '"""Иначе."""')
    (tmp_path / "second.py").write_text(other, encoding="utf-8")
    (tmp_path / "third.py").write_text(
        "import first\n\ndef read(path):\n    return first.read(path)\n", encoding="utf-8"
    )
    files = sorted(tmp_path.glob("*.py"))
    assert repeated(files, tmp_path) == [["first.py::read", "second.py::read"]]
    (tmp_path / "second.py").unlink()
    assert repeated(sorted(tmp_path.glob("*.py")), tmp_path) == [], "вызов общего принят за копию"


def test_a_signature_covers_its_set_and_no_third_copy(tmp_path: Path) -> None:
    """Подпись снимает названный набор мест, а третья копия краснеет снова."""
    for name in ("first", "second"):
        (tmp_path / f"{name}.py").write_text(COPIED, encoding="utf-8")
    signed = {frozenset({"first.py::read", "second.py::read"}): "причина"}
    assert repeated(sorted(tmp_path.glob("*.py")), tmp_path, signed) == []
    (tmp_path / "third.py").write_text(COPIED, encoding="utf-8")
    assert repeated(sorted(tmp_path.glob("*.py")), tmp_path, signed) == [
        ["first.py::read", "second.py::read", "third.py::read"]
    ]
