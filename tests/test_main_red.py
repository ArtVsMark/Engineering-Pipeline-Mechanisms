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

import ast
import json
import re
from pathlib import Path
from typing import Any, Final

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


#: Разрешённый список из одного имени — им проверяются исходы решения.
ALLOWED_ONE: Final = {"ci-complete": "замер: 17 миганий из 29"}


def test_one_red_on_the_first_attempt_is_rerun() -> None:
    """Упал ровно один, попытка первая, имя В СПИСКЕ — перезапуск.

    ИМЯ ЗДЕСЬ СМЕНИЛОСЬ С `test` НА `ci-complete`, и это не подгонка под код, а
    смена договора (#607). Прежде одиночное обязательное перезапускалось любое:
    оно проходило `one_fall` ВАКУУМНО. Теперь решает история мигания, а решение
    013 снова соблюдается — `test` судит дерево и в списке его нет.
    """
    assert module.rerun_reason(["ci-complete"], [], run=100, tries=1, allowed=ALLOWED_ONE) == ""


def test_a_second_attempt_is_not_rerun_again() -> None:
    """Перезапуск ровно один: второй означал бы «чиним перезапуском» (124).

    Такой цикл не сходится никогда: то, что чинится перезапуском, — мигание, и
    его надо записать, а не повторять.
    """
    said = module.rerun_reason(["ci-complete"], [], run=100, tries=2, allowed=ALLOWED_ONE)
    assert said == module.ALREADY


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
    said = module.rerun_reason(["ci-complete"], [], run=0, tries=1, allowed=ALLOWED_ONE)
    assert said == module.NO_ADDRESS
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


def test_several_advisory_reds_are_not_a_flake() -> None:
    """Совещательных красных несколько — это похоже на дефект, а не на осечку.

    Перезапуск одного не вернул бы ветку в зелень, а два сразу — уже не осечка
    канала (124). Причина при этом СВОЯ, а не «не в списке»: читателю важно,
    что дело в числе, а не в имени (154).
    """
    said = module.rerun_reason([], ["a", "b"], run=100, tries=1, allowed={"a": "почему"})
    assert said == module.ADVISORY_NOT_ALONE


def test_a_lone_advisory_red_is_rerun_when_the_list_allows_it() -> None:
    """Одиночное совещательное красное перезапускается, если имя разрешено.

    ЗАМЕР 15.09.2026, с которого список и начался: на голове deaf0c0 упал шаг
    значков — на толчке витрины в ветку-сироту, — и перезапуск того же прогона
    дал зелёное без единой правки. Перезапустил владелец рукой: приём известен,
    механизма у него не было (002). Разбор — решение 025.
    """
    allowed = module.rerunnable()
    assert allowed.get("badges"), "список пуст — предмет не найден (075)"
    assert module.rerun_reason([], ["badges"], run=100, tries=1, allowed=allowed) == ""
    assert module.rerun_reason([], ["badges"], run=100, tries=2, allowed=allowed) == module.ALREADY
    assert module.rerun_reason([], ["badges"], run=0, tries=1, allowed=allowed) == module.NO_ADDRESS


def test_an_unlisted_advisory_red_is_not_rerun() -> None:
    """Имя не в списке — перезапуска нет, какова бы ни была природа красноты.

    Список разрешительный (068), и попадают в него по ЗАМЕРУ, а не по
    рассуждению о том, «бывает ли у этой проверки мигание». Рассуждение здесь
    уже ошиблось: прежняя редакция этой проверки брала примером `debt` и
    объясняла, что его красное «означает настоящий долг, и второй заход ответит
    то же самое». 16.09.2026 замер сказал обратное — тот же прогон со второй
    попытки позеленел без единой правки, — и имя переехало в список. Премиса
    проверки была догадкой, и держалась она ровно до первого замера
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

    Поэтому образцом взято имя, которого в списке НЕТ и чей замер не сделан:
    отсутствие в списке — это и есть «замера не было», а не суждение о природе.
    """
    unlisted = "review"
    assert unlisted not in module.rerunnable(), (
        f"{unlisted} попало в список — образцу «не в списке» нужно другое имя"
    )
    said = module.rerun_reason([], [unlisted], run=100, tries=1, allowed=module.rerunnable())
    assert said == module.ADVISORY_ONLY


def test_a_required_red_is_still_judged_by_its_own_rule() -> None:
    """Обязательное красное разбирается прежним правилом, а не списком.

    ЗДЕСЬ СТОЯЛО «список — про совещательные, обязательное разбирается прежним
    правилом», и прежнее правило перезапускало ЛЮБОЕ одиночное обязательное,
    включая `test`. Решение 013 запрещает ровно это: семь обязательных считают
    дерево, и зелёное со второго раза скрыло бы находку (#607).

    Теперь обязательное вне списка не перезапускается, а «упал не один»
    остаётся прежним — и проверяется здесь же.
    """
    assert module.rerun_reason(["test"], [], run=100, tries=1, allowed={}) == (
        module.REQUIRED_UNLISTED
    )
    assert (
        module.rerun_reason(["test"], ["other"], run=100, tries=1, allowed={}) == module.NOT_ALONE
    )


def test_the_allowed_list_names_a_reason_for_every_name(tmp_path: Path) -> None:
    """Имя в списке без причины — отказ входа: перезапуск без объяснения (154)."""
    path = tmp_path / "rerun.json"
    path.write_text('{"allowed": [{"check": "badges"}]}', encoding="utf-8")
    with pytest.raises(module.NotRun, match="без причины"):
        module.rerunnable(path)
    path.write_text("не json", encoding="utf-8")
    with pytest.raises(module.NotRun, match="не прочитан"):
        module.rerunnable(path)


#: Замер входа в список: день, номер прогона, исход второй попытки. Форма та
#: же, что у расписаний, и по той же причине — «сделано 15 сентября» и «прогон
#: 34960373446, попытка 2 зелена» проверяются по-разному: первое читается, а
#: второе спрашивается у площадки (005, 139).
MEASURED_RE: Final = re.compile(r"^\d{2}\.\d{2}\.\d{4} · прогон \d+ · попытка \d+ зелена$")


def test_every_allowed_name_carries_its_measurement() -> None:
    """Имя попадает в список по ЗАМЕРУ, и замер назван датой и прогоном.

    Правило списка объявлено в самих данных: имя входит потому, что красное
    этой проверки НЕ означает дефекта дерева, и доказывается это одним —
    перезапуск того же прогона дал зелёное без единой правки. Пока поле
    `measured` никто не спрашивал, вход в список держался на прозе `why`, а
    проза не отличает замер от рассуждения — и уже ошиблась: про `debt` было
    написано, что «второй заход ответит то же самое»
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md),
    [139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

    Форма замера — та же, что у расписаний: день, номер прогона, исход второй
    попытки. Второе написание того же расходится с первым молча (022).
    """
    said = json.loads((ROOT / ".rules" / "rerun.json").read_text(encoding="utf-8"))
    names = [str(one.get("check") or "") for one in said["allowed"]]
    assert names, "список пуст — предмет проверки не найден (075)"
    for one in said["allowed"]:
        name = str(one.get("check") or "")
        stamp = str(one.get("measured") or "")
        assert MEASURED_RE.match(stamp), (
            f"«{name}»: замер не назван или не той формы — «{stamp}». "
            "Нужны день ДД.ММ.ГГГГ, номер прогона и исход второй попытки (139)"
        )


