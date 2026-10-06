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

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, load_script, walk

module = load_script("build_changelog.py")
journal = load_script("journal.py")
journal_gate = load_script("check_journal.py")
changerefs = load_script("changerefs.py")

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
    return sorted(p for p in walk(FRAGMENTS, "*.md") if p.name != "README.md")


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
    anchored = "[порядок](../docs/dev/release.md#порядок-выпуска)"
    assert module.relink(anchored, was=Path("changelog.d"), now=Path(".")) == (
        "[порядок](docs/dev/release.md#порядок-выпуска)"
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


def test_travelled_names_only_what_the_commit_left_behind() -> None:
    """Разбор снятий прогнан НАПРЯМУЮ, а не только через вердикт гейта.

    Через вердикт проверяется, что гейт в целом отвергает верное; здесь — что
    именно он считает отставшим. Разница важна: сойдись вердикт по другой
    причине, отставшие назывались бы неверно, и чинить пошли бы не то.
    """
    said = journal_gate.marks_of("Разобрано: abc1234\nРазобрано: def5678, 21e7c8e — один дефект\n")
    assert said == {"abc1234", "def5678", "21e7c8e"}


def test_a_text_without_resolutions_yields_nothing() -> None:
    """Текста без снятий не хватает на отметку: пусто — это пусто, а не ноль."""
    assert journal_gate.marks_of("### Правка\n\nПроза без отметок.\n") == set()
    assert journal_gate.marks_of("") == set()


def test_a_prose_mention_of_the_word_is_not_a_mark() -> None:
    """Слово «Разобрано» в прозе без отпечатка отметкой не считается.

    Фрагменты этого проекта РАССКАЗЫВАЮТ о снятиях — «снятие живёт строкой
    „Разобрано:“ в теле», — и такой пересказ не должен требовать отпечатка в
    коммите: гейт краснел бы на тексте о механизме (051).
    """
    assert journal_gate.marks_of("снятие живёт строкой «Разобрано:» в теле изменения") == set()


#: Что git говорит, когда пути у предка не было. Снято с живого вызова
#: 17.09.2026; путь и ссылка заменены скобками, дословна ФОРМА сообщения — её и
#: разбирает гейт. Формулировка по памяти здесь уже подвела — подделка говорила
#: «fatal: path does not exist», а площадка называет путь и ссылку, — и гейт,
#: разбирающий сообщение, на такой
#: подделке проверялся впустую (170).
NO_SUCH_PATH_SAYS: Final = (
    "git show <ссылка>:<путь> → fatal: path '<путь>' does not exist in '<ссылка>'"
)
#: Вторая форма того же: путь ЕСТЬ в рабочем дереве и отсутствует в коммите.
#: Её нашёл живой прогон, а не память: первая редакция гейта знала одну форму и
#: покраснела на этой — то есть строгая сторона сработала, как обещано.
ON_DISK_NOT_IN_SAYS: Final = (
    "git show <sha>:<путь> → fatal: path '<путь>' exists on disk, but not in '<sha>'"
)
#: Отказ ДРУГОЙ природы: ссылки нет вовсе. Снято тем же заходом.
BROKEN_REF_SAYS: Final = "git show нет-такой-ссылки:README.md → fatal: invalid object name"


def fake_git(body: str, at_base: str) -> Callable[[list[str]], str]:
    """Подделка транспорта, РАЗБИРАЮЩАЯ команду: тело коммитов и вид у основания.

    Подделка, отвечающая одним текстом на любой вызов, здесь неверна с тех пор,
    как разбор спрашивает ДВЕ разные вещи: тело коммитов и вид фрагмента у
    основания. Отвечая обоим одно, она делает объявленное пустым — и проверка
    «все отметки уехали» перестаёт проверять то, чем названа.

    ЗАМЕРЕНО, А НЕ ОБЪЯВЛЕНО: механизм окалечен так, что тело коммитов не
    спрашивается ВОВСЕ (`carried = set()`). Со старой подделкой проверка
    осталась зелёной, с этой — покраснела
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """

    def _git(args: list[str]) -> str:
        if "merge-base" in args:
            return "деадбиф\n"
        if "show" in args:
            return at_base
        return f"починка\n\n{body}"

    return _git


def test_travelled_compares_the_fragment_with_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отставшими названы ровно те отметки, которых нет в теле коммита.

    Прогоняется сам разбор, а не только вердикт гейта: сойдись вердикт по
    другой причине, отставшие назывались бы неверно, и чинить пошли бы не то.
    """
    fragment = tmp_path / "changelog.d" / "правка.fixed.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Разобрано: abc1234\nРазобрано: def5678\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        journal_gate.journal,
        "changed_files",
        lambda base, alive_only=False, ancestor=None: [str(fragment.relative_to(tmp_path))],
    )
    monkeypatch.setattr(journal_gate.journal, "git", fake_git("Разобрано: abc1234\n", ""))
    assert journal_gate.travelled("origin/main") == ["def5678"]


def test_travelled_says_nothing_when_all_marks_rode_along(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Все отметки уехали — отставших нет: гейт судит расхождение, а не наличие."""
    fragment = tmp_path / "changelog.d" / "правка.fixed.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Разобрано: abc1234\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        journal_gate.journal,
        "changed_files",
        lambda base, alive_only=False, ancestor=None: [str(fragment.relative_to(tmp_path))],
    )
    monkeypatch.setattr(journal_gate.journal, "git", fake_git("Разобрано: abc1234\n", ""))
    assert journal_gate.travelled("origin/main") == []


