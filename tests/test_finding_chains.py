"""Замер цепочек находок: число — команда, а не память окна (#746)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("finding_chains.py")


def said(*pairs: tuple[int, str]) -> list[tuple[int, str]]:
    """Пары «изменение, заголовок находки» — как их отдаёт чтение лент."""
    return list(pairs)


def test_a_place_is_the_path_before_the_colon() -> None:
    """Место — путь до двоеточия; находка без пути места не получает."""
    assert module.place_of("tests/outcomes.py:186-188 — граница") == "tests/outcomes.py"
    assert module.place_of("`scripts/x.py`:12 — что-то") == "scripts/x.py"
    assert module.place_of("проза без адреса") == ""


def test_places_are_counted_by_changes_and_a_repeat_within_one_change_once() -> None:
    """Место считается по изменениям; повтор на ТОМ ЖЕ изменении — один раз."""
    measured = module.chains(
        said(
            (1, "a.py:1 — первая"),
            (2, "a.py:2 — вторая"),
            (2, "a.py:2 — вторая"),
            (3, "a.py:3 — третья"),
            (3, "b.py:1 — другое место"),
            (4, "без места"),
            (4, "без места"),
        )
    )
    assert measured.findings == 5
    assert measured.changes == 4, "повтор на том же изменении засчитан дважды"
    assert measured.unplaced == 1
    assert measured.places == {"a.py": [1, 2, 3], "b.py": [3]}
    assert measured.reached(3) == ["a.py"]
    assert measured.reached(2) == ["a.py"]
    assert module.Chains(findings=0, changes=0, unplaced=0).reached(1) == []
    lines = module.report(measured)
    assert "  a.py: #1, #2, #3" in lines


def test_a_finding_retold_on_another_change_is_a_new_link() -> None:
    """Та же находка на другом изменении — звено цепочки, а не повтор.

    Ленты читаются от новых к старым: снятие поперёк изменений засчитало бы
    находку новейшему и потеряло изменение, где она родилась (#764).
    """
    measured = module.chains(
        said((9, "a.py:1 — та же"), (8, "a.py:1 — та же"), (7, "a.py:1 — та же"))
    )
    assert measured.places == {"a.py": [7, 8, 9]}, "звено цепочки снято как повтор"
    assert measured.findings == 1, "уникальная находка посчитана по изменениям"
    assert measured.changes == 3
    unplaced = module.chains(said((2, "без места"), (1, "без места")))
    assert unplaced.unplaced == 1, "находка без места посчитана по изменениям, а не по отпечатку"


@pytest.mark.parametrize(
    ("title", "place"),
    [
        ("scripts/x.py:12 — с расширением", "scripts/x.py"),
        ("Makefile:3 — без расширения", "Makefile"),
        (".github/CODEOWNERS:1 — без расширения в каталоге", ".github/CODEOWNERS"),
        (".gitignore:3 — точка в начале", ".gitignore"),
        ("`.rules/bindings.json`:40 — в обратных кавычках", ".rules/bindings.json"),
        ("Вердикт:1 — кириллица это проза", ""),
        ("путь без номера: строки нет", ""),
    ],
)
def test_every_form_of_a_place_is_read(title: str, place: str) -> None:
    """Формы пути перечислены разом (195), а не по одной на заход."""
    assert module.place_of(title) == place


def platform(monkeypatch: pytest.MonkeyPatch, comments: dict[int, list[dict[str, Any]]]) -> None:
    """Площадка с закрытыми изменениями и их лентами."""

    def paginate(path: str, *_rest: Any, **_kw: Any) -> Any:
        if path.startswith("repos/o/r/pulls"):
            return iter({"number": number} for number in sorted(comments, reverse=True))
        number = int(path.split("/")[-2])
        return iter(comments[number])

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")


def look(*titles: str) -> dict[str, Any]:
    """Комментарий взгляда с находками и вердиктом."""
    lines = "\n".join(f"НАХОДКА[риск]: {title}" for title in titles)
    return {"user": {"type": "Bot"}, "body": f"{lines}\n\nВЕРДИКТ: находок {len(titles)}"}


def test_the_measurement_reads_the_change_feeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Замер читает ленты изменений тем же разбором, что сборщик реестра."""
    platform(
        monkeypatch,
        {
            7: [look("a.py:1 — раз")],
            8: [look("a.py:2 — два")],
            9: [look("a.py:3 — три", "b.py:1 — иное")],
        },
    )
    assert module.main(["--repo", "o/r", "--last", "10"]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert "уникальных находок: 4 на 3 изменениях" in out
    assert "  a.py: #7, #8, #9" in out


def test_without_a_token_the_measurement_is_not_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет токена — замер не снят, а не «находок ноль» (045)."""
    platform(monkeypatch, {7: [look("a.py:1 — раз")]})
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN


def test_a_silent_platform_is_not_an_empty_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — второй исход, а не пустой замер."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("503")

    monkeypatch.setattr(module.ghrest, "paginate", refuse)
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN


def test_a_range_repeats_the_same_numbers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отрезок `--from/--to` читает ровно свои изменения, а не последние N."""
    platform(
        monkeypatch,
        {
            10: [look("z.py:1 — за верхней границей")],
            9: [look("a.py:1 — раз")],
            8: [look("a.py:2 — два")],
            7: [look("y.py:1 — за нижней границей")],
        },
    )
    assert module.main(["--repo", "o/r", "--from", "8", "--to", "9"]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert "уникальных находок: 2 на 2 изменениях" in out, out


@pytest.mark.parametrize(
    "bounds",
    [["--to", "9"], ["--from", "8"], ["--from", "9", "--to", "8"]],
    ids=["только верхняя", "только нижняя", "перевёрнутый отрезок"],
)
def test_a_range_needs_both_bounds_in_order(
    monkeypatch: pytest.MonkeyPatch, bounds: list[str]
) -> None:
    """Одна граница без другой читала бы всю историю молча — это отказ (взгляд на #769)."""
    platform(monkeypatch, {9: [look("a.py:1 — раз")], 8: [look("a.py:2 — два")]})
    assert module.main(["--repo", "o/r", *bounds]) == module.EXIT_BROKEN


def test_an_empty_range_is_not_a_zero_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отрезок без изменений — отказ, а не нулевой замер (045)."""
    platform(monkeypatch, {9: [look("a.py:1 — раз")]})
    assert module.main(["--repo", "o/r", "--from", "100", "--to", "200"]) == module.EXIT_BROKEN


def test_a_moment_repeats_the_numbers_after_a_late_look(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--at` отсекает находки, дописанные поздним взглядом после замера."""
    early = {**look("a.py:1 — раз"), "created_at": "2026-09-24T10:00:00Z"}
    late = {**look("b.py:1 — дописано позже"), "created_at": "2026-09-24T20:00:00Z"}
    platform(monkeypatch, {9: [early, late]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2026-09-24T19:00:00Z"]
    assert module.main(args) == module.EXIT_OK
    assert "уникальных находок: 1 на 1 изменениях" in capsys.readouterr().out


def test_reading_counts_the_changes_it_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """`read_counted` отдаёт и находки, и число прочитанных изменений — по нему пустое отличимо."""
    platform(monkeypatch, {9: [look("a.py:1 — раз")], 8: [look("a.py:2 — два")]})
    said, seen, kept = module.read_counted("o/r", "t", 10, 8, 9)
    assert seen == 2 and len(said) == 2
    assert kept == 2
    assert module.read_counted("o/r", "t", 10, 100, 200) == ([], 0, 0)


@pytest.mark.parametrize(
    "said", ["2026-09-24", "2026-09-24T19:00:00", "вчера"], ids=["дата", "без пояса", "не ISO"]
)
def test_a_moment_without_time_and_zone_is_refused(
    monkeypatch: pytest.MonkeyPatch, said: str
) -> None:
    """`--at` без времени или пояса резал бы не там и молча — это отказ (взгляд на #781)."""
    platform(monkeypatch, {9: [look("a.py:1 — раз")]})
    assert (
        module.main(["--repo", "o/r", "--from", "9", "--to", "9", "--at", said])
        == module.EXIT_BROKEN
    )


def test_a_moment_with_an_offset_is_the_same_instant() -> None:
    """Смещение пояса — тот же момент, а не сдвиг на смещение."""
    assert module.moment("2026-09-24T22:00:00+03:00") == module.moment("2026-09-24T19:00:00Z")


def test_findings_written_by_an_edit_after_the_moment_are_not_counted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Находки дописаны правкой после `--at` — их нет в замере на `--at` (взгляд на #781)."""
    kept = {
        **look("a.py:1 — раз"),
        "created_at": "2026-09-24T10:00:00Z",
        "updated_at": "2026-09-24T10:05:00Z",
    }
    late = {
        **look("b.py:1 — дописано правкой"),
        "created_at": "2026-09-24T18:00:00Z",
        "updated_at": "2026-09-24T20:00:00Z",
    }
    platform(monkeypatch, {9: [kept, late]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2026-09-24T19:00:00Z"]
    assert module.main(args) == module.EXIT_OK
    assert "уникальных находок: 1 на 1 изменениях" in capsys.readouterr().out


def test_a_moment_before_every_finding_is_not_a_zero_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Момент раньше всех лент — пустой замер, а значит отказ (045, 195)."""
    platform(monkeypatch, {9: [{**look("a.py:1 — раз"), "created_at": "2026-09-24T10:00:00Z"}]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2020-01-01T00:00:00Z"]
    assert module.main(args) == module.EXIT_BROKEN


def test_said_at_is_the_last_edit_and_falls_back_to_creation() -> None:
    """`said_at` — время правки; нет правки — время создания."""
    edited = {"created_at": "2026-09-24T10:00:00Z", "updated_at": "2026-09-24T11:00:00Z"}
    assert module.said_at(edited) == module.moment("2026-09-24T11:00:00Z")
    assert module.said_at({"created_at": "2026-09-24T10:00:00Z"}) == module.moment(
        "2026-09-24T10:00:00Z"
    )


def test_a_moment_over_honest_empty_feeds_is_a_zero_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ленты прочитаны до момента, находок в них нет — это ноль, а не отказ (взгляд на #781)."""
    quiet = {
        "user": {"type": "Bot"},
        "body": "ВЕРДИКТ: находок 0",
        "created_at": "2026-09-24T10:00:00Z",
    }
    platform(monkeypatch, {9: [quiet]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2026-09-24T19:00:00Z"]
    assert module.main(args) == module.EXIT_OK
    assert "уникальных находок: 0" in capsys.readouterr().out


def test_a_comment_without_time_is_a_named_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Меток времени нет — отказ с причиной, а не трейсбек разбора (взгляд на #781)."""
    platform(monkeypatch, {9: [look("a.py:1 — раз")]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2026-09-24T19:00:00Z"]
    assert module.main(args) == module.EXIT_BROKEN


def test_a_human_remark_before_the_moment_does_not_count_as_a_read_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """До `--at` только реплика человека, взгляд сказал позже — это пустое отсечение (#787)."""
    remark = {
        "user": {"type": "User"},
        "body": "@claude посмотри",
        "created_at": "2026-09-24T10:00:00Z",
    }
    verdict = {**look("a.py:1 — раз"), "created_at": "2026-09-24T20:00:00Z"}
    platform(monkeypatch, {9: [remark, verdict]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2026-09-24T19:00:00Z"]
    assert module.main(args) == module.EXIT_BROKEN


def test_an_unparsable_time_is_undated_not_any_value_error() -> None:
    """Неразборная метка — `Undated`; прочие ошибки разбора не выдаются за «замер не снят»."""
    with pytest.raises(module.Undated):
        module.said_at({"updated_at": "вчера"})
    with pytest.raises(module.Undated):
        module.said_at({})


def test_findings_before_the_moment_count_even_if_the_verdict_came_later(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Находки сказаны до `--at`, вердикт — отдельной записью после: это счёт, а не отказ.

    Ответ взгляда бывает двумя записями (`review_findings.last_look`): находки
    пишет комментарий действия, число — механизм. Отказ по одному `kept`
    выдавал прочитанные находки за пустоту (взгляд на #787, 195).
    """
    lines = {
        "user": {"type": "Bot"},
        "body": "НАХОДКА[риск]: a.py:1 — раз",
        "created_at": "2026-09-24T10:00:00Z",
    }
    verdict = {
        "user": {"type": "Bot"},
        "body": "ВЕРДИКТ: находок 1",
        "created_at": "2026-09-24T20:00:00Z",
    }
    platform(monkeypatch, {9: [lines, verdict]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2026-09-24T19:00:00Z"]
    assert module.main(args) == module.EXIT_OK
    assert "уникальных находок: 1" in capsys.readouterr().out


def test_a_human_finding_line_before_the_moment_is_not_a_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строка `НАХОДКА[…]` в реплике человека до `--at` отказ не снимает (взгляд на #789)."""
    quoted = {
        "user": {"type": "User"},
        "body": "НАХОДКА[риск]: a.py:1 — процитировано человеком",
        "created_at": "2026-09-24T10:00:00Z",
    }
    verdict = {**look("a.py:1 — раз"), "created_at": "2026-09-24T20:00:00Z"}
    platform(monkeypatch, {9: [quoted, verdict]})
    args = ["--repo", "o/r", "--from", "9", "--to", "9", "--at", "2026-09-24T19:00:00Z"]
    assert module.main(args) == module.EXIT_BROKEN