#: Сводный гейт: единственное имя, которого нет в ответе проекта по построению
#: — он не проверка дерева, а ЧИТАТЕЛЬ чужих записей на голове. Выдаётся
#: файлом `.github/workflows/ci-complete.yml`, и защита ветки знает ровно его.
AGGREGATE: Final = "ci-complete"


def test_every_allowed_name_is_known_and_does_not_judge_the_tree() -> None:
    """Имя списка объявлено в ответе проекта — или это сводный гейт.

    ЗДЕСЬ СТОЯЛО «в списке только СОВЕЩАТЕЛЬНЫЕ», и это кодировало прежнее
    правило: решать по классу. Решает история мигания (#607): `ci-complete`
    обязателен, но дерево не судит — он опрашивает записи ДРУГИХ проверок, и
    его одиночное красное при зелёных соседях по построению значит «не
    дочитал». Семнадцать миганий из двадцати девяти это показали, а отчёт
    назвал причину — 16 из 16 несут «ждём соседей на голове».

    Что осталось прежним и важнее прежнего: имя, которого в ответе нет и
    которое не сводный гейт, — это список, разошедшийся с деревом (022, 075).
    """
    checks = policy.load()
    for name in module.rerunnable():
        if name == AGGREGATE:
            continue
        assert name in checks, f"«{name}» не объявлен в .pipeline.yml"
        assert not checks[name].holds_merge, (
            f"«{name}» держит слияние и судит дерево — его перезапускать нельзя (013)"
        )


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
        {"name": "lint / lint", "details_url": "https://x/actions/runs/777/job/3"},
    ]
    assert module.target_run(["test"], ["lint"], red, FEEDS) == 0


def test_the_target_of_a_lone_advisory_red_is_its_own_run() -> None:
    """Одиночное совещательное красное становится предметом перезапуска.

    Тот же урок, что на #160, только с другой стороны: решение о перезапуске
    (`rerun_reason`) и выбор его предмета — один вопрос. Пока предмет не
    находился, решение уже говорило «перезапускаем», а заход отказывал под
    именем «адрес записи не разобрался» — чинилась бы причина отказа, а не
    исход.
    """
    red = [{"name": "badges", "details_url": "https://x/actions/runs/34960373446/job/1"}]
    assert module.target_run([], ["badges"], red, FEEDS) == 34960373446


def test_no_target_when_several_advisory_reds_stand_together() -> None:
    """Совещательных несколько — предмета нет: перезапуск одного не даёт зелень."""
    red = [
        {"name": "badges", "details_url": "https://x/actions/runs/777/job/1"},
        {"name": "review", "details_url": "https://x/actions/runs/777/job/2"},
    ]
    assert module.target_run([], ["badges", "review"], red, FEEDS) == 0


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
    said = " ".join(module.said_queue(module.Queue(3, 0)))
    assert "ни одно не помечено" in said
    assert "3" in said


def test_a_frozen_queue_with_a_fix_says_so() -> None:
    """Починка есть — сказано и это: молчание значило бы то же, что «нет»."""
    said = " ".join(module.said_queue(module.Queue(3, 1)))
    assert "fix-main" in said
    assert "ни одно не помечено" not in said


def test_an_empty_queue_is_its_own_state() -> None:
    """Пустая очередь — не «никто не чинит», а «двигать нечего» (154)."""
    assert "пуста" in " ".join(module.said_queue(module.Queue(0, 0)))


def test_the_queue_count_reads_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Счёт берётся у площадки и считает только поданное в очередь.

    Черновик в очередь не подан, изменение без метки `automerge` — тоже: они не
    ждут слияния, и считать их значило бы завышать число ждущих.

    Чтение и счёт теперь РАЗДЕЛЕНЫ: площадку спрашивает `live_changes`, один раз
    на заход, а `queue_now` только считает по готовому списку (находка `b0396e9`
    на #364). Здесь проверяется связка целиком — счёт по тому, что реально
    пришло с площадки.
    """
    rows = [
        {"number": 1, "labels": [{"name": "automerge"}], "draft": False},
        {"number": 2, "labels": [{"name": "automerge"}, {"name": "fix-main"}], "draft": False},
        {"number": 3, "labels": [{"name": "automerge"}], "draft": True},
        {"number": 4, "labels": [], "draft": False},
    ]
    monkeypatch.setattr(module.automerge.ghrest, "paginate", lambda *_, **__: iter(rows))
    assert module.queue_now(module.live_changes("o/r", "token")) == module.Queue(2, 1)


def test_an_unread_queue_is_not_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — счёт НЕ ВЫДУМЫВАЕТСЯ и не выдаётся за пустоту.

    ЗДЕСЬ БЫЛА ЗАЩИЩЁННАЯ ЛОЖЬ. Прежняя подпись этого теста говорила, что ноль
    отказа честен, «потому что текст сообщает: двигать нечего». Но текст
    утверждает `Очередь пуста: чинить некому и нечего двигать` — это заявление
    ПРО ОЧЕРЕДЬ, а в неё никто не смотрел. Нашёл внешний взгляд находкой
    `4925118` на #370; правило — 045.

    Отказ поднимается классом ЕДИНСТВЕННОГО транспорта: `ghrest` у проекта
    один на все механизмы (001), и держит это `tests/test_ghrest.py`. В
    прогоне `main_red.ghrest` и `automerge.ghrest` — один и тот же модуль,
    поэтому и класс отказа один.
    """

    def falls(*_: object, **__: object) -> object:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.automerge.ghrest, "paginate", falls)
    assert module.live_changes("o/r", "token") is None, "отказ прочтён как пустой список"
    counted = module.queue_now(None)
    assert not counted.read, "непрочитанная очередь не отличается от прочитанной"
    said = " ".join(module.said_queue(counted))
    assert "не прочитана" in said, "запись молчит о том, что смотреть не удалось"
    assert "пуста" not in said, "непрочитанная очередь объявлена пустой — это и есть ложь"


