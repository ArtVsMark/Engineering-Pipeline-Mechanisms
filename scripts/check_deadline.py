#!/usr/bin/env python3
"""Гейт: вызов процесса в механизме несёт дедлайн и ловит его истечение (100, 220, #1439).

ОДНА РЕАЛИЗАЦИЯ НА СЕМЬЮ (214, решение владельца 18.10.2026 по #1439). Прежде
предикат жил в нашем тесте, а у каталога и Usage-Token — свои копии. Теперь он
здесь: наш тест `tests/test_subprocess_deadline.py` зовёт эти же функции, а
потребитель получает тот же разбор шагом в джобе `pipeline` (`step-pipeline.yml`)
с подъёмом тега.

ПРЕДМЕТ — МЕХАНИЗМ, А НЕ ПРОГОН. Зависший `git` или `bash` держал гейт до
предела площадки, и красное приходило через сорок минут причиной «превышено
время», а не названным отказом. Замер 17.10.2026 по `scripts/`,
`packages/transport/` и `.claude/hooks/` нашего дерева — 21 вызов в 15 файлах.

ПРАВИЛО СТРОГОЕ, И У НЕГО ДВЕ ПОЛОВИНЫ. Вызов процесса (`run`,
`check_output`, `check_call`, `call` — по имени, с `subprocess.` или без)
несёт довод `timeout=`, И стоит в теле `try`, чей обработчик ловит
`TimeoutExpired` (или его предка `SubprocessError`, или `Exception`).
Дедлайн без поимки менял бы зависание на трассу с кодом 1 — то же
нарушение третьего исхода (039), только быстрее.

`Popen` ДЕДЛАЙНА В ВЫЗОВЕ НЕ БЕРЁТ — у него `communicate(timeout=)`, — и
предикат его отвергает целиком: у нас таких вызовов ноль, и первый появится
вместе с решением, как его судить (075).

ТЕЛО `try` — ТО, ЧТО ИСПОЛНЯЕТСЯ В НЁМ (находка `f7d1815`). Вызов внутри
`def` или `lambda`, вложенных в тело, исполнится позже и вне этого `try`:
такой вызов поимкой внешнего блока не считается. Предел назван: тело
вложенного `class`, довод по умолчанию и декоратор вложенного `def`
исполняются сразу, при определении, то есть в `try`, — их предикат тоже не
засчитывает, и это строгость, а не дыра.

МОДУЛЬ ПОД ДРУГИМ ИМЕНЕМ — ТОТ ЖЕ МОДУЛЬ (находка `bde3e93`): `import
subprocess as sp` даёт `sp.run`, и предикат его видит наравне с
`from subprocess import run as r`.

СОСЕД ЗА ГРАНИЦЕЙ (195): вызов через переменную-псевдоним (`spawn =
subprocess.run`) и `os.system` предикат не видит. Набор тестов не судится:
это не механизм, а его проверка, и предел ей ставит площадка.

СЕМЬЮ СПРОСИЛИ (162). У каталога нашёлся свой гейт дедлайна: он требует
названный предел и выводит его значение из вида вызова, но поимку истечения
не судит. Свой гейт есть и у Usage-Token. Требование названного предела
взято у каталога, поимка истечения — наша вторая половина. Одна реализация
на семью — решение владельца 17.10.2026: шаг механизмов заменит копии, и
каталог возьмёт готовый шаг, когда он выйдет с тегом.

У ПОТРЕБИТЕЛЯ — ПРЕДУПРЕЖДЕНИЕ, ОТКАЗ — КЛЮЧОМ `--enforce` (решение владельца
18.10.2026, пункт (б)). Строгий гейт на дереве, которое писали без него,
краснел бы с первым же подъёмом тега: замер каталога на нашем дереве 16.10 —
257 вызовов без `timeout=` в одних `tests/` (051). Где лежит код, говорит
`--paths` (пункт (в)): наш `paths.SOURCES` у соседа не верен.

Исходы (039): ``0`` чисто, предупреждено без `--enforce` или кода нет — причина
напечатана · ``1`` найдено при `--enforce` · ``2`` не отработал (git отказал,
файл не разобран).
"""

import argparse
import ast
import sys
from pathlib import Path
from typing import Final

