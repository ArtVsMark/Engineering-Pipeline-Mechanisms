"""Заготовка свода для потребителя не расходится с нашим сводом молча (#995, пункт 1).

РЕШЕНИЕ ВЛАДЕЛЬЦА 06.10.2026, вариант А. Заготовка — отдельные файлы
`kit/AGENTS.md` и `kit/CLAUDE.md`: общая часть (как окно работает с
конвейером) и заглушки наполнения, которое пишет владелец потребителя. Наш
свод не делится — его правка перезапускает окна (047).

ВТОРОЙ ИСТОЧНИК ДЕРЖИТСЯ СВЕРКОЙ, А НЕ ВНИМАНИЕМ (022). Единица сверки —
абзац прозы и пункт блока кода: заготовка берёт из раздела нашего свода
только переносимое, и каждая её общая единица обязана стоять дословно в
одноимённом разделе нашего свода. Правка абзаца у нас без правки заготовки
краснеет здесь. Обратного гейт не держит, и ПРЕДЕЛ НАЗВАН: новый абзац
нашего свода в заготовку сам не попадает — переносимый ли он, решает чтение.
И второй предел: сверяется текст единицы, а не её опора — абзац, который
ссылается на «строку выше» или на шаг из вырезанной единицы, проходит
дословно и ведёт в пустоту. Это держит чтение при отборе (взгляд на #1179).
Третий предел — соседний случай второго (195): единица называет МЕХАНИЗМ
словами («шаг открытия предупреждает…»), а не путём, и едет ли он к
потребителю, решает не текст, а `onboard.py`. Путь гейт ловит
(`foreign`), прозу о механизме — нет; держит чтение, и абзац о фактах
нашего окружения уходит в заглушку, а не в общую часть (поздний взгляд
на #1179).
КРИТЕРИЙ ОТБОРА, по которому читают: ФАКТ ОКРУЖЕНИЯ — всегда наполнение.
Что выдаёт платформа, что делает прокси на записи, есть ли `gh` — это
замер нашего окна, и в общей части он стал бы утверждением о чужом проекте.
Общей частью едут правило и его довод, а не наш замер; запрет, довод
которого — замер, едет заглушкой с адресом правила (взгляд на #1190).

ЗАГЛУШКА НАПОЛНЕНИЯ — единица, которая начинается с `FILLING`. Её текст
свободен: это место, где потребитель пишет своё, а не наша формулировка.
"""

import re
from typing import Final

import pytest

from tests.conftest import ROOT, load_script
from tests.test_portable import NAMED_PATH, consumer_has, inventory

paths = load_script("paths.py")
RULEBOOK = load_script("check_rulebook_fresh.py")

#: Начало заглушки наполнения: всё, что с него начинается, пишет потребитель.
FILLING: Final = "> **Наполнение проекта:**"
FENCE: Final = "```"
#: Ссылка разметки с относительным адресом: внешний адрес и якорь — не путь дерева.
RELATIVE_LINK: Final = re.compile(r"\]\((?!https?://|#)([^)\s]+)\)")


def units(text: str) -> dict[str, list[str]]:
    """Разделы документа (`## …`; вступление — ключ "") и их единицы сверки.

    Единица прозы — абзац между пустыми строками. В блоке кода единица —
    пункт: строка без отступа вместе со своими строками продолжения. Так
    заготовка берёт из блока запретов только переносимые пункты, а не весь
    блок или ничего. Заголовок первого уровня — имя документа, а не единица:
    у потребителя оно своё.
    """
    found: dict[str, list[str]] = {"": []}
    section, fenced = "", False
    held: list[str] = []

    def flush() -> None:
        if held:
            found[section].append("\n".join(held))
            held.clear()

    for line in text.splitlines():
        if line.startswith(FENCE):
            flush()
            fenced = not fenced
        elif fenced:
            if not line.strip() or not line[0].isspace():
                flush()
            if line.strip():
                held.append(line)
        elif line.startswith("## "):
            flush()
            section = line[3:].strip()
            found[section] = []
        elif line.startswith("# ") or not line.strip():
            flush()
        else:
            held.append(line)
    flush()
    return found


def common(found: dict[str, list[str]]) -> dict[str, list[str]]:
    """Общие единицы по разделам — всё, кроме заглушек наполнения."""
    return {
        section: kept
        for section, said in found.items()
        if (kept := [one for one in said if not one.startswith(FILLING)])
    }


def strays(kit: str, ours: str) -> list[str]:
    """Общие единицы заготовки, которых нет дословно в одноимённом разделе нашего свода."""
    mine = units(ours)
    return [
        f"[{section or 'вступление'}] {one.splitlines()[0][:80]}"
        for section, said in common(units(kit)).items()
        for one in said
        if one not in mine.get(section, [])
    ]


