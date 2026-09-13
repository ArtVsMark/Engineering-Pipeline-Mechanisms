"""Форма фрагментов журнала проверяется на ВСЁМ дереве, а не на тронутом.

ГЕЙТ ИЗМЕНЕНИЯ ВИДИТ ТОЛЬКО СВОИ ФАЙЛЫ, и в этом дыра, которая уже сработала.
`scripts/build_changelog.py --fragments` разбирает фрагменты, которые тронуло
ИЗМЕНЕНИЕ; фрагмент, приехавший из общей ветки слиянием, мимо него проходит.

ЗАМЕР 11.09.2026. Форма причины у рода ``internal`` заведена одним изменением;
пока оно стояло в очереди, в общую ветку слился третий внутренний фрагмент,
написанный по старой форме. Гейт изменения его не видел, а споткнулась бы о
него СБОРКА ВЫПУСКА — то есть шаг, который нельзя отменить
([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)).
Нашёл внешний взгляд на #212.

Поэтому здесь тот же разбор, но по ВСЕЙ папке и на каждом изменении: новое
правило проверяется против уже накопленного корпуса, а не только против того,
что принесла его же правка
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script

module = load_script("build_changelog.py")
journal = load_script("journal.py")

FRAGMENTS = ROOT / "changelog.d"


def files() -> list[Path]:
    """Все фрагменты папки, кроме её описания.

    ПУСТАЯ ПАПКА ЗДЕСЬ — ЗАКОННОЕ СОСТОЯНИЕ, А НЕ ОТСУТСТВИЕ ПРЕДМЕТА. Выпуск
    переносит фрагменты в `changelog.d/released/<версия>/`, и сразу после него в
    папке остаётся один `README.md`. Красное на этом было бы ложным ровно того
    класса, который этот набор и ловит: здоровое дерево, объявленное поломкой.
    Нашёл внешний взгляд на #212.

    Разница с правилом
    [075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)
    проходит по тому, ОБЯЗАН ли предмет существовать. У гейта изменения обязан —
    изменение без фрагмента отвергается. У дерева между выпуском и следующим
    изменением — нет.
    """
    assert FRAGMENTS.is_dir(), "папки фрагментов нет вовсе — это поломка дерева, а не пустота"
    assert (FRAGMENTS / "README.md").is_file(), "описание папки фрагментов пропало"
    return sorted(p for p in FRAGMENTS.glob("*.md") if p.name != "README.md")


def test_an_emptied_folder_is_a_state_not_a_failure() -> None:
    """Сразу после выпуска в папке остаётся один `README.md` — и это не красное.

    Проверяется тем, что гейт обязан ПРИНЯТЬ: пустой список фрагментов
    разбирается в пустой список записей, а не в отказ (140).
    """
    assert module.parse_fragments([]) == []
    assert module.parse_fragments([FRAGMENTS / "README.md"]) == []


def test_every_fragment_in_the_tree_parses() -> None:
    """Каждый лежащий фрагмент разбирается ТЕМ ЖЕ разбором, что и выпуск.

    Своей копии правил здесь нет намеренно: вторая копия приняла бы то, что
    первая отвергает, и разошлись бы они молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    parsed = module.parse_fragments(files())
    assert len(parsed) == len(files())


@pytest.mark.parametrize(
    "body, why",
    [
        ("### Заголовок без причины\n\n#1", "род `internal` без причины первой строкой"),
        ("> **Потребителю безразлично:**\n\n#1", "пустая причина"),
        ("> Потребителю безразлично: так\n\n#1", "причина без разметки"),
    ],
)
def test_an_internal_fragment_without_a_reason_is_rejected(
    tmp_path: Path, body: str, why: str
) -> None:
    """Род `internal` без причины первой строкой отвергается.

    «Журналу это безразлично» — состояние, а не молчание, и состояние обязано
    назвать себя
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    Правило держалось прозой `changelog.d/README.md` и не держалось ничем —
    оба внутренних фрагмента проекта его нарушали. Проверяется оно тем, что
    обязано отвергнуть (140).
    """
    bad = tmp_path / "a-slug.internal.md"
    bad.write_text(body, encoding="utf-8")
    with pytest.raises(module.NotRun) as refused:
        module.parse_fragments([bad])
    assert "internal" in str(refused.value), why


