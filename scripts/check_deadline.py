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

`Popen` ДЕДЛАЙНА В ВЫЗОВЕ НЕ БЕРЁТ — у него `communicate(timeout=)` или
`wait(timeout=)`. Поэтому `Popen` законен, когда в той же функции (или на
уровне модуля, если он там) стоит такое ожидание с `timeout=` в теле `try`,
ловящего `TimeoutExpired`. Прежде он отвергался целиком: у нас таких вызовов
ноль, но у потребителя законная форма иначе не выполнима (взгляд на #1530).
Предел назван: что ожидание идёт именно у этого `Popen`, предикат не сверяет —
одного ожидания с дедлайном в той же области достаточно.

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
subprocess.run`), `os.system`, `os.popen`, `pty.spawn` и
`asyncio.create_subprocess_exec`/`_shell` предикат не видит. У первых трёх
дедлайна нет вовсе, у асинхронных он ставится ожиданием (`asyncio.wait_for`),
а не доводом вызова; в нашем дереве их ноль (замер 22.10.2026 по
`code_files`). Набор тестов не судится: это не механизм, а его проверка, и
предел ей ставит площадка.

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

ФАЙЛ, КОТОРЫЙ PYTHON РАННЕРА НЕ РАЗБИРАЕТ, — ТОЖЕ ПРЕДУПРЕЖДЕНИЕ (поздний
взгляд на #1530, решение (б)). Шаблон `.py`, синтаксис Python 2 или новее
раннера, чужая кодировка — дерево, писанное без гейта, иначе краснело бы с
первым подъёмом тега исходом «не отработал». Без `--enforce` такой файл
называется аннотацией «не разобран» и счётом, а не молчит; с `--enforce` —
«не отработал»: строгий проект свой код разбирать обязан.

Исходы (039): ``0`` чисто, предупреждено без `--enforce` или кода нет — причина
напечатана · ``1`` найдено при `--enforce` · ``2`` не отработал (git отказал,
файл не прочитан, при `--enforce` — и не разобран).
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


#: Ожидание процесса, у которого дедлайн — довод, а не у `Popen`.
WAITS: Final = frozenset({"communicate", "wait"})


def waits_with_deadline(tree: ast.AST, safe: set[int]) -> set[int]:
    """Узлы областей (модуль, функции), где есть пойманное ожидание процесса с `timeout=`.

    Отдаёт `id` каждого узла, исполняемого в такой области: `Popen` среди них законен.
    """
    allowed: set[int] = set()
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        inside = [node for statement in scope.body for node in executed(statement)]
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in WAITS
            and any(word.arg == "timeout" for word in node.keywords)
            and id(node) in safe
            for node in inside
        ):
            allowed |= {id(node) for node in inside}
    return allowed


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
    awaited = waits_with_deadline(tree, safe)
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and is_spawn(node, imported, modules)):
            continue
        if spawned_name(node.func) == "Popen":
            if id(node) not in awaited:
                found.append(
                    f"{node.lineno}: Popen без пойманного communicate(timeout=) или wait(timeout=)"
                )
        elif not any(word.arg == "timeout" for word in node.keywords):
            found.append(f"{node.lineno}: без timeout=")
        elif id(node) not in safe:
            found.append(f"{node.lineno}: TimeoutExpired не пойман")
    return found


def code_of(root: Path, places: list[str]) -> list[str]:
    """Файлы `.py` под названными местами дерева, по индексу и вне его; отказ git — «не отработал».

    Вне индекса — потому что предполётная видит файл до толчка, а гейт,
    не видящий того, что окно пишет сейчас, зелен на непросмотренном (075).

    МЕСТ НЕТ — ФАЙЛОВ НЕТ (поздний взгляд на #1530). `git ls-files --` без
    путей отдаёт всё дерево: у потребителя без единого места из умолчания гейт
    судил бы весь его репозиторий вместе с `tests/`, а не отвечал «неприменимо».
    """
    if not places:
        # Дерево всё равно спрашивается: вне репозитория — «не отработал», а не
        # «кода нет» и при пустом перечне. Исход читается, а не только код
        # выхода: в голом репозитории и внутри `.git` git отвечает `false` с
        # кодом 0, а прежний `ls-files` там давал «не отработал» (взгляд на #1538).
        inside = gitcall.output(["rev-parse", "--is-inside-work-tree"], NotRun, cwd=str(root))
        if inside.strip() != "true":
            raise NotRun(f"{root} — не рабочее дерево git: rev-parse ответил {inside.strip()!r}")
        return []
    listed = gitcall.output(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *places],
        NotRun,
        cwd=str(root),
    )
    return sorted(one for one in listed.split("\0") if one.endswith(".py"))


def look(
    root: Path, places: list[str], *, named: bool = True
) -> tuple[list[tuple[str, str, str]], int, list[tuple[str, str]]]:
    """Находки «файл, строка, что», число просмотренных файлов и неразобранные «файл, почему».

    Неразобранный — файл, который прочитан, но этот Python его не разбирает:
    его судит `main` по `--enforce`. Непрочитанный (`OSError`) — «не отработал».

    Место, НАЗВАННОЕ входом, обязано быть в дереве: опечатка иначе выдала бы
    себя за «кода нет» (075, взгляд на #1530). Место из умолчания может
    отсутствовать — у потребителя хуков окна бывает не заведено.
    """
    missing = [one for one in places if not (root / one).exists()]
    if missing and named:
        raise NotRun(f"мест кода нет в дереве: {', '.join(missing)}")
    names = code_of(root, [one for one in places if one not in missing])
    found: list[tuple[str, str, str]] = []
    unparsed: list[tuple[str, str]] = []
    for name in names:
        try:
            raw = (root / name).read_bytes()
        except OSError as exc:
            raise NotRun(f"{name} не прочитан: {exc}") from exc
        try:
            bad = undeadlined(raw.decode("utf-8"))
        except (UnicodeDecodeError, SyntaxError, ValueError, RecursionError) as exc:
            unparsed.append((name, report.cut(str(exc))))
            continue
        for one in bad:
            line, what = one.split(": ", 1)
            found.append((name, line, what))
    return found, len(names), unparsed


def escaped(value: str, *, prop: bool) -> str:
    """Значение команды площадки: `%` и переводы строк, у свойства ещё `:` и `,` (#1530)."""
    said = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return said.replace(":", "%3A").replace(",", "%2C") if prop else said


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обходит места кода и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument(
        "--paths",
        default=None,
        help=f"места кода механизмов через пробел, от корня; без ключа — {' '.join(DEFAULT_PATHS)}",
    )
    parser.add_argument(
        "--enforce", action="store_true", help="найденное — отказ, а не предупреждение"
    )
    args = parser.parse_args(argv)
    named = args.paths is not None
    places = args.paths.split() if named else list(DEFAULT_PATHS)
    if not places:
        print("гейт не отработал: мест кода не названо (075)", file=sys.stderr)
        return EXIT_BROKEN
    try:
        found, seen, unparsed = look(args.root, places, named=named)
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
    level = "error" if args.enforce else "warning"
    for name, why in unparsed:
        print(
            f"::{level} file={escaped(name, prop=True)}::"
            f"{escaped(f'файл не разобран — дедлайн в нём не судился: {why}', prop=False)}"
        )
    if unparsed:
        print(f"не разобрано файлов: {len(unparsed)} из {seen} — их вызовы не судились")
        if args.enforce:
            print("гейт не отработал: строгий проект свой код разбирать обязан", file=sys.stderr)
            return EXIT_BROKEN
    # ЗНАМЕНАТЕЛЬ ОДИН — РАЗОБРАННЫЕ ФАЙЛЫ (взгляд на #1546): неразобранные
    # названы строкой выше, и «просмотрено» о них не говорит.
    judged = seen - len(unparsed)
    if not judged:
        # Ни один файл не разобран — зелёного утверждения нет, есть неприменимость
        # с причиной (154): судить было нечего, а не «чисто».
        print(f"неприменимо: ни один из файлов {seen} не разобран — вызовов процесса судить негде")
        return EXIT_OK
    if not found:
        print(f"дедлайн у каждого вызова процесса: разобрано файлов {judged}")
        return EXIT_OK
    print(
        f"вызов процесса без дедлайна или без его поимки (100, 039): {len(found)} "
        f"в разобранных файлах {judged}"
    )
    for one in found:
        # Аннотация с файлом и строкой: площадка кладёт её на строку диффа.
        name, line, what = one
        print(
            f"::{level} file={escaped(name, prop=True)},line={line}::"
            f"{escaped(what.strip(), prop=False)} (100)"
        )
    print(
        "Назовите timeout= и ловите subprocess.TimeoutExpired тем же исходом, что OSError: "
        "зависший процесс иначе держит гейт до предела площадки."
    )
    return EXIT_FOUND if args.enforce else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
