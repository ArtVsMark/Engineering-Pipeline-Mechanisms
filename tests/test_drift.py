"""Дрейф: внешний вход сдвинулся, дерево не менялось.

Проверяется не «механизм зовёт площадку», а три свойства, без которых
совещательный канал по расписанию превращается в шум:

* расхождение названо числами — «было X, стало Y», а не «устарело»;
* у каждой записи есть следующий шаг: запись без него — сообщение о погоде;
* источники независимы, и неспрошенный источник не выглядит как «всё сошлось».
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

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


def test_a_moved_summary_form_is_a_drift() -> None:
    """Сводка сменила форму — разрез об этом узнаёт, а не считает по прежней.

    ЗАМЕР, ИЗ КОТОРОГО ВЫРОСЛА СВЕРКА: сводка ушла на 1.3 восьмого сентября,
    `family.READS_SCHEMA` остался под 1.2, и расхождение прожило девять дней.
    Считалось оно всё это время — `build_facts` клал его в факты ключом
    `schema_agrees`, — и не печаталось нигде. Из сверки контрактов `where` был
    исключён комментарием «сверять нам в них нечего»: файл чужой, но ЧИТАТЕЛЬ
    наш, и номер у него свой (044).
    """
    found = module.reader_is_behind({"schema": "9.9"})
    assert len(found) == 1
    assert "9.9" in found[0].said
    assert module.family.READS_SCHEMA in found[0].said
    assert "157" in found[0].next_step


def test_a_summary_of_our_own_form_is_not_a_drift() -> None:
    """Форма та же — записи нет: дрейф называет сдвиг, а не состояние."""
    assert module.reader_is_behind({"schema": module.family.READS_SCHEMA}) == []


def test_a_summary_without_a_form_is_not_read_as_zero() -> None:
    """Номера нет — сверять нечего, и это не «ноль».

    Ключа нет значит «не прочитали», а не «версия нулевая» (045). То же
    соглашение действует у самого каталога по всей выгрузке.
    """
    assert module.reader_is_behind({}) == []
    assert module.reader_is_behind({"schema": ""}) == []


def slice_with(findings: Any) -> dict[str, Any]:
    """Сводка, где наш срез несёт заданные находки каталога."""
    return {
        "consumers": [
            {
                "repo": "o/Engineering-Pipeline-Mechanisms",
                "holds": {},
                "findings": findings,
            }
        ]
    }


def test_a_catalogue_finding_about_us_reaches_the_registry() -> None:
    """Находка каталога о НАШЕМ ответе доезжает до того, кто её чинит.

    Канал был построен той стороной и не читался этой: ключ `findings` завёлся
    в форме сводки 1.2 восьмого сентября ровно ради адресата (142), и девять
    дней его не читала ни одна строка кода.
    """
    found = module.catalogue_found(
        slice_with(["ответ по схеме 1.3, у контракта 1.4"]), "o/Engineering-Pipeline-Mechanisms"
    )
    assert len(found) == 1
    assert "1.4" in found[0].said
    assert "bindings.json" in found[0].next_step, "починка живёт у нас, а не у каталога (086)"


def test_a_finding_of_many_lines_stays_one_record() -> None:
    """Перенос строки из чужого текста не разрывает запись на две.

    Чужой текст едет ЦИТАТОЙ: тело задачи разбирается построчно, и находка с
    переносом дала бы обрывок, который разбор прочитал бы отдельной записью
    (085).
    """
    found = module.catalogue_found(
        slice_with(["первая строка\nвторая строка\n\nтретья"]), "o/Engineering-Pipeline-Mechanisms"
    )
    assert len(found) == 1
    assert "\n" not in str(found[0])
    assert "третья" in found[0].said, "хвост находки не потерян"


def test_a_long_finding_says_how_much_was_cut() -> None:
    """Длинная находка обрезается ВСЛУХ: урезанное молча выглядит полным (016)."""
    found = module.catalogue_found(slice_with(["я" * 900]), "o/Engineering-Pipeline-Mechanisms")
    assert len(found) == 1
    assert "обрезано" in found[0].said and "900" in found[0].said


def test_no_findings_is_a_state_not_a_record() -> None:
    """Каталог не нашёл у нас ничего — записи нет, и это состояние (027).

    `null` каталог ставит себе сам: находок о себе у него не бывает. Пустой
    список и отсутствие ключа значат то же самое — «не нашли».
    """
    empty: tuple[Any, ...] = ([], None)
    for said in empty:
        assert module.catalogue_found(slice_with(said), "o/Engineering-Pipeline-Mechanisms") == []
    assert (
        module.catalogue_found(
            {"consumers": [{"repo": "o/Engineering-Pipeline-Mechanisms"}]},
            "o/Engineering-Pipeline-Mechanisms",
        )
        == []
    )


def test_a_blank_finding_is_not_a_record() -> None:
    """Пустая строка в списке — не находка: запись без предмета хуже молчания."""
    assert (
        module.catalogue_found(slice_with(["", "   "]), "o/Engineering-Pipeline-Mechanisms") == []
    )


def test_missing_from_the_summary_is_said_once() -> None:
    """Нас нет в сводке — говорит об этом ОДИН читатель, а не оба.

    Второй раз то же самое было бы вторым счётом одного (022): находку «нас нет
    в сводке вовсе» ставит `snapshot_is_stale`, и находки каталога о нашем
    ответе её не повторяют.
    """
    assert module.catalogue_found({"consumers": []}, "o/Engineering-Pipeline-Mechanisms") == []


def test_the_slice_is_found_by_the_full_address() -> None:
    """Себя узнаём по полному адресу, а не по хвосту имени (194, находка #119).

    Поиск теперь один на двоих читателей, и проверяется он на обоих: копия
    разошлась бы с оригиналом молча (090).
    """
    stranger = {"consumers": [{"repo": "чужой/Engineering-Pipeline-Mechanisms", "findings": ["х"]}]}
    assert module.our_slice(stranger, "o/Engineering-Pipeline-Mechanisms") is None
    assert module.catalogue_found(stranger, "o/Engineering-Pipeline-Mechanisms") == []


def test_all_questions_to_the_summary_read_one_answer() -> None:
    """Сводка читается ОДИН раз на все три вопроса, а не по разу на каждый.

    Второе чтение того же адреса могло бы прийти уже другим, и вердикты
    разошлись бы молча (022) — ровно ту поломку внешний взгляд нашёл в
    `build_facts` на #240. Здесь это держится формой: `family_summary`
    принимает уже прочитанное, а не адрес.

    Вопроса три, и слить их нельзя: форму чиним правкой кода, находку каталога
    — правкой ответа, отставший снимок не чиним вовсе (ждём прогона каталога).
    Адресат у каждого свой (142).
    """
    names = list(inspect.signature(module.family_summary).parameters)
    assert names[0] == "where", "сводка обязана приходить прочитанной, а не адресом"
    where = {
        "schema": "9.9",
        "consumers": [
            {
                "repo": "o/Engineering-Pipeline-Mechanisms",
                "holds": {"074": {"mechanism": "document"}},
                "findings": ["ответ построен на выгрузке 1.5, у нас 1.7"],
            }
        ],
    }
    mine = {"rules": {"074": {"mechanism": "gate"}}}
    found = module.family_summary(where, mine, "o/Engineering-Pipeline-Mechanisms")
    kinds_found = {record.source for record in found}
    assert kinds_found == {"family-schema", "catalogue-finding", "family-snapshot"}, (
        f"все три вопроса задаются по одному чтению, и вердикты у них разные: {kinds_found}"
    )


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
    # Источник версий чужих действий читает ДЕРЕВО, а не сеть: `broken` его не
    # останавливает, и настоящее расхождение в прогонах проекта сделало бы этот
    # прогон красным по чужому поводу. Предмет здесь — молчание источников.
    monkeypatch.setattr(module, "actions_disagree", lambda *a, **k: [])
    # Источник «выпуск против дерева» тоже читает дерево и историю, а не
    # сеть: отравленный транспорт его не останавливает, а настоящее
    # отставание выпуска сделало бы этот прогон красным по чужому поводу.
    monkeypatch.setattr(module, "release_behind_tree", lambda *a, **k: [])
    # Проба против выпуска — того же рода: читает дерево и историю. Её
    # отставание наступит при ПЕРВОМ ЖЕ выпуске, и без подделки этот прогон
    # покраснел бы по поводу, к молчанию источников отношения не имеющему.
    # Нашёл внешний взгляд на #574.
    monkeypatch.setattr(module, "probe_behind_release", lambda *a, **k: [])
    # Источник защиты ветки ходит к площадке своим запросом, а не через
    # `fetch`: в подделке его гасят отдельно, иначе проверка молчания одних
    # источников пошла бы в сеть за другим.
    monkeypatch.setattr(module, "protection_moved", lambda *a, **k: [])
    # Выпуски чужих действий тоже ходят к площадке своим запросом — гасятся
    # так же, по той же причине.
    monkeypatch.setattr(module, "actions_behind", lambda *a, **k: [])
    # Пометки закреплений и предупреждения площадки — того же рода: свой
    # запрос к площадке, гасятся так же (#665).
    monkeypatch.setattr(module, "pin_mislabelled", lambda *a, **k: [])
    monkeypatch.setattr(module, "platform_warnings", lambda *a, **k: [])
    found, silent = module.look("o/r", "token", {"rules": {}})
    assert found == []
    assert silent == [
        "каталог",
        "сводка семьи",
        "вердикты по предложениям",
        "набор вопросов витрины",
    ]
    assert "Не спрошено" in module.render_body(found, silent)


def test_one_silent_source_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """Недоступный каталог не отменяет устаревшей сводки: источники независимы.

    ПОДДЕЛЫВАЮТСЯ ВСЕ ИСТОЧНИКИ, А НЕ ТЕ, У КОГО СЕГОДНЯ ЕСТЬ ПРЕДМЕТ. Разбор
    вердиктов по предложениям здесь не подделывался — и тест проходил ровно
    потому, что очередь предложений была ПУСТА: источник молчал не по замыслу
    теста, а от отсутствия предмета. Первое же записанное предложение (17.09.2026)
    это вскрыло, покрасив тест, не имеющий к предложениям отношения. Зелёное,
    державшееся на пустоте соседнего файла, — то же вырожденное зелёное, что
    ловит
    [075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md).
    """
    drift = module.Drift("family-snapshot", "разошлось", "починить")

    def poisoned(*_: object, **__: object) -> None:
        raise AssertionError("источник пошёл в сеть: он не подделан")

    # ТРАНСПОРТ ОТРАВЛЕН, И ЭТО ГЛАВНОЕ В ТЕСТЕ. Подделки ниже перечислены
    # руками, а рукописный список отстаёт от механизма молча: к 17.09.2026 в
    # нём не хватало ДВУХ источников — разбора вердиктов по предложениям и
    # версий языка, — и второй ходил из набора в сеть по-настоящему. Проверять
    # полноту списка счётом бесполезно (счёт сходится случайно; это назвал
    # внешний взгляд на #428). Поэтому полноту держит не список, а отравленный
    # транспорт: источник, о котором здесь забыли, упрётся в него и скажет об
    # этом сам — молчаливого зелёного у него не остаётся
    # ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    monkeypatch.setattr(module.ghrest, "request", poisoned)
    monkeypatch.setattr(module.ghrest, "raw_text", poisoned)
    monkeypatch.setattr(module, "fetch", lambda url: {})
    monkeypatch.setattr(
        module, "catalogue_moved", lambda *_: (_ for _ in ()).throw(module.NotRun("нет"))
    )
    monkeypatch.setattr(module, "snapshot_is_stale", lambda *_: [drift])
    monkeypatch.setattr(module, "pinned_tag_moved", lambda *_: [])
    monkeypatch.setattr(module, "protection_moved", lambda *a, **k: [])
    monkeypatch.setattr(module, "proposals_answered", lambda *a, **k: [])
    # ВЕРСИИ ЯЗЫКА ХОДИЛИ В СЕТЬ, И ПЕРВАЯ ПОЧИНКА ЭТОГО НЕ ЗАКРЫЛА. Подделан
    # был `language_moved`, а сеть дёргает `manifest(...)`: он стоит АРГУМЕНТОМ
    # и вычисляется раньше вызова. Подделка выглядела полной и не была ею —
    # поймал это отравленный транспорт, а не чтение кода глазами.
    monkeypatch.setattr(module, "manifest", lambda url: [{}])
    monkeypatch.setattr(module, "declared_versions", lambda: ([], ""))
    monkeypatch.setattr(module, "language_moved", lambda *a, **k: [])
    # ВЕРСИИ ЧУЖИХ ДЕЙСТВИЙ ЧИТАЮТ ДЕРЕВО, А НЕ СЕТЬ, и подделываются поэтому
    # иначе: отравленный транспорт их не остановит, а настоящее расхождение в
    # прогонах проекта сделало бы этот прогон красным по чужому поводу. Предмет
    # здесь — как `look` ведёт себя с молчащим источником, а не состав прогонов.
    monkeypatch.setattr(module, "actions_disagree", lambda *a, **k: [])
    # ВЫПУСКИ ЧУЖИХ ДЕЙСТВИЙ ХОДЯТ В СЕТЬ — и отравленный транспорт это поймал
    # на первом же прогоне: источник, о котором здесь забыли, сказал о себе
    # сам, ровно как задумано (075).
    monkeypatch.setattr(module, "actions_behind", lambda *a, **k: [])
    # Пометки закреплений и предупреждения площадки поймал тот же приём
    # на их первом прогоне (#665) — гасятся так же.
    monkeypatch.setattr(module, "pin_mislabelled", lambda *a, **k: [])
    monkeypatch.setattr(module, "platform_warnings", lambda *a, **k: [])
    # Источник «выпуск против дерева» тоже читает дерево и историю, а не
    # сеть: отравленный транспорт его не останавливает, а настоящее
    # отставание выпуска сделало бы этот прогон красным по чужому поводу.
    monkeypatch.setattr(module, "release_behind_tree", lambda *a, **k: [])
    # Проба против выпуска — того же рода: читает дерево и историю. Её
    # отставание наступит при ПЕРВОМ ЖЕ выпуске, и без подделки этот прогон
    # покраснел бы по поводу, к молчанию источников отношения не имеющему.
    # Нашёл внешний взгляд на #574.
    monkeypatch.setattr(module, "probe_behind_release", lambda *a, **k: [])
    monkeypatch.setattr(module, "showcase_questions_moved", lambda *_: [])
    monkeypatch.setattr(module, "gap_tasks_closed", lambda *a: [])
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


def sources_of_drift() -> tuple[set[str], set[str]]:
    """Источники дрейфа модуля и те из них, до которых доходит обход.

    ИСТОЧНИК УЗНАЁТСЯ ПО ТОМУ, ЧТО ОН ВОЗВРАЩАЕТ, а не по имени: `list[Drift]` —
    это и есть «источник дрейфа», а имя бывает любым
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    Достижимость считается ПО ВЫЗОВАМ, а не по прямому упоминанию в `look`: три
    источника семьи зовутся через `family_summary`, и требовать от них прямого
    вызова значило бы чинить исправное (044).
    """
    tree = ast.parse((ROOT / "scripts" / "drift.py").read_text(encoding="utf-8"))
    bodies = {one.name: one for one in tree.body if isinstance(one, ast.FunctionDef)}
    said = {
        name
        for name, one in bodies.items()
        if one.returns and ast.unparse(one.returns).replace(" ", "") == "list[Drift]"
    }
    seen: set[str] = set()
    queue = ["look"]
    while queue:
        name = queue.pop()
        if name in seen or name not in bodies:
            continue
        seen.add(name)
        for node in ast.walk(bodies[name]):
            if isinstance(node, ast.Call):
                head = node.func
                called = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
                if called in bodies:
                    queue.append(called)
    return said - {"look"}, seen


def test_every_source_of_drift_is_reached_by_the_pass() -> None:
    """Источник, до которого обход не доходит, — работа в никуда.

    ПРЕЖДЕ ПОЛНОТУ ДЕРЖАЛ ОТРАВЛЕННЫЙ ТРАНСПОРТ: забытый источник упирался в
    него и говорил о себе сам. Это работает, пока каждый источник ходит в СЕТЬ.
    18.09.2026 появился первый, который читает только дерево, — версии чужих
    действий, — и отравить его нечем: забудь его в списке, и он промолчал бы
    зелёным
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    Замер 18.09.2026: источников тринадцать, обход доходит до всех.
    """
    said, reached = sources_of_drift()
    assert said, "функций, возвращающих список дрейфа, не нашлось — предмет не найден (075)"
    lost = sorted(said - reached)
    assert not lost, (
        "источник дрейфа объявлен, а обход до него не доходит:\n  "
        + "\n  ".join(lost)
        + "\n  Допишите его в список `asks` у `look` — иначе он не отработает ни разу,"
        " а снаружи это выглядит как «дрейфа нет»."
    )


def workflow(tmp_path: Path, name: str, body: str) -> Path:
    """Кладёт прогон в поддельное дерево: свой каталог, а не общий (149)."""
    where = tmp_path / "workflows"
    where.mkdir(exist_ok=True)
    (where / name).write_text(body, encoding="utf-8")
    return where


def test_a_pass_without_runs_is_a_refusal_not_agreement(tmp_path: Path) -> None:
    """Прогонов нет — источник ОТКАЗЫВАЕТ, а не сообщает «сошлось».

    Пустой обход здесь читается как схождение: источник отдал бы пустой список
    находок, заход напечатал бы «внешние входы сошлись с деревом», и снаружи это
    неотличимо от настоящего схождения
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    У дрейфа для этого есть свой исход: молчащий источник называется по имени, и
    `look` перечисляет его отдельно от находок.

    ЗАМЕР 19.09.2026: найдено ЗАПУСКОМ механизмов на пустом корне, а не чтением
    кода — форма у обхода была та же, что у здоровых соседей.
    """
    where = tmp_path / "workflows"
    where.mkdir()
    with pytest.raises(module.NotRun):
        module.action_versions(where)


def test_one_version_of_a_foreign_action_is_not_a_drift(tmp_path: Path) -> None:
    """Одна версия у действия во всех прогонах — расхождения нет."""
    where = workflow(tmp_path, "a.yml", "      - uses: actions/checkout@v4\n")
    workflow(tmp_path, "b.yml", "      - uses: actions/checkout@abc123 # v4\n")
    assert module.actions_disagree(module.action_versions(where)) == []


def test_two_versions_of_one_foreign_action_are_named(tmp_path: Path) -> None:
    """Одно действие названо двумя версиями — это дрейф, и обе названы числами.

    Форму пина разводит триггер (152): где вызывающий берётся с общей ветки,
    нужен хеш. Версию не разводит ничто, и два мажора чужого кода в одном
    конвейере живут молча. Замер 18.09.2026: `actions/checkout` — `v4` в семи
    прогонах и хеш с пометкой `v7.0.1` в тринадцати.
    """
    where = workflow(tmp_path, "a.yml", "      - uses: actions/checkout@v4\n")
    workflow(tmp_path, "b.yml", "      - uses: actions/checkout@abc123 # v7.0.1\n")
    found = module.actions_disagree(module.action_versions(where))
    assert [one.source for one in found] == ["action-version"]
    assert "v4" in found[0].said and "v7.0.1" in found[0].said


def test_a_pinned_hash_is_read_by_its_marked_version(tmp_path: Path) -> None:
    """Хеш с пометкой считается ТОЙ версией, а не собой.

    Иначе каждый хеш — своя «версия», и два прогона на одном и том же хеше без
    пометки выглядели бы расхождением. Пометка и есть объявление
    ([035](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/035-version-is-never-edited-by-hand.md)).
    """
    where = workflow(tmp_path, "a.yml", "      - uses: actions/setup-python@abc # v5\n")
    said = module.action_versions(where)
    assert said["actions/setup-python"] == {"v5": ["a.yml"]}


def test_our_own_action_is_not_judged_here(tmp_path: Path) -> None:
    """Своё и семейное судит гейт заготовки, а не этот источник (022, 090).

    Второй судья тому же предмету разошёлся бы с первым молча: у механизма семьи
    свои правила закрепления, и они уже проверяются `tests/test_family_pinning.py`.
    """
    where = workflow(
        tmp_path,
        "a.yml",
        "      - uses: ArtVsMark/Engineering-Incidents-Playbook@v1.2.0\n"
        "      - uses: ArtVsMark/Engineering-Incidents-Playbook@v1.3.0\n",
    )
    assert module.actions_disagree(module.action_versions(where)) == []


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
    assert "${{" not in ahead, (
        "предрелизная версия прочитана как подстановка площадки, а не как число: "
        "разбор смотрит не туда, и дрейф предрелизной ветки не нашёлся бы вовсе (045)"
    )
    assert ahead.count(".") == 1 and ahead not in matrix, (
        "предрелизная ветка — ветка языка и не повторяет обязательную матрицу"
    )


def test_both_version_lists_come_from_a_matrix() -> None:
    """Версии называет матрица — у обоих джобов, и это ради имени записи.

    Площадка приписывает значения матрицы к имени джоба: `test-next (3.15)`
    читается в списке проверок изменения, а версия внутри шага — нет. Владелец
    прочёл именно так: «3.15 в проверках не видно» (046).
    """
    path = ROOT / ".github" / "workflows" / "ci.yml"
    jobs = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("jobs") or {}
    for job in ("test-matrix", "test-next"):
        cells = module.matrix_of(jobs, job, path)
        assert cells, f"{job}: версии не в матрице — из имени записи они пропадут"
        step = [
            said
            for step in (jobs[job].get("steps") or [])
            if (said := ((step or {}).get("with") or {}).get("python-version"))
        ]
        assert step == ["${{ matrix.python }}"], (
            f"{job}: шаг берёт версию не из матрицы — источников числа стало два (022)"
        )


def test_a_job_without_a_matrix_is_the_third_outcome() -> None:
    """Матрицы нет — отказ входа с названным джобом, а не «версий нет» (075, 158)."""
    with pytest.raises(module.NotRun, match="test-next"):
        module.matrix_of({"test-next": {"steps": []}}, "test-next", Path("ci.yml"))


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
    владельца идентификатором не является, и полный адрес у нас есть.

    ССЫЛКА НА 194 ЗДЕСЬ СТОЯЛА И СНЯТА, как и в самом механизме: то правило про
    ВНЕШНИЕ реестры, где имя занимает первый пришедший, а реестр потребителей
    каталога закрытый и разрешительный. Требование здесь своё.
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


PROTECTED: dict[str, Any] = {
    "branch": "main",
    "enforcement": "active",
    "rules": ["deletion", "non_fast_forward", "required_status_checks"],
    "required_contexts": ["ci-complete"],
    "strict": True,
    "run_token_may_bypass": "never",
}


def platform(
    *,
    kinds: tuple[str, ...] = ("deletion", "non_fast_forward", "required_status_checks"),
    contexts: tuple[str, ...] = ("ci-complete",),
    strict: bool = True,
    bypass: str | None = "never",
) -> Any:
    """Ответ площадки о защите ветки — подделываемый по каждому свойству."""
    rules: list[dict[str, Any]] = []
    for kind in kinds:
        one: dict[str, Any] = {"type": kind, "ruleset_id": 1}
        if kind == "required_status_checks":
            one["parameters"] = {
                "strict_required_status_checks_policy": strict,
                "required_status_checks": [{"context": name} for name in contexts],
            }
        rules.append(one)

    def reply(_method: str, path: str, *_args: object, **_kwargs: object) -> Any:
        if "/rules/branches/" in path:
            return rules
        return {} if bypass is None else {"current_user_can_bypass": bypass}

    return reply


def watched(monkeypatch: pytest.MonkeyPatch, reply: Any) -> list[Any]:
    """Находки источника «защита общей ветки» на подделанном ответе."""
    monkeypatch.setattr(module, "declared_protection", lambda *a, **k: PROTECTED)
    monkeypatch.setattr(module.ghrest, "request", reply)
    found: list[Any] = module.protection_moved("o/r", "t")
    return found


def test_protection_that_matches_the_declaration_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сошлось — записи нет. Иначе канал шумит на исправном (051)."""
    assert watched(monkeypatch, platform()) == []


def test_a_removed_rule_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Снятое правило названо поимённо: «правил стало меньше» чинить нечем."""
    found = watched(monkeypatch, platform(kinds=("required_status_checks",)))
    assert len(found) == 1
    assert "deletion" in found[0].said and "non_fast_forward" in found[0].said
    assert found[0].next_step, "запись без следующего шага — сообщение о погоде"


def test_a_changed_required_context_is_named_with_both_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Обязательный контекст разошёлся — сказано, что объявлено и что стоит.

    Имя контекста — дословный вход защиты: расхождение на один символ значит,
    что защита ждёт вердикта, которого никто не выдаёт.
    """
    found = watched(monkeypatch, platform(contexts=("ci",)))
    assert len(found) == 1
    assert "ci-complete" in found[0].said and "'ci'" in found[0].said


def test_a_dropped_freshness_requirement_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Снятая свежесть — тоже ослабление: два зелёных порознь дают красное после слияния."""
    found = watched(monkeypatch, platform(strict=False))
    assert len(found) == 1
    assert "свежесть" in found[0].said


def test_a_granted_bypass_for_the_run_token_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Право обхода у токена ПРОГОНА — находка, а не новость.

    Прогон, способный толкать мимо гейтов, и есть путь в общую ветку мимо них:
    объявить это можно, но молча получить — нет (064).
    """
    found = watched(monkeypatch, platform(bypass="always"))
    assert len(found) == 1
    assert "обхода" in found[0].said and "always" in found[0].said


def test_an_unanswered_bypass_is_not_read_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка промолчала про обход — это отказ, а не «обхода нет».

    Молчание, прочитанное как «всё хорошо», — ровно тот вывод из незнания,
    который запрещён
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Источник дрейфа при этом не роняет остальные: заход назовёт его молчащим.
    """
    with pytest.raises(module.NotRun):
        watched(monkeypatch, platform(bypass=None))


def test_the_declaration_is_read_from_the_tree(tmp_path: Path) -> None:
    """Объявление берётся файлом дерева, а не снимком площадки."""
    where = tmp_path / "protection.json"
    where.write_text(json.dumps(PROTECTED, ensure_ascii=False), encoding="utf-8")
    assert module.declared_protection(where)["branch"] == "main"


def test_a_declaration_without_a_branch_is_an_input_error(tmp_path: Path) -> None:
    """Объявление без ветки — ошибка входа, а не «сравнивать нечего» (075)."""
    where = tmp_path / "protection.json"
    where.write_text(json.dumps({"rules": []}), encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.declared_protection(where)


def test_the_live_declaration_matches_the_shape_the_source_reads() -> None:
    """Объявление в дереве читается тем же разбором, что и в прогоне (022)."""
    said = module.declared_protection(ROOT / ".rules" / "protection.json")
    assert said["branch"] == "main"
    assert said["required_contexts"] == ["ci-complete"]
    assert said["run_token_may_bypass"] == "never"


def test_every_ruleset_is_asked_about_the_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Право обхода читается у КАЖДОГО набора, а не у первого.

    Наборов бывает несколько, и вправе обойти достаточно одного: выйти после
    первого значило бы проверить самый безобидный и назвать это проверкой.
    Нашёл внешний взгляд на #272 — докстринг обещал обход всех, код читал один.
    """
    rules = [
        {"type": "deletion", "ruleset_id": 1},
        {"type": "non_fast_forward", "ruleset_id": 2},
        {
            "type": "required_status_checks",
            "ruleset_id": 1,
            "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": "ci-complete"}],
            },
        },
    ]
    asked: list[int] = []

    def reply(_method: str, path: str, *_args: object, **_kwargs: object) -> Any:
        if "/rules/branches/" in path:
            return rules
        ruleset = int(path.rsplit("/", 1)[1])
        asked.append(ruleset)
        return {"current_user_can_bypass": "never" if ruleset == 1 else "always"}

    found = watched(monkeypatch, reply)
    assert sorted(asked) == [1, 2], f"спрошены не все наборы: {asked}"
    assert len(found) == 1, found
    assert "наборе 2" in found[0].said and "always" in found[0].said


