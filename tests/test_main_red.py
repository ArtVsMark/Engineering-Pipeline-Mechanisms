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

import pytest
import yaml

from tests.conftest import ROOT, load_script

module = load_script("main_red.py")
policy = load_script("pipeline_checks.py")

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


# --- решение о перезапуске: проверяется отдельно от захода --------------------
#
# Находка ревью по #98: центральная логика правила 124 жила внутри `main()` и
# не проверялась ничем — подделать её там пришлось бы вместе со всей площадкой,
# то есть не проверять вовсе.


def test_one_red_on_the_first_attempt_is_rerun() -> None:
    """Упал ровно один и попытка первая — перезапуск. Это весь случай мигания."""
    assert module.rerun_reason(["test"], [], run=100, tries=1) == ""


def test_a_second_attempt_is_not_rerun_again() -> None:
    """Перезапуск ровно один: второй означал бы «чиним перезапуском» (124).

    Такой цикл не сходится никогда: то, что чинится перезапуском, — мигание, и
    его надо записать, а не повторять.
    """
    assert module.rerun_reason(["test"], [], run=100, tries=2) == module.ALREADY


def test_several_reds_are_not_rerun() -> None:
    """Упало несколько — перезапуска нет вовсе: это похоже на дефект."""
    assert module.rerun_reason(["test", "lint"], [], run=100, tries=1) == module.NOT_ALONE


def test_an_advisory_red_alongside_blocks_the_rerun() -> None:
    """Совещательное красное рядом — тоже «упал не один».

    Перезапуск минимума перезапускает ВСЕ упавшие джобы прогона, а не один:
    значит рядом стоящее совещательное красное поехало бы вместе с ним, и
    «ровно один» перестало бы быть правдой.
    """
    assert module.rerun_reason(["test"], ["test (3.15)"], run=100, tries=1) == module.NOT_ALONE


def test_an_unreadable_address_is_its_own_reason() -> None:
    """«Адрес не разобрался» — не то же, что «уже перезапускался».

    Бездействие одинаковое, а значат они разное: первое — поломка чтения,
    второе — состояние работы. Одно сообщение на оба отправило бы разбирать
    дефект, которого нет (154).
    """
    assert module.rerun_reason(["test"], [], run=0, tries=1) == module.NO_ADDRESS
    assert module.NO_ADDRESS != module.ALREADY


def test_a_lone_advisory_red_is_not_called_a_crowd() -> None:
    """Упала одна совещательная — сказано именно это, а не «упал не один».

    Бездействие в обоих случаях одинаковое, а состояния разные: «упал не один»
    отправляет читателя искать второй упавший джоб, которого нет. Прежняя
    редакция говорила так про ЕДИНСТВЕННУЮ красную совещательную (154). Нашёл
    разбор на #101.
    """
    said = module.rerun_reason([], ["test-next"], run=100, tries=1)
    assert said == module.ADVISORY_ONLY
    assert said != module.NOT_ALONE


def test_advisory_reds_never_reach_a_rerun() -> None:
    """Совещательное красное не перезапускается ни в каком числе.

    Оно не держит ничего и уходит в долг источника 3 (084): перезапуск ради
    него тратил бы прогон на то, что и так записано.
    """
    assert module.rerun_reason([], ["a", "b"], run=100, tries=1) == module.ADVISORY_ONLY


# --- одно падение, отражённое двумя именами -----------------------------------

FEEDS = {"test": {"test-matrix"}}


def test_an_aggregate_and_its_matrix_are_one_fall() -> None:
    """Агрегат и его матричная ячейка — одно падение, а не два.

    Агрегат ждёт матрицу через `needs` и краснеет ровно потому, что красна
    ячейка. Пока это считалось двумя падениями, условие «упал ровно один» не
    выполнялось ПО ПОСТРОЕНИЮ, и перезапуск мигнувшей общей ветки не случался
    никогда.

    Замер 10.09.2026: `main` встала красной на `test` и `test-matrix (3.12)`,
    очередь заморозилась — а снять заморозку нечем, новых слияний в
    замороженной очереди не бывает.
    """
    assert module.one_fall(["test"], ["test-matrix (3.12)"], FEEDS) is True
    assert module.rerun_reason(["test"], ["test-matrix (3.12)"], 7, 1, FEEDS) == ""


