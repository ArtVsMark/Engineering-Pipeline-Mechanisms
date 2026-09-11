"""Дрейф: внешний вход сдвинулся, дерево не менялось.

Проверяется не «механизм зовёт площадку», а три свойства, без которых
совещательный канал по расписанию превращается в шум:

* расхождение названо числами — «было X, стало Y», а не «устарело»;
* у каждой записи есть следующий шаг: запись без него — сообщение о погоде;
* источники независимы, и неспрошенный источник не выглядит как «всё сошлось».
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("drift.py")


def test_a_moved_export_contract_is_named_with_both_numbers() -> None:
    """Выгрузка каталога поднялась — сказано, до чего и с чего.

    Подъём контракта означает, что ответы стоит ПЕРЕЧИТАТЬ, а не только
    починить схему (157), и следующий шаг записи говорит именно это.
    """
    found = module.catalogue_moved({"contracts": {"export": "1.6"}}, {"answers_to": "1.5"})
    assert len(found) == 1
    assert "1.6" in found[0].said and "1.5" in found[0].said
    assert "перечитать" in found[0].next_step.lower()


def test_a_settled_catalogue_says_nothing() -> None:
    """Сошедшийся каталог записи не даёт: пустая запись учит пролистывать."""
    export = {"contracts": {"export": "1.5", "bindings": "1.2"}, "count": 2}
    mine = {"answers_to": "1.5", "schema": "1.2", "rules": {"001": {}, "002": {}}}
    assert module.catalogue_moved(export, mine) == []


def test_new_rules_in_the_catalogue_are_counted() -> None:
    """Правил в каталоге больше, чем наших ответов — это очередь разбора."""
    found = module.catalogue_moved({"count": 200}, {"rules": {"001": {}}})
    assert len(found) == 1
    assert "200" in found[0].said and "1" in found[0].said


def test_a_stale_snapshot_names_the_rules_it_shows_wrong() -> None:
    """Сводка семьи показывает механизм документом — правила названы поимённо.

    Замер 10.09.2026: снимок семичасовой давности показывал шесть правил
    документами, когда они уже держались гейтами, и разрез приоритета — наш
    собственный — назвал их долгом, которого нет.
    """
    where = {
        "consumers": [
            {
                "repo": "o/Engineering-Pipeline-Mechanisms",
                "holds": {"074": {"mechanism": "document"}},
            }
        ]
    }
    mine = {"rules": {"074": {"mechanism": "gate"}}}
    found = module.snapshot_is_stale(where, mine, "o/Engineering-Pipeline-Mechanisms")
    assert len(found) == 1
    assert "074" in found[0].said


def test_a_snapshot_that_agrees_is_not_a_drift() -> None:
    """Сводка показывает то же, что дерево — записи нет."""
    where = {
        "consumers": [
            {"repo": "o/Engineering-Pipeline-Mechanisms", "holds": {"074": {"mechanism": "gate"}}}
        ]
    }
    mine = {"rules": {"074": {"mechanism": "gate"}}}
    assert module.snapshot_is_stale(where, mine, "o/Engineering-Pipeline-Mechanisms") == []


def test_missing_from_the_family_is_said_out_loud() -> None:
    """Нас нет в сводке вовсе — это находка, а не пустой ответ (045)."""
    found = module.snapshot_is_stale(
        {"consumers": []}, {"rules": {}}, "o/Engineering-Pipeline-Mechanisms"
    )
    assert len(found) == 1
    assert "нет в сводке" in found[0].said


def test_a_silent_source_never_reads_as_settled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Источник не ответил — это сказано, а не превращено в «дрейфа нет».

    Молчание источника и сошедшееся состояние снаружи одинаковы, и разница
    здесь стоит целого канала: пропущенный молча источник делает совещательный
    прогон вежливым «выключен».
    """

    def broken(*_: Any, **__: Any) -> Any:
        raise module.NotRun("снимок не прочитан")

    monkeypatch.setattr(module, "fetch", broken)
    monkeypatch.setattr(module, "pinned_tag_moved", lambda *_: [])
    found, silent = module.look("o/r", "token", {"rules": {}})
    assert found == []
    assert silent == ["каталог", "сводка семьи", "вердикты по предложениям"]
    assert "Не спрошено" in module.render_body(found, silent)