def test_a_mark_the_fragment_already_carried_is_not_demanded_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отметку, стоявшую во фрагменте У ОСНОВАНИЯ, это изменение не везёт.

    Первая редакция гейта читала текущий текст фрагмента ЦЕЛИКОМ. Изменение,
    правящее в уже слитом фрагменте одну фразу, получало красное на чужих
    отметках — уехавших с тем изменением, которое их и объявило. Поймано на
    #438: девять отпечатков, повезти которые заново значило бы снять находки
    дважды.
    """
    fragment = tmp_path / "changelog.d" / "правка.fixed.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Разобрано: abc1234\n\nдописанная фраза\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        journal_gate.journal,
        "changed_files",
        lambda base, alive_only=False, ancestor=None: [str(fragment.relative_to(tmp_path))],
    )
    monkeypatch.setattr(journal_gate.journal, "git", fake_git("", "Разобрано: abc1234\n"))
    assert journal_gate.travelled("origin/main") == []


def test_a_mark_added_by_this_change_is_still_demanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вторая половина: НОВАЯ отметка в том же фрагменте по-прежнему требуется.

    Без неё послабление снесло бы гейт целиком: «фрагмент уже существовал»
    стало бы пропуском для всего, что в него допишут (051).
    """
    fragment = tmp_path / "changelog.d" / "правка.fixed.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Разобрано: abc1234\nРазобрано: def5678\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        journal_gate.journal,
        "changed_files",
        lambda base, alive_only=False, ancestor=None: [str(fragment.relative_to(tmp_path))],
    )
    monkeypatch.setattr(journal_gate.journal, "git", fake_git("", "Разобрано: abc1234\n"))
    assert journal_gate.travelled("origin/main") == ["def5678"]


