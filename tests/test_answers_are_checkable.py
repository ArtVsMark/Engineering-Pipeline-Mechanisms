"""Ответ каталогу проверяется по названному адресу, а не на слово.

СОСЕДНИЙ ГЕЙТ ДЕРЖИТ ИМЯ, ЭТОТ — УТВЕРЖДЕНИЕ. `tests/test_bindings_addresses.py`
сверяет, что названный файл лежит в дереве. Этого мало: ответ говорит не «файл
есть», а «механизм проверяет вот это», и называет ЧЕМ — именем функции,
константы, поля. Пока проверялось только имя файла, утверждение о содержимом
держалось вниманием автора ответа.

ЗАМЕР 11.09.2026, ревизия всех 170 ответов с адресом по просьбе владельца.
Нашлось два расхождения, и оба такого рода:

* ответ по **063** отправлял за проверкой обращения в
  `.github/workflows/review.yml` — там `author_association` не встречается ни
  разу, проверка живёт в `claude.yml`;
* ответ по **119** говорил «CHANGELOG.md — в `EXEMPT_FILES` гейта», называя
  адресом `scripts/journal.py`; константа живёт в `scripts/check_journal.py`.

Ни одно из двух не ловилось ничем: файлы существуют, адреса разрешаются,
утверждения ложны. Читатель, пошедший по такому адресу, механизма не находит и
не может отличить «ответ врёт» от «механизм переехал»
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
"""

from __future__ import annotations

import json
import re
from typing import Final

import pytest

from tests.conftest import ROOT

BINDINGS = ROOT / ".rules" / "bindings.json"
#: Полный путь механизма: с каталогом, а не одно имя файла. Имя без каталога
#: сверяет соседний гейт; здесь нужен путь — по нему и читают.
PATH_RE: Final = re.compile(
    r"(?<![\w./-])((?:scripts|tests|docs|changelog\.d|\.github|\.rules|\.claude)/[\w./-]+\.[a-z]{2,5})\b"
)
#: Ссылка на функцию внутри механизма: `файл.py::имя`.
FUNCTION_RE: Final = re.compile(r"([\w./-]+\.py)::(\w+)")
#: Что считается НАЗВАННЫМ ПОНЯТИЕМ: имя в обратных кавычках, змеиный
#: идентификатор, константа заглавными. Слова русского языка сюда не попадают,
#: и это намеренно: проверяется то, что можно найти в коде поиском.
TOKEN_RE: Final = re.compile(
    r"`([A-Za-z_][\w.]{2,})`|(?<![\w`])([a-z]+_[a-z_]+|[A-Z]{3,}_[A-Z_]+)(?![\w`])"
)
#: Файлы, которые механизмами не являются и в которых понятие искать незачем.
READABLE: Final = (".py", ".yml", ".yaml", ".json", ".md", ".txt")
#: Понятия, названные в ответе, которых в названных им файлах нет законно, —
#: с причиной у каждого. Список разрешительный (068): «похоже на исключение»
#: сюда не попадает.
ELSEWHERE: Final[dict[str, str]] = {}
#: Пути, которых в этом дереве нет и быть не должно: механизм соседа законно
#: называется в ответе. Список тот же по смыслу, что FOREIGN у соседнего
#: гейта, и ведётся отдельно намеренно — там имя, здесь путь.
FOREIGN_PATHS: Final[dict[str, str]] = {
    "scripts/onboard_consumer.py": "механизм каталога: им собран наш ответ, у нас его нет",
}


def answers() -> dict[str, dict[str, str]]:
    """Ответы проекта по правилам каталога."""
    rules: dict[str, dict[str, str]] = json.loads(BINDINGS.read_text(encoding="utf-8"))["rules"]
    return {number: answer for number, answer in rules.items() if answer.get("status") == "active"}


def prose(answer: dict[str, str]) -> str:
    """Проза ответа целиком: адрес и причина читаются вместе."""
    return " ".join(str(answer.get(field) or "") for field in ("where", "why"))


def file_stems() -> set[str]:
    """Имена файлов дерева без расширения: они не понятия, а адреса."""
    return {path.stem for path in ROOT.rglob("*") if path.is_file()}


def test_there_are_answers_with_addresses() -> None:
    """Предмет найден: действующие ответы есть и называют пути (075)."""
    with_paths = [number for number, answer in answers().items() if PATH_RE.search(prose(answer))]
    assert len(with_paths) > 50, f"ответов с полным путём {len(with_paths)} — предмет не найден"


@pytest.mark.parametrize("number", sorted(answers()))
def test_every_full_path_in_an_answer_exists(number: str) -> None:
    """Полный путь, названный в ответе, существует в дереве.

    Соседний гейт сверяет только имя файла: механизм, переехавший в другой
    каталог, проходил его целиком.
    """
    missing = [
        path
        for path in PATH_RE.findall(prose(answers()[number]))
        if path not in FOREIGN_PATHS and not (ROOT / path).exists()
    ]
    assert not missing, (
        f"ответ на {number} называет несуществующий путь: {missing}. "
        "Поправьте ответ или объявите путь чужим в FOREIGN_PATHS с причиной"
    )


@pytest.mark.parametrize("number", sorted(answers()))
def test_every_named_function_exists(number: str) -> None:
    """Функция, названная через `::`, есть в названном файле."""
    problems: list[str] = []
    for name, function in FUNCTION_RE.findall(prose(answers()[number])):
        path = ROOT / name
        if not path.is_file():
            problems.append(f"{name}::{function} — файла нет")
        elif f"def {function}" not in path.read_text(encoding="utf-8"):
            problems.append(f"{name}::{function} — функции нет в файле")
    assert not problems, f"ответ на {number}: {problems}"


@pytest.mark.parametrize("number", sorted(answers()))
def test_every_named_notion_is_found_at_the_named_address(number: str) -> None:
    """Понятие, названное в ответе, встречается в файле, который ответ называет.

    Это и есть разница между «адрес разрешается» и «утверждение верно»: ответ
    обещает читателю, что по адресу он найдёт названное.
    """
    answer = answers()[number]
    text = prose(answer)
    files = [ROOT / path for path in PATH_RE.findall(text)]
    files = [path for path in files if path.is_file() and path.suffix in READABLE]
    if not files:
        return
    blob = "\n".join(path.read_text(encoding="utf-8") for path in files)
    stems = file_stems()
    missing = [
        token
        for match in TOKEN_RE.finditer(text)
        if (token := match.group(1) or match.group(2))
        if "." not in token and token not in stems and token not in ELSEWHERE
        if token not in blob
    ]
    assert not missing, (
        f"ответ на {number} называет {missing}, и ни одно не встречается по названным им "
        f"адресам ({', '.join(str(path.relative_to(ROOT)) for path in files)}). "
        "Поправьте адрес, поправьте ответ или объявите понятие в ELSEWHERE с причиной"
    )


def test_every_exception_names_its_reason() -> None:
    """У каждого исключения названа причина, а не просто пропуск (154)."""
    assert all(ELSEWHERE.values()), "понятие выведено из проверки без причины"
    assert all(FOREIGN_PATHS.values()), "чужой путь объявлен без причины"


def test_no_exception_outlived_its_reason() -> None:
    """Чужой путь, появившийся в дереве, в исключении больше не нуждается."""
    stray = sorted(path for path in FOREIGN_PATHS if (ROOT / path).exists())
    assert not stray, f"эти пути есть в дереве и исключения не требуют: {stray}"
