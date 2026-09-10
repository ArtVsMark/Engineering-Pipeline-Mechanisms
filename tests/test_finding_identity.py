"""Находка, пересказанная другими словами, — та же находка.

Отпечаток берётся от заголовка, а заголовок ревьюер на новом заходе
пересказывает: «вторая точка вызова (scripts/ci_complete.py:341)» и «точка
вызова scripts/ci_complete.py:341» — одна беда. Реестр складывал их двумя
записями. Замер 10.09.2026 по #23: четыре записи об одном и том же на #149 и
две на #148.

Признаков тождества два, и они разной силы:

* совпавшие АДРЕСА — точный: место в дереве пересказ не меняет. Держится он
  тем, что формат адреса требуется от ревьюера подсказкой;
* сходство слов — сеть под ним, с порогом в пустоте между замеренными
  значениями: 0.960 у настоящего дубля, 0.400 у ближайшей пары РАЗНЫХ находок,
  и ни одной пары между ними. Сравниваются СЛОВА: посимвольное сходство рушится
  от перестановки, и «не может измениться» против «измениться не может» давало
  0.827 — ниже порога, хотя это одна фраза.

Цена ошибки здесь несимметрична: лишняя запись стоит строки в реестре, а
слипшиеся находки — потерянной находки. Поэтому проверяется и то, что механизм
НЕ склеивает.
"""

from __future__ import annotations

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


def test_addresses_are_read_in_one_shape() -> None:
    """Адрес читается одним написанием — и из скобок, и без них."""
    assert module.addresses(FIRST) == frozenset(
        {"scripts/ci_complete.py:76-93", "scripts/ci_complete.py:341"}
    )
    assert module.addresses(FIRST) == module.addresses(SECOND)


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


def test_a_finding_without_an_address_falls_back_to_words() -> None:
    """Адреса нет вовсе — узнать находку больше не по чему, кроме слов."""
    bare = "значок показывает число, которое не может измениться"
    retold = "значок показывает число, которое измениться не может"
    assert module.addresses(bare) == frozenset()
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
