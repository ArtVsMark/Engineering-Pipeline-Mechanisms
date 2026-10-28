"""Пути данных проекта — ключом таблицы, а не прозой и не константой мимо неё (#1623).

РЕШЕНИЕ ВЛАДЕЛЬЦА 25.10.2026. Навык и отдаваемый документ называют данные
проекта ключом таблицы путей и пояснением словами, что это за файл; адрес
приходит командой `paths.py <ключ>` во время вызова. Голый путь умолчания в
тексте не пишется: у потребителя, переназначившего его разделом `paths:`,
текст повёл бы окно к файлу, которого у него нет.

ПУТЬ РЯДОМ С КЛЮЧОМ — ЗАКОНЕН (решение владельца 28.10.2026, #639; находки
`e57de54`, `fd0378c`). Читатель, которому запускатель закрыт, — внешний взгляд
с закрытым списком команд — адреса по одной команде не узнаёт. Поэтому
сразу за командой ключа в той же фразе может стоять его умолчание формой
`BESIDE`: «`… paths.py <ключ>`, по умолчанию `<путь>`». Путь, не равный
умолчанию этого ключа, краснеет: рядом с ключом — только его собственный.

ДВЕ ПОЛОВИНЫ ГЕЙТА.

* **Текст.** Предмет — навыки, которые заход кладёт потребителю
  (`onboard.SKILLS_KITTED`), и тексты заготовок `kit/**/*.md`. Краснеет путь
  умолчания любого ключа `paths.PROJECT` не рядом со своим ключом (путь внутрь каталога — ссылка на
  документ поставщика, а не данные проекта, и не судится), неизвестный ключ
  в команде и команда без пояснения словами перед ней. Форма команды у
  навыка — `python scripts/paths.py`: подстановка при кладке делает из неё
  вызов запускателя; у заготовки `kit/` подстановки нет, и форма там сразу
  запускателем.
* **Код.** Константа-двойник ключа (`paths.BINDINGS` и соседи) в
  `scripts/` законна умолчанием на уровне модуля, в тексте сообщения
  (f-строка) и как имя файла (`.name`); иное употребление — чтение мимо
  таблицы. `onboard.py` исключён поимённо: он лежит у поставщика и называет
  пути заготовок, которые кладёт.

ГРАНИЦА НАЗВАНА (057). Что пояснение называет ИМЕННО этот файл, машина не
отличит: гейт требует слов перед командой, а не их верности.
"""

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, load_script, walk

paths = load_script("paths.py")
onboard = load_script("onboard.py")

#: Путь умолчания каждого ключа — граница пути, а не подстрока: продолжение
#: `/…` ведёт внутрь каталога (документ поставщика), а не к данным проекта.
DEFAULTS: Final = {
    key: re.compile(re.escape(path.as_posix()) + r"(?![\w/.-])")
    for key, path in paths.PROJECT.items()
}
#: Команда адреса в навыке и в заготовке `kit/`.
SKILL_CALL: Final = re.compile(r"python scripts/paths\.py ([\w-]+)")
KIT_CALL: Final = re.compile(r"bash \.claude/mechanisms\.sh paths\.py ([\w-]+)")
#: Умолчание сразу за командой ключа, в той же фразе: «`…`, по умолчанию `путь`».
BESIDE: Final = r"`,\s+по умолчанию\s+`([^`\n]+)`"
#: Пояснение — слово кириллицей в пределах окна перед командой, в том же абзаце.
EXPLAINED: Final = re.compile(r"[а-яё]{3,}", re.IGNORECASE)
WINDOW: Final = 80
#: Модули, которым константы-двойники законны целиком, — с причиной.
CODE_EXEMPT: Final = {
    "paths.py": "сама таблица: умолчания живут здесь",
    "onboard.py": "заход подключения лежит у поставщика и называет пути заготовок, которые кладёт",
}


def text_subjects() -> list[tuple[Path, re.Pattern[str], re.Pattern[str]]]:
    """Тексты гейта: навык — со своей формой команды, заготовка `kit/` — со своей."""
    skills = [(ROOT / one, SKILL_CALL, KIT_CALL) for one in onboard.SKILLS_KITTED]
    kit = [(one, KIT_CALL, SKILL_CALL) for one in walk(ROOT / paths.KIT, "**/*.md")]
    return skills + kit


