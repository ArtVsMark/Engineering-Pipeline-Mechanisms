"""Номер формата говорит, ЧЕГО он версия, — а его отсутствие называет причину.

Правило 164 требует не наличия номера, а его однозначности **в точке чтения**:
проект публикует несколько независимо версионируемых предметов, и один и тот же
ключ у разных предметов означает, что номер соседа рано или поздно окажется
вписан не туда — причём обе стороны останутся валидными, и не заметит этого ни
разбор, ни человек
([164](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/164-a-version-says-what-it-versions.md)).

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Записей в `.rules/` десять.
Пять объявляли, почему номера у них нет; **ни одна** из пяти несущих номер не
поясняла всех своих. Худший случай — витрина: `schema` и `answers_to` там **оба
равнялись 1.1**, то есть ошибка «вписал номер соседа» была бы не просто тихой, а
ненаблюдаемой в принципе. Ещё две записи — исходы и защита ветки — молчали и о
номере, и о его отсутствии, тогда как пятеро соседей причину называли: молчание
состоянием не является
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ВЫЧИТКА. Номер приходит от издателя и поднимается им же;
объяснение к нему пишет потребитель — то есть расходятся они на чужой правке, а
не на своей, и своего красного у такого расхождения нет. Замер выше собран
руками за один заход и показал ноль из пяти: внимание здесь уже не сработало
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: верность самого объяснения.
Он требует, чтобы у номера был подписанный предмет, и не судит, тот ли предмет
назван. Так же устроен и `.rules/leniency.json` — форма держится машиной,
существо правкой обоих
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import json
from typing import Any, Final

from tests.conftest import ROOT

RULES: Final = ROOT / ".rules"
#: Ключи, которыми запись несёт номер формата.
NUMBERS: Final = ("schema", "answers_to")
#: Объявление «номера нет» и его причины. Ключ русский — как у прочих объявлений.
NO_NUMBER: Final = "_версии_нет"


def declarations() -> list[tuple[str, dict[str, Any]]]:
    """Записи `.rules/` и их содержимое."""
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(RULES.glob("*.json"))
    ]


def test_the_subject_of_this_gate_exists() -> None:
    """Объявлений нет — отказ, а не «чисто» (075)."""
    assert declarations(), f"в {RULES} нет ни одного объявления — сверять нечего"


def test_every_number_says_what_it_versions() -> None:
    """У каждого номера есть пояснение рядом — в точке чтения, а не в документе."""
    mute = [
        f"{name}: номер «{key}» без пояснения «_{key}» рядом"
        for name, said in declarations()
        for key in NUMBERS
        if key in said and f"_{key}" not in said
    ]
    assert not mute, (
        "номер не говорит, чего он версия (164):\n  "
        + "\n  ".join(mute)
        + "\n  Пояснение ставится ключом «_<имя>» СРАЗУ ПОСЛЕ номера: предмет узнаётся"
        " в точке чтения,\n  а не поиском по документам."
    )


def test_a_record_without_a_number_says_why() -> None:
    """Номера нет — причина названа. «Нет» без причины неотличимо от «забыли» (154)."""
    mute = [
        name
        for name, said in declarations()
        if not any(key in said for key in NUMBERS) and NO_NUMBER not in said
    ]
    assert not mute, (
        "запись без номера формата не назвала причину (154, 164): "
        + ", ".join(mute)
        + f"\n  Причина объявляется ключом «{NO_NUMBER}»; у соседей она обычно одна —"
        " единственный читатель\n  записи едет тем же коммитом, что и она сама."
    )


def test_two_numbers_in_one_record_are_told_apart() -> None:
    """Два номера в одной записи различены пояснениями, а не порядком строк.

    Это сильнейшая форма беды, которую называет правило, и мерить её надо
    отдельно: пока номера РАВНЫ, вписанный не туда не отличим ничем. Такая
    запись в дереве есть — витрина, — и довод гейта держится тем, что она есть
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    pairs = [(name, said) for name, said in declarations() if all(k in said for k in NUMBERS)]
    assert pairs, "записей с двумя номерами нет — довод про сильнейшую форму пуст"
    for name, said in pairs:
        for key in NUMBERS:
            текст = str(said.get(f"_{key}", ""))
            assert текст, f"{name}: номер «{key}» без пояснения"
            прочие = [other for other in NUMBERS if other != key]
            assert any(other in текст for other in прочие), (
                f"{name}: пояснение к «{key}» не отделяет его от {прочие} — а именно"
                " спутать их и предлагает форма записи (164)"
            )
