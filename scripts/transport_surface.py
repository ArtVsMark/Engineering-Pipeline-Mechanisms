#!/usr/bin/env python3
"""Снимок поверхности транспорта: число `VERSION` движется вместе с поверхностью.

ЗАЧЕМ ЭТО ЕСТЬ (#1048, решение владельца 03.10.2026, вариант А). Шапка
`packages/transport/pyproject.toml` обещала: «пока транспорт двигают правкой,
число двигают вместе с ней рукой». Обещание не держало ничего: #1025 поднял
`requires-python` транспорта, а `VERSION` остался 0.2.0 и прожил в общей
ветке до #1040. Нашли взгляды на #1040 (`5808620`, `e39cec2`), а не механизм.

КАК ДЕРЖИТСЯ. Рядом с числом лежит снимок поверхности —
`packages/transport/SURFACE`: версия, к которой он относится,
`requires-python`, модули пакета и их публичные имена с подписями функций.
Набор (`tests/test_transport_package.py`) сверяет живую поверхность со
снимком в обе стороны: поверхность сменилась при прежнем `VERSION` — красное
«сдвиньте VERSION»; `VERSION` сдвинут, а снимок старый — красное «перепишите
снимок». Снимок пишет этот модуль, рукой его не правят: обновление — вывод
команды, а не текст.

ЧТО СЧИТАЕТСЯ ПОВЕРХНОСТЬЮ (взгляды на #1068 и #1080). Договор установки —
`requires-python` и `dependencies`. Имена модуля и его классов — все, которым
область присваивает, где бы ни стояло присваивание: их берёт `symtable`, по
которому связывает имена сам Python, а не перечень видов операторов. Публичны
имена без `_` впереди и все dunder-имена (`__init__`, `__call__`, `__all__`).
Функция пишется с декораторами, подписью и возвращаемым типом, класс — с
декораторами, базами и ключами (`metaclass=…`): это меняет вызов при прежнем
имени. Строки снимка отсортированы.

ЧЕГО ЗДЕСЬ НЕТ, И ГРАНИЦА НАЗВАНА (195). Импорт верхнего уровня (`import
report` в `ghrest`): `ghrest.report` достижим, но это зависимость реализации,
а не обещание потребителю, и смена её поверхности не меняет. Присваивание
`X += …` нового имени не заводит — имя уже стоит в снимке. Значение имени: смена значения
константы (`TIMEOUT`) — поведение, а не поверхность. Умолчание подписи
записано так, как стоит в коде: литерал (`timeout=30`) виден, и его смена
краснеет, а умолчание через константу (`limit=MERGED_WINDOW`) видно именем, и
смена значения константы — снова поведение. Поведение функции при прежней
подписи снимок не видит тоже: его держат тесты пакета, а не число.

ПОВЕРХНОСТЬ СВЕРЯЕТСЯ С ОБЩЕЙ ВЕТКОЙ, А НЕ СО СНИМКОМ В ГОЛОВЕ (взгляды на
#1068, `88a3574`, `0caa805`). Снимок, сверенный только сам с собой,
обходился двумя путями: удалить `SURFACE` и запустить команду или сменить
формат в шапке — и поверхность переписывалась при прежнем `VERSION`. Поэтому
поверхность общей ветки вычисляется ЭТИМ ЖЕ разбором из её файлов
(`base_surface`), и сменилась она при том же `VERSION` — отказ команды и
красное набора, что бы ни лежало в `SURFACE`. Формат шапки на это не влияет:
обе стороны разобраны одним кодом. Снимок в дереве остаётся сверкой «вывод
команды записан».

Исходы: ``0`` снимок записан · ``2`` не отработал (пакет не прочитан или
общей ветки нет — сверять поверхность не с чем, и это не «сходится») ·
``3`` отказ: поверхность сменилась при прежнем `VERSION` — против снимка или
против общей ветки.
"""

import argparse
import ast
import symtable
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Final

import gitcall
import paths

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_REFUSED: Final = 3

