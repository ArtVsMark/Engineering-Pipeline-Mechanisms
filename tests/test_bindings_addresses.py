"""Ответ каталогу называет адреса, которые ЕСТЬ в дереве.

Каталог требует от поля `where` разрешимый адрес, а не прозу, и проверяет это у
себя — но у потребителя проверить не может: файл чужой, и красное оттуда
приучало бы читать красное как фон. Значит проверять обязан сам потребитель
([174](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/174-facts-about-a-project-are-published-by-it.md)).

ЧТО ЭТО ЛОВИТ. Механизм переименовали или он переехал, а ответ остался прежним:
снаружи такой ответ выглядит живым, и расхождение молчит до тех пор, пока
кто-нибудь не пойдёт по адресу руками. ЗАМЕР 10.09.2026, найдено ревизией по
просьбе владельца, а не механизмом: ответ на правило 075 называл
`gates_complete.py` — имя, под которым сводный гейт не живёт с самого
переименования.

ЧЕГО ГЕЙТ НЕ ТРЕБУЕТ. Чужих адресов — механизм соседа законно называется в
ответе и в нашем дереве не лежит. Такие имена перечислены списком с причиной, а
не пропускаются молча
([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

import pytest

ROOT = Path(__file__).resolve().parent.parent
BINDINGS = ROOT / ".rules" / "bindings.json"

#: Имя файла механизма внутри ответа: то, по чему читатель пойдёт искать.
#: Ведущая точка входит в имя: `.pipeline.yml` — файл ответа проекта, и без неё
#: гейт искал бы в дереве несуществующий `pipeline.yml`.
NAME_RE: Final = re.compile(r"(?<![\w./-])(\.?[\w./-]+\.(?:py|yml|yaml))\b")

#: Имена, которых в этом дереве нет и быть не должно. Список разрешительный:
#: каждое названо с причиной, и молчаливого пропуска здесь нет.
FOREIGN: Final = {
    "onboard_consumer.py": "механизм каталога: им собран наш ответ, у нас его нет",
}


def answers() -> dict[str, dict[str, str]]:
    """Ответы проекта по правилам каталога."""
    document = json.loads(BINDINGS.read_text(encoding="utf-8"))
    rules: dict[str, dict[str, str]] = document["rules"]
    return rules


def tree_names() -> set[str]:
    """Имена файлов дерева — по ним и ищет читатель ответа."""
    return {path.name for path in ROOT.rglob("*") if path.is_file()}


def named_files() -> list[tuple[str, str]]:
    """Пары «правило, имя файла», названные в ответах."""
    found: list[tuple[str, str]] = []
    for rule, answer in sorted(answers().items()):
        for field in ("where", "why"):
            for name in NAME_RE.findall(str(answer.get(field) or "")):
                found.append((rule, name.rsplit("/", 1)[-1]))
    return found


def test_the_gate_found_its_subject() -> None:
    """Предмет проверки найден: ответы есть и адреса в них называются (075)."""
    assert answers(), "ответов каталогу нет — проверять нечего"
    assert named_files(), "ни один ответ не называет файла — предмет не найден"


@pytest.mark.parametrize(
    ("rule", "name"), named_files(), ids=lambda item: item if isinstance(item, str) else ""
)
def test_a_named_mechanism_exists_in_the_tree(rule: str, name: str) -> None:
    """Файл, названный в ответе, лежит в дереве — или объявлен чужим.

    Ответ, называющий несуществующий механизм, врёт каталогу и читателю
    одинаково правдоподобно: снаружи он ничем не отличается от живого.
    """
    if name in FOREIGN:
        return
    assert name in tree_names(), (
        f"ответ на правило {rule} называет «{name}», которого в дереве нет. "
        "Механизм переименован или переехал — поправьте ответ или объявите имя "
        f"чужим в FOREIGN с причиной. Известные чужие: {sorted(FOREIGN)}"
    )


def test_every_foreign_name_is_explained() -> None:
    """У каждого чужого имени названа причина, а не просто пропуск (154)."""
    assert all(FOREIGN.values()), "чужое имя объявлено без причины"


def test_the_foreign_list_is_not_a_graveyard() -> None:
    """В списке чужих нет имён, которые в дереве всё же есть.

    Такое имя означает, что исключение пережило свою причину: механизм появился
    у нас, а гейт продолжает его не проверять.
    """
    stray = sorted(set(FOREIGN) & tree_names())
    assert not stray, f"эти имена есть в дереве и в исключении не нуждаются: {stray}"


#: Любой адрес файла в ответе, включая документы: нужен, чтобы отличить
#: «назван документ» от «не названо ничего» — это разные находки (154).
ANY_FILE_RE: Final = re.compile(r"(?<![\w./-])(\.?[\w./-]+\.[a-z]{2,5})\b")
#: Что считается ИСПОЛНЯЕМЫМ адресом: то, что можно запустить и получить код
#: возврата. Список закрытый: «похоже на путь» приняло бы и документ, а весь
#: смысл правила в том, что документ механизмом не является.
RUNNABLE_SUFFIXES = (".py", ".yml", ".yaml")
#: Механизмы, у которых исполняемого адреса нет и быть не может, — с причиной.
#: Пустой список тут был бы честнее пустой отговорки: имя попадает сюда только
#: тогда, когда предмет действительно вне дерева (154).
RUNNABLE_ELSEWHERE: dict[str, str] = {}


@pytest.mark.parametrize(
    "answer",
    [(number, one) for number, one in sorted(answers().items()) if one.get("mechanism") == "gate"],
    ids=lambda pair: str(pair[0]),
)
def test_a_gate_names_something_runnable(answer: tuple[str, dict[str, Any]]) -> None:
    """Ответ «держится гейтом» называет адрес ИСПОЛНЯЕМОГО, а не документа.

    Правило 139: механизм считается работающим по прогону, а не по написанному.
    Документ прогоном не подтверждается вовсе — он не запускается; ответ,
    называющий гейтом абзац в `AGENTS.md`, обещает проверку, которой нет.

    Правило соблюдалось всеми ста пятью ответами и держалось при этом
    вниманием: сто шестому ничто не мешало назвать документ. Гейт перенесён от
    каталога, где список видов тоже закрытый (162).
    """
    number, one = answer
    if number in RUNNABLE_ELSEWHERE:
        return
    names = ANY_FILE_RE.findall(one.get("where") or "")
    runnable = [name for name in names if name.endswith(RUNNABLE_SUFFIXES)]
    assert runnable, (
        f"правило {number}: ответ «gate» не назвал исполняемого — {names or 'адресов нет'}. "
        "Механизм подтверждается прогоном, а документ не запускается (139)"
    )