def test_a_fragment_born_here_has_no_base_and_all_its_marks_are_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Фрагмента у основания нет — отказ `git show` значит «все отметки новые».

    Третий исход здесь обязан идти в СТРОГУЮ сторону: принять отказ чтения за
    «отметок у основания много» значило бы зеленеть ровно на новых фрагментах,
    ради которых гейт и стоит (045, 068).
    """
    fragment = tmp_path / "changelog.d" / "новое.added.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Разобрано: abc1234\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        journal_gate.journal,
        "changed_files",
        lambda base, alive_only=False, ancestor=None: [str(fragment.relative_to(tmp_path))],
    )

    def refusing(args: list[str]) -> str:
        if "merge-base" in args:
            return "деадбиф\n"
        if "show" in args:
            raise journal_gate.NotRun(NO_SUCH_PATH_SAYS)
        return "починка без отметок"

    monkeypatch.setattr(journal_gate.journal, "git", refusing)
    assert journal_gate.travelled("origin/main") == ["abc1234"]


def test_at_base_reads_the_file_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вид файла у основания спрашивается у истории, а не у рабочего дерева.

    Спрашивается прямо, а не только через вердикт: сойдись вердикт по другой
    причине, вычитаемое было бы взято не оттуда, и послабление стало бы шире
    заявленного.
    """
    asked: list[list[str]] = []

    def remembering(args: list[str]) -> str:
        asked.append(args)
        return "Разобрано: abc1234\n"

    monkeypatch.setattr(journal_gate.journal, "git", remembering)
    assert journal_gate.at_base("деадбиф", "changelog.d/правка.fixed.md") == (
        "Разобрано: abc1234\n"
    )
    assert asked == [["git", "show", "деадбиф:changelog.d/правка.fixed.md"]]


def test_at_base_says_empty_when_the_path_was_not_there(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пути у основания не было — пусто, и это законный исход, а не отказ захода."""

    def refusing(args: list[str]) -> str:
        raise journal_gate.NotRun(NO_SUCH_PATH_SAYS)

    monkeypatch.setattr(journal_gate.journal, "git", refusing)
    assert journal_gate.at_base("деадбиф", "changelog.d/новое.added.md") == ""


def test_both_forms_of_no_such_path_are_read_as_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обе формы отказа «пути там нет» читаются одинаково — как отсутствие.

    Форм у git две, и вторую нашёл ЖИВОЙ ПРОГОН: первая редакция знала одну, и
    набор покраснел на пути, который есть в рабочем дереве и отсутствует в
    коммите. Строгая сторона сработала как обещано — неузнанное назвалось, а не
    прочиталось как «файла не было».
    """
    for said in (NO_SUCH_PATH_SAYS, ON_DISK_NOT_IN_SAYS):

        def refusing(args: list[str], said: str = said) -> str:
            raise journal_gate.NotRun(said)

        monkeypatch.setattr(journal_gate.journal, "git", refusing)
        assert journal_gate.at_base("деадбиф", "changelog.d/новое.added.md") == "", said


def test_at_base_lets_an_unknown_refusal_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ НЕ про отсутствие пути уходит наверх, а не читается как «файла не было».

    Битая ссылка, обрезанный чекаут, сломанный репозиторий — при глушении любого
    отказа все они читались бы как «фрагмент здесь родился», и заход требовал бы
    увезти ВСЕ отметки, не сказав почему. Своя поломка не бывает зелёной (039).
    """

    def broken(args: list[str]) -> str:
        raise journal_gate.NotRun(BROKEN_REF_SAYS)

    monkeypatch.setattr(journal_gate.journal, "git", broken)
    with pytest.raises(journal_gate.NotRun):
        journal_gate.at_base("деадбиф", "changelog.d/правка.fixed.md")


def test_the_content_is_read_at_the_same_point_as_the_file_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Список файлов и их содержимое берутся у ОДНОГО общего предка.

    Вершина базы движется, пока изменение открыто: выпуск переносит фрагменты в
    `released/`, и `main:changelog.d/<фрагмент>` перестаёт существовать — все его
    отметки становятся «новыми», и заход требует увезти уже уехавшее. Нашёл
    внешний взгляд на #441.
    """
    fragment = tmp_path / "changelog.d" / "правка.fixed.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("Разобрано: abc1234\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        journal_gate.journal,
        "changed_files",
        lambda base, alive_only=False, ancestor=None: [str(fragment.relative_to(tmp_path))],
    )
    asked: list[list[str]] = []

    def remembering(args: list[str]) -> str:
        asked.append(args)
        if "merge-base" in args:
            return "деадбиф\n"
        if "show" in args:
            return "Разобрано: abc1234\n"
        return "починка без отметок"

    monkeypatch.setattr(journal_gate.journal, "git", remembering)
    assert journal_gate.travelled("origin/main") == []
    shown = [args for args in asked if "show" in args]
    assert shown, "содержимое у основания не спрашивалось вовсе"
    assert all(args[2].startswith("деадбиф:") for args in shown), (
        f"содержимое взято не у общего предка, а у движущейся вершины: {shown}"
    )


