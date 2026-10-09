"""Ссылка из оригинала в копию: только картинкой, никогда текстом.

ПРЕДМЕТ — КОПИЯ ОРИГИНАЛА, А НЕ ВСЯКОЕ ПРОИЗВОДНОЕ (решение владельца 09.10.2026,
#1213). Правило 089 говорит о связи источника с его витриной: копия отстаёт от
оригинала, и ссылка уводит в прошлое. Производное, у которого оригинала в
дереве НЕТ — данные обхода чужих деревьев, — не копия: свежее места нет, и
ссылка на него никуда не уводит. Такие имена названы перечнем
`NO_ORIGINAL_IN_TREE` с причиной, а не выведены догадкой (046). Прежняя редакция
запрещала текстом любой адрес производного и тем трактовала 089 шире буквы.

Связь источника с витриной односторонняя. Ссылка из оригинала в копию уводит
читателя на заведомо более старое — витрина пересобирается прогоном и отстаёт от
дерева всегда, — а полноту источника начинают мерить по чужому справочнику
([089](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/089-never-link-from-the-original-to-its-copy.md)).

ЧЕМ КАРТИНКА ОТЛИЧАЕТСЯ ОТ ССЫЛКИ, И ПОЧЕМУ РАЗНИЦА НЕ КОСМЕТИЧЕСКАЯ. Значок
показывает ЧИСЛО и никуда не ведёт: читатель остаётся в дереве. Ссылка текстом
уводит — и уводит на копию, собранную прошлым прогоном. Поэтому разрешена ровно
одна форма: имя внутри цели картинки. Тот же предикат держит и «значок показан»
(`tests/conftest.py`), и по той же причине: проверка ОТНОШЕНИЯ через присутствие
подстроки зеленеет там, где отношения нет
([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН: документов в дереве 504, адресов
своего производного — шесть, все шесть картинкой, текстом ноль. То есть
требование исполнялось и не держалось ничем: соседний гейт
(`scripts/check_derived_refs.py`) проверяет ОБРАТНОЕ — что названное производное
нарисовано, — и ссылку текстом пропускает как законную
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

РАЗБОР АДРЕСА НЕ ЗАВОДИТСЯ ЗАНОВО: он живёт у `check_derived_refs.py`, который
знает обе формы адреса площадки — `raw.githubusercontent.com` и `blob|raw`. Вторая
копия разошлась бы с первой молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: ссылку на производное ЧУЖОГО
проекта. Там оригинал не наш, и правило говорит о связи со своей копией; сосед,
ссылающийся на нашу витрину, поступает законно — ему она и адресована
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

import re
from pathlib import Path
from typing import Final

from tests.conftest import ROOT, load_script, walk_deep

der = load_script("check_derived_refs.py")
paths = load_script("paths.py")

#: Цель картинки: `![подпись](адрес)`. Ссылка без восклицательного знака — не она.
IMAGE: Final = re.compile(r"!\[[^\]]*\]\([^)\s]*\)")
#: Наше имя у площадки — ВЛАДЕЛЕЦ И РЕПОЗИТОРИЙ ЦЕЛИКОМ, а не подстрока.
#: Сравнение подстрокой принимало за своё чужой `Somebody/…-Mechanisms-Fork`:
#: у соседа по имени наша копия не наша, и ссылка на неё законна
#: ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
#: Нашёл внешний взгляд.
OURS: Final = "ArtVsMark/Engineering-Pipeline-Mechanisms"
#: Производное без оригинала в дереве — ПОЛНЫЙ адрес на ветке `badges` и почему.
#: Ссылка текстом на них законна: копией чего-то из дерева они не являются.
#: Адрес целиком, с веткой и путём, а не имя файла: иначе одноимённая копия в
#: другом каталоге или на другой ветке прошла бы как законный текст (взгляд на #1280).
WITHOUT_ORIGIN_BRANCH: Final = "badges"
NO_ORIGINAL_IN_TREE: Final = {
    f"{paths.BADGES_DIR.as_posix()}/who.md": (
        "кто из семьи зовёт наши шаги — обход клонов соседей; в дереве этих данных нет"
    ),
}


def documents() -> list[Path]:
    """Отслеживаемые документы дерева."""
    return sorted(path for path in walk_deep(ROOT, "*.md") if ".git" not in path.parts)


def addresses() -> list[tuple[Path, int, str, bool]]:
    """Адреса СВОЕГО производного в документах: файл, строка, ветка, внутри картинки."""
    found: list[tuple[Path, int, str, bool]] = []
    for path in documents():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in der.DERIVED_RE.finditer(line):
                where = match["rawrepo"] or match["repo"] or ""
                ref = match["rawref"] or match["ref"] or ""
                path_on_branch = (match["rawpath"] or match["path"] or "").lstrip("/")
                if where.lower() != OURS.lower() or ref == paths.TRUNK:
                    continue
                if ref == WITHOUT_ORIGIN_BRANCH and path_on_branch in NO_ORIGINAL_IN_TREE:
                    continue
                inside = any(
                    shot.start() <= match.start() and match.end() <= shot.end()
                    for shot in IMAGE.finditer(line)
                )
                found.append((path, number, ref, inside))
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Адресов производного нет — отказ, а не «чисто» (075)."""
    assert documents(), "документов в дереве не нашлось — сверять нечего"
    assert addresses(), (
        "ни один документ не называет своего производного — предмет проверки не найден:"
        " витрина либо не показывается вовсе, либо адрес её изменился"
    )