def test_an_unrelated_neighbour_is_still_two_falls() -> None:
    """Чужое имя рядом — по-прежнему два падения, и перезапуска нет.

    Правило 124 перезапускает ОДНО мигнувшее. Два независимых падения — это
    похоже на дефект, и перезапуск скрыл бы его.
    """
    assert module.one_fall(["test"], ["lint"], FEEDS) is False
    assert module.rerun_reason(["test"], ["lint"], 7, 1, FEEDS) == module.NOT_ALONE


def test_two_holding_names_are_never_one_fall() -> None:
    """Два обязательных красных — это не мигание, чем бы они ни были связаны."""
    assert module.one_fall(["test", "lint"], [], FEEDS) is False


def test_the_link_is_read_from_the_tree() -> None:
    """Связь берётся из `needs` прогонов, а не вписана в механизм.

    Проза `.pipeline.yml` про «доезжает через needs» — объяснение для человека;
    решение принимается по данным дерева, иначе они разойдутся молча (022).
    """
    fed = policy.feeds()
    assert fed.get("test") == {"test-matrix"}


def test_the_target_of_the_rerun_matches_the_decision() -> None:
    """Предмет перезапуска ищется по тому же условию, что и решение.

    Пока выбор жил своим условием, сценарий «агрегат плюс его матрица» до
    перезапуска не доходил: `one_fall` уже говорил «одно падение», а номер
    прогона не вычислялся — и отказ приходил под другим именем, «адрес записи
    не разобрался». Починка меняла причину отказа, а не исход. Нашёл внешний
    взгляд на #160.
    """
    red = [
        {"name": "test", "details_url": "https://x/actions/runs/777/job/1"},
        {"name": "test-matrix (3.12)", "details_url": "https://x/actions/runs/777/job/2"},
    ]
    assert module.target_run(["test"], ["test-matrix (3.12)"], red, FEEDS) == 777


def test_no_target_when_it_is_not_one_fall() -> None:
    """Два падения — предмета нет, и перезапускать нечего."""
    red = [
        {"name": "test", "details_url": "https://x/actions/runs/777/job/1"},
        {"name": "lint", "details_url": "https://x/actions/runs/777/job/3"},
    ]
    assert module.target_run(["test"], ["lint"], red, FEEDS) == 0


def test_no_target_when_the_record_carries_no_run() -> None:
    """Запись без разбираемого адреса даёт ноль, а не выдуманный номер."""
    red = [{"name": "test", "details_url": "не адрес"}]
    assert module.target_run(["test"], [], red, FEEDS) == 0


# --- заморозка называет, чем её снять -----------------------------------------


def test_a_frozen_queue_says_nobody_unblocks_it() -> None:
    """Заморозка без починки в очереди — сказано вслух, а не в лог прогона.

    Дважды за смену починка стояла в очереди без метки: «это чинит общую ветку»
    решает человек, а не механизм. Очередь при этом молчала — она пишет «нет
    изменения с меткой» в лог своего прогона, куда никто не смотрит. Адресат у
    такого сообщения есть, и это задача о красноте (142).
    """
    said = " ".join(module.said_queue(3, 0))
    assert "ни одно не помечено" in said
    assert "3" in said


def test_a_frozen_queue_with_a_fix_says_so() -> None:
    """Починка есть — сказано и это: молчание значило бы то же, что «нет»."""
    said = " ".join(module.said_queue(3, 1))
    assert "fix-main" in said
    assert "ни одно не помечено" not in said


def test_an_empty_queue_is_its_own_state() -> None:
    """Пустая очередь — не «никто не чинит», а «двигать нечего» (154)."""
    assert "пуста" in " ".join(module.said_queue(0, 0))


def test_the_queue_count_reads_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Счёт берётся у площадки и считает только поданное в очередь.

    Черновик в очередь не подан, изменение без метки `automerge` — тоже: они не
    ждут слияния, и считать их значило бы завышать число ждущих.
    """
    rows = [
        {"number": 1, "labels": [{"name": "automerge"}], "draft": False},
        {"number": 2, "labels": [{"name": "automerge"}, {"name": "fix-main"}], "draft": False},
        {"number": 3, "labels": [{"name": "automerge"}], "draft": True},
        {"number": 4, "labels": [], "draft": False},
    ]
    monkeypatch.setattr(module.automerge.ghrest, "paginate", lambda *_, **__: iter(rows))
    assert module.queue_now("o/r", "token") == (2, 1)


def test_an_unread_queue_is_not_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — счёт не выдумывается.

    Ноль здесь означает «не спросили», и текст про пустую очередь честен: он
    говорит, что двигать нечего, а не что починки нет.

    Отказ поднимается классом ЕДИНСТВЕННОГО транспорта: `ghrest` у проекта
    один на все механизмы (001), и держит это `tests/test_ghrest.py`. В
    прогоне `main_red.ghrest` и `automerge.ghrest` — один и тот же модуль,
    поэтому и класс отказа один.
    """

    def falls(*_: object, **__: object) -> object:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.automerge.ghrest, "paginate", falls)
    assert module.queue_now("o/r", "token") == (0, 0)


