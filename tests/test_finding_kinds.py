"""Роды находок: форма держится машиной, существо — человеком.

Запись копит КОНТЕКСТ, в чём косяк, чтобы третий случай одного рода был отличим
от первого. Отличить их можно лишь тогда, когда род назван словами, по которым
его узнают в следующий раз, а встречи названы отпечатками, а не числом: число
рассохлось бы первой же новой находкой
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

ЧЕГО ЭТОТ ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: ВЕРНОСТЬ отнесения
находки к роду. Отнесение — суждение, и машине оно недоступно; здесь держится
форма, как у таблицы послаблений
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

module = load_script("finding_kinds.py")

#: Отпечаток находки: короткий хеш коммита, каким его печатает реестр.
FINGERPRINT: Final = re.compile(r"^[0-9a-f]{7}$")
#: Адрес того, что род породил: путь к механизму либо номер правила или ответа.
#: Список закрытый: «улучшили подход» адресом не является и проверке не видно.
ADDRESS: Final = re.compile(
    r"(?:scripts|tests|packages|docs|\.claude)/[\w./-]+|(?:правил|ответ)\w*\s+\d{3}"
)
#: Короче этого признак рода — отписка, а не признак. Число то же, что у причин
#: витрины и пробелов: там оно взято у каталога, здесь берётся у них (022).
SIGN_AT_LEAST: Final = 60


def kinds() -> dict[str, dict[str, object]]:
    """Объявленные роды."""
    said: dict[str, dict[str, object]] = module.read()
    return said


def test_the_record_exists_and_is_not_empty() -> None:
    """Объявления нет — отказ, а не «родов нет» (075)."""
    assert kinds(), "роды находок не объявлены — предмет проверки не найден"


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_kind_says_what_the_mistake_is(name: str) -> None:
    """У рода назван ПРИЗНАК — то, по чему его узнают в следующий раз.

    Без него запись превращается в список ярлыков: имя рода есть, а отнести к
    нему новую находку не по чему, и счёт повторов становится вкусовым.
    """
    sign = str(kinds()[name].get("признак", "")).strip()
    assert len(sign) >= SIGN_AT_LEAST, (
        f"{name}: признак короче {SIGN_AT_LEAST} знаков — это ярлык, а не признак"
    )


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_kind_counts_by_fingerprints_not_by_a_number(name: str) -> None:
    """Встречи названы ОТПЕЧАТКАМИ: число рассохлось бы первой же находкой (005)."""
    met = kinds()[name].get("встречен")
    assert isinstance(met, list) and met, f"{name}: встречи не перечислены отпечатками"
    wrong = [str(one) for one in met if not FINGERPRINT.match(str(one))]
    assert not wrong, f"{name}: не отпечатки находок: {', '.join(wrong)}"


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_kind_says_what_holds_it_or_why_nothing_does(name: str) -> None:
    """Род держится механизмом либо называет причину, почему не держится (154)."""
    held = str(kinds()[name].get("закрыт", "")).strip()
    assert held, f"{name}: не сказано, чем род закрыт"
    if held.lower().startswith(module.NO_MECHANISM):
        assert len(held) > len(module.NO_MECHANISM) + 10, (
            f"{name}: «{held}» — молчание под видом ответа; «нет» обязано назвать причину"
        )


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_what_the_kind_gave_birth_to_is_addressable(name: str) -> None:
    """Пометка «породил» называет АДРЕС, а не впечатление.

    Род бывает закрыт чужим, давно стоявшим механизмом, — а бывает тем, который
    из него и родился. Без пометки повторный род выглядит бесплодным, хотя из
    него вышло правило; с пометкой без адреса она неотличима от похвалы.
    """
    born = kinds()[name].get(module.BORN)
    if born is None:
        return
    assert isinstance(born, list) and born, f"{name}: «породил» объявлен пустым"
    mute = [str(one) for one in born if not re.search(ADDRESS, str(one))]
    assert not mute, (
        f"{name}: «породил» без адреса — {'; '.join(one[:60] for one in mute)}."
        " Назовите механизм путём, а правило — номером."
    )


def test_a_repeated_kind_without_a_mechanism_is_named() -> None:
    """Повтор без механизма НАЗЫВАЕТСЯ, а не тонет среди прочих родов.

    Это и есть польза записи: род, встреченный трижды, — вход в гейт или в
    предложение правила. Пока роды жили в памяти окна, третий случай был
    неотличим от первого
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    """
    said = kinds()
    repeated = module.repeated(said)
    assert repeated, "повторяющихся родов нет вовсе — порог либо предмет выбран неверно"
    debt = module.unheld(said)
    for name, times in debt:
        assert times >= module.REPEATED_AT
        assert str(said[name].get("закрыт", "")).lower().startswith(module.NO_MECHANISM)


def test_the_threshold_is_declared_not_buried() -> None:
    """Порог повтора объявлен именем, а не вписан числом посреди разбора (005)."""
    assert isinstance(module.REPEATED_AT, int)
    assert 2 <= module.REPEATED_AT <= 5, (
        f"порог повтора {module.REPEATED_AT}: два — это совпадение, больше пяти — уже не ряд"
    )


def test_the_skill_and_the_record_name_each_other() -> None:
    """Навык разбора находки зовёт эту запись, а запись зовётся им.

    Механизм без процедуры остаётся числом, которое некому заполнить: роды
    называет человек в минуту разбора
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    skill = ROOT / ".claude" / "skills" / "close-a-finding" / "SKILL.md"
    said = skill.read_text(encoding="utf-8")
    assert "scripts/finding_kinds.py" in said, "навык не зовёт механизма родов"
    assert "finding-kinds.json" in said, "навык не называет, куда записывать род"


def test_the_walk_names_the_kinds(run_script) -> None:  # type: ignore[no-untyped-def]
    """Заход процессом называет роды и выходит нулём — исход прогоняется."""
    done = run_script("finding_kinds.py")
    assert done.code == module.EXIT_OK, done.err
    assert "родов" in done.out, done.out


def test_a_missing_record_is_the_third_outcome(tmp_path, run_script) -> None:  # type: ignore[no-untyped-def]
    """Объявления нет — отказ с адресом, а не «родов ноль» (075).

    «Родов ноль» прозвучало бы как «повторов нет», то есть отказ входа выдал бы
    себя за вердикт (045).
    """
    done = run_script("finding_kinds.py", "--kinds", str(tmp_path / "нет.json"))
    assert done.code == module.EXIT_BROKEN
    assert "взять неоткуда" in done.err, done.err
