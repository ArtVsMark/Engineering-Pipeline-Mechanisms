"""Карта взгляда: куда смотреть, потому что машина туда не смотрит.

Проверяется не «механизм читает JSON», а три свойства, без которых карта
вредит больше, чем помогает:

* карта берётся с ОБЩЕЙ ветки — иначе её подделает то самое изменение;
* неприменимое НАЗВАНО отдельной группой: взгляд не ищет его нарушений, но
  говорит, если предмет попался — это находка об ОТВЕТЕ, а не о коде;
* заголовки не пришли — сказано вслух, а не подменено молчанием.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("review_map.py")


def test_a_machine_held_rule_is_not_sent_to_the_eyes() -> None:
    """Правило с механизмом уходит в машинную половину, а не в список для глаз."""
    answer = {
        "rules": {
            "001": {"status": "active", "mechanism": "gate"},
            "002": {"status": "active", "mechanism": "pipeline"},
            "003": {"status": "active", "mechanism": "document"},
        }
    }
    machine, eyes, _ = module.split(answer)
    assert machine == ["001", "002"]
    assert eyes == ["003"]


def test_a_rule_declared_inapplicable_is_named_to_the_eyes() -> None:
    """Неприменимое не зовёт взгляд искать нарушения, но НАЗВАНО ему.

    Прежде оно не попадало в карту вовсе, и рассуждение было верным ровно до
    тех пор, пока верен ответ, — а проверяет ответ тот же взгляд, которому его
    и не показывали. Замер 16.09.2026: из 29 ответов «неприменимо» четыре
    оказались неверными и стояли месяцами (044).

    Правило, объявленное действующим и не держащееся ничем, по-прежнему идёт
    глазам как работа: у него предмет ЕСТЬ.
    """
    answer = {
        "rules": {
            "001": {"status": "not-applicable"},
            "002": {"status": "rejected", "why": "предмета нет"},
            "003": {"status": "active", "mechanism": "none"},
        }
    }
    machine, eyes, denied = module.split(answer)
    assert machine == []
    assert eyes == ["003"], "правило, не держащееся ничем, глазам показать надо"
    # ТРИ ОТРИЦАТЕЛЬНЫХ ОТВЕТА РАЗВЕДЕНЫ: «неприменимо» обещает, что предмета
    # нет; «отвергнуто» — что предмет есть, а правило не принято, и нарушение
    # там ожидаемо. Под одной вывеской это неправда (022). Нашёл внешний взгляд
    # находкой `b724e53`.
    assert denied == {"not-applicable": ["001"], "rejected": ["002"]}, denied


def test_the_inapplicable_group_asks_for_a_collision_not_a_hunt() -> None:
    """Просьба к взгляду асимметрична: не искать нарушения, а сказать о предмете.

    Симметричная просьба («проверь и эти двадцать три») стоила бы взгляду
    втрое дороже и утонула бы в шуме — а такую подсказку перестают читать
    целиком, вместе с полезной
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    text = module.render(
        ["001"],
        ["003"],
        {"not-applicable": ["007"]},
        {"007": "Правило без предмета"},
        touched=False,
    )
    assert "НЕПРИМЕНИМЫМИ" in text
    assert "НЕ НАДО" in text, "просьба не названа асимметричной — взгляд пойдёт искать"
    assert "находка об ОТВЕТЕ" in text
    assert "007" in text and "Правило без предмета" in text


def test_each_negative_answer_asks_its_own_question() -> None:
    """У каждого отрицательного ответа своя просьба, а не общая вывеска.

    «Неприменимо» — предмета нет, скажи, если попался. «Отвергнуто» — предмет
    есть, нарушение ОЖИДАЕМО, находка одна: причина отвержения устарела. «Не
    смотрели» — обещаний не давали, любая находка новая. Свалить их вместе
    значит сказать взгляду неправду о двух третях списка (022, 046).
    """
    text = module.render(
        ["001"],
        [],
        {"not-applicable": ["007"], "rejected": ["008"], "unreviewed": ["009"]},
        {},
        touched=False,
    )
    assert "НЕПРИМЕНИМЫМИ" in text and "007" in text
    assert "ОТВЕРГ" in text and "ОЖИДАЕМО" in text and "008" in text
    assert "ответа ещё НЕТ" in text and "009" in text


def test_a_status_outside_the_contract_is_named_not_lumped() -> None:
    """Статус вне договора назван словом, а не свален к соседям (045, 068).

    Молча положить незнакомый статус в чужую группу значило бы сказать взгляду
    о правиле то, чего проект не обещал.
    """
    text = module.render(["001"], [], {"почти-неприменимо": ["010"]}, {}, touched=False)
    assert "договором не объявлен" in text
    assert "010" in text
    # Текст просьбы спрашивается у самого разбора: назвать статус и число —
    # его работа, и проверять её через сборку всей карты значило бы проверять
    # заодно всё остальное.
    said = "\n".join(module.unknown_status("почти-неприменимо", 3))
    assert "почти-неприменимо" in said and "3" in said
    assert "находка" in said, "расхождение ответа со своей схемой не названо находкой"


def test_the_map_names_where_the_machine_is_absent() -> None:
    """В карте названо, сколько правил без машины и какие именно."""
    text = module.render(["001"], ["003"], {}, {"003": "Заголовок правила"}, touched=False)
    assert "003" in text and "Заголовок правила" in text
    assert "Машина держит 1" in text


