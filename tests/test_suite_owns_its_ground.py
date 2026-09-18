"""Набор забирает площадку себе, а не заносит её в исключения.

Когда сторож шумит из-за ресурса, к которому одинаково ходят и проверяемый код, и
всё остальное на машине — системный временный каталог, домашняя папка, общий кеш,
фиксированный порт, — лечится ВЛАДЕНИЕ ресурсом. Исключение по имени оставляет
площадку общей и вместе с шумом гасит настоящую находку
([149](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/149-the-suite-owns-its-temp.md)).

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Обращений набора к общей площадке
— НОЛЬ: файлы механизмов собираются в `tmp_path`, а транспорт проверяется на своём
сервере, поднятом на случайном порту. То есть требование исполнялось и держалось
внимательностью: первый же тест, написавший в системный временный каталог или
занявший порт числом, не покраснел бы нигде — а упал бы позже и у другого, на
машине, где этот порт занят
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЛИТЕРАЛ И ВЫЗОВ РАЗВЕДЕНЫ, И ЭТО НЕ ПЕДАНТИЗМ. Общую площадку называют двумя
разными способами, и проверять их одинаково нельзя:

* `"/tmp/…"` — ЛИТЕРАЛ. Предмет здесь и есть строка, отношения между двумя
  вещами нет, и сверять её текстом честно. Список литералов закрытый;
* `Path.home()`, `expanduser("~")`, `tempfile.gettempdir()` — ВЫЗОВЫ. Тут
  подстрока проверяет отношение по написанию и промахивается в обе стороны:
  `pathlib.Path . home()` с пробелами не видна, а `Path.home()` в докстроке
  засчитывается как обращение
  ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).

Прежняя редакция сверяла всё построчно одним набором образцов и отсеивала
комментарии по решётке — то есть докстроку отсеять не могла вовсе: проза о
`/tmp` покраснела бы наравне с обращением. Теперь ВСЁ читается разбором, а
докстрока исключается как докстрока, а не как строка, начинающаяся с решётки.

Порт меряется разбором с самого начала: число в строке бывает чем угодно.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT

SUITE: Final = ROOT / "tests"

#: Общая площадка, названная ЛИТЕРАЛОМ. Предмет здесь и есть строка.
SHARED_LITERAL: Final = "/tmp"
#: Общая площадка, полученная ВЫЗОВОМ: имя зовомого — обе формы записи разом.
SHARED_CALLS: Final = frozenset(
    {"gettempdir", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory", "home", "expanduser"}
)
#: Общая площадка, взятая из окружения: `os.environ["HOME"]`.
SHARED_ENV: Final = frozenset({"HOME", "TMPDIR", "TEMP"})

#: Чем поднимают свой сервер: порт у него обязан быть выбран площадкой, а не нами.
SERVERS: Final = frozenset({"HTTPServer", "ThreadingHTTPServer", "TCPServer"})


def suite_files() -> list[Path]:
    """Модули набора — предмет этой проверки. Сам гейт из предмета исключён.

    ОБЪЯВЛЕНИЕ ПРИЗНАКА НЕИЗБЕЖНО СОДЕРЖИТ ОБРАЗЕЦ, и на первом же прогоне гейт
    нашёл сам себя. Приём тот же, что у гейта версии: там пример маркера не
    приводится намеренно, потому что маркеры ищутся во всех файлах. Цена названа:
    свою площадку этот модуль не проверяет — он её и не берёт, а берёт только
    дерево на чтение
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    here = Path(__file__).resolve()
    return sorted(
        path
        for path in SUITE.rglob("*.py")
        if "__pycache__" not in path.parts and path.resolve() != here
    )