def test_an_empty_queue_and_an_unread_one_do_not_say_the_same(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пусто и не прочитано — РАЗНЫЕ тексты, а не одно число в двух ролях (039).

    Проверяется парой: совпадение строк означало бы, что различие завели в типе,
    а до читателя оно не доехало.
    """
    monkeypatch.setattr(module.automerge.ghrest, "paginate", lambda *_, **__: iter([]))
    empty = " ".join(module.said_queue(module.queue_now(module.live_changes("o/r", "t"))))
    unread = " ".join(module.said_queue(module.queue_now(None)))
    assert empty != unread, "два разных состояния очереди читаются одинаково"
    assert "пуста" in empty


def test_an_unread_list_is_not_an_empty_one_for_the_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Не прочитано — метка не расставляется, а не «расставлять некому» (045).

    Пустой список означал бы «живых изменений нет», и заморозка молча не
    отметилась бы ни на ком: отказ чтения выглядел бы сделанной работой.
    """
    put: list[object] = []
    monkeypatch.setattr(module, "stamp", lambda *a, **k: put.append(a))
    marked, freed = module.pause("o/r", "token", None, frozen=True, apply=True)
    assert (marked, freed, put) == ([], [], []), "по непрочитанному списку что-то отметили"


# --- что нашёл внешний взгляд: каждая находка проверена отказом ---------------


def test_the_live_list_goes_by_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живые изменения читаются ВСЕ, а не первой страницей (находка #168).

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
    assert module.queue_now(module.live_changes("o/r", "token")) == module.Queue(60, 1), (
        "хвост списка потерян"
    )


def test_only_one_place_asks_the_platform_for_open_changes() -> None:
    """Открытые изменения спрашивает ОДИН заход, и он назван (находки #168, #364).

    Сперва свой обход завёл счёт очереди (#168), потом — метка заморозки (#364).
    Оба раза класс один: второе прочтение одного источника расходится с первым
    молча и стоит вызовов из общей квоты (022, 090, 058). Поэтому проверяется не
    отдельная функция, а ВЕСЬ механизм: строка запроса в нём ровно одна, и лежит
    она в `live_changes`.
    """
    source = (ROOT / "scripts" / "main_red.py").read_text(encoding="utf-8")
    # Считаются СТРОКОВЫЕ ЛИТЕРАЛЫ разбора, а не вхождения в текст файла: адрес,
    # названный в пояснении, — это объяснение, а не запрос, и гейт, спотыкающийся
    # о собственный комментарий, красит исправное дерево (051). Отдельного
    # исключения для строк документации не нужно: запрос строится литералом
    # внутри вызова, и проверка меряет ровно это.
    asked = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "pulls?state=open" in node.value
    ]
    assert not asked, (
        f"в механизме появился свой запрос открытых изменений ({asked}) — читать их "
        "должен канонический читатель очереди, а не сырой обход"
    )
    place = source.index("def live_changes")
    body = source[place : source.index("@dataclass(frozen=True, slots=True)\nclass Seen")]
    assert "automerge.open_changes" in body, "читатель не зовёт канонический список"
    assert source.count("automerge.open_changes(") == 1, (
        "канонический список зовётся из механизма больше одного раза — это снова "
        "два обхода за заход"
    )


def test_a_frozen_queue_is_shown_beside_what_holds_it() -> None:
    """Строка очереди сшита с телом задачи при НЕПУСТЫХ обоих концах (находка #168).

    Прежде проверялись порознь: `said_queue` — своими случаями, `render_body`
    — с пустой очередью. Сшивка не проверялась ни разу, а именно она и говорит
    читателю, что держит слияние и кто это разблокирует.
    """
    body = module.render_body(["test"], ["test-next"], [], "abc1234", module.Queue(3, 1))
    assert "test" in body and "test-next" in body
    assert "с меткой `fix-main`: **1**" in body, body


def live(*pairs: tuple[int, str], marks: tuple[str, ...] = ()) -> list[Any]:
    """Живые изменения подделкой: номер и голова — всё, что читают потребители.

    Строится НАСТОЯЩИМ типом очереди, а не словарём: подделка своей формы
    разошлась бы с площадкой молча, и проверка держала бы не тот предмет (049).
    """
    return [
        module.automerge.Change(
            number=number,
            branch="b",
            base="main",
            head=head,
            title="",
            body="",
            draft=False,
            marks=frozenset(marks),
        )
        for number, head in pairs
    ]


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
        {
            "name": "lint / lint",
            "status": "completed",
            "conclusion": "cancelled",
            "started_at": "01",
        },
        {"name": "lint / lint", "status": "completed", "conclusion": "success", "started_at": "02"},
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
        for sha, runs in heads.items():
            if sha in path:
                return runs
        return []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    # Обход слитых гасится явно: предмет этой подделки — открытые изменения, и
    # сеть за слитыми увела бы проверку к настоящей площадке.
    monkeypatch.setattr(module.ghrest, "merged_changes", lambda *a, **k: [])
    found = module.seen_on_changes(
        "o/r", "token", [], "12.09.2026", live((7, "aaa"), (7, "bbb"))
    ).flakes
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
        return []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "merged_changes", lambda *a, **k: [])
    module.seen_on_changes("o/r", "token", [], "12.09.2026", live((7, "aaa")))
    checks = [path for path in asked if "check-runs" in path]
    assert checks, "записи проверок головы изменения не читались вовсе"
    for path in checks:
        assert "per_page=100" not in path, f"страница одна, хвост теряется: {path}"


def test_a_flake_on_a_merged_change_is_still_a_flake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Слитое изменение обходится наравне с открытым: мигание — свойство головы.

    Замер 13.09.2026: реестр #99 говорил «повторных зелёных не было», а на
    головах слитых #259 и #262 лежало по настоящему миганию `ci-complete`.
    Изменение, слившееся за минуты, исчезает из списка открытых раньше, чем шаг
    успевает заглянуть, — то есть чем БЫСТРЕЕ очередь, тем меньше миганий видит
    детектор, и молчание реестра оказывается следствием того, куда он смотрит, а
    не наблюдением
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    blinked: list[dict[str, object]] = [
        {
            "name": "ci-complete",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "01",
            "details_url": "https://github.com/o/r/actions/runs/77/job/1",
        },
        {"name": "ci-complete", "status": "completed", "conclusion": "success", "started_at": "02"},
    ]

    def paginate(path: str, *_: object, **__: object) -> list[dict[str, object]]:
        if "pulls?" in path:
            return []
        return blinked if "ccc" in path else []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(
        module.ghrest,
        "merged_changes",
        lambda *a, **k: [{"number": 262, "head": {"sha": "ccc"}, "merged_at": "вчера"}],
    )
    found = module.seen_on_changes("o/r", "token", [], "13.09.2026", []).flakes
    assert [(one.name, one.run, one.where) for one in found] == [("ci-complete", 77, "#262")]


