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

ЧТО СЧИТАЕТСЯ ПОВЕРХНОСТЬЮ — И ЧЕГО ЗДЕСЬ НЕТ (195). Имена верхнего уровня
без `_`: функции с подписью и возвращаемым типом, классы с базами, прочие
имена — одним именем, без значения: смена значения константы (`TIMEOUT`) —
поведение, а не поверхность, и сюда не входит. Поведение функции при прежней
подписи снимок не видит тоже: его держат тесты пакета, а не число.

Исходы: ``0`` снимок записан · ``2`` не отработал (пакет не прочитан).
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

#: Файл снимка рядом с числом версии.
SNAPSHOT: Final = "SURFACE"
#: Первая строка снимка — чем он сделан; разбор её пропускает.
HEADER: Final = (
    "# Поверхность транспорта. Пишет `python scripts/transport_surface.py`; "
    "рукой не правится (#1048)."
)
#: Метка строки с версией, к которой относится снимок.
VERSION_MARK: Final = "VERSION "


class NotRun(RuntimeError):
    """Пакет не прочитан — снимок собрать не из чего (075)."""


def public_names(source: str, module: str) -> list[str]:
    """Публичные имена модуля строками снимка: `модуль.имя…`, по порядку в файле."""
    found: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                back = f" -> {ast.unparse(node.returns)}" if node.returns else ""
                found.append(f"{module}.{node.name}({ast.unparse(node.args)}){back}")
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                bases = ", ".join(ast.unparse(base) for base in node.bases)
                found.append(f"{module}.{node.name}({bases})")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            found += [
                f"{module}.{target.id}"
                for target in targets
                if isinstance(target, ast.Name) and not target.id.startswith("_")
            ]
    return found


def surface(package: Path) -> tuple[str, list[str]]:
    """Живая поверхность пакета: (`VERSION`, строки снимка без версии)."""
    try:
        version = (package / "VERSION").read_text(encoding="utf-8").strip()
        project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
        modules = list(project["tool"]["setuptools"]["py-modules"])
        lines = [f"requires-python {project['project']['requires-python']}"]
        for module in modules:
            lines += public_names((package / f"{module}.py").read_text(encoding="utf-8"), module)
    except (OSError, KeyError, SyntaxError, tomllib.TOMLDecodeError) as exc:
        raise NotRun(f"пакет {package} не прочитан: {exc}") from exc
    return version, lines


def render(version: str, lines: list[str]) -> str:
    """Текст снимка: шапка, версия, поверхность."""
    return "\n".join([HEADER, f"{VERSION_MARK}{version}", *lines]) + "\n"


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
    (package / SNAPSHOT).write_text(render(version, lines), encoding="utf-8")
    print(f"снимок поверхности {version} записан: {package / SNAPSHOT}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