# --- что нашёл внешний взгляд: каждая находка проверена отказом ---------------


def test_the_queue_count_goes_by_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Счёт очереди читает ВСЕ открытые изменения, а не первую страницу (находка #168).

    Одна страница на пятьдесят занижала не только «в очереди», но и счёт
    помеченных `fix-main`: механизм мог сказать «разблокировать некому», когда
    разблокирующее изменение уже стояло за краем. Проверяется тем, что
    помеченное лежит шестидесятым.
    """
    rows: list[dict[str, Any]] = [
        {
            "number": n,
            "labels": [{"name": "automerge"}],
            "draft": False,
            "head": {"ref": "b", "sha": "s"},
            "base": {"ref": "main"},
        }
        for n in range(1, 60)
    ]
    rows.append(
        {
            "number": 60,
            "labels": [{"name": "automerge"}, {"name": "fix-main"}],
            "draft": False,
            "head": {"ref": "b", "sha": "s"},
            "base": {"ref": "main"},
        }
    )
    monkeypatch.setattr(module.automerge.ghrest, "paginate", lambda *_, **__: iter(rows))
    assert module.queue_now("o/r", "token") == (60, 1), "хвост списка потерян"


def test_the_queue_count_reads_the_queue_not_its_own_listing() -> None:
    """Список открытых изменений читает очередь, а не второй сборщик (находка #168).

    Второе прочтение одного источника расходится с первым молча (022, 090).
    Проверяется по самому механизму: своего запроса открытых изменений в нём
    не осталось.
    """
    source = (ROOT / "scripts" / "main_red.py").read_text(encoding="utf-8")
    place = source.index("def queue_now")
    body = source[place : source.index("def said_queue")]
    assert "automerge.open_changes" in body, "счёт собирает список сам"
    assert "pulls?state=open" not in body, "в механизме остался свой запрос открытых изменений"


def test_a_frozen_queue_is_shown_beside_what_holds_it() -> None:
    """Строка очереди сшита с телом задачи при НЕПУСТЫХ обоих концах (находка #168).

    Прежде проверялись порознь: `said_queue` — своими случаями, `render_body`
    — с пустой очередью. Сшивка не проверялась ни разу, а именно она и говорит
    читателю, что держит слияние и кто это разблокирует.
    """
    body = module.render_body(["test"], ["test-next"], [], "abc1234", (3, 1))
    assert "test" in body and "test-next" in body
    assert "с меткой `fix-main`: **1**" in body, body


def test_a_flake_is_seen_without_a_rerun() -> None:
    """Мигание — зелёное ПОСЛЕ красного на той же голове, и перезапуск не нужен.

    Прежний замер искал мигания среди перезапусков и не мог их найти:
    перезапускать было некому, и отсутствие перезапусков доказывало само себя.
    Голова та же — значит дерево то же, и зелёное получено не правкой (044).
    Разбор — `docs/decisions/014-a-flake-must-be-visible-before-it-is-rerun.md`.
    """
    runs = [
        {
            "name": "review",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "01",
            "details_url": "https://github.com/o/r/actions/runs/7001/job/1",
        },
        {"name": "review", "status": "completed", "conclusion": "success", "started_at": "02"},
    ]
    # Номер ПАДАВШЕГО прогона — часть находки: по нему одна запись отличается
    # от следующей такой же, и частота не теряется (#222).
    assert module.flaky_names(runs) == {"review": 7001}


def test_green_before_red_is_not_a_flake() -> None:
    """Зелёное ДО красного — обычная краснота, а не мигание.

    Порядок читается по времени начала записи, а не по порядку ответа
    площадки: иначе всякое упавшее после успеха имя считалось бы мигающим.
    """
    runs = [
        {"name": "test", "status": "completed", "conclusion": "success", "started_at": "01"},
        {"name": "test", "status": "completed", "conclusion": "failure", "started_at": "02"},
    ]
    assert module.flaky_names(runs) == {}


def test_a_cancelled_record_is_not_a_fall() -> None:
    """Отменённая и пропущенная записи миганием не считаются.

    Пройденной ни одна не считается, но и отказом не является: считать отмену
    падением значило бы объявлять мигающим каждое имя, вытесненное группой
    отмены, — а это штатное событие, а не находка (124).
    """
    runs = [
        {"name": "lint", "status": "completed", "conclusion": "cancelled", "started_at": "01"},
        {"name": "lint", "status": "completed", "conclusion": "success", "started_at": "02"},
        {"name": "pr-meta", "status": "completed", "conclusion": "skipped", "started_at": "01"},
        {"name": "pr-meta", "status": "completed", "conclusion": "success", "started_at": "02"},
    ]
    assert module.flaky_names(runs) == {}


def test_a_flake_on_a_change_names_where_it_blinked() -> None:
    """Запись мигания говорит, ГДЕ мигнуло: общая ветка не подписывается.

    Умолчание молчаливое намеренно: записи общей ветки заведены раньше, и
    переписывать их задним числом незачем (043).
    """
    shared = module.Flake("test", "12.09.2026", 7)
    on_change = module.Flake("review", "12.09.2026", 217, "#217")
    assert shared.said().endswith("прогон 7")
    assert on_change.said().endswith("прогон 217 · #217")
    assert module.parse_flakes(f"{shared.said()}\n{on_change.said()}") == [shared, on_change]


def test_a_flake_without_a_run_number_is_not_recorded() -> None:
    """Запись, чей прогон не разобрался, миганием не считается.

    Разбор строгий по той же причине, что и у перезапуска: не разобралось —
    значит запись поставило не то приложение, и отличить это мигание от
    следующего будет нечем (045).
    """
    runs = [
        {"name": "x", "status": "completed", "conclusion": "failure", "started_at": "01"},
        {"name": "x", "status": "completed", "conclusion": "success", "started_at": "02"},
    ]
    assert module.flaky_names(runs) == {}


def test_two_flakes_of_one_name_are_two_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одно имя, мигнувшее дважды, даёт ДВЕ записи, а не одну.

    Дедупликация шла по номеру ИЗМЕНЕНИЯ, и второе мигание того же имени на том
    же изменении терялось — то есть терялась частота, ради которой мигания и
    записывают. Нашёл внешний взгляд на #222.
    """

    def head(sha: str, run: int) -> list[dict[str, object]]:
        return [
            {
                "name": "review",
                "status": "completed",
                "conclusion": "failure",
                "started_at": "01",
                "details_url": f"https://github.com/o/r/actions/runs/{run}/job/1",
            },
            {"name": "review", "status": "completed", "conclusion": "success", "started_at": "02"},
        ]

    heads = {"aaa": head("aaa", 11), "bbb": head("bbb", 22)}

    def paginate(path: str, *_: object, **__: object) -> list[dict[str, object]]:
        if "pulls?" in path:
            return [
                {"number": 7, "head": {"sha": "aaa"}},
                {"number": 7, "head": {"sha": "bbb"}},
            ]
        for sha, runs in heads.items():
            if sha in path:
                return runs
        return []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    found = module.flakes_on_changes("o/r", "token", [], "12.09.2026")
    assert [(one.name, one.run, one.where) for one in found] == [
        ("review", 11, "#7"),
        ("review", 22, "#7"),
    ]


def test_a_change_head_is_read_by_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Записи головы изменения читаются СТРАНИЦАМИ, как и у общей ветки.

    Умолчание площадки обрезает хвост молча, а хвост — это и есть вторая запись
    имени, без которой мигание неотличимо от обычной красноты (#222).
    """
    asked: list[str] = []

    def paginate(path: str, *_: object, **__: object) -> list[dict[str, object]]:
        asked.append(path)
        return [{"number": 7, "head": {"sha": "aaa"}}] if "pulls?" in path else []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    module.flakes_on_changes("o/r", "token", [], "12.09.2026")
    checks = [path for path in asked if "check-runs" in path]
    assert checks, "записи проверок головы изменения не читались вовсе"
    for path in checks:
        assert "per_page=100" not in path, f"страница одна, хвост теряется: {path}"