def test_open_changes_are_still_walked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обратная сторона: открытые изменения из обхода не выпали (097).

    Добавив слитые, легко подменить один список другим — и потерять ровно те
    мигания, которые видны прямо сейчас.
    """
    blinked: list[dict[str, object]] = [
        {
            "name": "lint / lint",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "01",
            "details_url": "https://github.com/o/r/actions/runs/88/job/1",
        },
        {"name": "lint / lint", "status": "completed", "conclusion": "success", "started_at": "02"},
    ]

    def paginate(path: str, *_: object, **__: object) -> list[dict[str, object]]:
        return blinked if "ddd" in path else []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "merged_changes", lambda *a, **k: [])
    found = module.seen_on_changes("o/r", "token", [], "13.09.2026", live((9, "ddd"))).flakes
    assert [(one.name, one.where) for one in found] == [("lint / lint", "#9")]


# --- объявленные исходы захода -----------------------------------------------


def platform(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]],
    proofs: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Подделывает площадку и отдаёт список того, что заход записал.

    Подделывается ГРАНИЦА с площадкой, а не разбор: красноту, обязательность,
    счётчик попыток и вид записи считает сам механизм — иначе проверялась бы
    подделка. Поэтому ответ зависит от АДРЕСА, как у настоящей площадки: голова
    общей ветки и список заходов `ci` живут по разным адресам.
    """
    written: list[str] = []
    monkeypatch.setenv("GH_TOKEN", "токен")

    def asked(method: str, path: str, *rest: Any, **kw: Any) -> dict[str, Any]:
        if "actions/workflows" in path:
            return {"workflow_runs": list(proofs or [{"conclusion": "success"}])}
        return {"sha": "0123456789abcdef"}

    monkeypatch.setattr(module.ghrest, "request", asked)
    monkeypatch.setattr(module.ghrest, "paginate", lambda *a, **k: iter(records))
    monkeypatch.setattr(module.findings, "live_issue", lambda repo, token, mark: (1, ""))
    # Живые изменения — отдельный предмет и свои проверки выше. Здесь важны
    # исходы захода, и подделка списка проверок на список изменений не похожа:
    # чтение гасится целиком, а не подсовыванием чужой формы (049).
    monkeypatch.setattr(module, "live_changes", lambda repo, token: [])
    monkeypatch.setattr(
        module,
        "seen_on_changes",
        lambda repo, token, known, day, live, answer=None, **kw: module.Seen(
            flakes=known, unfixed=[]
        ),
    )
    monkeypatch.setattr(module, "queue_now", lambda live: module.Queue(0, 0))
    monkeypatch.setattr(module, "pause", lambda repo, token, live, *, frozen, apply: ([], []))
    monkeypatch.setattr(module, "save", lambda repo, token, body, apply: written.append(body))
    return written


def test_a_green_shared_branch_is_its_own_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Все записи на голове зелены — свой исход, а не «красно» и не «не смог».

    Три исхода, а не два: «посмотрел и красно», «посмотрел и зелено», «не
    посмотрел»
    ([039](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/039-three-outcomes-not-two.md)).
    """
    platform(monkeypatch, [{"name": "lint / lint", "status": "completed", "conclusion": "success"}])
    assert module.main(["--repo", "o/r"]) == module.EXIT_GREEN


def test_a_red_required_check_is_the_red_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Красная проверка на голове — исход «красно», и запись об этом ложится."""
    written = platform(
        monkeypatch, [{"name": "lint / lint", "status": "completed", "conclusion": "failure"}]
    )
    assert module.main(["--repo", "o/r"]) == module.EXIT_RED
    assert written and "lint" in written[0], "о красной проверке не записано"


def test_a_head_without_records_is_the_third_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Записей проверок на голове нет — «не отработал», а не «зелено» (075)."""
    platform(monkeypatch, [])
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN
    assert "ни одной записи проверки" in capsys.readouterr().err


# --- у цикла починки есть дно --------------------------------------------------


def test_the_counter_of_proofs_comes_from_the_platform() -> None:
    """Попытка — заход, НЕ доказавший зелень; счёт идёт до первого зелёного.

    Свой счётчик разошёлся бы с площадкой молча, и в сторону бесконечных
    попыток (049). Полоса читается от свежего к старому: зелёный её закрывает.
    """
    заходы = [
        {"conclusion": "failure"},
        {"conclusion": "timed_out"},
        {"conclusion": "success"},
        {"conclusion": "failure"},
    ]
    monkey = pytest.MonkeyPatch()
    monkey.setattr(module.ghrest, "request", lambda *a, **k: {"workflow_runs": заходы})
    try:
        assert module.proofs("o/r", "токен") == module.Proof(tries=2, whole=True), (
            "зелёный закрывает полосу, и старое красное за ним не считается"
        )
    finally:
        monkey.undo()


def test_a_cancelled_run_neither_counts_nor_breaks_the_streak() -> None:
    """Отменённый заход вердикта не несёт: ни попытка, ни доказательство зелени.

    Считать отсутствие вердикта доказательством — то же молчаливое умолчание, от
    которого страхует 045: полоса оборвалась бы на отмене, и предел не наступил
    бы никогда.
    """
    заходы = [
        {"conclusion": "failure"},
        {"conclusion": "cancelled"},
        {"conclusion": "failure"},
        {"conclusion": "success"},
    ]
    monkey = pytest.MonkeyPatch()
    monkey.setattr(module.ghrest, "request", lambda *a, **k: {"workflow_runs": заходы})
    try:
        assert module.proofs("o/r", "токен") == module.Proof(tries=2, whole=True)
    finally:
        monkey.undo()


def test_a_count_without_a_green_in_sight_says_it_is_a_lower_bound() -> None:
    """Зелёного в прочитанном окне нет — число НЕ МЕНЬШЕЕ, а не точное (045)."""
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        module.ghrest, "request", lambda *a, **k: {"workflow_runs": [{"conclusion": "failure"}] * 4}
    )
    try:
        счёт = module.proofs("o/r", "токен")
    finally:
        monkey.undo()
    assert счёт == module.Proof(tries=4, whole=False)
    assert "не меньше 4" in module.said_tries(счёт)[0]


def test_the_owner_becomes_the_addressee_only_at_the_limit() -> None:
    """Предел исчерпан — адресат владелец; до предела адресат прежний (109).

    Механизм при этом никого не останавливает: он называет число и того, кому
    дальше решать. Остановка починки решением механизма была бы решением за
    человека (154).
    """
    ниже = module.render_body(
        ["test"], [], [], "0123456", module.Queue(1, 0), module.Proof(2, True)
    )
    предел = module.render_body(
        ["test"], [], [], "0123456", module.Queue(1, 0), module.Proof(3, True)
    )
    assert "**2** из 3" in ниже and "Адресат — владелец" not in ниже
    assert "Адресат — владелец" in предел, "на пределе адресат обязан смениться"
    assert "не починка" in предел, "названо и то, чем следующий шаг НЕ является"


def test_the_counter_is_not_asked_when_nothing_holds_the_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Совещательное красное очередь не морозит — и владельца по нему не будят.

    Предел живёт у состояния «Проверка» контура 3, а оно наступает от красной
    ОБЯЗАТЕЛЬНОЙ. Иначе приоритет звучал бы всегда и перестал что-либо значить
    (051).
    """
    written = platform(
        monkeypatch,
        [{"name": "debt", "status": "completed", "conclusion": "failure"}],
        proofs=[{"conclusion": "failure"}] * 5,
    )
    assert module.main(["--repo", "o/r"]) == module.EXIT_RED
    assert written and "из 3" not in written[0], "счётчик попыток спрошен без заморозки"