# --- объявленные исходы захода -----------------------------------------------


def test_no_drift_is_its_own_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Внешние входы сошлись с деревом — свой исход, а не «записано».

    «Спросили и сошлось» и «записали находку» — разные состояния, и путать их
    значит терять ответ там, где он есть
    ([039](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/039-three-outcomes-not-two.md)).
    """
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "ours", dict)
    monkeypatch.setattr(module, "look", lambda repo, token, mine: ([], []))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    assert module.main(["--repo", "o/r"]) == module.EXIT_NOTHING
    assert "дрейфа нет" in capsys.readouterr().out


def test_a_found_drift_is_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Вход сдвинулся — исход записи, и число находок названо."""
    moved = module.Drift("каталог", "было 200, стало 203", "перечитать ответы")
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "ours", dict)
    monkeypatch.setattr(module, "look", lambda repo, token, mine: ([moved], []))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    assert module.main(["--repo", "o/r"]) == module.EXIT_RECORDED
    said = capsys.readouterr().out
    assert "сдвинулось внешних входов: 1" in said
    assert "перечитать ответы" in said, "запись без того, что делать, — сообщение о погоде"


def test_all_sources_silent_is_not_a_settled_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Молчат ВСЕ источники — поломка захода, а не «дрейфа нет».

    «Спросить не удалось» и «сошлось» снаружи одинаковы, и принять первое за
    второе значит зазеленеть на незнании
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "ours", dict)
    monkeypatch.setattr(module, "look", lambda repo, token, mine: ([], list(module.SOURCES)))
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN
    assert "ни один источник не ответил" in capsys.readouterr().err


