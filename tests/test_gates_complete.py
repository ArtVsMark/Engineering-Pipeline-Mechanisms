"""Вердикт сводного гейта проверяется тем, что он обязан отвергнуть."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, load_script

module = load_script("ci_complete.py")

#: Шапка ответа проекта: схема и диапазон совместимости — их требует разбор.
HEAD = 'schema: 4\ncontract: ">=0.1,<0.2"\n'
REQUIRED = ["lint", "test"]


def run(
    name: str,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: str = "1",
    started_at: str = "2026-09-10T06:00:00Z",
) -> dict[str, Any]:
    """Собирает одну запись проверки в том виде, в каком её отдаёт площадка."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started_at,
        "details_url": f"https://github.com/o/r/actions/runs/{run_id}/job/9",
    }


def test_all_green_is_green() -> None:
    """Все объявленные зелёные — вердикт зелёный."""
    problems, waiting = module.verdict([run("lint"), run("test")], REQUIRED, "ci-complete")
    assert (problems, waiting) == ([], False)


def test_missing_record_is_rejected() -> None:
    """Записи нет на голове: прогон не стартовал, а не «зелено» (075)."""
    problems, _ = module.verdict([run("lint")], REQUIRED, "ci-complete")
    assert len(problems) == 1 and "записи нет" in problems[0]


def test_no_records_on_the_head_is_rejected() -> None:
    """Записей на голове нет ни одной: прогон не стартовал, а не «все прошли».

    Отдельно от недостачи одного имени: пустой вход — это отсутствие предмета
    проверки, и гейт, не нашедший предмета, обязан падать (075). Проверяется
    тем, что названы ОБА объявленных имени, а не «есть хотя бы одна находка».
    """
    problems, waiting = module.verdict([], REQUIRED, "ci-complete")
    assert not waiting
    assert {problem.split(":")[0] for problem in problems} == set(REQUIRED)
    assert all("записи нет" in problem for problem in problems)


def test_both_failures_are_named() -> None:
    """Вердикт выносится после последнего случая, а не на первой находке (159).

    Ранний выход снаружи неотличим от рабочего набора: первый отказ назван,
    остальные превращаются в печать. Проверяется тем, что отказов ровно два и
    названы оба, а не «есть хотя бы один».
    """
    problems, _ = module.verdict(
        [run("lint", conclusion="failure"), run("test", conclusion="failure")],
        REQUIRED,
        "ci-complete",
    )
    assert len(problems) == 2
    assert {problem.split(":")[0] for problem in problems} == {"lint", "test"}


def test_skipped_is_rejected() -> None:
    """Пропущенный джоб — отказ: иначе выключение шага обходит гейт."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="skipped")], REQUIRED, "ci-complete"
    )
    assert any("пропущен" in problem for problem in problems)


def test_all_cancelled_is_rejected() -> None:
    """Если все записи имени отменены, живого вердикта нет — это отказ."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="cancelled")], REQUIRED, "ci-complete"
    )
    assert any("все записи отменены" in problem for problem in problems)


def test_a_cancelled_record_does_not_hide_a_queued_job() -> None:
    """Отменённая запись прежнего захода не прячет свой же джоб в очереди.

    Замер 10.09.2026, изменение #145: сводный опросил голову в 16:33:40, у
    `test` на ней лежала одна запись — отменённая в 16:33:02 вытесненным
    заходом. Свой `test` ждал матрицу через `needs` и завершился зелёным в
    16:33:57, на семнадцать секунд позже вердикта. Гейт объявил «все записи
    отменены», хотя ждать оставалось семнадцать секунд.

    Красное было о гонке, а не о работе: следующий заход дал зелёное на том же
    коммите — то есть мигание (124), которое чинят, а не перезапускают.
    """
    runs = [run("lint"), run("test", conclusion="cancelled")]
    mine = {"lint": "completed", "test": "queued"}
    problems, waiting = module.verdict(runs, REQUIRED, "ci-complete", mine=mine)
    assert problems == []
    assert waiting is True


