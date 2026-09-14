"""Срок жизни окна проверяется тем, что гейт обязан отвергнуть.

Гейт, который меряет величину и никогда её не называет, зелен всегда и не держит
ничего. Поэтому здесь прогоняется каждый объявленный исход — включая третий, «не
отработал»
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md),
[145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).

ОТДЕЛЬНО ПРОВЕРЯЕТСЯ ТО, ЧЕМ ЗАМЕР ОШИБСЯ. Ответ по правилу 006 держался на
утверждении «величины, растущей вместе с окном, в дереве нет». Здесь она
считается на подготовленном дереве — то есть премиса проверена прогоном, а не
принята на веру
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import load_script

module = load_script("check_window_lifetime.py")
window = load_script("window.py")

BROKEN: Final = 2
REJECTED: Final = 1
CLEAN: Final = 0

#: Начало отсчёта в подготовленном дереве. Дата заведомо своя: гейт считает
#: РАЗНОСТЬ, и привязка к «сегодня» сделала бы тест зависимым от дня прогона.
START: Final = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)

WINDOW_A: Final = "session_AAA"
WINDOW_B: Final = "session_BBB"

COAUTHOR: Final = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"


def git(
    cwd: Path, *args: str, when: datetime | None = None, committed: datetime | None = None
) -> None:
    """Зовёт git в подготовленном дереве, при нужде подставляя даты."""
    env = dict(os.environ)
    if when is not None:
        env["GIT_AUTHOR_DATE"] = when.isoformat()
        env["GIT_COMMITTER_DATE"] = (committed or when).isoformat()
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def tail(session: str | None, *, by_window: bool = True) -> str:
    """Хвостовой блок трейлеров: соавторство и адрес окна (156)."""
    lines = []
    if by_window:
        lines.append(COAUTHOR)
    if session:
        lines.append(
            f"Claude-Session: https://claude.ai/code/session_{session.removeprefix('session_')}"
        )
    return ("\n\n" + "\n".join(lines)) if lines else ""


def commit(
    root: Path,
    subject: str,
    *,
    day: float,
    session: str | None = WINDOW_A,
    by_window: bool = True,
    committed_day: float | None = None,
) -> None:
    """Один коммит на указанный день от начала отсчёта."""
    when = START + timedelta(days=day)
    committed = START + timedelta(days=committed_day) if committed_day is not None else None
    (root / "file.txt").write_text(subject, encoding="utf-8")
    git(root, "add", "file.txt")
    git(
        root,
        "commit",
        "-m",
        subject + tail(session, by_window=by_window),
        when=when,
        committed=committed,
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Дерево с общей веткой `main`, на которую окно уже отметилось."""
    root = tmp_path / "tree"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Artem Markitanov")
    git(root, "config", "user.email", "86671904+ArtVsMark@users.noreply.github.com")
    commit(root, "первая работа окна", day=0)
    return root


def run(root: Path, *args: str) -> int:
    """Заход гейта по подготовленному дереву."""
    code: int = module.main(["--root", str(root), "--base", "main", "--history", "main", *args])
    return code