def test_one_silent_source_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """Недоступный каталог не отменяет устаревшей сводки: источники независимы."""
    drift = module.Drift("family-snapshot", "разошлось", "починить")
    monkeypatch.setattr(module, "fetch", lambda url: {})
    monkeypatch.setattr(
        module, "catalogue_moved", lambda *_: (_ for _ in ()).throw(module.NotRun("нет"))
    )
    monkeypatch.setattr(module, "snapshot_is_stale", lambda *_: [drift])
    monkeypatch.setattr(module, "pinned_tag_moved", lambda *_: [])
    found, silent = module.look("o/r", "token", {})
    assert found == [drift]
    assert silent == ["каталог"]


def test_every_record_carries_its_next_step() -> None:
    """У записи есть следующий шаг: без него это сообщение о погоде (142)."""
    line = str(module.Drift("source", "было X, стало Y", "сделать Z"))
    assert "что делать" in line
    assert "сделать Z" in line


def test_an_empty_body_is_not_a_lie() -> None:
    """Пустое тело говорит «сошлись», а не молчит."""
    assert "сошлись" in module.render_body([])


# --- версии языка ------------------------------------------------------------

#: Мир на 10.09.2026: 3.14 вышла, 3.15 только пробная. Подделка держит ровно ту
#: форму, что у настоящего манифеста: версия и признак стабильности.
TODAY = [
    {"version": "3.13.15", "stable": True},
    {"version": "3.14.7", "stable": True},
    {"version": "3.15.0-rc.2", "stable": False},
]


def test_todays_matrix_is_not_a_drift() -> None:
    """Матрица гоняет стабильные, `test-next` — пробную: расхождения нет."""
    assert module.language_moved(TODAY, ["3.13", "3.14"], "3.15") == []


def test_a_released_branch_missing_from_the_matrix_is_named() -> None:
    """Ветка стала стабильной, а матрица её не гоняет — это дрейф.

    Ни одна наша правка не делает ветку стабильной: это расписание CPython, и
    приходит оно между нашими изменениями. Замер 10.09.2026: о выходе 3.14
    механизм не узнал — это сказал владелец.
    """
    found = module.language_moved(TODAY, ["3.13"], "3.15")
    assert [one.source for one in found] == ["python-stable"]
    assert "3.14" in found[0].said


def test_a_prerelease_that_grew_up_is_moved_not_kept() -> None:
    """Пробная ветка стала стабильной — `test-next` держит её зря."""
    grown = [{"version": "3.15.0", "stable": True}, {"version": "3.16.0-alpha.1", "stable": False}]
    found = module.language_moved(grown, ["3.15"], "3.15")
    assert [one.source for one in found] == ["python-next"]
    assert "уже стабильна" in found[0].said


def test_a_newer_prerelease_moves_the_next_job() -> None:
    """Появилась следующая пробная ветка — `test-next` отстал."""
    ahead = [
        {"version": "3.14.7", "stable": True},
        {"version": "3.15.0-rc.1", "stable": False},
        {"version": "3.16.0-alpha.1", "stable": False},
    ]
    found = module.language_moved(ahead, ["3.14"], "3.15")
    assert [one.source for one in found] == ["python-next"]
    assert "3.16" in found[0].said


def test_a_branch_the_platform_never_heard_of_is_a_drift() -> None:
    """Матрица называет ветку, которой площадка не знает — прогон её не поставит."""
    found = module.language_moved(TODAY, ["3.14", "3.99"], "3.15")
    assert "python-matrix" in [one.source for one in found]


def test_versions_are_ordered_by_number_not_by_string() -> None:
    """`3.9` младше `3.10`: по строке вышло бы наоборот, и «новейшая» соврала бы."""
    older = [{"version": "3.9.1", "stable": True}, {"version": "3.10.1", "stable": True}]
    stable, _ = module.minors(older)
    assert stable == ["3.9", "3.10"]


def test_an_empty_manifest_is_the_third_outcome() -> None:
    """Ни одной стабильной ветки — это поломка входа, а не «всё сошлось» (075)."""
    with pytest.raises(module.NotRun):
        module.language_moved([{"version": "3.15.0-rc.1", "stable": False}], ["3.14"], "")


def test_the_matrix_is_read_from_the_run_itself() -> None:
    """Версии берутся из `ci.yml`, а не из второго списка рядом.

    Второе место, где то же знание ведётся отдельно, разошлось бы с первым
    молча — и дрейф сравнивал бы мир со своей копией вчерашней матрицы (090).
    """
    matrix, ahead = module.declared_versions()
    assert matrix, "матрица не разобралась"
    assert all(part.count(".") == 1 for part in matrix), matrix
    assert ahead, "предрелизная ветка не разобралась"