def test_missing_titles_are_said_not_hidden() -> None:
    """Заголовки не пришли — карта говорит об этом, а не молчит (045)."""
    text = module.render(["001"], ["003"], {}, {}, touched=False)
    assert "не пришли" in text
    assert "003" in text, "без заголовков остаются номера, а не пустота"


def test_touching_the_answer_is_flagged_to_the_reviewer() -> None:
    """Изменение правит сам ответ каталогу — ревьюеру об этом сказано.

    Карта взята с общей ветки и правки не видит; молчание об этом дало бы
    ревьюеру уверенность, которой у него нет (085).
    """
    text = module.render(["001"], ["003"], {}, {"003": "Правило"}, touched=True)
    assert "правит сам ответ" in text


def test_the_answer_is_read_from_the_base_not_the_worktree(tmp_path: Path) -> None:
    """Ответ читается из названной ревизии, а не из рабочего дерева.

    Проверяется на настоящем репозитории: голова объявляет всё машинным, база —
    нет. Механизм обязан увидеть базу.
    """

    def run(*args: str) -> None:
        subprocess.run(
            args, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=True
        )

    run("git", "init", "--quiet", "-b", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Тест")
    answer = tmp_path / module.ANSWER
    answer.parent.mkdir(parents=True, exist_ok=True)
    base = {"rules": {"003": {"status": "active", "mechanism": "document"}}}
    answer.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "--quiet", "-m", "база")
    forged = {"rules": {"003": {"status": "active", "mechanism": "gate"}}}
    answer.write_text(json.dumps(forged, ensure_ascii=False), encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "--quiet", "-m", "голова объявляет всё машинным")

    here = Path.cwd()
    try:
        os.chdir(tmp_path)
        machine, eyes, _ = module.split(module.from_base("HEAD~1"))
    finally:
        os.chdir(here)
    assert eyes == ["003"], "подделанная голова победила базу"
    assert machine == []


def test_an_unreadable_base_is_the_third_outcome(tmp_path: Path) -> None:
    """Базы нет — шаг не отработал, а не «карта пуста» (075)."""
    with pytest.raises(module.NotRun):
        module.from_base("нет-такой-ревизии")


def test_a_bilingual_title_takes_the_project_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заголовок каталога двуязычный — берётся русский, язык этого проекта."""

    def export(_: str) -> dict[str, Any]:
        return {"rules": [{"id": "003", "title": {"ru": "По-русски", "en": "In English"}}]}

    monkeypatch.setattr(module.ghrest, "raw_json", export)
    assert module.titles() == {"003": "По-русски"}


def test_a_map_that_assembled_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Карта собралась и легла в файл — чистый исход.

    Прогонялся только отказ: ответ каталогу пуст. «Чисто» у шага было
    объявлено и не проверялось ни разу
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    """
    where = tmp_path / "карта.json"
    monkeypatch.setattr(module, "from_base", lambda base: {"001": "mechanism"})
    monkeypatch.setattr(
        module, "split", lambda said: (["001"], ["002"], {"not-applicable": ["003"]})
    )
    monkeypatch.setattr(module, "titles", dict)
    monkeypatch.setattr(module, "touches_the_answer", lambda base: False)
    monkeypatch.setattr(module, "render", lambda *a, **k: "карта")
    assert module.main(["--out", str(where)]) == module.EXIT_OK
    assert where.is_file(), "карта не легла в файл"
    said = capsys.readouterr().out
    assert "карта собрана" in said
    # Третья группа считается вслух наравне с двумя первыми: число, которого нет
    # в отчёте, читатель считает нулём (046).
    assert "not-applicable 1" in said, said


def test_the_tally_line_has_no_dangling_comma_when_nothing_is_denied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """При пустом «неприменимо» в строке итога нет висящей запятой.

    Склейка через `", ".join(...)` давала на пустом словаре пустую строку, и
    итог читался как «глазами 8,  → путь». Случай не выдуман: «неприменимых»
    может не остаться вовсе — это и есть цель разбора ответов. Нашёл внешний
    взгляд на #416.
    """
    monkeypatch.setattr(module, "split", lambda answer: (["001"], ["002"], {}))
    monkeypatch.setattr(module, "titles", lambda: {})
    monkeypatch.setattr(module, "touches_the_answer", lambda base: False)
    monkeypatch.setattr(module, "render", lambda *a, **k: "карта")
    monkeypatch.setattr(module, "from_base", lambda base: {"rules": {}})
    module.main(["--base", "HEAD", "--out", str(tmp_path / "map.md")])
    said = capsys.readouterr().out
    assert ",  " not in said and ", →" not in said, f"висящая запятая в итоге: {said!r}"
    assert "машиной 1, глазами 1 →" in said


def test_a_git_refusal_does_not_silence_the_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """git отказал — карта считается тронутой, а не нетронутой (045).

    Пустой `stdout` при отказе давал «не тронут», и взгляд НЕ получал указания
    сверить карту с дифом. Цена пропуска названа в самом механизме: ревью,
    которому подделали карту (085). Лишняя строка «сверь с дифом» дешевле
    молчания.
    """
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_a, **_k: module.subprocess.CompletedProcess([], 128, "", "fatal: bad revision"),
    )
    assert module.touches_the_answer("origin/main") is True


def test_an_untouched_answer_is_still_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вторая половина: git ответил пусто и успешно — ответ не тронут.

    Без неё «всегда тронут» добавляло бы строку к каждому взгляду, а указание,
    звучащее всегда, перестаёт что-либо значить (051).
    """
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_a, **_k: module.subprocess.CompletedProcess([], 0, "", ""),
    )
    assert module.touches_the_answer("origin/main") is False
