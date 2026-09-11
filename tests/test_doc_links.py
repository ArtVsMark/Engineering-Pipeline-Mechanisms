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

import pytest

from tests.conftest import ROOT

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
    found = sorted(ROOT / name for name in listed.stdout.split("\0") if name.endswith(".md"))
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


def unresolved(path: Path) -> list[str]:
    """Ссылки документа, которым некуда вести."""
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