def test_the_record_carries_the_counter_when_the_queue_is_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При заморозке счётчик попыток стоит в записи, а не в выводе шага (142)."""
    written = platform(
        monkeypatch,
        [{"name": "lint / lint", "status": "completed", "conclusion": "failure"}],
        proofs=[{"conclusion": "failure"}, {"conclusion": "success"}],
    )
    assert module.main(["--repo", "o/r"]) == module.EXIT_RED
    assert "**1** из 3" in written[0]


# --- запись мигания не заглатывает тело ----------------------------------------


# --- красное, пережившее слияние ----------------------------------------------


def records(*rows: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    """Записи проверок головы: имя, начало, исход, прогон."""
    return [
        {
            "name": name,
            "status": "completed",
            "started_at": started,
            "conclusion": outcome,
            "details_url": f"https://x/actions/runs/{run}/job/1",
        }
        for name, started, outcome, run in rows
    ]


def test_a_red_with_nothing_after_it_is_unfixed() -> None:
    """Последняя запись имени красна — значит красное пережило слияние.

    Позеленеть ему нечем: голова слитого изменения не пересобирается, и прогонов
    по ней никто не назначает.
    """
    runs = records(("task-items", "01", "failure", 77))
    assert module.unfixed_names(runs) == {"task-items": 77}


def test_a_red_followed_by_green_is_a_flake_not_unfixed() -> None:
    """Красное, за которым пришло зелёное, — МИГАНИЕ, и долгом оно не становится."""
    runs = records(("lint", "01", "failure", 77), ("lint", "02", "success", 78))
    assert module.unfixed_names(runs) == {}
    assert module.flaky_names(runs) == {"lint": 77}


def test_a_green_then_red_is_unfixed_not_a_flake() -> None:
    """Обратный порядок: зелёное, затем красное — это НЕ мигание, а долг.

    Порядок читается по времени начала записи. По порядку ответа площадки оба
    случая выглядели бы одинаково.
    """
    runs = records(("debt", "01", "success", 77), ("debt", "02", "failure", 78))
    assert module.unfixed_names(runs) == {"debt": 78}
    assert module.flaky_names(runs) == {}


def test_red_green_red_is_both_and_that_is_named() -> None:
    """Красное → зелёное → красное даёт ОБА факта, и это не дефект.

    Мигание на первом прогоне (зелёное получено без правки дерева) и долг на
    последнем (проверка так и осталась красной) — разные наблюдения о разных
    прогонах. Спрятать одно ради непересечения значило бы потерять его (016).

    ЗДЕСЬ БЫЛО ЛОЖНОЕ УТВЕРЖДЕНИЕ. Запись проекта обещала, что списки делят
    выборку без пересечения по ИМЕНИ; на этой последовательности обещание не
    выполнялось. Нашёл внешний взгляд находкой `359a558` на #379. Настоящая
    граница — разные ПРОГОНЫ, и держится она здесь.
    """
    runs = records(
        ("x", "01", "failure", 11), ("x", "02", "success", 22), ("x", "03", "failure", 33)
    )
    assert module.flaky_names(runs) == {"x": 11}
    assert module.unfixed_names(runs) == {"x": 33}
    assert module.flaky_names(runs)["x"] != module.unfixed_names(runs)["x"], (
        "оба списка назвали один прогон — тогда это действительно одна находка дважды"
    )


def test_an_unfixed_line_is_never_read_as_a_flake() -> None:
    """Строка долга не разбирается как мигание — ни при каком классе.

    Разделы живут в одном теле задачи, разбор у них общий. Пропущенный класс
    давал строку, НЕОТЛИЧИМУЮ от записи мигания, и следующий заход уносил долг
    слитого изменения в реестр миганий с выдуманным днём и местом (045). Нашёл
    внешний взгляд находкой `b5dd9e7` на #379.
    """
    for klass in ("", "advisory", "required", "unreviewed"):
        line = module.Unfixed("task-items", "#368", 77, klass).said()
        assert module.parse_flakes(line) == [], f"строка долга прочтена как мигание: {line!r}"
        assert module.NO_CLASS in line or klass in line, "класс не попал в запись"


def test_a_cancelled_last_record_is_not_unfixed() -> None:
    """Отменённая запись вердиктом не считается — её разбирает сводный гейт."""
    runs = records(("test", "01", "failure", 77), ("test", "02", "cancelled", 78))
    assert module.unfixed_names(runs) == {"test": 77}, "отменённая заслонила настоящее красное"


def test_unfixed_is_read_only_on_merged_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Красное ЖИВОГО изменения долгом по сделанному не считается.

    Там оно ещё держит очередь или ждёт починки: путать это с долгом значило бы
    звать чинить то, что в работе (195).
    """
    runs = records(("task-items", "01", "failure", 77))

    def paginate(path: str, *_: object, **__: object) -> list[dict[str, Any]]:
        return runs if "check-runs" in path else []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "merged_changes", lambda *a, **k: [])
    seen = module.seen_on_changes("o/r", "t", [], "16.09.2026", live((7, "aaa")))
    assert seen.unfixed == [], "красное живого изменения попало в долг по слитому"


def test_unfixed_on_a_merged_change_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """На слитом изменении красное записывается, и класс проверки назван.

    ЗАМЕР 16.09.2026: таких записей три — `task-items` на #366, #367 и #368, все
    совещательные. Увидел их человек глазами, механизма не было (002).
    """
    runs = records(("task-items", "01", "failure", 104367663319))

    def paginate(path: str, *_: object, **__: object) -> list[dict[str, Any]]:
        return runs if "check-runs" in path else []

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(
        module.ghrest,
        "merged_changes",
        lambda *a, **k: [{"number": 368, "head": {"sha": "ddd"}}],
    )
    answer = {"task-items": module.policy.Check(name="task-items", klass="advisory")}
    seen = module.seen_on_changes("o/r", "t", [], "16.09.2026", [], answer)
    assert [(one.name, one.where, one.klass) for one in seen.unfixed] == [
        ("task-items", "#368", "advisory")
    ]


