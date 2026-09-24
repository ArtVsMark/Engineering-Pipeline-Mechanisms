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
