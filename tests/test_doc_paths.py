"""Путь в обратных кавычках в документе ведёт к файлу, который есть.

ССЫЛКИ ДЕРЖИТ СОСЕД, ПУТИ В КАВЫЧКАХ — НИКТО (#1675). `tests/test_doc_links.py`
судит ссылки Markdown, `tests/test_live_references.py` — адреса `модуль.имя` в
коде. Но документы чаще пишут путь не ссылкой, а инлайн-кодом — `` `scripts/x.py` ``, —
и такой путь после переименования молча вёл в пустоту. Замер 25.10.2026 на
`main` `f0e59689`: в 76 документах 351 путь в кавычках, 27 не находились в
дереве. Двадцать из них — записи решений, семь — пути другого дерева (ниже);
гнилых в живых документах — ноль, потому что первая волна сверки (#1678) их
уже починила. Гейт держит, чтобы новые не появлялись.

ПУТЬ РАЗРЕШАЕТСЯ ТРЕМЯ СПОСОБАМИ, И ТРЕТИЙ — ОБЪЯВЛЕНИЕМ. Файл нашего дерева;
файл заготовки потребителя — тот же путь под `kit/data/` (его кладёт заход
подключения, `scripts/onboard.py`); путь, который живёт не в общей ветке, —
только из закрытого перечня `ELSEWHERE` с причиной (068, 154). Разрешающего
«всё, что похоже на путь потребителя» нет: по виду такой путь неотличим от
опечатки.

ГРАНИЦЫ НАЗВАНЫ (046, 195):
- записи решений (`docs/decisions/`) не судятся: запись — состояние на день
  решения, и править её задним числом запрещает `scripts/check_decisions_edit.py`;
  старое имя там — история, а не гниль;
- журнал (`CHANGELOG.md`, фрагменты `changelog.d/`) — тоже история; живое
  описание формы фрагментов, `changelog.d/README.md`, судится как документ;
- судятся пути под девятью корнями дерева (`PATH_RE`) с расширением из
  перечня: корневые файлы (`AGENTS.md`, `pyproject.toml`) и прочие корни образец
  не видит — у корня свой короткий набор, и по виду слово с точкой в кавычках
  неотличимо от имени без пути;
- пути в комментариях кода гейт не читает — у кода свой сосед,
  `tests/test_live_references.py`, и он судит адреса функций, а не файлов;
- смысл пути — тот ли это файл, о котором говорит фраза, — машине не виден (057).
"""

import re
from pathlib import Path
from typing import Final

from tests.conftest import ROOT
from tests.test_doc_links import documents

#: Путь в инлайн-коде: корневой каталог дерева, имя файла с расширением; хвост
#: `::имя` (тест или функция) отрезается — судится файл.
PATH_RE: Final = re.compile(
    r"`(?P<path>(?:scripts|tests|docs|\.github|\.rules|\.claude|kit|packages|export)"
    r"/[\w./-]+?\.(?:py|yml|yaml|md|json|sh|toml|txt|svg))(?:::[\w.]+)?`"
)
#: Документы-история: старое имя в них законно (см. шапку).
HISTORY: Final = ("docs/decisions/", "changelog.d/", "CHANGELOG.md")
#: Живые документы под приставкой истории: описание, а не запись.
LIVE_IN_HISTORY: Final = frozenset({"changelog.d/README.md"})
#: Заготовка потребителя: путь `X` у потребителя — это `kit/data/X` у нас.
KIT: Final = Path("kit") / "data"
#: Пути, которые живут не в общей ветке этого дерева, — каждый с причиной.
ELSEWHERE: Final[dict[str, str]] = {
    ".claude/kit-laid.json": "пишет заход подключения в дереве потребителя (`scripts/onboard.py`)",
    ".github/badges/facts.json": "ветка `badges`, а у издателя — до публикации",
    ".github/badges/contracts.json": "ветка `badges`: манифест семьи рядом с фактами",
    ".github/badges/findings.json": "ветка `badges`: архив находок (`scripts/findings_archive.py`)",
}


def dead_paths(doc: Path, text: str, root: Path = ROOT) -> list[str]:
    """Пути документа, которых нет ни в дереве, ни в заготовке, ни в `ELSEWHERE`."""
    dead = []
    for found in PATH_RE.finditer(text):
        path = found.group("path")
        if (root / path).exists() or (root / KIT / path).exists() or path in ELSEWHERE:
            continue
        line = text[: found.start()].count("\n") + 1
        dead.append(f"{doc.relative_to(root).as_posix()}:{line}: `{path}`")
    return dead


def live_documents() -> list[Path]:
    """Документы, которые судятся: все, кроме истории."""
    return [
        doc
        for doc in documents()
        if (name := doc.relative_to(ROOT).as_posix()) in LIVE_IN_HISTORY
        or not name.startswith(HISTORY)
    ]


def test_every_path_in_the_documents_is_live() -> None:
    """Путь в кавычках ведёт к файлу дерева, заготовки или объявленному «не здесь»."""
    dead = [
        line
        for doc in live_documents()
        for line in dead_paths(doc, doc.read_text(encoding="utf-8"))
    ]
    assert not dead, (
        "путь в документе ведёт в пустоту — переименован или удалён:\n  "
        + "\n  ".join(dead)
        + "\n  Живёт не в общей ветке — внесите его в ELSEWHERE с причиной."
    )


def test_the_documents_name_paths_at_all() -> None:
    """Предмет есть: документы называют сотни путей, гейт не проходит ноль раз (075)."""
    named = sum(len(PATH_RE.findall(doc.read_text(encoding="utf-8"))) for doc in live_documents())
    assert named > 100, f"путей в кавычках всего {named} — образец перестал их видеть"


def test_every_elsewhere_path_is_still_named() -> None:
    """Объявление «живёт не здесь» не переживает упоминание (154): снятое — снимается."""
    said = "\n".join(doc.read_text(encoding="utf-8") for doc in live_documents())
    stale = sorted(path for path in ELSEWHERE if f"`{path}`" not in said)
    assert not stale, f"в ELSEWHERE объявлены пути, которых документы больше не называют: {stale}"


def test_a_missing_path_is_named_and_a_present_one_is_not(tmp_path: Path) -> None:
    """Обе половины: несуществующий путь назван с местом, существующий — нет."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "есть.py").write_text("", encoding="utf-8")
    doc = tmp_path / "doc.md"
    text = "Зовёт `scripts/есть.py::main`,\nа прежде звал `scripts/нет.py`.\n"
    assert dead_paths(doc, text, tmp_path) == ["doc.md:2: `scripts/нет.py`"]


def test_a_kit_path_and_a_declared_one_resolve(tmp_path: Path) -> None:
    """Путь потребителя разрешается заготовкой, «не здесь» — объявлением, а не видом."""
    (tmp_path / "kit" / "data" / ".claude").mkdir(parents=True)
    (tmp_path / "kit" / "data" / ".claude" / "preflight.sh").write_text("", encoding="utf-8")
    doc = tmp_path / "doc.md"
    text = "`.claude/preflight.sh`, `.github/badges/facts.json`, `.claude/kit-lost.json`"
    assert dead_paths(doc, text, tmp_path) == ["doc.md:1: `.claude/kit-lost.json`"]


def test_a_live_document_under_a_history_prefix_is_judged() -> None:
    """Описание формы фрагментов — живой документ, а не запись истории."""
    judged = {doc.relative_to(ROOT).as_posix() for doc in live_documents()}
    assert judged >= LIVE_IN_HISTORY
    assert not any(name.startswith("docs/decisions/") for name in judged)
