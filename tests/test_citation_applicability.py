"""Гейт правила 204: ссылка на правило утверждает его применимость.

ЧТО ИМЕННО ЗДЕСЬ ПРОВЕРЯЕТСЯ, А ЧТО НЕТ. Правило говорит: ссылка на правило
есть утверждение, что правило **применимо** к названному случаю, и проверяется
она разделом «Применимость» цитируемого правила, а не подходящей фразой из его
буквы. Подходит ли раздел «Не работает» к нашему случаю — вывод из смысла, и
машина его не делает. Но у утверждения есть половина, решаемая **данными**:
проект уже сказал по каждому правилу каталога, применимо ли оно к нему, —
это `.rules/bindings.json`. Опереться на правило, чью применимость мы сами
отвергли, — противоречие, и оно видно без чтения смысла.

ЗАМЕР 11.09.2026, ИЗ-ЗА КОТОРОГО ГЕЙТ И ПОЯВИЛСЯ. Таких ссылок нашлось две, и
обе — ровно тот случай, который правило описывает: подходящая фраза из буквы.
`docs/behaviour.md` опирался на 193 («приёмка починки строже чинимого дефекта»),
тогда как 193 — о МАССОВОЙ автоматической починке данных, и наш же ответ по
нему говорит `not-applicable`. Вторая ссылка написана в тот же день, в
докстроке нового механизма.

УПОМИНАНИЕ — НЕ ОСНОВАНИЕ, И ПРАВИЛО ЭТО НАЗЫВАЕТ. Сослаться на неприменимое
правило законно, когда речь о ЕГО границе, а не о нашем требовании. Такие
ссылки живут в списке ниже — закрытом и с причиной у каждой. Список, в который
можно дописать молча, перестал бы быть границей и стал бы местом, куда сваливают
неудобное ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.conftest import ROOT

BINDINGS = ROOT / ".rules" / "bindings.json"
LINK_RE = re.compile(r"rules/ru/(?P<number>\d{3})-")
SUFFIXES = frozenset({".py", ".md", ".yml", ".yaml", ".json"})

#: Ссылки на правила, чья применимость у нас отвергнута, и которые всё же
#: законны: речь идёт о ГРАНИЦЕ цитируемого правила, а не о нашем требовании.
#: Ключ — «путь:номер правила», значение — почему это упоминание, а не основание.
MENTIONS: dict[str, str] = {
    "scripts/check_derived_refs.py:194": (
        "это граница правила 196, а не наше требование: 196 само говорит, что для "
        "ЧУЖОГО ресурса предмет другой и держит его 194. Механизм здесь ссылается "
        "на чужую границу, чтобы объяснить, ЧЕГО он не судит"
    ),
}


def cited() -> dict[str, list[str]]:
    """Номер правила → где на него ссылаются: «путь:строка»."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    )
    found: dict[str, list[str]] = {}
    for name in listed.stdout.split("\0"):
        if not name or Path(name).suffix not in SUFFIXES:
            continue
        # Сам этот файл называет номера как ПРИМЕРЫ разбора, а не как основание.
        if name == "tests/test_citation_applicability.py":
            continue
        for number, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            for match in LINK_RE.finditer(line):
                found.setdefault(match["number"], []).append(f"{name}:{number}")
    return found


def answers() -> dict[str, str]:
    """Наш ответ по каждому правилу каталога: номер → статус."""
    rules = json.loads(BINDINGS.read_text(encoding="utf-8"))["rules"]
    return {number: str(answer.get("status") or "") for number, answer in rules.items()}


def test_there_are_citations_to_check() -> None:
    """Предмет найден: ссылки на правила в дереве есть (075)."""
    assert cited(), "ссылок на правила в дереве нет — проверять нечего"


def test_no_requirement_rests_on_a_rule_we_called_inapplicable() -> None:
    """Мы не опираемся на правило, применимость которого сами отвергли (204).

    Починок у находки две, и выбирает их человек: либо ссылка неверна — тогда
    правится она, либо неверен ответ — тогда перечитывается он. Молчаливого
    третьего пути нет.
    """
    our = answers()
    problems = [
        f"{place} — {number} ({our[number]}): наш ответ отрицает применимость"
        for number, places in sorted(cited().items())
        for place in places
        if our.get(number) and our[number] != "active"
        if f"{place.split(':')[0]}:{number}" not in MENTIONS
    ]
    assert not problems, "ссылка утверждает применимость, а ответ её отрицает:\n  " + "\n  ".join(
        problems
    )


def test_every_mention_names_its_reason() -> None:
    """У каждой записи в списке упоминаний названа причина (154)."""
    bare = [place for place, why in MENTIONS.items() if not why.strip()]
    assert not bare, f"упоминание без причины: {bare}"


def test_the_mention_list_has_no_dead_entries() -> None:
    """Список не хранит записей о том, чего в дереве уже нет.

    Мёртвая запись разрешает то, чего не существует, и незаметно разрешит
    новое: путь вернётся в дерево с другой ссылкой, а разрешение уже стоит.
    """
    live = {
        f"{place.split(':')[0]}:{number}" for number, places in cited().items() for place in places
    }
    dead = sorted(set(MENTIONS) - live)
    assert not dead, f"запись списка не имеет предмета в дереве: {dead}"


def test_every_cited_rule_has_an_answer_at_all() -> None:
    """Ссылка на правило, по которому ответа нет вовсе, — тоже утверждение впустую."""
    our = answers()
    unknown = sorted(number for number in cited() if number not in our)
    assert not unknown, f"ссылка на правило без нашего ответа: {unknown}"
