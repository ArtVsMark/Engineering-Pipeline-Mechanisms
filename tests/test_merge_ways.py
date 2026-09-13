"""Способ слияния держится настройкой площадки, а не только гейтом по истории.

Решение `docs/decisions/007-merge-method-is-held-by-the-platform-too.md`:
у площадки остаётся одна кнопка — уплотнение. Настройка живёт ВНЕ дерева, её не
видит ни ревью, ни прогон, и вернуть кнопку можно одним щелчком. Поэтому разрыв
между решением и настройкой СПРАШИВАЕТСЯ, а не предполагается.

Гейт `tests/test_squash_only.py` держит другой конец: он замечает нарушение по
истории общей ветки, когда чинить уже нечем. Настройка не пускает, гейт
замечает, если пустила, — и оба нужны (046).

Нашёл внешний взгляд на #167: в решении не был назван более дешёвый вариант,
способный предотвратить инцидент, а не только поймать его повторение.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("check_required_context.py")
DECISION = ROOT / "docs" / "decisions" / "007-merge-method-is-held-by-the-platform-too.md"


def answer(**flags: bool) -> dict[str, Any]:
    """Ответ площадки о репозитории — только те поля, что читает сверка."""
    return {"allow_squash_merge": True, **flags}


def test_an_extra_merge_way_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включённый merge-коммит — находка: решение 006 говорит иначе."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: answer(allow_merge_commit=True))
    assert module.merge_ways("o/r", "token") == ["merge-коммит"]


def test_rebase_is_an_extra_way_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Перестановка тоже лишняя: коммиты окна уехали бы в общую ветку как есть."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: answer(allow_rebase_merge=True))
    assert module.merge_ways("o/r", "token") == ["перестановка"]


def test_both_extra_ways_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Названы ОБА лишних способа, а не первый попавшийся (159)."""
    said = answer(allow_merge_commit=True, allow_rebase_merge=True)
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: said)
    assert module.merge_ways("o/r", "token") == ["merge-коммит", "перестановка"]


def test_squash_alone_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одно уплотнение — это и есть решённое состояние, находки нет."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: answer())
    assert module.merge_ways("o/r", "token") == []


def test_auto_merge_is_not_an_extra_way(monkeypatch: pytest.MonkeyPatch) -> None:
    """Авто-мерж площадки — вход НАШЕГО шага очереди, а не способ слияния.

    Он взводится меткой согласия и сливает тем способом, какой разрешён. Снять
    его значило бы сломать шаг 8 ради запрета, который уже достигается выбором
    способа, — и это названо в решении, а не умолчано (154).
    """
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: answer(allow_auto_merge=True))
    assert module.merge_ways("o/r", "token") == []


def test_an_unread_setting_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — «не отработало», а не «лишнего нет» (045)."""

    def broken(*_: object, **__: object) -> Any:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.ghrest, "request", broken)
    with pytest.raises(module.NotRun):
        module.merge_ways("o/r", "token")


def test_the_decision_is_recorded_not_only_coded() -> None:
    """Развилка записана решением, а не живёт в коде механизма (042, 161).

    У неё есть цена переключения и был выбор: гейт по истории, настройка, или
    оба. Запись без альтернатив — объявление, а не решение.
    """
    said = DECISION.read_text(encoding="utf-8")
    assert "## Отвергнутые варианты" in said
    assert "Оставить один гейт" in said, "не назван вариант, который был до этого решения"


def test_the_context_gate_reports_a_divergence_when_it_is_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сверка ПРОГОНЯЕТСЯ по пути находки, а не только разбирается по частям.

    Чистые функции проверяли решение, но не проводку: заход мог решить
    «расходится» и вернуть ноль, и набор этого бы не заметил
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    monkeypatch.setenv("MERGE_QUEUE_TOKEN", "подделка")
    monkeypatch.setattr(module, "declared_context", lambda *a, **k: "ci-complete")
    monkeypatch.setattr(module, "protection", lambda *a, **k: ["чужое-имя"])
    assert module.main(["--repo", "o/r"]) == module.EXIT_FINDINGS


def test_the_context_gate_is_silent_when_the_names_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Обратная сторона того же прогона: совпали имена — находки нет (097)."""
    monkeypatch.setenv("MERGE_QUEUE_TOKEN", "подделка")
    monkeypatch.setattr(module, "declared_context", lambda *a, **k: "ci-complete")
    monkeypatch.setattr(module, "protection", lambda *a, **k: ["ci-complete"])
    # Способы слияния — второй предмет того же захода, и без него он честно
    # уходит в третий исход: сеть в наборе не спрашивают.
    monkeypatch.setattr(module, "merge_ways", lambda *a, **k: [])
    assert module.main(["--repo", "o/r"]) == module.EXIT_OK