def test_the_resolution_parse_is_the_same_one_the_change_body_uses() -> None:
    """Строку снятия разбирает ОДИН разбор, и он общий с телом изменения.

    Здесь жил свой: строка находилась образцом, а отпечатки выбирались по ВСЕЙ
    строке — включая текст причины. Ровно этот дефект `changerefs` уже чинил у
    себя, разведя отпечатки и причину, и второй разбор повторял его заново.

    ЗАМЕР 17.09.2026: по 660 строкам «Разобрано» в журнале и последних 400 телах
    коммитов два разбора совпали на ВСЕХ — дефект был скрытым, а не сработавшим.
    Предъявляется он одной строкой, и она здесь.
    """
    said = "Разобрано: abc1234 — премиса опровергнута заходом deadbee, чинить нечего"
    assert journal_gate.marks_of(said) == {"abc1234"}, (
        "отпечаток взят из ТЕКСТА ПРИЧИНЫ — значит разбор снова свой, а не общий"
    )
    assert journal_gate.marks_of(said) == set(changerefs.resolved_in(said)), (
        "разбор гейта разошёлся с разбором тела изменения"
    )


def test_the_ancestor_is_asked_exactly_once_per_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """За весь заход гейта `git merge-base` зовётся ОДИН раз, и это считается.

    Прежде точку брали ТРИЖДЫ: дважды внутри `changed_files` и ещё раз внутри
    `travelled`. Заявление «спрашивается однажды» было сделано, когда убрали
    один из трёх, — то есть оказалось шире починки (нашёл внешний взгляд на
    #451, и назвал дважды).

    Цена трёх вопросов не в трёх вызовах git: общая ветка движется, пока
    изменение открыто, и три читателя ОДНОГО захода могут получить разные
    точки — список путей от одной, выжившие от другой, содержимое от третьей.

    СЧИТАЕТСЯ ВЫЗОВ, А НЕ ЧИТАЕТСЯ КОД. Обещание «один раз» проверяемо только
    счётом: правка, добавляющая четвёртого читателя, в глазах не отличается от
    правки, которая его не добавляет (139).
    """
    journal_dir = tmp_path / "changelog.d"
    journal_dir.mkdir()
    (journal_dir / "правка.fixed.md").write_text("### Правка\n\n#243\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    asked: list[list[str]] = []

    def remembering(args: list[str]) -> str:
        asked.append(args)
        if "merge-base" in args:
            return "деадбиф\n"
        if "show" in args:
            raise journal_gate.NotRun(NO_SUCH_PATH_SAYS)
        if "diff" in args:
            return "changelog.d/правка.fixed.md\0scripts/что-то.py\0"
        return "починка без отметок"

    monkeypatch.setattr(journal_gate.journal, "git", remembering)
    journal_gate.main(["--base", "origin/main"])
    merge_bases = [args for args in asked if "merge-base" in args]
    assert len(merge_bases) == 1, (
        f"общий предок спрошен {len(merge_bases)} раз(а) за заход: {merge_bases}"
    )


# --- шапка `internal` против состава изменения (#1010, 215) ------------------

HEADER = "> **Потребителю безразлично:** правится `scripts/x.py` и `docs/decisions/037`; ничего\n"


def test_header_paths_are_names_that_look_like_paths() -> None:
    """Путь — с косой чертой или расширением; «`internal`» путём не является."""
    text = "> **Потребителю безразлично:** `internal`, `a/b.py`, `c.json`, `requires-python`.\n"
    assert check.header_paths(text) == ["a/b.py", "c.json"]


def test_only_the_first_line_is_the_header() -> None:
    """Пути ниже шапки — проза фрагмента, а не пересказ состава."""
    assert check.header_paths("> шапка без путей\n\n`scripts/x.py` в теле\n") == []


@pytest.mark.parametrize(
    ("files", "stray"),
    [
        (["scripts/x.py", "docs/decisions/037-a-kind.md"], []),
        (["scripts/x.py"], ["docs/decisions/037"]),
        (["docs/decisions/037-a-kind.md"], ["scripts/x.py"]),
    ],
    ids=["всё-тронуто", "решение-не-тронуто", "скрипт-не-тронут"],
)
def test_a_header_path_outside_the_change_is_stray(files: list[str], stray: list[str]) -> None:
    """Обе половины: тронутое (в том числе по началу имени) не названо, чужое — названо."""
    assert check.stray_in_header(HEADER, files) == stray


def test_a_directory_in_the_header_covers_its_files() -> None:
    """`.rules/` в шапке покрывает тронутый `.rules/bindings.json`."""
    assert check.stray_in_header("> `.rules/` правится\n", [".rules/bindings.json"]) == []


def test_an_unnamed_mechanism_is_named_back() -> None:
    """Тронутый механизм `scripts/`, не названный шапкой, называется; названный — нет."""
    files = ["scripts/x.py", "scripts/y.py", "tests/test_y.py"]
    assert check.unnamed_mechanisms(HEADER, files) == ["scripts/y.py"]
    assert check.unnamed_mechanisms("> правится `y` и x.py\n", files) == []


def test_a_stray_header_rejects_the_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Шапка с путём вне изменения — отказ шага журнала, и путь назван."""
    fragment = "changelog.d/a-note.internal.md"
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / fragment).write_text(HEADER + "\n### Заголовок\n\nтекст\n\n#1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check.journal, "common_ancestor", lambda _base: "предок")
    monkeypatch.setattr(check.journal, "changed_files", lambda *_, **__: [fragment, "scripts/x.py"])
    monkeypatch.setattr(check, "travelled", lambda *_: [])
    assert check.main(["--base", "origin/main"]) == check.EXIT_REJECTED
    assert "docs/decisions/037" in capsys.readouterr().err


def test_an_unnamed_mechanism_is_a_warning_not_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Тронутый, но не названный механизм — предупреждение, и исход чистый (051)."""
    fragment = "changelog.d/a-note.internal.md"
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / fragment).write_text(
        "> **Потребителю безразлично:** поправлена докстрока\n\n### З\n\nт\n\n#1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check.journal, "common_ancestor", lambda _base: "предок")
    monkeypatch.setattr(check.journal, "changed_files", lambda *_, **__: [fragment, "scripts/y.py"])
    monkeypatch.setattr(check, "travelled", lambda *_: [])
    assert check.main(["--base", "origin/main"]) == check.EXIT_OK
    out = capsys.readouterr().out
    assert "предупреждение" in out and "scripts/y.py" in out, out


def test_a_wrapped_header_is_read_whole() -> None:
    """Шапка, перенесённая на строки `> …`, читается целиком (взгляд на #1111)."""
    text = "> **Потребителю безразлично:** правится\n> `scripts/x.py`.\n\n### З\n\n`scripts/y.py`\n"
    assert check.header_paths(text) == ["scripts/x.py"]
    assert check.unnamed_mechanisms(text, ["scripts/x.py"]) == []


def test_a_path_under_a_negation_is_not_a_claim() -> None:
    """«Ни `.pipeline.yml` не тронут» — не пересказ правки; соседняя часть — пересказ."""
    text = (
        "> **Потребителю безразлично:** правится `scripts/x.py` — "
        "ни форма `.pipeline.yml`, ни имена не тронуты.\n"
    )
    assert check.header_paths(text) == ["scripts/x.py"]
    assert check.stray_in_header(text, ["scripts/x.py"]) == []


@pytest.mark.parametrize(
    ("name", "files", "seen"),
    [
        ("scripts/review", ["scripts/review_map.py"], False),
        ("scripts/review", ["scripts/review.py"], True),
        ("docs/decisions/037", ["docs/decisions/037-a-kind.md"], True),
        ("docs/decisions/03", ["docs/decisions/037-a-kind.md"], False),
        (".rules/", [".rules/bindings.json"], True),
    ],
    ids=["чужой-хвост", "расширение", "номер-решения", "часть-номера", "каталог"],
)
def test_a_name_prefix_counts_only_at_a_boundary(name: str, files: list[str], seen: bool) -> None:
    """Начало имени засчитывается на границе «-», «.», «/» — не внутри имени (взгляд на #1111)."""
    assert check.covered(name, files) is seen


def test_measure_counts_internal_fragments_by_their_own_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Замер судит каждый фрагмент составом коммита, который его завёл."""
    fragment = "changelog.d/a.internal.md"
    answers = {
        ("log",): "aaa\n",
        ("show", "-z", "--name-only", "--format="): f"\n{fragment}\0scripts/z.py\0",
        ("show", "-z", "--name-only", "--diff-filter=A"): f"\n{fragment}\0",
        ("show", "aaa:"): "> **Потребителю безразлично:** правится `docs/x.md`\n",
    }

    def output(args: list[str], *_: object, **__: object) -> str:
        for prefix, said in answers.items():
            if tuple(args[: len(prefix)]) == prefix or (
                prefix[0] == "show" and len(prefix) == 2 and args[1].startswith(prefix[1])
            ):
                return said
        raise AssertionError(args)

    monkeypatch.setattr(check.gitcall, "output", output)
    assert check.measure("HEAD") == (1, 1, 1)


def test_every_unreleased_fragment_keeps_the_shape() -> None:
    """Форма нового фрагмента держится на всей папке, а не только на тронутом (#1172, 195).

    Фрагмент, приехавший слиянием, гейт изменения не видел бы. Выпущенное в
    `released/` не судится: оно источник, и правка задним числом запрещена.
    """
    off = {
        one.slug: why for one in module.parse_fragments(files()) if (why := module.shape_fault(one))
    }
    assert not off, f"невыпущенные фрагменты не той формы: {off}"


@pytest.mark.parametrize(
    ("body", "fault"),
    [
        ("### Заголовок\n\nОдна строка о сути.\n\n#1", ""),
        ("### Заголовок\n\n" + "строка\n" * 10 + "\n#1", ""),
        ("### Заголовок\n\n" + "строка\n" * 11 + "\n#1", "тело 11 строк"),
        ("## Заголовок\n\nСтрока.\n\n#1", "заголовок выше"),
        ("### Заголовок\n\nСтрока.\n\n# Раздел\n\n#1", "заголовок выше"),
        ("### Заголовок\n\n#### Подраздел\n\nСтрока.\n\n#1 #2", ""),
    ],
    ids=["короткий", "ровно предел", "сверх предела", "уровень версии", "уровень h1", "ниже ###"],
)
def test_the_shape_fault_is_named(body: str, fault: str) -> None:
    """Обе половины: длина и уровень заголовка названы; годный фрагмент чист."""
    said = module.shape_fault(module.Fragment("fixed", "проба", body))
    assert (fault in said) if fault else said == "", said


def test_the_change_gate_refuses_a_long_fragment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Гейт изменения отвергает длинный фрагмент; выпуск того же не требует (#1172)."""
    folder = tmp_path / "changelog.d"
    folder.mkdir()
    (folder / "длинный.fixed.md").write_text(
        "### Заголовок\n\n" + "строка\n" * 11 + "\n#1\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "FRAGMENTS", Path("changelog.d"))
    with pytest.raises(module.NotRun, match="не той формы"):
        module.fragments_of(["changelog.d/длинный.fixed.md"])
    assert module.read_fragments(folder), "выпуск отверг то, что формой не судит"