import gitcall
import report

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Где у потребителя лежит код механизмов, если вход шага не назван.
DEFAULT_PATHS: Final = ("scripts", ".claude/hooks")
#: Вызовы процесса, которые судятся, — по имени, как у `tests/test_git_refuses.py`.
SPAWNS: Final = frozenset({"run", "check_output", "check_call", "call", "Popen"})
#: Поимка, означающая «истёк дедлайн — свой исход».
CATCHES: Final = frozenset({"TimeoutExpired", "SubprocessError", "Exception"})
#: Узлы, внутрь которых предикат поимку объемлющего `try` не несёт: тело `def` и
#: `lambda` исполняется позже и вне него, тело `class` — сразу, и его гейт судит
#: строже, чем исполняется (предел назван в шапке).
SCOPES: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def spawned_name(func: ast.expr) -> str:
    """Имя вызываемого: `subprocess.run` и `run` из импорта — одно имя."""
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def is_spawn(call: ast.Call, imported: set[str], modules: frozenset[str] = frozenset()) -> bool:
    """Вызов процесса: атрибут модуля `subprocess` (под любым именем) или имя, взятое из него."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr in SPAWNS
            and isinstance(func.value, ast.Name)
            and func.value.id in {"subprocess", *modules}
        )
    return isinstance(func, ast.Name) and func.id in imported


def executed(statement: ast.AST) -> list[ast.AST]:
    """Узлы, исполняемые там, где написан `statement`: в тела `def`, `lambda`, `class` не входит."""
    found: list[ast.AST] = []
    todo = [statement]
    while todo:
        node = todo.pop()
        found.append(node)
        if not isinstance(node, SCOPES):
            todo.extend(ast.iter_child_nodes(node))
    return found


def caught(block: ast.Try) -> set[str]:
    """Имена классов, которые ловят обработчики этого `try`."""
    names: set[str] = set()
    for handler in block.handlers:
        if handler.type is not None:
            kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            names |= {ast.unparse(one).rsplit(".", 1)[-1] for one in kinds}
    return names


def guarded(tree: ast.AST) -> set[int]:
    """Узлы в ТЕЛЕ `try` с поимкой истёкшего дедлайна — не в обработчике и не после."""
    inside: set[int] = set()
    for block in ast.walk(tree):
        if isinstance(block, ast.Try) and caught(block) & CATCHES:
            inside |= {id(node) for statement in block.body for node in executed(statement)}
    return inside


def undeadlined(source: str) -> list[str]:
    """Вызовы процесса исходника без дедлайна или без поимки его истечения."""
    tree = ast.parse(source)
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess"
        for alias in node.names
        if alias.name in SPAWNS
    }
    modules = frozenset(
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "subprocess" and alias.asname
    )
    safe = guarded(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and is_spawn(node, imported, modules)):
            continue
        if spawned_name(node.func) == "Popen":
            found.append(f"{node.lineno}: Popen — дедлайн не в вызове")
        elif not any(word.arg == "timeout" for word in node.keywords):
            found.append(f"{node.lineno}: без timeout=")
        elif id(node) not in safe:
            found.append(f"{node.lineno}: TimeoutExpired не пойман")
    return found


def code_of(root: Path, places: list[str]) -> list[str]:
    """Файлы `.py` под названными местами дерева, по индексу и вне его; отказ git — «не отработал».

    Вне индекса — потому что предполётная видит файл до толчка, а гейт,
    не видящий того, что окно пишет сейчас, зелен на непросмотренном (075).
    """
    listed = gitcall.output(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *places],
        NotRun,
        cwd=str(root),
    )
    return sorted(one for one in listed.split("\0") if one.endswith(".py"))


def look(root: Path, places: list[str]) -> tuple[list[str], int]:
    """Находки строками «файл:строка: что» и число просмотренных файлов."""
    names = code_of(root, places)
    found: list[str] = []
    for name in names:
        try:
            source = (root / name).read_text(encoding="utf-8")
            bad = undeadlined(source)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
            raise NotRun(f"{name} не разобран: {exc}") from exc
        found += [f"{name}:{one}" for one in bad]
    return found, len(names)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обходит места кода и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument(
        "--paths",
        default=" ".join(DEFAULT_PATHS),
        help="места кода механизмов через пробел, от корня",
    )
    parser.add_argument(
        "--enforce", action="store_true", help="найденное — отказ, а не предупреждение"
    )
    args = parser.parse_args(argv)
    places = args.paths.split()
    if not places:
        print("гейт не отработал: мест кода не названо (075)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        found, seen = look(args.root, places)
    except NotRun as exc:
        print(f"гейт не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    if not seen:
        # Кода на Python под названными местами нет — судить нечего, и это
        # говорится, а не выдаётся за «чисто» (154).
        print(
            f"неприменимо: под {', '.join(places)} файлов .py нет — вызовов процесса судить негде"
        )
        return EXIT_OK
    if not found:
        print(f"дедлайн у каждого вызова процесса: файлов просмотрено {seen}")
        return EXIT_OK
    level = "error" if args.enforce else "warning"
    print(
        f"вызов процесса без дедлайна или без его поимки (100, 039): {len(found)} из файлов {seen}"
    )
    for one in found:
        # Аннотация с файлом и строкой: площадка кладёт её на строку диффа.
        name, line, what = one.split(":", 2)
        print(f"::{level} file={name},line={line}::{what.strip()} (100)")
    print(
        "Назовите timeout= и ловите subprocess.TimeoutExpired тем же исходом, что OSError: "
        "зависший процесс иначе держит гейт до предела площадки."
    )
    return EXIT_FOUND if args.enforce else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
