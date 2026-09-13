"""Ссылка на правило каталога ведёт туда, куда обещает.

Ссылками на правила проект обосновывает решения: почти каждый механизм называет
правило, из которого вырос. Битая ссылка обесценивает довод дважды — читатель
не может ни проверить его, ни отличить «правила нет» от «адрес переврали».

Замер 10.09.2026: битых ссылок в дереве оказалось 29 из 300. Номер везде был
верным, а имя файла писалось по памяти, близко к смыслу.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("check_rule_links.py")


def test_a_wrong_name_at_a_right_number_is_found() -> None:
    """Номер верный, имя выдумано — это находка.

    Ровно так выглядели все 29: `046-a-red-must-name-its-cause.md` вместо
    `046-name-the-gaps-do-not-level-them.md`. Площадка отдаёт по такой ссылке
    404, и ни один прогон об этом не говорил.
    """
    found = [(Path("a.py"), 7, "046", "a-red-must-name-its-cause")]
    problems = module.broken(found, {"046": "name-the-gaps-do-not-level-them"})
    assert len(problems) == 1
    assert "046" in problems[0] and "a.py:7" in problems[0]


def test_a_missing_number_is_told_apart_from_a_wrong_name() -> None:
    """«Правила нет» и «адрес переврали» — разные находки и разные починки (154)."""
    found = [(Path("a.py"), 1, "999", "made-up")]
    problems = module.broken(found, {"046": "name-the-gaps-do-not-level-them"})
    assert "в каталоге нет" in problems[0]


def test_a_correct_link_is_not_a_finding() -> None:
    """Совпало — молчим."""
    found = [(Path("a.py"), 1, "046", "name-the-gaps-do-not-level-them")]
    assert module.broken(found, {"046": "name-the-gaps-do-not-level-them"}) == []


def test_an_empty_catalogue_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Выгрузка пуста — гейт падает, а не объявляет «чисто» (045, 075)."""
    monkeypatch.setattr(module.ghrest, "raw_json", lambda *_: {"rules": []})
    with pytest.raises(module.NotRun):
        module.known()


def test_an_unreachable_catalogue_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каталог недоступен — это «не спросили», а не «всё сошлось»."""

    def broken(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("нет сети")

    monkeypatch.setattr(module.ghrest, "raw_json", broken)
    with pytest.raises(module.NotRun):
        module.known()


def test_the_live_tree_has_no_broken_links() -> None:
    """Живое дерево проходит гейт — иначе он был бы объявлением намерения.

    Ссылки читаются из дерева, а имена — из каталога по сети. Без сети проверка
    пропускается: её предмет тогда недоступен, и падение говорило бы о канале.
    """
    try:
        real = module.known()
    except module.NotRun as exc:
        pytest.skip(f"каталог недоступен: {exc}")
    found = module.links(Path())
    assert found, "ссылок на правила в дереве нет — предмет не найден"
    assert module.broken(found, real) == []


def test_links_that_resolve_are_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Все ссылки разрешились — чистый исход, и охват назван числом.

    Охват печатается ВСЕГДА: проверка, читающая список, без числа неотличима
    от той, что не нашла ничего
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    monkeypatch.setattr(module, "known", lambda: {"044": "check-the-premise-before-fixing"})
    monkeypatch.setattr(
        module,
        "links",
        lambda root: [("AGENTS.md", 1, "044", "check-the-premise-before-fixing")],
    )
    assert module.main([]) == module.EXIT_OK
    assert "проверено 1" in capsys.readouterr().out