def text_problems(text: str, call: re.Pattern[str], foreign: re.Pattern[str]) -> list[str]:
    """Нарушения формы в одном тексте: голый путь, чужая форма, неизвестный ключ, без слов."""
    found: list[str] = []
    bare = text
    for beside in re.finditer(call.pattern + BESIDE, text):
        key, said = beside[1], beside[2]
        if key not in paths.PROJECT or said != paths.PROJECT[key].as_posix():
            found.append(f"рядом с ключом «{key}» не его умолчание: {said}")
            continue
        # Путь рядом со своим ключом из суда голого пути вынимается — длина
        # та же, чтобы окно пояснения перед командой считалось по месту.
        bare = bare[: beside.start(2)] + " " * len(said) + bare[beside.end(2) :]
    found += [
        f"путь умолчания ключа «{key}»: {pattern.pattern.split('(?')[0]}"
        for key, pattern in DEFAULTS.items()
        if pattern.search(bare)
    ]
    found += [f"команда чужой формы: {one[0]}" for one in foreign.finditer(text)]
    for said in call.finditer(text):
        if said[1] not in paths.PROJECT:
            found.append(f"ключа «{said[1]}» в таблице нет")
        before = text[max(0, said.start() - WINDOW) : said.start()].split("\n\n")[-1]
        if not EXPLAINED.search(before):
            found.append(f"команда без пояснения, что за файл: {said[0]}")
    return found


def test_the_text_names_project_data_by_key_with_words() -> None:
    """Навыки и заготовки `kit/` называют данные ключом и словами, а не путём (#1623)."""
    subjects = text_subjects()
    assert len(subjects) > len(onboard.SKILLS_KITTED), "заготовки kit/ не найдены (075)"
    told = {
        str(path.relative_to(ROOT)): problems
        for path, call, foreign in subjects
        if (problems := text_problems(path.read_text(encoding="utf-8"), call, foreign))
    }
    assert told == {}


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("правит `.rules/bindings.json` руками", "путь умолчания ключа «bindings»"),
        ("ответ каталогу (`python scripts/paths.py bindingz`)", "ключа «bindingz» в таблице нет"),
        ("`python scripts/paths.py bindings`", "без пояснения"),
        ("ответ (`bash .claude/mechanisms.sh paths.py bindings`)", "чужой формы"),
        (
            "ответ (`python scripts/paths.py bindings`, по умолчанию `.rules/roles.json`)",
            "рядом с ключом «bindings» не его умолчание",
        ),
        (
            "ответ (`python scripts/paths.py roles`, по умолчанию `.rules/bindings.json`)",
            "путь умолчания ключа «bindings»",
        ),
    ],
    ids=[
        "голый-путь",
        "неизвестный-ключ",
        "без-слов",
        "форма-запускателя-в-навыке",
        "рядом-чужой-путь",
        "рядом-путь-другого-ключа",
    ],
)
def test_the_text_gate_turns_red_on_each_form(text: str, said: str) -> None:
    """Каждая половина текста краснеет на своём нарушении — проверка откатом формы."""
    assert any(said in one for one in text_problems(text, SKILL_CALL, KIT_CALL))


def test_the_default_beside_its_own_key_is_lawful() -> None:
    """Умолчание сразу за командой своего ключа — законно; то же отдельно — нет (`e57de54`)."""
    beside = (
        "таблица ролей (`python scripts/paths.py bindings`, по умолчанию `.rules/bindings.json`)"
    )
    assert text_problems(beside, SKILL_CALL, KIT_CALL) == []
    apart = beside + "; правят `.rules/bindings.json` руками"
    assert any(
        "путь умолчания ключа «bindings»" in one
        for one in text_problems(apart, SKILL_CALL, KIT_CALL)
    )


def test_a_path_inside_a_directory_key_is_a_document_not_data() -> None:
    """Ссылка внутрь `docs/decisions/` — документ поставщика, а не каталог данных."""
    text = (
        "решение [`038`](../../../docs/decisions/038-x.md)"
        " и ответ (`python scripts/paths.py bindings`)"
    )
    assert text_problems(text, SKILL_CALL, KIT_CALL) == []


def twins() -> dict[str, str]:
    """Константы `paths`, чьё значение — путь умолчания ключа таблицы: имя → ключ."""
    by_path = {path: key for key, path in paths.PROJECT.items()}
    return {
        name: by_path[value]
        for name in dir(paths)
        if isinstance(value := getattr(paths, name), Path) and value in by_path
    }


def code_problems(source: str, names: dict[str, str]) -> list[str]:
    """Употребления двойника мимо таблицы: не умолчание модуля, не сообщение, не `.name`.

    ГРАНИЦА НАЗВАНА (057, взгляд на #1653 `518a3ca`): уровень модуля разрешён
    целиком, и за именем, которому там присвоен двойник, гейт не следит —
    `ANSWER = paths.BINDINGS`, а затем `(root / ANSWER).read_text()` в функции
    прошли бы мимо таблицы. Мерка 28.10.2026 по `scripts/*.py`: таких
    присваиваний шесть — `automerge.RULES_ANSWER`, `family_check.ANSWER`,
    `findings.ANSWER_FILE`, `project_badge.ANSWER`, `onboard.DATA_KITTED` и
    `onboard.KIT_REFUSED`, — и ни одно не читает файл: подпись сообщения,
    умолчание подписи, перечень заготовки. Слежка за именами через функции —
    отдельный разбор потока, и пути от реального входа к нему нет.
    """
    tree = ast.parse(source)
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    found: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "paths"
            and node.attr in names
        ):
            continue
        up = parent.get(node)
        if isinstance(up, ast.FormattedValue) or (
            isinstance(up, ast.Attribute) and up.attr == "name"
        ):
            continue
        scope: ast.AST = node
        while scope in parent and not isinstance(
            scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        ):
            scope = parent[scope]
        if isinstance(scope, ast.Module):
            continue
        found.append(f"{node.lineno}: paths.{node.attr} — ключ «{names[node.attr]}» мимо таблицы")
    return found


