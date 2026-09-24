"""Находка, пересказанная другими словами, — та же находка.

Отпечаток берётся от заголовка, а заголовок ревьюер на новом заходе
пересказывает: «вторая точка вызова (scripts/ci_complete.py:341)» и «точка
вызова scripts/ci_complete.py:341» — одна беда. Реестр складывал их двумя
записями. Замер 10.09.2026 по #23: четыре записи об одном и том же на #149 и
две на #148.

Признак тождества один — сходство слов, с порогом в пустоте между
замеренными значениями: 0.960 у настоящего дубля, 0.400 у ближайшей пары
РАЗНЫХ находок, и ни одной пары между ними. Сравниваются СЛОВА: посимвольное
сходство рушится от перестановки, и «не может измениться» против «измениться
не может» давало 0.827 — ниже порога, хотя это одна фраза.

Совпавший АДРЕС был вторым признаком и решал сам, при любых словах, — и снят:
у одного места бывает и новая беда, и под адресом прежней она уходила вместе
с её снятием (`7b62e1a`). Замер 24.09.2026: из 18 пар равного адреса ниже
порога слов 17 пересказов от 0.056 и одна пара разных бед с 0.057 — порога
между ними нет.

Цена ошибки здесь несимметрична: лишняя запись стоит строки в реестре, а
слипшиеся находки — потерянной находки. Поэтому проверяется и то, что механизм
НЕ склеивает.
"""

from __future__ import annotations

from typing import Final

from tests.conftest import load_script

module = load_script("review_findings.py")
findings = load_script("findings.py")

#: Две живые записи по #148 — дословно из реестра. Различие в середине.
FIRST = (
    "still_coming()` доверяет `status` из `own_jobs()`, не проверяя `conclusion`, "
    "хотя ровно этот класс рассинхрона уже измерен для check-runs в `pending()` "
    "(scripts/ci_complete.py:76-93) — если Jobs API ведёт себя так же, вторая точка "
    "вызова (scripts/ci_complete.py:341) продержит `waiting=True` до тайм-аута вместо отказа"
)
SECOND = (
    "still_coming()` доверяет `status` из `own_jobs()`, не проверяя `conclusion`, "
    "хотя ровно этот класс рассинхрона уже измерен для check-runs в `pending()` "
    "(scripts/ci_complete.py:76-93) — если Jobs API ведёт себя так же, точка вызова "
    "scripts/ci_complete.py:341 продержит `waiting=True` до тайм-аута вместо отказа"
)


#: Две РАЗНЫЕ беды по одному адресу из разных заходов на #657 — дословно.
#: Сходство слов 0.057: адрес совпал, предметы — нет.
AT_ONE_PLACE: Final = (
    "scripts/runs_series.py:181 — дequoting в `bare_of` рвёт квотированный джойнер "
    '(`echo "a | b"` → две команды вместо одной)',
    "`bare_of` режет по `#` внутри слова без пробела перед ним, а `shlex`-комментарий "
    "шире, чем комментарий POSIX-оболочки — scripts/runs_series.py:181",
)


def test_an_equal_address_is_not_an_identity() -> None:
    """Совпавший адрес при других словах — две находки, а не одна (`7b62e1a`).

    Прежде адрес решал сам, и новая беда по месту прежней ложилась на её
    запись, а снятие прежней уносило обе. Живая пара — две разные беды одной
    строки из двух заходов на #657.
    """
    assert module.same_finding(*AT_ONE_PLACE) is False
    entries = {"aaaaaaa": findings.Entry(657, "риск", AT_ONE_PLACE[0])}
    assert module.existing_mark(entries, 657, AT_ONE_PLACE[1]) is None


def test_a_retold_finding_is_the_same_one() -> None:
    """Живой случай: тот же дефект, пересказанный, — одна находка."""
    assert module.same_finding(FIRST, SECOND) is True


def test_two_different_findings_do_not_merge() -> None:
    """Разные находки одного изменения не склеиваются.

    Ближайшая пара разных находок дала сходство 0.514 — вдвое ниже порога, и
    адреса у них разные.
    """
    other = (
        "порядок очереди читает `.pipeline.yml` дважды за заход "
        "(scripts/automerge.py:88) — второе чтение может застать другой файл"
    )
    assert module.same_finding(FIRST, other) is False


def test_the_same_trouble_in_another_change_is_another_finding() -> None:
    """Та же беда в другом изменении — другая находка: снимают их порознь."""
    entries = {"aaaaaaa": findings.Entry(148, "риск", FIRST)}
    assert module.existing_mark(entries, 148, SECOND) == "aaaaaaa"
    assert module.existing_mark(entries, 149, SECOND) is None


def test_a_finding_without_an_address_is_known_by_words_too() -> None:
    """Адреса нет вовсе — находку узнают те же слова, что и с адресом."""
    bare = "значок показывает число, которое не может измениться"
    retold = "значок показывает число, которое измениться не может"
    assert module.same_finding(bare, retold) is True


def test_the_kept_fingerprint_survives_the_retelling() -> None:
    """Отпечаток сохраняется прежний — по нему находку уже могли снять.

    Снятие едет строкой `Разобрано: <отпечаток>` в теле изменения. Смени
    отпечаток при пересказе — и снятие, написанное автором починки, промахнётся
    мимо записи.
    """
    entries = {"aaaaaaa": findings.Entry(148, "риск", FIRST)}
    mark = module.existing_mark(entries, 148, SECOND)
    assert mark == "aaaaaaa"
    assert mark != module.fingerprint(SECOND)