def test_a_pin_without_a_subpath_is_still_a_pin() -> None:
    """Действие каталога подключают двумя формами, и обе — предмет счёта.

    `<repo>/.github/actions/<имя>@<тег>` подключает одно действие,
    `<repo>@<тег>` — действие из корня. Прежняя редакция искала подстроку
    `<repo>/` и вторую форму теряла молча: `rules-inbox.yml` выпадал из счёта, а
    совпадение тегов у обоих подключений это маскировало. Нашёл разбор на #119.
    """
    said = "\n".join(
        [
            f"      - uses: {module.CATALOGUE}/.github/actions/attribution@v1.2.0",
            f"      - uses: {module.CATALOGUE}@v1.3.0",
        ]
    )
    assert sorted(found.group("tag") for found in module.PINNED_RE.finditer(said)) == [
        "v1.2.0",
        "v1.3.0",
    ]


def test_a_pin_of_a_stranger_is_not_ours() -> None:
    """Чужое действие с похожим именем в счёт не идёт: предмет — наш каталог."""
    said = "      - uses: someone/Engineering-Incidents-Playbook-fork@v9.9.9"
    assert [found.group("tag") for found in module.PINNED_RE.finditer(said)] == []


def test_the_record_names_where_the_stale_pin_lives(monkeypatch: pytest.MonkeyPatch) -> None:
    """В записи назван файл с отставшим подключением, а не только тег.

    «Подключено v1.2.0» без адреса заставляет искать его по всему дереву — то
    есть делать руками работу, которую механизм уже сделал.
    """
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"tag_name": "v9.9.9"})
    found = module.pinned_tag_moved("o/r", "token")
    assert len(found) == 1
    assert ".yml" in found[0].said, found[0].said


