"""Гейт 196 проверяется отказом: ссылка вперёд артефакта обязана краснеть.

Правило говорит о ПОРЯДКЕ, а не о целости витрины, и гейт легко построить так,
что он зелен всегда: спросить площадку про то, чего изменение не добавляло.
Поэтому здесь проверяется и находка, и то, что предмет отбирается верно —
чужой репозиторий и общая ветка в него не попадают.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("check_derived_refs.py")

OURS = "ArtVsMark/Engineering-Pipeline-Mechanisms"
BADGE = f"![значок](https://raw.githubusercontent.com/{OURS}/badges/rules.svg)"


def test_a_badge_on_its_own_branch_is_the_subject() -> None:
    """Адрес производного разбирается на ветку и путь."""
    assert module.ours([BADGE], OURS) == [("badges", "rules.svg")]


def test_a_link_into_the_trunk_is_not_the_subject() -> None:
    """Ссылка в общую ветку — обычная ссылка дерева, её держит гейт 022."""
    line = f"[договор](https://github.com/{OURS}/blob/main/docs/pipeline.md)"
    assert module.ours([line], OURS) == []


def test_someone_elses_artefact_is_not_our_order() -> None:
    """Чужое появление проект не упорядочивает — предмет другой (194)."""
    line = "![чужой](https://raw.githubusercontent.com/OtherOwner/Other/badges/x.svg)"
    assert module.ours([line], OURS) == []


def test_the_same_address_twice_is_one_subject() -> None:
    """Один адрес, названный дважды, — одна проверка, а не две."""
    assert module.ours([BADGE, BADGE], OURS) == [("badges", "rules.svg")]


def test_a_reference_before_the_artefact_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка говорит «нет такого» — значит ссылка уехала первой."""

    def nothing(_method: str, path: str, _token: str) -> Any:
        raise module.ghrest.NotFound(f"GET {path} → 404")

    monkeypatch.setattr(module.ghrest, "request", nothing)
    assert module.drawn(OURS, "t", "badges", "rules.svg") is False


def test_a_drawn_artefact_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Артефакт нарисован — порядок соблюдён, находки нет."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_: {"name": "rules.svg"})
    assert module.drawn(OURS, "t", "badges", "rules.svg") is True


def test_an_unreachable_platform_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — это «не отработал», а не «нарисовано» (045)."""

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise module.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(module.ghrest, "request", broken)
    with pytest.raises(module.NotRun):
        module.drawn(OURS, "t", "badges", "rules.svg")


def test_the_readme_badges_are_seen_by_this_parser() -> None:
    """Разбор видит НАСТОЯЩИЕ значки витрины, а не только выдуманный образец (075).

    Без этой строки гейт мог бы разбирать форму, которой в дереве нет, и молчать
    ровно про тот случай, ради которого построен.
    """
    from tests.conftest import ROOT

    readme = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    seen = module.ours(readme, OURS)
    assert len(seen) >= 4, f"значков витрины разобрано {len(seen)} — разбор их не видит"
    assert {ref for ref, _ in seen} == {"badges"}, seen


def test_the_gate_reports_an_undrawn_artefact_when_it_is_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Гейт ПРОГОНЯЕТСЯ по пути находки, а не только разбирается по частям.

    Чистые функции проверяли решение, но не проводку: заход мог решить
    «не нарисовано» и вернуть ноль, и набор этого бы не заметил
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    monkeypatch.setenv("GH_TOKEN", "подделка")
    monkeypatch.setattr(module, "added_lines", lambda *a, **k: [BADGE])
    monkeypatch.setattr(module, "drawn", lambda *a, **k: False)
    assert module.main(["--repo", OURS, "--base", "main"]) == module.EXIT_FOUND


def test_the_gate_is_silent_when_the_artefact_is_drawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обратная сторона того же прогона: нарисованное проходит (097)."""
    monkeypatch.setenv("GH_TOKEN", "подделка")
    monkeypatch.setattr(module, "added_lines", lambda *a, **k: [BADGE])
    monkeypatch.setattr(module, "drawn", lambda *a, **k: True)
    assert module.main(["--repo", OURS, "--base", "main"]) == module.EXIT_OK