#: Эталонный набор каталога в прогонах: два вопроса, больше не нужно.
THEIR_SHOWCASE = {"questions": [{"id": "ci"}, {"id": "release"}]}


def showcase(*ids: str) -> dict[str, Any]:
    """Наш ответ витрины из названных вопросов."""
    return {"questions": [{"id": one} for one in ids]}


def test_a_question_the_catalogue_asks_and_we_do_not_is_drift() -> None:
    """Каталог спросил новое — у нас пробел, и он назван.

    Пока сверялся только НОМЕР контракта витрины, состав мог разойтись молча:
    добавить вопрос, не тронув схему, каталог вправе, и обе стороны видели бы
    своё зелёное (055).
    """
    found = module.showcase_questions_moved(THEIR_SHOWCASE, showcase("ci"))
    assert [one.source for one in found] == ["showcase-questions"]
    assert "release" in found[0].said
    assert found[0].next_step, "запись без того, что делать, — сообщение о погоде (142)"


def test_an_answer_of_ours_the_catalogue_does_not_ask_is_drift() -> None:
    """Свой вопрос сверх набора — второй список, и он расходится молча."""
    found = module.showcase_questions_moved(THEIR_SHOWCASE, showcase("ci", "release", "своё"))
    assert [one.source for one in found] == ["showcase-extra"]
    assert "своё" in found[0].said


