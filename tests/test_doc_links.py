"""Гейт правила 022: ссылка внутри своих документов ведёт к существующему месту.

ПОЧЕМУ ЭТО ПОЛОВИНА ПРЕДМЕТА, И ПОЧЕМУ ИМЕННО ЭТА. Правило требует один
канонический документ на тему, а всё прочее — ссылками на него. Граница правила
сама называет предел машины: «битые ссылки — да, смысловое расхождение копий —
нет». Расхождение двух описаний одного и того же машина не увидит; ссылку,
ведущую в никуда, — увидит, и без неё канон не работает вовсе: читатель,
которого отправили по битому адресу, перепишет содержимое у себя.

ЧУЖИЕ ПРАВИЛА УЖЕ СВЕРЯЮТСЯ, СВОИ ДОКУМЕНТЫ — НЕТ. `scripts/check_rule_links.py`
держит ссылки на каталог правил; обхода ссылок между СВОИМИ документами не было,
и замер это подтвердил: `AGENTS.md` отправлял за решением по адресу
`../docs/decisions/…` — на один уровень выше корня, то есть в пустоту. Ссылка
стояла с 09.09.2026 и не краснела ни разу.

АДРЕС ПЛОЩАДКИ — НЕ ПУТЬ В ДЕРЕВЕ. `../../issues/7` выглядит как выход за
корень, а на площадке разрешается в задачу. Такие адреса из проверки выведены
списком РАЗРЕШЁННОГО (068): не «всё, что вышло за корень, пропускаем», а
«вышло за корень и дальше идёт известный раздел площадки».
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

#: Ссылка Markdown: `[текст](адрес)` и `[текст](адрес "подпись")`.
LINK_RE = re.compile(r"\[[^\]]*\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
#: Разделы площадки, к которым ведёт относительный адрес из документа. Они
#: разрешаются вне дерева, и файла для них не существует ни в одной ветке.
PLATFORM = (
    "issues",
    "pull",
    "pulls",
    "discussions",
    "wiki",
    "commit",
    "commits",
    "compare",
    "tree",
    "blob",
    "releases",
    "actions",
    "labels",
    "milestone",
    "projects",
)
#: Производные документы, которые здесь не проверяются ФАЙЛОМ, — с причиной (154).
#: Собранный журнал пересобирает только ВЫПУСК (030), и на изменении его трогать
#: нельзя: переезд документа (#840) оставляет в нём ссылку на старое место до
#: ближайшего выпуска, и чинить её изменением нечем. Но исключён только
#: закоммиченный файл, а не журнал: ниже проверяется журнал В ТОМ ВИДЕ, В КАКОМ
#: ЕГО СОБЕРЁТ ВЫПУСК, — `build_changelog.render`, с перепиской ссылок сборщика.
#: Без этого результат переписки не сверял никто (взгляд на #875).
DERIVED = frozenset({"CHANGELOG.md"})
#: Схемы, которые проверяются не здесь: внешние адреса ловит взгляд, а не гейт.
OUTSIDE = ("http://", "https://", "mailto:", "tel:")


def documents() -> list[Path]:
    """Отслеживаемые документы дерева: предмет проверки."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    )
    found = sorted(
        ROOT / name
        for name in listed.stdout.split("\0")
        if name.endswith(".md") and name not in DERIVED
    )
    assert found, "в дереве нет ни одного документа — проверять нечего (075)"
    return found


def anchors(text: str) -> set[str]:
    """Якоря документа: заголовки, приведённые к виду, которым их адресуют."""
    found: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        bare = re.sub(r"[^\w\s-]", "", line.lstrip("# ").strip(), flags=re.UNICODE)
        found.add(re.sub(r"\s+", "-", bare).strip("-").lower())
    return found


def goes_to_the_platform(target: str) -> bool:
    """Адрес ведёт в раздел площадки, а не в дерево."""
    parts = [part for part in target.split("/") if part not in (".", "")]
    if ".." not in parts:
        return False
    rest = [part for part in parts if part != ".."]
    return bool(rest) and rest[0] in PLATFORM


