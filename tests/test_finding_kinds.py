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
#: Что похоже на адрес: путь с косой чертой либо имя файла с расширением, а
#: также номер правила или ответа. ЖИВОСТЬ ПРОВЕРЯЕТСЯ ОТНОШЕНИЕМ — существует
#: ли такой путь в дереве, — а не перечнем каталогов: перечень пропускал
#: корневые файлы, и встреча, названная `pyproject.toml`, объявлялась безадресной
#: (18.09.2026)
#: ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
LOOKS_LIKE_A_PATH: Final = re.compile(r"[\w.-]+(?:/[\w./-]+)*\.[a-z]{2,5}\b|[\w.-]+/[\w./-]+")
#: Номер правила каталога или нашего ответа — адрес не в дереве, а в договоре.
A_NUMBER: Final = re.compile(r"(?:правил|ответ)\w*\s+\d{3}")


def addressed(said: str) -> bool:
    """Назван ли в строке ЖИВОЙ адрес — путь дерева либо номер правила.

    Путь проверяется существованием, а не написанием: список каталогов угадал бы
    предмет и уже угадал — корневые файлы в него не попадали.
    """
    if A_NUMBER.search(said):
        return True
    return any((ROOT / one.split("::")[0]).exists() for one in LOOKS_LIKE_A_PATH.findall(said))


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
    """Встречи перечислены ПОШТУЧНО: число рассохлось бы первой же находкой (005).

    Штука — отпечаток находки внешнего взгляда либо запись «окно: <адрес>» о
    роде, пойманном собственным откатом до толчка. Второй формы до 18.09.2026
    не было, и это был не пробел оформления: род, дважды пойманный в окне,
    считался встреченным ноль раз и порога не достигал никогда.

    АДРЕС У ВСТРЕЧИ В ОКНЕ ОБЯЗАТЕЛЕН по той же причине, по какой обязателен у
    пометки «породил»: без него «поймали такое же» неотличимо от впечатления, а
    проверить нечем — коммита с находкой не существует.
    """
    met = kinds()[name].get("встречен")
    assert isinstance(met, list) and met, f"{name}: встречи не перечислены поштучно"
    wrong: list[str] = []
    for one in (str(each) for each in met):
        if FINGERPRINT.match(one):
            continue
        if one.startswith(module.IN_WINDOW):
            if not addressed(one[len(module.IN_WINDOW) :]):
                wrong.append(f"«{one}» — встреча в окне без адреса")
            continue
        wrong.append(f"«{one}» — ни отпечаток, ни «{module.IN_WINDOW}<адрес>»")
    assert not wrong, f"{name}: {'; '.join(wrong)}"


def test_the_word_no_is_matched_whole_not_by_prefix() -> None:
    """«Нет» узнаётся целым словом: приставка увела бы род в долг по первой букве.

    `startswith("нет")` читает «нетронутый», «нетривиально» и «нет-нет» как
    объявление отсутствия механизма — то есть род с ЖИВЫМ механизмом попал бы в
    долг, а долг перестал бы быть долгом
    ([141](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/141-a-marker-is-matched-whole-not-by-prefix.md)).
    """
    говорит_нет = ("нет", "НЕТ — причина", "нет, потому что", " нет — причина ")
    не_говорит = ("нетривиально держится разбором", "нетронутый гейт", "держится гейтом", "")
    wrong = [one for one in говорит_нет if not module.said_no(one)]
    assert not wrong, f"объявление отсутствия не опознано: {wrong}"
    wrong = [one for one in не_говорит if module.said_no(one)]
    assert not wrong, f"живой механизм прочитан как «нет» по приставке: {wrong}"


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_the_split_of_origins_adds_up(name: str) -> None:
    """Состав встреч печатается сложением, а не вторым счётом.

    «Взгляд» и «окно» — разные совокупности, и читателю долга видно, дошёл ли
    род до общей ветки. Второй список того же разошёлся бы с первым молча
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)),
    поэтому происхождение живёт в самой записи встречи, а состав вычисляется.
    """
    body = kinds()[name]
    seen, caught = module.origins(body)
    met = body.get("встречен")
    assert seen + caught == len(met if isinstance(met, list) else []), (
        f"{name}: состав встреч не сходится с их числом — счёт разошёлся с записью"
    )


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_kind_says_what_holds_it_or_why_nothing_does(name: str) -> None:
    """Род держится механизмом либо называет причину, почему не держится (154)."""
    held = str(kinds()[name].get("закрыт", "")).strip()
    assert held, f"{name}: не сказано, чем род закрыт"
    if module.said_no(held):
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
    mute = [str(one) for one in born if not addressed(str(one))]
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
        assert module.said_no(str(said[name].get("закрыт", "")))


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