def test_an_agreeing_showcase_is_silent() -> None:
    """Состав сошёлся — молчание: дрейф говорит о расхождении, а не о погоде."""
    assert module.showcase_questions_moved(THEIR_SHOWCASE, showcase("ci", "release")) == []


def test_the_order_of_questions_is_not_drift() -> None:
    """Порядок — оформление витрины, а не её состав.

    Судить порядок значило бы красить перестановку строк; сосед у сужения
    назван (195).
    """
    assert module.showcase_questions_moved(THEIR_SHOWCASE, showcase("release", "ci")) == []


def test_an_empty_showcase_is_the_third_outcome() -> None:
    """Набор без вопросов — поломка входа, а не «состав сошёлся» (075)."""
    with pytest.raises(module.NotRun):
        module.showcase_questions_moved(THEIR_SHOWCASE, {"questions": []})


def test_ours_file_names_what_is_missing_and_what_is_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Общее чтение наших файлов: отсутствие и негодная форма — третий исход.

    Обобщено по ТРЕТЬЕМУ случаю (093): два чтения жили порознь законно, третье
    стало поводом. Причина отсутствия остаётся своей у каждого зовущего — она
    объясняет читателю, чего именно не подключено.
    """
    monkeypatch.chdir(tmp_path)
    негодный = Path(".rules/showcase.json")
    with pytest.raises(module.NotRun, match="канал не подключён"):
        module.ours_file(негодный, missing="канал не подключён")
    негодный.parent.mkdir(parents=True)
    негодный.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(module.NotRun, match="не словарь"):
        module.ours_file(негодный, missing="канал не подключён")
    негодный.write_text('{"questions": []}', encoding="utf-8")
    assert module.ours_file(негодный, missing="канал не подключён") == {"questions": []}


def test_our_showcase_is_read_from_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Наш набор берётся из дерева, а отсутствие файла — третий исход."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(module.NotRun):
        module.ours_showcase()
    (tmp_path / ".rules").mkdir()
    (tmp_path / ".rules" / "showcase.json").write_text(
        json.dumps(showcase("ci"), ensure_ascii=False), encoding="utf-8"
    )
    assert module.asked_ids(module.ours_showcase()) == ["ci"]


# --- пробелы, названные задачей ----------------------------------------------


def отвечает(состояния: dict[int, str]) -> Any:
    """Площадка, отвечающая о задачах названными состояниями."""

    def request(method: str, path: str, token: str, body: Any = None) -> dict[str, Any]:
        номер = int(path.rsplit("/", 1)[-1])
        return {"state": состояния.get(номер, "open")}

    return request


def test_a_gap_that_names_a_closed_task_is_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ обещает пробел и называет закрытую задачу — это дрейф.

    Замер 13.09.2026: ответ по 032 говорил «у роли этого пока нет — названо
    задачей #33», а #33 закрыта тремя днями раньше вместе с починкой. Четвёртый
    случай одного класса за смену, и все четыре нашёл человек, а не механизм.
    """
    mine = {"rules": {"032": {"where": "у роли этого пока нет — названо задачей #33"}}}
    monkeypatch.setattr(module.ghrest, "request", отвечает({33: "closed"}))
    found = module.gap_tasks_closed("о/р", "токен", mine)
    assert [one.source for one in found] == ["gap-032"]
    assert "#33" in found[0].said
    assert found[0].next_step, "запись без того, что делать, — сообщение о погоде (142)"


