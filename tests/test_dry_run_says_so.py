"""Пробный заход НАЗЫВАЕТ СЕБЯ: иначе ослабленный режим молчит.

Правило 045 запрещает не только молчаливое продолжение в ослабленном режиме, но
и его невидимость, и признак нарушения назван у самого правила прямо: «в логе
нет строки, по которой видно, в каком режиме прошёл КОНКРЕТНЫЙ запуск»
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Разница не косметическая: пробный заход и заход, которому нечего было делать,
снаружи дают один наблюдаемый исход — ничего не изменилось.

ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И НАПИСАН. Пробный режим есть у
**пятнадцати** механизмов; признак режима несли **шесть**, и все шесть вписывали
семь букв строкой у себя. Проверок при этом не было ни одной: все проверки
пробного захода спрашивают «ничего не тронул» и ни одна — «сказал, в каком
режиме прошёл». То есть требование исполнялось наполовину и не держалось ничем
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ПРИЗНАК ОДИН НА ВСЕХ, И ЭТО УСЛОВИЕ САМОГО ГЕЙТА. Пока приставка была вписана в
шесть модулей, предикат по дереву искал бы ПОДСТРОКУ — то есть проверял бы
отношение присутствием текста, и переписанная в одном месте формулировка увела
бы модуль из-под проверки молча
([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
Признак вынесен в `report.DRY`, и гейт спрашивает ИМЯ, а не буквы
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: он требует, чтобы механизм
УМЕЛ назвать режим, а не чтобы называл его в каждой строке. Разбором по дереву
второе неотличимо от первого: строка собирается на ходу. Проверку «пробный
заход действительно это напечатал» ведут прогоны самих механизмов
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
from typing import Final

from tests.conftest import ROOT, load_script

#: Ключи, которыми механизм объявляет пробный режим.
DRY_FLAGS: Final = ('"--apply"', '"--dry-run"')
#: Имя общего признака: гейт спрашивает ЕГО, а не семь букв внутри строки.
MARK: Final = "DRY"
SCRIPTS: Final = ROOT / "scripts"


def with_a_dry_run() -> list[str]:
    """Механизмы, объявившие пробный режим ключом входа."""
    found = []
    for path in sorted(SCRIPTS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(flag in text for flag in DRY_FLAGS):
            found.append(path.name)
    return found


def names_the_mode(name: str) -> bool:
    """Тянется ли механизм к общему признаку режима — РАЗБОРОМ, а не подстрокой.

    Признаётся обращение `report.DRY`/`report.announce` и прямой импорт имени.
    Строка с теми же буквами, вписанная у себя, признаком НЕ считается: она и
    есть то, от чего признак вынесен наверх.
    """
    tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in (MARK, "announce")
            and isinstance(node.value, ast.Name)
            and node.value.id == "report"
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "report"
            and any(alias.name in (MARK, "announce") for alias in node.names)
        ):
            return True
    return False


def test_the_subject_of_this_gate_exists() -> None:
    """Механизмов с пробным режимом нет — отказ, а не «чисто» (075)."""
    assert with_a_dry_run(), "ни один механизм не объявил пробного режима — сверять нечего"


def test_every_mechanism_with_a_dry_run_can_name_it() -> None:
    """Объявил пробный режим — умеет его назвать. Иначе ослабление невидимо."""
    silent = [name for name in with_a_dry_run() if not names_the_mode(name)]
    assert not silent, (
        "механизм объявил пробный режим и не умеет его назвать — ослабление молчит (045):\n  "
        + "\n  ".join(silent)
    )


def test_the_mark_lives_in_one_place() -> None:
    """Признак объявлен в общем низу, а не вписан в механизмы по копии.

    Довод гейта — «спрашиваем имя, а не буквы» — держится ровно этим. Вернётся
    вписанная строка, и предикат снова станет подстрочным, а проверка этого не
    заметит: здесь она это замечает
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    mark = load_script("../packages/transport/report.py").DRY
    written = [
        path.name
        for path in sorted(SCRIPTS.glob("*.py"))
        if mark in path.read_text(encoding="utf-8")
    ]
    assert not written, (
        f"признак режима «{mark}» вписан строкой, а не взят из общего низа (022, 090): "
        + ", ".join(written)
    )