#: Файл снимка рядом с числом версии.
SNAPSHOT: Final = "SURFACE"
#: Первая строка снимка — чем он сделан и в каком формате; разбор её пропускает.
#: Номер формата растёт с каждой правкой разбора: по нему команда отличает
#: «сменился формат» от «сменилась поверхность».
HEADER: Final = (
    "# Поверхность транспорта, формат 4. Пишет `python scripts/transport_surface.py`; "
    "рукой не правится (#1048)."
)
#: Метка строки с версией, к которой относится снимок.
VERSION_MARK: Final = "VERSION "
#: С чем сверяется поверхность, если не сказано иное: общая ветка.
BASE: Final = "origin/main"


class NotRun(RuntimeError):
    """Пакет не прочитан — снимок собрать не из чего (075)."""


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef, owner: str) -> str:
    """Строка снимка функции: декораторы, имя, подпись как в коде и возвращаемый тип."""
    back = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    marks = "".join(f"@{ast.unparse(one)} " for one in node.decorator_list)
    return f"{marks}{owner}.{node.name}({ast.unparse(node.args)}){back}"


def public(name: str) -> bool:
    """Публично ли имя: без `_` впереди либо dunder (`__call__`, `__all__`)."""
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def scope_nodes(body: list[ast.stmt]) -> list[ast.AST]:
    """Узлы одной области видимости: всё, кроме тел вложенных функций и классов."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop(0)
        found.append(node)
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            stack.extend(ast.iter_child_nodes(node))
    return found


def class_line(node: ast.ClassDef, owner: str) -> str:
    """Строка снимка класса: декораторы, имя, базы и ключи (`metaclass=…`)."""
    marks = "".join(f"@{ast.unparse(one)} " for one in node.decorator_list)
    said = [ast.unparse(base) for base in node.bases] + [ast.unparse(one) for one in node.keywords]
    return f"{marks}{owner}.{node.name}({', '.join(said)})"


def names_in(table: symtable.SymbolTable, body: list[ast.stmt], owner: str) -> list[str]:
    """Публичные имена области строками снимка, отсортированные.

    ИМЕНА ДАЁТ ИНТЕРПРЕТАТОР, А НЕ ПЕРЕЧЕНЬ ВИДОВ УЗЛОВ (взгляды на #1068 и
    #1080, 210). Прежний разбор знал виды операторов поимённо — `if`, `try`,
    `for`, `with` — и каждый заход взгляда называл следующий: `while`,
    `match`, `except*`, декоратор класса. Здесь имена области берутся из
    `symtable` — той же таблицы, по которой связывает имена сам Python: всё,
    чему область присваивает, где бы ни стояло присваивание. AST нужен только
    для строки `def` и `class`: подпись, декораторы, базы и ключи.

    Импорт в поверхность не входит: это зависимость реализации, а не обещание
    потребителю. Строки сортируются: перестановка определений в модуле
    поверхность не меняет (`a417b45`).
    """
    defs: dict[str, list[ast.AST]] = {}
    for node in scope_nodes(body):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            defs.setdefault(node.name, []).append(node)
    children = {child.get_name(): child for child in table.get_children()}
    found: set[str] = set()
    for symbol in table.get_symbols():
        name = symbol.get_name()
        # Импорт символом не «присвоен» (`is_assigned` ложно), и отдельной
        # проверки `is_imported` не нужно: условие ниже его уже снимает.
        if not public(name) or not (symbol.is_assigned() or symbol.is_namespace()):
            continue
        if name not in defs:
            found.add(f"{owner}.{name}")
            continue
        for node in defs[name]:
            if isinstance(node, ast.ClassDef):
                found.add(class_line(node, owner))
                inner = children.get(name)
                if inner is not None:
                    found.update(names_in(inner, node.body, f"{owner}.{name}"))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found.add(signature(node, owner))
    return sorted(found)


def public_names(source: str, module: str) -> list[str]:
    """Публичные имена модуля строками снимка: `модуль.имя…`, отсортированные."""
    return names_in(symtable.symtable(source, module, "exec"), ast.parse(source).body, module)


def surface(package: Path) -> tuple[str, list[str]]:
    """Живая поверхность пакета: (`VERSION`, строки снимка без версии)."""
    try:
        return surface_from(lambda name: (package / name).read_text(encoding="utf-8"))
    except OSError as exc:
        raise NotRun(f"пакет {package} не прочитан: {exc}") from exc


def base_surface(root: Path, base: str = BASE) -> tuple[str, list[str]]:
    """Поверхность пакета в `base` — тем же разбором из её файлов, а не из её снимка."""

    def shown(name: str) -> str:
        return gitcall.output(["show", f"{base}:{paths.TRANSPORT}/{name}"], NotRun, cwd=str(root))

    return surface_from(shown)


def moved_without_version(version: str, lines: list[str], root: Path, base: str = BASE) -> str:
    """Почему поверхность нельзя принять против `base`; пустая строка — можно."""
    was, before = base_surface(root, base)
    if was == version and before != lines:
        changed = sorted(set(lines) ^ set(before))
        return (
            f"поверхность сменилась против {base} при прежнем VERSION {version}: {changed} — "
            f"сдвиньте {paths.TRANSPORT / 'VERSION'}"
        )
    return ""


def surface_from(read_file: Callable[[str], str]) -> tuple[str, list[str]]:
    """Поверхность из файлов пакета, прочитанных `read_file` по имени файла."""
    try:
        version = read_file("VERSION").strip()
        project = tomllib.loads(read_file("pyproject.toml"))
        modules = list(project["tool"]["setuptools"]["py-modules"])
        needs = sorted(str(one) for one in project["project"].get("dependencies") or [])
        lines = [
            f"requires-python {project['project']['requires-python']}",
            f"dependencies {', '.join(needs) or '—'}",
        ]
        for module in modules:
            lines += public_names(read_file(f"{module}.py"), module)
    except (KeyError, SyntaxError, tomllib.TOMLDecodeError) as exc:
        raise NotRun(f"пакет не прочитан: {exc}") from exc
    return version, lines


def render(version: str, lines: list[str]) -> str:
    """Текст снимка: шапка, версия, поверхность."""
    return "\n".join([HEADER, f"{VERSION_MARK}{version}", *lines]) + "\n"


def header_of(path: Path) -> str:
    """Первая строка записанного снимка — формат, в котором он записан; нет файла — пусто."""
    try:
        return path.read_text(encoding="utf-8").partition("\n")[0]
    except OSError:
        return ""


def refusal(package: Path, version: str, lines: list[str]) -> str:
    """Почему снимок переписывать нельзя; пустая строка — можно.

    Нельзя ровно в одном случае: снимок того же формата и той же версии
    описывает ДРУГУЮ поверхность. Тогда переписать его значило бы снять
    красное без сдвига `VERSION` (взгляд на #1068).
    """
    path = package / SNAPSHOT
    if header_of(path) != HEADER:
        return ""
    try:
        noted, before = read(path)
    except NotRun:
        return ""
    if noted == version and before != lines:
        return (
            f"поверхность сменилась при прежнем VERSION {version} — сдвиньте "
            f"{package / 'VERSION'}, потом пишите снимок"
        )
    return ""


def read(path: Path) -> tuple[str, list[str]]:
    """Записанный снимок: (версия, строки поверхности). Нет файла — отказ, а не пусто."""
    try:
        said = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    except OSError as exc:
        raise NotRun(f"снимка {path} нет: {exc}") from exc
    body = [line for line in said if not line.startswith("#")]
    if not body or not body[0].startswith(VERSION_MARK):
        raise NotRun(f"{path}: первой строкой после шапки ждали «{VERSION_MARK}X.Y.Z»")
    return body[0].removeprefix(VERSION_MARK), body[1:]


def main(argv: list[str] | None = None) -> int:
    """Пишет снимок живой поверхности рядом с `VERSION`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--base", default=BASE, help="с чем сверять поверхность")
    args = parser.parse_args(argv)
    package = args.root / paths.TRANSPORT
    try:
        version, lines = surface(package)
        why = refusal(package, version, lines) or moved_without_version(
            version, lines, args.root, args.base
        )
    except NotRun as exc:
        print(f"снимок не записан: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if why:
        print(f"снимок не записан: {why}", file=sys.stderr)
        return EXIT_REFUSED
    (package / SNAPSHOT).write_text(render(version, lines), encoding="utf-8")
    print(f"снимок поверхности {version} записан: {package / SNAPSHOT}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
