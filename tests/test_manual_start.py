"""У прогона есть рука, которой его пускают, — или названа причина, почему нет.

События теряются. Если запуск бывает ТОЛЬКО по событию, единственным способом
добудиться становится мусорное изменение
([104](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/104-event-driven-automation-needs-a-manual-button.md)).

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Прогонов в дереве двадцать,
кнопку несут девятнадцать — то есть требование исполнялось. Держалось оно при
этом СПИСКОМ ИЗ ДЕСЯТИ ИМЁН, вписанным в ответ каталогу рукой: список отстал от
дерева почти вдвое и не краснел нигде, а новый прогон без кнопки не покраснел бы
тоже
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md),
[005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

ИСКЛЮЧЕНИЕ ОБЪЯВЛЕНО ЗДЕСЬ, А НЕ УГАДЫВАЕТСЯ. Список разрешительный: прогон вне
его обязан нести кнопку, а попавший в него — назвать причину, по которой она
бессмысленна
([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md),
[154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
"""

from __future__ import annotations

from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, walk

WORKFLOWS: Final = ROOT / ".github" / "workflows"
#: Ключ ручного запуска у площадки.
BY_HAND: Final = "workflow_dispatch"
#: Прогоны, которым кнопка бессмысленна, — с причиной у каждого.
WITHOUT_A_HAND: Final[dict[str, str]] = {
    "claude.yml": (
        "отвечает на ОБРАЩЕНИЕ человека и запускается им же: событие здесь и есть"
        " рука. Кнопка без обращения смотрела бы в пустоту — отвечать было бы не на"
        " что, и запуск дал бы заход без предмета (075)"
    ),
    "step-debt.yml": (
        "ВЫЗЫВАЕМЫЙ прогон: сам он не идёт никогда, его зовут по `uses:`. Рука у"
        " него есть, но чужая — кнопка вызывающего (`ci.yml`), и она на месте."
        " Своя кнопка здесь не добавила бы способа добудиться, зато сделала бы"
        " прогон идущим САМОСТОЯТЕЛЬНО — то есть завела бы вторую проверку с тем"
        " же именем, которую пришлось бы отдельно объявлять в `.pipeline.yml`"
    ),
}


def runs() -> list[tuple[str, dict[Any, Any]]]:
    """Объявления прогонов дерева.

    КЛЮЧИ ЗДЕСЬ СМЕШАННЫЕ, и тип это признаёт: YAML разбирает голое `on:` как
    булево `True`, так что объявление несёт и строковые ключи, и один булев.
    Объявить `dict[str, Any]` значило бы описать не то, что читается (045).
    """
    found: list[tuple[str, dict[Any, Any]]] = []
    for path in walk(WORKFLOWS, "*.y*ml"):
        said = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found.append((path.name, said))
    return found


def triggers(said: dict[Any, Any]) -> set[str]:
    """Чем прогон запускается. `on` читается и как ключ, и как True.

    YAML разбирает голое `on:` как булево True — это не причуда, а норма языка, и
    разбор, знающий одну форму, теряет ВСЕ события прогона молча (045).
    """
    # Ключ `True` здесь настоящий: YAML разбирает голое `on:` булевым, и словарь
    # объявления несёт оба вида ключей разом. Разбор типов этого не ждёт, потому
    # и спрашивается явно.
    on: Any = said.get("on")
    if on is None:
        on = said.get(True) or {}
    if isinstance(on, dict):
        return set(on)
    if isinstance(on, list):
        return set(on)
    return {str(on)}


def test_the_subject_of_this_gate_exists() -> None:
    """Прогонов нет — отказ, а не «у всех есть кнопка» (075)."""
    assert runs(), f"в {WORKFLOWS} не нашлось объявлений прогонов — сверять нечего"


@pytest.mark.parametrize("name", [one for one, _ in runs()], ids=lambda one: one)
def test_a_run_can_be_started_by_hand(name: str) -> None:
    """Прогон пускается рукой — либо назван исключением с причиной."""
    said = dict(runs())[name]
    if BY_HAND in triggers(said):
        return
    why = WITHOUT_A_HAND.get(name, "")
    assert why, (
        f"{name}: запускается только событием и не назван исключением (104)."
        f"\n  События теряются, и добудиться будет нечем, кроме мусорного изменения."
        f"\n  Добавьте `{BY_HAND}:` либо впишите причину в WITHOUT_A_HAND."
    )
    assert len(why) >= 40, f"{name}: причина «{why}» — отписка, а не причина (154)"


def test_no_exception_outlives_its_run() -> None:
    """Исключение не переживает свой прогон и не прикрывает имеющий кнопку.

    Обратная половина. Мёртвая строка в списке читается как решение о прогоне,
    которого нет; строка о прогоне, у которого кнопка ЕСТЬ, — как запрет там, где
    запрета не нужно, и оба состояния молчат
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    alive = dict(runs())
    orphan = sorted(set(WITHOUT_A_HAND) - set(alive))
    assert not orphan, f"исключение названо для прогона, которого нет: {', '.join(orphan)}"
    spare = sorted(name for name in WITHOUT_A_HAND if BY_HAND in triggers(alive[name]))
    assert not spare, f"прогон несёт кнопку и при этом назван исключением: {', '.join(spare)}"