def test_the_reason_is_required_only_of_internal(tmp_path: Path) -> None:
    """Прочие роды причины не требуют: у них она и есть само содержание."""
    good = tmp_path / "a-slug.fixed.md"
    good.write_text("### Починка\n\nЧто было и что стало.\n\n#1", encoding="utf-8")
    assert len(module.parse_fragments([good])) == 1


def test_the_reason_line_matches_what_the_spec_shows() -> None:
    """Образец в описании папки — тот самый, что принимает разбор.

    Расхождение между показанной формой и принимаемой хуже отсутствия обеим:
    автор пишет по образцу и получает красное (022).
    """
    spec = (FRAGMENTS / "README.md").read_text(encoding="utf-8")
    shown = [line for line in spec.splitlines() if "Потребителю безразлично" in line]
    assert shown, "описание папки не показывает форму причины"
    for line in shown:
        assert journal.REASON_LINE_RE.match(line.strip()), f"образец не проходит разбор: {line}"


# --- переезд записи и её ссылки ----------------------------------------------


def test_a_link_into_the_tree_is_recalculated_on_the_way_to_the_changelog() -> None:
    """Ссылка на файл дерева пересчитывается под новое место записи.

    Фрагмент пишется, лёжа в `changelog.d/`, и адресует соседей оттуда.
    Собранный журнал живёт в корне: та же строка ведёт выше корня и в пустоту.
    """
    said = "[решение](../docs/decisions/006-merge-by-squash.md)"
    assert module.relink(said, was=Path("changelog.d"), now=Path(".")) == (
        "[решение](docs/decisions/006-merge-by-squash.md)"
    )


def test_a_link_follows_the_fragment_into_the_release_directory() -> None:
    """Переезд в каталог выпуска уводит запись на два уровня вниз — и ссылку тоже."""
    said = "[решение](../docs/decisions/006-merge-by-squash.md)"
    moved = module.relink(said, was=Path("changelog.d"), now=Path("changelog.d/released/9.9.0"))
    assert moved == "[решение](../../../docs/decisions/006-merge-by-squash.md)"


def test_a_platform_address_is_left_alone() -> None:
    """Адрес площадки выглядит относительным, но разрешается не в дереве.

    Трогать его вслепую значит менять работающее на угаданное. Предел назван, а
    не заровнен
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    said = "[#183](../../pull/183)"
    assert module.relink(said, was=Path("changelog.d"), now=Path(".")) == said


def test_an_outside_address_and_an_anchor_keep_their_shape() -> None:
    """Внешний адрес не трогается, а якорь переезжает вместе со своим файлом."""
    outside = "[каталог](https://github.com/ArtVsMark/Engineering-Incidents-Playbook)"
    assert module.relink(outside, was=Path("changelog.d"), now=Path(".")) == outside
    anchored = "[порядок](../docs/release.md#порядок-выпуска)"
    assert module.relink(anchored, was=Path("changelog.d"), now=Path(".")) == (
        "[порядок](docs/release.md#порядок-выпуска)"
    )


def test_a_text_that_did_not_move_is_untouched() -> None:
    """Переезда не было — переписывать нечего: разбор не трогает текст зря."""
    said = "[решение](../docs/decisions/006-merge-by-squash.md)"
    assert module.relink(said, was=Path("changelog.d"), now=Path("changelog.d")) == said


check = load_script("check_journal.py")


def test_outward_counts_themes_and_not_internal_notes() -> None:
    """Тема — запись наружу; внутренней сопровождают чужую работу (132)."""
    записи = [
        "changelog.d/a-theme.added.md",
        "changelog.d/a-side-note.internal.md",
        "changelog.d/another-theme.fixed.md",
    ]
    assert check.outward(записи) == [
        "changelog.d/a-theme.added.md",
        "changelog.d/another-theme.fixed.md",
    ]


def test_say_if_compound_speaks_only_above_the_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Порог взят замером, и молчание ниже него — тоже ответ.

    Замер 13.09.2026 по 120 слитым: одна запись наружу у 101 изменения. Гейт,
    предупреждающий на норме, учит пролистывать предупреждения (051).
    """
    check.say_if_compound(["changelog.d/one.added.md", "changelog.d/note.internal.md"])
    assert capsys.readouterr().err == "", "одна тема предупреждения не заслуживает"

    check.say_if_compound(["changelog.d/one.added.md", "changelog.d/two.fixed.md"])
    said = capsys.readouterr().err
    assert "::warning::" in said and "наружу: 2" in said
    assert "разделите" in said, "предупреждение называет, что делать (142)"