def test_an_open_task_behind_a_gap_is_not_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пробел, названный ОТКРЫТОЙ задачей, — честная работа, а не находка."""
    mine = {"rules": {"087": {"where": "вторая половина пока не сделана — #87"}}}
    monkeypatch.setattr(module.ghrest, "request", отвечает({87: "open"}))
    assert module.gap_tasks_closed("о/р", "токен", mine) == []


def test_a_closed_task_without_a_gap_is_not_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ссылка на закрытую задачу сама по себе законна: это история.

    Из одиннадцати ссылок на задачи в ответах девять именно таковы — на
    источник инцидента. Судится только СОСЕДСТВО с утверждением о пробеле:
    сосед у сужения назван (195).
    """
    mine = {"rules": {"166": {"where": "разбор и починка — #12"}}}
    monkeypatch.setattr(module.ghrest, "request", отвечает({12: "closed"}))
    assert module.gap_tasks_closed("о/р", "токен", mine) == []


def test_a_task_far_from_the_gap_is_not_counted() -> None:
    """Номер из соседнего абзаца к пробелу отношения не имеет.

    Ответы длинные, и без окна любой пробел притягивал бы к себе все номера
    ответа — механизм ловил бы законное (051).
    """
    далеко = "вторая половина пока не сделана" + "х" * (module.GAP_WINDOW + 10) + " #77"
    assert module.gaps_naming_a_task({"rules": {"130": {"where": далеко}}}) == []


