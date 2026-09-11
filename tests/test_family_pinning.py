"""Гейт правила 155: заготовка, которую проект раздаёт, применена у него самого.

ЧТО ЗДЕСЬ ЗАГОТОВКА. Проект раздаёт наружу не файлы, а **способ подключения**, и
говорит об этом прямо: «Это не сборник заготовок для копирования: подключение к
общим механизмам идёт версией, к которой потребитель прибит, а не переносом
файлов руками» (`README.md`). Заготовка — сам этот способ, и правило требует,
чтобы проект применял его у себя ТЕМ ЖЕ образом, каким предлагает потребителю.

ПРОВЕРЯЕТСЯ ДВА, И ОБА МАШИННО. Первое: каждое обращение к механизму семьи
закреплено версией-тегом, а не подвижной ссылкой — ветка или `@main` означают,
что проект советует потребителю прибиваться, а сам едет за головой. Второе: у
одного механизма семьи версия ОДНА на все прогоны. Две разные версии одного
механизма в одном дереве — это уже не подключение, а два подключения, и
расходятся они молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

ЧЕГО ЭТОТ ГЕЙТ НЕ ПРОВЕРЯЕТ, И ЭТО НАЗВАНО. Что файл семьи не скопирован в
дерево руками, машина отсюда не скажет: копию узнают по содержимому, а
содержимое чужого механизма здесь неизвестно. Эту половину держит гейт дрейфа
(`scripts/drift.py`), который спрашивает семью, и вычитка.

Чужие действия (не семьи) сюда не входят: их закрепление — предмет правила о
прибивании зависимостей, а не о своей же заготовке.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

from tests.conftest import ROOT

WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
#: Владелец семьи: проекты, между которыми и идёт подключение версией.
FAMILY = "ArtVsMark/"
#: Обращение к чужому механизму: `uses: <владелец>/<имя>[/путь]@<ссылка>`.
USES_RE = re.compile(r"uses:\s*(?P<repo>[\w.-]+/[\w.-]+)(?P<path>/[\w./-]+)?@(?P<ref>\S+)")
#: Закреплённая версия: тег вида `vN.N.N`. Мажорный алиас (`@v1`) сюда не
#: входит намеренно — он подвижен, и потребитель, прибитый к нему, едет вместе
#: с чужими правками.
PINNED_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def family_uses() -> list[tuple[Path, int, str, str]]:
    """Обращения к механизмам семьи: где, к какому репозиторию и к какой ссылке."""
    found: list[tuple[Path, int, str, str]] = []
    for path in WORKFLOWS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = USES_RE.search(line)
            if match and match["repo"].startswith(FAMILY):
                found.append((path, number, match["repo"], match["ref"]))
    return found


def test_the_project_connects_to_the_family_at_all() -> None:
    """Предмет найден: подключения к семье есть (075).

    Без этой строки гейт зеленел бы на проекте, который свою же заготовку не
    применяет вовсе, — то есть ровно на том случае, ради которого построен.
    """
    assert family_uses(), "обращений к механизмам семьи нет — проверять нечего"


@pytest.mark.parametrize(
    ("path", "number", "repo", "ref"),
    family_uses(),
    ids=lambda value: str(value) if not isinstance(value, Path) else value.name,
)
def test_every_family_use_is_pinned_to_a_version(
    path: Path, number: int, repo: str, ref: str
) -> None:
    """Подключение идёт версией, как проект и советует потребителю (155)."""
    assert PINNED_RE.match(ref), (
        f"{path.name}:{number} — {repo}@{ref}: подключение не закреплено версией. "
        "Проект советует потребителю прибиваться к версии, а сам едет за головой"
    )


def test_one_family_mechanism_is_pinned_to_one_version() -> None:
    """У механизма семьи версия одна на всё дерево: две расходятся молча (022)."""
    versions: dict[str, set[str]] = defaultdict(set)
    for _path, _number, repo, ref in family_uses():
        versions[repo].add(ref)
    split = {repo: sorted(refs) for repo, refs in versions.items() if len(refs) > 1}
    assert not split, f"механизм семьи подключён двумя версиями сразу: {split}"
