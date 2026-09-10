"""Красная общая ветка: что морозит, что записывается и что перезапускается.

Отвергаемое здесь тройное, и все три ошибки одинаково правдоподобны снаружи:

* **лишний перезапуск** — «чиним перезапуском» не сходится никогда, а бесконечный
  повтор выглядит как работа
  ([124](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/124-rerun-the-minimum-and-record-the-flake.md));
* **совещательное красное, объявленное простоем** — простоя нет, очередь идёт, и
  приоритет, звучащий всегда, перестаёт что-либо значить
  ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md));
* **потерянное мигание** — зелёное со второго раза без записи возвращается тем же
  тестом через неделю.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tests.conftest import ROOT, load_script

module = load_script("main_red.py")

WORKFLOW = ROOT / ".github" / "workflows" / "main-red.yml"
REQUIRED = ["lint", "test"]


def record(name: str, conclusion: str | None = "success", run: int = 100) -> dict[str, Any]:
    """Запись проверки в том виде, в каком её отдаёт площадка."""
    return {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "details_url": f"https://github.com/o/r/actions/runs/{run}/job/{run + 1}",
    }


def test_a_green_head_says_nothing() -> None:
    """Зелёная голова красноты не даёт: пустое состояние не выдумывается (027)."""
    assert module.red_of([record("lint"), record("test")]) == []


def test_a_running_check_is_not_red() -> None:
    """Незавершённая проверка — отсутствие вердикта, а не отказ.

    Считать её красной значило бы морозить общую ветку на каждом прогоне —
    ровно в тот момент, когда он ещё идёт.
    """
    running = {"name": "test", "status": "in_progress", "conclusion": None, "details_url": ""}
    assert module.red_of([running]) == []


def test_a_cancelled_check_is_not_red() -> None:
    """Отменённая запись пройденной не считается, но и отказом не является.

    Отмена — штатное следствие группы отмены, и объявлять по ней заморозку
    значит морозить ветку на каждом втором толчке.
    """
    assert module.red_of([record("test", "cancelled")]) == []


def test_a_skipped_check_is_not_red() -> None:
    """Пропуск на общей ветке — объявленное состояние change-only джоба."""
    assert module.red_of([record("pr-meta", "skipped")]) == []


def test_required_red_holds_the_merge_and_advisory_does_not() -> None:
    """Класс проверки решает, чем её красное является, — и решают это ДАННЫЕ.

    Это вся суть разведения: обязательная морозит очередь и даёт источник 0,
    совещательная не морозит ничего и даёт источник 3.
    """
    red = module.red_of([record("test", "failure"), record("test (3.15)", "failure")])
    holds, rest = module.split(red, REQUIRED)
    assert holds == ["test"]
    assert rest == ["test (3.15)"]


def test_an_advisory_red_is_not_declared_a_standstill() -> None:
    """Совещательное красное источником 0 не объявляется.

    Простоя нет: очередь идёт, слить может каждый. Объявить это нулём значит
    объявить простой, которого нет.
    """
    holds, rest = module.split(module.red_of([record("test (3.15)", "failure")]), REQUIRED)
    assert holds == []
    assert rest == ["test (3.15)"]


def test_the_run_number_is_read_from_the_record() -> None:
    """Номер прогона берётся из адреса записи: своего поля площадка не даёт."""
    assert module.run_id_of(record("test", "failure", run=4242)) == 4242


def test_a_record_without_an_address_gives_no_run() -> None:
    """Адрес не разобрался — перезапускать нечего, и это не ноль «на всякий».

    Ноль здесь означает «прогон неизвестен», и вызывающий обязан это увидеть,
    а не отправить перезапуск в никуда (045).
    """
    assert module.run_id_of({"name": "test", "details_url": "https://example/nothing"}) == 0


def test_a_flake_is_recorded_once_per_run() -> None:
    """Одно и то же мигание одним прогоном не удваивается при повторном заходе."""
    once = module.flakes_after([], "test", 100, "10.09.2026")
    twice = module.flakes_after(once, "test", 100, "10.09.2026")
    assert len(twice) == 1


def test_the_same_check_flaking_twice_is_two_records() -> None:
    """Разные прогоны — разные записи: частота мигания и есть предмет (124).

    Свести их в одну запись значило бы потерять то, ради чего мигания
    записывают: тест, мигнувший пятикратно, и тест, мигнувший однажды, — разные
    находки.
    """
    once = module.flakes_after([], "test", 100, "10.09.2026")
    twice = module.flakes_after(once, "test", 101, "10.09.2026")
    assert [item.run for item in twice] == [100, 101]


def test_flakes_survive_a_round_trip() -> None:
    """Записанное мигание читается обратно: иначе заход заводит его заново."""
    flakes = [module.Flake("test", "10.09.2026", 100)]
    body = module.render_body([], [], flakes, "abc1234")
    assert module.parse_flakes(body) == flakes


def test_the_body_separates_the_two_sources() -> None:
    """В теле задачи источники названы по отдельности, а не свалены в кучу.

    Читателю нужно не «что-то красное», а «что чинить сейчас, а что перед
    правилами»: у записей разный приоритет, и это должно быть видно (021).
    """
    body = module.render_body(["test"], ["test (3.15)"], [], "abc1234")
    assert "источник 0" in body
    assert "источник 3" in body
    assert body.index("источник 0") < body.index("источник 3"), "порядок источников перепутан"


def test_an_empty_section_says_so() -> None:
    """Пустой раздел объявляется словами, а не исчезает (027)."""
    body = module.render_body([], [], [], "abc1234")
    assert "Пусто" in body


# --- прогон, который это запускает --------------------------------------------


def document() -> dict[str, Any]:
    """Описание прогона красноты."""
    loaded: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return loaded


def test_the_rerun_right_is_asked_for_where_it_is_used() -> None:
    """Право перезапуска объявлено ровно у того прогона, который перезапускает."""
    assert document()["permissions"]["actions"] == "write"


def test_the_step_reading_the_platform_gets_a_token() -> None:
    """Шаг, читающий площадку, получает токен: иначе он молча слеп."""
    for step in document()["jobs"]["main-red"]["steps"]:
        if "main_red.py" in str(step.get("run") or ""):
            assert set(step.get("env") or {}) & {"GH_TOKEN", "GITHUB_TOKEN"}


def test_only_the_shared_branch_is_the_subject() -> None:
    """Своё красное на изменении сюда не относится: это источник 2 его автора."""
    assert "head_branch == 'main'" in document()["jobs"]["main-red"]["if"]


def test_the_job_owns_the_shared_state() -> None:
    """Заход один на репозиторий и не вытесняется: он пишет состояние (149)."""
    group = document()["concurrency"]
    assert group["group"] and "${{" not in group["group"]
    assert group["cancel-in-progress"] is False


def test_the_exit_codes_are_read_as_an_allowlist() -> None:
    """Коды разбираются списком разрешённого: незнакомый — отказ (068)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "0)" in text and "3)" in text and "*)" in text


def test_the_contract_describes_this_loop() -> None:
    """Механизм отвечает договору, а не заводит свой порядок (029).

    Контур 3 описан в `docs/behaviour.md` давно; здесь проверяется, что
    механизм строится под него, а не рядом с ним.
    """
    text = (ROOT / "docs" / "behaviour.md").read_text(encoding="utf-8")
    assert "Контур 3" in text
    assert "перезапускает его **один раз**" in text


def test_the_gap_line_is_gone_once_the_mechanism_exists(tmp_path: Path) -> None:
    """Пробел «здоровья общей ветки нет» не должен пережить свой механизм.

    Строка уходит из раздела пробелов, когда механизм появился и подтверждён
    прогоном (139). Здесь проверяется первая половина: механизм в дереве есть,
    и раздел пробелов обязан говорить о нём иначе, чем «нет ничего».
    """
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "тревоги, перезапуска одной проверки, заморозки и разморозки нет" not in text, (
        "механизм есть, а пробел всё ещё объявлен целиком — читатель поверит своду"
    )