def test_a_cancelled_record_of_a_foreign_name_is_still_a_refusal() -> None:
    """Дыры это не открывает: ждём только объявленный СВОИМ прогоном джоб.

    Имя, которого в своём прогоне нет вовсе, с одной отменённой записью
    остаётся отказом. Иначе достаточно было бы отменить прогон, чтобы
    обязательная проверка перестала держать слияние (075).
    """
    runs = [run("lint"), run("test", conclusion="cancelled")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete", mine={"lint": "completed"})
    assert any("все записи отменены" in problem for problem in problems)


def test_a_finished_job_of_ours_does_not_excuse_a_cancelled_record() -> None:
    """Свой джоб завершён, а живой записи нет — ждать больше нечего.

    Это то же различие, что у имени без записей: `completed` в своём прогоне
    означает, что запись уже не появится, и отказ остаётся отказом.
    """
    runs = [run("lint"), run("test", conclusion="cancelled")]
    mine = {"lint": "completed", "test": "completed"}
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete", mine=mine)
    assert any("все записи отменены" in problem for problem in problems)


def test_cancelled_beside_a_live_record_is_ignored() -> None:
    """Отмена от группы отмены не делает здоровую голову красной.

    Новый толчок или новая метка гасят прогон на той же голове, и его записи
    остаются лежать рядом с живыми. Первый прогон на площадке покраснел именно
    на этом: `filter=latest` записи отменённого прогона не отсекает.
    """
    runs = [
        run("lint", conclusion="cancelled"),
        run("lint"),
        run("test", conclusion="cancelled"),
        run("test"),
    ]
    assert module.verdict(runs, REQUIRED, "ci-complete") == ([], False)


def test_failure_beside_a_cancelled_record_still_rejects() -> None:
    """Отбрасывание отмен не прячет настоящий отказ."""
    runs = [run("lint"), run("test", conclusion="cancelled"), run("test", conclusion="failure")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete")
    assert any("failure" in problem for problem in problems)


def test_failure_is_rejected() -> None:
    """Красный сосед делает сводный красным, а не пропущенным."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="failure")], REQUIRED, "ci-complete"
    )
    assert any("failure" in problem for problem in problems)


def test_pending_makes_it_wait() -> None:
    """Незавершённый сосед означает ожидание, а не вердикт."""
    _, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress", conclusion=None)],
        REQUIRED,
        "ci-complete",
    )
    assert waiting is True


def test_two_live_records_with_one_name_are_flagged() -> None:
    """Одно обязательное имя от двух живых прогонов — вердикт неоднозначен."""
    problems, _ = module.verdict([run("lint"), run("test"), run("test")], REQUIRED, "ci-complete")
    assert any("живых записей с одним именем" in problem for problem in problems)


def test_a_record_with_a_conclusion_is_not_awaited() -> None:
    """Запись с исходом завершена, каким бы ни было её состояние.

    Погашенный группой отмены прогон оставляет на голове запись со `status:
    in_progress` и уже проставленным `conclusion`. Ждать её нечего, а ждали бы
    её вечно: новых событий у изменения больше нет, и сдвинуть её нечем.
    Замер 09.09.2026: очередь встала на изменении #73 при девяти зелёных
    записях из-за одной такой записи-зомби.
    """
    problems, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress")], REQUIRED, "ci-complete"
    )
    assert (problems, waiting) == ([], False)


def test_a_record_without_a_conclusion_is_still_awaited() -> None:
    """Настоящая идущая запись по-прежнему останавливает вердикт (097).

    Иначе лечение хуже болезни: гейт перестал бы ждать вообще и выносил бы
    вердикт по недосчитанной голове.
    """
    problems, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress", conclusion=None)],
        REQUIRED,
        "ci-complete",
    )
    assert waiting and not problems


def test_itself_is_not_awaited() -> None:
    """Сводный не ждёт собственной записи — иначе он не дождётся никогда."""
    problems, waiting = module.verdict(
        [run("lint"), run("test")], [*REQUIRED, "ci-complete"], "ci-complete"
    )
    assert (problems, waiting) == ([], False)


def test_records_of_a_foreign_run_do_not_confuse_the_verdict() -> None:
    """Второй прогон того же файла на голове — штатное событие, а не беда.

    Снятие черновика или новое событие запускают ci заново на том же коммите, и
    каждое имя оказывается представлено дважды при обоих здоровых прогонах.
    Замер 09.09: это уронило сводный гейт при восьми зелёных соседях.
    """
    runs = [
        run("lint", run_id="old"),
        run("test", run_id="old"),
        run("lint", run_id="mine"),
        run("test", run_id="mine"),
    ]
    assert module.verdict(runs, REQUIRED, "ci-complete", "mine") == ([], False)


def test_a_foreign_record_still_counts_when_own_run_has_none() -> None:
    """Имя, которого свой прогон не выдаёт, берётся у чужого — иначе пропуск."""
    runs = [run("lint", run_id="mine"), run("test", conclusion="failure", run_id="old")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete", "mine")
    assert any("failure" in problem for problem in problems)


def test_two_records_of_the_same_run_are_still_ambiguous() -> None:
    """Внутри одного прогона два одинаковых имени — по-прежнему неоднозначность."""
    runs = [run("lint", run_id="mine"), run("test", run_id="mine"), run("test", run_id="mine")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete", "mine")
    assert any("живых записей с одним именем" in problem for problem in problems)


# --- наполнение опроса приходит из данных ------------------------------------


def test_two_sources_of_subject_are_refused() -> None:
    """Наполнение объявлено дважды — отказ, а не «возьмём тот, что подробнее».

    Два списка одного и того же расходятся молча (022), и молчание здесь стоит
    дороже всего: разойдясь, они дадут зелёный гейт на неполном опросе.
    """
    try:
        module.sources(".pipeline.yml", "lint,test")
    except module.NotRun as exc:
        assert "дважды" in str(exc)
    else:
        raise AssertionError("два источника наполнения приняты молча")


def test_policy_gives_both_classes(tmp_path: Any) -> None:
    """Из данных приходят обязательные и совещательные — разными списками."""
    answer = tmp_path / ".pipeline.yml"
    answer.write_text(
        HEAD + "checks:\n  lint: required\n  review:\n    class: advisory\n"
        '    why: слияния не держит\n    addressee: "#23"\n'
        "  e2e:\n    class: off\n    why: нет окружения\n",
        encoding="utf-8",
    )
    required, advisory = module.sources(str(answer), "")
    assert required == ["lint"]
    assert advisory == ["review"]


def test_advisory_missing_record_is_not_a_problem() -> None:
    """У совещательной отсутствие записи законно: она могла не идти вовсе."""
    problems, _ = module.verdict([], ["review"], "ci-complete", strict_missing=False)
    assert problems == []


def test_advisory_red_is_still_reported() -> None:
    """Но красное у совещательной не молчит: иначе это «выключена» повежливее."""
    failed = run("review", conclusion="failure")
    problems, _ = module.verdict([failed], ["review"], "ci-complete", strict_missing=False)
    assert len(problems) == 1 and "review" in problems[0]


def test_required_missing_record_is_still_a_refusal() -> None:
    """У обязательной послабления нет: нет записи — нет вердикта (075)."""
    problems, _ = module.verdict([], ["lint"], "ci-complete")
    assert len(problems) == 1 and "записи нет" in problems[0]


# --- одна запись на имя: чтение записей проверок -------------------------------------------------


def test_two_runs_on_one_head_are_not_an_ambiguity() -> None:
    """Два прогона `ci` на одной голове — штатное следствие двух событий.

    Сводный гейт различает своё от чужого по номеру прогона; у очереди своего
    прогона среди них нет. Замер 09.09.2026: на первом живом заходе очередь
    отвергла изменение #57 с шестью зелёными именами, потому что каждое было
    представлено дважды.
    """
    runs = [run("lint"), run("lint"), run("test"), run("test")]
    assert sorted(run["name"] for run in module.worst_per_name(runs)) == ["lint", "test"]


def test_the_worst_record_of_a_name_wins() -> None:
    """Из двух записей имени берётся ХУДШАЯ, а не первая попавшаяся.

    Взять любую значило бы иногда сливать красное: зелёная запись попадалась бы
    первой. Ошибаться здесь можно только в сторону строгости (051).
    """
    kept = module.worst_per_name([run("test"), run("test", conclusion="failure")])
    assert [run["conclusion"] for run in kept] == ["failure"]


def test_a_live_record_beats_a_cancelled_one() -> None:
    """Отменённая ниже любой живой: она гасится новым прогоном, а не ломает."""
    kept = module.worst_per_name([run("lint", conclusion="cancelled"), run("lint")])
    assert [run["conclusion"] for run in kept] == ["success"]


def test_all_cancelled_stays_cancelled() -> None:
    """Если живой записи у имени нет вовсе, отмена доезжает до вердикта."""
    kept = module.worst_per_name(
        [run("lint", conclusion="cancelled"), run("lint", conclusion="cancelled")]
    )
    assert [run["conclusion"] for run in kept] == ["cancelled"]


def test_a_zombie_record_does_not_stop_the_queue() -> None:
    """Запись `in_progress` с исходом очередь не останавливает.

    Она завершена, и ждать её нечего: новых событий у изменения больше нет.
    Замер 09.09.2026 — изменение #73 стояло при девяти зелёных записях.
    """
    kept = module.worst_per_name([run("pipeline", status="in_progress")])
    assert module.severity(kept[0]) == 0


def test_pending_beats_success_but_not_failure() -> None:
    """Идущая запись важнее зелёной: имя ещё не досчитано, а не пройдено."""
    pending = module.worst_per_name(
        [run("test"), run("test", conclusion=None, status="in_progress")]
    )
    assert [run["status"] for run in pending] == ["in_progress"]
    red = module.worst_per_name(
        [
            run("test", conclusion=None, status="in_progress"),
            run("test", conclusion="failure"),
        ]
    )
    assert [run["conclusion"] for run in red] == ["failure"]


def test_a_fresh_record_beats_a_stale_one() -> None:
    """Свежая запись имени важнее старой, даже если старая хуже.

    ЗАМЕР 10.09.2026, изменение #102. Новый толчок погасил прежний прогон, но
    его записи остались лежать на голове: агрегат `test` — `failure` в 06:27:23
    у погашенного и `success` в 06:27:57 у живого. Разбор брал худшую из всех —
    и голова становилась красной НАВСЕГДА: новых событий у изменения больше не
    будет, а зелёное живого прогона проигрывало мёртвому.
    """
    kept = module.worst_per_name(
        [
            run("test", conclusion="failure", started_at="2026-09-10T06:27:23Z"),
            run("test", conclusion="success", started_at="2026-09-10T06:27:57Z"),
        ]
    )
    assert [item["conclusion"] for item in kept] == ["success"]


def test_a_stale_green_does_not_hide_a_fresh_red() -> None:
    """И наоборот: свежее красное не прячется за старым зелёным.

    Свежесть решает в обе стороны, иначе это была бы не свежесть, а поблажка.
    """
    kept = module.worst_per_name(
        [
            run("test", conclusion="success", started_at="2026-09-10T06:27:23Z"),
            run("test", conclusion="failure", started_at="2026-09-10T06:27:57Z"),
        ]
    )
    assert [item["conclusion"] for item in kept] == ["failure"]


def test_records_of_one_moment_are_still_judged_by_severity() -> None:
    """Записи, начатые в одну секунду, разбираются по тяжести — как и прежде.

    Это случай двух прогонов одного файла от двух событий: обе записи живые, и
    ошибаться среди них можно только в сторону строгости (051).
    """
    kept = module.worst_per_name(
        [
            run("test", conclusion="success", started_at="2026-09-10T06:00:00Z"),
            run("test", conclusion="failure", started_at="2026-09-10T06:00:00Z"),
        ]
    )
    assert [item["conclusion"] for item in kept] == ["failure"]


def test_a_record_without_a_start_is_the_oldest() -> None:
    """Запись без времени начала считается самой старой, а не самой свежей.

    Неизвестное время не должно давать преимущество: иначе запись, у которой
    площадка поля не заполнила, вытесняла бы настоящую (045).
    """
    kept = module.worst_per_name(
        [
            run("test", conclusion="success", started_at="2026-09-10T06:00:00Z"),
            {"name": "test", "status": "completed", "conclusion": "failure"},
        ]
    )
    assert [item["conclusion"] for item in kept] == ["success"]


# --- джоб, который ещё не стартовал ------------------------------------------
#
# ЗАМЕР 10.09.2026: агрегат `test` ждёт матрицу версий через `needs`, а сводный
# гейт опрашивает голову раньше — записи ещё нет. Отсутствие читалось как
# «прогон не стартовал», и изменение #102 получило красный обязательный
# контекст при полностью зелёных проверках.


def test_a_queued_job_is_waited_for_not_failed() -> None:
    """Джоб своего прогона, ещё не стартовавший, — ожидание, а не отказ.

    Его отличает от «не стартует вовсе» ровно одно: он объявлен в своём
    прогоне и не завершён. Без этого различия гейт краснеет на всяком джобе с
    `needs`, то есть на здоровом прогоне.
    """
    problems, waiting = module.verdict(
        [run("lint")], ["lint", "test"], "ci-complete", mine={"test": "queued"}
    )
    assert problems == []
    assert waiting is True


def test_a_job_absent_from_the_run_is_still_a_refusal() -> None:
    """Имени нет ни на голове, ни среди джобов прогона — отказ, как и прежде.

    Это вторая половина различия: «ещё не стартовал» и «не будет никогда»
    снаружи одинаковы, и поблажка второму означала бы зелёное на прогоне,
    которого не было (075).
    """
    problems, waiting = module.verdict(
        [run("lint")], ["lint", "test"], "ci-complete", mine={"lint": "completed"}
    )
    assert waiting is False
    assert any("не стартовал" in problem for problem in problems)


def test_a_completed_job_without_a_record_is_a_refusal() -> None:
    """Джоб завершился, а записи нет — отказ: ждать больше нечего."""
    problems, _ = module.verdict(
        [run("lint")], ["lint", "test"], "ci-complete", mine={"test": "completed"}
    )
    assert any("не стартовал" in problem for problem in problems)


def test_without_the_run_the_strictness_stays() -> None:
    """Не спросили о своём прогоне — разбор возвращается к прежней строгости.

    Молчаливая поблажка на неизвестности хуже лишнего красного: она делает
    гейт зелёным ровно тогда, когда он не смог проверить (045).
    """
    problems, waiting = module.verdict([run("lint")], ["lint", "test"], "ci-complete")
    assert waiting is False
    assert problems


def test_a_cancelled_record_never_outranks_a_live_one() -> None:
    """Отменённая запись не побеждает живую, даже будучи свежее.

    ЗАМЕР 10.09.2026, изменение #109. Семь прогонов подряд гасили друг друга:
    последней записью имени оказалась отменённая в 07:51, а зелёная — в 07:50.
    Разбор, ставший считать по свежести, объявил «все записи отменены» и выдал
    метку источника 2 изменению с зелёным вердиктом.

    Вердикта в отменённой записи нет НИКАКОГО, поэтому свежесть между ней и
    живой ничего не значит.
    """
    kept = module.worst_per_name(
        [
            run("test", conclusion="success", started_at="2026-09-10T07:50:43Z"),
            run("test", conclusion="cancelled", started_at="2026-09-10T07:51:35Z"),
        ]
    )
    assert [item["conclusion"] for item in kept] == ["success"]


def test_all_cancelled_still_reaches_the_verdict() -> None:
    """Если живой записи у имени нет вовсе, отмена доезжает до вердикта.

    Пройденной она не считается, и молчаливое «зелено» здесь было бы ложью:
    вердикта у этого имени просто нет (075).
    """
    kept = module.worst_per_name(
        [
            run("test", conclusion="cancelled", started_at="2026-09-10T07:50:00Z"),
            run("test", conclusion="cancelled", started_at="2026-09-10T07:51:00Z"),
        ]
    )
    assert [item["conclusion"] for item in kept] == ["cancelled"]


def test_freshness_still_decides_among_live_records() -> None:
    """Между живыми записями по-прежнему решает свежесть.

    Иначе возвращается прежний дефект: красная запись погашенного прогона
    держала голову красной навсегда.
    """
    kept = module.worst_per_name(
        [
            run("test", conclusion="failure", started_at="2026-09-10T06:27:23Z"),
            run("test", conclusion="success", started_at="2026-09-10T06:27:57Z"),
        ]
    )
    assert [item["conclusion"] for item in kept] == ["success"]


def test_a_skipped_record_never_outranks_a_live_one() -> None:
    """Свежая пропущенная запись не вытесняет живую зелёную.

    Агрегат `test` при отменённой матрице кладёт `skipped`, и эта запись, будучи
    свежее, объявляла отказ поверх зелёного вердикта живого прогона. Тот же
    класс, что был у отменённой записи, только на другом исходе. Нашёл разбор
    на #107.
    """
    runs = [
        {"name": "test", "conclusion": "success", "started_at": "2026-09-10T07:50:00Z"},
        {"name": "test", "conclusion": "skipped", "started_at": "2026-09-10T07:51:00Z"},
    ]
    assert module.worst_per_name(runs)[0]["conclusion"] == "success"


def test_a_lone_skipped_required_is_still_a_refusal() -> None:
    """Пропущенная в одиночестве по-прежнему отказ: 040 не ослаблен.

    Разница между «есть живая запись рядом» и «живой нет вовсе» держит здесь обе
    стороны: молчаливое «зелено» на пропуске было бы ровно той дырой, от которой
    правило и написано.
    """
    problems, _ = module.verdict(
        [{"name": "test", "conclusion": "skipped"}], ["test"], "ci-complete"
    )
    assert problems and "пропущен" in problems[0]


def test_a_record_without_a_verdict_is_named_as_such() -> None:
    """«Без вердикта» — это отмена и пропуск, и список закрыт.

    Живые исходы сюда не попадают ни при каких обстоятельствах: иначе первый
    ключ начал бы прятать настоящее красное.
    """
    assert not module.has_verdict({"conclusion": "cancelled"})
    assert not module.has_verdict({"conclusion": "skipped"})
    assert module.has_verdict({"conclusion": "failure"})
    assert module.has_verdict({"conclusion": "success"})


def test_a_job_with_a_conclusion_is_not_still_coming(monkeypatch: pytest.MonkeyPatch) -> None:
    """Джоб с проставленным исходом «ещё идущим» не считается.

    Тот же класс рассинхрона, что у записей проверок: площадка выставляет
    исход, а состояние остаётся переходным. Прочитанный по одному лишь
    `status`, такой джоб держал бы `waiting=True` до тайм-аута вместо отказа.
    Нашёл внешний взгляд на #148.
    """
    payload = {
        "jobs": [
            {"name": "test", "status": "in_progress", "conclusion": "failure"},
            {"name": "lint", "status": "in_progress", "conclusion": None},
        ]
    }
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: payload)
    roster = module.roster_of("o/r", "7", "token")
    assert "test" not in roster.running
    assert roster.running["lint"] == "in_progress"
    assert module.still_coming("test", roster.running) is False
    assert module.still_coming("lint", roster.running) is True


def test_the_summarised_run_is_the_freshest_one_on_the_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сводится самый свежий прогон `ci` на голове, а не первый попавшийся.

    Два прогона одного файла на одной голове — штатное следствие двух событий
    (толчок и снятие черновика). Группа отмены гасит предыдущий, и последнее
    слово обязано остаться за новым (179).
    """
    payload = {
        "workflow_runs": [
            {"name": "ci", "id": 11, "created_at": "2026-09-11T14:45:17Z"},
            {"name": "ci", "id": 22, "created_at": "2026-09-11T14:45:18Z"},
            {"name": "review", "id": 33, "created_at": "2026-09-11T14:46:00Z"},
        ]
    }
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: payload)
    found = module.summarised_run("o/r", "abc", "token")
    assert found is not None and found["id"] == 22


def test_no_summarised_run_is_waiting_not_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Прогона, который сводится, ещё нет — это ожидание, а не отказ и не «зелено».

    События приходят в своём порядке, и сводный гейт легко стартует раньше
    `ci`. Отказ здесь был бы красным на здоровом, молчаливое «зелено» —
    нарушением 075.
    """
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: {"workflow_runs": []})
    assert module.summarised_run("o/r", "abc", "token") is None
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda *_, **__: (_ for _ in ()).throw(module.ghrest.TransportError("площадка молчит")),
    )
    assert module.summarised_run("o/r", "abc", "token") is None


def test_the_gate_does_not_take_its_own_run_for_the_summarised_one() -> None:
    """Номер прогона больше НЕ берётся из окружения — он чужой всем соседям.

    Пока гейт был джобом внутри `ci`, `GITHUB_RUN_ID` совпадал со сводимым
    прогоном. После переезда в свой файл совпадение исчезло, и от этого разом
    отказали оба различия, на которых держится разбор гонки: предпочтение
    записей сводимого прогона и `roster_of`. Замер 11.09.2026 — #199 получил
    красное «все записи отменены» за 51 секунду вместо ожидания, дважды подряд.
    """
    source = module.__doc__ or ""
    assert "GITHUB_RUN_ID" not in source
    parser_source = __import__("inspect").getsource(module.main)
    assert "GITHUB_RUN_ID" not in parser_source, "номер прогона снова берётся из окружения"
    assert "summarised_run(" in parser_source


def test_the_gate_waits_for_the_roster_not_for_the_whole_run() -> None:
    """Ждут СОСТАВ сводимого прогона, а не его завершение.

    ЗАМЕР 11.09.2026, #199, третий заход. Прогон `ci` создан в 15:14:18 и уже
    существовал, а джобов в нём не было ни одного — первый стартовал в
    15:14:55. Гейт опросил голову в 15:14:22, увидел пустой список джобов и
    только отменённые записи прежних заходов — и вынес «все записи отменены»
    за одиннадцать секунд.

    Ждать при этом ЗАВЕРШЕНИЯ нельзя: так совещательная проверка начинает
    задерживать вердикт, то есть становится обязательной обходным путём (051).
    Нашёл внешний взгляд на #199. Состава довольно — дальше каждое имя ждут
    отдельно, и совещательное не ждут вовсе.

    Отменённый прогон вердикта не несёт: следом идёт новый заход (179).
    """
    live = module.Roster(read=True, named=2, running={"lint": "queued"})
    empty = module.Roster(read=True, named=0, running={})
    assert not module.ready_to_judge(None, live)
    assert not module.ready_to_judge({"status": "queued", "conclusion": None}, empty)
    assert not module.ready_to_judge({"status": "completed", "conclusion": "cancelled"}, live)
    assert module.ready_to_judge({"status": "queued", "conclusion": None}, live)
    assert module.ready_to_judge({"status": "in_progress", "conclusion": None}, live)
    assert module.ready_to_judge({"status": "completed", "conclusion": "success"}, live)
    assert module.was_cancelled({"status": "completed", "conclusion": "cancelled"})
    assert not module.was_cancelled({"status": "completed", "conclusion": "failure"})


def test_an_advisory_check_never_delays_the_verdict() -> None:
    """Совещательная проверка вердикта не держит — ни красным, ни ожиданием.

    `.pipeline.yml` объявляет `test-next` совещательным: «слияния не держит».
    Ожидание всего прогона `ci` делало его задерживающим на КАЖДОМ изменении —
    обязательным обходным путём. Здесь предмет прямой: незавершённая
    совещательная запись не поднимает флаг ожидания.
    """
    runs = [run("lint"), run("test"), run("test-next", status="in_progress", conclusion=None)]
    problems, waiting = module.verdict(runs, REQUIRED, "ci-complete", "1")
    assert problems == [] and waiting is False, (problems, waiting)
    advisory, _ = module.verdict(runs, ["test-next"], "ci-complete", "1", strict_missing=False)
    assert advisory == [], advisory


def test_a_finished_run_is_not_an_unnamed_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Прогон, у которого ВСЕ джобы завершились, состав назвал — и вердикт идёт.

    Список едущих джобов у такого прогона пуст ВСЕГДА, и по нему одному он
    неотличим от «прогон ещё ничего не назвал». Ожидание на этом висело бы до
    тайм-аута и кончалось ложным красным на здоровом прогоне. Нашёл внешний
    взгляд на #203.
    """
    done = {"jobs": [{"name": "lint", "status": "completed", "conclusion": "success"}]}
    monkeypatch.setattr(module.ghrest, "request", lambda *_, **__: done)
    roster = module.roster_of("o/r", "7", "token")
    assert roster.read and roster.named == 1 and roster.running == {}
    assert module.ready_to_judge({"status": "completed", "conclusion": "success"}, roster)


def test_an_unread_roster_never_holds_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не прочитанный список — не пустой: гейт идёт прежней строгостью.

    Отказ транспорта означает «различить нечем» и возврат к строгости (045).
    Сведённый к «состав ещё не назван», он повесил бы гейт до тайм-аута — то
    есть поменял бы строгость на ложное красное.
    """

    def silent(*_: object, **__: object) -> object:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.ghrest, "request", silent)
    roster = module.roster_of("o/r", "7", "token")
    assert roster.read is False and roster.named == 0
    assert module.ready_to_judge({"status": "in_progress", "conclusion": None}, roster)


def test_the_verdict_shows_every_record_it_weighed() -> None:
    """Вердикт печатает ВСЕ записи имени, а не выбранную из них.

    Выбор между записями и есть то, что разбирают, когда красное оказывается о
    гонке: показать один итог значило бы скрыть предмет разбора. Замер
    12.09.2026 — три захода подряд вынесли решённое красное за полминуты при
    сроке 900, и разобрать их было нечем: логи прогона читаются не из всякого
    окна (#261).
    """
    runs = [
        {
            "name": "test",
            "status": "completed",
            "conclusion": "cancelled",
            "started_at": "2026-09-12T19:49:17Z",
            "id": 1,
        },
        {
            "name": "test",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-09-12T19:51:02Z",
            "id": 2,
        },
    ]
    said = module.judged_on(runs, ["test"], {})
    assert len(said) == 1
    assert "cancelled" in said[0], "отменённая запись скрыта — именно её и разбирают"
    assert "success" in said[0]


def test_a_name_without_records_says_so_rather_than_vanishing() -> None:
    """Имя без записей печатается словами, а не пропадает из вывода.

    Пропажа записи — самый частый предмет отказа этого гейта, и увидеть её надо
    прямо в состоянии, а не выводить из того, что строки нет
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    said = module.judged_on([], ["lint"], {})
    assert said == ["  lint: записей нет; в сводимом прогоне: нет"]


def test_the_state_says_which_jobs_are_still_running() -> None:
    """Состав едущих джобов — часть состояния: им объясняется ожидание.

    «Записей нет» и «джоб ещё едет» снаружи одинаковы, а решается ими разное
    (097).
    """
    said = module.judged_on([], ["lint"], {"lint": "in_progress"})
    assert "в сводимом прогоне: in_progress" in said[0]


def verdict_of(
    runs: list[dict[str, Any]], names: list[str], *, mine: dict[str, str], run_live: bool
) -> tuple[list[str], bool]:
    """Вердикт по подделанному состоянию головы — без сети и без прогона."""
    problems, waiting = module.verdict(runs, names, "ci-complete", "", mine=mine, run_live=run_live)
    return list(problems), bool(waiting)


def test_a_name_missing_from_a_live_run_waits_rather_than_refuses() -> None:
    """Имя, которого нет в списке джобов ИДУЩЕГО прогона, ждут, а не отвергают.

    Замер 12.09.2026, изменение #267: третий заход `ci` шёл вторую секунду,
    семь его джобов уже дали `success`, а `test-matrix` и агрегат `test` не
    значились в списке джобов вовсе — матрица ещё не развернулась. У `test` на
    голове лежали две записи, обе отменённые прежними заходами, и гейт объявил
    «все записи отменены» при живом прогоне, который через минуту стал зелёным.
    """
    runs = [
        {
            "name": "test",
            "status": "completed",
            "conclusion": "cancelled",
            "started_at": "2026-09-12T22:11:32Z",
        }
    ]
    problems, waiting = verdict_of(runs, ["test"], mine={}, run_live=True)
    assert waiting, "живой прогон не дождались"
    assert not problems, problems


def test_a_finished_run_missing_a_name_is_still_a_refusal() -> None:
    """Обратная сторона: прогон ЗАВЕРШЁН, а имени нет — это отказ (075).

    Без этого случая послабление стало бы дырой: «ждём» по всякому имени,
    которого нет, зеленило бы гейт на прогоне, где обязательная проверка не
    создалась вовсе (097).
    """
    problems, waiting = verdict_of([], ["test"], mine={}, run_live=False)
    assert not waiting
    assert problems and "test" in problems[0]


def test_a_cancelled_only_name_refuses_once_the_run_is_done() -> None:
    """Все записи отменены и прогон завершён — отказ остаётся отказом."""
    runs = [
        {
            "name": "test",
            "status": "completed",
            "conclusion": "cancelled",
            "started_at": "2026-09-12T22:11:32Z",
        }
    ]
    problems, waiting = verdict_of(runs, ["test"], mine={}, run_live=False)
    assert not waiting
    assert problems and "отменены" in problems[0]


def annotation_line() -> str:
    """Строка прогона, готовящая вывод к аннотации площадки."""
    document = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci-complete.yml").read_text(encoding="utf-8")
    )
    said = str(document["jobs"]["ci-complete"]["steps"][-1]["run"])
    found = [line for line in said.splitlines() if "sed -z" in line]
    if len(found) != 1:
        raise AssertionError(
            f"строка подготовки аннотации найдена {len(found)} раз — читать нечего"
        )
    return found[0]


def test_the_annotation_escapes_the_percent_first() -> None:
    """Знак процента экранируется ПЕРВЫМ, иначе экранирование съедает себя.

    Обратный порядок превращает подставленный `%0A` в `%250A`, а знак процента,
    пришедший из вывода, обрезает сообщение — то самое, ради читаемости
    которого аннотация и заведена. Нашёл внешний взгляд на #265.
    """
    said = annotation_line()
    where = {mark: said.find(mark) for mark in ("s/%/%25/g", "s/\\n/%0A/g")}
    assert all(place != -1 for place in where.values()), f"замены не на месте: {where}"
    assert where["s/%/%25/g"] < where["s/\\n/%0A/g"], "процент экранируется не первым"


def test_a_deadline_on_the_waiting_path_still_explains_itself(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Срок вышел, а сводимый прогон так и не появился — причина названа.

    Выход по сроку с пути ожидания не доходит до опроса записей, и печать
    состояния падала `UnboundLocalError`: вместо названной причины «прогон не
    найден» человек получал след падения самого гейта. Нашёл внешний взгляд
    на #265.
    """
    monkeypatch.setattr(module, "summarised_run", lambda *a, **k: None)
    monkeypatch.setattr(module, "roster_of", lambda *a, **k: module.Roster(False, 0, {}))
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    code = module.main(
        ["--repo", "o/r", "--sha", "deadbeef", "--required", "lint", "--timeout", "0"]
    )
    said = capsys.readouterr().out
    assert code == module.EXIT_RED
    assert "не найден" in said
    assert "вердикт вынесен на таком состоянии" in said
    assert "lint: записей нет" in said