def test_a_derived_address_is_only_ever_an_image() -> None:
    """Адрес производного стоит целью КАРТИНКИ, а не ссылкой в текст."""
    away = [
        f"{path.relative_to(ROOT)}:{number} — ветка «{ref}» названа ссылкой, а не картинкой"
        for path, number, ref, inside in addresses()
        if not inside
    ]
    assert not away, (
        "ссылка из оригинала в копию уводит читателя на заведомо более старое (089):\n  "
        + "\n  ".join(away)
        + "\n  Значок показывают картинкой — он несёт число и никуда не ведёт."
        "\n  За содержимым читателя отправляют к источнику в дереве, а не к витрине."
    )


def test_a_neighbours_repository_is_not_taken_for_ours() -> None:
    """Чужой репозиторий с похожим именем своим не считается.

    Сравнение подстрокой принимало за своё `Somebody/…-Mechanisms-Fork`: у
    соседа по имени наша копия не наша, и ссылка на неё законна — правило о
    связи оригинала с копией говорит о СВОЕЙ копии. Нашёл внешний взгляд.
    """
    assert OURS.count("/") == 1, "своё имя названо без владельца — сравнивать будет нечего"
    for foreign in (
        "Somebody/Engineering-Pipeline-Mechanisms-Fork",
        "Other/Engineering-Pipeline-Mechanisms",
        "ArtVsMark/Engineering-Pipeline-Mechanisms-Docs",
    ):
        assert foreign.lower() != OURS.lower(), f"{foreign} принят за своё"


def test_every_exception_is_laid_by_the_build() -> None:
    """Исключение называет то, что сборка и правда кладёт: мёртвое имя краснеет (005)."""
    facts = load_script("build_facts.py")
    laid = {f"{paths.BADGES_DIR.as_posix()}/{name}" for name in facts.branch_files()}
    stale = sorted(set(NO_ORIGINAL_IN_TREE) - laid)
    assert not stale, f"исключение 089 называет то, чего сборка не кладёт: {stale}"


def test_the_exception_has_no_original_in_the_tree() -> None:
    """Основание исключения держится сборкой: из одного дерева таблицы «кем» не собрать.

    Таблица читает раздел фактов семьи «uptake», а его даёт только обход клонов (`--uptake`).
    Ляжет этот вход в дерево — сборка без обхода прочтёт его, исключение станет
    ложным, и здесь покраснеет (взгляд на #1280, 044).
    """
    facts = load_script("build_facts.py")
    tree_only = facts.family_facts(None, answers=ROOT / ".rules" / "bindings.json")
    assert not tree_only["uptake"].get("read"), (
        "family.uptake прочитан без обхода клонов — у таблицы «кем» есть оригинал в дереве,"
        " и исключение 089 для неё больше не законно"
    )