def foreign(text: str) -> list[str]:
    """Пути нашего дерева, которые заготовка называет, а у потребителя их не будет.

    Читается и ссылка разметки, и путь буквами: заготовка — инструкция окну,
    и `scripts/…` в её прозе ведёт в пустоту так же, как ссылка.
    """
    answers = inventory()["answers"]
    said = {match.group(1) for match in NAMED_PATH.finditer(text)}
    said |= {match.group(1).split("#")[0] for match in RELATIVE_LINK.finditer(text)}
    return sorted(one for one in said if one and not consumer_has(one.rstrip("/"), answers))


def kits() -> list[str]:
    """Имена свода, у которых есть заготовка: состав свода — у гейта его свежести (022)."""
    return [name for name in RULEBOOK.RULEBOOK if (ROOT / paths.KIT / name).is_file()]


def test_every_part_of_the_rulebook_has_its_kit() -> None:
    """Заготовка есть у каждого файла свода: потребителю нужен весь свод, а не половина."""
    missing = set(RULEBOOK.RULEBOOK) - set(kits())
    assert not missing, f"заготовки нет у {sorted(missing)}"


@pytest.mark.parametrize("name", RULEBOOK.RULEBOOK)
def test_the_common_part_of_the_kit_stands_in_our_rulebook(name: str) -> None:
    """Каждая общая единица заготовки стоит дословно в одноимённом разделе нашего свода."""
    kit = (ROOT / paths.KIT / name).read_text(encoding="utf-8")
    found = strays(kit, (ROOT / name).read_text(encoding="utf-8"))
    assert not found, (
        f"{paths.KIT / name}: общая часть разошлась с {name} — поправьте заготовку "
        f"или пометьте единицу заглушкой «{FILLING}»: {found}"
    )


@pytest.mark.parametrize("name", RULEBOOK.RULEBOOK)
def test_the_kit_is_a_kit_and_not_a_copy_or_a_blank(name: str) -> None:
    """Есть и общая часть, и наполнение: без первой сверять нечего (075), без второго это копия."""
    said = units((ROOT / paths.KIT / name).read_text(encoding="utf-8"))
    assert common(said), f"{paths.KIT / name}: общей части нет — гейт сверял бы пустоту (075)"
    filling = [one for part in said.values() for one in part if one.startswith(FILLING)]
    assert filling, f"{paths.KIT / name}: заглушек наполнения нет — это копия нашего свода"


@pytest.mark.parametrize("name", RULEBOOK.RULEBOOK)
def test_the_kit_names_only_what_the_consumer_has(name: str) -> None:
    """Заготовка не ведёт в наше дерево: `docs/`, `scripts/` у потребителя нет."""
    found = foreign((ROOT / paths.KIT / name).read_text(encoding="utf-8"))
    assert not found, f"{paths.KIT / name}: названо то, чего у потребителя не будет: {found}"


OURS: Final = """# Наш свод

> **Читатель:** агент.

## Запреты

```
❌ НЕ писать в main
❌ НЕ открывать учётными данными агента:
   автором станет приложение
❌ НЕ трогать CONTRACT_VERSION
```

Абзац общий,
в две строки.
"""


@pytest.mark.parametrize(
    ("kit", "stray"),
    [
        ("# Свой\n\n## Запреты\n\n```\n❌ НЕ писать в main\n```\n", False),
        (
            "## Запреты\n\n```\n❌ НЕ открывать учётными данными агента:\n"
            "   автором станет приложение\n```\n",
            False,
        ),
        ("## Запреты\n\nАбзац общий,\nв две строки.\n", False),
        ("## Своё\n\n> **Наполнение проекта:** что угодно\n", False),
        ("> **Читатель:** агент.\n", False),
        ("## Запреты\n\nАбзац общий,\nв три строки.\n", True),
        ("## Запреты\n\n```\n❌ НЕ открывать учётными данными агента:\n```\n", True),
        ("## Другое\n\nАбзац общий,\nв две строки.\n", True),
    ],
    ids=[
        "пункт блока",
        "пункт с продолжением",
        "абзац",
        "заглушка",
        "вступление",
        "правленный абзац",
        "обрезанный пункт",
        "чужой раздел",
    ],
)
def test_strays_tell_a_taken_unit_from_a_changed_one(kit: str, stray: bool) -> None:
    """Обе половины сверки: взятое дословно проходит, правленое и перенесённое — нет."""
    assert bool(strays(kit, OURS)) is stray


def test_a_path_of_our_tree_in_the_kit_is_foreign() -> None:
    """Обе половины: наш документ и скрипт чужие потребителю, свод и внешний адрес — нет."""
    text = (
        "[`docs/use/pipeline.md`](docs/use/pipeline.md) · `scripts/preflight.py` · "
        "[`AGENTS.md`](AGENTS.md) · [каталог](https://example.org/rules) · [вверх](#раздел)"
    )
    assert foreign(text) == ["docs/use/pipeline.md", "scripts/preflight.py"]


def test_units_keep_the_last_item_and_an_empty_section() -> None:
    """Разбор не теряет пункт в конце блока и раздел без единиц."""
    said = units("## Пусто\n\n## Блок\n\n```\nодин\n  продолжение\nдва\n```\n")
    assert said == {"": [], "Пусто": [], "Блок": ["один\n  продолжение", "два"]}