def test_the_unfixed_section_names_its_window() -> None:
    """Раздел говорит, что он ЗЕРКАЛО ОКНА, а не накопитель (016, 049).

    Иначе исчезновение записи вместе с уходом изменения из окна читалось бы как
    «разобрано».
    """
    body = module.render_body(
        [], [], [], "abc1234", unfixed=[module.Unfixed("task-items", "#368", 77, "advisory")]
    )
    said = body[body.index("## Красное, пережившее") :]
    assert "зеркало окна" in said, "граница окна не названа — молчание прочтётся как «чисто»"
    assert "заводят задачу" in said, "не сказано, чем запись переживает окно"
    assert "task-items · #368 · advisory · прогон 77" in said


def test_an_empty_unfixed_section_says_so() -> None:
    """Пустой раздел называет себя — молчание не состояние (154)."""
    body = module.render_body([], [], [], "abc1234", unfixed=[])
    said = body[body.index("## Красное, пережившее") :]
    assert "Пусто" in said


def test_a_flake_name_does_not_swallow_the_body() -> None:
    """Имя мигания кончается на своей строке, а не на первой точке-разделителе.

    Класс с отрицанием матчит и перевод строки: имя первого мигания заглатывало
    ВСЁ тело до первой настоящей записи — вместе с заголовками разделов, — а
    сборка печатала это обратно. Реестр рос с каждым заходом и врал читателю
    двумя списками одного раздела.

    Замер 14.09.2026 на живом реестре: 19 «миганий», первое полтора килобайта,
    шесть разделов вместо трёх, тело выросло за один заход с 3052 до 3144 знаков.
    """
    body = "\n".join(
        [
            "## Не держит слияние, но не потеряно — источник 3",
            "",
            "- **debt**",
            "",
            "Починка такого бывает крупной — вплоть до переезда.",
            "",
            "## Мигания",
            "",
            "- ci-complete · 13.09.2026 · прогон 34721547141 · #266",
        ]
    )
    found = module.parse_flakes(body)
    assert len(found) == 1, f"записей мигания не одна, а {len(found)}"
    assert found[0].name == "ci-complete", f"имя заглотило соседние строки: {found[0].name!r}"
    assert "\n" not in found[0].name, "в имени мигания оказался перевод строки"


def test_a_bold_entry_of_another_section_is_not_a_flake() -> None:
    """Запись другого раздела (`- **имя**`) миганием не считается.

    Разделы «источник 0» и «источник 3» пишут имена жирным и без точек-
    разделителей: это другой род записи, и путать их значило бы переносить
    красноту головы в журнал миганий.
    """
    assert module.parse_flakes("- **test**\n- **debt**") == []


def test_a_duplicate_already_in_the_registry_is_healed_on_reading() -> None:
    """Повтор, лежащий в теле, при чтении отсеивается — реестр заживает сам.

    ЗАМЕР 16.09.2026: в #99 лежал ровно один такой повтор — `ci-complete` на
    прогоне 34721547141 у #266, дважды. Родился он 14.09, когда разбор строки
    был сломан; сам дефект починен, а след остался, и снять его было некому.
    Тело пересобирается ИЗ ПРОЧИТАННОГО, поэтому повтор переписывался бы
    обратно каждым заходом (049).
    """
    body = "\n".join(
        [
            "## Мигания",
            "",
            "- ci-complete · 13.09.2026 · прогон 34721547141 · #266",
            "- automerge · 13.09.2026 · прогон 34748699552 · #282",
            "- ci-complete · 13.09.2026 · прогон 34721547141 · #266",
        ]
    )
    found = module.parse_flakes(body)
    assert [(one.name, one.run) for one in found] == [
        ("ci-complete", 34721547141),
        ("automerge", 34748699552),
    ], "повтор не отсеян либо порядок первых наблюдений потерян"


def test_healing_keeps_the_first_day_not_the_last() -> None:
    """Выживает ПЕРВАЯ запись: день мигания — когда его увидели (154)."""
    body = "\n".join(
        [
            "- lint · 13.09.2026 · прогон 77 · #5",
            "- lint · 16.09.2026 · прогон 77 · #5",
        ]
    )
    found = module.parse_flakes(body)
    assert [(one.day) for one in found] == ["13.09.2026"], "день переписан последним наблюдением"


def test_the_two_places_ask_one_identity() -> None:
    """Отсев при чтении и добавление новой записи спрашивают ОДНО тождество.

    Ключи разошлись: чтение отсеивало по `(имя, прогон, где)`, добавление
    считало тождеством `(имя, прогон)`. Повтор одного прогона с разным «где»
    читатель не отсеивал, а добавление такой записи не сделало бы. Нашёл внешний
    взгляд находками `acdf734` и `f8d8414` на #372.

    Проверяется ПОВЕДЕНИЕМ, а не чтением исходника: два ключа могут совпасть
    сегодня и разойтись завтра, и держать надо результат.
    """
    # ФОРМА НАСТОЯЩАЯ: общая ветка НЕ подписывается — она умолчание, и «где» у
    # неё берётся из него. Подпись «общая ветка» строкой не бывает вовсе: в имя
    # места пробел не влезает (`\S+`), и такая строка не разобралась бы — то
    # есть проверка прошла бы на неразобранном входе, ничего не проверив (075).
    body = "\n".join(
        [
            "- ci-complete · 13.09.2026 · прогон 77",
            "- ci-complete · 13.09.2026 · прогон 77 · #266",
        ]
    )
    read = module.parse_flakes(body)
    assert read and read[0].where == module.SHARED, "подделка не собралась — предмета нет (075)"
    assert len(read) == 1, "чтение оставило две записи одного прогона — ключ отсева шире тождества"
    added = module.flakes_after(read, "ci-complete", 77, "16.09.2026", where="#999")
    assert added == read, "добавление сочло тот же прогон новым миганием"


def test_the_identity_is_the_name_and_the_run() -> None:
    """Тождество названо явно: имя и прогон, без «где» и без дня.

    Прогон принадлежит ровно одному месту, а день — свойство наблюдения. Ни то,
    ни другое не делает из одного мигания два.
    """
    one = module.Flake("lint", "13.09.2026", 77, "#5")
    other = module.Flake("lint", "16.09.2026", 77, "общая ветка")
    assert one.same == other.same == ("lint", 77)
    assert module.Flake("lint", "13.09.2026", 78, "#5").same != one.same, (
        "разные прогоны схлопнуты в одно мигание — потеряна частота"
    )


def test_one_run_of_two_names_is_two_records() -> None:
    """Разные имена на одном прогоне — две записи, а не повтор (016).

    Матричные ячейки и агрегат живут в одном прогоне: свести их в одну запись
    значило бы потерять, что именно мигало.
    """
    body = "\n".join(
        [
            "- test-matrix (3.12) · 13.09.2026 · прогон 77 · #5",
            "- test-matrix (3.13) · 13.09.2026 · прогон 77 · #5",
        ]
    )
    assert len(module.parse_flakes(body)) == 2, "разные имена схлопнуты в одну запись"