def test_mechanisms_read_project_data_through_the_table() -> None:
    """Код механизмов не читает данные проекта константой мимо таблицы путей (#1623)."""
    names = twins()
    assert len(names) == len(paths.PROJECT), "двойник есть у каждого ключа — иначе меряем не то"
    told = {
        one.name: problems
        for one in walk(ROOT / paths.SCRIPTS, "*.py")
        if one.name not in CODE_EXEMPT
        and (problems := code_problems(one.read_text(encoding="utf-8"), names))
    }
    assert told == {}


def test_the_code_gate_turns_red_on_a_read_and_keeps_the_lawful() -> None:
    """Чтение в функции краснеет; умолчание модуля, сообщение и имя файла — законны."""
    names = {"BINDINGS": "bindings"}
    red = "def f(root):\n    return (root / paths.BINDINGS).read_text()\n"
    assert code_problems(red, names)
    lawful = (
        "ANSWER = paths.BINDINGS\n"
        "def g(where):\n"
        "    print(f'нет {paths.BINDINGS}')\n"
        "    return where.parent / paths.BINDINGS.name\n"
    )
    assert code_problems(lawful, names) == []


#: Литерал пути умолчания, законный там, где таблицу прочитать нечем, — с причиной.
LITERAL_EXEMPT: Final = {
    ("labels-sync.yml", ".github/labels.yml"): (
        "фильтр `on.push.paths` вычисляется площадкой до любого шага: таблицу путей "
        "ему прочитать нечем"
    ),
}


def literal_reads(root: Path) -> list[tuple[str, str]]:
    """Путь умолчания ключа таблицы буквами там, где его ЧИТАЮТ, а не называют (#1722).

    В скрипте — строка, которая целиком равна пути (константа вроде прежнего
    `RECORDS = "docs/decisions/"`); в прогоне — путь операндом команды вне
    `echo` и комментария (прежнее `[ -f .github/attribution-since ]`). Текст
    сообщений и пояснений не судится: путь в нём называют, а не читают.
    ГРАНИЦА НАЗВАНА: путь, собранный из частей, обход не видит.
    """
    defaults = {path.as_posix() for path in paths.PROJECT.values()}
    found: list[tuple[str, str]] = []
    for one in walk(root / paths.SCRIPTS, "*.py"):
        if one.name in CODE_EXEMPT or one.name == "paths.py":
            continue
        for node in ast.walk(ast.parse(one.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.rstrip("/") in defaults
            ):
                found.append((one.name, node.value.rstrip("/")))
    for one in walk(root / paths.WORKFLOWS, "*.yml"):
        for line in one.read_text(encoding="utf-8").splitlines():
            said = line.strip()
            if said.startswith("#") or "echo " in said:
                continue
            for path in defaults:
                operand = r"(^|[\s\"'(<=:-])" + re.escape(path) + r"(/|[\"'\s)]|$)"
                if re.search(operand, said):
                    found.append((one.name, path))
    return sorted(set(found))


def test_no_mechanism_reads_project_data_by_a_literal_path() -> None:
    """Скрипты и прогоны не читают данные проекта путём умолчания буквами (#1722).

    Мерка 28.10.2026: два чтения мимо таблицы — каталог записей решений в
    `check_decisions_edit.py` и отметка атрибуции в `step-attribution-history.yml`;
    переназначение разделом `paths:` у них молча не действовало.
    """
    found = literal_reads(ROOT)
    assert [one for one in found if one not in LITERAL_EXEMPT] == []
    stale = [key for key in LITERAL_EXEMPT if key not in found]
    assert not stale, f"исключение без литерала — снять: {stale}"


def test_the_literal_gate_reds_on_a_read_and_keeps_a_message(tmp_path: Path) -> None:
    """Константа пути и операнд прогона краснеют; путь в сообщении — нет."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "scripts" / "x.py").write_text(
        'RECORDS = "docs/decisions/"\nSAID = "поправьте .rules/bindings.json"\n',
        encoding="utf-8",
    )
    (tmp_path / ".github" / "workflows" / "y.yml").write_text(
        "run: |\n  if [ -f .github/attribution-since ]; then :; fi\n"
        '  echo "нет .github/authors.txt"\n',
        encoding="utf-8",
    )
    assert literal_reads(tmp_path) == [
        ("x.py", "docs/decisions"),
        ("y.yml", ".github/attribution-since"),
    ]
