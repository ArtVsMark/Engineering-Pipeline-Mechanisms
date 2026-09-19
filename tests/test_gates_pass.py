"""У каждого гейта есть прогон ЧИСТОГО входа, а не только прогон отказа.

У проверки два рода ошибок, и они независимы
([097](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/097-a-checker-has-two-error-types.md)).
Ложное «прошло» — гейт не отверг того, что обязан; его держит
`tests/test_gates_reject.py` по ВСЕМ гейтам сразу. Ложное «не прошло» — гейт
отверг здоровое; проверяется здесь и тем же способом.

ПОЧЕМУ ВТОРАЯ ПОЛОВИНА НЕ МЕНЕЕ ВАЖНА. Гейт, отвергающий верное, дороже
отсутствующего: его начинают обходить формулировкой, и вместе с шумом гаснет
настоящая находка
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
Сегодня это уже случилось дважды за смену: предикат поиска вверх по дереву
покраснел на трёх исправных механизмах, а предикат адреса настройки — на
четырёх сравнениях по имени файла. Оба поймал прогон, а не чтение.

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ПРОВЕРКА И НАПИСАНА. Прогон чистого входа есть
у ВСЕХ ВОСЕМНАДЦАТИ гейтов — то есть половина правила исполнялась и не держалась
ничем. Ответ проекта при этом утверждал симметрию: «tests/test_gates_reject.py —
ложное „прошло“; tests/test_gates_complete.py — ложное „не прошло“». Первое
верно и идёт по всем гейтам разом; второе — про ОДИН механизм, `ci_complete.py`,
и на прочие семнадцать не смотрит вовсе. Девятнадцатый гейт без чистого прогона
не покраснел бы нигде
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

РАЗБОР ЗДЕСЬ НЕ ЗАВОДИТСЯ ЗАНОВО. Чем запускают гейт и что утверждают о его
исходе, уже читает `tests/outcomes.py`; второй такой разбор разошёлся бы с
первым молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
Предмет — те же `GATES`, что у прогона отказа, и берутся они оттуда же.

ПРЕДЕЛ ТОТ ЖЕ, ЧТО У СОСЕДА, и назван теми же словами: предметом считается
МОДУЛЬ — запускает гейт и утверждает чистый исход. Модуль, запускающий два
гейта и утверждающий чистое одним из них, засчитает оба. Ловится здесь другое —
гейт, у которого чистого прогона нет НИГДЕ
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

from typing import Final

from tests import outcomes
from tests.conftest import ROOT, walk
from tests.test_gates_reject import GATES

#: Как в этом дереве называют ЧИСТЫЙ исход. Список разрешительный: новое имя
#: дописывается сюда, а не проходит само (068). Замер 18.09.2026 по 18 гейтам:
#: `EXIT_OK` у шестнадцати, `EXIT_CLEAN` у двух — третьего написания нет.
CLEAN_NAMES: Final = ("EXIT_OK", "EXIT_CLEAN")


def clean_of(gate: str) -> set[int]:
    """Какими числами ЭТОТ гейт объявляет чистый исход — по его константам.

    Спрашивается у гейта, а не назначается нулём: число — следствие объявления,
    и требовать нуля от механизма, объявившего иначе, значило бы чинить
    исправное
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    return {code for name, code in outcomes.declared(gate).items() if name in CLEAN_NAMES}


def gates_with_a_clean_run() -> set[str]:
    """Гейты, у которых в наборе есть прогон их ЧИСТОГО входа."""
    found: set[str] = set()
    for path in walk(ROOT / "tests", "test_*.py"):
        tree = outcomes.tree_of(path)
        numbers, names = outcomes.asserted(tree)
        for gate in outcomes.started_by(tree):
            if gate not in GATES:
                continue
            said = outcomes.declared(gate)
            hit = numbers | {said[name] for name in names if name in said}
            if hit & clean_of(gate):
                found.add(gate)
    return found


def test_the_subject_of_this_gate_exists() -> None:
    """Предмета нет — отказ, а не «чисто» (075)."""
    assert GATES, "гейтов в дереве не нашлось — сверять нечего"
    assert all(clean_of(one) for one in GATES), (
        "гейт не объявляет чистого исхода ни одним из известных имён: "
        f"{sorted(one for one in GATES if not clean_of(one))} — допишите имя в CLEAN_NAMES"
    )


def test_every_gate_has_a_run_of_its_clean_input() -> None:
    """У каждого гейта прогоняется и здоровый вход, а не только подделанный.

    Гейт, проверенный одним отказом, доказывает половину: он умеет краснеть.
    Умеет ли он молчать на исправном дереве — другой вопрос, и ответ на него
    приходит позже и у другого
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    mute = sorted(set(GATES) - gates_with_a_clean_run())
    assert not mute, (
        "у гейта нет прогона ЧИСТОГО входа (097):\n  "
        + "\n  ".join(mute)
        + "\n  Прогон здорового входа — вторая половина проверки: без неё"
        " неизвестно, отвергает ли гейт исправное дерево."
    )