def test_the_body_does_not_grow_when_rebuilt() -> None:
    """Пересборка тела из него же самого не удлиняет его.

    Реестр объявлен зеркалом живых артефактов: заход собирает тело заново, и
    прогон разбора по собственному выводу обязан давать то же самое. Пока имя
    заглатывало строки, каждый заход добавлял разделы — зеркало превращалось в
    сугроб.
    """
    first = module.render_body(holds=[], rest=["debt"], flakes=[], sha="abcdef1")
    again = module.render_body(
        holds=[], rest=["debt"], flakes=module.parse_flakes(first), sha="abcdef1"
    )
    assert again == first, "пересборка изменила тело — зеркало копит вместо отражения"


# --- метка заморозки: состояние видно на изменении ------------------------------


def changes_and_writes(
    monkeypatch: pytest.MonkeyPatch, changes: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """Подделывает список живых изменений и записывает, что механизм пишет."""
    written: list[tuple[str, str]] = []

    def paginate(path: str, token: str, key: str | None = None) -> Any:
        assert "pulls?state=open" in path, path
        return iter(changes)

    def request(method: str, path: str, token: str, *rest: Any, **kw: Any) -> Any:
        written.append((method, path))
        return {}

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "request", request)
    return written


def change(number: int, *marks: str) -> Any:
    """Живое изменение — в тех полях, которые читает расстановка меток.

    Настоящим типом очереди, а не словарём: список приходит в `pause` уже
    разобранным, и подделка своей формы держала бы не тот предмет (049).
    """
    return live((number, f"голова{number}"), marks=marks)[0]


def test_the_freeze_is_marked_on_everything_but_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Красная обязательная — метка на всех живых, кроме несущих `fix-main`.

    Починка — единственный выход из заморозки, и остановить её значило бы запереть
    выход (126).
    """
    changes = [change(1), change(2, "fix-main"), change(3, module.LABEL_PAUSED)]
    written = changes_and_writes(monkeypatch, [])
    marked, freed = module.pause("o/r", "токен", changes, frozen=True, apply=True)
    assert (marked, freed) == ([1], []), "помечается только то, чего ещё не помечено"
    assert written == [("POST", "repos/o/r/issues/1/labels")]


def test_a_green_branch_takes_the_mark_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Позеленела общая ветка — метку снимает тот же шаг, а не человек.

    Метка — зеркало состояния ветки, а не журнал события: снятие рукой означало бы
    второго владельца у одной метки (022, 049).
    """
    changes = [change(1, module.LABEL_PAUSED), change(2), change(3, module.LABEL_PAUSED)]
    written = changes_and_writes(monkeypatch, [])
    marked, freed = module.pause("o/r", "токен", changes, frozen=False, apply=True)
    assert (marked, freed) == ([], [1, 3])
    assert all(method == "DELETE" for method, _ in written)
    assert written[0][1] == "repos/o/r/issues/1/labels/paused%2Fmain-red", (
        "косая черта в имени метки обязана быть закодирована: иначе площадка "
        "ищет метку не там и отвечает «не найдено», а снятие выглядит сделанным (045)"
    )


def test_a_dry_walk_marks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сухой заход называет, что сделал бы, и не пишет ничего."""
    written = changes_and_writes(monkeypatch, [])
    marked, freed = module.pause("o/r", "токен", [change(1)], frozen=True, apply=False)
    assert (marked, freed) == ([1], []), "сказано, что было бы помечено"
    assert written == [], "сухой заход площадку не трогает"


def test_a_refused_listing_does_not_drop_the_red(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Список изменений не прочитан — заход не падает: краснота важнее меток (084).

    Отказ ловится ОДИН раз, в чтении, а не в каждом потребителе: читателей у
    списка трое, и три своих обработчика отказа разошлись бы между собой молча
    (090). Потребители дальше видят `None` и каждый говорит своё.
    """

    def refuse(path: str, token: str, key: str | None = None) -> Any:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(module.ghrest, "paginate", refuse)
    assert module.live_changes("o/r", "токен") is None
    said = capsys.readouterr().out
    assert "живые изменения не прочитаны" in said
    assert "площадка не ответила" in said, "причина отказа потеряна (154)"
    assert module.pause("o/r", "токен", None, frozen=True, apply=True) == ([], [])
    assert "метки заморозки не расставлены" in capsys.readouterr().out