def test_an_unreadable_number_silences_only_its_own_pair(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Один неразрешимый номер не гасит весь источник за заход.

    Номера берутся из ПРОЗЫ, и там попадается всё: чужой репозиторий, опечатка,
    номер, которого ещё нет. Пока один такой ронял источник целиком, молчание
    об опечатке выглядело как «дрейфа нет» по всем остальным парам (045).
    Нашёл внешний взгляд на #330.
    """

    def request(method: str, path: str, token: str, body: Any = None) -> dict[str, Any]:
        номер = int(path.rsplit("/", 1)[-1])
        if номер == 9999:
            raise module.ghrest.TransportError("404: такой задачи нет")
        return {"state": "closed"}

    monkeypatch.setattr(module.ghrest, "request", request)
    mine = {
        "rules": {
            "001": {"where": "половина пока не сделана — #9999"},
            "002": {"where": "половина пока не сделана — #33"},
        }
    }
    found = module.gap_tasks_closed("о/р", "токен", mine)
    assert [one.source for one in found] == ["gap-002"], "живая пара потеряна из-за соседней"
    assert "9999" in capsys.readouterr().out, "нечитаемый номер пропущен молча"


def test_the_live_answers_have_no_stale_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живое дерево: ни одного пробела, названного задачей, не осталось.

    Пустой ответ здесь — состояние, а не молчание: пары «пробел → задача» в
    ответах сегодня нет вовсе, и проверять нечего именно поэтому (154).
    """
    assert module.gaps_naming_a_task(module.ours()) == []


def test_every_named_source_is_actually_asked() -> None:
    """Имя источника в списке и вопрос к нему — одно и то же.

    Источник, названный в `SOURCES` и не спрошенный, делал бы проверку «молчат
    все» неверной: знаменатель больше числителя, и заход никогда не признал бы
    себя сломанным (075). Обратное так же: спрошенный и не названный не попадёт
    в раздел «Не спрошено» и пропадёт молча.
    """
    said = inspect.getsource(module.look)
    unasked = [one for one in module.SOURCES if f'"{one}"' not in said]
    assert not unasked, f"источник назван, а вопроса к нему нет: {unasked}"
    assert len(module.SOURCES) == len(set(module.SOURCES)), "имя источника названо дважды"

    # ОБРАТНАЯ СТОРОНА — ТА, РАДИ КОТОРОЙ ПРОВЕРКА И НУЖНА. Докстрока обещала её
    # с самого начала, а предикат выше смотрел только в одну: «названное
    # спрошено» держит знаменатель, «спрошенное названо» — числитель. Замер
    # 19.09.2026: спрашивалось девять источников, названо восемь, и «версии
    # чужих действий» не значились в списке вовсе — порог «молчат все» сработал
    # бы, когда ответил один, и промолчал бы, когда не ответил никто. Нашёл
    # внешний взгляд (`9661544`), а проза о нём здесь уже стояла
    # ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    #
    # Имена берутся РАЗБОРОМ, а не подстрокой: подстрока нашлась бы и в
    # пояснении рядом, и предикат снова оказался бы шире предмета.
    tree = ast.parse(textwrap.dedent(said))
    # Присваивание берётся В ОБОИХ видах: у `asks` стоит аннотация типа, то есть
    # это `AnnAssign`, а не `Assign`. Разбор, знавший один вид, нашёл пустой
    # список — и проверка честно отказала третьим исходом вместо того, чтобы
    # зазеленеть на пустоте (075).
    asked: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            named = any(getattr(target, "id", "") == "asks" for target in node.targets)
        elif isinstance(node, ast.AnnAssign):
            named = getattr(node.target, "id", "") == "asks"
        else:
            continue
        if not named:
            continue
        for pair in getattr(node.value, "elts", []):
            if (
                isinstance(pair, ast.Tuple)
                and pair.elts
                and isinstance(pair.elts[0], ast.Constant)
                and isinstance(pair.elts[0].value, str)
            ):
                asked.append(pair.elts[0].value)
    assert asked, "список вопросов не разобрался — предмета у проверки нет (075)"
    unnamed = [one for one in asked if one not in module.SOURCES]
    assert not unnamed, (
        f"источник спрашивается, а в списке не назван: {unnamed} — порог «молчат все»"
        f" считается по {len(module.SOURCES)} именам против {len(asked)} вопросов"
    )
    assert tuple(asked) == module.SOURCES, (
        f"порядок разошёлся: спрашиваются {asked}, объявлены {list(module.SOURCES)}"
    )


def test_an_unread_protection_is_the_third_outcome_of_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ общего чтения защиты — третий исход источника, а не падение захода.

    Прочие источники дрейфа к осечке сети на этом не причастны, и ронять из-за неё
    весь заход значило бы терять их находки (084, 039).
    """

    def refuse(repo: str, branch: str, token: str) -> Any:
        raise module.protection.NotRead("площадка не ответила")

    monkeypatch.setattr(module.protection, "live", refuse)
    monkeypatch.setattr(module, "declared_protection", lambda *a, **k: PROTECTED)
    with pytest.raises(module.NotRun, match="не ответила"):
        module.protection_moved("o/r", "токен")


def released_tree(tmp_path: Path, *, marked_before_tag: bool) -> Path:
    """Дерево с настоящим тегом выпуска и помеченным файлом до или после него.

    История настоящая: подделанный ответ git подтверждал бы согласие кода с
    нашим представлением о тегах, а не с git (170).
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    run = ["git", "-C", str(tmp_path)]
    subprocess.run([*run, "init", "--quiet", "-b", "main"], check=True)
    subprocess.run([*run, "config", "user.email", "т@т"], check=True)
    subprocess.run([*run, "config", "user.name", "т"], check=True)
    marked = tmp_path / "scripts" / "shipped_tool.py"

    def commit(message: str) -> None:
        subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
        subprocess.run([*run, "commit", "--quiet", "-m", message], check=True)

    if marked_before_tag:
        marked.write_text('"""ОТДАЁТСЯ НАРУЖУ: пример."""\n', encoding="utf-8")
        commit("инструмент")
        subprocess.run([*run, "tag", "v1.0.0"], check=True)
        return tmp_path
    (tmp_path / "scripts" / "свой.py").write_text('"""свой."""\n', encoding="utf-8")
    commit("до выпуска")
    subprocess.run([*run, "tag", "v1.0.0"], check=True)
    marked.write_text('"""ОТДАЁТСЯ НАРУЖУ: пример."""\n', encoding="utf-8")
    commit("инструмент после выпуска")
    return tmp_path


def test_a_release_behind_the_tree_is_a_drift(tmp_path: Path) -> None:
    """Помеченное есть в дереве, а выпуск его не несёт — это находка.

    Предмет не «файла нет у нас», а «потребитель по названной ему ссылке его
    не достанет»: между этими ответами и живёт весь источник.
    """
    found = module.release_behind_tree(released_tree(tmp_path, marked_before_tag=False))
    assert len(found) == 1
    assert found[0].source == "release-behind"
    assert "scripts/shipped_tool.py" in found[0].said, "запись не назвала файл поимённо (046)"
    assert "выпуск" in found[0].next_step, "запись без следующего шага — сообщение о погоде (142)"


def test_a_release_that_carries_everything_is_not_a_drift(tmp_path: Path) -> None:
    """Вторая половина: выпуск несёт помеченное — находок нет.

    Без неё источник был бы неотличим от «всегда находит», а такой учат
    обходить (051).
    """
    assert module.release_behind_tree(released_tree(tmp_path, marked_before_tag=True)) == []


def test_without_a_release_the_source_does_not_read_as_settled(tmp_path: Path) -> None:
    """Выпусков нет — третий исход, а не «всё в выпуске» (045).

    На обрезанном клоне теги не выкачиваются, и молчание источника снаружи
    неотличимо от схождения.
    """
    (tmp_path / "scripts").mkdir()
    subprocess.run(["git", "-C", str(tmp_path), "init", "--quiet", "-b", "main"], check=True)
    with pytest.raises(module.NotRun, match="выпусков не видно"):
        module.release_behind_tree(tmp_path)


def test_a_source_refusal_is_recorded_as_silence_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Отказ источника «выпуск против дерева» записывается, а не роняет обход.

    Предикат достижимости живёт у `check_shipped` и кидает СВОЁ исключение.
    `look` ловит `drift.NotRun`, и чужая форма прошла бы мимо `except`: один
    отказ этого источника уносил бы весь заход, вместо строки «источник не
    ответил». Нашёл внешний взгляд на #562 и проверил тем же приёмом, что
    здесь, — подменой `at_ref` на «ссылки не видно».
    """
    monkeypatch.setattr(module.check_shipped, "at_ref", lambda *_a, **_k: None)
    with pytest.raises(module.NotRun):
        module.release_behind_tree(released_tree(tmp_path, marked_before_tag=False))


def test_a_readable_release_is_not_a_refusal(tmp_path: Path) -> None:
    """Вторая половина: ссылка читается — отказа нет.

    Без неё «всегда отказывать» прошло бы проверку, а источник, который всегда
    молчит, снаружи неотличим от сошедшегося (045).
    """
    assert module.release_behind_tree(released_tree(tmp_path, marked_before_tag=True)) == []


def released(tags: dict[str, str]) -> Any:
    """Площадка, отвечающая последним выпуском по имени действия."""

    def request(_method: str, path: str, *_rest: Any, **_kw: Any) -> dict[str, Any]:
        repo = path.removeprefix("repos/").removesuffix("/releases/latest")
        if repo not in tags:
            raise module.ghrest.NotFound(f"{repo}: выпусков нет")
        return {"tag_name": tags[repo]}

    return request


def test_a_pinned_action_says_when_it_falls_behind() -> None:
    """Вышел выпуск новее нашего пина — дрейф называет его со ссылкой на журнал.

    ЗАМЕР 23.09.2026: чужих действий в дереве три, все закреплены, и о новой
    версии проект не узнавал никак — спросил владелец. Для действия каталога
    вопрос задавался давно; здесь он расширен на все закреплённые
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    said = {"anthropics/claude-code-action": {"v1.0.216": ["review.yml"]}}
    newer = released({"anthropics/claude-code-action": "v1.0.231"})
    found = module.actions_behind(said, "t", newer)
    assert len(found) == 1
    assert "v1.0.216" in found[0].said and "v1.0.231" in found[0].said
    assert "releases/tag/v1.0.231" in found[0].next_step


def test_a_major_pin_does_not_fall_behind_on_a_patch() -> None:
    """Пин по мажору отстаёт только тогда, когда вышел новый мажор.

    Вторая половина: без неё мажорный пин `v5` краснел бы на каждой заплатке
    `v5.x`, и дрейф учили бы пролистывать
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    said = {"actions/setup-python": {"v5": ["ci.yml"]}}
    assert module.actions_behind(said, "t", released({"actions/setup-python": "v5.6.0"})) == []
    assert len(module.actions_behind(said, "t", released({"actions/setup-python": "v6.0.0"}))) == 1


def test_a_tag_that_is_not_a_number_is_named_not_called_fresh() -> None:
    """Тег, который не номер, и действие без выпусков НАЗЫВАЮТСЯ, а не роняются.

    Сравнить такой пин не с чем. Первая редакция его молча пропускала — и
    откат «выдать за свежий» не покраснел: снаружи оба исхода были пустотой.
    Ответить «не отстало» там, где ответа нет, — тихий запасной путь
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    assert module.version_of("latest") is None
    assert module.version_of("v2-beta") is None
    assert module.version_of("v7.0.1") == (7, 0, 1)
    said = {"someone/no-releases": {"v1": ["x.yml"]}, "someone/odd": {"v1": ["x.yml"]}}
    found = module.actions_behind(said, "t", released({"someone/odd": "nightly"}))
    assert [one.source for one in found] == ["action-unchecked"], found
    assert "someone/no-releases" in found[0].said and "someone/odd" in found[0].said


#: Хеши закреплений в подделках: сорок знаков, как их принимает площадка.
HASH_A: Final = "a" * 40
HASH_B: Final = "b" * 40


def test_only_a_hash_with_a_label_is_taken_for_the_label_check(tmp_path: Path) -> None:
    """Сверке пометки отдаётся только пара «хеш + пометка».

    Хеш без пометки сверять не с чем — его называет `actions_behind`; тег без
    хеша сам и есть версия; своё действие судит гейт заготовки.
    """
    runs = tmp_path / "workflows"
    runs.mkdir()
    (runs / "one.yml").write_text(
        f"      - uses: actions/checkout@{HASH_A} # v7.0.1\n"
        f"      - uses: actions/setup-python@{HASH_B}\n"
        "      - uses: actions/setup-python@v5\n"
        f"      - uses: ArtVsMark/Engineering-Incidents-Playbook@{HASH_B} # v1.2.0\n",
        encoding="utf-8",
    )
    assert module.pinned_hashes(runs) == {"actions/checkout": {"v7.0.1": {HASH_A}}}


def compared(statuses: dict[str, str]) -> Any:
    """Подделка сравнения «хеш...тег»: пометка → что отвечает площадка."""

    def request(_method: str, path: str, *_rest: Any, **_kw: Any) -> dict[str, Any]:
        label = path.rsplit("...", 1)[1]
        if label not in statuses:
            raise module.ghrest.NotFound(f"тега {label} нет")
        return {"status": statuses[label]}

    return request


def test_a_hash_that_left_its_label_is_named() -> None:
    """Хеш и пометка разошлись — дрейф называет пару; совпали — молчит.

    ЗАМЕР 23.09.2026: закреплений по хешу три, все согласны. Предмет — день,
    когда хеш поднимут, а пометку забудут: исполняется хеш, а версию по пометке
    читает и человек, и сам дрейф.
    """
    pins = {"actions/checkout": {"v7.0.1": {HASH_A}}}
    assert module.pin_mislabelled(pins, "t", compared({"v7.0.1": "identical"})) == []
    for status in ("behind", "diverged"):
        found = module.pin_mislabelled(pins, "t", compared({"v7.0.1": status}))
        assert [one.source for one in found] == ["action-pin-mislabelled"], status
        assert HASH_A[:7] in found[0].said and status in found[0].said
    missing = module.pin_mislabelled(pins, "t", compared({}))
    assert len(missing) == 1 and "тега нет" in missing[0].said


def test_a_floating_label_may_run_ahead_of_its_hash_a_release_label_may_not() -> None:
    """Подвижная пометка (`v5`) уходит вперёд законно; пометка выпуска — нет.

    Обе половины нужны: без первой каждый выпуск `v5.x` краснел бы у пина
    `# v5` — хотя хеш на той же линии, а отставание называет `actions_behind`;
    без второй тег полного выпуска, ушедший от хеша, выдавался бы за согласие
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    floating = {"actions/setup-python": {"v5": {HASH_B}}}
    assert module.pin_mislabelled(floating, "t", compared({"v5": "ahead"})) == []
    release = {"actions/checkout": {"v7.0.1": {HASH_A}}}
    assert len(module.pin_mislabelled(release, "t", compared({"v7.0.1": "ahead"}))) == 1


def annotated_head(
    monkeypatch: pytest.MonkeyPatch,
    runs: list[dict[str, Any]],
    notes: dict[int, list[dict[str, Any]]],
) -> list[str]:
    """Подделка площадки для предупреждений: голова, её проверки, их аннотации.

    Отдаёт СТРАНИЦАМИ, как площадка: `page=N` получает N-й кусок по
    `PER_PAGE`. Иначе проверка не различала бы чтение первой страницы и чтение
    до конца — ровно то, что нашёл внешний взгляд на #675.
    """
    asked: list[str] = []
    size = module.ghrest.PER_PAGE

    def page_of(items: list[Any], path: str) -> list[Any]:
        number = int(path.rsplit("page=", 1)[1]) if "page=" in path else 1
        return items[(number - 1) * size : number * size]

    def request(_method: str, path: str, *_rest: Any, **_kw: Any) -> Any:
        asked.append(path)
        if path.endswith("/commits/main"):
            return {"sha": "c" * 40}
        if "/annotations" in path:
            return page_of(notes[int(path.split("/check-runs/")[1].split("/")[0])], path)
        return {"check_runs": page_of(runs, path)}

    monkeypatch.setattr(module.ghrest, "request", request)
    return asked


def note(level: str, message: str) -> dict[str, Any]:
    """Аннотация в том виде, в каком её отдаёт площадка."""
    return {"annotation_level": level, "message": message, "path": ".github", "title": ""}


NODE: Final = "Node.js 20 is deprecated. The following actions target Node.js 20"
UBUNTU: Final = "The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026."


def test_a_platform_warning_reaches_an_addressee_and_ours_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Английское предупреждение площадки становится записью; наше русское — нет.

    ЗАМЕР 23.09.2026: на 518 проверках шести голов общей ветки аннотаций
    уровня warning и notice без кириллицы нашлось ровно два текста, оба
    площадки; все прочие — наши. Поле `path` у обеих сторон `.github` и не
    различает ничего.

    Вторая половина — уровень: отказ проверки называет её собственный красный
    цвет, и в предупреждения он не идёт.
    """
    runs = [
        {"id": 1, "name": "lint", "output": {"annotations_count": 3}},
        {"id": 2, "name": "lint", "output": {"annotations_count": 3}},
        {"id": 3, "name": "types", "output": {"annotations_count": 1}},
        {"id": 4, "name": "quiet", "output": {"annotations_count": 0}},
    ]
    notes = {
        1: [
            note("warning", NODE),
            note("warning", "окно обхода заполнено (30)"),
            note("failure", "Process completed with exit code 1."),
        ],
        3: [note("notice", UBUNTU), note("warning", NODE)],
    }
    asked = annotated_head(monkeypatch, runs, notes)
    found = module.platform_warnings("o/r", "t")
    assert [one.source for one in found] == ["platform-warning", "platform-warning"]
    said = " ".join(one.said for one in found)
    assert "Node.js 20" in said and "Ubuntu 26" in said
    assert "окно обхода" not in said and "exit code" not in said
    assert "(2 проверок" in next(one.said for one in found if "Node.js" in one.said)
    # По одной проверке на имя и только с аннотациями: предупреждение одно и то
    # же в каждом задании, а ночной заход не обязан спрашивать девяносто раз.
    annotated = sorted({path.split("?")[0] for path in asked if "/annotations" in path})
    assert annotated == ["repos/o/r/check-runs/1/annotations", "repos/o/r/check-runs/3/annotations"]


def test_a_head_without_checks_is_a_refusal_not_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверок на голове нет — источник отказывает, а не докладывает «тишину»."""
    annotated_head(monkeypatch, [], {})
    with pytest.raises(module.NotRun, match="нет ни одной проверки"):
        module.platform_warnings("o/r", "t")


def test_a_warning_past_the_first_page_is_still_heard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка за краем первой страницы и аннотация за краем своей — услышаны.

    НАХОДКИ ВНЕШНЕГО ВЗГЛЯДА НА #675 (`771da9b`, `4b70f97`). Проверок на голове
    общей ветки под девяносто при странице в сто, аннотаций у проверки —
    страница по умолчанию в тридцать. Предупреждение за краем пропадало бы
    молча — ровно то, ради чего источник написан.
    """
    size = module.ghrest.PER_PAGE
    quiet = [
        {"id": 10 + one, "name": f"q{one}", "output": {"annotations_count": 0}}
        for one in range(size)
    ]
    late = {"id": 7, "name": "late", "output": {"annotations_count": size + 1}}
    filler = [note("warning", f"наше пояснение {one}") for one in range(size)]
    annotated_head(monkeypatch, [*quiet, late], {7: [*filler, note("notice", UBUNTU)]})
    found = module.platform_warnings("o/r", "t")
    assert [one.source for one in found] == ["platform-warning"], found
    assert "Ubuntu 26" in found[0].said