def test_each_stale_tag_is_named_with_its_own_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Отставший тег назван вместе со СВОИМИ файлами, а не рядом с чужими (находка #122).

    Два плоских списка — теги и все файлы разом — при разных тегах в разных
    прогонах не говорят, что где; а править надо именно тот файл, где стоит
    именно тот тег.
    """
    catalogue = module.CATALOGUE
    (tmp_path / "one.yml").write_text(f"uses: {catalogue}/.github/actions/a@v1.0.0\n", "utf-8")
    (tmp_path / "two.yml").write_text(f"uses: {catalogue}/.github/actions/b@v1.1.0\n", "utf-8")
    monkeypatch.setattr(module.paths, "WORKFLOWS", tmp_path)
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"tag_name": "v9.9.9"})
    said = module.pinned_tag_moved("o/r", "token")[0].said
    assert "v1.0.0 — one.yml" in said, said
    assert "v1.1.0 — two.yml" in said, said


# --- вердикты по предложениям ------------------------------------------------
#
# ФОРМА ОТВЕТА ВЗЯТА У КАТАЛОГА, А НЕ ПРИДУМАНА. Прежде подделки здесь были
# собраны по разумению окна: вердикты под ключом `proposals`, номер в поле
# `number`. Каталог отдаёт `verdicts` и `rule`, и разбор молчал — а тест
# молчал вместе с ним, потому что повторял ту же ошибку (170). Цена: к
# 11.09.2026 каталог принял все четыре наших предложения, и ни об одном
# источник не сказал. Снятый ответ лежит в
# `tests/fixtures/catalogue-proposals.shape.json`.

MINE = {"proposals": [{"slug": "a-thing-broke", "claim": "…", "incident": "…", "trail": "x.py"}]}
CAPTURED = ROOT / "tests" / "fixtures" / "catalogue-proposals.shape.json"


def captured() -> dict[str, Any]:
    """Снятый ответ каталога — то, с чем сверяются подделки."""
    return dict(json.loads(CAPTURED.read_text(encoding="utf-8")))


def answer(verdict: dict[str, Any], key: str = "o/r:a-thing-broke") -> dict[str, Any]:
    """Ответ каталога той же формы, что и снятый: раздел `verdicts`."""
    return {"schema": captured()["schema"], module.VERDICTS: {key: verdict}}


def test_the_shape_of_the_answer_is_taken_from_the_catalogue() -> None:
    """Подделки собраны по СНЯТОМУ ответу, а не по памяти окна (170).

    Без этой сверки набор доказывает согласованность кода с представлением
    окна о каталоге, а не с каталогом. Ровно так четыре вердикта и прошли мимо.
    """
    real = captured()
    assert module.VERDICTS in real, f"снятый ответ не несёт раздела «{module.VERDICTS}»"
    one = next(iter(real[module.VERDICTS].values()))
    assert "rule" in one, "номер в снятом ответе назван не полем rule — разбор смотрит не туда"
    assert "status" in one, "статус в снятом ответе назван иначе"


def test_an_admitted_proposal_stops_being_a_proposal() -> None:
    """Каталог принял предложение — оно перестало быть предложением.

    У принятого появился НОМЕР, и отвечают по нему теперь в `bindings.json`, а
    не в очереди на приём. Вердикт выносит каталог у себя и по своему
    расписанию: ни одна наша правка этого не делает, и события не приходит —
    ровно предмет дрейфа (080).
    """
    found = module.proposals_answered(answer({"status": "admitted", "rule": "196"}), MINE, "o/r")
    assert len(found) == 1
    assert "196" in found[0].said
    assert "bindings.json" in found[0].next_step


def test_a_rejected_proposal_names_the_reason() -> None:
    """Отвергнутое несёт причину каталога, а не только слово «отвергнуто» (154)."""
    said = {"status": "rejected", "why": "уже есть 042"}
    found = module.proposals_answered(answer(said), MINE, "o/r")
    assert len(found) == 1
    assert "уже есть 042" in found[0].said


def test_a_merged_proposal_points_at_the_existing_rule() -> None:
    """Третий статус каталога — «свёрнуто с существующим» — разбор знает.

    Прежде его не знал никто: незнакомый статус молча уходил в «вердикта нет»,
    и предложение оставалось в очереди на приём навсегда.
    """
    said = {"status": "merged-into", "rule": "042", "why": "предмет тот же"}
    found = module.proposals_answered(answer(said), MINE, "o/r")
    assert len(found) == 1 and "042" in found[0].said
    assert "предмет тот же" in found[0].said


def test_an_unknown_status_is_named_not_swallowed() -> None:
    """Статус, которого разбор не знает, называется, а не молчит (045)."""
    found = module.proposals_answered(answer({"status": "deferred"}), MINE, "o/r")
    assert len(found) == 1
    assert "deferred" in found[0].said and "не знает" in found[0].said


def test_an_unrecognised_answer_is_a_record_not_silence() -> None:
    """Ответ без раздела вердиктов — запись «форма не узнана», а не «сошлось».

    «Ответа нет» и «ответ в незнакомом виде» снаружи одинаковы и значат
    разное: первое штатно, второе означает, что источник ослеп. Ровно это и
    случилось, когда разбор искал раздел «proposals».
    """
    found = module.proposals_answered({"proposals": {}}, MINE, "o/r")
    assert len(found) == 1
    assert "форма не узнана" in found[0].said


def test_a_proposal_without_a_verdict_is_not_a_drift() -> None:
    """Каталог ещё не ответил — это ожидание, а не расхождение."""
    assert module.proposals_answered({module.VERDICTS: {}}, MINE, "o/r") == []


def test_a_verdict_for_another_project_is_not_ours() -> None:
    """Ключ несёт владельца и репозиторий: чужой вердикт мимо нас."""
    said = answer({"status": "admitted", "rule": "196"}, key="other/repo:a-thing-broke")
    assert module.proposals_answered(said, MINE, "o/r") == []


def test_a_non_numeric_matrix_entry_does_not_fell_the_pass() -> None:
    """Опечатка в матрице не роняет весь дрейф, а уходит в конец.

    Матрица читается из `ci.yml` — правимого руками файла. Запись вроде
    `3.13-dev` давала `ValueError`, и падал ВЕСЬ заход, включая источники, к
    языку отношения не имеющие: источники затем и разделены, чтобы отказ одного
    не уносил остальные. Нашёл внешний взгляд на #121.
    """
    assert module.order("3.13-dev") == ()
    assert module.order("pypy3.10") == ()
    assert module.order("3.9") < module.order("3.10")
    assert sorted(["3.13-dev", "3.10", "3.9"], key=module.order) == ["3.13-dev", "3.9", "3.10"]


# --- номера контрактов: их шесть, и двигаются они порознь ---------------------


def test_every_contract_of_ours_is_compared(tmp_path: Path) -> None:
    """Сверяются все наши номера, а не один.

    Каталог отдаёт блок `contracts` со всеми форматами разом, и двигаются они
    ПОРОЗНЬ: подъём выгрузки не означает подъёма формы ответа. Пока сверялась
    одна `bindings`, отставание `proposals` жило незамеченным — файл валиден,
    номер старый, и обе стороны видят своё зелёное. Замер 11.09.2026: каталог
    поднял шесть контрактов разом, у нас разошлись два.
    """
    (tmp_path / ".rules").mkdir()
    (tmp_path / ".rules" / "proposals.json").write_text('{"schema": "1.0"}', encoding="utf-8")
    (tmp_path / ".rules" / "showcase.json").write_text('{"schema": "1.1"}', encoding="utf-8")
    said = module.ours_by_contract({"schema": "1.3"}, tmp_path)
    assert ("bindings", ".rules/bindings.json", "1.3") in said
    assert ("proposals", ".rules/proposals.json", "1.0") in said
    assert ("showcase", ".rules/showcase.json", "1.1") in said


def test_a_lagging_contract_is_a_drift(tmp_path: Path) -> None:
    """Отставший номер — сдвиг внешнего входа, а не мелочь оформления.

    Подъём контракта означает ПЕРЕЧИТАТЬ ответы, а не только починить число
    (157). Поэтому находка называет файл и говорит о перечитывании.
    """
    (tmp_path / ".rules").mkdir()
    (tmp_path / ".rules" / "proposals.json").write_text('{"schema": "1.0"}', encoding="utf-8")
    export = {"contracts": {"export": "1.7", "bindings": "1.3", "proposals": "1.1"}, "count": 1}
    mine = {"schema": "1.3", "answers_to": "1.7", "rules": {"001": {}}}
    was = os.getcwd()
    os.chdir(tmp_path)
    try:
        found = module.catalogue_moved(export, mine)
    finally:
        os.chdir(was)
    names = {one.source for one in found}
    assert "proposals-schema" in names, names
    assert "bindings-schema" not in names


def test_foreign_contracts_are_not_ours(tmp_path: Path) -> None:
    """`consumers` и `where` — файлы САМОГО каталога, и сверять нам в них нечего.

    Требовать от себя чужой номер значило бы краснеть на том, чего у нас нет
    и быть не должно (051).
    """
    assert {name for name, _ in module.OUR_CONTRACTS} == {"bindings", "proposals", "showcase"}


def test_an_empty_queue_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Предложений нет — вердиктов по ним быть не может, и форма чужого ответа не предмет.

    Пустая очередь объявлена законным состоянием в самом `.rules/proposals.json`.
    Без этой границы проект, которому нечего предлагать, получал бы запись
    «форма не узнана» на каждом ночном заходе — то есть красное на здоровом (051).
    """
    assert module.proposals_answered({}, {"proposals": []}, "o/r") == []


def test_we_are_recognised_by_the_full_address_not_by_a_name_tail() -> None:
    """Себя узнаём по полному адресу владелец/имя (находка #119).

    Сверка по хвосту имени принимает за нас форк или одноимённый репозиторий
    другого владельца: разрез приоритета считался бы по ЧУЖОЙ сводке. Имя без
    владельца идентификатором не является (194).
    """
    mine = {"rules": {"001": {"mechanism": "gate"}}}
    stranger = {"consumers": [{"repo": "someone/Engineering-Pipeline-Mechanisms", "holds": {}}]}
    found = module.snapshot_is_stale(stranger, mine, "ArtVsMark/Engineering-Pipeline-Mechanisms")
    assert len(found) == 1 and "нас нет в сводке" in found[0].said, found

    ours = {"consumers": [{"repo": "ArtVsMark/Engineering-Pipeline-Mechanisms", "holds": {}}]}
    found = module.snapshot_is_stale(ours, mine, "ArtVsMark/Engineering-Pipeline-Mechanisms")
    assert len(found) == 1 and "документами" in found[0].said, found


def test_a_verdict_without_a_status_is_named_not_skipped() -> None:
    """Вердикт есть, а статуса в нём нет — это запись, а не тишина (находка #179).

    Пропустить такую значит объявить отвеченное неотвеченным и держать
    предложение в очереди на приём навсегда (045).
    """
    found = module.proposals_answered(answer({"rule": "196"}), MINE, "o/r")
    assert len(found) == 1
    assert "«status»" in found[0].said and "a-thing-broke" in found[0].said


def test_a_verdict_that_is_not_a_mapping_is_named_too() -> None:
    """Ответ пришёл не словарём — тоже «прочитать нечем», а не «ответа нет»."""
    found = module.proposals_answered(answer("admitted"), MINE, "o/r")  # type: ignore[arg-type]
    assert len(found) == 1 and "не словарём" in found[0].said