def unresolved(path: Path, text: str | None = None) -> list[str]:
    """Ссылки документа, которым некуда вести; `text` — содержимое, если файл не он."""
    if text is None:
        text = path.read_text(encoding="utf-8")
    here = path.relative_to(ROOT).as_posix()
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in LINK_RE.finditer(line):
            target = match["target"].strip("<>")
            if target.startswith(OUTSIDE) or goes_to_the_platform(target):
                continue
            where, _, anchor = target.partition("#")
            if not where:
                if anchor.lower() not in anchors(text):
                    problems.append(f"{here}:{number} — своего якоря «{anchor}» нет")
                continue
            landing = path.parent / where
            if not landing.exists():
                problems.append(f"{here}:{number} — «{target}» не ведёт ни к чему")
            elif anchor and landing.suffix == ".md":
                there = anchors(landing.read_text(encoding="utf-8"))
                if anchor.lower() not in there:
                    problems.append(f"{here}:{number} — в «{where}» нет якоря «{anchor}»")
    return problems


@pytest.mark.parametrize("path", documents(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_links_inside_our_own_documents_resolve(path: Path) -> None:
    """Ссылка на свой документ ведёт к существующему файлу и якорю (022)."""
    problems = unresolved(path)
    assert not problems, "ссылки, которым некуда вести:\n  " + "\n  ".join(problems)


def test_the_journal_as_the_release_builds_it_resolves() -> None:
    """Журнал, собранный выпуском сейчас, ведёт по живым адресам (взгляд на #875).

    Закоммиченный `CHANGELOG.md` отстаёт до выпуска, и это его право (030);
    собранный сборщиком из тех же фрагментов — нет: его ссылки и есть то, что
    получит потребитель.
    """
    builder = load_script("build_changelog.py")
    journal = ROOT / next(iter(DERIVED))
    problems = unresolved(journal, builder.render(builder.read_version()))
    assert not problems, "собранный журнал ведёт в никуда:\n  " + "\n  ".join(problems)


#: Где путь к документу пишется не ссылкой, а буквами: код, прогоны, таблицы
#: правил. Проверка ссылок их не видит, а переезд документа (#840) оставлял в
#: них старые пути — промпт взгляда, таблица ролей (взгляд на #875). Тесты вне
#: предмета: их фикстуры строят вымышленные пути намеренно, а настоящий путь,
#: ставший неверным, роняет сам тест.
NAMED_IN: Final = (".py", ".yml", ".yaml", ".json", ".toml", ".sh")
#: Путь к документу, написанный буквами.
DOC_PATH_RE: Final = re.compile(r"docs/[\w./-]+\.md")
#: Вымышленные пути в примерах — с причиной у каждого (071).
EXAMPLES: Final = {
    "docs/x.md": "пример переезда ссылки в описании `build_changelog.relink`",
}


def test_paths_named_outside_documents_exist() -> None:
    """Путь `docs/….md`, названный буквами в коде и прогонах, ведёт к файлу (взгляд на #875).

    Константы `scripts/paths.py` держат только те места, что их читают; прочие
    упоминания при следующем переезде нашлись бы глазами — или не нашлись.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    ).stdout.split("\0")
    stale = [
        f"{name}:{number} — {said}"
        for name in listed
        if name.endswith(NAMED_IN) and not name.startswith("tests/")
        for number, line in enumerate(
            (ROOT / name).read_text(encoding="utf-8").splitlines(), start=1
        )
        for said in DOC_PATH_RE.findall(line)
        if said not in EXAMPLES and not (ROOT / said).exists()
    ]
    assert not stale, "путь к документу, которого нет:\n  " + "\n  ".join(stale)


def test_the_check_sees_links_at_all() -> None:
    """Предмет найден: ссылки в дереве есть, и их разбирает тот же разбор (075)."""
    seen = sum(
        1
        for path in documents()
        for line in path.read_text(encoding="utf-8").splitlines()
        for match in LINK_RE.finditer(line)
        if not match["target"].strip("<>").startswith(OUTSIDE)
        and not goes_to_the_platform(match["target"].strip("<>"))
    )
    assert seen > 10, f"ссылок в дереве {seen} — разбор их не видит, и гейт зелен впустую"
