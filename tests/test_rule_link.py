"""Ссылка на правило спрашивается у выгрузки, а не пишется по памяти.

ЗАМЕР, РАДИ КОТОРОГО ШАГ ЗАВЕДЁН (20–21.09.2026, #589): гейт `check_rule_links`
отверг ДЕВЯТЬ выдуманных слагов за смену — `155`, `146`, `126`, `050`, `058`,
`152`, `039`, `170` и `204`, — плюс полностью несуществующее
`104-a-refusal-names-the-way-out`. Номер окно помнило верно каждый раз, имя
файла — ни разу. Девятый, `204`, нашёлся внутри докстроки самого шага.

Цена не в пропущенной ошибке: гейт ловил ВСЕ. Цена в цикле — ссылка пишется в
пояснение, гейт зовётся предполётной в конце, и один промах стоит полного
повторного захода.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("rule_link.py")
gate = load_script("check_rule_links.py")

SLUGS = {"005": "hand-written-numbers-rot", "155": "a-template-you-dont-use-drifts"}


def test_a_link_is_built_from_the_export() -> None:
    """Ссылка собирается из выгрузки и совпадает с тем, что принимает гейт."""
    said = module.link("155", SLUGS)
    assert said == (
        "[155](https://github.com/ArtVsMark/Engineering-Incidents-Playbook"
        "/blob/main/rules/ru/155-a-template-you-dont-use-drifts.md)"
    ), said


def test_the_built_link_passes_the_gate_that_judges_links() -> None:
    """Напечатанное принимает ТОТ ЖЕ образец, которым гейт судит ссылки.

    Это и есть смысл шага: он не «похоже пишет», а отдаёт ровно ту форму,
    которую гейт признаёт. Разойдись они — шаг стал бы вторым источником
    правды о ссылках
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    said = module.link("005", SLUGS)
    found = gate.LINK_RE.search(said)
    assert found, f"гейт не узнаёт собственную форму ссылки: {said}"
    assert found["number"] == "005"
    assert found["slug"] == SLUGS["005"]


@pytest.mark.parametrize("written", ["5", "05", "005", "#5", " 5 "])
def test_a_number_is_read_the_way_people_write_it(written: str) -> None:
    """Номер принимается в любом привычном написании и приводится к трём знакам.

    Автор пишет «5», «05» и «#5» одинаково охотно, а в каталоге номер всегда
    трёхзначный. Отказ на «5» отправлял бы искать ошибку там, где её нет.
    """
    assert module.link(written, SLUGS).startswith("[005](")


def test_an_unknown_number_is_a_refusal_not_a_guess() -> None:
    """Номера нет в выгрузке — отказ с названным предметом, а не правдоподобие.

    Выдуманная ссылка опаснее отсутствующей: она выглядит верной и проходит
    глазами, а гейт отвергнет её уже после толчка (154).
    """
    with pytest.raises(LookupError):
        module.link("999", SLUGS)


def test_a_silent_catalogue_is_its_own_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каталог молчит — свой исход, а не «правила нет».

    Молчание канала говорит о сети, а не о нашем дереве. Выдать его за «такого
    правила нет» значило бы отправить автора искать несуществующую ошибку
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """

    def silent() -> dict[str, str]:
        raise module.catalogue.Silent("канал молчит")

    monkeypatch.setattr(module.check_rule_links, "known", silent)
    assert module.main(["005"]) == module.EXIT_SILENT


def test_a_broken_read_is_told_apart_from_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ чтения — третий исход, и он НЕ тот же, что молчание канала (039).

    Половина, которую забывают: без неё «выгрузка пуста» и «сети нет» пришли бы
    под одним кодом, и разбирать их автор стал бы одинаково.
    """

    def broken() -> dict[str, str]:
        raise module.check_rule_links.NotRun("выгрузка пуста")

    monkeypatch.setattr(module.check_rule_links, "known", broken)
    assert module.main(["005"]) == module.EXIT_BROKEN


def test_several_numbers_are_printed_at_once(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Несколько номеров печатаются одним заходом: фрагмент цитирует не одно."""
    monkeypatch.setattr(module.check_rule_links, "known", lambda: SLUGS)
    assert module.main(["005", "155"]) == module.EXIT_OK
    printed = capsys.readouterr().out.splitlines()
    assert len(printed) == 2, printed


def test_an_unknown_number_is_the_declared_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Исход «такого правила нет» прогоняется через заход, а не только изнутри.

    ОБЪЯВЛЕННЫЙ ИСХОД ПРОГОНЯЕТСЯ (039, 145): `EXIT_UNKNOWN` был назван в
    докстроке и проверен только на `link()` — то есть на половине пути. Поймал
    это `tests/test_outcomes_run.py`, и поймал верно: заход мог отдавать любой
    код, а проза обещала этот.
    """
    monkeypatch.setattr(module.check_rule_links, "known", lambda: SLUGS)
    assert module.main(["999"]) == module.EXIT_UNKNOWN


def test_a_known_number_is_the_ok_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вторая половина: известный номер даёт нулевой исход, а не тот же отказ."""
    monkeypatch.setattr(module.check_rule_links, "known", lambda: SLUGS)
    assert module.main(["155"]) == module.EXIT_OK