def test_a_refused_write_names_the_change(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ на одном изменении назван и не уносит остальные (154)."""

    def request(method: str, path: str, token: str, *rest: Any, **kw: Any) -> Any:
        if "/issues/1/" in path:
            raise module.ghrest.TransportError("нет прав")
        return {}

    monkeypatch.setattr(module.ghrest, "request", request)
    marked, freed = module.pause("o/r", "токен", [change(1), change(2)], frozen=True, apply=True)
    assert (marked, freed) == ([2], [])
    assert "#1: метка заморозки не поставлена" in capsys.readouterr().out


# --- мигание на голове ИЗМЕНЕНИЯ перезапускается тоже (#584) ------------------


def rerun_said(
    monkeypatch: pytest.MonkeyPatch,
    runs: list[dict[str, Any]],
    *,
    tries: int = 1,
    apply: bool = False,
) -> tuple[str, list[int]]:
    """Что решил перезапуск на голове изменения и что он тронул у площадки."""
    hit: list[int] = []
    monkeypatch.setattr(module, "attempt", lambda repo, run, token: tries)
    monkeypatch.setattr(module, "rerun_failed", lambda repo, run, token: hit.append(run))
    said = module.rerun_on_change("o/r", "токен", 7, runs, [*REQUIRED, AGGREGATE], {}, apply=apply)
    return said, hit


def test_a_lone_red_on_a_change_is_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одиночное красное на голове ИЗМЕНЕНИЯ перезапускается — как на общей ветке.

    ЗАМЕР, РАДИ КОТОРОГО ЭТО ЗАВЕДЕНО (#584): в реестре #99 двадцать девять
    миганий, и ДВАДЦАТЬ из них — на голове изменения, где перезапуска не было
    вовсе. Каждое гасил человек рукой либо оно гасло следующим толчком.

    Отсрочка была объявлена с условием пересмотра — «пока эти записи не назовут
    первое имя», — и имя названо: `ci-complete`, семнадцать раз
    ([126](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/126-a-freeze-needs-a-thaw-path.md)).

    ИМЯ ЗДЕСЬ СМЕНИЛОСЬ С `lint` НА `ci-complete` (#607). Прежняя редакция
    ставила одиночным `lint` и ждала перезапуска — то есть требовала от
    механизма ровно того, что решение 013 запрещает: перезапуска обязательного,
    которое СУДИТ ДЕРЕВО. Приёмка была зелёной потому, что код тогда
    перезапускал все семь; исправился код — исправилась и она.
    """
    said, hit = rerun_said(monkeypatch, [record(AGGREGATE, "failure", run=42)], apply=True)
    assert "перезапущен" in said, said
    assert hit == [42], "прогон не перезапущен вовсе"


def test_two_reds_on_a_change_are_a_defect_not_a_flake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Два красных — дефект, а не осечка: перезапуска нет.

    Половина, без которой механизм неотличим от «перезапускать всё красное» —
    а такой прячет настоящий дефект за зелёным со второго раза (124).
    """
    said, hit = rerun_said(
        monkeypatch,
        [record("lint", "failure", run=42), record("test", "failure", run=42)],
        apply=True,
    )
    assert "перезапуска не будет" in said, said
    assert hit == [], "перезапущено то, что перезапускать нельзя"


def test_a_second_attempt_on_a_change_is_not_rerun_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Перезапуск ОДИН: вторая попытка уже была, и третьей не будет.

    Без этой половины механизм перезапускал бы вечно, и мигание, уже
    записанное, гасилось бы снова и снова вместо разбора.

    ПРИЧИНА ПРОВЕРЯЕТСЯ ПОИМЁННО, А НЕ ПО «перезапуска не будет». Прежняя
    редакция ставила здесь `lint` и смотрела только на общую часть сообщения —
    и после #607 осталась бы зелёной по ДРУГОЙ причине: «обязательное вне
    списка». Бездействие совпало бы, предмет — нет, и проверка сторожила бы не
    то ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    said, hit = rerun_said(monkeypatch, [record(AGGREGATE, "failure", run=42)], tries=2, apply=True)
    assert module.ALREADY in said, said
    assert hit == [], "перезапущено во второй раз"


def test_a_green_change_head_asks_the_platform_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Зелёная голова не стоит НИ ОДНОГО вызова: спрашивать нечего.

    Голов столько, сколько живых изменений, и вызов на каждой платится из общей
    квоты
    ([058](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/058-when-the-quota-is-out-stop.md)).
    """
    asked: list[int] = []

    def counted(repo: str, run: int, token: str) -> int:
        asked.append(run)
        return 1

    monkeypatch.setattr(module, "attempt", counted)
    monkeypatch.setattr(module, "rerun_failed", lambda repo, run, token: None)
    said = module.rerun_on_change("o/r", "токен", 7, [record("lint")], REQUIRED, {}, apply=True)
    assert said == "", said
    assert asked == [], "у зелёной головы спрашивали номер попытки"


def test_the_platform_is_asked_only_after_the_cheap_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Номер попытки спрашивается ПОСЛЕ условий, выводимых из прочитанного.

    Два красных — это видно из уже прочитанных записей, и платить за ответ
    площадки, который ничего не изменит, незачем (058).
    """
    asked: list[int] = []

    def counted(repo: str, run: int, token: str) -> int:
        asked.append(run)
        return 1

    monkeypatch.setattr(module, "attempt", counted)
    monkeypatch.setattr(module, "rerun_failed", lambda repo, run, token: None)
    module.rerun_on_change(
        "o/r",
        "токен",
        7,
        [record("lint", "failure", run=42), record("test", "failure", run=42)],
        REQUIRED,
        {},
        apply=True,
    )
    assert asked == [], "площадку спросили там, где ответ ничего не решал"


def test_the_decision_is_the_same_one_as_the_shared_branch() -> None:
    """Условия у изменения и у общей ветки ОДНИ, а не две копии (022, 090).

    Проверяется не текст, а поведение: решение на голове изменения обязано
    совпасть с тем, что отдаёт `rerun_reason` — тот же, по которому живёт общая
    ветка. Разъедутся — здесь покраснеет.
    """
    required = [*REQUIRED, AGGREGATE]
    holds, rest = module.split(module.red_of([record(AGGREGATE, "failure", run=42)]), required)
    assert module.rerun_reason(holds, rest, 42, 1, {}, module.rerunnable()) == ""
    holds, rest = module.split(
        module.red_of([record("lint", "failure", run=42), record("test", "failure", run=42)]),
        required,
    )
    assert module.rerun_reason(holds, rest, 42, 1, {}, module.rerunnable()) != ""


# --- перезапуск решается историей мигания, а не классом (#607) ----------------


def test_a_lone_required_red_outside_the_list_is_not_rerun() -> None:
    """Обязательное вне разрешённого списка НЕ перезапускается.

    ЗАМЕР, РАДИ КОТОРОГО ПРОВЕРКА ЗАВЕДЕНА (21.09.2026). Код перезапускал ВСЕ
    СЕМЬ обязательных: одиночное красное доходило до `one_fall` и проходило его
    ВАКУУМНО — `all(...)` по пустому списку истинно. То есть `lint`
    перезапустился бы наравне с `ci-complete`, а решение 013 говорит прямо:
    семь обязательных СЧИТАЮТ ДЕРЕВО, их красное означает дефект, и зелёное со
    второго раза скрыло бы находку
    ([124](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/124-rerun-the-minimum-and-record-the-flake.md)).

    Комментарий над тем же кодом обещал обратное — «обязательные не
    перезапускаются никогда», — и проза расходилась с кодом.
    """
    said = module.rerun_reason(["lint"], [], 1, 1, {}, module.rerunnable())
    assert said == module.REQUIRED_UNLISTED, said


def test_a_listed_check_is_rerun_whatever_its_class() -> None:
    """Имя из списка перезапускается независимо от класса.

    Вторая половина: без неё «обязательное не перезапускается» вернулось бы
    запретом по КЛАССУ, а решает история мигания. `ci-complete` обязателен и
    дерева не судит — он читатель чужих записей, и семнадцать его миганий из
    двадцати девяти это показали.
    """
    assert module.rerun_reason(["ci-complete"], [], 1, 1, {}, module.rerunnable()) == ""


def test_the_aggregate_with_its_matrix_is_still_one_fall() -> None:
    """Агрегат вместе со своей матрицей — ОДНО падение под разными именами.

    Ради этого случая `one_fall` и заведён, и список имён здесь ни при чём:
    агрегат краснеет ровно потому, что красна ячейка. Спрашивать у списка
    каждое из двух имён значило бы разрушить его смысл.
    """
    said = module.rerun_reason(
        ["test"], ["test-matrix (3.12)"], 1, 1, {"test": {"test-matrix"}}, module.rerunnable()
    )
    assert said == "", said


def test_the_listed_names_carry_a_measurement() -> None:
    """У каждого имени списка названы причина И замер (014, 154).

    Имя без замера — догадка, а список заведён ровно затем, чтобы догадок в нём
    не было: «перезапускать всё красное» прячет дефект.
    """
    said = module.rerunnable()
    assert "ci-complete" in said, "имя с семнадцатью миганиями в список не попало"
    for name, why in said.items():
        assert why.strip(), f"{name}: имя без причины"