def called_name(node: ast.Call) -> str:
    """Имя того, что зовут, — и голым именем, и через точку.

    `HTTPServer(...)` и `server.HTTPServer(...)` — один и тот же сервер, а
    первая редакция знала только первую форму: вызов через атрибут или алиас
    проходил мимо проверки молча. Нашёл внешний взгляд.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def server_address(node: ast.Call) -> ast.expr | None:
    """Адрес, отданный серверу, — позиционно или именованным доводом.

    `HTTPServer(server_address=(...))` — та же запись другими словами, и первая
    редакция её не видела: ветка `not node.args` обрывала разбор до чтения
    порта. Возвращается `None`, когда формы разобрать не удалось: это «не
    проверил», а не «порт хорош».
    """
    if node.args:
        return node.args[0]
    for keyword in node.keywords:
        if keyword.arg == "server_address":
            return keyword.value
    return None


def test_the_subject_of_this_gate_exists() -> None:
    """Модулей набора нет — отказ, а не «чисто» (075)."""
    assert suite_files(), f"в {SUITE} не нашлось модулей набора — сверять нечего"


def docstrings_of(tree: ast.AST) -> set[int]:
    """Узлы-докстроки по их месту: проза о площадке обращением не является."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def shared_ground_in(path: Path) -> list[str]:
    """Обращения модуля к ОБЩЕЙ площадке — разбором, а не построчным образцом.

    Три способа назвать её читаются тремя разными узлами, и смешивать их в один
    образец значило бы проверять написание вместо отношения: литерал `"/tmp/x"`,
    вызов `Path.home()` или `expanduser(...)`, чтение `environ["HOME"]`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prose = docstrings_of(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in prose and node.value.startswith(SHARED_LITERAL):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno} — литерал «{node.value}»")
        elif isinstance(node, ast.Call):
            head = node.func
            name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
            if name in SHARED_CALLS:
                found.append(f"{path.relative_to(ROOT)}:{node.lineno} — вызов {name}()")
        elif isinstance(node, ast.Subscript):
            asked = node.slice
            holder = node.value
            where = holder.attr if isinstance(holder, ast.Attribute) else getattr(holder, "id", "")
            # ИМЯ БЕРЁТСЯ СТРОКОЙ ЯВНО. `ast.Constant.value` бывает чем угодно,
            # включая байты, и подстановка их в сообщение дала бы «b'HOME'» —
            # запись, по которой место не найдёшь поиском (176).
            if where == "environ" and isinstance(asked, ast.Constant):
                said = asked.value
                if isinstance(said, str) and said in SHARED_ENV:
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno} — environ[«{said}»]")
    return found


def test_the_suite_never_names_the_shared_ground() -> None:
    """Набор не называет общую площадку: он забирает свою через `tmp_path`."""
    named = [one for path in suite_files() for one in shared_ground_in(path)]
    assert not named, (
        "набор берёт ОБЩУЮ площадку вместо своей (149):\n  "
        + "\n  ".join(named)
        + "\n  Своя площадка приходит фикстурой `tmp_path`: она принадлежит прогону"
        " и исчезает вместе с ним."
    )


def test_a_server_of_the_suite_takes_the_port_it_is_given() -> None:
    """Свой сервер поднимается на порту, который выбирает площадка, а не мы.

    Фиксированный порт — тот же общий ресурс: он занят у соседа по машине, и набор
    падает не там, где дефект. Меряется РАЗБОРОМ: число в строке само по себе
    ничего не значит, а вот второй член пары, отданной серверу, значит.
    """
    fixed: list[str] = []
    seen = 0
    for path in suite_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or called_name(node) not in SERVERS:
                continue
            seen += 1
            where = server_address(node)
            if where is None:
                # Форма записи сторожу неизвестна — значит порт он НЕ ПРОВЕРИЛ, и
                # молчать здесь нельзя: слепой отвергает (045, 068).
                fixed.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} — адрес сервера записан формой,"
                    " которой проверка не знает, и порт остался непроверенным"
                )
                continue
            if isinstance(where, ast.Tuple) and len(where.elts) == 2:
                port = where.elts[1]
                if isinstance(port, ast.Constant) and port.value != 0:
                    fixed.append(f"{path.relative_to(ROOT)}:{node.lineno} — порт {port.value!r}")
    assert seen, "набор не поднимает своего сервера — предмет проверки не найден (075)"
    assert not fixed, (
        "сервер набора занимает ФИКСИРОВАННЫЙ порт — общий ресурс машины (149):\n  "
        + "\n  ".join(fixed)
        + "\n  Порт 0 означает «выбери сама»; настоящий читается из `server_address`."
    )


def test_the_suite_actually_takes_a_ground_of_its_own() -> None:
    """Довод гейта замерен: своя площадка у набора действительно есть.

    Оба запрета выше молчат и на наборе, который НИКУДА не пишет вовсе, — а такой
    набор ничего и не проверяет. Поэтому здесь спрашивается обратное: `tmp_path`
    у набора в ходу
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    users = [
        path.relative_to(ROOT).as_posix()
        for path in suite_files()
        if "tmp_path" in path.read_text(encoding="utf-8")
    ]
    assert users, "ни один модуль не берёт своей площадки — запрет выше держит пустоту"


@pytest.mark.parametrize(
    ("source", "seen", "about"),
    [
        ('HTTPServer(("127.0.0.1", 8080), h)', True, "голым именем"),
        ('server.HTTPServer(("127.0.0.1", 8080), h)', True, "через атрибут"),
        ('HTTPServer(server_address=("127.0.0.1", 8080))', True, "именованным доводом"),
        ('HTTPServer(("127.0.0.1", 0), h)', False, "порт выбирает площадка"),
    ],
)
def test_a_fixed_port_is_seen_in_every_form_of_the_call(
    source: str, seen: bool, about: str
) -> None:
    """Фиксированный порт виден в каждой форме записи вызова.

    Первая редакция знала одну: вызов через атрибут (`server.HTTPServer(…)`) и
    адрес именованным доводом (`server_address=…`) проходили мимо молча — то
    есть гейт говорил о запрете, не проверяя его. Обе нашёл внешний взгляд.
    """
    node = next(one for one in ast.walk(ast.parse(source)) if isinstance(one, ast.Call))
    assert called_name(node) in SERVERS, f"{about}: сервер не узнан вовсе"
    where = server_address(node)
    assert where is not None, f"{about}: адрес сервера не найден"
    assert isinstance(where, ast.Tuple)
    port = where.elts[1]
    fixed = isinstance(port, ast.Constant) and port.value != 0
    assert fixed is seen, f"{about}: фиксированный порт {'не ' if seen else ''}замечен"


def test_an_unreadable_address_is_not_taken_for_a_good_one() -> None:
    """Форму адреса не разобрали — это «не проверил», а не «порт хорош» (045)."""
    node = next(
        one for one in ast.walk(ast.parse("HTTPServer(**настройки)")) if isinstance(one, ast.Call)
    )
    assert called_name(node) in SERVERS
    assert server_address(node) is None, "неразобранная форма выдана за проверенную"
