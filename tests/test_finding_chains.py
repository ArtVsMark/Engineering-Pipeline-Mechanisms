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


def test_places_are_counted_by_changes_and_retold_findings_once() -> None:
    """Место считается по изменениям; пересказ той же находки — один раз."""
    measured = module.chains(
        said(
            (1, "a.py:1 — первая"),
            (2, "a.py:2 — вторая"),
            (2, "a.py:2 — вторая"),
            (3, "a.py:3 — третья"),
            (3, "b.py:1 — другое место"),
            (4, "без места"),
            (5, "без места"),
        )
    )
    assert measured.findings == 5
    assert measured.changes == 4, "пересказ находки на другом изменении засчитан дважды"
    assert measured.unplaced == 1
    assert measured.places == {"a.py": [1, 2, 3], "b.py": [3]}
    assert measured.reached(3) == ["a.py"]
    assert measured.reached(2) == ["a.py"]
    assert module.Chains(findings=0, changes=0, unplaced=0).reached(1) == []
    lines = module.report(measured)
    assert "  a.py: #1, #2, #3" in lines


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