def test_a_window_inside_the_term_is_clean(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Окно моложе предела — чистый исход, и срок при этом НАЗВАН.

    Молчаливое зелёное здесь ничем не отличалось бы от невыполненной проверки.
    """
    git(tree, "checkout", "-b", "work")
    commit(tree, "работа на третий день", day=2)
    assert run(tree, "--head", "work") == CLEAN
    said = capsys.readouterr().out
    assert "2 сут 0 ч" in said, f"срок не назван: {said}"


def test_a_window_over_the_term_is_named(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Окно старше пяти суток гейт называет — это и есть то, что он держит."""
    git(tree, "checkout", "-b", "work")
    commit(tree, "работа на седьмой день", day=6)
    assert run(tree, "--head", "work") == REJECTED
    said = capsys.readouterr().out
    assert "ПЕРЕЖИЛО" in said and "6 сут" in said, f"превышение не названо: {said}"


def test_the_term_is_measured_from_the_history_not_the_branch(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Начало окна ищется в ИСТОРИИ, а не в ветке изменения.

    По ветке виден лишь кусок работы окна: считай начало по ней — и окно,
    живущее неделю, выглядело бы однодневным на каждой новой ветке. Это ровно
    та ошибка, из-за которой величину сочли неизмеримой.
    """
    git(tree, "checkout", "-b", "work")
    commit(tree, "работа на седьмой день", day=6)
    assert run(tree, "--head", "work") == REJECTED, "срок сочтён по ветке, а не по истории"
    assert "6 сут" in capsys.readouterr().out


def test_the_author_date_is_used_not_the_committer_one(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Дата берётся авторская: коммитерскую переписывают уплотнение и перенос.

    Иначе срок считался бы от дня слияния — то есть мерил бы очередь, а не окно.
    """
    git(tree, "checkout", "-b", "work")
    # Написано на седьмой день, уплотнено в тот же день, что и начало.
    commit(tree, "работа на седьмой день", day=6, committed_day=0)
    assert run(tree, "--head", "work") == REJECTED, "срок посчитан по коммитерской дате"
    assert "6 сут" in capsys.readouterr().out


def test_a_change_without_a_window_has_no_subject(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Изменение без соавтора-окна правилу 006 не подчиняется.

    Это ЧИСТЫЙ исход, а не третий: у руки человека срока жизни сессии нет, и
    требовать след от неё значило бы краснеть на законном отсутствии предмета.
    """
    git(tree, "checkout", "-b", "work")
    commit(tree, "правка руками", day=6, session=None, by_window=False)
    assert run(tree, "--head", "work") == CLEAN
    assert "предмета нет" in capsys.readouterr().out


def test_a_window_without_a_trail_does_not_go_green(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Окно подписалось, а трейлера сессии нет — третий исход, не «чисто».

    Именно этим трейлер и становится обязательным: `attribution` требует
    соавторства и про сессию не знает, а зеленеть на нехватке входа значит
    выводить ответ из незнания (045).
    """
    git(tree, "checkout", "-b", "work")
    commit(tree, "окно без следа", day=6, session=None)
    assert run(tree, "--head", "work") == BROKEN
    assert "Claude-Session" in capsys.readouterr().err


def test_an_empty_range_is_not_clean(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Предмета не нашлось — гейт падает, а не зеленеет (075)."""
    git(tree, "checkout", "-b", "work")
    assert run(tree, "--head", "work") == BROKEN
    assert "предмета проверки не нашлось" in capsys.readouterr().err


def test_two_windows_on_one_change_are_both_measured(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Изменение, которое вели два окна, мерится по каждому.

    Взять одно значило бы прятать второе: работу продолжает то окно, что
    подписалось позже, а срок пережить может любое.
    """
    git(tree, "checkout", "-b", "work")
    commit(tree, "продолжило другое окно", day=1, session=WINDOW_B)
    commit(tree, "и снова первое", day=6, session=WINDOW_A)
    assert run(tree, "--head", "work") == REJECTED
    said = capsys.readouterr().out
    assert WINDOW_A in said and WINDOW_B in said, f"названо не каждое окно: {said}"


def test_a_cut_history_is_not_a_young_window(
    tmp_path: Path, tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """В обрезанной истории начало окна не видно — и это третий исход.

    Прочитать обрезку как «окно молодое» значило бы зеленеть тем охотнее, чем
    меньше механизм знает. Пробел назвал внешний взгляд находкой `51a6454`.
    """
    commit(tree, "вторая работа окна", day=1)
    commit(tree, "третья работа окна", day=6)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth", "1", f"file://{tree}", str(shallow)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    git(shallow, "config", "user.name", "Artem Markitanov")
    git(shallow, "config", "user.email", "86671904+ArtVsMark@users.noreply.github.com")
    git(shallow, "checkout", "-b", "work")
    commit(shallow, "работа в мелком клоне", day=7)
    assert run(shallow, "--head", "work") == BROKEN
    assert "история обрезана" in capsys.readouterr().err


def test_the_limit_comes_from_the_rule_not_from_a_series(tree: Path) -> None:
    """Предел объявлен правилом 006, а не выведен из ряда замеров.

    Вывести его из трёх окон значило бы назначить порог по одной точке — ровно
    то, от чего проект отказался у покрытия (050).
    """
    assert window.LIMIT_DAYS == 5, "предел разошёлся с правилом 006 «три–пять дней»"
    assert window.WARN_DAYS == 3, "нижняя граница срока разошлась с правилом 006"
    assert window.WARN_DAYS < window.LIMIT_DAYS, "предупреждение не раньше предела"


def test_the_trailer_pattern_is_shared_with_the_hail(tree: Path) -> None:
    """Образец трейлера один на всех, кто его читает (090).

    Второй образец того же разошёлся бы с первым молча: правка формата в одном
    месте из двух выглядит полной.
    """
    hail = load_script("hail.py")
    assert hail.SESSION_RE is window.SESSION_RE, "у оклика свой образец трейлера — копия разойдётся"


# --- разбор следа окна: модуль прогоняется прямо ------------------------------
#
# Гейт выше проверяется через свою точку входа, и этого мало: общий модуль читает
# ещё и оклик, а значит у него свои потребители и свои границы. Прогон через
# одного потребителя оставил бы их непроверенными (145).


def test_a_commit_reads_its_window_from_the_tail() -> None:
    """Коммит называет своё окно по хвостовому блоку, а не по телу (156)."""
    one = window.Commit(
        sha="abc1234",
        when=START,
        message=f"тема\n\n{COAUTHOR}\nClaude-Session: https://claude.ai/code/{WINDOW_A}",
    )
    assert one.session == WINDOW_A
    assert window.made_by_window(one.message), "соавтор-окно не опознан"


def test_a_commit_without_a_window_names_neither() -> None:
    """Ни окна, ни следа — и оба ответа отрицательные, а не пустые догадки."""
    one = window.Commit(sha="abc1234", when=START, message="правка руками")
    assert one.session is None
    assert not window.made_by_window(one.message)


def test_the_coauthor_is_matched_by_mail_not_by_name() -> None:
    """Сверяется почта: имя подставляет окружение, и оно меняется.

    Тот же выбор, что в `.github/authors.txt`, и по той же причине.
    """
    said = f"тема\n\nCo-Authored-By: Иное Имя <{window.WINDOW_MAIL}>"
    assert window.made_by_window(said), "окно не опознано из-за написания имени"
    assert not window.made_by_window("тема\n\nCo-Authored-By: Claude Opus 5 <someone@else>")


def test_a_lifetime_names_the_limit_it_crossed() -> None:
    """Срок за пределом и срок у предела — разные состояния, и оба названы."""
    first = window.Commit(sha="a", when=START, message="раз")
    over = window.Lifetime(
        session=WINDOW_A,
        first=first,
        last=window.Commit(sha="b", when=START + timedelta(days=6), message="два"),
        whole=True,
    )
    near = window.Lifetime(
        session=WINDOW_A,
        first=first,
        last=window.Commit(sha="c", when=START + timedelta(days=4), message="три"),
        whole=True,
    )
    assert over.over_limit and not over.near_limit
    assert near.near_limit and not near.over_limit
    assert window.said_age(over.age) == "6 сут 0 ч", "срок сказан не сутками и часами"


def test_the_history_is_read_oldest_first(tree: Path) -> None:
    """Коммиты читаются от старых к новым: по первому и находят начало окна."""
    commit(tree, "вторая работа окна", day=1)
    found = window.commits("main", cwd=str(tree))
    assert [one.when.day for one in found] == [1, 2], "порядок чтения истории обратный"
    assert all(one.session == WINDOW_A for one in found)


def test_a_whole_history_is_not_called_cut(tree: Path) -> None:
    """Полная история обрезанной не считается — иначе гейт не зеленел бы никогда."""
    assert not window.is_shallow(cwd=str(tree))


def test_a_first_appearance_starts_the_window(tree: Path) -> None:
    """Окна ещё нет в истории — срок нулевой, и это законное состояние.

    Первая работа окна не должна выглядеть ни обрезкой, ни превышением.
    """
    head = window.Commit(sha="new", when=START + timedelta(days=2), message="первая работа")
    age = window.lifetime(WINDOW_B, "main", head, cwd=str(tree))
    assert age.age == timedelta(0)
    assert age.whole and not age.over_limit


def test_an_unknown_revision_is_not_run(tree: Path) -> None:
    """Спросили несуществующее — третий исход, а не пустая история (045)."""
    with pytest.raises(window.NotRun):
        window.commits("несуществующая-ветка", cwd=str(tree))
