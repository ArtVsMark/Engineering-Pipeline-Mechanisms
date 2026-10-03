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

ЧТО СЧИТАЕТСЯ ПОВЕРХНОСТЬЮ (взгляд на #1068). Договор установки —
`requires-python` и `dependencies`. Имена модулей без `_` на верхнем уровне,
в том числе внутри `if`/`try` верхнего уровня: функции с подписью и
возвращаемым типом, классы с базами, их публичные методы и `__init__` с
подписями, публичные атрибуты класса, псевдонимы `type X = …`, прочие имена —
и поодиночке, и кортежным присваиванием.

ЧЕГО ЗДЕСЬ НЕТ, И ГРАНИЦА НАЗВАНА (195). Значение имени: смена значения
константы (`TIMEOUT`) — поведение, а не поверхность. Умолчание подписи
записано так, как стоит в коде: литерал (`timeout=30`) виден, и его смена
краснеет, а умолчание через константу (`limit=MERGED_WINDOW`) видно именем, и
смена значения константы — снова поведение. Поведение функции при прежней
подписи снимок не видит тоже: его держат тесты пакета, а не число.

КОМАНДА НЕ ПЕРЕПИСЫВАЕТ ПОВЕРХНОСТЬ ПРИ ПРЕЖНЕМ ЧИСЛЕ (взгляд на #1068).
Иначе её же подсказка из красного сообщения снимала бы красное без сдвига
`VERSION`. Сменилась поверхность, а `VERSION` тот же, что в снимке, — отказ с
названным шагом. Переписать снимок при прежнем числе законно в одном случае —
сменился ФОРМАТ снимка (шапка): это правка разбора, а не поверхности. Правку
файла рукой команда не остановит, и это предел: снимок — вывод команды, и
рукописная правка производного видна в диффе изменения.

Исходы: ``0`` снимок записан · ``2`` не отработал (пакет не прочитан) ·
``3`` отказ: поверхность сменилась при прежнем `VERSION`.
"""

import argparse
import ast
import sys
import tomllib
from pathlib import Path
from typing import Final

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
    "# Поверхность транспорта, формат 2. Пишет `python scripts/transport_surface.py`; "
    "рукой не правится (#1048)."
)
#: Метка строки с версией, к которой относится снимок.
VERSION_MARK: Final = "VERSION "


class NotRun(RuntimeError):
    """Пакет не прочитан — снимок собрать не из чего (075)."""


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef, owner: str) -> str:
    """Строка снимка функции: имя, подпись как в коде и возвращаемый тип."""
    back = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{owner}.{node.name}({ast.unparse(node.args)}){back}"


def assigned(target: ast.expr) -> list[str]:
    """Имена, которым присваивает цель: одиночное и кортежное присваивание."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [name for one in target.elts for name in assigned(one)]
    return []


def names_in(body: list[ast.stmt], owner: str) -> list[str]:
    """Публичные имена тела модуля или класса строками снимка, по порядку в файле.

    Тела `if` и `try` верхнего уровня обходятся тоже: имя, объявленное
    условно, — всё равно имя модуля, и выпасть из снимка без следа оно не
    вправе (взгляд на #1068).
    """
    found: list[str] = []
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_") or node.name == "__init__":
                found.append(signature(node, owner))
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                bases = ", ".join(ast.unparse(base) for base in node.bases)
                found.append(f"{owner}.{node.name}({bases})")
                found += names_in(node.body, f"{owner}.{node.name}")
        elif isinstance(node, ast.TypeAlias):
            if not node.name.id.startswith("_"):
                found.append(f"{owner}.{node.name.id}")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            found += [
                f"{owner}.{name}"
                for target in targets
                for name in assigned(target)
                if not name.startswith("_")
            ]
        elif isinstance(node, ast.If):
            found += names_in(node.body, owner) + names_in(node.orelse, owner)
        elif isinstance(node, ast.Try):
            found += names_in(node.body, owner)
            for handler in node.handlers:
                found += names_in(handler.body, owner)
            found += names_in(node.orelse, owner) + names_in(node.finalbody, owner)
    return found


def public_names(source: str, module: str) -> list[str]:
    """Публичные имена модуля строками снимка: `модуль.имя…`, по порядку в файле."""
    return names_in(ast.parse(source).body, module)


def surface(package: Path) -> tuple[str, list[str]]:
    """Живая поверхность пакета: (`VERSION`, строки снимка без версии)."""
    try:
        version = (package / "VERSION").read_text(encoding="utf-8").strip()
        project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
        modules = list(project["tool"]["setuptools"]["py-modules"])
        needs = sorted(str(one) for one in project["project"].get("dependencies") or [])
        lines = [
            f"requires-python {project['project']['requires-python']}",
            f"dependencies {', '.join(needs) or '—'}",
        ]
        for module in modules:
            lines += public_names((package / f"{module}.py").read_text(encoding="utf-8"), module)
    except (OSError, KeyError, SyntaxError, tomllib.TOMLDecodeError) as exc:
        raise NotRun(f"пакет {package} не прочитан: {exc}") from exc
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
    args = parser.parse_args(argv)
    package = args.root / paths.TRANSPORT
    try:
        version, lines = surface(package)
    except NotRun as exc:
        print(f"снимок не записан: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    why = refusal(package, version, lines)
    if why:
        print(f"снимок не записан: {why}", file=sys.stderr)
        return EXIT_REFUSED
    (package / SNAPSHOT).write_text(render(version, lines), encoding="utf-8")
    print(f"снимок поверхности {version} записан: {package / SNAPSHOT}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
